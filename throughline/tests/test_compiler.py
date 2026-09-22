"""Deck Compiler: slide count, region contract, headline length limit,
and the ID-stability golden test (ARCH §15)."""
from __future__ import annotations

import unittest

from helpers import EngineError, claims_mod, cleanup, compiler, evidence_mod, ingest_paste, make_workspace, models, narrative, new_store

FILLER_ROUTE = {"label": "Filler (unselected)", "beats": [
    {"role": "HOOK", "headline": "Filler hook", "timeBudgetSeconds": 60},
    {"role": "ASK", "headline": "Filler ask", "timeBudgetSeconds": 60},
]}


class CompileHappyPathTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def _compiled_slides(self, conn, ws, brief):
        source = ingest_paste(conn, self.store, ws.id, "Fact text.")
        atom = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")[0]
        evidence_mod.set_disposition(conn, ws.id, atom.id, "KEEP", actor="T")
        factual = claims_mod.propose_claims(conn, ws.id, [
            {"type": "factual", "text": "Fact", "evidenceAtomIds": [atom.id]},
        ], actor="T")[0]
        aspirational = claims_mod.propose_claims(conn, ws.id, [
            {"type": "aspirational", "text": "Goal", "aspirationalLabel": "GOAL"},
        ], actor="T")[0]
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        sel = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
        beats = [
            {"role": "HOOK", "headline": "Hook", "timeBudgetSeconds": 60},
            {"role": "STAKES", "headline": "Stakes", "timeBudgetSeconds": 60},
            {"role": "TURN", "headline": "Turn", "timeBudgetSeconds": 60},
            {"role": "MECHANISM", "headline": "Mechanism", "timeBudgetSeconds": 60, "visualDescription": "Diagram"},
            {"role": "PROOF", "headline": "Proof", "timeBudgetSeconds": 60, "claimIds": [factual.id], "visualDescription": "Chart", "spokenTalkTrack": "Here is the proof point."},
            {"role": "OBJECTION", "headline": "Objection", "timeBudgetSeconds": 60, "claimIds": [aspirational.id]},
            {"role": "ASK", "headline": "Ask", "timeBudgetSeconds": 60},
        ]
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        return compiler.compile_deck(conn, ws.id, actor="T")

    def test_slide_count_within_bounds(self):
        ws, brief, conn = make_workspace(self.store)
        slides = self._compiled_slides(conn, ws, brief)
        self.assertGreaterEqual(len(slides), 7)
        self.assertLessEqual(len(slides), 15)
        conn.close()

    def test_hook_slide_has_no_visual_region(self):
        ws, brief, conn = make_workspace(self.store)
        slides = self._compiled_slides(conn, ws, brief)
        hook = [s for s in slides if s.role == "HOOK"][0]
        self.assertEqual(hook.layout, "hook")
        self.assertNotIn("visual", hook.regions)
        conn.close()

    def test_standard_slide_has_all_nine_regions(self):
        ws, brief, conn = make_workspace(self.store)
        slides = self._compiled_slides(conn, ws, brief)
        proof = [s for s in slides if s.role == "PROOF"][0]
        expected = {"headline", "visual", "body", "notes.spoken", "notes.transitionIn",
                    "notes.transitionOut", "notes.timeBudget", "notes.fallback", "notes.sources"}
        self.assertEqual(set(proof.regions.keys()), expected)
        conn.close()

    def test_aspirational_claim_gets_visible_label_prefix(self):
        ws, brief, conn = make_workspace(self.store)
        slides = self._compiled_slides(conn, ws, brief)
        objection = [s for s in slides if s.role == "OBJECTION"][0]
        self.assertIn("[GOAL]", objection.regions["body"].text)
        conn.close()

    def test_each_slide_has_at_most_three_claims(self):
        ws, brief, conn = make_workspace(self.store)
        slides = self._compiled_slides(conn, ws, brief)
        for s in slides:
            self.assertLessEqual(len(s.claim_ids()), 3)
        conn.close()

    def test_notes_have_talk_track_time_budget_fallback_and_source(self):
        ws, brief, conn = make_workspace(self.store)
        slides = self._compiled_slides(conn, ws, brief)
        proof = [s for s in slides if s.role == "PROOF"][0]
        self.assertTrue(proof.regions["notes.spoken"].text)
        self.assertTrue(proof.regions["notes.timeBudget"].text.isdigit())
        self.assertTrue(proof.regions["notes.fallback"].text)
        self.assertTrue(proof.regions["notes.sources"].text)
        conn.close()

    def test_headline_over_limit_blocks_compile(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Fact text.")
        atom = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")[0]
        evidence_mod.set_disposition(conn, ws.id, atom.id, "KEEP", actor="T")
        factual = claims_mod.propose_claims(conn, ws.id, [
            {"type": "factual", "text": "Fact", "evidenceAtomIds": [atom.id]},
        ], actor="T")[0]
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        sel = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
        too_long = "X" * 150
        beats = [
            {"role": "HOOK", "headline": too_long, "timeBudgetSeconds": 60},
            {"role": "STAKES", "headline": "Stakes", "timeBudgetSeconds": 60},
            {"role": "TURN", "headline": "Turn", "timeBudgetSeconds": 60},
            {"role": "MECHANISM", "headline": "Mechanism", "timeBudgetSeconds": 60},
            {"role": "PROOF", "headline": "Proof", "timeBudgetSeconds": 60, "claimIds": [factual.id]},
            {"role": "OBJECTION", "headline": "Objection", "timeBudgetSeconds": 60},
            {"role": "ASK", "headline": "Ask", "timeBudgetSeconds": 60},
        ]
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        with self.assertRaises(EngineError) as ctx:
            compiler.compile_deck(conn, ws.id, actor="T")
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        conn.close()

    def test_id_stability_golden_test(self):
        """Compiling the same, unchanged workspace twice must produce
        byte-identical deck/slide/region IDs, and contentHash values
        unaffected by timestamp-only differences (ARCH §15)."""
        ws, brief, conn = make_workspace(self.store)
        slides_first = self._compiled_slides(conn, ws, brief)
        ids_first = sorted((s.id, tuple(sorted(s.regions.keys())), {r: reg.content_hash for r, reg in s.regions.items()}.items()) for s in slides_first)

        import time
        time.sleep(0.01)  # ensure any timestamp fields would differ if used
        slides_second = compiler.compile_deck(conn, ws.id, actor="T")
        ids_second = sorted((s.id, tuple(sorted(s.regions.keys())), {r: reg.content_hash for r, reg in s.regions.items()}.items()) for s in slides_second)

        self.assertEqual(ids_first, ids_second)
        self.assertEqual({s.id for s in slides_first}, {s.id for s in slides_second})
        for s1, s2 in zip(sorted(slides_first, key=lambda s: s.id), sorted(slides_second, key=lambda s: s.id)):
            for role in s1.regions:
                self.assertEqual(s1.regions[role].content_hash, s2.regions[role].content_hash)
        conn.close()

    def test_recompile_preserves_accessibility_metadata(self):
        ws, brief, conn = make_workspace(self.store)
        slides = self._compiled_slides(conn, ws, brief)
        proof = [s for s in slides if s.role == "PROOF"][0]
        compiler.set_alt_text(conn, ws.id, proof.id, "visual", "A bar chart", confirmed_by="Speaker", actor="T")
        recompiled = compiler.compile_deck(conn, ws.id, actor="T")
        proof2 = [s for s in recompiled if s.role == "PROOF"][0]
        self.assertEqual(proof2.regions["visual"].alt_text, "A bar chart")
        self.assertEqual(proof2.regions["visual"].alt_text_confirmed_by, "Speaker")
        conn.close()


class ProposeCutsTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_hook_and_ask_are_never_cut(self):
        ws, brief, conn = make_workspace(self.store)
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        sel = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
        beats = [
            {"role": "HOOK", "headline": "Hook", "timeBudgetSeconds": 60},
            {"role": "STAKES", "headline": "Stakes", "timeBudgetSeconds": 300},
            {"role": "TURN", "headline": "Turn", "timeBudgetSeconds": 300},
            {"role": "ASK", "headline": "Ask", "timeBudgetSeconds": 60},
        ]
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        cuts = compiler.propose_cuts(conn, ws.id, target_seconds=120)
        import engine.persistence as persistence
        route = persistence.get(conn, "route", routes[0].id, models.NarrativeRoute)
        cut_beats = [b for b in route.beats if b.id in cuts]
        self.assertTrue(all(b.role not in ("HOOK", "ASK") for b in cut_beats))
        self.assertTrue(len(cuts) > 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
