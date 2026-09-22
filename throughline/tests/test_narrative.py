"""Narrative Store + Narrative Gate: exactly-3-throughlines, custom
override, 2-3 routes, and every FR-NAR-4 gate rule individually."""
from __future__ import annotations

import unittest

from helpers import (
    EngineError, claims_mod, cleanup, evidence_mod, ingest_paste, make_workspace, models, narrative, new_store,
)

FILLER_ROUTE = {"label": "Filler (unselected)", "beats": [
    {"role": "HOOK", "headline": "Filler hook", "timeBudgetSeconds": 60},
    {"role": "ASK", "headline": "Filler ask", "timeBudgetSeconds": 60},
]}


def _seven_valid_beats(factual_id, aspirational_id):
    return [
        {"role": "HOOK", "headline": "Hook", "timeBudgetSeconds": 60},
        {"role": "STAKES", "headline": "Stakes", "timeBudgetSeconds": 60},
        {"role": "TURN", "headline": "Turn", "timeBudgetSeconds": 60},
        {"role": "MECHANISM", "headline": "Mechanism", "timeBudgetSeconds": 60},
        {"role": "PROOF", "headline": "Proof", "timeBudgetSeconds": 60, "claimIds": [factual_id]},
        {"role": "OBJECTION", "headline": "Objection", "timeBudgetSeconds": 60, "claimIds": [aspirational_id]},
        {"role": "ASK", "headline": "Ask", "timeBudgetSeconds": 60},
    ]


class ThroughlineTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_requires_exactly_three_drafts(self):
        ws, brief, conn = make_workspace(self.store)
        with self.assertRaises(EngineError) as ctx:
            narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B"], actor="T")
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        with self.assertRaises(EngineError):
            narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C", "D"], actor="T")
        conn.close()

    def test_no_auto_select_and_custom_text_wins(self):
        ws, brief, conn = make_workspace(self.store)
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        self.assertTrue(all(not t.selected for t in throughlines))
        selected = narrative.select_throughline(conn, ws.id, actor="T", custom_text="My own throughline")
        self.assertEqual(selected.text, "My own throughline")
        self.assertEqual(selected.origin, "custom")
        conn.close()

    def test_selecting_a_proposed_candidate_deselects_others(self):
        ws, brief, conn = make_workspace(self.store)
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[1].id)
        import engine.persistence as persistence
        all_t = persistence.list_all(conn, "throughline", ws.id, models.NarrativeThroughline)
        selected = [t for t in all_t if t.selected]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].id, throughlines[1].id)
        conn.close()


class RouteCountTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_requires_two_or_three_routes(self):
        ws, brief, conn = make_workspace(self.store)
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        sel = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
        with self.assertRaises(EngineError) as ctx:
            narrative.propose_routes(conn, ws.id, sel.id, [FILLER_ROUTE], actor="T")
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        conn.close()

    def test_beat_claim_cap_enforced_at_proposal(self):
        ws, brief, conn = make_workspace(self.store)
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        sel = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
        bad_route = {"label": "R", "beats": [
            {"role": "HOOK", "headline": "H", "timeBudgetSeconds": 60},
            {"role": "PROOF", "headline": "P", "timeBudgetSeconds": 60, "claimIds": ["a", "b", "c", "d"]},
            {"role": "ASK", "headline": "A", "timeBudgetSeconds": 60},
        ]}
        with self.assertRaises(EngineError) as ctx:
            narrative.propose_routes(conn, ws.id, sel.id, [bad_route, FILLER_ROUTE], actor="T")
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        conn.close()


class NarrativeGateTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def _claims(self, conn, ws_id):
        source = ingest_paste(conn, self.store, ws_id, "Fact text.")
        atom = evidence_mod.extract_evidence(conn, ws_id, source.id, actor="T")[0]
        evidence_mod.set_disposition(conn, ws_id, atom.id, "KEEP", actor="T")
        factual = claims_mod.propose_claims(conn, ws_id, [
            {"type": "factual", "text": "Fact", "evidenceAtomIds": [atom.id]},
        ], actor="T")[0]
        aspirational = claims_mod.propose_claims(conn, ws_id, [
            {"type": "aspirational", "text": "Goal", "aspirationalLabel": "GOAL"},
        ], actor="T")[0]
        return factual, aspirational

    def _select(self, conn, ws_id, brief_id):
        throughlines = narrative.propose_throughlines(conn, ws_id, brief_id, ["A", "B", "C"], actor="T")
        return narrative.select_throughline(conn, ws_id, actor="T", throughline_id=throughlines[0].id)

    def test_valid_route_passes_every_rule(self):
        ws, brief, conn = make_workspace(self.store)
        factual, aspirational = self._claims(conn, ws.id)
        sel = self._select(conn, ws.id, brief.id)
        routes = narrative.propose_routes(conn, ws.id, sel.id, [
            {"label": "R", "beats": _seven_valid_beats(factual.id, aspirational.id)}, FILLER_ROUTE,
        ], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        result = narrative.run_narrative_gate(conn, ws.id, actor="T")
        self.assertTrue(result.passed, result.failed_checks)
        conn.close()

    def test_missing_hook_fails(self):
        ws, brief, conn = make_workspace(self.store)
        factual, aspirational = self._claims(conn, ws.id)
        sel = self._select(conn, ws.id, brief.id)
        beats = _seven_valid_beats(factual.id, aspirational.id)
        beats[0] = {"role": "STAKES", "headline": "Not a hook", "timeBudgetSeconds": 60}
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        result = narrative.run_narrative_gate(conn, ws.id, actor="T")
        self.assertFalse(result.passed)
        self.assertTrue(any("HOOK" in f.message for f in result.failed_checks))
        conn.close()

    def test_missing_ask_fails(self):
        ws, brief, conn = make_workspace(self.store)
        factual, aspirational = self._claims(conn, ws.id)
        sel = self._select(conn, ws.id, brief.id)
        beats = _seven_valid_beats(factual.id, aspirational.id)
        beats[-1] = {"role": "OBJECTION", "headline": "Not an ask", "timeBudgetSeconds": 60}
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        result = narrative.run_narrative_gate(conn, ws.id, actor="T")
        self.assertFalse(result.passed)
        self.assertTrue(any("ASK" in f.message for f in result.failed_checks))
        conn.close()

    def test_adjacent_beat_job_collision_fails(self):
        ws, brief, conn = make_workspace(self.store)
        factual, aspirational = self._claims(conn, ws.id)
        sel = self._select(conn, ws.id, brief.id)
        beats = _seven_valid_beats(factual.id, aspirational.id)
        beats[2] = dict(beats[1])  # duplicate STAKES right after STAKES
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        result = narrative.run_narrative_gate(conn, ws.id, actor="T")
        self.assertFalse(result.passed)
        self.assertTrue(any("collision" in f.message for f in result.failed_checks))
        conn.close()

    def test_unverified_proof_beat_fails(self):
        ws, brief, conn = make_workspace(self.store)
        factual, aspirational = self._claims(conn, ws.id)
        sel = self._select(conn, ws.id, brief.id)
        beats = _seven_valid_beats(factual.id, aspirational.id)
        beats[4]["claimIds"] = []  # PROOF beat with no claim at all
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        result = narrative.run_narrative_gate(conn, ws.id, actor="T")
        self.assertFalse(result.passed)
        self.assertTrue(any("PROOF" in f.message for f in result.failed_checks))
        conn.close()

    def test_unlabeled_aspirational_claim_fails(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Fact text.")
        atom = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")[0]
        evidence_mod.set_disposition(conn, ws.id, atom.id, "KEEP", actor="T")
        factual = claims_mod.propose_claims(conn, ws.id, [
            {"type": "factual", "text": "Fact", "evidenceAtomIds": [atom.id]},
        ], actor="T")[0]
        # Aspirational claim proposed WITHOUT a label.
        aspirational = claims_mod.propose_claims(conn, ws.id, [{"type": "aspirational", "text": "Goal"}], actor="T")[0]
        sel = self._select(conn, ws.id, brief.id)
        beats = _seven_valid_beats(factual.id, aspirational.id)
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        result = narrative.run_narrative_gate(conn, ws.id, actor="T")
        self.assertFalse(result.passed)
        self.assertTrue(any("aspirational" in f.message for f in result.failed_checks))
        conn.close()

    def test_less_than_ten_percent_buffer_fails(self):
        ws, brief, conn = make_workspace(self.store, brief_overrides={"durationMinutes": 8})
        factual, aspirational = self._claims(conn, ws.id)
        sel = self._select(conn, ws.id, brief.id)
        beats = _seven_valid_beats(factual.id, aspirational.id)  # totals 420s = 7min, but budget is 8min=480s -> buffer 12.5%, fine
        # Tighten the budget further so buffer drops under 10%.
        ws_full = None
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        # 420/480 = 87.5% allocated -> 12.5% buffer, should PASS; now shrink duration to 7 minutes (420s) -> 0% buffer, should FAIL.
        import engine.persistence as persistence
        ws_row = persistence.get(conn, "workspace", ws.id, models.Workspace)
        b = persistence.get(conn, "brief", ws_row.brief_id, models.TalkBrief)
        b.duration_minutes = 7.0
        persistence.commit(conn, "brief", b, None)
        result = narrative.run_narrative_gate(conn, ws.id, actor="T")
        self.assertFalse(result.passed)
        self.assertTrue(any("buffer" in f.message for f in result.failed_checks))
        conn.close()

    def test_too_few_slides_fails(self):
        ws, brief, conn = make_workspace(self.store)
        sel = self._select(conn, ws.id, brief.id)
        routes = narrative.propose_routes(conn, ws.id, sel.id, [
            {"label": "R", "beats": [
                {"role": "HOOK", "headline": "H", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "A", "timeBudgetSeconds": 60},
            ]}, FILLER_ROUTE,
        ], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        result = narrative.run_narrative_gate(conn, ws.id, actor="T")
        self.assertFalse(result.passed)
        self.assertTrue(any("7-15" in f.message or "beats" in f.message for f in result.failed_checks))
        conn.close()


if __name__ == "__main__":
    unittest.main()
