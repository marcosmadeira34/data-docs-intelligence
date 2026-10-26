from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, AnalystCtx, Paging, ViewerCtx, get_owned
from app.core.errors import Conflict
from app.modules.audit import service as audit
from app.modules.clients.models import ClientAccount
from app.modules.files.models import FileAsset
from app.modules.processing.models import ProcessingJob

router = APIRouter(prefix="/clients", tags=["empresas atendidas"])


class ClientIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    external_reference: str | None = Field(None, max_length=100)
    tax_id: str | None = Field(None, max_length=20)
    notes: str | None = Field(None, max_length=2000)


class ClientPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    external_reference: str | None = Field(None, max_length=100)
    tax_id: str | None = Field(None, max_length=20)
    notes: str | None = Field(None, max_length=2000)
    status: Literal["active", "inactive"] | None = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    external_reference: str | None
    tax_id: str | None
    notes: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ClientDetail(ClientOut):
    file_count: int
    job_count: int
    last_activity_at: datetime | None


class ClientPage(BaseModel):
    items: list[ClientOut]
    total: int


@router.get("", response_model=ClientPage, summary="Listar empresas atendidas")
def list_clients(ctx: ViewerCtx, db: DB, page: Paging, q: str | None = Query(None, max_length=100),
                 status: Literal["active", "inactive"] | None = None):
    stmt = select(ClientAccount).where(ClientAccount.organization_id == ctx.org_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(ClientAccount.name.ilike(like), ClientAccount.external_reference.ilike(like),
                              ClientAccount.tax_id.ilike(like)))
    if status:
        stmt = stmt.where(ClientAccount.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(ClientAccount.name).limit(page.limit).offset(page.offset)).all()
    return ClientPage(items=items, total=total)


@router.post("", response_model=ClientOut, status_code=201, summary="Cadastrar empresa atendida")
def create_client(body: ClientIn, ctx: AnalystCtx, db: DB):
    client = ClientAccount(organization_id=ctx.org_id, **body.model_dump())
    client.name = client.name.strip()
    db.add(client)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Já existe uma empresa com este nome.") from exc
    audit.record_ctx(db, ctx, "client.created", "client_account", client.id, {"name": client.name})
    db.commit()
    return client


@router.get("/{client_id}", response_model=ClientDetail, summary="Consultar empresa atendida")
def get_client(client_id: uuid.UUID, ctx: ViewerCtx, db: DB):
    client = get_owned(db, ClientAccount, client_id, ctx.org_id, "Empresa")
    files = db.scalar(select(func.count()).select_from(FileAsset).where(
        FileAsset.client_account_id == client.id, FileAsset.status != "deleted")) or 0
    jobs = db.scalar(select(func.count()).select_from(ProcessingJob).where(ProcessingJob.client_account_id == client.id)) or 0
    last = db.scalar(select(func.max(FileAsset.created_at)).where(FileAsset.client_account_id == client.id))
    return ClientDetail(**ClientOut.model_validate(client).model_dump(), file_count=files, job_count=jobs, last_activity_at=last)


@router.patch("/{client_id}", response_model=ClientOut, summary="Editar ou desativar empresa atendida")
def update_client(client_id: uuid.UUID, body: ClientPatch, ctx: AnalystCtx, db: DB):
    client = get_owned(db, ClientAccount, client_id, ctx.org_id, "Empresa")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(client, k, v.strip() if isinstance(v, str) and k == "name" else v)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Já existe uma empresa com este nome.") from exc
    audit.record_ctx(db, ctx, "client.updated", "client_account", client.id, {"fields": sorted(changes)})
    db.commit()
    return client
