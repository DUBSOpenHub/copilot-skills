"""Evidence Ledger (ARCH §8).

Turns an `AUTHORIZED`-or-later source's normalized text into evidence
atoms, lets the user curate their disposition, and revalidates atoms
against their source's current access/freshness state.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

from . import models, parsers, persistence
from .errors import EngineError

MAX_ATOMS_PER_SOURCE = 20
EXCERPT_MAX_CHARS = 800

# Source states from which extraction is permitted: AUTHORIZED or anywhere
# further down the main path already (idempotent re-extraction / re-check).
EXTRACTABLE_SOURCE_STATES = {
    models.SourceState.AUTHORIZED.value,
    models.SourceState.RETRIEVED.value,
    models.SourceState.NORMALIZED.value,
    models.SourceState.CURATED.value,
    models.SourceState.CITED.value,
    models.SourceState.APPROVED.value,
}

# Deterministic default confidence by extraction outcome (MVP has no
# learned/semantic scoring model — see docs/data-model.md). A source with
# recoverable text scores higher than one with none (e.g. an image).
CONFIDENCE_WITH_TEXT = 0.9
CONFIDENCE_WITHOUT_TEXT = 0.4


def _split_paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text.strip()) if text.strip() else []
    blocks = [b.strip() for b in blocks if b.strip()]
    if not blocks and text.strip():
        blocks = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return blocks[:MAX_ATOMS_PER_SOURCE]


def extract_evidence(conn, workspace_id: str, source_id: str, actor: str, force: bool = False) -> list[models.EvidenceAtom]:
    source = persistence.get(conn, "source", source_id, models.SourceArtifact)
    if source is None or source.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"source '{source_id}' not found", {"sourceId": source_id})
    if source.state not in EXTRACTABLE_SOURCE_STATES:
        raise EngineError(
            "VALIDATION_ERROR",
            f"source '{source_id}' is not extractable in state '{source.state}'"
            + (f" ({source.hold_reason})" if source.hold_reason else ""),
            {"sourceId": source_id, "state": source.state},
        )

    existing = [a for a in persistence.list_all(conn, "evidence", workspace_id, models.EvidenceAtom) if a.source_id == source_id]
    if existing and not force:
        return existing

    text = ""
    is_no_text_expected = (
        source.local_path is not None
        and Path(source.local_path).suffix.lower() in parsers.NO_TEXT_EXPECTED_EXTENSIONS
    )
    if not is_no_text_expected and source.local_path and Path(source.local_path).exists():
        text = Path(source.local_path).read_text(encoding="utf-8", errors="replace")
    paragraphs = [] if is_no_text_expected else _split_paragraphs(text)

    atoms: list[models.EvidenceAtom] = []
    if not paragraphs:
        atoms.append(_build_atom(workspace_id, source, source.uri, "", CONFIDENCE_WITHOUT_TEXT,
                                  "No automatically extractable text (e.g. a visual-only source). "
                                  "Usable as a visual/demo reference only."))
    else:
        for idx, para in enumerate(paragraphs):
            locator = f"{source.uri}#p{idx}" if len(paragraphs) > 1 else source.uri
            atoms.append(_build_atom(workspace_id, source, locator, para[:EXCERPT_MAX_CHARS], CONFIDENCE_WITH_TEXT, para[:EXCERPT_MAX_CHARS]))

    writes = [("evidence", a) for a in atoms]
    audits = [
        models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="evidence.extract", subject_type="evidence", subject_id=a.id,
            details={"sourceId": source_id, "locator": a.locator},
        )
        for a in atoms
    ]

    # Source progresses NORMALIZED -> CURATED as a result of extraction
    # succeeding; the RETRIEVED/NORMALIZED steps already happened in
    # ingest.py's synchronous parse, so only the final hop is recorded here
    # (audit `details.transitionPath` documents the full conceptual path).
    prior_state = source.state
    source.state = models.SourceState.CURATED.value
    source.updated_at = models.now_iso()
    writes.append(("source", source))
    audits.append(models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="source.transition", subject_type="source", subject_id=source.id,
        details={"from": prior_state, "to": source.state, "transitionPath": ["RETRIEVED", "NORMALIZED", "CURATED"]},
    ))

    persistence.commit_many(conn, writes, audits)
    return atoms


def _build_atom(workspace_id: str, source: models.SourceArtifact, locator: str, excerpt: str, confidence: float, excerpt_full: str) -> models.EvidenceAtom:
    content_hash = hashlib.sha256(excerpt_full.encode("utf-8")).hexdigest()
    return models.EvidenceAtom(
        id=models.new_id("evidence"),
        workspace_id=workspace_id,
        source_id=source.id,
        locator=locator,
        owner=source.owner,
        version=source.version,
        content_hash=content_hash,
        sensitivity=source.sensitivity_label,
        access_snapshot=source.acl_snapshot or source.permission_state,
        freshness=models.FreshnessState.FRESH.value,
        confidence=confidence,
        excerpt=excerpt_full,
    )


def set_disposition(conn, workspace_id: str, atom_id: str, disposition: str, actor: str) -> models.EvidenceAtom:
    disposition = (disposition or "").strip().upper()
    if disposition not in (models.Disposition.KEEP.value, models.Disposition.QUARANTINE.value, models.Disposition.REJECT.value):
        raise EngineError("VALIDATION_ERROR", f"disposition must be KEEP, QUARANTINE, or REJECT (got '{disposition}')", {})
    atom = persistence.get(conn, "evidence", atom_id, models.EvidenceAtom)
    if atom is None or atom.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"evidence atom '{atom_id}' not found", {"atomId": atom_id})
    previous = atom.disposition
    atom.disposition = disposition
    atom.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="evidence.set_disposition", subject_type="evidence", subject_id=atom.id,
        details={"from": previous, "to": disposition},
    )
    persistence.commit(conn, "evidence", atom, audit)

    linked_claim_ids = list(atom.linked_claim_ids)
    if disposition == models.Disposition.REJECT.value and linked_claim_ids:
        # FR-EVD-2: a rejected atom must not remain cited by any claim.
        from . import claims as claims_mod
        for claim_id in linked_claim_ids:
            claims_mod.unlink_evidence(conn, workspace_id, claim_id, atom_id, actor, reason="atom_rejected")
    if disposition in (models.Disposition.REJECT.value, models.Disposition.QUARANTINE.value) and linked_claim_ids:
        # FR-EVD-8: an already-APPROVED/LOCKED factual claim that just lost
        # its only valid support is demoted with a hedged rewrite, never
        # silently left at its confident wording. `_recompute_state` alone
        # deliberately protects APPROVED/LOCKED claims from automatic
        # regression, so this path is routed through the dedicated
        # reassessment used everywhere else evidence validity changes.
        from . import claims as claims_mod
        for claim_id in linked_claim_ids:
            claim = persistence.get(conn, "claim", claim_id, models.Claim)
            if claim is not None:
                claims_mod.reassess_after_evidence_change(conn, workspace_id, claim, actor, reason=f"atom_{disposition.lower()}")
    return atom


def is_valid_for_citation(atom: models.EvidenceAtom) -> bool:
    return atom.is_valid_for_citation()


def make_hedged_rewrite(original_text: str) -> str:
    """Deterministic, mechanical hedge applied when a factual claim loses
    its supporting evidence (FR-EVD-8). This is intentionally a simple,
    honest transformation — not a generative rewrite — since the Engine
    never authors persuasive prose (that stays the Skill Prompt Layer's
    job); the speaker can refine the wording before re-approving."""
    stripped = original_text.strip()
    return f"[UNVERIFIED \u2014 pending re-validation] It has been reported that {stripped[0].lower() + stripped[1:] if stripped else stripped}"


def demote_dependent_claims(conn, workspace_id: str, atom_id: str, actor: str, reason: str) -> list[models.Claim]:
    """FR-EVD-8: called whenever an atom becomes ACCESS_REVOKED/STALE (or is
    rejected). Recomputes every claim citing it; a factual claim that has
    lost all valid supporting evidence is demoted to REWRITE_REQUIRED with
    an attached hedged rewrite, never left silently at its old wording."""
    from . import claims as claims_mod

    atom = persistence.get(conn, "evidence", atom_id, models.EvidenceAtom)
    if atom is None:
        return []
    demoted = []
    for claim_id in atom.linked_claim_ids:
        claim = persistence.get(conn, "claim", claim_id, models.Claim)
        if claim is None:
            continue
        demoted_claim = claims_mod.reassess_after_evidence_change(conn, workspace_id, claim, actor, reason)
        if demoted_claim is not None:
            demoted.append(demoted_claim)
    return demoted
