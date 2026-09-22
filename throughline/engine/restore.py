"""Restore Point Manager (ARCH §11, FR-DEL-7).

A restore point is captured at every gate pass and every compile/export —
a safe, atomic copy of the whole `workspace.db` via SQLite's own online
backup API (safe against concurrent readers), so "one action reverts to
the last-known-good deck" is always literally true: swap the file back.
`apply()` always snapshots the *current* state first, so a revert is
itself reversible.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from . import models, persistence
from .errors import EngineError


def create_restore_point(conn: sqlite3.Connection, workspace_id: str, trigger: str, actor: Optional[str]) -> models.RestorePoint:
    db_path = persistence.db_path_from_conn(conn)
    workspace_dir = db_path.parent
    restore_root = workspace_dir / "restore_points"
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target_dir = restore_root / f"{stamp}-{trigger}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_db = target_dir / "workspace.db"

    conn.execute("PRAGMA wal_checkpoint(FULL);")
    persistence.backup_db(db_path, target_db)

    rp = models.RestorePoint(
        id=models.new_id("restore"), workspace_id=workspace_id, trigger=trigger,
        actor=actor, path=str(target_db),
    )
    (target_dir / "meta.json").write_text(json.dumps({
        "id": rp.id, "workspaceId": workspace_id, "trigger": trigger, "actor": actor, "createdAt": rp.created_at,
    }))
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor or "system",
        action="restore.create", subject_type="restore_point", subject_id=rp.id, details={"trigger": trigger},
    )
    persistence.commit(conn, "restore_point", rp, audit)
    return rp


def list_restore_points(conn: sqlite3.Connection, workspace_id: str) -> list[models.RestorePoint]:
    return persistence.list_all(conn, "restore_point", workspace_id, models.RestorePoint)


def apply_restore_point(conn: sqlite3.Connection, workspace_id: str, restore_id: str, actor: str) -> tuple[models.RestorePoint, models.RestorePoint]:
    """Reverts the live `workspace.db` to `restore_id`'s snapshot, after
    first snapshotting the current state (so the revert is reversible).
    The caller must close `conn` immediately after this returns and reopen
    a fresh connection, since the underlying file has been replaced."""
    rp = persistence.get(conn, "restore_point", restore_id, models.RestorePoint)
    if rp is None or rp.workspace_id != workspace_id:
        raise EngineError("RESTORE_POINT_NOT_FOUND", f"restore point '{restore_id}' not found", {"restoreId": restore_id})
    if not Path(rp.path).exists():
        raise EngineError("RESTORE_POINT_NOT_FOUND", f"restore point '{restore_id}' data file is missing on disk", {"restoreId": restore_id, "path": rp.path})

    pre_revert = create_restore_point(conn, workspace_id, trigger="pre_revert", actor=actor)
    db_path = persistence.db_path_from_conn(conn)
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="restore.apply", subject_type="restore_point", subject_id=rp.id,
        details={"preRevertId": pre_revert.id},
    )
    persistence.append_audit(conn, audit)
    conn.execute("PRAGMA wal_checkpoint(FULL);")
    conn.close()

    persistence.backup_db(Path(rp.path), db_path)
    return rp, pre_revert
