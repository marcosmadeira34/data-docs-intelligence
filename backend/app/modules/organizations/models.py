from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, Timestamped, UUIDPk, utcnow

ROLES = ("owner", "admin", "analyst", "viewer")


class Organization(UUIDPk, Timestamped, Base):
    """Escritório contábil ou BPO assinante da plataforma."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="active")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (CheckConstraint("status in ('active','suspended')", name="status"),)


class User(UUIDPk, Timestamped, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")
    last_login_at: Mapped[datetime | None]

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")

    __table_args__ = (CheckConstraint("status in ('active','disabled')", name="status"),)


class Membership(UUIDPk, Timestamped, Base):
    __tablename__ = "memberships"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="active")

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship()

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        CheckConstraint("role in ('owner','admin','analyst','viewer')", name="role"),
        CheckConstraint("status in ('active','disabled')", name="status"),
    )
