"""
Audit log service.

Every governance or pipeline event that must leave a durable trace calls
audit_write() BEFORE its surrounding db.commit() so the audit row is
committed atomically with the business operation.

actor_id conventions:
  - Human actors: the identifier passed by the caller (approved_by, submitted_by, …)
  - System/worker actors: "system/<worker-name>"   e.g. "system/extraction"
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


def audit_write(
    db: AsyncSession,
    *,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    before_state: dict | None = None,
    after_state: dict | None = None,
) -> AuditLog:
    """
    Add an AuditLog row to the current session without committing.

    The caller is responsible for committing the session; the audit row will
    be persisted atomically with the surrounding business transaction.
    """
    entry = AuditLog(
        log_id=uuid.uuid4(),
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before_state=before_state,
        after_state=after_state,
    )
    db.add(entry)
    return entry
