from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, Timestamped, UUIDPk, utcnow


class DatasetProfile(UUIDPk, Timestamped, Base):
    """Perfil lógico de um tipo de arquivo (ex.: 'Contas a pagar - ERP X')."""

    __tablename__ = "dataset_profiles"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    client_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("client_accounts.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_profile_versions.id", ondelete="SET NULL", use_alter=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    versions: Mapped[list[DatasetProfileVersion]] = relationship(
        back_populates="profile", foreign_keys="DatasetProfileVersion.profile_id", order_by="DatasetProfileVersion.version")

    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        Index("ix_dataset_profiles_org_client", "organization_id", "client_account_id"),
        CheckConstraint("status in ('active','archived')", name="status"),
    )


class DatasetProfileVersion(UUIDPk, Timestamped, Base):
    """Versão imutável da estrutura esperada de um perfil."""

    __tablename__ = "dataset_profile_versions"

    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_profiles.id", ondelete="CASCADE"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    source_format: Mapped[str] = mapped_column(String(10))
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    header_row: Mapped[int] = mapped_column(Integer)
    delimiter: Mapped[str | None] = mapped_column(String(4))
    encoding: Mapped[str | None] = mapped_column(String(30))
    columns: Mapped[list[Any]]
    structure_signature: Mapped[str] = mapped_column(String(64), index=True)
    structural_rules: Mapped[dict[str, Any]] = mapped_column(default=dict)
    approval_status: Mapped[str] = mapped_column(String(20), default="draft")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    change_note: Mapped[str | None] = mapped_column(Text)
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("file_assets.id", ondelete="SET NULL"))

    profile: Mapped[DatasetProfile] = relationship(back_populates="versions", foreign_keys=[profile_id])
    mapping: Mapped[MappingProfile | None] = relationship(back_populates="profile_version", uselist=False)

    __table_args__ = (
        UniqueConstraint("profile_id", "version"),
        CheckConstraint("approval_status in ('draft','approved','superseded')", name="approval_status"),
    )


class MappingProfile(UUIDPk, Timestamped, Base):
    """Mapeamento coluna de origem -> campo canônico de uma versão de perfil."""

    __tablename__ = "mapping_profiles"

    profile_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_profile_versions.id", ondelete="CASCADE"), unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    entries: Mapped[list[Any]]
    suggestion_source: Mapped[str] = mapped_column(String(20), default="heuristic")
    confirmation_threshold: Mapped[float] = mapped_column(Float)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None]

    profile_version: Mapped[DatasetProfileVersion] = relationship(back_populates="mapping")
