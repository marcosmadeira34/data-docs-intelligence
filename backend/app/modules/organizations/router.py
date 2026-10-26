"""Autenticação, sessão, organização corrente, membros e consumo."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, AdminCtx, CurrentCtx, ViewerCtx
from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailed
from app.core.security import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    create_access_token,
    generate_temporary_password,
    hash_password,
    login_throttle,
    new_csrf_token,
    verify_password,
)
from app.modules.audit import service as audit
from app.modules.billing import service as billing
from app.modules.billing.models import Plan
from app.modules.organizations import schemas as s
from app.modules.organizations.models import Membership, Organization, User

auth_router = APIRouter(prefix="/auth", tags=["autenticação"])
router = APIRouter(tags=["organização"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _memberships(db, user_id: uuid.UUID) -> list[s.MembershipSummary]:
    rows = db.execute(
        select(Membership, Organization).join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user_id, Membership.status == "active", Organization.status == "active")
        .order_by(Organization.name)
    ).all()
    return [s.MembershipSummary(organization_id=o.id, organization_name=o.name, role=m.role) for m, o in rows]


def _issue_session(response: Response, db, user: User, org: Organization, role: str) -> s.SessionOut:
    settings = get_settings()
    token = create_access_token(user.id, org.id)
    csrf = new_csrf_token()
    max_age = settings.access_token_ttl_minutes * 60
    response.set_cookie(ACCESS_COOKIE, token, max_age=max_age, httponly=True, secure=settings.cookie_secure,
                        samesite="strict", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=settings.cookie_secure,
                        samesite="strict", path="/")
    return s.SessionOut(access_token=token, csrf_token=csrf, user=s.UserOut.model_validate(user),
                        organization=s.OrganizationOut.model_validate(org), role=role, memberships=_memberships(db, user.id))


@auth_router.post("/signup", response_model=s.SessionOut, status_code=201, summary="Criar organização e usuário proprietário")
def signup(body: s.SignupIn, response: Response, db: DB, request: Request):
    if not get_settings().allow_signup:
        raise Forbidden("O cadastro público está desativado. Solicite acesso ao administrador.")
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise Conflict("Já existe um usuário com este e-mail. Faça login ou peça para ser adicionado à organização.")
    org = Organization(name=body.organization_name.strip())
    user = User(name=body.name.strip(), email=email, password_hash=hash_password(body.password))
    db.add_all([org, user])
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
    billing.start_trial(db, org.id)
    audit.record(db, organization_id=org.id, actor_user_id=user.id, action="organization.created", entity_type="organization",
                 entity_id=org.id, ip_address=_client_ip(request))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Não foi possível concluir o cadastro (e-mail já utilizado).") from exc
    return _issue_session(response, db, user, org, "owner")


@auth_router.post("/login", response_model=s.SessionOut, summary="Autenticar")
def login(body: s.LoginIn, response: Response, db: DB, request: Request):
    email, ip = body.email.lower(), _client_ip(request)
    generic = Unauthorized("E-mail ou senha inválidos.", code="invalid_credentials")
    if login_throttle.is_locked(email, ip):
        raise Unauthorized("Muitas tentativas. Aguarde alguns minutos e tente novamente.", code="too_many_attempts")
    user = db.scalar(select(User).where(User.email == email))
    if not verify_password(body.password, user.password_hash if user else None) or user is None or user.status != "active":
        login_throttle.fail(email, ip)
        raise generic
    q = (select(Membership, Organization).join(Organization, Organization.id == Membership.organization_id)
         .where(Membership.user_id == user.id, Membership.status == "active", Organization.status == "active"))
    if body.organization_id:
        q = q.where(Organization.id == body.organization_id)
    row = db.execute(q.order_by(Membership.created_at)).first()
    if row is None:
        login_throttle.fail(email, ip)
        raise generic
    login_throttle.reset(email, ip)
    membership, org = row
    user.last_login_at = datetime.now(UTC)
    audit.record(db, organization_id=org.id, actor_user_id=user.id, action="auth.login", entity_type="user", entity_id=user.id,
                 ip_address=ip)
    db.commit()
    return _issue_session(response, db, user, org, membership.role)


@auth_router.post("/logout", status_code=204, summary="Encerrar sessão")
def logout(response: Response):
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@auth_router.post("/switch-organization", response_model=s.SessionOut, summary="Trocar organização ativa")
def switch_organization(body: s.SwitchOrgIn, ctx: CurrentCtx, response: Response, db: DB):
    row = db.execute(
        select(Membership, Organization).join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == ctx.user.id, Organization.id == body.organization_id, Membership.status == "active",
               Organization.status == "active")
    ).first()
    if row is None:
        raise NotFound("Organização não encontrada.")
    membership, org = row
    return _issue_session(response, db, ctx.user, org, membership.role)


@router.get("/me", response_model=s.MeOut, summary="Usuário autenticado")
def me(ctx: ViewerCtx, db: DB):
    return s.MeOut(user=s.UserOut.model_validate(ctx.user), organization=s.OrganizationOut.model_validate(ctx.organization),
                   role=ctx.role, memberships=_memberships(db, ctx.user.id))


@router.post("/me/password", status_code=204, summary="Alterar a própria senha")
def change_password(body: s.ChangePasswordIn, ctx: ViewerCtx, db: DB):
    if not verify_password(body.current_password, ctx.user.password_hash):
        raise ValidationFailed("Senha atual incorreta.")
    ctx.user.password_hash = hash_password(body.new_password)
    audit.record_ctx(db, ctx, "user.password_changed", "user", ctx.user.id)
    db.commit()


@router.get("/organizations/current", response_model=s.OrganizationOut, summary="Organização corrente")
def current_org(ctx: ViewerCtx):
    return ctx.organization


@router.patch("/organizations/current", response_model=s.OrganizationOut, summary="Atualizar organização")
def update_org(body: s.OrgUpdateIn, ctx: AdminCtx, db: DB):
    ctx.organization.name = body.name.strip()
    audit.record_ctx(db, ctx, "organization.updated", "organization", ctx.org_id, {"name": body.name})
    db.commit()
    return ctx.organization


@router.get("/organizations/current/usage", response_model=s.UsageOut, summary="Plano, limites e consumo do mês")
def usage(ctx: ViewerCtx, db: DB):
    sub, limits = billing.get_limits(db, ctx.org_id)
    plan = db.get(Plan, sub.plan_code) if sub else None
    return s.UsageOut(
        plan_code=sub.plan_code if sub else "trial", plan_name=plan.name if plan else "Avaliação",
        subscription_status=sub.status if sub else "trialing", overage_policy=sub.overage_policy if sub else "block",
        period=billing.current_period(), usage=billing.usage_for_period(db, ctx.org_id), limits=limits)


# --------------------------------------------------------------------------- membros


def _member_out(m: Membership, u: User) -> s.MemberOut:
    return s.MemberOut(id=m.id, user_id=u.id, name=u.name, email=u.email, role=m.role, status=m.status, created_at=m.created_at,
                       last_login_at=u.last_login_at)


@router.get("/organizations/current/members", response_model=list[s.MemberOut], summary="Listar membros")
def list_members(ctx: AdminCtx, db: DB):
    rows = db.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                      .where(Membership.organization_id == ctx.org_id).order_by(User.name)).all()
    return [_member_out(m, u) for m, u in rows]


@router.post("/organizations/current/members", response_model=s.MemberCreatedOut, status_code=201, summary="Adicionar membro")
def add_member(body: s.MemberCreateIn, ctx: AdminCtx, db: DB):
    if body.role == "owner" and ctx.role != "owner":
        raise Forbidden("Somente proprietários podem conceder o papel de proprietário.")
    _, limits = billing.get_limits(db, ctx.org_id)
    active = db.scalar(select(func.count()).select_from(Membership)
                       .where(Membership.organization_id == ctx.org_id, Membership.status == "active")) or 0
    billing.check_count_limit("users", active, limits)
    email = body.email.lower()
    user = db.scalar(select(User).where(User.email == email))
    temp = None
    if user is None:
        temp = generate_temporary_password()
        user = User(name=body.name.strip(), email=email, password_hash=hash_password(temp))
        db.add(user)
        db.flush()
    elif db.scalar(select(Membership.id).where(Membership.organization_id == ctx.org_id, Membership.user_id == user.id)):
        raise Conflict("Este usuário já é membro da organização.")
    m = Membership(organization_id=ctx.org_id, user_id=user.id, role=body.role)
    db.add(m)
    db.flush()
    audit.record_ctx(db, ctx, "member.added", "membership", m.id, {"role": body.role, "user_id": str(user.id)})
    db.commit()
    return s.MemberCreatedOut(member=_member_out(m, user), temporary_password=temp)


def _owner_count(db, org_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(Membership).where(
        Membership.organization_id == org_id, Membership.role == "owner", Membership.status == "active")) or 0


@router.patch("/organizations/current/members/{membership_id}", response_model=s.MemberOut, summary="Alterar papel ou status")
def update_member(membership_id: uuid.UUID, body: s.MemberUpdateIn, ctx: AdminCtx, db: DB):
    m = db.get(Membership, membership_id)
    if m is None or m.organization_id != ctx.org_id:
        raise NotFound("Membro não encontrado.")
    if m.user_id == ctx.user.id:
        raise Forbidden("Você não pode alterar o próprio papel ou status.")
    if (m.role == "owner" or body.role == "owner") and ctx.role != "owner":
        raise Forbidden("Somente proprietários podem alterar proprietários.")
    removing_owner = m.role == "owner" and ((body.role and body.role != "owner") or body.status == "disabled")
    if removing_owner and _owner_count(db, ctx.org_id) <= 1:
        raise Conflict("A organização precisa de pelo menos um proprietário ativo.")
    before = {"role": m.role, "status": m.status}
    if body.role:
        m.role = body.role
    if body.status:
        m.status = body.status
    audit.record_ctx(db, ctx, "member.updated", "membership", m.id, {"before": before, "after": {"role": m.role, "status": m.status}})
    db.commit()
    return _member_out(m, db.get(User, m.user_id))


@router.post("/organizations/current/members/{membership_id}/reset-password", response_model=s.TemporaryPasswordOut,
             summary="Gerar senha temporária para um membro")
def reset_member_password(membership_id: uuid.UUID, ctx: AdminCtx, db: DB):
    m = db.get(Membership, membership_id)
    if m is None or m.organization_id != ctx.org_id:
        raise NotFound("Membro não encontrado.")
    if m.role == "owner" and ctx.role != "owner":
        raise Forbidden("Somente proprietários podem redefinir a senha de proprietários.")
    user = db.get(User, m.user_id)
    # Um usuário em várias organizações só pode ter a senha redefinida por quem o administra em todas.
    others = db.scalar(select(func.count()).select_from(Membership).where(
        Membership.user_id == user.id, Membership.organization_id != ctx.org_id)) or 0
    if others:
        raise Forbidden("Este usuário pertence a outras organizações; ele deve alterar a própria senha.")
    temp = generate_temporary_password()
    user.password_hash = hash_password(temp)
    audit.record_ctx(db, ctx, "member.password_reset", "membership", m.id)
    db.commit()
    return s.TemporaryPasswordOut(temporary_password=temp)
