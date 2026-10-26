from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, Timestamped, UUIDPk


class ValidationRule(UUIDPk, Timestamped, Base):
    """Versão de uma regra de validação. Cada alteração cria uma nova linha.

    ``rule_key`` é o identificador estável entre versões; apenas uma versão por
    ``rule_key`` tem ``is_current = true``. Regras com ``organization_id`` nulo
    são globais (catálogo da plataforma) e somente leitura para organizações.
    """

    __tablename__ = "validation_rules"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    client_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("client_accounts.id", ondelete="CASCADE"))
    profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_profiles.id", ondelete="CASCADE"))
    rule_key: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    rule_type: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict[str, Any]]
    severity: Mapped[str] = mapped_column(String(10))
    applies_when: Mapped[dict[str, Any] | None]
    message: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), default="active")
    is_current: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        UniqueConstraint("rule_key", "version"),
        Index("ix_validation_rules_org_current", "organization_id", "is_current"),
        CheckConstraint("severity in ('error','warning','info')", name="severity"),
        CheckConstraint("status in ('active','inactive')", name="status"),
    )
