"""SQLite persistence, workspace-root resolution, and the single-active-
workspace lock (ARCH.md §11).

Layout under the (configurable) workspace root::

    <root>/workspace/.active-lock
    <root>/workspace/<workspaceId>/workspace.db
    <root>/workspace/<workspaceId>/staging/
    <root>/workspace/<workspaceId>/exports/
    <root>/workspace/<workspaceId>/restore_points/

The root defaults to ``~/.copilot/throughline`` but can be overridden (in
priority order) by an explicit constructor argument, the
``THROUGHLINE_WORKSPACE_ROOT`` environment variable, the ``THROUGHLINE_HOME``
environment variable (an alternate name for the same setting, honored
whenever ``THROUGHLINE_WORKSPACE_ROOT`` is unset), or the CLI's
``--workspace-root`` flag — this is what lets the open test suite run many
isolated workspaces in parallel without touching a real user's home
directory, while production use needs no configuration at all. It is also
what makes a *bare* `run-scenario` invocation (no `--workspace`/`--out`)
resolve to a deterministic, discoverable root: the same precedence chain
every other command already uses (docs/engine-cli-reference.md).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, TypeVar

from . import models

T = TypeVar("T")

DEFAULT_ROOT_ENV = "THROUGHLINE_WORKSPACE_ROOT"
HOME_ROOT_ENV = "THROUGHLINE_HOME"


def default_root() -> Path:
    override = os.environ.get(DEFAULT_ROOT_ENV) or os.environ.get(HOME_ROOT_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".copilot" / "throughline"


# One row-storage table per ledger, per ARCH §11. Every table shares the
# same generic shape (`id`, `workspace_id`, `data` JSON blob, timestamps)
# plus a small number of indexed columns used by hot-path queries so the
# whole store stays queryable for engineering debugging without becoming
# the black-box test surface (tests always go through the CLI).
_TABLES = {
    "workspace": "state",
    "brief": None,
    "source": "state",
    "evidence": "disposition",
    "claim": "state",
    "conflict": "status",
    "throughline": None,
    "route": None,
    "slide": None,
    "gate_result": "gate",
    "approval": None,
    "restore_point": None,
    "unmatched_content": None,
    "pending_edit": "status",
}

_SCHEMA_TABLES_SQL = "\n".join(
    f"""
    CREATE TABLE IF NOT EXISTS {table} (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        {extra_col + " TEXT," if extra_col else ""}
        seq INTEGER,
        data TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_{table}_workspace ON {table}(workspace_id);
    """
    for table, extra_col in _TABLES.items()
)

_SCHEMA_AUDIT_SQL = """
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    details TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit(workspace_id);
"""

_SCHEMA_KV_SQL = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    """One `Store` per resolved workspace root. Cheap to construct; holds
    no long-lived connection (each command-line invocation is one process,
    so a connection is opened/closed per CLI command)."""

    def __init__(self, root: Optional[Path | str] = None):
        self.root = Path(root).expanduser() if root else default_root()
        self.workspace_base = self.root / "workspace"
        self.workspace_base.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.workspace_base, 0o700)
        except OSError:
            pass

    # -- lock -------------------------------------------------------------
    @property
    def lock_path(self) -> Path:
        return self.workspace_base / ".active-lock"

    def read_lock(self) -> Optional[dict]:
        if not self.lock_path.exists():
            return None
        try:
            return json.loads(self.lock_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def active_workspace_id(self) -> Optional[str]:
        """Returns the active workspace id, or `None` if no lock exists.

        Deliberately **not** pid-liveness-based: every Engine command is a
        one-shot, independently-invoked process by design (ARCH §2/§4), so
        the process that created the lock has already exited by the time
        any later command runs — that is the *normal* case, not a crash.
        Treating a dead pid as "stale" would silently defeat NFR-2 (a
        second `workspace new` moments after the first would wrongly
        succeed). The lock is a persistent marker; only an explicit
        `workspace reset` (or resuming the *same* workspace id) clears it."""
        lock = self.read_lock()
        if lock is None:
            return None
        return lock.get("workspaceId")

    def acquire_lock(self, workspace_id: str) -> None:
        """Unconditional overwrite — used only by callers that have already
        established (via `try_acquire_lock`) that taking the lock is safe."""
        payload = {"workspaceId": workspace_id, "pid": os.getpid(), "startedAt": models.now_iso()}
        self.lock_path.write_text(json.dumps(payload))

    def try_acquire_lock(self, workspace_id: str) -> bool:
        """Atomically creates the lock file with `O_CREAT | O_EXCL`, so two
        processes racing to open a workspace against the same root can
        never both win — the OS guarantees exactly one `open()` succeeds
        (ARCH §11's single-active-workspace guarantee, made race-free
        rather than relying on a separate check-then-write step)."""
        payload = json.dumps({"workspaceId": workspace_id, "pid": os.getpid(), "startedAt": models.now_iso()}).encode("utf-8")
        try:
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        return True

    def release_lock(self) -> None:
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    # -- workspace directories ---------------------------------------------
    def workspace_dir(self, workspace_id: str) -> Path:
        d = self.workspace_base / workspace_id
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        (d / "staging").mkdir(exist_ok=True)
        (d / "exports").mkdir(exist_ok=True)
        (d / "restore_points").mkdir(exist_ok=True)
        return d

    def db_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "workspace.db"

    def list_workspace_ids(self) -> list[str]:
        if not self.workspace_base.exists():
            return []
        return sorted(
            p.name for p in self.workspace_base.iterdir()
            if p.is_dir() and (p / "workspace.db").exists()
        )

    # -- connection ----------------------------------------------------
    def connect(self, workspace_id: str) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path(workspace_id), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(_SCHEMA_TABLES_SQL)
        conn.executescript(_SCHEMA_AUDIT_SQL)
        conn.executescript(_SCHEMA_KV_SQL)
        return conn


# ---------------------------------------------------------------------------
# Generic entity read/write, keyed by table name + dataclass type.
# ---------------------------------------------------------------------------

def upsert(conn: sqlite3.Connection, table: str, entity: Any) -> None:
    assert is_dataclass(entity)
    data = models.to_jsonable(entity)
    # The Workspace entity's own `id` doubles as its `workspace_id` (a
    # workspace is not scoped *within* itself under a separate key).
    workspace_id = data.get("workspace_id", data["id"])
    extra_col = _TABLES[table]
    now = models.now_iso()
    created_at = data.get("created_at", now)
    updated_at = data.get("updated_at", now)
    if extra_col:
        extra_val = data.get(extra_col)
        conn.execute(
            f"INSERT INTO {table} (id, workspace_id, {extra_col}, seq, data, created_at, updated_at) "
            f"VALUES (?, ?, ?, COALESCE((SELECT seq FROM {table} WHERE id=?), "
            f"(SELECT COALESCE(MAX(seq),0)+1 FROM {table})), ?, ?, ?) "
            f"ON CONFLICT(id) DO UPDATE SET {extra_col}=excluded.{extra_col}, "
            f"data=excluded.data, updated_at=excluded.updated_at",
            (data["id"], workspace_id, extra_val, data["id"], json.dumps(data), created_at, updated_at),
        )
    else:
        conn.execute(
            f"INSERT INTO {table} (id, workspace_id, seq, data, created_at, updated_at) "
            f"VALUES (?, ?, COALESCE((SELECT seq FROM {table} WHERE id=?), "
            f"(SELECT COALESCE(MAX(seq),0)+1 FROM {table})), ?, ?, ?) "
            f"ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (data["id"], workspace_id, data["id"], json.dumps(data), created_at, updated_at),
        )


def get(conn: sqlite3.Connection, table: str, entity_id: str, cls: type[T]) -> Optional[T]:
    row = conn.execute(f"SELECT data FROM {table} WHERE id=?", (entity_id,)).fetchone()
    if row is None:
        return None
    return models.dataclass_from_dict(cls, json.loads(row["data"]))


def list_all(conn: sqlite3.Connection, table: str, workspace_id: str, cls: type[T]) -> list[T]:
    rows = conn.execute(
        f"SELECT data FROM {table} WHERE workspace_id=? ORDER BY seq ASC", (workspace_id,)
    ).fetchall()
    return [models.dataclass_from_dict(cls, json.loads(r["data"])) for r in rows]


def append_audit(conn: sqlite3.Connection, event: models.AuditEvent) -> None:
    conn.execute(
        "INSERT INTO audit (id, workspace_id, actor, action, subject_type, subject_id, details, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event.id, event.workspace_id, event.actor, event.action,
            event.subject_type, event.subject_id, json.dumps(event.details), event.timestamp,
        ),
    )


def tail_audit(conn: sqlite3.Connection, workspace_id: str, since: Optional[str] = None) -> list[models.AuditEvent]:
    if since:
        rows = conn.execute(
            "SELECT * FROM audit WHERE workspace_id=? AND timestamp >= ? ORDER BY seq ASC",
            (workspace_id, since),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM audit WHERE workspace_id=? ORDER BY seq ASC", (workspace_id,)
        ).fetchall()
    return [
        models.AuditEvent(
            id=r["id"], workspace_id=r["workspace_id"], actor=r["actor"], action=r["action"],
            subject_type=r["subject_type"], subject_id=r["subject_id"],
            details=json.loads(r["details"]), timestamp=r["timestamp"],
        )
        for r in rows
    ]


def commit(
    conn: sqlite3.Connection,
    table: str,
    entity: Any,
    audit_event: Optional[models.AuditEvent] = None,
) -> None:
    """The one write primitive: upsert an entity and append its audit event
    in a single SQLite transaction, so every state mutation is structurally
    audited (ARCH §8) rather than by convention."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        upsert(conn, table, entity)
        if audit_event is not None:
            append_audit(conn, audit_event)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def commit_many(
    conn: sqlite3.Connection,
    writes: Iterable[tuple[str, Any]],
    audit_events: Iterable[models.AuditEvent] = (),
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table, entity in writes:
            upsert(conn, table, entity)
        for event in audit_events:
            append_audit(conn, event)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def kv_get(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def backup_db(src_path: Path, dst_path: Path) -> None:
    """Safe-against-concurrent-readers copy using sqlite3's own backup API
    (ARCH §11), used by restore.py for restore points."""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def db_path_from_conn(conn: sqlite3.Connection) -> Path:
    row = conn.execute("PRAGMA database_list").fetchone()
    return Path(row[2])


def workspace_dir_from_conn(conn: sqlite3.Connection) -> Path:
    return db_path_from_conn(conn).parent
