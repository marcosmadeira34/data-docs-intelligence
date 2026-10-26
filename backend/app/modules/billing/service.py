"""Planos, limites de uso e registro de consumo (aplicados no backend).

Nenhuma cobrança real é feita: ``PaymentProvider`` é uma abstração cuja
implementação padrão não faz nada. Ver docs/roadmap.md para a integração.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import LimitExceeded
from app.modules.billing.models import Plan, Subscription, UsageRecord

DEFAULT_PLANS: dict[str, dict] = {
    "trial": {"name": "Avaliação", "price_cents": 0, "limits": {
        "files": 300, "records": 500_000, "jobs": 500, "comparisons": 200, "users": 5, "profiles": 30,
        "max_file_bytes": 50 * 1024 * 1024}},
    "essencial": {"name": "Essencial", "price_cents": 0, "limits": {
        "files": 2000, "records": 5_000_000, "jobs": 4000, "comparisons": 2000, "users": 15, "profiles": 200,
        "max_file_bytes": 50 * 1024 * 1024}},
    "profissional": {"name": "Profissional", "price_cents": 0, "limits": {
        "files": None, "records": 50_000_000, "jobs": None, "comparisons": None, "users": 100, "profiles": None,
        "max_file_bytes": 200 * 1024 * 1024}},
}
METRICS = ("files", "records", "jobs", "comparisons")


def current_period(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m")


def ensure_default_plans(db: Session) -> None:
    existing = set(db.scalars(select(Plan.code)))
    for code, data in DEFAULT_PLANS.items():
        if code not in existing:
            db.add(Plan(code=code, name=data["name"], limits=data["limits"], price_cents=data["price_cents"]))
    db.flush()


def start_trial(db: Session, organization_id: uuid.UUID) -> Subscription:
    ensure_default_plans(db)
    sub = Subscription(organization_id=organization_id, plan_code="trial", status="trialing", overage_policy="block",
                       current_period_start=datetime.now(UTC))
    db.add(sub)
    return sub


def get_limits(db: Session, organization_id: uuid.UUID) -> tuple[Subscription | None, dict]:
    sub = db.scalar(select(Subscription).where(Subscription.organization_id == organization_id))
    if sub is None:
        return None, DEFAULT_PLANS["trial"]["limits"]
    plan = db.get(Plan, sub.plan_code)
    return sub, (plan.limits if plan else DEFAULT_PLANS["trial"]["limits"])


def usage_for_period(db: Session, organization_id: uuid.UUID, period: str | None = None) -> dict[str, int]:
    period = period or current_period()
    rows = db.execute(
        select(UsageRecord.metric, func.coalesce(func.sum(UsageRecord.quantity), 0))
        .where(UsageRecord.organization_id == organization_id, UsageRecord.period == period)
        .group_by(UsageRecord.metric)
    ).all()
    out = dict.fromkeys(METRICS, 0)
    out.update({m: int(q) for m, q in rows})
    return out


def check_quota(db: Session, organization_id: uuid.UUID, metric: str, increment: int = 1) -> None:
    """Lança ``LimitExceeded`` se a operação ultrapassar o limite e a política for 'block'."""
    sub, limits = get_limits(db, organization_id)
    if sub is not None and sub.status == "canceled":
        raise LimitExceeded("A assinatura da organização está cancelada.", code="subscription_inactive")
    limit = limits.get(metric)
    if limit is None:
        return
    used = usage_for_period(db, organization_id).get(metric, 0)
    if used + increment > limit and (sub is None or sub.overage_policy == "block"):
        raise LimitExceeded(
            f"Limite mensal do plano atingido para '{metric}' ({used}/{limit}).",
            details={"metric": metric, "used": used, "limit": limit},
        )


def check_count_limit(metric: str, current_count: int, limits: dict) -> None:
    limit = limits.get(metric)
    if limit is not None and current_count >= limit:
        raise LimitExceeded(f"O plano permite no máximo {limit} ({metric}).", details={"metric": metric, "limit": limit})


def record_usage(db: Session, organization_id: uuid.UUID, metric: str, quantity: int, entity_type: str | None = None,
                 entity_id: object = None) -> None:
    db.add(UsageRecord(organization_id=organization_id, metric=metric, quantity=quantity, period=current_period(),
                       entity_type=entity_type, entity_id=str(entity_id) if entity_id else None))


class PaymentProvider(Protocol):
    def create_checkout(self, organization_id: uuid.UUID, plan_code: str) -> str: ...
    def cancel(self, subscription: Subscription) -> None: ...


class NoPaymentProvider:
    """Implementação padrão: sem integração de pagamentos configurada."""

    def create_checkout(self, organization_id: uuid.UUID, plan_code: str) -> str:
        raise NotImplementedError("Nenhum provedor de pagamentos configurado.")

    def cancel(self, subscription: Subscription) -> None:
        raise NotImplementedError("Nenhum provedor de pagamentos configurado.")
