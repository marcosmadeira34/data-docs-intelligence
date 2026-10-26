from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, BigIntPK, Timestamped, UUIDPk

JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
# file_error: problema no arquivo; config_error: configuração/perfil/regra; infrastructure_error: falha técnica (retentável)
ERROR_KINDS = ("file_error", "config_error", "infrastructure_error", "timeout")


class JobMixin:
    """Campos comuns de execução usados pela fila no banco."""

    status: Mapped[str] = mapped_column(String(20), default="queued")
    error_kind: Mapped[str | None] = mapped_column(String(30))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None]
    run_after: Mapped[datetime | None]


class ProcessingJob(UUIDPk, Timestamped, JobMixin, Base):
    __tablename__ = "processing_jobs"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    client_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("client_accounts.id", ondelete="CASCADE"))
    file_asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("file_assets.id", ondelete="RESTRICT"))
    profile_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_profile_versions.id", ondelete="RESTRICT"))
    reprocess_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("processing_jobs.id", ondelete="SET NULL"))
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Evidências de reprodutibilidade
    rules_snapshot: Mapped[list[Any] | None]
    input_snapshot: Mapped[dict[str, Any] | None]
    summary: Mapped[dict[str, Any] | None]
    records_read: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    info_count: Mapped[int] = mapped_column(Integer, default=0)
    findings_stored: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key"),
        Index("ix_processing_jobs_org_created", "organization_id", "created_at"),
        Index("ix_processing_jobs_status", "status"),
        CheckConstraint("status in ('queued','running','succeeded','failed','cancelled')", name="status"),
    )


class ValidationFinding(Base):
    __tablename__ = "validation_findings"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("processing_jobs.id", ondelete="CASCADE"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("validation_rules.id", ondelete="SET NULL"))
    rule_key: Mapped[str] = mapped_column(String(80))
    rule_version: Mapped[int] = mapped_column(Integer)
    rule_type: Mapped[str] = mapped_column(String(40))
    rule_name: Mapped[str | None] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(10))
    row_number: Mapped[int | None] = mapped_column(BigInteger)
    record_key: Mapped[str | None] = mapped_column(String(120))
    field: Mapped[str | None] = mapped_column(String(64))
    observed_value: Mapped[str | None] = mapped_column(String(130))
    message: Mapped[str] = mapped_column(String(500))
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    review_status: Mapped[str] = mapped_column(String(20), default="open")
    review_note: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None]

    __table_args__ = (
        Index("ix_validation_findings_job_severity", "job_id", "severity"),
        Index("ix_validation_findings_job_rule", "job_id", "rule_key"),
        Index("ix_validation_findings_job_field", "job_id", "field"),
        CheckConstraint("review_status in ('open','acknowledged','resolved','false_positive')", name="review_status"),
    )
