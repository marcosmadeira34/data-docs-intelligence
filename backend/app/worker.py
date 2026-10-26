"""Worker de processamento assíncrono.

Uso: python -m app.worker
Processa validações e comparações enfileiradas, recupera jobs travados e aplica
a política de retenção de arquivos. Pode haver várias réplicas (SKIP LOCKED).
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.database import models as _all_models  # noqa: F401  (registra todas as tabelas no metadata)
from app.infrastructure.database.session import session_factory
from app.modules.audit import service as audit
from app.modules.comparison import service as comparison_service
from app.modules.comparison.models import ComparisonJob
from app.modules.files import service as files_service
from app.modules.processing import queue
from app.modules.processing import service as processing_service
from app.modules.processing.models import ProcessingJob

log = logging.getLogger("app.worker")
QUEUES = [
    (ProcessingJob, processing_service.execute_job, processing_service.cleanup),
    (ComparisonJob, comparison_service.execute_comparison, comparison_service.cleanup),
]
_stop = False


def _handle_stop(*_):
    global _stop
    _stop = True


def run_once(worker_id: str) -> bool:
    """Processa no máximo um job de cada fila. Retorna True se algo foi executado."""
    did = False
    for model, executor, cleanup in QUEUES:
        db = session_factory()()
        try:
            job_id = queue.claim_next(db, model, worker_id)
        finally:
            db.close()
        if job_id:
            queue.run_claimed(model, job_id, executor, cleanup)
            did = True
    return did


def maintenance() -> None:
    db = session_factory()()
    try:
        for model, _, _ in QUEUES:
            recovered = queue.recover_stale(db, model)
            if recovered:
                log.warning("worker.recovered_stale", extra={"kind": model.__tablename__, "count": recovered})
        purged = files_service.purge_expired(db)
        for f in purged:
            audit.record(db, organization_id=f.organization_id, actor_user_id=None, action="file.retention_purged",
                         entity_type="file_asset", entity_id=f.id)
        if purged:
            db.commit()
            log.info("worker.retention_purged", extra={"count": len(purged)})
    finally:
        db.close()


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    log.info("worker.started", extra={"worker_id": worker_id})
    last_maintenance = 0.0
    while not _stop:
        if time.monotonic() - last_maintenance > 300:
            maintenance()
            last_maintenance = time.monotonic()
        try:
            busy = run_once(worker_id)
        except Exception:
            log.exception("worker.loop_error")
            busy = False
        if not busy:
            time.sleep(s.worker_poll_seconds)
    log.info("worker.stopped")


if __name__ == "__main__":
    main()
