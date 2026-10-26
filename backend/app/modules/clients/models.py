from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, Timestamped, UUIDPk, utcnow


class ClientAccount(UUIDPk, Timestamped, Base):
    """Empresa atendida pelo escritório/BPO (não é quem paga a assinatura)."""

    __tablename__ = "client_accounts"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    external_reference: Mapped[str | None] = mapped_column(String(100))
    tax_id: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        Index("ix_client_accounts_org_status", "organization_id", "status"),
        CheckConstraint("status in ('active','inactive')", name="status"),
    )
