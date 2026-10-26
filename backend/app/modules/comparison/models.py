from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, BigIntPK, Timestamped, UUIDPk
from app.modules.processing.models import JobMixin


class ComparisonJob(UUIDPk, Timestamped, JobMixin, Base):
    __tablename__ = "comparison_jobs"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    client_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("client_accounts.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(String(200))
    file_a_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("file_assets.id", ondelete="RESTRICT"))
    file_b_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("file_assets.id", ondelete="RESTRICT"))
    config: Mapped[dict[str, Any]]
    input_snapshot: Mapped[dict[str, Any] | None]
    summary: Mapped[dict[str, Any] | None]
    results_stored: Mapped[int] = mapped_column(Integer, default=0)
    results_truncated: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key"),
        Index("ix_comparison_jobs_org_created", "organization_id", "created_at"),
        Index("ix_comparison_jobs_status", "status"),
        CheckConstraint("status in ('queued','running','succeeded','failed','cancelled')", name="status"),
    )


class ComparisonResult(Base):
    __tablename__ = "comparison_results"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    comparison_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("comparison_jobs.id", ondelete="CASCADE"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(20))
    key_value: Mapped[str | None] = mapped_column(String(250))
    row_a: Mapped[int | None] = mapped_column(BigInteger)
    row_b: Mapped[int | None] = mapped_column(BigInteger)
    differences: Mapped[list[Any]] = mapped_column(default=list)
    note: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (Index("ix_comparison_results_cmp_category", "comparison_id", "category"),)
