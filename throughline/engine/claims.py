"""Claim Engine + Conflict Detector (ARCH §8, §13).

`propose_claims` never generates claim text itself — the Skill Prompt
Layer supplies `drafts`; this module validates shape (exactly one type per
claim, non-empty text) and owns every subsequent state transition
deterministically (ARCH §4 "load-bearing separation for testability").

Conflict detection follows the same propose/validate split used
everywhere else in this design: recognizing that two atoms' *content*
contradicts each other is a comprehension task left to the human/agent
(exactly like claim/route/note authorship); the Engine's job — turning
that determination into a structured, blocking `ConflictCard` that can
never be silently resolved — is fully automatic and deterministic. The one
exception is the *sensitivity-label* conflict, which is pure string
inequality over two atoms' `sensitivity` fields and is therefore detected
automatically with no human input at all (ARCH §13).
"""
from __future__ import annotations

from typing import Optional

from . import evidence, models, persistence
from .errors import EngineError

VALID_CLAIM_TYPES = {t.value for t in models.ClaimType}


def propose_claims(conn, workspace_id: str, drafts: list[dict], actor: str) -> list[models.Claim]:
    if not drafts:
        raise EngineError("VALIDATION_ERROR", "at least one claim draft is required", {})
    claims: list[models.Claim] = []
    writes = []
    audits = []
    for draft in drafts:
        claim_type = (draft.get("type") or "").strip().upper()
        text = (draft.get("text") or "").strip()
        if claim_type not in VALID_CLAIM_TYPES:
            raise EngineError(
                "VALIDATION_ERROR",
                f"claim type must be exactly one of {sorted(VALID_CLAIM_TYPES)} (got '{draft.get('type')}')",
                {"type": draft.get("type")},
            )
        if not text:
            raise EngineError("VALIDATION_ERROR", "claim text must not be empty", {})
        aspirational_label = draft.get("aspirationalLabel")
        if aspirational_label is not None:
            aspirational_label = aspirational_label.strip().upper()
        if claim_type == models.ClaimType.ASPIRATIONAL.value and aspirational_label is not None:
            if aspirational_label not in models.ASPIRATIONAL_LABELS:
                raise EngineError(
                    "VALIDATION_ERROR",
                    f"aspirationalLabel must be one of {models.ASPIRATIONAL_LABELS}",
                    {"aspirationalLabel": aspirational_label},
                )
        claim = models.Claim(
            id=models.new_id("claim"),
            workspace_id=workspace_id,
            type=claim_type,
            text=text,
            state=models.ClaimState.CLASSIFIED.value,
            rationale=draft.get("rationale"),
            aspirational_label=aspirational_label,
        )
        claims.append(claim)
        writes.append(("claim", claim))
        audits.append(models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="claim.propose", subject_type="claim", subject_id=claim.id,
            details={"type": claim_type},
        ))
    persistence.commit_many(conn, writes, audits)

    # Evidence-link any atoms supplied inline with the draft, then recompute
    # every claim's state — even one with zero atoms, so a factual claim's
    # `state` honestly reads UNSUPPORTED immediately (FR-EVD-4), not only
    # once a later gate check happens to look.
    for draft, claim in zip(drafts, claims):
        for atom_id in draft.get("evidenceAtomIds", []) or []:
            link_evidence(conn, workspace_id, claim.id, atom_id, actor)
        _recompute_state(conn, workspace_id, claim.id, actor)
    return [persistence.get(conn, "claim", c.id, models.Claim) for c in claims]


def _get_claim(conn, workspace_id: str, claim_id: str) -> models.Claim:
    claim = persistence.get(conn, "claim", claim_id, models.Claim)
    if claim is None or claim.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"claim '{claim_id}' not found", {"claimId": claim_id})
    return claim


def _get_atom(conn, workspace_id: str, atom_id: str) -> models.EvidenceAtom:
    atom = persistence.get(conn, "evidence", atom_id, models.EvidenceAtom)
    if atom is None or atom.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"evidence atom '{atom_id}' not found", {"atomId": atom_id})
    return atom


def link_evidence(
    conn, workspace_id: str, claim_id: str, atom_id: str, actor: str,
    contradicts_atom_id: Optional[str] = None,
) -> models.Claim:
    claim = _get_claim(conn, workspace_id, claim_id)
    if claim.state == models.ClaimState.LOCKED.value:
        raise EngineError("IMMUTABLE_LOCKED_CLAIM", f"claim '{claim_id}' is LOCKED; use an explicit rewrite action", {"claimId": claim_id})
    atom = _get_atom(conn, workspace_id, atom_id)
    if atom.disposition != models.Disposition.KEEP.value:
        raise EngineError(
            "VALIDATION_ERROR",
            f"evidence atom '{atom_id}' has disposition '{atom.disposition}'; only KEEP atoms may be cited",
            {"atomId": atom_id, "disposition": atom.disposition},
        )

    if atom_id not in claim.evidence_atom_ids:
        claim.evidence_atom_ids.append(atom_id)
    if claim_id not in atom.linked_claim_ids:
        atom.linked_claim_ids.append(claim_id)
    atom.updated_at = models.now_iso()

    source = persistence.get(conn, "source", atom.source_id, models.SourceArtifact)
    writes = [("claim", claim), ("evidence", atom)]
    audits = [models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="claim.link_evidence", subject_type="claim", subject_id=claim.id,
        details={"atomId": atom_id},
    )]
    if source is not None and source.state == models.SourceState.CURATED.value:
        source.state = models.SourceState.CITED.value
        source.updated_at = models.now_iso()
        writes.append(("source", source))
        audits.append(models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="source.transition", subject_type="source", subject_id=source.id,
            details={"from": models.SourceState.CURATED.value, "to": models.SourceState.CITED.value},
        ))
    persistence.commit_many(conn, writes, audits)

    _recompute_state(conn, workspace_id, claim.id, actor)

    # Structural (auto) sensitivity-label conflict scan across every pair of
    # currently-linked atoms on this claim (§13 — pure data comparison).
    _scan_sensitivity_conflicts(conn, workspace_id, claim.id, actor)

    if contradicts_atom_id:
        _register_conflict(conn, workspace_id, claim.id, atom_id, contradicts_atom_id, actor, kind="contradiction")

    return _get_claim(conn, workspace_id, claim.id)


def unlink_evidence(conn, workspace_id: str, claim_id: str, atom_id: str, actor: str, reason: str) -> models.Claim:
    claim = _get_claim(conn, workspace_id, claim_id)
    atom = _get_atom(conn, workspace_id, atom_id)
    if atom_id in claim.evidence_atom_ids:
        claim.evidence_atom_ids.remove(atom_id)
    if claim_id in atom.linked_claim_ids:
        atom.linked_claim_ids.remove(claim_id)
    atom.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="claim.unlink_evidence", subject_type="claim", subject_id=claim.id,
        details={"atomId": atom_id, "reason": reason},
    )
    persistence.commit_many(conn, [("claim", claim), ("evidence", atom)], [audit])
    _recompute_state(conn, workspace_id, claim.id, actor)
    return _get_claim(conn, workspace_id, claim.id)


def _valid_atom_count(conn, workspace_id: str, claim: models.Claim) -> int:
    count = 0
    for atom_id in claim.evidence_atom_ids:
        atom = persistence.get(conn, "evidence", atom_id, models.EvidenceAtom)
        if atom is not None and atom.is_valid_for_citation():
            count += 1
    return count


def _recompute_state(conn, workspace_id: str, claim_id: str, actor: str) -> models.Claim:
    """Pure re-derivation of a claim's state from its current
    type/evidence/rationale/label, per FR-EVD-3/4/5/6. Never regresses a
    claim past APPROVED/LOCKED — those require an explicit human action
    (approve_claim / lock_claim), not automatic recomputation."""
    claim = _get_claim(conn, workspace_id, claim_id)
    if claim.state in (models.ClaimState.APPROVED.value, models.ClaimState.LOCKED.value,
                       models.ClaimState.RETIRED.value):
        return claim
    valid_atoms = _valid_atom_count(conn, workspace_id, claim)
    has_conflict = any(
        c.status == models.ConflictStatus.OPEN.value
        for c in persistence.list_all(conn, "conflict", workspace_id, models.ConflictCard)
        if c.claim_id == claim_id
    )
    new_state = claim.state
    if has_conflict:
        new_state = models.ClaimState.CONFLICTED.value
    elif claim.type == models.ClaimType.FACTUAL.value:
        new_state = models.ClaimState.VERIFIED.value if valid_atoms >= 1 else models.ClaimState.UNSUPPORTED.value
    elif claim.type == models.ClaimType.INTERPRETIVE.value:
        if valid_atoms >= 1 and claim.rationale:
            new_state = models.ClaimState.VERIFIED.value
        elif valid_atoms >= 1:
            new_state = models.ClaimState.EVIDENCE_LINKED.value
        else:
            new_state = models.ClaimState.CLASSIFIED.value
    elif claim.type == models.ClaimType.ASPIRATIONAL.value:
        new_state = models.ClaimState.VERIFIED.value if claim.aspirational_label else models.ClaimState.CLASSIFIED.value

    if new_state != claim.state:
        old_state = claim.state
        claim.state = new_state
        claim.updated_at = models.now_iso()
        audit = models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="claim.recompute_state", subject_type="claim", subject_id=claim.id,
            details={"from": old_state, "to": new_state, "validAtoms": valid_atoms},
        )
        persistence.commit(conn, "claim", claim, audit)
    return claim


def set_rationale(conn, workspace_id: str, claim_id: str, rationale: str, actor: str) -> models.Claim:
    claim = _get_claim(conn, workspace_id, claim_id)
    if not rationale or not rationale.strip():
        raise EngineError("RATIONALE_REQUIRED", "rationale must not be empty", {"claimId": claim_id})
    claim.rationale = rationale.strip()
    claim.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="claim.set_rationale", subject_type="claim", subject_id=claim.id, details={},
    )
    persistence.commit(conn, "claim", claim, audit)
    return _recompute_state(conn, workspace_id, claim_id, actor)


def set_aspirational_label(conn, workspace_id: str, claim_id: str, label: str, actor: str) -> models.Claim:
    claim = _get_claim(conn, workspace_id, claim_id)
    if claim.type != models.ClaimType.ASPIRATIONAL.value:
        raise EngineError("VALIDATION_ERROR", "aspirational_label only applies to ASPIRATIONAL claims", {"claimId": claim_id})
    label = (label or "").strip().upper()
    if label not in models.ASPIRATIONAL_LABELS:
        raise EngineError("VALIDATION_ERROR", f"label must be one of {models.ASPIRATIONAL_LABELS}", {"label": label})
    claim.aspirational_label = label
    claim.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="claim.set_aspirational_label", subject_type="claim", subject_id=claim.id, details={"label": label},
    )
    persistence.commit(conn, "claim", claim, audit)
    return _recompute_state(conn, workspace_id, claim_id, actor)


def approve_claim(conn, workspace_id: str, claim_id: str, actor: str) -> models.ApprovalRecord:
    if not actor or not actor.strip():
        raise EngineError("APPROVER_REQUIRED", "approve_claim requires a named human actor", {"claimId": claim_id})
    claim = _recompute_state(conn, workspace_id, claim_id, actor)
    if claim.type == models.ClaimType.FACTUAL.value and claim.state == models.ClaimState.UNSUPPORTED.value:
        raise EngineError(
            "CLAIM_UNSUPPORTED",
            f"claim '{claim_id}' is UNSUPPORTED and cannot be approved until it has verified evidence",
            {"claimId": claim_id},
        )
    if claim.type == models.ClaimType.INTERPRETIVE.value and not claim.rationale:
        raise EngineError("RATIONALE_REQUIRED", f"claim '{claim_id}' needs a rationale before approval", {"claimId": claim_id})
    if claim.type == models.ClaimType.INTERPRETIVE.value and _valid_atom_count(conn, workspace_id, claim) < 1:
        raise EngineError(
            "CLAIM_UNSUPPORTED",
            f"claim '{claim_id}' is interpretive and needs at least one supporting evidence atom before approval (FR-EVD-5)",
            {"claimId": claim_id},
        )
    if claim.type == models.ClaimType.ASPIRATIONAL.value and not claim.aspirational_label:
        raise EngineError("VALIDATION_ERROR", f"claim '{claim_id}' needs an aspirational label before approval", {"claimId": claim_id})
    if claim.state == models.ClaimState.CONFLICTED.value:
        raise EngineError("CONFLICT_UNRESOLVED", f"claim '{claim_id}' has an unresolved conflict", {"claimId": claim_id})

    claim.state = models.ClaimState.APPROVED.value
    claim.approver = actor
    claim.approved_at = models.now_iso()
    claim.updated_at = claim.approved_at
    approval = models.ApprovalRecord(
        id=models.new_id("approval"), workspace_id=workspace_id, subject_type="claim",
        subject_id=claim_id, actor=actor, decision="approved",
    )
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="claim.approve", subject_type="claim", subject_id=claim.id, details={},
    )
    persistence.commit_many(conn, [("claim", claim), ("approval", approval)], [audit])
    return approval


def lock_claim(conn, workspace_id: str, claim_id: str, actor: str) -> models.Claim:
    claim = _get_claim(conn, workspace_id, claim_id)
    if claim.state != models.ClaimState.APPROVED.value:
        raise EngineError("VALIDATION_ERROR", f"claim '{claim_id}' must be APPROVED before it can be LOCKED", {"claimId": claim_id})
    claim.state = models.ClaimState.LOCKED.value
    claim.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="claim.lock", subject_type="claim", subject_id=claim.id, details={},
    )
    persistence.commit(conn, "claim", claim, audit)
    return claim


def rewrite_claim(conn, workspace_id: str, claim_id: str, new_text: str, actor: str) -> models.Claim:
    """FR-NAR-6: the only way LOCKED (or any) claim wording changes is this
    explicit, speaker-initiated action — never silent automated rewrite."""
    claim = _get_claim(conn, workspace_id, claim_id)
    if not new_text or not new_text.strip():
        raise EngineError("VALIDATION_ERROR", "new_text must not be empty", {"claimId": claim_id})
    was_locked = claim.state == models.ClaimState.LOCKED.value
    claim.text = new_text.strip()
    claim.hedged_rewrite = None
    claim.approver = None
    claim.approved_at = None
    claim.state = models.ClaimState.EVIDENCE_LINKED.value if claim.evidence_atom_ids else models.ClaimState.CLASSIFIED.value
    claim.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="claim.rewrite", subject_type="claim", subject_id=claim.id,
        details={"wasLocked": was_locked},
    )
    persistence.commit(conn, "claim", claim, audit)
    return _recompute_state(conn, workspace_id, claim_id, actor)


def demote_claim(conn, workspace_id: str, claim_id: str, hedged_rewrite: str, actor: str, reason: str) -> models.Claim:
    claim = _get_claim(conn, workspace_id, claim_id)
    claim.state = models.ClaimState.REWRITE_REQUIRED.value
    claim.hedged_rewrite = hedged_rewrite
    claim.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="claim.demote", subject_type="claim", subject_id=claim.id,
        details={"reason": reason},
    )
    persistence.commit(conn, "claim", claim, audit)
    return claim


def reassess_after_evidence_change(conn, workspace_id: str, claim: models.Claim, actor: str, reason: str) -> Optional[models.Claim]:
    """FR-EVD-8: invoked whenever an atom the claim cites changes access or
    freshness state. A factual claim that has lost every valid supporting
    atom is demoted (never left at its previously-confident wording)."""
    if claim.type != models.ClaimType.FACTUAL.value:
        _recompute_state(conn, workspace_id, claim.id, actor)
        return None
    if claim.state not in (
        models.ClaimState.VERIFIED.value, models.ClaimState.REVIEWED.value,
        models.ClaimState.APPROVED.value, models.ClaimState.LOCKED.value,
    ):
        _recompute_state(conn, workspace_id, claim.id, actor)
        return None
    valid_atoms = _valid_atom_count(conn, workspace_id, claim)
    if valid_atoms == 0:
        hedged = evidence.make_hedged_rewrite(claim.text)
        return demote_claim(conn, workspace_id, claim.id, hedged, actor, reason)
    return None


# ---------------------------------------------------------------------------
# Conflict Detector
# ---------------------------------------------------------------------------

def _register_conflict(conn, workspace_id: str, claim_id: str, atom_id_a: str, atom_id_b: str, actor: str, kind: str) -> models.ConflictCard:
    atom_a = _get_atom(conn, workspace_id, atom_id_a)
    atom_b = _get_atom(conn, workspace_id, atom_id_b)
    source_a = persistence.get(conn, "source", atom_a.source_id, models.SourceArtifact)
    source_b = persistence.get(conn, "source", atom_b.source_id, models.SourceArtifact)

    existing = [
        c for c in persistence.list_all(conn, "conflict", workspace_id, models.ConflictCard)
        if c.claim_id == claim_id and c.status == models.ConflictStatus.OPEN.value
        and {c.atom_id_a, c.atom_id_b} == {atom_id_a, atom_id_b}
    ]
    if existing:
        return existing[0]

    card = models.ConflictCard(
        id=models.new_id("conflict"),
        workspace_id=workspace_id,
        claim_id=claim_id,
        atom_id_a=atom_id_a,
        atom_id_b=atom_id_b,
        source_a=source_a.uri if source_a else atom_a.locator,
        source_b=source_b.uri if source_b else atom_b.locator,
        date_a=atom_a.version,
        date_b=atom_b.version,
        owner_a=atom_a.owner,
        owner_b=atom_b.owner,
        scope_a=source_a.source_type if source_a else "",
        scope_b=source_b.source_type if source_b else "",
        kind=kind,
    )
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="conflict.create", subject_type="conflict", subject_id=card.id,
        details={"claimId": claim_id, "kind": kind},
    )
    persistence.commit(conn, "conflict", card, audit)
    _recompute_state(conn, workspace_id, claim_id, actor)
    return card


def _scan_sensitivity_conflicts(conn, workspace_id: str, claim_id: str, actor: str) -> list[models.ConflictCard]:
    claim = _get_claim(conn, workspace_id, claim_id)
    atoms = [persistence.get(conn, "evidence", aid, models.EvidenceAtom) for aid in claim.evidence_atom_ids]
    atoms = [a for a in atoms if a is not None]
    created = []
    for i in range(len(atoms)):
        for j in range(i + 1, len(atoms)):
            a, b = atoms[i], atoms[j]
            if a.sensitivity is not None and b.sensitivity is not None and a.sensitivity != b.sensitivity:
                created.append(_register_conflict(conn, workspace_id, claim_id, a.id, b.id, actor, kind="sensitivity_label"))
    return created


def scan_conflicts(conn, workspace_id: str, claim_id: str, actor: str = "system") -> list[models.ConflictCard]:
    """Public re-scan entry point (also used by `gate run evidence`)."""
    return _scan_sensitivity_conflicts(conn, workspace_id, claim_id, actor)


def resolve_conflict(conn, workspace_id: str, conflict_id: str, decision: str, actor: str) -> models.ConflictCard:
    if not decision or not decision.strip():
        raise EngineError("VALIDATION_ERROR", "decision must not be empty", {"conflictId": conflict_id})
    card = persistence.get(conn, "conflict", conflict_id, models.ConflictCard)
    if card is None or card.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"conflict '{conflict_id}' not found", {"conflictId": conflict_id})
    card.status = models.ConflictStatus.RESOLVED.value
    card.decision = decision.strip()
    card.decided_by = actor
    card.decided_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="conflict.resolve", subject_type="conflict", subject_id=card.id,
        details={"decision": decision},
    )
    persistence.commit(conn, "conflict", card, audit)
    _recompute_state(conn, workspace_id, card.claim_id, actor)
    return card


def retire_claim(conn, workspace_id: str, claim_id: str, actor: str) -> models.Claim:
    claim = _get_claim(conn, workspace_id, claim_id)
    claim.state = models.ClaimState.RETIRED.value
    claim.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="claim.retire", subject_type="claim", subject_id=claim.id, details={},
    )
    persistence.commit(conn, "claim", claim, audit)
    return claim


def verify_grounding(conn, workspace_id: str, claim_ids: list[str]) -> dict:
    """Rehearsal Q&A grounding check (ARCH §14's acknowledged limit): the
    Engine can verify every cited claim ID is APPROVED/LOCKED, but cannot
    semantically verify prose faithfulness — that stays speaker-reviewed,
    made visible via this per-answer grounding report rather than claimed
    as fully automatic verification."""
    results = {}
    for cid in claim_ids:
        claim = persistence.get(conn, "claim", cid, models.Claim)
        if claim is None or claim.workspace_id != workspace_id:
            results[cid] = {"grounded": False, "reason": "claim not found"}
        elif claim.state not in (models.ClaimState.APPROVED.value, models.ClaimState.LOCKED.value):
            results[cid] = {"grounded": False, "reason": f"claim state is '{claim.state}', not APPROVED/LOCKED"}
        else:
            results[cid] = {"grounded": True, "reason": None}
    all_grounded = all(v["grounded"] for v in results.values()) if results else True
    return {"allGrounded": all_grounded, "claims": results}
