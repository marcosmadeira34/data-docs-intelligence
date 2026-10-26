from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DB, AnalystCtx, Paging, ViewerCtx, get_owned
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound
from app.modules.audit import service as audit
from app.modules.files.models import FileAsset
from app.modules.processing import queue, service
from app.modules.processing.models import ProcessingJob, ValidationFinding
from app.modules.profiles.models import DatasetProfile
from app.modules.reports.export import csv_stream

router = APIRouter(prefix="/jobs", tags=["execuções"])


class JobIn(BaseModel):
    file_id: uuid.UUID
    profile_id: uuid.UUID
    rule_ids: list[uuid.UUID] | None = Field(None, max_length=200, description="Omitido = regras ativas no escopo; lista vazia = nenhuma regra além das do mapeamento")
    auto_type_checks: bool = True


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    client_account_id: uuid.UUID
    file_asset_id: uuid.UUID
    profile_version_id: uuid.UUID
    reprocess_of_id: uuid.UUID | None
    status: str
    error_kind: str | None
    failure_reason: str | None
    attempts: int
    max_attempts: int
    records_read: int
    error_count: int
    warning_count: int
    info_count: int
    findings_stored: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    created_by: uuid.UUID | None
    parameters: dict[str, Any]
    input_snapshot: dict[str, Any] | None
    summary: dict[str, Any] | None


class JobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    client_account_id: uuid.UUID
    file_asset_id: uuid.UUID
    status: str
    error_kind: str | None
    records_read: int
    error_count: int
    warning_count: int
    info_count: int
    created_at: datetime
    finished_at: datetime | None
    input_snapshot: dict[str, Any] | None


class JobPage(BaseModel):
    items: list[JobListItem]
    total: int


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_key: str
    rule_version: int
    rule_type: str
    rule_name: str | None
    severity: str
    row_number: int | None
    record_key: str | None
    field: str | None
    observed_value: str | None
    message: str
    evidence: dict[str, Any]
    review_status: str
    review_note: str | None
    reviewed_at: datetime | None


class FindingPage(BaseModel):
    items: list[FindingOut]
    total: int
    facets: dict[str, dict[str, int]]


class ReviewIn(BaseModel):
    review_status: Literal["open", "acknowledged", "resolved", "false_positive"]
    review_note: str | None = Field(None, max_length=500)


def run_job_now(job_id: uuid.UUID) -> None:
    from app.infrastructure.database.session import session_factory

    db = session_factory()()
    try:
        claimed = queue.claim_specific(db, ProcessingJob, job_id, "inline")
    finally:
        db.close()
    if claimed:
        queue.run_claimed(ProcessingJob, job_id, service.execute_job, service.cleanup)


def _maybe_inline(db: Session, job: ProcessingJob, file: FileAsset) -> ProcessingJob:
    if file.size_bytes <= get_settings().job_inline_max_bytes:
        run_job_now(job.id)
        db.expire_all()
        job = db.get(ProcessingJob, job.id)
    return job


@router.post("", response_model=JobOut, status_code=201, summary="Executar validação de um arquivo com um perfil")
def create_job(body: JobIn, ctx: AnalystCtx, db: DB,
               idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=100)):
    file = get_owned(db, FileAsset, body.file_id, ctx.org_id, "Arquivo")
    profile = get_owned(db, DatasetProfile, body.profile_id, ctx.org_id, "Perfil")
    job, created = service.create_job(db, ctx, file=file, profile=profile, rule_ids=body.rule_ids,
                                      auto_type_checks=body.auto_type_checks, idempotency_key=idempotency_key)
    if not created:
        return job
    audit.record_ctx(db, ctx, "job.created", "processing_job", job.id,
                     {"file_id": str(file.id), "profile_version_id": str(job.profile_version_id), "rules": len(job.rules_snapshot or [])})
    db.commit()
    return _maybe_inline(db, job, file)


@router.get("", response_model=JobPage, summary="Histórico de execuções")
def list_jobs(ctx: ViewerCtx, db: DB, page: Paging, client_id: uuid.UUID | None = None, file_id: uuid.UUID | None = None,
              status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None):
    stmt = select(ProcessingJob).where(ProcessingJob.organization_id == ctx.org_id)
    if client_id:
        stmt = stmt.where(ProcessingJob.client_account_id == client_id)
    if file_id:
        stmt = stmt.where(ProcessingJob.file_asset_id == file_id)
    if status:
        stmt = stmt.where(ProcessingJob.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(ProcessingJob.created_at.desc()).limit(page.limit).offset(page.offset)).all()
    return JobPage(items=items, total=total)


@router.get("/{job_id}", response_model=JobOut, summary="Consultar execução")
def get_job(job_id: uuid.UUID, ctx: ViewerCtx, db: DB):
    return service.get_job(db, job_id, ctx.org_id)


def _findings_stmt(job_id: uuid.UUID, severity, rule_key, field, review_status, q):
    stmt = select(ValidationFinding).where(ValidationFinding.job_id == job_id)
    if severity:
        stmt = stmt.where(ValidationFinding.severity == severity)
    if rule_key:
        stmt = stmt.where(ValidationFinding.rule_key == rule_key)
    if field:
        stmt = stmt.where(ValidationFinding.field == field)
    if review_status:
        stmt = stmt.where(ValidationFinding.review_status == review_status)
    if q:
        stmt = stmt.where(ValidationFinding.record_key.ilike(f"%{q.strip()}%"))
    return stmt


@router.get("/{job_id}/findings", response_model=FindingPage, summary="Inconsistências da execução (com filtros)")
def list_findings(job_id: uuid.UUID, ctx: ViewerCtx, db: DB, page: Paging,
                  severity: Literal["error", "warning", "info"] | None = None, rule_key: str | None = Query(None, max_length=80),
                  field: str | None = Query(None, max_length=64),
                  review_status: Literal["open", "acknowledged", "resolved", "false_positive"] | None = None,
                  q: str | None = Query(None, max_length=100)):
    job = service.get_job(db, job_id, ctx.org_id)
    stmt = _findings_stmt(job.id, severity, rule_key, field, review_status, q)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(ValidationFinding.row_number.is_(None), ValidationFinding.row_number, ValidationFinding.id)
                       .limit(page.limit).offset(page.offset)).all()
    facets: dict[str, dict[str, int]] = {}
    for col, name in ((ValidationFinding.severity, "severity"), (ValidationFinding.rule_key, "rule_key"),
                      (ValidationFinding.field, "field"), (ValidationFinding.review_status, "review_status")):
        rows = db.execute(select(col, func.count()).where(ValidationFinding.job_id == job.id).group_by(col)).all()
        facets[name] = {str(k): int(v) for k, v in rows if k is not None}
    return FindingPage(items=items, total=total, facets=facets)


@router.patch("/{job_id}/findings/{finding_id}", response_model=FindingOut, summary="Registrar revisão de uma inconsistência")
def review_finding(job_id: uuid.UUID, finding_id: int, body: ReviewIn, ctx: AnalystCtx, db: DB):
    job = service.get_job(db, job_id, ctx.org_id)
    f = db.get(ValidationFinding, finding_id)
    if f is None or f.job_id != job.id:
        raise NotFound("Inconsistência não encontrada.")
    f.review_status, f.review_note = body.review_status, body.review_note
    f.reviewed_by, f.reviewed_at = ctx.user.id, datetime.now(UTC)
    audit.record_ctx(db, ctx, "finding.reviewed", "validation_finding", f.id, {"job_id": str(job.id), "status": body.review_status})
    db.commit()
    return f


@router.get("/{job_id}/findings/export.csv", summary="Exportar inconsistências em CSV")
def export_findings(job_id: uuid.UUID, ctx: ViewerCtx, db: DB, severity: Literal["error", "warning", "info"] | None = None,
                    rule_key: str | None = Query(None, max_length=80), field: str | None = Query(None, max_length=64)):
    job = service.get_job(db, job_id, ctx.org_id)
    audit.record_ctx(db, ctx, "report.exported", "processing_job", job.id, {"format": "csv", "kind": "findings"})
    db.commit()
    stmt = _findings_stmt(job.id, severity, rule_key, field, None, None).order_by(ValidationFinding.row_number, ValidationFinding.id)
    header = ["execucao", "arquivo", "sha256", "linha", "chave_registro", "severidade", "regra", "nome_regra", "versao_regra",
              "campo", "valor_observado", "mensagem", "status_revisao", "evidencia"]
    snap = job.input_snapshot or {}

    # Materializado antes do streaming: a sessão do request é fechada antes do envio do corpo.
    findings = db.scalars(stmt).all()

    def rows():
        for f in findings:
            yield [str(job.id), snap.get("file_name"), snap.get("sha256"), f.row_number, f.record_key, f.severity, f.rule_key,
                   f.rule_name, f.rule_version, f.field, f.observed_value, f.message, f.review_status, f.evidence]

    return StreamingResponse(csv_stream(header, rows()), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="inconsistencias_{job.id}.csv"', "Cache-Control": "no-store"})


@router.get("/{job_id}/report", summary="Relatório da execução com evidências de reprodutibilidade")
def job_report(job_id: uuid.UUID, ctx: ViewerCtx, db: DB):
    job = service.get_job(db, job_id, ctx.org_id)
    by_rule = db.execute(select(ValidationFinding.rule_key, ValidationFinding.severity, func.count())
                         .where(ValidationFinding.job_id == job.id).group_by(ValidationFinding.rule_key, ValidationFinding.severity)).all()
    return {
        "job_id": str(job.id), "status": job.status, "error_kind": job.error_kind, "failure_reason": job.failure_reason,
        "organization_id": str(job.organization_id), "client_account_id": str(job.client_account_id),
        "created_at": job.created_at, "started_at": job.started_at, "finished_at": job.finished_at, "attempts": job.attempts,
        "input": job.input_snapshot, "parameters": job.parameters,
        "rules": [{k: r[k] for k in ("rule_key", "rule_type", "version", "severity", "name", "params")} for r in job.rules_snapshot or []],
        "totals": {"records": job.records_read, "errors": job.error_count, "warnings": job.warning_count, "infos": job.info_count,
                   "findings_stored": job.findings_stored},
        "findings_by_rule": [{"rule_key": k, "severity": s, "count": c} for k, s, c in by_rule],
        "summary": job.summary,
    }


@router.post("/{job_id}/reprocess", response_model=JobOut, status_code=201, summary="Reprocessar com o mesmo arquivo e perfil")
def reprocess(job_id: uuid.UUID, ctx: AnalystCtx, db: DB):
    old = service.get_job(db, job_id, ctx.org_id)
    if old.status in ("queued", "running"):
        raise Conflict("A execução ainda está em andamento.")
    file = get_owned(db, FileAsset, old.file_asset_id, ctx.org_id, "Arquivo")
    profile = get_owned(db, DatasetProfile, uuid.UUID(old.parameters["profile_id"]), ctx.org_id, "Perfil")
    saved = old.parameters.get("rule_ids")
    rule_ids = [uuid.UUID(i) for i in saved] if saved is not None else None
    job, _ = service.create_job(db, ctx, file=file, profile=profile, rule_ids=rule_ids,
                                auto_type_checks=old.parameters.get("auto_type_checks", True), idempotency_key=None,
                                reprocess_of=old.id)
    audit.record_ctx(db, ctx, "job.reprocessed", "processing_job", job.id, {"reprocess_of": str(old.id)})
    db.commit()
    return _maybe_inline(db, job, file)


@router.post("/{job_id}/cancel", response_model=JobOut, summary="Cancelar execução enfileirada")
def cancel(job_id: uuid.UUID, ctx: AnalystCtx, db: DB):
    job = service.get_job(db, job_id, ctx.org_id)
    if job.status != "queued":
        raise Conflict("Somente execuções enfileiradas podem ser canceladas.")
    job.status, job.finished_at = "cancelled", datetime.now(UTC)
    audit.record_ctx(db, ctx, "job.cancelled", "processing_job", job.id)
    db.commit()
    return job
