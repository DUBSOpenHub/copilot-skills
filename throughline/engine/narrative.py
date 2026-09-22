"""Narrative Store + Narrative Gate (ARCH §8, §6).

Throughlines and routes are agent-authored text validated and persisted
here; the beat-spine rules that gate slide compilation (FR-NAR-4) are the
one piece of genuine rule-engine logic in this module.
"""
from __future__ import annotations

from typing import Optional

from . import models, persistence
from .errors import EngineError

REQUIRED_THROUGHLINE_COUNT = 3
VALID_ROUTE_COUNT = (2, 3)
MIN_SLIDES = 7
MAX_SLIDES = 15
MIN_TIME_BUFFER_RATIO = 0.10
VERIFIED_OR_BETTER = {
    models.ClaimState.VERIFIED.value, models.ClaimState.REVIEWED.value,
    models.ClaimState.APPROVED.value, models.ClaimState.LOCKED.value,
}


def default_throughline_drafts(brief: Optional[models.TalkBrief]) -> list[str]:
    """Deterministic fallback for FR-NAR-1 ("from the talk brief, the
    skill proposes exactly three candidate throughlines"), reused by every
    public entry point that proposes throughlines without already having
    its own three drafts in hand -- normally the Skill Prompt Layer's job
    (this module's own docstring: `propose_*` functions never generate
    text themselves). This is a separate, pure function of the brief that
    a caller (`cli.cmd_narrative_propose_throughlines` with no `--input`,
    or `scenario._run_steps` with no `throughlineDrafts`) passes *into*
    `propose_throughlines` exactly like any other drafts list -- it never
    persists anything itself and `propose_throughlines`'s own contract
    (exactly `REQUIRED_THROUGHLINE_COUNT`, non-empty, validated and
    persisted the same way regardless of who supplied the drafts) is
    unchanged.

    Always returns exactly `REQUIRED_THROUGHLINE_COUNT` distinct,
    non-empty strings derived from the brief's own fields (never a static
    placeholder) -- the same brief always yields the same three
    candidates, with graceful wording even for a still-incomplete brief."""
    takeaway = (brief.takeaway if brief else "") or "the core idea of this talk"
    audience = (brief.audience if brief else "") or "the audience"
    event_type = (brief.event_type if brief else "") or "session"
    tone = (brief.tone if brief else "") or "direct"
    proof_points = [p for p in ((brief.proof_points if brief else None) or []) if p]
    proof_point = proof_points[0] if proof_points else takeaway

    candidates = [
        f"{takeaway} — a {tone} throughline for {audience}",
        f"What {audience} need to walk away knowing: {takeaway}",
        f"Proof first: {proof_point}, then why it matters for {audience}",
    ]
    seen: set[str] = set()
    drafts: list[str] = []
    for position, candidate in enumerate(candidates):
        text = candidate.strip() or f"Candidate throughline {position + 1} for this {event_type}"
        while text in seen:
            text = f"{text} ({position + 1})"
        seen.add(text)
        drafts.append(text)
    return drafts


def propose_throughlines(conn, workspace_id: str, brief_id: str, drafts: list[str], actor: str) -> list[models.NarrativeThroughline]:
    if len(drafts) != REQUIRED_THROUGHLINE_COUNT:
        raise EngineError(
            "VALIDATION_ERROR",
            f"exactly {REQUIRED_THROUGHLINE_COUNT} throughline candidates are required (got {len(drafts)})",
            {"count": len(drafts)},
        )
    if any(not (d or "").strip() for d in drafts):
        raise EngineError("VALIDATION_ERROR", "throughline candidates must not be empty", {})

    candidates = [
        models.NarrativeThroughline(id=models.new_id("throughline"), workspace_id=workspace_id,
                                     brief_id=brief_id, text=d.strip(), origin="proposed")
        for d in drafts
    ]
    writes = [("throughline", c) for c in candidates]
    audits = [
        models.AuditEvent(id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
                           action="narrative.propose_throughlines", subject_type="throughline", subject_id=c.id, details={})
        for c in candidates
    ]
    persistence.commit_many(conn, writes, audits)
    return candidates


def select_throughline(
    conn, workspace_id: str, actor: str,
    throughline_id: Optional[str] = None, custom_text: Optional[str] = None,
) -> models.NarrativeThroughline:
    existing = persistence.list_all(conn, "throughline", workspace_id, models.NarrativeThroughline)
    if custom_text and custom_text.strip():
        brief_id = existing[0].brief_id if existing else ""
        selected = models.NarrativeThroughline(
            id=models.new_id("throughline"), workspace_id=workspace_id, brief_id=brief_id,
            text=custom_text.strip(), origin="custom", selected=True,
        )
        writes = [("throughline", selected)]
    elif throughline_id:
        match = next((t for t in existing if t.id == throughline_id), None)
        if match is None:
            raise EngineError("NOT_FOUND", f"throughline '{throughline_id}' not found", {"throughlineId": throughline_id})
        match.selected = True
        selected = match
        writes = [("throughline", selected)]
    else:
        raise EngineError("VALIDATION_ERROR", "either throughline_id or custom_text is required", {})

    for t in existing:
        if t.id != selected.id and t.selected:
            t.selected = False
            writes.append(("throughline", t))

    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="narrative.select_throughline", subject_type="throughline", subject_id=selected.id,
        details={"origin": selected.origin},
    )
    persistence.commit_many(conn, writes, [audit])

    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    ws.active_throughline_id = selected.id
    if ws.phase == models.WorkspacePhase.NARRATIVE_SELECTION.value:
        ws.phase = models.WorkspacePhase.ROUTE_SELECTION.value
    ws.updated_at = models.now_iso()
    persistence.commit(conn, "workspace", ws, None)
    return selected


_ROUTE_BEAT_HEADLINE_TEMPLATES = {
    "HOOK": "Why {audience} should lean in right now",
    "STAKES": "What is at risk if {takeaway} goes unaddressed",
    # Used only when a PROOF slot has no qualifying claim and is replaced
    # by a second STAKES beat (see `_spine` below) -- kept distinct from
    # the primary "STAKES" headline above so the two beats never read
    # identically within the same route.
    "STAKES_SECONDARY": "Why this matters most for {audience}",
    "TURN": "The shift that changes the {event_type}",
    "MECHANISM": "How {throughline_text} actually works",
    "PROOF": "The evidence behind this claim",
    "OBJECTION": "Addressing the most likely objection",
    "ASK": "What {audience} should do next",
}
# Two distinct, narrative-gate-passable 7-beat spines (FR-NAR-4: one
# opening HOOK, one closing ASK, no two adjacent beats sharing a role) --
# `PROOF` is only used when a qualifying claim exists (see
# `default_route_drafts` below); a plain second `STAKES` beat takes its
# slot otherwise, never an uncited/empty PROOF beat.
_PRIMARY_ROUTE_ROLE_ORDER = ["HOOK", "STAKES", "TURN", "MECHANISM", "PROOF", "OBJECTION", "ASK"]
_ALTERNATE_ROUTE_ROLE_ORDER = ["HOOK", "TURN", "STAKES", "MECHANISM", "OBJECTION", "PROOF", "ASK"]
DEFAULT_ROUTE_BEAT_SECONDS = 20  # low, fixed budget -- safely under the >=10% time-buffer rule for any realistic brief duration
# Every template above interpolates at most one brief/throughline-derived
# field into a short, fixed surrounding phrase -- truncating each
# interpolated value to this length keeps every resulting headline safely
# under the Compiler's own `MAX_HEADLINE_CHARS` (100) regardless of how
# long the caller's own brief/throughline text is (never a raw crash from
# an over-length beat headline, `engine.compiler._build_slide`).
_HEADLINE_FIELD_MAX_CHARS = 40


def _truncated_for_headline(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= _HEADLINE_FIELD_MAX_CHARS:
        return text
    return text[: _HEADLINE_FIELD_MAX_CHARS - 1].rstrip() + "…"


def default_route_drafts(
    brief: Optional[models.TalkBrief],
    throughline: Optional[models.NarrativeThroughline],
    claims: Optional[list[models.Claim]] = None,
) -> list[dict]:
    """Deterministic fallback for FR-NAR-3 ("the skill proposes two or
    three narrative routes"), mirroring `default_throughline_drafts`
    above for the parallel route step: `propose_routes` itself never
    generates beats, it only validates and persists whatever drafts it is
    given -- this is a separate, pure function of the brief/throughline/
    claims a caller (`scenario._run_steps`, when a *source-driven*
    scenario stages no `routeDrafts`/`propose_route` entries of its own)
    passes *into* `propose_routes` exactly like any other drafts list.

    Deliberately narrower than the throughline fallback: it is only ever
    invoked for a scenario that has actually ingested at least one source
    (see the call site) -- a bare brief with no source/claim context at
    all still gets no default routes and is correctly refused for missing
    routes exactly as before (`tests/test_candidate_persistence_on_
    refusal.py`, `tests/test_default_throughline_generation.py`'s own
    `ScenarioRunnerDefaultGenerationTests` pin this pre-existing
    behavior). This keeps FR-NAR-3's "none auto-selects" intact too: this
    function only proposes candidates, exactly like
    `default_throughline_drafts` does -- selection is a wholly separate,
    unaffected, later step.

    Always returns exactly 2 real, brief/throughline-derived route
    drafts, each a full, narrative-gate-passable beat spine (one HOOK
    opening, one closing ASK, no adjacent-role repeats, low fixed
    per-beat time budgets that leave the required >=10% buffer for any
    realistic brief duration, and headlines that always stay within the
    Compiler's own length limit -- see `_truncated_for_headline` above).
    A PROOF beat citing the first already-approved, verified-or-better
    factual claim among `claims` is included only when one exists;
    otherwise the PROOF slot is skipped in favor of a second STAKES beat
    -- never a guessed/synthesized or uncited claim reference."""
    audience = _truncated_for_headline((brief.audience if brief else "") or "the audience")
    takeaway = _truncated_for_headline((brief.takeaway if brief else "") or "the core idea of this talk")
    event_type = _truncated_for_headline((brief.event_type if brief else "") or "session")
    throughline_text = _truncated_for_headline((throughline.text if throughline else "") or takeaway)

    proof_claim_id = next(
        (
            c.id for c in (claims or [])
            if c and c.type == models.ClaimType.FACTUAL.value and c.state in VERIFIED_OR_BETTER and c.approver
        ),
        None,
    )

    def _spine(role_order: list[str]) -> list[dict]:
        beats = []
        for role in role_order:
            if role == "PROOF" and not proof_claim_id:
                actual_role, headline_key = "STAKES", "STAKES_SECONDARY"
            else:
                actual_role, headline_key = role, role
            headline = _ROUTE_BEAT_HEADLINE_TEMPLATES[headline_key].format(
                audience=audience, takeaway=takeaway, event_type=event_type, throughline_text=throughline_text,
            )
            beat = {"role": actual_role, "headline": headline, "timeBudgetSeconds": DEFAULT_ROUTE_BEAT_SECONDS}
            if actual_role == "PROOF":
                beat["claimIds"] = [proof_claim_id]
            beats.append(beat)
        return beats

    return [
        {"label": "Primary route", "beats": _spine(_PRIMARY_ROUTE_ROLE_ORDER)},
        {"label": "Alternate route", "beats": _spine(_ALTERNATE_ROUTE_ROLE_ORDER)},
    ]


def _beat_from_draft(route_id: str, order: int, draft: dict) -> models.Beat:
    role = (draft.get("role") or "").strip().upper()
    if role not in {r.value for r in models.BeatRole}:
        raise EngineError("VALIDATION_ERROR", f"beat role '{draft.get('role')}' is invalid", {"role": draft.get("role")})
    headline = (draft.get("headline") or "").strip()
    if not headline:
        raise EngineError("VALIDATION_ERROR", "every beat needs a non-empty headline", {"order": order})
    claim_ids = list(draft.get("claimIds", []) or [])
    if len(claim_ids) > 3:
        raise EngineError("VALIDATION_ERROR", "a beat may reference at most 3 claims (FR-PPT-2)", {"order": order, "count": len(claim_ids)})
    return models.Beat(
        id=models.new_id("beat"),
        route_id=route_id,
        order=order,
        role=role,
        headline=headline,
        claim_ids=claim_ids,
        spoken_talk_track=draft.get("spokenTalkTrack", "") or "",
        transition_in=draft.get("transitionIn", "") or "",
        transition_out=draft.get("transitionOut", "") or "",
        time_budget_seconds=int(draft.get("timeBudgetSeconds", 60) or 60),
        fallback_line=draft.get("fallbackLine", "") or "",
        source_refs=list(draft.get("sourceRefs", []) or []),
        visual_description=draft.get("visualDescription", "") or "",
        is_demo=bool(draft.get("isDemo", False)),
    )


def propose_routes(conn, workspace_id: str, throughline_id: str, drafts: list[dict], actor: str) -> list[models.NarrativeRoute]:
    if len(drafts) not in VALID_ROUTE_COUNT:
        raise EngineError(
            "VALIDATION_ERROR",
            f"exactly 2 or 3 narrative routes are required (got {len(drafts)})",
            {"count": len(drafts)},
        )
    routes = []
    writes = []
    audits = []
    for draft in drafts:
        route_id = models.new_id("route")
        beats = [_beat_from_draft(route_id, i, b) for i, b in enumerate(draft.get("beats", []) or [])]
        if not beats:
            raise EngineError("VALIDATION_ERROR", "each route needs at least one beat", {})
        route = models.NarrativeRoute(
            id=route_id, workspace_id=workspace_id, throughline_id=throughline_id,
            label=draft.get("label", "") or "Untitled route", beats=beats,
        )
        routes.append(route)
        writes.append(("route", route))
        audits.append(models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="narrative.propose_routes", subject_type="route", subject_id=route.id,
            details={"beatCount": len(beats)},
        ))
    persistence.commit_many(conn, writes, audits)
    return routes


def select_route(conn, workspace_id: str, route_id: str, actor: str) -> models.NarrativeRoute:
    existing = persistence.list_all(conn, "route", workspace_id, models.NarrativeRoute)
    match = next((r for r in existing if r.id == route_id), None)
    if match is None:
        raise EngineError("NOT_FOUND", f"route '{route_id}' not found", {"routeId": route_id})
    writes = []
    for r in existing:
        want = r.id == route_id
        if r.selected != want:
            r.selected = want
            writes.append(("route", r))
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="narrative.select_route", subject_type="route", subject_id=route_id, details={},
    )
    persistence.commit_many(conn, writes, [audit])

    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    ws.active_route_id = route_id
    ws.updated_at = models.now_iso()
    persistence.commit(conn, "workspace", ws, None)
    return match


def get_active_route(conn, workspace_id: str) -> Optional[models.NarrativeRoute]:
    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    if ws is None or not ws.active_route_id:
        return None
    return persistence.get(conn, "route", ws.active_route_id, models.NarrativeRoute)


def run_narrative_gate(conn, workspace_id: str, actor: Optional[str] = None) -> models.GateResult:
    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    route = get_active_route(conn, workspace_id)
    failures: list[models.GateFailure] = []

    if route is None:
        failures.append(models.GateFailure(code="NARRATIVE_GATE_FAILED", message="no route has been selected"))
        return _finalize(conn, workspace_id, failures, actor, ws.snapshot_version if ws else 0)

    beats = sorted(route.beats, key=lambda b: b.order)
    brief = persistence.get(conn, "brief", ws.brief_id, models.TalkBrief) if ws and ws.brief_id else None

    if not (MIN_SLIDES <= len(beats) <= MAX_SLIDES):
        failures.append(models.GateFailure(
            code="NARRATIVE_GATE_FAILED",
            message=f"route has {len(beats)} beats; a compiled deck must have {MIN_SLIDES}-{MAX_SLIDES} slides",
            subject_id=route.id,
        ))

    hook_beats = [b for b in beats if b.role == models.BeatRole.HOOK.value]
    if len(hook_beats) != 1:
        failures.append(models.GateFailure(code="NARRATIVE_GATE_FAILED", message=f"route must have exactly one HOOK beat (found {len(hook_beats)})", subject_id=route.id))
    elif beats[0].role != models.BeatRole.HOOK.value:
        failures.append(models.GateFailure(code="NARRATIVE_GATE_FAILED", message="the HOOK beat must open the route", subject_id=hook_beats[0].id))

    ask_beats = [b for b in beats if b.role == models.BeatRole.ASK.value]
    if len(ask_beats) != 1:
        failures.append(models.GateFailure(code="NARRATIVE_GATE_FAILED", message=f"route must have exactly one closing ASK beat (found {len(ask_beats)})", subject_id=route.id))
    elif beats[-1].role != models.BeatRole.ASK.value:
        failures.append(models.GateFailure(code="NARRATIVE_GATE_FAILED", message="the ASK beat must close the route", subject_id=ask_beats[0].id))

    for i in range(len(beats) - 1):
        if beats[i].role == beats[i + 1].role:
            failures.append(models.GateFailure(
                code="NARRATIVE_GATE_FAILED",
                message=f"adjacent beats at positions {i} and {i + 1} both have job '{beats[i].role}' (beat-job collision)",
                subject_id=beats[i + 1].id,
            ))

    claim_cache: dict[str, Optional[models.Claim]] = {}

    def _claim(cid: str) -> Optional[models.Claim]:
        if cid not in claim_cache:
            claim_cache[cid] = persistence.get(conn, "claim", cid, models.Claim)
        return claim_cache[cid]

    for beat in beats:
        if beat.role == models.BeatRole.PROOF.value:
            verified_factual = False
            for cid in beat.claim_ids:
                claim = _claim(cid)
                if claim and claim.type == models.ClaimType.FACTUAL.value and claim.state in VERIFIED_OR_BETTER:
                    verified_factual = True
                    break
            if not verified_factual:
                failures.append(models.GateFailure(
                    code="NARRATIVE_GATE_FAILED",
                    message=f"PROOF beat '{beat.id}' has no verified factual claim",
                    subject_id=beat.id,
                ))
        for cid in beat.claim_ids:
            claim = _claim(cid)
            if claim and claim.type == models.ClaimType.ASPIRATIONAL.value and not claim.aspirational_label:
                failures.append(models.GateFailure(
                    code="NARRATIVE_GATE_FAILED",
                    message=f"aspirational claim '{cid}' referenced by beat '{beat.id}' has no visible label",
                    subject_id=cid,
                ))

    if brief is not None and brief.duration_minutes:
        total_available = brief.duration_minutes * 60
        allocated = sum(b.time_budget_seconds for b in beats)
        buffer_ratio = 1 - (allocated / total_available) if total_available > 0 else 0
        if buffer_ratio < MIN_TIME_BUFFER_RATIO:
            failures.append(models.GateFailure(
                code="NARRATIVE_GATE_FAILED",
                message=(
                    f"only {buffer_ratio * 100:.1f}% time buffer remains "
                    f"({allocated}s allocated of {total_available:.0f}s available); "
                    f"at least {MIN_TIME_BUFFER_RATIO * 100:.0f}% must remain"
                ),
                subject_id=route.id,
            ))

    return _finalize(conn, workspace_id, failures, actor, ws.snapshot_version if ws else 0)


def _finalize(conn, workspace_id: str, failures: list[models.GateFailure], actor: Optional[str], snapshot_version: int) -> models.GateResult:
    return models.GateResult(
        gate=models.GateName.NARRATIVE.value,
        passed=not failures,
        failed_checks=failures,
        workspace_snapshot_version=snapshot_version,
        actor=actor,
    )
