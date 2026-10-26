from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import DB, AdminCtx, AnalystCtx, Paging, ViewerCtx, get_owned
from app.core.config import get_settings
from app.core.errors import AppError, FileRejected, ValidationFailed
from app.infrastructure.ai import get_suggester
from app.infrastructure.storage import get_storage
from app.modules.audit import service as audit
from app.modules.billing import service as billing
from app.modules.clients.models import ClientAccount
from app.modules.files import service
from app.modules.files.models import FileAsset
from app.modules.profiles import service as profiles_service

router = APIRouter(prefix="/files", tags=["arquivos"])


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    client_account_id: uuid.UUID
    original_filename: str
    detected_format: str
    size_bytes: int
    content_hash: str
    status: str
    uploaded_by: uuid.UUID | None
    created_at: datetime
    retention_until: datetime | None
    deleted_at: datetime | None
    duplicate_of_id: uuid.UUID | None
    read_options: dict[str, Any] | None
    structure_confirmed: bool


class FileDetail(FileOut):
    inspection: dict[str, Any] | None


class FilePage(BaseModel):
    items: list[FileOut]
    total: int


class StructureIn(BaseModel):
    sheet: str | None = Field(None, max_length=255)
    header_row: int | None = Field(None, ge=1, le=1000)
    delimiter: Literal[",", ";", "\t", "|"] | None = None
    encoding: Literal["utf-8", "utf-8-sig", "cp1252", "latin-1", "utf-16"] | None = None


class SuggestionOut(BaseModel):
    source_column: str
    target_field: str | None
    confidence: float
    rationale: str
    warnings: list[str]
    requires_confirmation: bool
    alternatives: list[str]
    source: str
    inferred_type: str | None = None
    number_style: str | None = None
    date_format: str | None = None


class MappingSuggestionsOut(BaseModel):
    provider: str
    confirmation_threshold: float
    suggestions: list[SuggestionOut]
    profile_matches: list[dict[str, Any]]


@router.post("", response_model=FileDetail, status_code=201, summary="Enviar arquivo CSV/XLSX")
def upload_file(ctx: AnalystCtx, db: DB, client_id: uuid.UUID = Form(...), file: UploadFile = File(...)):
    client = get_owned(db, ClientAccount, client_id, ctx.org_id, "Empresa")
    if client.status != "active":
        raise ValidationFailed("A empresa está desativada; reative-a para enviar arquivos.")
    billing.check_quota(db, ctx.org_id, "files")
    _, limits = billing.get_limits(db, ctx.org_id)
    max_bytes = min(get_settings().max_upload_bytes, limits.get("max_file_bytes") or get_settings().max_upload_bytes)
    try:
        asset = service.create_file(db, organization_id=ctx.org_id, client_id=client.id, user_id=ctx.user.id,
                                    filename=file.filename or "arquivo", stream=file.file, max_bytes=max_bytes)
    except AppError as exc:
        audit.record_ctx(db, ctx, "file.rejected", "file_asset", None,
                         {"code": exc.code, "client_id": str(client.id), "filename": service.sanitize_filename(file.filename)})
        db.commit()
        raise
    billing.record_usage(db, ctx.org_id, "files", 1, "file_asset", asset.id)
    audit.record_ctx(db, ctx, "file.uploaded", "file_asset", asset.id,
                     {"client_id": str(client.id), "format": asset.detected_format, "size_bytes": asset.size_bytes,
                      "sha256": asset.content_hash})
    db.commit()
    return asset


@router.get("", response_model=FilePage, summary="Listar arquivos")
def list_files(ctx: ViewerCtx, db: DB, page: Paging, client_id: uuid.UUID | None = None,
               q: str | None = Query(None, max_length=100), include_deleted: bool = False):
    stmt = select(FileAsset).where(FileAsset.organization_id == ctx.org_id)
    if client_id:
        stmt = stmt.where(FileAsset.client_account_id == client_id)
    if q:
        stmt = stmt.where(FileAsset.original_filename.ilike(f"%{q.strip()}%"))
    if not include_deleted:
        stmt = stmt.where(FileAsset.status != "deleted")
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(FileAsset.created_at.desc()).limit(page.limit).offset(page.offset)).all()
    return FilePage(items=items, total=total)


@router.get("/{file_id}", response_model=FileDetail, summary="Consultar arquivo e inspeção estrutural")
def get_file(file_id: uuid.UUID, ctx: ViewerCtx, db: DB):
    return get_owned(db, FileAsset, file_id, ctx.org_id, "Arquivo")


@router.get("/{file_id}/profile", summary="Inspecionar estrutura com outras opções (sem salvar)")
def preview_structure(file_id: uuid.UUID, ctx: ViewerCtx, db: DB, sheet: str | None = Query(None, max_length=255),
                      header_row: int | None = Query(None, ge=1, le=1000),
                      delimiter: Literal[",", ";", "\t", "|"] | None = None,
                      encoding: Literal["utf-8", "utf-8-sig", "cp1252", "latin-1", "utf-16"] | None = None):
    asset = get_owned(db, FileAsset, file_id, ctx.org_id, "Arquivo")
    overrides = {"sheet": sheet, "header_row": header_row, "delimiter": delimiter, "encoding": encoding}
    if not any(overrides.values()):
        return asset.inspection
    return service.reinspect(asset, overrides).to_dict()


@router.post("/{file_id}/structure", response_model=FileDetail, summary="Confirmar aba, cabeçalho e delimitador")
def confirm_structure(file_id: uuid.UUID, body: StructureIn, ctx: AnalystCtx, db: DB):
    asset = get_owned(db, FileAsset, file_id, ctx.org_id, "Arquivo")
    report = service.reinspect(asset, body.model_dump())
    asset.inspection = report.to_dict()
    asset.read_options = report.options
    asset.structure_confirmed = True
    audit.record_ctx(db, ctx, "file.structure_confirmed", "file_asset", asset.id, {"options": report.options})
    db.commit()
    return asset


@router.post("/{file_id}/mapping", response_model=MappingSuggestionsOut, summary="Sugerir mapeamento e perfis compatíveis")
def suggest_mapping(file_id: uuid.UUID, ctx: ViewerCtx, db: DB):
    asset = get_owned(db, FileAsset, file_id, ctx.org_id, "Arquivo")
    if not asset.inspection:
        raise FileRejected("O arquivo não possui inspeção disponível (conteúdo excluído).", code="file_content_deleted")
    columns = asset.inspection["columns"]
    threshold = get_settings().mapping_confirmation_threshold
    suggester = get_suggester()
    by_name = {c["name"]: c for c in columns}
    suggestions = [
        SuggestionOut(**s.model_dump(), inferred_type=by_name[s.source_column].get("inferred_type"),
                      number_style=by_name[s.source_column].get("number_style"),
                      date_format=by_name[s.source_column].get("date_format"))
        for s in suggester.suggest(columns, threshold)
    ]
    matches = profiles_service.match_profiles(db, ctx.org_id, asset)
    return MappingSuggestionsOut(provider=suggester.name, confirmation_threshold=threshold, suggestions=suggestions,
                                 profile_matches=matches)


@router.get("/{file_id}/download", summary="Baixar arquivo original (autorizado)")
def download_file(file_id: uuid.UUID, ctx: ViewerCtx, db: DB):
    asset = get_owned(db, FileAsset, file_id, ctx.org_id, "Arquivo")
    if asset.status == "deleted" or not asset.storage_key:
        raise FileRejected("O conteúdo deste arquivo foi excluído.", code="file_content_deleted")
    audit.record_ctx(db, ctx, "file.downloaded", "file_asset", asset.id)
    db.commit()
    media = "text/csv" if asset.detected_format == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(asset.original_filename)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    return StreamingResponse(get_storage().open_stream(asset.storage_key), media_type=media, headers=headers)


@router.delete("/{file_id}", status_code=204, summary="Excluir conteúdo do arquivo (mantém histórico)")
def delete_file(file_id: uuid.UUID, ctx: AdminCtx, db: DB):
    asset = get_owned(db, FileAsset, file_id, ctx.org_id, "Arquivo")
    if asset.status == "deleted":
        return
    service.delete_content(asset)
    audit.record_ctx(db, ctx, "file.deleted", "file_asset", asset.id, {"sha256": asset.content_hash})
    db.commit()
