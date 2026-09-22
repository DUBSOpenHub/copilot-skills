"""Restore Point Manager: a restore point at every gate pass/compile/
export, and "one action reverts to the last-known-good deck" (FR-DEL-7)."""
from __future__ import annotations

import unittest

from helpers import claims_mod, cleanup, evidence_mod, gates, ingest_paste, make_workspace, models, new_store, restore_mod


class RestorePointTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_passing_gate_creates_a_restore_point(self):
        ws, brief, conn = make_workspace(self.store)
        before = len(restore_mod.list_restore_points(conn, ws.id))
        gates.run_gate(conn, ws.id, "scope", actor="T")
        after = restore_mod.list_restore_points(conn, ws.id)
        self.assertGreater(len(after), before)
        self.assertTrue(any(rp.trigger == "gate:scope" for rp in after))
        conn.close()

    def test_apply_reverts_state_and_snapshots_current_first(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Original text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        claim = claims_mod.propose_claims(conn, ws.id, [
            {"type": "factual", "text": "Original claim", "evidenceAtomIds": [atoms[0].id]},
        ], actor="T")[0]
        gates.run_gate(conn, ws.id, "scope", actor="T")  # creates a restore point capturing this state
        restore_points = restore_mod.list_restore_points(conn, ws.id)
        target = [rp for rp in restore_points if rp.trigger == "gate:scope"][-1]

        # Mutate further after the restore point.
        claims_mod.propose_claims(conn, ws.id, [{"type": "factual", "text": "A second claim"}], actor="T")

        rp, pre_revert = restore_mod.apply_restore_point(conn, ws.id, target.id, actor="T")
        self.assertEqual(rp.id, target.id)
        self.assertIsNotNone(pre_revert.id)

        # conn was closed by apply_restore_point (file was swapped); reconnect.
        conn2 = self.store.connect(ws.id)
        import engine.persistence as persistence
        claims_after_revert = persistence.list_all(conn2, "claim", ws.id, models.Claim)
        self.assertEqual(len(claims_after_revert), 1)
        self.assertEqual(claims_after_revert[0].text, "Original claim")
        conn2.close()

    def test_restore_point_not_found_is_a_clear_error(self):
        from engine.errors import EngineError
        ws, brief, conn = make_workspace(self.store)
        with self.assertRaises(EngineError) as ctx:
            restore_mod.apply_restore_point(conn, ws.id, "restore:does-not-exist", actor="T")
        self.assertEqual(ctx.exception.code, "RESTORE_POINT_NOT_FOUND")
        conn.close()


if __name__ == "__main__":
    unittest.main()
