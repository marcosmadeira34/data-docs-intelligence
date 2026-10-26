from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.modules.audit.models import AuditEvent


def record(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    """Adiciona um evento à transação corrente (persistido no commit da operação)."""
    event = AuditEvent(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details or {},
        request_id=request_id_var.get(),
        ip_address=ip_address,
    )
    db.add(event)
    return event


def record_ctx(db: Session, ctx, action: str, entity_type: str, entity_id: Any = None, details: dict[str, Any] | None = None) -> AuditEvent:
    return record(db, organization_id=ctx.org_id, actor_user_id=ctx.user.id, action=action, entity_type=entity_type,
                  entity_id=entity_id, details=details)
