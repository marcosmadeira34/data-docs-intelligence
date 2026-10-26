"""Dependências HTTP: autenticação, escopo da organização e autorização por papel."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, TypeVar

import jwt
from fastapi import Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.security import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, decode_access_token
from app.infrastructure.database.session import get_db
from app.modules.organizations.models import Membership, Organization, User

ROLE_RANK = {"viewer": 0, "analyst": 1, "admin": 2, "owner": 3}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

DB = Annotated[Session, Depends(get_db)]


@dataclass
class Ctx:
    user: User
    organization: Organization
    membership: Membership

    @property
    def org_id(self) -> uuid.UUID:
        return self.organization.id

    @property
    def role(self) -> str:
        return self.membership.role

    def has_role(self, minimum: str) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[minimum]


def _extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise Unauthorized("Autenticação necessária.")
    # Autenticação por cookie exige token CSRF (double submit) em métodos que alteram estado.
    if request.method not in _SAFE_METHODS:
        header = request.headers.get(CSRF_HEADER)
        cookie = request.cookies.get(CSRF_COOKIE)
        if not header or not cookie or header != cookie:
            raise Forbidden("Token CSRF ausente ou inválido.", code="csrf_failed")
    return token


def get_ctx(request: Request, db: DB) -> Ctx:
    token = _extract_token(request)
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
        org_id = uuid.UUID(payload["org"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise Unauthorized("Sessão inválida ou expirada.") from exc
    row = db.execute(
        select(User, Membership, Organization)
        .join(Membership, Membership.user_id == User.id)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(User.id == user_id, Organization.id == org_id)
    ).first()
    if row is None:
        raise Unauthorized("Sessão inválida ou expirada.")
    user, membership, org = row
    if user.status != "active" or membership.status != "active" or org.status != "active":
        raise Unauthorized("Acesso desativado.")
    request.state.user_id = str(user.id)
    request.state.org_id = str(org.id)
    return Ctx(user=user, organization=org, membership=membership)


CurrentCtx = Annotated[Ctx, Depends(get_ctx)]


def require_role(minimum: str):
    def dep(ctx: CurrentCtx) -> Ctx:
        if not ctx.has_role(minimum):
            raise Forbidden("Seu papel não permite esta operação.")
        return ctx

    return Depends(dep)


ViewerCtx = Annotated[Ctx, require_role("viewer")]
AnalystCtx = Annotated[Ctx, require_role("analyst")]
AdminCtx = Annotated[Ctx, require_role("admin")]
OwnerCtx = Annotated[Ctx, require_role("owner")]

M = TypeVar("M")


def get_owned(db: Session, model: type[M], obj_id: uuid.UUID, org_id: uuid.UUID, label: str = "Recurso") -> M:
    """Busca um recurso garantindo que pertence à organização. 404 em qualquer outro caso (evita IDOR e enumeração)."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "organization_id", None) != org_id:
        raise NotFound(f"{label} não encontrado.")
    return obj


class Pagination:
    def __init__(self, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=1_000_000)):
        self.limit = limit
        self.offset = offset


Paging = Annotated[Pagination, Depends()]
