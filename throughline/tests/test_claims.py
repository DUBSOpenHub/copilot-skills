"""Claim Engine + Conflict Detector: exactly-one-type enforcement,
FR-EVD-6 aspirational labeling, FR-EVD-8 demotion, FR-NAR-6 immutability,
and both conflict mechanisms (sensitivity-label auto-detect, explicit
contradiction)."""
from __future__ import annotations

import unittest

from helpers import EngineError, claims_mod, cleanup, evidence_mod, ingest_paste, make_workspace, models, new_store


class ClaimTypingTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_claim_carries_exactly_one_type(self):
        ws, brief, conn = make_workspace(self.store)
        claim = claims_mod.propose_claims(conn, ws.id, [{"type": "factual", "text": "X"}], actor="T")[0]
        self.assertIn(claim.type, [t.value for t in models.ClaimType])
        conn.close()

    def test_invalid_type_rejected(self):
        ws, brief, conn = make_workspace(self.store)
        with self.assertRaises(EngineError) as ctx:
            claims_mod.propose_claims(conn, ws.id, [{"type": "opinion", "text": "X"}], actor="T")
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        conn.close()

    def test_type_is_case_insensitive(self):
        ws, brief, conn = make_workspace(self.store)
        claim = claims_mod.propose_claims(conn, ws.id, [{"type": "FACTUAL", "text": "X"}], actor="T")[0]
        self.assertEqual(claim.type, models.ClaimType.FACTUAL.value)
        conn.close()

    def test_empty_text_rejected(self):
        ws, brief, conn = make_workspace(self.store)
        with self.assertRaises(EngineError):
            claims_mod.propose_claims(conn, ws.id, [{"type": "factual", "text": "   "}], actor="T")
        conn.close()


class FactualClaimTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_factual_claim_with_zero_evidence_is_unsupported(self):
        ws, brief, conn = make_workspace(self.store)
        claim = claims_mod.propose_claims(conn, ws.id, [{"type": "factual", "text": "X"}], actor="T")[0]
        self.assertEqual(claim.state, models.ClaimState.UNSUPPORTED.value)
        conn.close()

    def test_factual_claim_with_kept_evidence_is_verified(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Evidence text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        claim = claims_mod.propose_claims(conn, ws.id, [
            {"type": "factual", "text": "X", "evidenceAtomIds": [atoms[0].id]},
        ], actor="T")[0]
        self.assertEqual(claim.state, models.ClaimState.VERIFIED.value)
        conn.close()


class InterpretiveClaimTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_interpretive_requires_rationale_and_evidence_to_approve(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Evidence text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        claim = claims_mod.propose_claims(conn, ws.id, [
            {"type": "interpretive", "text": "X", "evidenceAtomIds": [atoms[0].id]},
        ], actor="T")[0]
        with self.assertRaises(EngineError) as ctx:
            claims_mod.approve_claim(conn, ws.id, claim.id, actor="T")
        self.assertEqual(ctx.exception.code, "RATIONALE_REQUIRED")
        claims_mod.set_rationale(conn, ws.id, claim.id, "Because evidence shows a trend.", actor="T")
        approval = claims_mod.approve_claim(conn, ws.id, claim.id, actor="Approver Name")
        self.assertEqual(approval.actor, "Approver Name")
        conn.close()


class AspirationalClaimTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_aspirational_requires_label_to_approve(self):
        ws, brief, conn = make_workspace(self.store)
        claim = claims_mod.propose_claims(conn, ws.id, [{"type": "aspirational", "text": "We recommend X"}], actor="T")[0]
        with self.assertRaises(EngineError):
            claims_mod.approve_claim(conn, ws.id, claim.id, actor="T")
        claims_mod.set_aspirational_label(conn, ws.id, claim.id, "recommendation", actor="T")
        approval = claims_mod.approve_claim(conn, ws.id, claim.id, actor="T")
        self.assertEqual(approval.decision, "approved")
        conn.close()

    def test_invalid_label_rejected(self):
        ws, brief, conn = make_workspace(self.store)
        claim = claims_mod.propose_claims(conn, ws.id, [{"type": "aspirational", "text": "We recommend X"}], actor="T")[0]
        with self.assertRaises(EngineError):
            claims_mod.set_aspirational_label(conn, ws.id, claim.id, "WISH", actor="T")
        conn.close()


class LockAndRewriteTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def _approved_factual_claim(self, conn, ws_id):
        source = ingest_paste(conn, self.store, ws_id, "Evidence text.")
        atoms = evidence_mod.extract_evidence(conn, ws_id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws_id, atoms[0].id, "KEEP", actor="T")
        claim = claims_mod.propose_claims(conn, ws_id, [
            {"type": "factual", "text": "X", "evidenceAtomIds": [atoms[0].id]},
        ], actor="T")[0]
        claims_mod.approve_claim(conn, ws_id, claim.id, actor="T")
        return claim, atoms[0]

    def test_lock_requires_approved_state(self):
        ws, brief, conn = make_workspace(self.store)
        claim = claims_mod.propose_claims(conn, ws.id, [{"type": "factual", "text": "X"}], actor="T")[0]
        with self.assertRaises(EngineError):
            claims_mod.lock_claim(conn, ws.id, claim.id, actor="T")
        conn.close()

    def test_locked_claim_cannot_be_linked_without_rewrite(self):
        ws, brief, conn = make_workspace(self.store)
        claim, atom = self._approved_factual_claim(conn, ws.id)
        claims_mod.lock_claim(conn, ws.id, claim.id, actor="T")
        with self.assertRaises(EngineError) as ctx:
            claims_mod.link_evidence(conn, ws.id, claim.id, atom.id, actor="T")
        self.assertEqual(ctx.exception.code, "IMMUTABLE_LOCKED_CLAIM")
        conn.close()

    def test_explicit_rewrite_is_the_only_way_to_change_locked_text(self):
        ws, brief, conn = make_workspace(self.store)
        claim, atom = self._approved_factual_claim(conn, ws.id)
        claims_mod.lock_claim(conn, ws.id, claim.id, actor="T")
        rewritten = claims_mod.rewrite_claim(conn, ws.id, claim.id, "New wording", actor="T")
        self.assertEqual(rewritten.text, "New wording")
        self.assertIsNone(rewritten.approver)  # needs fresh approval
        conn.close()

    def test_demotion_attaches_hedged_rewrite_never_silently_kept(self):
        ws, brief, conn = make_workspace(self.store)
        claim, atom = self._approved_factual_claim(conn, ws.id)
        original_text = claim.text
        evidence_mod.set_disposition(conn, ws.id, atom.id, "REJECT", actor="T")
        import engine.persistence as persistence
        refreshed = persistence.get(conn, "claim", claim.id, models.Claim)
        self.assertEqual(refreshed.state, models.ClaimState.REWRITE_REQUIRED.value)
        self.assertIn(original_text[0].lower(), refreshed.hedged_rewrite.lower())
        self.assertNotEqual(refreshed.hedged_rewrite, original_text)
        conn.close()


class ConflictDetectorTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_sensitivity_label_mismatch_auto_creates_conflict(self):
        ws, brief, conn = make_workspace(self.store)
        s1 = ingest_paste(conn, self.store, ws.id, "Fact one.", uri="paste:a", sensitivity_label="internal")
        s2 = ingest_paste(conn, self.store, ws.id, "Fact two.", uri="paste:b", sensitivity_label="confidential")
        a1 = evidence_mod.extract_evidence(conn, ws.id, s1.id, actor="T")[0]
        a2 = evidence_mod.extract_evidence(conn, ws.id, s2.id, actor="T")[0]
        evidence_mod.set_disposition(conn, ws.id, a1.id, "KEEP", actor="T")
        evidence_mod.set_disposition(conn, ws.id, a2.id, "KEEP", actor="T")
        claim = claims_mod.propose_claims(conn, ws.id, [
            {"type": "factual", "text": "X", "evidenceAtomIds": [a1.id, a2.id]},
        ], actor="T")[0]
        import engine.persistence as persistence
        conflicts = persistence.list_all(conn, "conflict", ws.id, models.ConflictCard)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].kind, "sensitivity_label")
        refreshed = persistence.get(conn, "claim", claim.id, models.Claim)
        self.assertEqual(refreshed.state, models.ClaimState.CONFLICTED.value)
        conn.close()

    def test_explicit_contradiction_blocks_until_resolved(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "42 percent.\n\n55 percent.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        for a in atoms:
            evidence_mod.set_disposition(conn, ws.id, a.id, "KEEP", actor="T")
        claim = claims_mod.propose_claims(conn, ws.id, [{"type": "factual", "text": "The growth rate"}], actor="T")[0]
        claims_mod.link_evidence(conn, ws.id, claim.id, atoms[0].id, actor="T")
        claims_mod.link_evidence(conn, ws.id, claim.id, atoms[1].id, actor="T", contradicts_atom_id=atoms[0].id)
        import engine.persistence as persistence
        conflicts = persistence.list_all(conn, "conflict", ws.id, models.ConflictCard)
        open_conflicts = [c for c in conflicts if c.status == "OPEN"]
        self.assertEqual(len(open_conflicts), 1)
        self.assertEqual(open_conflicts[0].kind, "contradiction")
        self.assertEqual(open_conflicts[0].source_a, source.uri)
        with self.assertRaises(EngineError):
            claims_mod.approve_claim(conn, ws.id, claim.id, actor="T")
        claims_mod.resolve_conflict(conn, ws.id, open_conflicts[0].id, "Kept the newer figure per the speaker.", actor="T")
        refreshed = persistence.get(conn, "claim", claim.id, models.Claim)
        self.assertNotEqual(refreshed.state, models.ClaimState.CONFLICTED.value)
        conn.close()


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_verify_grounding_requires_approved_or_locked(self):
        ws, brief, conn = make_workspace(self.store)
        claim = claims_mod.propose_claims(conn, ws.id, [{"type": "factual", "text": "X"}], actor="T")[0]
        result = claims_mod.verify_grounding(conn, ws.id, [claim.id])
        self.assertFalse(result["allGrounded"])
        source = ingest_paste(conn, self.store, ws.id, "Evidence.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        claims_mod.link_evidence(conn, ws.id, claim.id, atoms[0].id, actor="T")
        claims_mod.approve_claim(conn, ws.id, claim.id, actor="T")
        result2 = claims_mod.verify_grounding(conn, ws.id, [claim.id])
        self.assertTrue(result2["allGrounded"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
