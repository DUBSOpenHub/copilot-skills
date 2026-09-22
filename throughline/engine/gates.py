"""Gate Runner (ARCH §6 gate pipeline, §8, PRD §5.8 FR-GATE).

Each gate is a pure function over the current workspace snapshot; `run_gate`
persists the latest `GateResult` per gate (cached, invalidated the instant
dependent state changes because it is simply recomputed on every call —
there is no explicit invalidation step, only re-evaluation).
"""
from __future__ import annotations

from typing import Optional

from . import ingest as ingest_mod
from . import models, narrative, persistence, restore
from .errors import EngineError

BLOCKING_SOURCE_STATES = {
    models.SourceState.PROPOSED.value, models.SourceState.PERMISSION_CHECKED.value,
    models.SourceState.LABEL_CONFLICT.value, models.SourceState.PARSE_FAILED.value,
    models.SourceState.QUARANTINED.value, models.SourceState.ACCESS_REVOKED.value,
}


def _persist(conn, workspace_id: str, result: models.GateResult) -> models.GateResult:
    record = models.GateResultRecord(
        id=f"gate:{result.gate}", workspace_id=workspace_id, gate=result.gate, passed=result.passed,
        failed_checks=result.failed_checks, evaluated_at=result.evaluated_at,
        workspace_snapshot_version=result.workspace_snapshot_version, actor=result.actor,
    )
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=result.actor or "system",
        action="gate.run", subject_type="gate", subject_id=result.gate,
        details={"passed": result.passed, "failureCount": len(result.failed_checks)},
    )
    persistence.commit(conn, "gate_result", record, audit)
    if result.passed:
        # FR-DEL-7: a restore point is captured at every gate pass.
        restore.create_restore_point(conn, workspace_id, trigger=f"gate:{result.gate.lower()}", actor=result.actor)
    return result


def _snapshot_version(conn, workspace_id: str) -> int:
    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    return ws.snapshot_version if ws else 0


def run_scope_gate(conn, workspace_id: str, actor: Optional[str] = None) -> models.GateResult:
    sources = persistence.list_all(conn, "source", workspace_id, models.SourceArtifact)
    failures = []
    for s in sources:
        if s.state == models.SourceState.RETIRED.value:
            continue
        if s.state in BLOCKING_SOURCE_STATES:
            failures.append(models.GateFailure(
                code="SOURCE_UNAUTHORIZED" if s.state in (models.SourceState.PROPOSED.value, models.SourceState.PERMISSION_CHECKED.value, models.SourceState.ACCESS_REVOKED.value) else "LABEL_CONFLICT",
                message=f"source '{s.uri}' is not authorized for the current scope (state={s.state})",
                subject_id=s.id,
            ))
    result = models.GateResult(gate=models.GateName.SCOPE.value, passed=not failures, failed_checks=failures,
                                workspace_snapshot_version=_snapshot_version(conn, workspace_id), actor=actor)
    return _persist(conn, workspace_id, result)


def run_evidence_gate(conn, workspace_id: str, actor: Optional[str] = None) -> models.GateResult:
    # §16.2: staleness is re-evaluated before every EVIDENCE gate run.
    for source in persistence.list_all(conn, "source", workspace_id, models.SourceArtifact):
        ingest_mod.revalidate_staleness(conn, workspace_id, source.id, actor or "system")

    atoms = persistence.list_all(conn, "evidence", workspace_id, models.EvidenceAtom)
    failures = []
    for a in atoms:
        if a.disposition != models.Disposition.KEEP.value:
            continue
        if not a.has_required_fields():
            failures.append(models.GateFailure(code="VALIDATION_ERROR", message=f"evidence atom '{a.id}' is missing a required field", subject_id=a.id))
        if a.access_state != models.AccessState.AUTHORIZED.value:
            failures.append(models.GateFailure(code="ACCESS_REVOKED", message=f"evidence atom '{a.id}' has revoked access ({a.locator})", subject_id=a.id))
        if a.freshness_state != models.FreshnessState.FRESH.value:
            failures.append(models.GateFailure(code="SOURCE_STALE", message=f"evidence atom '{a.id}' is STALE ({a.locator})", subject_id=a.id))
    result = models.GateResult(gate=models.GateName.EVIDENCE.value, passed=not failures, failed_checks=failures,
                                workspace_snapshot_version=_snapshot_version(conn, workspace_id), actor=actor)
    return _persist(conn, workspace_id, result)


def run_narrative_gate(conn, workspace_id: str, actor: Optional[str] = None) -> models.GateResult:
    result = narrative.run_narrative_gate(conn, workspace_id, actor)
    return _persist(conn, workspace_id, result)


def run_claims_gate(conn, workspace_id: str, actor: Optional[str] = None) -> models.GateResult:
    """FR-GATE-4: every claim *externally stated* (i.e. referenced by the
    compiled deck) needs a named human approver of record."""
    slides = persistence.list_all(conn, "slide", workspace_id, models.SlideSpec)
    referenced_claim_ids: set[str] = set()
    for slide in slides:
        referenced_claim_ids.update(slide.claim_ids())
    failures = []
    for cid in referenced_claim_ids:
        claim = persistence.get(conn, "claim", cid, models.Claim)
        if claim is None:
            failures.append(models.GateFailure(code="NOT_FOUND", message=f"referenced claim '{cid}' no longer exists", subject_id=cid))
            continue
        if claim.state == models.ClaimState.UNSUPPORTED.value:
            failures.append(models.GateFailure(code="CLAIM_UNSUPPORTED", message=f"claim '{cid}' is UNSUPPORTED", subject_id=cid))
        if not claim.approver:
            failures.append(models.GateFailure(code="VALIDATION_ERROR", message=f"claim '{cid}' has no named human approver of record", subject_id=cid))
    result = models.GateResult(gate=models.GateName.CLAIMS.value, passed=not failures, failed_checks=failures,
                                workspace_snapshot_version=_snapshot_version(conn, workspace_id), actor=actor)
    return _persist(conn, workspace_id, result)


# -- Readiness (accessibility + demo fallback) -------------------------------

FOREGROUND_HEX = "#1A1A1A"
BACKGROUND_HEX = "#FFFFFF"
ACCENT_HEX = "#2E5AAC"


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    r, g, b = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la, lb = relative_luminance(hex_a), relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def run_readiness_gate(conn, workspace_id: str, actor: Optional[str] = None) -> models.GateResult:
    slides = persistence.list_all(conn, "slide", workspace_id, models.SlideSpec)
    failures = []
    body_ratio = contrast_ratio(FOREGROUND_HEX, BACKGROUND_HEX)
    headline_ratio = contrast_ratio(ACCENT_HEX, BACKGROUND_HEX)
    if body_ratio < 4.5:
        failures.append(models.GateFailure(code="ACCESSIBILITY_CHECK_FAILED", message=f"template body contrast {body_ratio:.2f}:1 is below the 4.5:1 minimum", subject_id="template"))
    if headline_ratio < 3.0:
        failures.append(models.GateFailure(code="ACCESSIBILITY_CHECK_FAILED", message=f"template headline contrast {headline_ratio:.2f}:1 is below the 3:1 minimum", subject_id="template"))

    for slide in slides:
        region_roles = set(slide.regions.keys())
        if set(slide.reading_order) != region_roles:
            failures.append(models.GateFailure(
                code="ACCESSIBILITY_CHECK_FAILED",
                message=f"slide '{slide.id}' reading order does not cover exactly its regions (missing/extra entries)",
                subject_id=slide.id,
            ))
        visual_region = slide.regions.get("visual")
        if visual_region is not None:
            if not visual_region.alt_text or not visual_region.alt_text_confirmed_by:
                failures.append(models.GateFailure(code="ACCESSIBILITY_CHECK_FAILED", message=f"slide '{slide.id}' visual region is missing human-confirmed alt text", subject_id=slide.id))
        for role, region in slide.regions.items():
            if region.uses_color_signal and not region.non_color_indicator:
                failures.append(models.GateFailure(
                    code="ACCESSIBILITY_CHECK_FAILED",
                    message=f"slide '{slide.id}' region '{role}' uses a color-only signal with no non-color indicator",
                    subject_id=slide.id,
                ))
        if slide.is_demo:
            if slide.demo_asset is None:
                failures.append(models.GateFailure(code="DEMO_FALLBACK_MISSING", message=f"demo slide '{slide.id}' has no demo asset declared at all", subject_id=slide.id))
            else:
                missing = slide.demo_asset.missing_paths()
                for path_name in missing:
                    failures.append(models.GateFailure(code="DEMO_FALLBACK_MISSING", message=f"demo slide '{slide.id}' is missing its '{path_name}' fallback path", subject_id=slide.id))

    result = models.GateResult(gate=models.GateName.READINESS.value, passed=not failures, failed_checks=failures,
                                workspace_snapshot_version=_snapshot_version(conn, workspace_id), actor=actor)
    return _persist(conn, workspace_id, result)


def run_stage_gate(conn, workspace_id: str, actor: Optional[str] = None) -> models.GateResult:
    """FR-GATE-1/FR-GATE-5: Stage requires every prior gate to currently
    pass (re-checked fresh, not from a stale cache) and a named human actor
    — never satisfiable by an automated process."""
    failures = []
    order = [
        (models.GateName.SCOPE, run_scope_gate),
        (models.GateName.EVIDENCE, run_evidence_gate),
        (models.GateName.NARRATIVE, run_narrative_gate),
        (models.GateName.CLAIMS, run_claims_gate),
        (models.GateName.READINESS, run_readiness_gate),
    ]
    for gate_name, fn in order:
        sub_result = fn(conn, workspace_id, actor)
        if not sub_result.passed:
            failures.append(models.GateFailure(
                code="GATE_NOT_PASSED",
                message=f"{gate_name.value} gate has not passed ({len(sub_result.failed_checks)} failing check(s))",
                subject_id=gate_name.value,
            ))
    if not actor or not actor.strip():
        failures.append(models.GateFailure(code="STAGE_APPROVER_REQUIRED", message="stage approval requires a named human approver"))

    result = models.GateResult(gate=models.GateName.STAGE.value, passed=not failures, failed_checks=failures,
                                workspace_snapshot_version=_snapshot_version(conn, workspace_id), actor=actor)
    persisted = _persist(conn, workspace_id, result)

    if persisted.passed:
        ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
        ws.stage_approved_by = actor
        ws.stage_approved_at = models.now_iso()
        ws.phase = models.WorkspacePhase.STAGE_APPROVED.value
        ws.reopened_reason = None
        ws.updated_at = models.now_iso()
        approval = models.ApprovalRecord(
            id=models.new_id("approval"), workspace_id=workspace_id, subject_type="workspace",
            subject_id=workspace_id, actor=actor, decision="stage_approved",
        )
        audit = models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="gate.stage_approved", subject_type="workspace", subject_id=workspace_id, details={},
        )
        persistence.commit_many(conn, [("workspace", ws), ("approval", approval)], [audit])
        # every CITED source that survived to stage approval is now APPROVED
        for source in persistence.list_all(conn, "source", workspace_id, models.SourceArtifact):
            if source.state == models.SourceState.CITED.value:
                source.state = models.SourceState.APPROVED.value
                source.updated_at = models.now_iso()
                persistence.commit(conn, "source", source, models.AuditEvent(
                    id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
                    action="source.transition", subject_type="source", subject_id=source.id,
                    details={"from": "CITED", "to": "APPROVED"},
                ))
    return persisted


GATE_FUNCTIONS = {
    models.GateName.SCOPE: run_scope_gate,
    models.GateName.EVIDENCE: run_evidence_gate,
    models.GateName.NARRATIVE: run_narrative_gate,
    models.GateName.CLAIMS: run_claims_gate,
    models.GateName.READINESS: run_readiness_gate,
    models.GateName.STAGE: run_stage_gate,
}


def run_gate(conn, workspace_id: str, gate_name: str, actor: Optional[str] = None) -> models.GateResult:
    try:
        gate = models.GateName(gate_name.upper())
    except ValueError as exc:
        raise EngineError("VALIDATION_ERROR", f"unknown gate '{gate_name}'", {"gate": gate_name}) from exc
    return GATE_FUNCTIONS[gate](conn, workspace_id, actor)


def gate_status(conn, workspace_id: str) -> list[models.GateResultRecord]:
    return persistence.list_all(conn, "gate_result", workspace_id, models.GateResultRecord)
