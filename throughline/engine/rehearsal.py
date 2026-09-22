"""Rehearsal timing/drift reporting and grounded Q&A recording (FR-DEL-1/2/3).

Not explicitly named as its own file in ARCH §5's file listing (which
folds "rehearse run" into the general command table without assigning it
a module) — implemented here as a small, focused addition so timing/drift
math and Q&A-grounding recording have one clear home rather than being
smeared across `cli.py`. Documented as a deliberate, disclosed deviation
in the implementation report.
"""
from __future__ import annotations

from typing import Optional

from . import claims as claims_mod
from . import models, persistence, workspace as workspace_mod
from .errors import EngineError


def _time_budget(slide: models.SlideSpec) -> int:
    try:
        return int(slide.regions["notes.timeBudget"].text or 0)
    except (KeyError, ValueError):
        return 0


def distribute_total_duration(slides: list[models.SlideSpec], total_actual_seconds: float) -> dict[str, float]:
    """Normalizes a `run-scenario` `rehearse` action's aggregate
    whole-rehearsal actual-duration alias (`totalSeconds`/
    `totalActualSeconds`/`totalMinutes`/... -- see
    `engine.scenario._apply_rehearsal_total_entry`) into the identical
    per-slide `timings` contract `run_rehearsal` below already expects --
    allocated proportionally to each slide's own configured
    `notes.timeBudget` (an even split across all slides if every budget is
    zero/absent), so the resulting `perSlide`/`totalActualSeconds`/
    `totalDriftSeconds` reporting is fully populated exactly as a caller
    that timed every slide individually would have produced, never a
    second, parallel reporting shape. Returns `{}` for a workspace with no
    compiled slides yet (nothing to distribute across)."""
    if not slides:
        return {}
    budgets = {slide.id: _time_budget(slide) for slide in slides}
    total_budget = sum(budgets.values())
    if total_budget <= 0:
        share = total_actual_seconds / len(slides)
        return {slide_id: share for slide_id in budgets}
    return {slide_id: total_actual_seconds * (budget / total_budget) for slide_id, budget in budgets.items()}


def _active_sources(conn, workspace_id: str) -> list[models.SourceArtifact]:
    """The workspace's current active bundle -- excludes `RETIRED` and
    superseded (stale, re-ingested-over) snapshots, mirroring
    `engine.ingest._active_source_count`'s own definition of "active"."""
    sources = persistence.list_all(conn, "source", workspace_id, models.SourceArtifact)
    return [s for s in sources if s.state != models.SourceState.RETIRED.value and not s.superseded_by]


def _source_changes_since_last_rehearsal(conn, workspace_id: str, ws: Optional[models.Workspace]) -> list[dict]:
    """FR-M365-4: "the skill detects and surfaces source changes since
    the prior rehearsal." Diffs the active bundle's current
    `uri -> contentHash` snapshot against the one captured at the end of
    this workspace's own most recent prior `run_rehearsal` call
    (`ws.rehearsal_source_snapshot`) -- keyed by `uri` rather than a
    source's own `id`, since re-ingesting a changed `uri` always mints a
    brand-new `SourceArtifact` id (the prior one is marked `STALE`/
    superseded, per FR-SRC-5/§16.2), so a `uri`-keyed diff is what
    actually captures "this same source's content changed" rather than
    misreporting it as an unrelated remove+add pair: a `uri` present now
    but absent from that snapshot is `"added"`; one present in both with
    a different `contentHash` (re-ingested/changed content, a new id
    superseding the old) is `"changed"`; one in the prior snapshot but no
    longer active now (retired, with nothing superseding it) is
    `"removed"`. Never reports anything on a workspace's *first*
    rehearsal ever (`ws.last_rehearsal_at` is still `None`) -- there is no
    prior snapshot yet to diff against, so that call only establishes the
    baseline, exactly as the FR-M365-4 acceptance criterion's own
    "modified since the *last* rehearsal" implies."""
    if ws is None or not ws.last_rehearsal_at:
        return []
    previous = ws.rehearsal_source_snapshot or {}
    current_by_uri = {s.uri: s for s in _active_sources(conn, workspace_id)}
    changes = []
    for uri, source in current_by_uri.items():
        prior_hash = previous.get(uri)
        if prior_hash is None:
            changes.append({"uri": uri, "sourceId": source.id, "status": "added"})
        elif prior_hash != source.content_hash:
            changes.append({"uri": uri, "sourceId": source.id, "status": "changed"})
    for uri in previous:
        if uri not in current_by_uri:
            changes.append({"uri": uri, "sourceId": None, "status": "removed"})
    return changes


def run_rehearsal(conn, workspace_id: str, timings: dict[str, float], actor: str, skip_demos: bool = False) -> dict:
    """FR-DEL-1: per-slide/per-beat timing with drift and overrun warnings.
    `timings` maps `slideId -> actual seconds spent`. `skip_demos=True`
    substitutes each demo slide's fallback delivery for its live path
    (ARCH §14's one-click skip-demo path, FR-DEL-4 resilience) and still
    re-checks total timing (FR-DEL-1). Also reports `sourceChanges`
    (FR-M365-4) -- see `_source_changes_since_last_rehearsal` above."""
    slides = persistence.list_all(conn, "slide", workspace_id, models.SlideSpec)
    per_slide = []
    total_actual = 0.0
    total_budget = 0.0
    for slide in sorted(slides, key=lambda s: s.order):
        budget = _time_budget(slide)
        actual = timings.get(slide.id)
        if actual is None:
            continue
        note = None
        if skip_demos and slide.is_demo:
            note = "demo skipped; static/verbal fallback timing used"
        drift = actual - budget
        per_slide.append({
            "slideId": slide.id, "role": slide.role, "budgetSeconds": budget,
            "actualSeconds": actual, "driftSeconds": drift, "overrun": drift > 0, "note": note,
        })
        total_actual += actual
        total_budget += budget

    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    result = {
        "perSlide": per_slide,
        "totalActualSeconds": total_actual,
        "totalBudgetSeconds": total_budget,
        "totalDriftSeconds": total_actual - total_budget,
        "skipDemos": skip_demos,
        "sourceChanges": _source_changes_since_last_rehearsal(conn, workspace_id, ws),
    }
    if ws is not None and ws.phase in (
        models.WorkspacePhase.COMPILED.value, models.WorkspacePhase.GATE_REVIEW.value,
    ):
        workspace_mod.set_phase(conn, workspace_id, models.WorkspacePhase.REHEARSAL, actor)

    # FR-M365-4's own snapshot: re-fetched fresh (rather than reusing the
    # `ws` read above) since `set_phase` just above may have already
    # committed its own updated copy of the same row.
    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    if ws is not None:
        ws.rehearsal_source_snapshot = {s.uri: s.content_hash for s in _active_sources(conn, workspace_id)}
        ws.last_rehearsal_at = models.now_iso()
        ws.updated_at = ws.last_rehearsal_at
        persistence.commit(conn, "workspace", ws, None)

    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="rehearse.run", subject_type="workspace", subject_id=workspace_id,
        details={"totalDriftSeconds": result["totalDriftSeconds"], "skipDemos": skip_demos},
    )
    persistence.append_audit(conn, audit)
    return result


def record_qa(conn, workspace_id: str, qa_pairs: list[dict], actor: str) -> list[dict]:
    """FR-DEL-2: rehearsal-generated Q&A, restricted to approved claims.
    The question/answer text itself is agent-authored (never the Engine's
    job); the Engine verifies every cited claim id is APPROVED/LOCKED and
    makes that grounding visible per answer (ARCH §14's acknowledged
    limit: prose faithfulness stays a speaker-review responsibility)."""
    results = []
    for qa in qa_pairs:
        question = qa.get("question", "")
        answer = qa.get("answer", "")
        claim_ids = qa.get("claimIds", []) or []
        if not question.strip():
            raise EngineError("VALIDATION_ERROR", "each Q&A pair needs a non-empty question", {})
        grounding = claims_mod.verify_grounding(conn, workspace_id, claim_ids)
        results.append({"question": question, "answer": answer, "claimIds": claim_ids, "grounding": grounding})
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="rehearse.record_qa", subject_type="workspace", subject_id=workspace_id,
        details={"count": len(results), "allGrounded": all(r["grounding"]["allGrounded"] for r in results) if results else True},
    )
    persistence.append_audit(conn, audit)
    return results
