from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import DB, AnalystCtx, Paging, ViewerCtx, get_owned
from app.core.config import get_settings
from app.core.errors import NotFound, ValidationFailed
from app.domain.comparison.engine import ComparisonConfig
from app.infrastructure.database.session import session_factory
from app.modules.audit import service as audit
from app.modules.billing import service as billing
from app.modules.comparison import service
from app.modules.comparison.models import ComparisonJob, ComparisonResult
from app.modules.files.models import FileAsset
from app.modules.processing import queue
from app.modules.reports.export import csv_stream

router = APIRouter(prefix="/comparisons", tags=["comparações"])

CATEGORY_LABELS = {
    "match": "Correspondente sem divergência", "mismatch": "Correspondente com divergência", "only_a": "Somente no arquivo A",
    "only_b": "Somente no arquivo B", "duplicate_key_a": "Chave duplicada no arquivo A", "duplicate_key_b": "Chave duplicada no arquivo B",
    "missing_key_a": "Sem chave no arquivo A", "missing_key_b": "Sem chave no arquivo B",
}


class ComparisonIn(BaseModel):
    name: str | None = Field(None, max_length=200)
    file_a_id: uuid.UUID
    file_b_id: uuid.UUID
    config: ComparisonConfig


class SuggestIn(BaseModel):
    file_a_id: uuid.UUID
    file_b_id: uuid.UUID


class ComparisonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str | None
    client_account_id: uuid.UUID
    file_a_id: uuid.UUID
    file_b_id: uuid.UUID
    config: dict[str, Any]
    status: str
    error_kind: str | None
    failure_reason: str | None
    attempts: int
    summary: dict[str, Any] | None
    input_snapshot: dict[str, Any] | None
    results_stored: int
    results_truncated: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ComparisonPage(BaseModel):
    items: list[ComparisonOut]
    total: int


class ResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    key_value: str | None
    row_a: int | None
    row_b: int | None
    differences: list[dict[str, Any]]
    note: str | None


class ResultPage(BaseModel):
    items: list[ResultOut]
    total: int


def _get(db, cid: uuid.UUID, org_id: uuid.UUID) -> ComparisonJob:
    c = db.get(ComparisonJob, cid)
    if c is None or c.organization_id != org_id:
        raise NotFound("Comparação não encontrada.")
    return c


def run_comparison_now(cid: uuid.UUID) -> None:
    db = session_factory()()
    try:
        claimed = queue.claim_specific(db, ComparisonJob, cid, "inline")
    finally:
        db.close()
    if claimed:
        queue.run_claimed(ComparisonJob, cid, service.execute_comparison, service.cleanup)


@router.post("/suggest", summary="Sugerir chave e campos a comparar")
def suggest(body: SuggestIn, ctx: ViewerCtx, db: DB):
    a = get_owned(db, FileAsset, body.file_a_id, ctx.org_id, "Arquivo")
    b = get_owned(db, FileAsset, body.file_b_id, ctx.org_id, "Arquivo")
    return service.suggest_config(a, b)


@router.post("", response_model=ComparisonOut, status_code=201, summary="Comparar dois arquivos")
def create_comparison(body: ComparisonIn, ctx: AnalystCtx, db: DB,
                      idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=100)):
    if idempotency_key:
        existing = db.scalar(select(ComparisonJob).where(ComparisonJob.organization_id == ctx.org_id,
                                                         ComparisonJob.idempotency_key == idempotency_key))
        if existing:
            return existing
    a = get_owned(db, FileAsset, body.file_a_id, ctx.org_id, "Arquivo")
    b = get_owned(db, FileAsset, body.file_b_id, ctx.org_id, "Arquivo")
    if a.id == b.id:
        raise ValidationFailed("Selecione dois arquivos diferentes.")
    service.validate_config(body.config, a, b)
    billing.check_quota(db, ctx.org_id, "comparisons")
    s = get_settings()
    job = ComparisonJob(
        organization_id=ctx.org_id, client_account_id=a.client_account_id, name=body.name, file_a_id=a.id, file_b_id=b.id,
        config=body.config.model_dump(mode="json"), status="queued", max_attempts=s.job_max_attempts,
        idempotency_key=idempotency_key, created_by=ctx.user.id,
        input_snapshot={side: {"file_id": str(f.id), "file_name": f.original_filename, "sha256": f.content_hash,
                               "read_options": f.read_options} for side, f in (("a", a), ("b", b))})
    db.add(job)
    db.flush()
    billing.record_usage(db, ctx.org_id, "comparisons", 1, "comparison_job", job.id)
    audit.record_ctx(db, ctx, "comparison.created", "comparison_job", job.id, {"file_a_id": str(a.id), "file_b_id": str(b.id)})
    db.commit()
    if a.size_bytes + b.size_bytes <= s.job_inline_max_bytes:
        run_comparison_now(job.id)
        db.expire_all()
        job = db.get(ComparisonJob, job.id)
    return job


@router.get("", response_model=ComparisonPage, summary="Listar comparações")
def list_comparisons(ctx: ViewerCtx, db: DB, page: Paging, client_id: uuid.UUID | None = None):
    stmt = select(ComparisonJob).where(ComparisonJob.organization_id == ctx.org_id)
    if client_id:
        stmt = stmt.where(ComparisonJob.client_account_id == client_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(ComparisonJob.created_at.desc()).limit(page.limit).offset(page.offset)).all()
    return ComparisonPage(items=items, total=total)


@router.get("/{comparison_id}", response_model=ComparisonOut, summary="Consultar comparação")
def get_comparison(comparison_id: uuid.UUID, ctx: ViewerCtx, db: DB):
    return _get(db, comparison_id, ctx.org_id)


@router.get("/{comparison_id}/results", response_model=ResultPage, summary="Divergências e classificações")
def list_results(comparison_id: uuid.UUID, ctx: ViewerCtx, db: DB, page: Paging,
                 category: Literal["mismatch", "only_a", "only_b", "duplicate_key_a", "duplicate_key_b", "missing_key_a",
                                   "missing_key_b"] | None = None):
    c = _get(db, comparison_id, ctx.org_id)
    stmt = select(ComparisonResult).where(ComparisonResult.comparison_id == c.id)
    if category:
        stmt = stmt.where(ComparisonResult.category == category)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(ComparisonResult.id).limit(page.limit).offset(page.offset)).all()
    return ResultPage(items=items, total=total)


@router.get("/{comparison_id}/export.csv", summary="Exportar relatório de divergências em CSV")
def export_results(comparison_id: uuid.UUID, ctx: ViewerCtx, db: DB):
    c = _get(db, comparison_id, ctx.org_id)
    audit.record_ctx(db, ctx, "report.exported", "comparison_job", c.id, {"format": "csv", "kind": "comparison"})
    db.commit()
    results = db.scalars(select(ComparisonResult).where(ComparisonResult.comparison_id == c.id).order_by(ComparisonResult.id)).all()
    snap = c.input_snapshot or {}
    header = ["comparacao", "arquivo_a", "sha256_a", "arquivo_b", "sha256_b", "categoria", "descricao", "chave", "linha_a",
              "linha_b", "campo_a", "campo_b", "valor_a", "valor_b", "diferenca", "motivo", "observacao"]
    base = [str(c.id), snap.get("a", {}).get("file_name"), snap.get("a", {}).get("sha256"), snap.get("b", {}).get("file_name"),
            snap.get("b", {}).get("sha256")]

    def rows():
        for r in results:
            label = CATEGORY_LABELS.get(r.category, r.category)
            if r.differences:
                for d in r.differences:
                    yield [*base, r.category, label, r.key_value, r.row_a, r.row_b, d.get("column_a"), d.get("column_b"),
                           d.get("value_a"), d.get("value_b"), d.get("delta") or d.get("delta_days"), d.get("reason"), r.note]
            else:
                yield [*base, r.category, label, r.key_value, r.row_a, r.row_b, None, None, None, None, None, None, r.note]

    return StreamingResponse(csv_stream(header, rows()), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="comparacao_{c.id}.csv"', "Cache-Control": "no-store"})
