"""Dataclasses and enums for every Throughline entity, plus the state-machine
transition tables from ARCH.md §6. This module has no I/O — it is pure data
shape and pure validation functions, which is what makes it independently
unit-testable (tests/test_models.py).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Optional, Union, get_args, get_origin, get_type_hints


def new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def is_reachable(transitions: dict, start: Any, target: Any) -> bool:
    """BFS over a transition table; used both by unit tests (verifying the
    table's own shape) and defensively at runtime to guarantee a computed
    target state is actually reachable from the entity's known origin."""
    if start == target:
        return True
    seen = {start}
    frontier = [start]
    while frontier:
        nxt = []
        for s in frontier:
            for t in transitions.get(s, set()):
                if t == target:
                    return True
                if t not in seen:
                    seen.add(t)
                    nxt.append(t)
        frontier = nxt
    return False


def deck_id(workspace_id: str) -> str:
    return f"deck:{workspace_id}"


def slide_id(deck_id_: str, beat_order: int) -> str:
    return f"{deck_id_}:{beat_order}"


def region_id(slide_id_: str, role: str) -> str:
    return f"{slide_id_}:{role}"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WorkspacePhase(str, Enum):
    BRIEFING = "BRIEFING"
    SOURCING = "SOURCING"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    CLAIM_REVIEW = "CLAIM_REVIEW"
    NARRATIVE_SELECTION = "NARRATIVE_SELECTION"
    ROUTE_SELECTION = "ROUTE_SELECTION"
    COMPILED = "COMPILED"
    GATE_REVIEW = "GATE_REVIEW"
    REHEARSAL = "REHEARSAL"
    READINESS_REVIEW = "READINESS_REVIEW"
    STAGE_APPROVED = "STAGE_APPROVED"
    PACKAGED = "PACKAGED"


# Forward-only ordering of the "happy path" phase FSM. A phase may always be
# revisited (e.g. after REOPENED) by explicit engine action; this list is
# used only to compute "next required action" messaging and to validate that
# advance_phase() never jumps backward silently.
WORKSPACE_PHASE_ORDER = [
    WorkspacePhase.BRIEFING,
    WorkspacePhase.SOURCING,
    WorkspacePhase.EVIDENCE_REVIEW,
    WorkspacePhase.CLAIM_REVIEW,
    WorkspacePhase.NARRATIVE_SELECTION,
    WorkspacePhase.ROUTE_SELECTION,
    WorkspacePhase.COMPILED,
    WorkspacePhase.GATE_REVIEW,
    WorkspacePhase.REHEARSAL,
    WorkspacePhase.READINESS_REVIEW,
    WorkspacePhase.STAGE_APPROVED,
    WorkspacePhase.PACKAGED,
]


class SourceState(str, Enum):
    PROPOSED = "PROPOSED"
    PERMISSION_CHECKED = "PERMISSION_CHECKED"
    AUTHORIZED = "AUTHORIZED"
    RETRIEVED = "RETRIEVED"
    NORMALIZED = "NORMALIZED"
    CURATED = "CURATED"
    CITED = "CITED"
    APPROVED = "APPROVED"
    # Exceptions
    ACCESS_REVOKED = "ACCESS_REVOKED"
    STALE = "STALE"
    LABEL_CONFLICT = "LABEL_CONFLICT"
    PARSE_FAILED = "PARSE_FAILED"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


SOURCE_MAIN_PATH = [
    SourceState.PROPOSED,
    SourceState.PERMISSION_CHECKED,
    SourceState.AUTHORIZED,
    SourceState.RETRIEVED,
    SourceState.NORMALIZED,
    SourceState.CURATED,
    SourceState.CITED,
    SourceState.APPROVED,
]
SOURCE_EXCEPTION_STATES = {
    SourceState.ACCESS_REVOKED,
    SourceState.STALE,
    SourceState.LABEL_CONFLICT,
    SourceState.PARSE_FAILED,
    SourceState.QUARANTINED,
    SourceState.RETIRED,
}

# Allowed transitions: main path is strictly forward one step at a time;
# any main-path state may fall into any exception state; QUARANTINED and
# STALE sources may be resolved back onto the main path at AUTHORIZED
# (re-verified) by explicit user/engine action; RETIRED is terminal.
SOURCE_TRANSITIONS: dict[SourceState, set[SourceState]] = {}
for _i, _s in enumerate(SOURCE_MAIN_PATH):
    _nxt = set()
    if _i + 1 < len(SOURCE_MAIN_PATH):
        _nxt.add(SOURCE_MAIN_PATH[_i + 1])
    _nxt |= SOURCE_EXCEPTION_STATES
    SOURCE_TRANSITIONS[_s] = _nxt
SOURCE_TRANSITIONS[SourceState.ACCESS_REVOKED] = {SourceState.RETIRED}
SOURCE_TRANSITIONS[SourceState.STALE] = {SourceState.AUTHORIZED, SourceState.RETIRED}
SOURCE_TRANSITIONS[SourceState.LABEL_CONFLICT] = {SourceState.AUTHORIZED, SourceState.RETIRED, SourceState.QUARANTINED}
SOURCE_TRANSITIONS[SourceState.PARSE_FAILED] = {SourceState.RETIRED, SourceState.AUTHORIZED}
SOURCE_TRANSITIONS[SourceState.QUARANTINED] = {SourceState.AUTHORIZED, SourceState.RETIRED}
SOURCE_TRANSITIONS[SourceState.RETIRED] = set()


class ClaimType(str, Enum):
    FACTUAL = "FACTUAL"
    INTERPRETIVE = "INTERPRETIVE"
    ASPIRATIONAL = "ASPIRATIONAL"


ASPIRATIONAL_LABELS = ("GOAL", "INTENT", "RECOMMENDATION")


class ClaimState(str, Enum):
    DRAFT = "DRAFT"
    CLASSIFIED = "CLASSIFIED"
    EVIDENCE_LINKED = "EVIDENCE_LINKED"
    VERIFIED = "VERIFIED"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    # Exceptions
    UNSUPPORTED = "UNSUPPORTED"
    CONTESTED = "CONTESTED"
    CONFLICTED = "CONFLICTED"
    STALE = "STALE"
    RESTRICTED = "RESTRICTED"
    REWRITE_REQUIRED = "REWRITE_REQUIRED"
    RETIRED = "RETIRED"


CLAIM_MAIN_PATH = [
    ClaimState.DRAFT,
    ClaimState.CLASSIFIED,
    ClaimState.EVIDENCE_LINKED,
    ClaimState.VERIFIED,
    ClaimState.REVIEWED,
    ClaimState.APPROVED,
    ClaimState.LOCKED,
]
CLAIM_EXCEPTION_STATES = {
    ClaimState.UNSUPPORTED,
    ClaimState.CONTESTED,
    ClaimState.CONFLICTED,
    ClaimState.STALE,
    ClaimState.RESTRICTED,
    ClaimState.REWRITE_REQUIRED,
    ClaimState.RETIRED,
}
CLAIM_TRANSITIONS: dict[ClaimState, set[ClaimState]] = {}
for _i, _s in enumerate(CLAIM_MAIN_PATH):
    _nxt = set()
    if _i + 1 < len(CLAIM_MAIN_PATH):
        _nxt.add(CLAIM_MAIN_PATH[_i + 1])
    if _s != ClaimState.LOCKED:
        _nxt |= CLAIM_EXCEPTION_STATES
    CLAIM_TRANSITIONS[_s] = _nxt
# LOCKED is immutable except an explicit speaker rewrite action, modeled as
# a controlled path back to REWRITE_REQUIRED (never a silent auto-edit).
CLAIM_TRANSITIONS[ClaimState.LOCKED] = {ClaimState.REWRITE_REQUIRED}
CLAIM_TRANSITIONS[ClaimState.UNSUPPORTED] = {ClaimState.EVIDENCE_LINKED, ClaimState.RETIRED}
CLAIM_TRANSITIONS[ClaimState.CONTESTED] = {ClaimState.EVIDENCE_LINKED, ClaimState.RETIRED}
CLAIM_TRANSITIONS[ClaimState.CONFLICTED] = {ClaimState.EVIDENCE_LINKED, ClaimState.RETIRED}
CLAIM_TRANSITIONS[ClaimState.STALE] = {ClaimState.EVIDENCE_LINKED, ClaimState.VERIFIED, ClaimState.RETIRED}
CLAIM_TRANSITIONS[ClaimState.RESTRICTED] = {ClaimState.RETIRED}
CLAIM_TRANSITIONS[ClaimState.REWRITE_REQUIRED] = {ClaimState.CLASSIFIED, ClaimState.EVIDENCE_LINKED, ClaimState.RETIRED}
CLAIM_TRANSITIONS[ClaimState.RETIRED] = set()


class Disposition(str, Enum):
    PENDING = "PENDING"
    KEEP = "KEEP"
    QUARANTINE = "QUARANTINE"
    REJECT = "REJECT"


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"


class AccessState(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    ACCESS_REVOKED = "ACCESS_REVOKED"


class GateName(str, Enum):
    SCOPE = "SCOPE"
    EVIDENCE = "EVIDENCE"
    NARRATIVE = "NARRATIVE"
    CLAIMS = "CLAIMS"
    READINESS = "READINESS"
    STAGE = "STAGE"


GATE_ORDER = [
    GateName.SCOPE,
    GateName.EVIDENCE,
    GateName.NARRATIVE,
    GateName.CLAIMS,
    GateName.READINESS,
    GateName.STAGE,
]


class BeatRole(str, Enum):
    HOOK = "HOOK"
    STAKES = "STAKES"
    TURN = "TURN"
    MECHANISM = "MECHANISM"
    PROOF = "PROOF"
    OBJECTION = "OBJECTION"
    ASK = "ASK"


class SourceOrigin(str, Enum):
    LOCAL = "local"
    WORKIQ = "workiq"
    GITHUB = "github"


class ConflictStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ExportSubState(str, Enum):
    DRAFT_EXPORTED = "DRAFT_EXPORTED"
    VALIDATED = "VALIDATED"
    PACKAGED = "PACKAGED"


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses/enums into plain JSON-safe values."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Report response compatibility (Dark Factory hardening cycle 7)
# ---------------------------------------------------------------------------

# Each pair is (an already-established report field name, a top-level
# snake_case compatibility alias for it) -- the alias, once added, is a
# direct reference to the identical value already sitting under the
# established name, never a duplicate computation or a fabricated value.
# Established names that already read as snake_case-compatible on their
# own (`slides`, `claims`, `readiness`, `rehearsal`, `qa`, `steps`, ...)
# need no separate alias and are intentionally absent from this table.
REPORT_COMPAT_ALIAS_PAIRS: tuple[tuple[str, str], ...] = (
    ("sources", "source_ledger"),
    ("evidence", "evidence_atoms"),
    ("conflicts", "conflict_cards"),
    ("gateResults", "gate_results"),
    ("gateResults", "gates"),
    ("auditEvents", "audit_trail"),
    ("auditEvents", "audit_events"),
    ("throughlines", "candidate_throughlines"),
    ("routes", "narrative_routes"),
    ("restorePoints", "restore_points"),
    ("package", "export"),
)


def add_report_compat_aliases(data: Any) -> Any:
    """Adds top-level snake_case compatibility aliases for public callers
    that expect a snake_case name instead of (or alongside) an
    established camelCase report/command-result field -- see
    `REPORT_COMPAT_ALIAS_PAIRS` above, plus `workspace_id`/`deck_id`
    (mirroring `cli._identity_fields`'s own resolution order, but written
    onto `data` itself rather than only the outer envelope, so a caller
    reading a written `run-report.json` file -- never wrapped in that
    envelope -- still finds them). Mutates and returns `data` unchanged if
    it is not a plain dict (never raises on an unexpected shape).

    Every alias is added only when its already-established source key is
    actually present, and every identity field only when it actually
    resolves to a real value -- never fabricated, so a report that never
    reached far enough to populate a given collection (e.g. a refusal
    before any workspace/connection existed) carries neither the
    established name nor its alias, exactly as before. Safe to call more
    than once on the same dict (idempotent)."""
    if not isinstance(data, dict):
        return data
    for source_key, alias_key in REPORT_COMPAT_ALIAS_PAIRS:
        if source_key in data:
            data[alias_key] = data[source_key]

    workspace = data.get("workspace") if isinstance(data.get("workspace"), dict) else {}
    refusal_details = (data.get("refusal") or {}).get("details") or {}
    workspace_id = data.get("workspaceId") or workspace.get("id") or refusal_details.get("workspaceId")
    if isinstance(workspace_id, str) and workspace_id:
        data["workspace_id"] = workspace_id

    package = data.get("package") if isinstance(data.get("package"), dict) else {}
    deck_id = (
        data.get("deckId") or package.get("deckId") or workspace.get("deck_id") or workspace.get("deckId")
    )
    if isinstance(deck_id, str) and deck_id:
        data["deck_id"] = deck_id
    return data


def _coerce(hint: Any, raw: Any) -> Any:
    if raw is None:
        return None
    origin = get_origin(hint)
    if origin is list:
        (inner,) = get_args(hint)
        if is_dataclass(inner):
            return [dataclass_from_dict(inner, item) for item in raw]
        return list(raw)
    if origin is dict:
        _key, inner = get_args(hint)
        if is_dataclass(inner):
            return {k: dataclass_from_dict(inner, v) for k, v in raw.items()}
        return dict(raw)
    if origin is Union:
        args = [a for a in get_args(hint) if a is not type(None)]
        if len(args) == 1:
            return _coerce(args[0], raw)
        return raw
    if is_dataclass(hint):
        return dataclass_from_dict(hint, raw)
    return raw


def dataclass_from_dict(cls: type, data: Optional[dict]) -> Any:
    """Reconstruct a (possibly nested) dataclass instance from a plain dict
    produced by `to_jsonable`. Generic over every entity in this module so
    persistence.py needs no per-entity boilerplate."""
    if data is None:
        return None
    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        hint = hints.get(f.name)
        kwargs[f.name] = _coerce(hint, data[f.name])
    return cls(**kwargs)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

@dataclass
class TalkBrief:
    id: str
    workspace_id: str
    audience: str = ""
    event_type: str = ""
    duration_minutes: float = 20.0
    takeaway: str = ""
    proof_points: list[str] = field(default_factory=list)
    excluded_topics: list[str] = field(default_factory=list)
    tone: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class SourceArtifact:
    id: str
    workspace_id: str
    origin: str  # SourceOrigin value
    source_type: str
    uri: str
    owner: str
    permission_state: str  # "authorized" | "denied"
    acl_snapshot: str
    version: str
    retrieved_at: str
    content_hash: str
    state: str = SourceState.PROPOSED.value
    sensitivity_label: Optional[str] = None
    byte_size: int = 0
    local_path: Optional[str] = None
    captured_at: str = field(default_factory=now_iso)
    superseded_by: Optional[str] = None
    supersedes: Optional[str] = None
    hold_reason: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class EvidenceAtom:
    id: str
    workspace_id: str
    source_id: str
    locator: str
    owner: str
    version: str
    content_hash: str
    sensitivity: Optional[str]
    access_snapshot: str
    freshness: str
    confidence: float
    excerpt: str
    linked_claim_ids: list[str] = field(default_factory=list)
    disposition: str = Disposition.PENDING.value
    access_state: str = AccessState.AUTHORIZED.value
    freshness_state: str = FreshnessState.FRESH.value
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    # The 9 fields FR-EVD-1 requires populated at extraction time (see
    # docs/data-model.md §"FR-EVD-1 interpretation" for the field-count
    # rationale). linked_claim_ids intentionally starts empty and is not
    # part of this required-at-extraction set.
    REQUIRED_AT_EXTRACTION = (
        "source_id", "locator", "owner", "version", "content_hash",
        "sensitivity_or_none", "access_snapshot", "freshness", "confidence",
    )

    def has_required_fields(self) -> bool:
        if not (self.source_id and self.locator and self.owner and self.version
                and self.content_hash and self.access_snapshot and self.freshness):
            return False
        if self.confidence is None:
            return False
        # sensitivity may be legitimately None (no label) — its *presence as
        # an attribute* is what's required, not non-null content.
        return True

    def is_valid_for_citation(self) -> bool:
        """A claim may only cite an atom that the user kept, that still has
        authorized access, and that has not gone stale (FR-EVD-2/FR-EVD-8)."""
        return (
            self.disposition == Disposition.KEEP.value
            and self.access_state == AccessState.AUTHORIZED.value
            and self.freshness_state == FreshnessState.FRESH.value
        )


@dataclass
class ConflictCard:
    id: str
    workspace_id: str
    claim_id: str
    atom_id_a: str
    atom_id_b: str
    source_a: str
    source_b: str
    date_a: str
    date_b: str
    owner_a: str
    owner_b: str
    scope_a: str
    scope_b: str
    status: str = ConflictStatus.OPEN.value
    kind: str = "contradiction"  # "contradiction" | "sensitivity_label"
    decision: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None
    created_at: str = field(default_factory=now_iso)


@dataclass
class Claim:
    id: str
    workspace_id: str
    type: str  # ClaimType value
    text: str
    state: str = ClaimState.DRAFT.value
    rationale: Optional[str] = None
    aspirational_label: Optional[str] = None
    evidence_atom_ids: list[str] = field(default_factory=list)
    conflict_ids: list[str] = field(default_factory=list)
    approver: Optional[str] = None
    approved_at: Optional[str] = None
    hedged_rewrite: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class NarrativeThroughline:
    id: str
    workspace_id: str
    brief_id: str
    text: str
    origin: str = "proposed"  # "proposed" | "custom"
    selected: bool = False
    created_at: str = field(default_factory=now_iso)


@dataclass
class Beat:
    id: str
    route_id: str
    order: int
    role: str  # BeatRole value
    headline: str
    claim_ids: list[str] = field(default_factory=list)
    spoken_talk_track: str = ""
    transition_in: str = ""
    transition_out: str = ""
    time_budget_seconds: int = 60
    fallback_line: str = ""
    source_refs: list[str] = field(default_factory=list)
    visual_description: str = ""
    is_demo: bool = False


@dataclass
class NarrativeRoute:
    id: str
    workspace_id: str
    throughline_id: str
    label: str
    beats: list[Beat] = field(default_factory=list)
    selected: bool = False
    created_at: str = field(default_factory=now_iso)


@dataclass
class DemoAsset:
    slide_id: str
    live_path: Optional[str] = None
    prerecorded_asset_path: Optional[str] = None
    static_asset_path: Optional[str] = None
    verbal_recovery_script: Optional[str] = None

    def missing_paths(self) -> list[str]:
        missing = []
        if not self.live_path:
            missing.append("livePath")
        if not self.prerecorded_asset_path:
            missing.append("prerecordedAssetPath")
        if not self.static_asset_path:
            missing.append("staticAssetPath")
        if not self.verbal_recovery_script:
            missing.append("verbalRecoveryScript")
        return missing


@dataclass
class Region:
    role: str
    text: str = ""
    content_hash: str = ""
    claim_ids: list[str] = field(default_factory=list)
    alt_text: Optional[str] = None
    alt_text_confirmed_by: Optional[str] = None
    uses_color_signal: bool = False
    non_color_indicator: Optional[str] = None


@dataclass
class SlideSpec:
    id: str
    workspace_id: str
    deck_id: str
    beat_id: str
    order: int
    role: str  # job (BeatRole value)
    layout: str  # "hook" | "standard"
    regions: dict[str, Region] = field(default_factory=dict)
    reading_order: list[str] = field(default_factory=list)
    is_demo: bool = False
    demo_asset: Optional[DemoAsset] = None
    needs_review: bool = False
    needs_review_reason: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def claim_ids(self) -> list[str]:
        ids: list[str] = []
        for region in self.regions.values():
            for cid in region.claim_ids:
                if cid not in ids:
                    ids.append(cid)
        return ids


@dataclass
class GateFailure:
    code: str
    message: str
    subject_id: Optional[str] = None


@dataclass
class GateResult:
    gate: str  # GateName value
    passed: bool
    failed_checks: list[GateFailure] = field(default_factory=list)
    evaluated_at: str = field(default_factory=now_iso)
    workspace_snapshot_version: int = 0
    actor: Optional[str] = None


@dataclass
class GateResultRecord:
    """Persisted form of the latest `GateResult` per gate name (one row per
    gate per workspace; `id` is deterministic as `gate:<GateName>`)."""
    id: str
    workspace_id: str
    gate: str
    passed: bool
    failed_checks: list[GateFailure] = field(default_factory=list)
    evaluated_at: str = field(default_factory=now_iso)
    workspace_snapshot_version: int = 0
    actor: Optional[str] = None


@dataclass
class ApprovalRecord:
    id: str
    workspace_id: str
    subject_type: str
    subject_id: str
    actor: str
    decision: str
    decided_at: str = field(default_factory=now_iso)


@dataclass
class AuditEvent:
    id: str
    workspace_id: str
    actor: str
    action: str
    subject_type: str
    subject_id: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=now_iso)


@dataclass
class RestorePoint:
    id: str
    workspace_id: str
    trigger: str
    actor: Optional[str]
    path: str
    created_at: str = field(default_factory=now_iso)


@dataclass
class UnmatchedContentItem:
    id: str
    workspace_id: str
    source_pptx_path: str
    text: str
    context: str
    created_at: str = field(default_factory=now_iso)


@dataclass
class PendingEdit:
    """A re-imported text change that has NOT yet been merged back into the
    canonical workspace state (ARCH §9's "pending edit" — the canonical
    contract is never silently overwritten)."""
    id: str
    workspace_id: str
    slide_id: str
    region_role: str
    region_id: str
    old_text: str
    new_text: str
    old_hash: str
    new_hash: str
    claim_ids: list[str] = field(default_factory=list)
    status: str = "PENDING"  # PENDING | ACCEPTED | DISCARDED
    resolution_note: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    resolved_at: Optional[str] = None


@dataclass
class Workspace:
    id: str
    phase: str = WorkspacePhase.BRIEFING.value
    reopened_reason: Optional[str] = None
    brief_id: Optional[str] = None
    active_throughline_id: Optional[str] = None
    active_route_id: Optional[str] = None
    deck_id: Optional[str] = None
    manifest_id: Optional[str] = None
    stage_approved_by: Optional[str] = None
    stage_approved_at: Optional[str] = None
    snapshot_version: int = 0
    # FR-M365-4: the active-bundle source `uri -> contentHash` snapshot
    # captured at the end of the workspace's own most recent rehearsal,
    # and when that rehearsal happened -- `None` until the first
    # rehearsal ever runs (see `engine.rehearsal._source_changes_since_
    # last_rehearsal`, which never reports changes on that first call --
    # there is no prior snapshot yet to diff against).
    rehearsal_source_snapshot: dict[str, str] = field(default_factory=dict)
    last_rehearsal_at: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
