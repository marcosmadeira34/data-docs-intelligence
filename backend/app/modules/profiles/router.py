from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB, AnalystCtx, Paging, ViewerCtx, get_owned
from app.core.errors import NotFound
from app.domain.mapping.entries import MappingEntry
from app.modules.audit import service as audit
from app.modules.clients.models import ClientAccount
from app.modules.files.models import FileAsset
from app.modules.profiles import service
from app.modules.profiles.models import DatasetProfile, DatasetProfileVersion

router = APIRouter(prefix="/profiles", tags=["perfis"])


class ProfileCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(None, max_length=2000)
    client_id: uuid.UUID | None = Field(None, description="Nulo = perfil reutilizável por todas as empresas da organização")
    file_id: uuid.UUID
    entries: list[MappingEntry] = Field(min_length=1, max_length=300)
    approve: bool = True
    suggestion_source: Literal["heuristic", "ai", "manual"] = "heuristic"


class VersionCreateIn(BaseModel):
    file_id: uuid.UUID
    entries: list[MappingEntry] = Field(min_length=1, max_length=300)
    approve: bool = True
    change_note: str | None = Field(None, max_length=1000)
    suggestion_source: Literal["heuristic", "ai", "manual"] = "heuristic"


class ProfilePatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    description: str | None = Field(None, max_length=2000)
    status: Literal["active", "archived"] | None = None


class VersionOut(BaseModel):
    id: uuid.UUID
    version: int
    source_format: str
    sheet_name: str | None
    header_row: int
    delimiter: str | None
    encoding: str | None
    columns: list[dict[str, Any]]
    approval_status: str
    approved_at: datetime | None
    approved_by: uuid.UUID | None
    created_at: datetime
    change_note: str | None
    source_file_id: uuid.UUID | None
    mapping: list[dict[str, Any]]
    suggestion_source: str | None


class ProfileOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    client_account_id: uuid.UUID | None
    client_name: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    current_version: VersionOut | None
    version_count: int


class ProfileDetail(ProfileOut):
    versions: list[VersionOut]


class ProfilePage(BaseModel):
    items: list[ProfileOut]
    total: int


def _version_out(v: DatasetProfileVersion) -> VersionOut:
    return VersionOut(
        id=v.id, version=v.version, source_format=v.source_format, sheet_name=v.sheet_name, header_row=v.header_row,
        delimiter=v.delimiter, encoding=v.encoding, columns=v.columns, approval_status=v.approval_status,
        approved_at=v.approved_at, approved_by=v.approved_by, created_at=v.created_at, change_note=v.change_note,
        source_file_id=v.source_file_id, mapping=v.mapping.entries if v.mapping else [],
        suggestion_source=v.mapping.suggestion_source if v.mapping else None)


def _profile_out(db, p: DatasetProfile, detail: bool = False):
    current = db.get(DatasetProfileVersion, p.current_version_id) if p.current_version_id else None
    client = db.get(ClientAccount, p.client_account_id) if p.client_account_id else None
    data = dict(id=p.id, name=p.name, description=p.description, client_account_id=p.client_account_id,
                client_name=client.name if client else None, status=p.status, created_at=p.created_at,
                updated_at=p.updated_at, current_version=_version_out(current) if current else None,
                version_count=len(p.versions))
    if detail:
        return ProfileDetail(**data, versions=[_version_out(v) for v in sorted(p.versions, key=lambda v: -v.version)])
    return ProfileOut(**data)


@router.get("", response_model=ProfilePage, summary="Listar perfis")
def list_profiles(ctx: ViewerCtx, db: DB, page: Paging, client_id: uuid.UUID | None = None,
                  status: Literal["active", "archived"] | None = "active"):
    stmt = select(DatasetProfile).where(DatasetProfile.organization_id == ctx.org_id)
    if client_id:
        stmt = stmt.where(DatasetProfile.client_account_id == client_id)
    if status:
        stmt = stmt.where(DatasetProfile.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(DatasetProfile.name).limit(page.limit).offset(page.offset)).all()
    return ProfilePage(items=[_profile_out(db, p) for p in items], total=total)


@router.post("", response_model=ProfileDetail, status_code=201, summary="Criar perfil a partir de um arquivo e mapeamento")
def create_profile(body: ProfileCreateIn, ctx: AnalystCtx, db: DB):
    file = get_owned(db, FileAsset, body.file_id, ctx.org_id, "Arquivo")
    if body.client_id:
        get_owned(db, ClientAccount, body.client_id, ctx.org_id, "Empresa")
    profile = service.create_profile(
        db, org_id=ctx.org_id, user_id=ctx.user.id, name=body.name.strip(), description=body.description,
        client_id=body.client_id, file=file, entries=body.entries, approve=body.approve,
        suggestion_source=body.suggestion_source)
    audit.record_ctx(db, ctx, "profile.created", "dataset_profile", profile.id,
                     {"approved": body.approve, "file_id": str(file.id), "mapped": sum(1 for e in body.entries if e.target_field)})
    if body.approve:
        audit.record_ctx(db, ctx, "mapping.approved", "dataset_profile", profile.id, {"version": 1})
    db.commit()
    db.refresh(profile)
    return _profile_out(db, profile, detail=True)


@router.get("/{profile_id}", response_model=ProfileDetail, summary="Consultar perfil e versões")
def get_profile(profile_id: uuid.UUID, ctx: ViewerCtx, db: DB):
    return _profile_out(db, get_owned(db, DatasetProfile, profile_id, ctx.org_id, "Perfil"), detail=True)


@router.patch("/{profile_id}", response_model=ProfileDetail, summary="Renomear ou arquivar perfil")
def update_profile(profile_id: uuid.UUID, body: ProfilePatch, ctx: AnalystCtx, db: DB):
    p = get_owned(db, DatasetProfile, profile_id, ctx.org_id, "Perfil")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(p, k, v)
    audit.record_ctx(db, ctx, "profile.updated", "dataset_profile", p.id, {"fields": sorted(changes)})
    db.commit()
    return _profile_out(db, p, detail=True)


@router.post("/{profile_id}/versions", response_model=ProfileDetail, status_code=201, summary="Criar nova versão do perfil")
def create_version(profile_id: uuid.UUID, body: VersionCreateIn, ctx: AnalystCtx, db: DB):
    p = get_owned(db, DatasetProfile, profile_id, ctx.org_id, "Perfil")
    file = get_owned(db, FileAsset, body.file_id, ctx.org_id, "Arquivo")
    v = service.add_version(db, profile=p, user_id=ctx.user.id, file=file, entries=body.entries, approve=body.approve,
                            change_note=body.change_note, suggestion_source=body.suggestion_source)
    audit.record_ctx(db, ctx, "profile.version_created", "dataset_profile", p.id, {"version": v.version, "approved": body.approve})
    if body.approve:
        audit.record_ctx(db, ctx, "mapping.approved", "dataset_profile", p.id, {"version": v.version})
    db.commit()
    db.refresh(p)
    return _profile_out(db, p, detail=True)


@router.post("/{profile_id}/versions/{version_id}/approve", response_model=ProfileDetail, summary="Aprovar versão em rascunho")
def approve_version(profile_id: uuid.UUID, version_id: uuid.UUID, ctx: AnalystCtx, db: DB):
    p = get_owned(db, DatasetProfile, profile_id, ctx.org_id, "Perfil")
    v = db.get(DatasetProfileVersion, version_id)
    if v is None or v.profile_id != p.id:
        raise NotFound("Versão não encontrada.")
    service.approve_version(db, p, v, ctx.user.id)
    audit.record_ctx(db, ctx, "mapping.approved", "dataset_profile", p.id, {"version": v.version})
    db.commit()
    db.refresh(p)
    return _profile_out(db, p, detail=True)


@router.get("/{profile_id}/compatibility", summary="Verificar compatibilidade de um arquivo com a versão atual")
def profile_compatibility(profile_id: uuid.UUID, file_id: uuid.UUID, ctx: ViewerCtx, db: DB):
    p = get_owned(db, DatasetProfile, profile_id, ctx.org_id, "Perfil")
    file = get_owned(db, FileAsset, file_id, ctx.org_id, "Arquivo")
    if not p.current_version_id:
        raise NotFound("O perfil não possui versão aprovada.")
    return service.compatibility(db.get(DatasetProfileVersion, p.current_version_id), file)
