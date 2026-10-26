"""Fila de jobs persistida no PostgreSQL (SELECT ... FOR UPDATE SKIP LOCKED).

Escolhida no MVP em vez de Celery/Redis: menos infraestrutura, jobs sobrevivem a
reinícios e o estado fica consultável. Execução é idempotente: cada tentativa
apaga os resultados parciais da anterior antes de recomeçar.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import job_id_var
from app.infrastructure.database.base import as_utc
from app.infrastructure.database.session import session_factory

log = logging.getLogger(__name__)


class JobTimeout(Exception):
    pass


class ConfigError(AppError):
    """Erro de configuração (perfil, regra, mapeamento) — não retentável."""

    code = "config_error"


def claim_next(db: Session, model: Any, worker_id: str) -> uuid.UUID | None:
    now = datetime.now(UTC)
    stmt = (select(model).where(model.status == "queued", or_(model.run_after.is_(None), model.run_after <= now))
            .order_by(model.created_at).limit(1).with_for_update(skip_locked=True))
    job = db.scalars(stmt).first()
    if job is None:
        return None
    _mark_running(job, worker_id)
    db.commit()
    return job.id


def _mark_running(job: Any, worker_id: str) -> None:
    now = datetime.now(UTC)
    job.status = "running"
    job.attempts += 1
    job.started_at = now
    job.finished_at = None
    job.locked_by = worker_id
    job.locked_at = now
    job.error_kind = None
    job.failure_reason = None


def claim_specific(db: Session, model: Any, job_id: uuid.UUID, worker_id: str) -> bool:
    job = db.scalars(select(model).where(model.id == job_id, model.status == "queued").with_for_update(skip_locked=True)).first()
    if job is None:
        return False
    _mark_running(job, worker_id)
    db.commit()
    return True


def recover_stale(db: Session, model: Any) -> int:
    """Jobs 'running' cujo worker morreu: reenfileira (se houver tentativas) ou marca falha."""
    s = get_settings()
    limit = datetime.now(UTC) - timedelta(seconds=s.job_lock_timeout_seconds)
    count = 0
    for job in db.scalars(select(model).where(model.status == "running").with_for_update(skip_locked=True)):
        if as_utc(job.locked_at) and as_utc(job.locked_at) < limit:
            if job.attempts < job.max_attempts:
                job.status, job.run_after = "queued", None
            else:
                job.status, job.error_kind = "failed", "infrastructure_error"
                job.failure_reason = "Execução interrompida (worker não respondeu)."
                job.finished_at = datetime.now(UTC)
            count += 1
    db.commit()
    return count


def run_claimed(model: Any, job_id: uuid.UUID, executor: Callable[[Session, Any], None],
                cleanup: Callable[[Session, uuid.UUID], None] | None = None) -> None:
    """Executa um job já marcado como 'running', classificando falhas."""
    token = job_id_var.set(str(job_id))
    db = session_factory()()
    try:
        job = db.get(model, job_id)
        try:
            executor(db, job)
            db.commit()
            log.info("job.succeeded", extra={"kind": model.__tablename__})
            return
        except AppError as exc:
            db.rollback()
            kind = "config_error" if isinstance(exc, ConfigError) else "file_error"
            _fail(db, model, job_id, kind, exc.message, retry=False, cleanup=cleanup)
        except JobTimeout:
            db.rollback()
            _fail(db, model, job_id, "timeout", "Tempo máximo de execução excedido.", retry=False, cleanup=cleanup)
        except Exception:
            db.rollback()
            log.exception("job.infrastructure_error", extra={"kind": model.__tablename__})
            _fail(db, model, job_id, "infrastructure_error", "Falha técnica durante o processamento.", retry=True, cleanup=cleanup)
    finally:
        db.close()
        job_id_var.reset(token)


def _fail(db: Session, model: Any, job_id: uuid.UUID, kind: str, reason: str, retry: bool,
          cleanup: Callable[[Session, uuid.UUID], None] | None = None) -> None:
    job = db.get(model, job_id)
    if job is None:
        return
    if retry and job.attempts < job.max_attempts:
        job.status = "queued"
        job.run_after = datetime.now(UTC) + timedelta(seconds=30 * 2 ** (job.attempts - 1))
        job.error_kind, job.failure_reason = kind, f"{reason} Nova tentativa agendada."
    else:
        job.status = "failed"
        job.error_kind, job.failure_reason = kind, reason
        job.finished_at = datetime.now(UTC)
        if cleanup is not None:
            cleanup(db, job_id)  # resultados parciais não devem parecer completos
    job.locked_by = None
    db.commit()
    log.warning("job.failed", extra={"kind": model.__tablename__, "error_kind": kind, "will_retry": job.status == "queued"})
