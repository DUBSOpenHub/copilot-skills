"""Evidence Ledger: disposition changes and FR-EVD-2's "a rejected atom is
never cited" guarantee."""
from __future__ import annotations

import unittest

from helpers import EngineError, claims_mod, cleanup, evidence_mod, ingest_paste, make_workspace, models, new_store


class DispositionTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_disposition_defaults_to_pending(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Some text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        self.assertEqual(atoms[0].disposition, models.Disposition.PENDING.value)
        conn.close()

    def test_only_kept_atoms_are_linkable_to_claims(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Some text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "REJECT", actor="T")
        claim = claims_mod.propose_claims(conn, ws.id, [{"type": "factual", "text": "X"}], actor="T")[0]
        with self.assertRaises(EngineError) as ctx:
            claims_mod.link_evidence(conn, ws.id, claim.id, atoms[0].id, actor="T")
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        conn.close()

    def test_rejecting_a_linked_atom_unlinks_it_from_every_claim(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Some text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        claim = claims_mod.propose_claims(conn, ws.id, [
            {"type": "factual", "text": "X", "evidenceAtomIds": [atoms[0].id]},
        ], actor="T")[0]
        self.assertIn(atoms[0].id, claim.evidence_atom_ids)
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "REJECT", actor="T")
        import engine.persistence as persistence
        refreshed = persistence.get(conn, "claim", claim.id, models.Claim)
        self.assertNotIn(atoms[0].id, refreshed.evidence_atom_ids)
        self.assertEqual(refreshed.state, models.ClaimState.UNSUPPORTED.value)
        conn.close()

    def test_disposition_is_case_insensitive(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Some text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        atom = evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "keep", actor="T")
        self.assertEqual(atom.disposition, models.Disposition.KEEP.value)
        conn.close()

    def test_invalid_disposition_rejected(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Some text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        with self.assertRaises(EngineError) as ctx:
            evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "MAYBE", actor="T")
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        conn.close()

    def test_extract_is_idempotent_without_force(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Some text.")
        first = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        second = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        self.assertEqual([a.id for a in first], [a.id for a in second])
        conn.close()

    def test_image_source_yields_single_low_confidence_atom(self):
        ws, brief, conn = make_workspace(self.store)
        payload = {
            "origin": "local", "sourceType": "local_upload", "uri": str(self.root / "img.png"),
            "owner": "x@example.com", "permissionState": "authorized", "aclSnapshot": "owner", "version": "v1",
        }
        (self.root / "img.png").write_bytes(b"\x89PNGbinarydata")
        from helpers import ingest_mod
        source = ingest_mod.ingest_source(conn, ws.id, payload, actor="T", staging_dir=self.store.workspace_dir(ws.id) / "staging")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        self.assertEqual(len(atoms), 1)
        self.assertLess(atoms[0].confidence, 0.5)
        conn.close()


if __name__ == "__main__":
    unittest.main()
