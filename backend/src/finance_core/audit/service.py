"""Audit trail writer.

Audit rows are added to the caller's session so they commit atomically with the change
they describe: there is never a change without its audit record, or vice versa.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.audit.models import AuditEvent

Actor = Literal["user", "assistant", "system"]


def record_audit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    actor: Actor,
    action: str,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    session.add(
        AuditEvent(
            user_id=user_id,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            data=data,
            request_id=request_id,
        )
    )
