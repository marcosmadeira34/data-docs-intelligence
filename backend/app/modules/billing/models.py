from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, BigIntPK, Timestamped, UUIDPk, utcnow


class Plan(Base):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # Limites mensais; None = ilimitado. Chaves: files, records, jobs, comparisons, users, profiles, max_file_bytes
    limits: Mapped[dict[str, Any]]
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(default=True)


class Subscription(UUIDPk, Timestamped, Base):
    __tablename__ = "subscriptions"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), unique=True)
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"))
    status: Mapped[str] = mapped_column(String(20), default="trialing")
    # block: recusa operações acima do limite; allow: permite e registra excedente
    overage_policy: Mapped[str] = mapped_column(String(10), default="block")
    current_period_start: Mapped[datetime | None]
    current_period_end: Mapped[datetime | None]
    external_reference: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint("status in ('trialing','active','past_due','canceled')", name="status"),
        CheckConstraint("overage_policy in ('block','allow')", name="overage_policy"),
    )


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[int] = mapped_column(BigInteger)
    period: Mapped[str] = mapped_column(String(7))  # AAAA-MM
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (Index("ix_usage_records_org_metric_period", "organization_id", "metric", "period"),)
