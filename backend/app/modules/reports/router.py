"""Dashboard (métricas reais do banco) e trilha de auditoria."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DB, AdminCtx, Paging, ViewerCtx
from app.modules.audit.models import AuditEvent
from app.modules.clients.models import ClientAccount
from app.modules.comparison.models import ComparisonJob
from app.modules.files.models import FileAsset
from app.modules.organizations.models import User
from app.modules.processing.models import ProcessingJob

router = APIRouter(tags=["painel e auditoria"])


@router.get("/dashboard", summary="Indicadores da organização")
def dashboard(ctx: ViewerCtx, db: DB, days: int = Query(30, ge=1, le=365)):
    org = ctx.org_id
    since = datetime.now(UTC) - timedelta(days=days)

    def count(stmt) -> int:
        return int(db.scalar(stmt) or 0)

    jobs_by_status = dict(db.execute(select(ProcessingJob.status, func.count()).where(
        ProcessingJob.organization_id == org, ProcessingJob.created_at >= since).group_by(ProcessingJob.status)).all())
    findings = db.execute(select(func.coalesce(func.sum(ProcessingJob.error_count), 0),
                                 func.coalesce(func.sum(ProcessingJob.warning_count), 0),
                                 func.coalesce(func.sum(ProcessingJob.records_read), 0))
                          .where(ProcessingJob.organization_id == org, ProcessingJob.created_at >= since,
                                 ProcessingJob.status == "succeeded")).one()
    recent = db.execute(
        select(AuditEvent, User.name).outerjoin(User, User.id == AuditEvent.actor_user_id)
        .where(AuditEvent.organization_id == org).order_by(AuditEvent.created_at.desc()).limit(10)).all()
    return {
        "period_days": days,
        "clients_active": count(select(func.count()).select_from(ClientAccount).where(
            ClientAccount.organization_id == org, ClientAccount.status == "active")),
        "files_uploaded": count(select(func.count()).select_from(FileAsset).where(
            FileAsset.organization_id == org, FileAsset.created_at >= since)),
        "jobs_succeeded": int(jobs_by_status.get("succeeded", 0)),
        "jobs_failed": int(jobs_by_status.get("failed", 0)),
        "jobs_pending": int(jobs_by_status.get("queued", 0)) + int(jobs_by_status.get("running", 0)),
        "comparisons": count(select(func.count()).select_from(ComparisonJob).where(
            ComparisonJob.organization_id == org, ComparisonJob.created_at >= since)),
        "records_processed": int(findings[2]),
        "errors_found": int(findings[0]),
        "warnings_found": int(findings[1]),
        "recent_activity": [_event(e, name) for e, name in recent],
    }


def _event(e: AuditEvent, actor_name: str | None) -> dict[str, Any]:
    return {"id": e.id, "action": e.action, "entity_type": e.entity_type, "entity_id": e.entity_id, "actor_name": actor_name,
            "details": e.details, "created_at": e.created_at}


@router.get("/audit-events", summary="Trilha de auditoria (administradores)")
def audit_events(ctx: AdminCtx, db: DB, page: Paging, action: str | None = Query(None, max_length=60),
                 entity_id: str | None = Query(None, max_length=64)):
    stmt = select(AuditEvent, User.name).outerjoin(User, User.id == AuditEvent.actor_user_id).where(
        AuditEvent.organization_id == ctx.org_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if entity_id:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(AuditEvent.created_at.desc()).limit(page.limit).offset(page.offset)).all()
    return {"items": [_event(e, n) for e, n in rows], "total": total}
