"""Deck Compiler (ARCH §8, §9).

Turns the selected route's beat sequence into the Deck Contract
(`SlideSpec[]`) — a mechanical, deterministic mapping, never a place where
text is authored (that already happened when the route's beats were
proposed). Blocked outright unless the narrative gate currently passes
(FR-NAR-4).
"""
from __future__ import annotations

import hashlib
from typing import Optional

from . import models, narrative, persistence, restore
from .errors import EngineError

# The fixed, canonical region-role vocabulary (ARCH §9). Every slide uses a
# subset of exactly these roles, in this order, so `regionId` and
# `readingOrder` are deterministic and layout-consistent.
CANONICAL_REGION_ORDER = (
    "headline", "visual", "body",
    "notes.spoken", "notes.transitionIn", "notes.transitionOut",
    "notes.timeBudget", "notes.fallback", "notes.sources",
)
HOOK_REGION_ROLES = (
    "headline", "body",
    "notes.spoken", "notes.transitionIn", "notes.transitionOut",
    "notes.timeBudget", "notes.fallback", "notes.sources",
)
MAX_HEADLINE_CHARS = 100  # deterministic proxy for "≤2 lines" (no text-layout engine in the Engine)
DEFAULT_FALLBACK_LINE = "If this beat is cut for time, summarize the headline verbally in one sentence."


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _claim_bullet_text(claim: Optional[models.Claim], claim_id: str) -> str:
    if claim is None:
        return f"[missing claim {claim_id}]"
    prefix = ""
    if claim.type == models.ClaimType.ASPIRATIONAL.value:
        label = claim.aspirational_label or "GOAL"
        prefix = f"[{label}] "
    return f"{prefix}{claim.text}"


def _sources_for_beat(conn, workspace_id: str, beat: models.Beat) -> list[str]:
    refs: list[str] = list(dict.fromkeys(beat.source_refs))
    for claim_id in beat.claim_ids:
        claim = persistence.get(conn, "claim", claim_id, models.Claim)
        if claim is None:
            continue
        for atom_id in claim.evidence_atom_ids:
            atom = persistence.get(conn, "evidence", atom_id, models.EvidenceAtom)
            if atom is not None and atom.locator not in refs:
                refs.append(atom.locator)
    if not refs:
        refs = ["talk-brief"]
    return refs


def _build_slide(conn, workspace_id: str, deck_id: str, beat: models.Beat, total_beats: int, existing: Optional[models.SlideSpec]) -> models.SlideSpec:
    if len(beat.headline) > MAX_HEADLINE_CHARS:
        raise EngineError(
            "VALIDATION_ERROR",
            f"beat '{beat.id}' headline exceeds the ~{MAX_HEADLINE_CHARS}-character two-line limit",
            {"beatId": beat.id, "length": len(beat.headline)},
        )
    is_hook = beat.role == models.BeatRole.HOOK.value
    layout = "hook" if is_hook else "standard"
    sid = models.slide_id(deck_id, beat.order)

    if is_hook:
        body_text = beat.visual_description or beat.spoken_talk_track[:120]
        body_claim_ids: list[str] = []
    else:
        claims = [persistence.get(conn, "claim", cid, models.Claim) for cid in beat.claim_ids[:3]]
        bullets = [_claim_bullet_text(c, cid) for c, cid in zip(claims, beat.claim_ids[:3])]
        body_text = "\n".join(bullets)
        body_claim_ids = list(beat.claim_ids[:3])

    fallback = beat.fallback_line or DEFAULT_FALLBACK_LINE
    sources = _sources_for_beat(conn, workspace_id, beat)

    field_text = {
        "headline": beat.headline,
        "visual": "" if is_hook else beat.visual_description,
        "body": body_text,
        "notes.spoken": beat.spoken_talk_track,
        "notes.transitionIn": beat.transition_in,
        "notes.transitionOut": beat.transition_out,
        "notes.timeBudget": str(beat.time_budget_seconds),
        "notes.fallback": fallback,
        "notes.sources": "; ".join(sources),
    }
    roles = HOOK_REGION_ROLES if is_hook else CANONICAL_REGION_ORDER

    prior_regions = existing.regions if existing else {}
    regions: dict[str, models.Region] = {}
    for role in roles:
        text = field_text[role]
        prior = prior_regions.get(role)
        region = models.Region(
            role=role,
            text=text,
            content_hash=_content_hash(text),
            claim_ids=body_claim_ids if role == "body" else [],
        )
        if prior is not None:
            region.alt_text = prior.alt_text
            region.alt_text_confirmed_by = prior.alt_text_confirmed_by
            region.uses_color_signal = prior.uses_color_signal
            region.non_color_indicator = prior.non_color_indicator
        regions[role] = region

    reading_order = list(existing.reading_order) if existing and set(existing.reading_order) == set(roles) else list(roles)
    demo_asset = existing.demo_asset if (existing and beat.is_demo) else (models.DemoAsset(slide_id=sid) if beat.is_demo else None)

    return models.SlideSpec(
        id=sid,
        workspace_id=workspace_id,
        deck_id=deck_id,
        beat_id=beat.id,
        order=beat.order,
        role=beat.role,
        layout=layout,
        regions=regions,
        reading_order=reading_order,
        is_demo=beat.is_demo,
        demo_asset=demo_asset,
        needs_review=existing.needs_review if existing else False,
        needs_review_reason=existing.needs_review_reason if existing else None,
        created_at=existing.created_at if existing else models.now_iso(),
    )


def compile_deck(conn, workspace_id: str, actor: str) -> list[models.SlideSpec]:
    gate_result = narrative.run_narrative_gate(conn, workspace_id, actor)
    if not gate_result.passed:
        first = gate_result.failed_checks[0]
        raise EngineError(
            "NARRATIVE_GATE_FAILED",
            f"slide compilation is blocked: {first.message}",
            {"failedChecks": [models.to_jsonable(f) for f in gate_result.failed_checks]},
        )

    route = narrative.get_active_route(conn, workspace_id)
    deck_id = models.deck_id(workspace_id)
    beats = sorted(route.beats, key=lambda b: b.order)

    existing_slides = {s.id: s for s in persistence.list_all(conn, "slide", workspace_id, models.SlideSpec)}
    slides = [
        _build_slide(conn, workspace_id, deck_id, beat, len(beats), existing_slides.get(models.slide_id(deck_id, beat.order)))
        for beat in beats
    ]

    writes = [("slide", s) for s in slides]
    audits = [
        models.AuditEvent(id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
                           action="compile", subject_type="slide", subject_id=s.id, details={"beatId": s.beat_id})
        for s in slides
    ]
    persistence.commit_many(conn, writes, audits)

    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    ws.deck_id = deck_id
    ws.phase = models.WorkspacePhase.COMPILED.value
    ws.updated_at = models.now_iso()
    persistence.commit(conn, "workspace", ws, None)
    restore.create_restore_point(conn, workspace_id, trigger="compile", actor=actor)
    return slides


PROTECTED_ROLES = {models.BeatRole.HOOK.value, models.BeatRole.ASK.value}


def propose_cuts(conn, workspace_id: str, target_seconds: int) -> list[str]:
    """Greedy, deterministic cut proposal (ARCH §9 panic/cut path; FR-DEL-3).
    HOOK and ASK beats are never proposed for a cut. Returns beat ids in the
    order they should be cut to reach the target duration."""
    route = narrative.get_active_route(conn, workspace_id)
    if route is None:
        raise EngineError("VALIDATION_ERROR", "no route is selected", {})
    beats = sorted(route.beats, key=lambda b: b.order)
    total = sum(b.time_budget_seconds for b in beats)
    if total <= target_seconds:
        return []
    cuttable = sorted(
        (b for b in beats if b.role not in PROTECTED_ROLES),
        key=lambda b: (-b.time_budget_seconds, b.order),
    )
    cuts: list[str] = []
    remaining = total
    for beat in cuttable:
        if remaining <= target_seconds:
            break
        cuts.append(beat.id)
        remaining -= beat.time_budget_seconds
    return cuts


def set_alt_text(conn, workspace_id: str, slide_id: str, region_role: str, text: str, confirmed_by: str, actor: str) -> models.SlideSpec:
    slide = persistence.get(conn, "slide", slide_id, models.SlideSpec)
    if slide is None or slide.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"slide '{slide_id}' not found", {"slideId": slide_id})
    if region_role not in slide.regions:
        raise EngineError("VALIDATION_ERROR", f"slide '{slide_id}' has no region '{region_role}'", {"slideId": slide_id, "role": region_role})
    if not confirmed_by or not confirmed_by.strip():
        raise EngineError("VALIDATION_ERROR", "confirmed_by (a human name) is required", {"slideId": slide_id})
    region = slide.regions[region_role]
    region.alt_text = text
    region.alt_text_confirmed_by = confirmed_by
    slide.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="slide.set_alt_text", subject_type="slide", subject_id=slide_id, details={"role": region_role},
    )
    persistence.commit(conn, "slide", slide, audit)
    return slide


def set_reading_order(conn, workspace_id: str, slide_id: str, order: list[str], actor: str) -> models.SlideSpec:
    slide = persistence.get(conn, "slide", slide_id, models.SlideSpec)
    if slide is None or slide.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"slide '{slide_id}' not found", {"slideId": slide_id})
    region_roles = set(slide.regions.keys())
    if set(order) != region_roles or len(order) != len(set(order)):
        raise EngineError(
            "VALIDATION_ERROR",
            "reading order must be a total order over every region on the slide (no omissions, no duplicates)",
            {"slideId": slide_id, "given": order, "expected": sorted(region_roles)},
        )
    slide.reading_order = order
    slide.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="slide.set_reading_order", subject_type="slide", subject_id=slide_id, details={"order": order},
    )
    persistence.commit(conn, "slide", slide, audit)
    return slide


def set_color_signal(conn, workspace_id: str, slide_id: str, region_role: str, uses_color_signal: bool, non_color_indicator: Optional[str], actor: str) -> models.SlideSpec:
    slide = persistence.get(conn, "slide", slide_id, models.SlideSpec)
    if slide is None or slide.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"slide '{slide_id}' not found", {"slideId": slide_id})
    if region_role not in slide.regions:
        raise EngineError("VALIDATION_ERROR", f"slide '{slide_id}' has no region '{region_role}'", {"slideId": slide_id, "role": region_role})
    region = slide.regions[region_role]
    region.uses_color_signal = uses_color_signal
    region.non_color_indicator = non_color_indicator
    slide.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="slide.set_color_signal", subject_type="slide", subject_id=slide_id,
        details={"role": region_role, "usesColorSignal": uses_color_signal},
    )
    persistence.commit(conn, "slide", slide, audit)
    return slide


def set_demo_asset(
    conn, workspace_id: str, slide_id: str, actor: str,
    live_path: Optional[str] = None, prerecorded_asset_path: Optional[str] = None,
    static_asset_path: Optional[str] = None, verbal_recovery_script: Optional[str] = None,
) -> models.SlideSpec:
    slide = persistence.get(conn, "slide", slide_id, models.SlideSpec)
    if slide is None or slide.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"slide '{slide_id}' not found", {"slideId": slide_id})
    if not slide.is_demo:
        raise EngineError("VALIDATION_ERROR", f"slide '{slide_id}' is not a demo slide", {"slideId": slide_id})
    asset = slide.demo_asset or models.DemoAsset(slide_id=slide_id)
    if live_path is not None:
        asset.live_path = live_path
    if prerecorded_asset_path is not None:
        asset.prerecorded_asset_path = prerecorded_asset_path
    if static_asset_path is not None:
        asset.static_asset_path = static_asset_path
    if verbal_recovery_script is not None:
        asset.verbal_recovery_script = verbal_recovery_script
    slide.demo_asset = asset
    slide.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="slide.set_demo_asset", subject_type="slide", subject_id=slide_id, details={},
    )
    persistence.commit(conn, "slide", slide, audit)
    return slide
