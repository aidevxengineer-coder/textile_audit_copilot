from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def log_audit_event(
    session: Session,
    *,
    actor_user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    ip_address: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            metadata_json=metadata or {},
        )
    )
    session.commit()


def with_audit(
    audit_logger: Callable[..., None],
    *,
    actor_user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    ip_address: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    audit_logger(
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        metadata=metadata or {},
    )
