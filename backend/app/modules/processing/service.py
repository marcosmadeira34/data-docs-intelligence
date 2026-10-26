"""Criação e execução de processamentos (validação de um arquivo com um perfil)."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, LimitExceeded, NotFound, ValidationFailed
from app.domain.canonical_fields import field_type
from app.domain.ingestion.readers import iter_records
from app.domain.mapping.entries import RecordBuilder
from app.domain.validation.engine import Finding, RuleSpec, ValidationEngine
from app.domain.validation.rules import RuleContext, normalize_reference
from app.domain.values import is_blank
from app.modules.billing import service as billing
from app.modules.files import service as files_service
from app.modules.files.models import FileAsset
from app.modules.processing.models import ProcessingJob, ValidationFinding
from app.modules.processing.queue import ConfigError, JobTimeout
from app.modules.profiles import service as profiles_service
from app.modules.profiles.models import DatasetProfile, DatasetProfileVersion
from app.modules.validation import service as rules_service

FINDING_BATCH = 1000
PROGRESS_EVERY = 5000
MAX_REFERENCE_VALUES = 1_000_000


def implicit_specs(entries, auto_type_checks: bool) -> list[RuleSpec]:
    """Regras derivadas do mapeamento aprovado (campos obrigatórios e tipos)."""
    specs = []
    for e in entries:
        if not e.target_field or e.status == "ignored":
            continue
        if e.required:
            specs.append(RuleSpec(rule_key=f"system.required.{e.target_field}", rule_type="required",
                                  params={"field": e.target_field}, severity="error", name=f"Obrigatório: {e.target_field}"))
        ftype = field_type(e.target_field)
        if auto_type_checks and ftype in ("decimal", "integer", "date"):
            specs.append(RuleSpec(rule_key=f"system.type.{e.target_field}", rule_type="data_type",
                                  params={"field": e.target_field, "type": ftype}, severity="error",
                                  name=f"Tipo: {e.target_field}"))
    return specs


def _spec_dict(s: RuleSpec) -> dict[str, Any]:
    return {"rule_key": s.rule_key, "rule_type": s.rule_type, "params": s.params, "severity": s.severity, "name": s.name,
            "version": s.version, "rule_id": s.rule_id, "applies_when": s.applies_when, "message": s.message}


def create_job(db: Session, ctx, *, file: FileAsset, profile: DatasetProfile, rule_ids: list[uuid.UUID] | None,
               auto_type_checks: bool, idempotency_key: str | None, reprocess_of: uuid.UUID | None = None) -> tuple[ProcessingJob, bool]:
    """Cria o job (status 'queued'). Retorna (job, criado_agora)."""
    if idempotency_key:
        existing = db.scalar(select(ProcessingJob).where(ProcessingJob.organization_id == ctx.org_id,
                                                         ProcessingJob.idempotency_key == idempotency_key))
        if existing:
            return existing, False
    if file.status == "deleted":
        raise ValidationFailed("O conteúdo do arquivo foi excluído e não pode ser processado.")
    if profile.status != "active" or not profile.current_version_id:
        raise ValidationFailed("O perfil não está ativo ou não possui versão aprovada.")
    if profile.client_account_id and profile.client_account_id != file.client_account_id:
        raise ValidationFailed("O perfil pertence a outra empresa.")
    version = db.get(DatasetProfileVersion, profile.current_version_id)
    compat = profiles_service.compatibility(version, file)
    if compat["requires_review"]:
        raise Conflict("A estrutura do arquivo mudou em relação ao perfil aprovado. Revise o mapeamento e crie uma nova versão.",
                       details=compat, code="structure_review_required")
    s = get_settings()
    active = db.scalar(select(func.count()).select_from(ProcessingJob).where(
        ProcessingJob.organization_id == ctx.org_id, ProcessingJob.status.in_(("queued", "running")))) or 0
    if active >= s.max_concurrent_jobs_per_org:
        raise LimitExceeded("Há execuções demais em andamento. Aguarde a conclusão das atuais.", code="concurrency_limit")
    billing.check_quota(db, ctx.org_id, "jobs")
    billing.check_quota(db, ctx.org_id, "records", increment=max(1, (file.inspection or {}).get("row_count", 1)))

    entries = profiles_service.entries_of(version)
    rules = rules_service.applicable_rules(db, ctx.org_id, file.client_account_id, profile.id, rule_ids)
    specs = implicit_specs(entries, auto_type_checks) + [rules_service.to_spec(r) for r in rules]
    job = ProcessingJob(
        organization_id=ctx.org_id, client_account_id=file.client_account_id, file_asset_id=file.id,
        profile_version_id=version.id, status="queued", max_attempts=s.job_max_attempts, idempotency_key=idempotency_key,
        reprocess_of_id=reprocess_of, created_by=ctx.user.id,
        parameters={"rule_ids": [str(i) for i in rule_ids] if rule_ids is not None else None, "auto_type_checks": auto_type_checks,
                    "profile_id": str(profile.id)},
        rules_snapshot=[_spec_dict(sp) for sp in specs],
        input_snapshot={
            "file_id": str(file.id), "file_name": file.original_filename, "sha256": file.content_hash,
            "size_bytes": file.size_bytes, "format": file.detected_format, "read_options": file.read_options,
            "profile_id": str(profile.id), "profile_name": profile.name, "profile_version_id": str(version.id),
            "profile_version": version.version, "mapping": version.mapping.entries if version.mapping else [],
            "compatibility": compat["status"],
        },
    )
    db.add(job)
    db.flush()
    billing.record_usage(db, ctx.org_id, "jobs", 1, "processing_job", job.id)
    return job, True


def _load_reference_sets(db: Session, job: ProcessingJob, specs: list[RuleSpec]) -> dict[str, set[str]]:
    sets: dict[str, set[str]] = {}
    for spec in specs:
        if spec.rule_type != "cross_file":
            continue
        p = spec.params
        try:
            ref = db.get(FileAsset, uuid.UUID(p["reference_file_id"]))
        except (ValueError, KeyError) as exc:
            raise ConfigError("Regra entre arquivos com arquivo de referência inválido.") from exc
        if ref is None or ref.organization_id != job.organization_id:
            raise ConfigError("Arquivo de referência da regra não encontrado.")
        values: set[str] = set()
        with files_service.local_file(ref) as path:
            cols, rows = iter_records(path, files_service.resolved_options(path, ref))
            if p["reference_column"] not in cols:
                raise ConfigError(f"A coluna '{p['reference_column']}' não existe no arquivo de referência.")
            idx = cols.index(p["reference_column"])
            for _, row in rows:
                v = row[idx] if idx < len(row) else None
                if not is_blank(v):
                    values.add(normalize_reference(v, p.get("normalize", ["trim", "upper"])))
                if len(values) > MAX_REFERENCE_VALUES:
                    raise ConfigError("O arquivo de referência excede o limite de valores distintos.")
        sets[spec.rule_key] = values
    return sets


def execute_job(db: Session, job: ProcessingJob) -> None:
    """Executa a validação. Idempotente: remove achados de tentativas anteriores."""
    s = get_settings()
    started = time.monotonic()
    db.execute(delete(ValidationFinding).where(ValidationFinding.job_id == job.id))
    file = db.get(FileAsset, job.file_asset_id)
    version = db.get(DatasetProfileVersion, job.profile_version_id)
    if file is None or version is None:
        raise ConfigError("Arquivo ou versão de perfil não encontrados.")
    entries = profiles_service.entries_of(version)
    specs = [RuleSpec(**sp) for sp in job.rules_snapshot or []]
    ctx = RuleContext(reference_sets=_load_reference_sets(db, job, specs))
    names = {sp.rule_key: sp.name for sp in specs}
    buffer: list[dict[str, Any]] = []

    def flush() -> None:
        if buffer:
            db.execute(insert(ValidationFinding), buffer)
            buffer.clear()

    def sink(f: Finding) -> None:
        buffer.append({
            "job_id": job.id, "organization_id": job.organization_id,
            "rule_id": uuid.UUID(f.rule_id) if f.rule_id else None, "rule_key": f.rule_key, "rule_version": f.rule_version,
            "rule_type": f.rule_type, "rule_name": (names.get(f.rule_key) or "")[:200] or None, "severity": f.severity,
            "row_number": f.row_number, "record_key": f.record_key, "field": f.field, "observed_value": f.observed_value,
            "message": f.message[:500], "evidence": f.evidence, "review_status": "open",
        })
        if len(buffer) >= FINDING_BATCH:
            flush()

    with files_service.local_file(file) as path:
        columns, rows = iter_records(path, files_service.resolved_options(path, file))
        builder = RecordBuilder(columns, entries)
        if builder.missing_columns:
            raise ConfigError("Colunas mapeadas ausentes no arquivo: " + ", ".join(builder.missing_columns))
        engine = ValidationEngine(specs, mapped_fields=set(builder.target_fields), sink=sink, ctx=ctx,
                                  max_findings_per_rule=s.max_findings_per_rule, mask_sensitive=s.mask_sensitive_previews)
        for count, (row_number, row) in enumerate(rows, 1):
            if count > s.max_records_per_file:
                raise ValidationFailed(f"O arquivo excede o limite de {s.max_records_per_file} registros.")
            engine.process(builder.build(row_number, row))
            if count % PROGRESS_EVERY == 0:
                if time.monotonic() - started > s.job_timeout_seconds:
                    raise JobTimeout()
                flush()
                job.records_read = count
                db.commit()  # progresso visível para quem consulta
        result = engine.finish()
    flush()
    summary = result.summary()
    job.records_read = result.records
    job.error_count, job.warning_count, job.info_count = summary["errors"], summary["warnings"], summary["infos"]
    job.findings_stored = sum(r["stored"] for r in summary["rules"])
    summary["duration_seconds"] = round(time.monotonic() - started, 3)
    summary["truncated_rules"] = [r["rule_key"] for r in summary["rules"] if r["violations"] > r["stored"]]
    job.summary = summary
    job.status = "succeeded"
    job.finished_at = datetime.now(UTC)
    job.locked_by = None
    billing.record_usage(db, job.organization_id, "records", result.records, "processing_job", job.id)


def cleanup(db: Session, job_id: uuid.UUID) -> None:
    db.execute(delete(ValidationFinding).where(ValidationFinding.job_id == job_id))


def get_job(db: Session, job_id: uuid.UUID, org_id: uuid.UUID) -> ProcessingJob:
    job = db.get(ProcessingJob, job_id)
    if job is None or job.organization_id != org_id:
        raise NotFound("Execução não encontrada.")
    return job
