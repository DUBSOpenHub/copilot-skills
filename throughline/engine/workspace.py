"""Workspace Controller: phase FSM, single-active-workspace lock, and talk
brief lifecycle (ARCH §3, §6, §11; PRD FR-INV-1, NFR-2).
"""
from __future__ import annotations

from typing import Optional

from . import models, persistence, strings
from .errors import EngineError
from .persistence import Store

REQUIRED_BRIEF_FIELDS = ("audience", "event_type", "takeaway")

NEXT_ACTION = {
    models.WorkspacePhase.BRIEFING: "Provide the talk brief: audience, event/session type, duration, takeaway, required proof points, excluded topics, and tone.",
    models.WorkspacePhase.SOURCING: "Add curated sources to the bundle (up to 25 artifacts), then extract evidence from each.",
    models.WorkspacePhase.EVIDENCE_REVIEW: "Set a disposition (keep/quarantine/reject) for every evidence atom.",
    models.WorkspacePhase.CLAIM_REVIEW: "Propose and classify claims from kept evidence; resolve any conflict cards.",
    models.WorkspacePhase.NARRATIVE_SELECTION: "Review the three proposed throughlines and select, edit, or author one.",
    models.WorkspacePhase.ROUTE_SELECTION: "Review the proposed narrative routes and select one.",
    models.WorkspacePhase.COMPILED: "Run the gate pipeline (scope, evidence, narrative, claims) before rehearsal.",
    models.WorkspacePhase.GATE_REVIEW: "Resolve any failing gates, then proceed to rehearsal.",
    models.WorkspacePhase.REHEARSAL: "Rehearse the deck and record actual per-slide timings.",
    models.WorkspacePhase.READINESS_REVIEW: "Complete accessibility and demo-fallback checks for every slide.",
    models.WorkspacePhase.STAGE_APPROVED: "Export the full 9-artifact stage package.",
    models.WorkspacePhase.PACKAGED: "Stage package is ready. Review exported artifacts, or rehearse again.",
}


def _brief_from_payload(workspace_id: str, payload: dict) -> models.TalkBrief:
    return models.TalkBrief(
        id=models.new_id("brief"),
        workspace_id=workspace_id,
        audience=payload.get("audience", "") or "",
        event_type=payload.get("eventType", "") or "",
        duration_minutes=float(payload.get("durationMinutes", 20) or 20),
        takeaway=payload.get("takeaway", "") or "",
        proof_points=list(payload.get("proofPoints", []) or []),
        excluded_topics=list(payload.get("excludedTopics", []) or []),
        tone=payload.get("tone", "") or "",
    )


def _brief_is_complete(brief: models.TalkBrief) -> bool:
    return bool(brief.audience and brief.event_type and brief.takeaway and brief.duration_minutes)


def next_action_for(workspace: models.Workspace) -> str:
    if workspace.reopened_reason:
        return f"Resolve reopened item before continuing: {workspace.reopened_reason}"
    return NEXT_ACTION.get(models.WorkspacePhase(workspace.phase), "Continue to the next step.")


def create_workspace(store: Store, actor: str, brief_payload: Optional[dict] = None) -> tuple[models.Workspace, models.TalkBrief]:
    workspace_id = models.new_id("workspace")
    if not store.try_acquire_lock(workspace_id):
        # Lost the atomic race (or a live lock already exists): report the
        # actual current holder, never our own not-yet-used candidate id.
        current = store.read_lock()
        active_id = current.get("workspaceId") if current else "unknown"
        raise EngineError(
            "WORKSPACE_ALREADY_ACTIVE",
            strings.WORKSPACE_ALREADY_ACTIVE.format(workspace_id=active_id),
            {"workspaceId": active_id},
        )
    conn = store.connect(workspace_id)
    try:
        if brief_payload:
            brief = _brief_from_payload(workspace_id, brief_payload)
        else:
            brief = models.TalkBrief(id=models.new_id("brief"), workspace_id=workspace_id)
        phase = models.WorkspacePhase.SOURCING.value if _brief_is_complete(brief) else models.WorkspacePhase.BRIEFING.value
        ws = models.Workspace(id=workspace_id, phase=phase, brief_id=brief.id)
        audits = [
            models.AuditEvent(id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
                               action="workspace.create", subject_type="workspace", subject_id=workspace_id, details={}),
            models.AuditEvent(id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
                               action="brief.create", subject_type="brief", subject_id=brief.id, details={}),
        ]
        persistence.commit_many(conn, [("workspace", ws), ("brief", brief)], audits)
    except Exception:
        store.release_lock()  # roll back the lock we just won if setup failed
        raise
    finally:
        conn.close()
    return ws, brief


def show_workspace(store: Store) -> Optional[dict]:
    workspace_id = store.active_workspace_id()
    if not workspace_id:
        return None
    conn = store.connect(workspace_id)
    try:
        ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
        if ws is None:
            return None
        brief = persistence.get(conn, "brief", ws.brief_id, models.TalkBrief) if ws.brief_id else None
    finally:
        conn.close()
    return {"workspace": ws, "brief": brief, "nextAction": next_action_for(ws)}


def require_active_workspace(store: Store) -> str:
    workspace_id = store.active_workspace_id()
    if not workspace_id:
        raise EngineError(
            "NO_ACTIVE_WORKSPACE",
            f"No active talk workspace. Run 'workspace new' to open one ({strings.PRODUCT_NAME}).",
            {},
        )
    return workspace_id


def set_brief(conn, workspace_id: str, payload: dict, actor: str) -> tuple[models.Workspace, models.TalkBrief]:
    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    if ws is None:
        raise EngineError("NOT_FOUND", f"workspace '{workspace_id}' not found", {})
    brief = persistence.get(conn, "brief", ws.brief_id, models.TalkBrief)
    for field_name, key in (
        ("audience", "audience"), ("event_type", "eventType"), ("takeaway", "takeaway"), ("tone", "tone"),
    ):
        if key in payload and payload[key] is not None:
            setattr(brief, field_name, payload[key])
    if "durationMinutes" in payload and payload["durationMinutes"] is not None:
        brief.duration_minutes = float(payload["durationMinutes"])
    if "proofPoints" in payload and payload["proofPoints"] is not None:
        brief.proof_points = list(payload["proofPoints"])
    if "excludedTopics" in payload and payload["excludedTopics"] is not None:
        brief.excluded_topics = list(payload["excludedTopics"])
    brief.updated_at = models.now_iso()

    writes = [("brief", brief)]
    audits = [models.AuditEvent(id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
                                 action="brief.update", subject_type="brief", subject_id=brief.id, details={})]
    if ws.phase == models.WorkspacePhase.BRIEFING.value and _brief_is_complete(brief):
        ws.phase = models.WorkspacePhase.SOURCING.value
        ws.updated_at = models.now_iso()
        writes.append(("workspace", ws))
        audits.append(models.AuditEvent(id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
                                         action="workspace.phase", subject_type="workspace", subject_id=workspace_id,
                                         details={"to": ws.phase}))
    persistence.commit_many(conn, writes, audits)
    return ws, brief


def set_phase(conn, workspace_id: str, phase: models.WorkspacePhase, actor: str, clear_reopen: bool = False) -> models.Workspace:
    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    if ws is None:
        raise EngineError("NOT_FOUND", f"workspace '{workspace_id}' not found", {})
    previous = ws.phase
    ws.phase = phase.value
    ws.snapshot_version += 1
    ws.updated_at = models.now_iso()
    if clear_reopen:
        ws.reopened_reason = None
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="workspace.phase", subject_type="workspace", subject_id=workspace_id,
        details={"from": previous, "to": ws.phase},
    )
    persistence.commit(conn, "workspace", ws, audit)
    return ws


def reopen(conn, workspace_id: str, reason: str, actor: str) -> models.Workspace:
    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    if ws is None:
        raise EngineError("NOT_FOUND", f"workspace '{workspace_id}' not found", {})
    ws.reopened_reason = reason
    ws.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="workspace.reopen", subject_type="workspace", subject_id=workspace_id, details={"reason": reason},
    )
    persistence.commit(conn, "workspace", ws, audit)
    return ws


def bump_snapshot_version(conn, workspace_id: str, actor: str) -> int:
    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    ws.snapshot_version += 1
    ws.updated_at = models.now_iso()
    persistence.commit(conn, "workspace", ws, None)
    return ws.snapshot_version


def reset_active_workspace(store: Store, actor: str) -> Optional[str]:
    """Releases the single-workspace lock (ARCH §16.3: 'or an explicit
    workspace reset'). Data on disk is never deleted — only the lock is
    freed so a new `workspace new` may proceed."""
    workspace_id = store.active_workspace_id()
    if workspace_id:
        conn = store.connect(workspace_id)
        try:
            audit = models.AuditEvent(
                id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
                action="workspace.reset", subject_type="workspace", subject_id=workspace_id, details={},
            )
            persistence.append_audit(conn, audit)
        finally:
            conn.close()
    store.release_lock()
    return workspace_id


def resume_workspace(store: Store, workspace_id: str, actor: str) -> dict:
    if workspace_id not in store.list_workspace_ids():
        raise EngineError("NOT_FOUND", f"workspace '{workspace_id}' has no on-disk data", {"workspaceId": workspace_id})
    current = store.read_lock()
    if current is None or current.get("workspaceId") != workspace_id:
        if not store.try_acquire_lock(workspace_id):
            current = store.read_lock()
            active_id = current.get("workspaceId") if current else "unknown"
            if active_id != workspace_id:
                raise EngineError(
                    "WORKSPACE_ALREADY_ACTIVE",
                    strings.WORKSPACE_ALREADY_ACTIVE.format(workspace_id=active_id),
                    {"workspaceId": active_id},
                )
    result = show_workspace(store)
    if result is None:
        raise EngineError("NOT_FOUND", f"workspace '{workspace_id}' could not be loaded", {"workspaceId": workspace_id})
    return result
