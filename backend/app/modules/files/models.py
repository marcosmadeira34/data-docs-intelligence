from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, Timestamped, UUIDPk


class FileAsset(UUIDPk, Timestamped, Base):
    """Metadados de um arquivo enviado. O conteúdo fica no armazenamento de objetos privado."""

    __tablename__ = "file_assets"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    client_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("client_accounts.id", ondelete="CASCADE"))
    original_filename: Mapped[str] = mapped_column(String(255))
    detected_format: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    retention_until: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("file_assets.id", ondelete="SET NULL"))
    # Opções de leitura confirmadas pelo usuário (aba, linha de cabeçalho, delimitador, codificação)
    read_options: Mapped[dict[str, Any] | None]
    structure_confirmed: Mapped[bool] = mapped_column(default=False)
    # Último relatório de inspeção (prévia mascarada e limitada)
    inspection: Mapped[dict[str, Any] | None]

    __table_args__ = (
        Index("ix_file_assets_org_client_created", "organization_id", "client_account_id", "created_at"),
        Index("ix_file_assets_org_hash", "organization_id", "content_hash"),
        CheckConstraint("status in ('uploaded','inspected','deleted')", name="status"),
        CheckConstraint("detected_format in ('csv','xlsx')", name="format"),
    )
