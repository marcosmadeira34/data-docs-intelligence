from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from app.api.deps import DB, AnalystCtx, Paging, ViewerCtx
from app.core.errors import Conflict, Forbidden, NotFound
from app.domain.canonical_fields import CANONICAL_FIELDS
from app.domain.validation.rules import REGISTRY, catalog
from app.modules.audit import service as audit
from app.modules.clients.models import ClientAccount
from app.modules.files.models import FileAsset
from app.modules.profiles.models import DatasetProfile
from app.modules.validation import service
from app.modules.validation.models import ValidationRule

router = APIRouter(prefix="/validation-rules", tags=["regras de validação"])
Severity = Literal["error", "warning", "info"]


class RuleIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(None, max_length=2000)
    rule_type: str = Field(max_length=40)
    params: dict[str, Any]
    severity: Severity = "error"
    applies_when: dict[str, Any] | None = None
    message: str | None = Field(None, max_length=300)
    client_id: uuid.UUID | None = None
    profile_id: uuid.UUID | None = None
    status: Literal["active", "inactive"] = "active"


class RulePatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    description: str | None = Field(None, max_length=2000)
    params: dict[str, Any] | None = None
    severity: Severity | None = None
    applies_when: dict[str, Any] | None = None
    message: str | None = Field(None, max_length=300)
    status: Literal["active", "inactive"] | None = None


class RuleCheckIn(BaseModel):
    rule_type: str = Field(max_length=40)
    params: dict[str, Any]
    applies_when: dict[str, Any] | None = None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    rule_key: str
    version: int
    name: str
    description: str | None
    rule_type: str
    category: str
    params: dict[str, Any]
    severity: str
    applies_when: dict[str, Any] | None
    message: str | None
    status: str
    is_current: bool
    is_global: bool = False
    client_account_id: uuid.UUID | None
    profile_id: uuid.UUID | None
    created_by: uuid.UUID | None
    created_at: datetime


class RuleDetail(RuleOut):
    history: list[RuleOut]


class RulePage(BaseModel):
    items: list[RuleOut]
    total: int


def _out(r: ValidationRule) -> RuleOut:
    o = RuleOut.model_validate(r)
    o.is_global = r.organization_id is None
    return o


def _visible(db, rule_id: uuid.UUID, org_id: uuid.UUID) -> ValidationRule:
    r = db.get(ValidationRule, rule_id)
    if r is None or (r.organization_id is not None and r.organization_id != org_id):
        raise NotFound("Regra não encontrada.")
    return r


def _check_refs(db, org_id: uuid.UUID, rule_type: str, params: dict[str, Any], client_id, profile_id) -> None:
    if client_id:
        c = db.get(ClientAccount, client_id)
        if c is None or c.organization_id != org_id:
            raise NotFound("Empresa não encontrada.")
    if profile_id:
        p = db.get(DatasetProfile, profile_id)
        if p is None or p.organization_id != org_id:
            raise NotFound("Perfil não encontrado.")
    if rule_type == "cross_file":
        try:
            fid = uuid.UUID(str(params.get("reference_file_id")))
        except ValueError as exc:
            raise NotFound("Arquivo de referência não encontrado.") from exc
        f = db.get(FileAsset, fid)
        if f is None or f.organization_id != org_id:
            raise NotFound("Arquivo de referência não encontrado.")


@router.get("/catalog", summary="Catálogo de tipos de regra e campos canônicos")
def rule_catalog(ctx: ViewerCtx):
    return {
        "rule_types": catalog(),
        "canonical_fields": [{"key": f.key, "label": f.label, "data_type": f.data_type} for f in CANONICAL_FIELDS],
        "severities": ["error", "warning", "info"],
    }


@router.post("/check", summary="Validar parâmetros de uma regra sem salvar")
def check_rule(body: RuleCheckIn, ctx: ViewerCtx):
    return {"valid": True, "params": service.validate_definition(body.rule_type, body.params, body.applies_when)}


@router.get("", response_model=RulePage, summary="Listar regras (versões atuais)")
def list_rules(ctx: ViewerCtx, db: DB, page: Paging, include_global: bool = True, client_id: uuid.UUID | None = None,
               profile_id: uuid.UUID | None = None, status: Literal["active", "inactive"] | None = None,
               rule_type: str | None = None):
    stmt = service.current_rules_query(ctx.org_id, include_global)
    if client_id:
        stmt = stmt.where(or_(ValidationRule.client_account_id.is_(None), ValidationRule.client_account_id == client_id))
    if profile_id:
        stmt = stmt.where(or_(ValidationRule.profile_id.is_(None), ValidationRule.profile_id == profile_id))
    if status:
        stmt = stmt.where(ValidationRule.status == status)
    if rule_type:
        stmt = stmt.where(ValidationRule.rule_type == rule_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(ValidationRule.organization_id.is_(None), ValidationRule.name)
                       .limit(page.limit).offset(page.offset)).all()
    return RulePage(items=[_out(r) for r in items], total=total)


@router.post("", response_model=RuleOut, status_code=201, summary="Criar regra")
def create_rule(body: RuleIn, ctx: AnalystCtx, db: DB):
    params = service.validate_definition(body.rule_type, body.params, body.applies_when)
    _check_refs(db, ctx.org_id, body.rule_type, params, body.client_id, body.profile_id)
    rule = ValidationRule(
        organization_id=ctx.org_id, client_account_id=body.client_id, profile_id=body.profile_id,
        rule_key=service.new_rule_key(body.name), version=1, name=body.name.strip(), description=body.description,
        rule_type=body.rule_type, category=REGISTRY[body.rule_type].category, params=params, severity=body.severity,
        applies_when=body.applies_when, message=body.message, status=body.status, is_current=True, created_by=ctx.user.id)
    db.add(rule)
    db.flush()
    audit.record_ctx(db, ctx, "rule.created", "validation_rule", rule.id, {"rule_key": rule.rule_key, "type": rule.rule_type})
    db.commit()
    return _out(rule)


@router.get("/{rule_id}", response_model=RuleDetail, summary="Consultar regra e histórico de versões")
def get_rule(rule_id: uuid.UUID, ctx: ViewerCtx, db: DB):
    r = _visible(db, rule_id, ctx.org_id)
    history = db.scalars(select(ValidationRule).where(ValidationRule.rule_key == r.rule_key,
                                                      ValidationRule.organization_id == r.organization_id)
                         .order_by(ValidationRule.version.desc())).all()
    return RuleDetail(**_out(r).model_dump(), history=[_out(h) for h in history])


@router.patch("/{rule_id}", response_model=RuleOut, summary="Alterar regra (cria nova versão)")
def update_rule(rule_id: uuid.UUID, body: RulePatch, ctx: AnalystCtx, db: DB):
    r = _visible(db, rule_id, ctx.org_id)
    if r.organization_id is None:
        raise Forbidden("Regras globais não podem ser alteradas por organizações. Use 'duplicar' para criar uma cópia.")
    if not r.is_current:
        raise Conflict("Somente a versão atual pode ser alterada.")
    changes = body.model_dump(exclude_unset=True)
    params = changes.get("params", r.params)
    applies_when = changes["applies_when"] if "applies_when" in changes else r.applies_when
    params = service.validate_definition(r.rule_type, params, applies_when)
    _check_refs(db, ctx.org_id, r.rule_type, params, None, None)
    new = ValidationRule(
        organization_id=r.organization_id, client_account_id=r.client_account_id, profile_id=r.profile_id,
        rule_key=r.rule_key, version=r.version + 1, name=changes.get("name", r.name),
        description=changes.get("description", r.description), rule_type=r.rule_type, category=r.category, params=params,
        severity=changes.get("severity", r.severity), applies_when=applies_when, message=changes.get("message", r.message),
        status=changes.get("status", r.status), is_current=True, created_by=ctx.user.id)
    r.is_current = False
    db.flush()
    db.add(new)
    db.flush()
    audit.record_ctx(db, ctx, "rule.updated", "validation_rule", new.id,
                     {"rule_key": r.rule_key, "from_version": r.version, "to_version": new.version, "fields": sorted(changes)})
    db.commit()
    return _out(new)


@router.post("/{rule_id}/clone", response_model=RuleOut, status_code=201, summary="Duplicar regra (ex.: global) para a organização")
def clone_rule(rule_id: uuid.UUID, ctx: AnalystCtx, db: DB):
    r = _visible(db, rule_id, ctx.org_id)
    copy = ValidationRule(
        organization_id=ctx.org_id, rule_key=service.new_rule_key(r.name), version=1, name=f"{r.name}"[:200],
        description=r.description, rule_type=r.rule_type, category=r.category, params=r.params, severity=r.severity,
        applies_when=r.applies_when, message=r.message, status="active", is_current=True, created_by=ctx.user.id)
    db.add(copy)
    db.flush()
    audit.record_ctx(db, ctx, "rule.cloned", "validation_rule", copy.id, {"source_rule_key": r.rule_key, "source_version": r.version})
    db.commit()
    return _out(copy)
