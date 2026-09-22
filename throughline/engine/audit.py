"""Append-only audit log (ARCH §8, NFR-8). This module intentionally
exposes only `append_audit` and `tail_audit` — there is no update or
delete function anywhere in the Engine CLI surface, so the audit trail
cannot be edited after the fact, by anyone, including the Engine itself.
"""
from __future__ import annotations

from typing import Optional

from . import models, persistence


def append_audit(conn, event: models.AuditEvent) -> None:
    persistence.append_audit(conn, event)


def record(conn, workspace_id: str, actor: str, action: str, subject_type: str, subject_id: str, details: Optional[dict] = None) -> models.AuditEvent:
    event = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor, action=action,
        subject_type=subject_type, subject_id=subject_id, details=details or {},
    )
    persistence.append_audit(conn, event)
    return event


def tail_audit(conn, workspace_id: str, since: Optional[str] = None) -> list[models.AuditEvent]:
    return persistence.tail_audit(conn, workspace_id, since)
