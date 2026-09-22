"""Regression tests for lazy default-route generation timing and route-
candidate persistence in the ordered action-list executor (Dark Factory
hardening cycle 10, acceptance pass 13:
`engine/scenario._run_ordered_action_list`'s `_select_route_now`), plus
confirmation that ordered-list tail finalization never double-records a
domain refusal already recorded by an explicit action.

Compatibility gap this closes: a source-driven ordered scenario that
omits an explicit `propose_route`/`routeDrafts` action and instead
invokes `select_narrative_route`, `compile_deck`, or `rehearse` directly
still needs `narrative.default_route_drafts` to fire exactly once,
lazily, before any of those actions' own validation -- and, separately,
once routes are proposed, they must be visible in `report["route"]
["candidates"]` immediately, so a *later* failure (an out-of-range
`select_narrative_route`, or any other refusal further down the same
walk) never erases already-durably-persisted route candidates from the
caller-visible report.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import DEFAULT_BRIEF, REPO_ROOT, cleanup, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _brief_step(**overrides) -> dict:
    payload = {"action": "set_talk_brief", **DEFAULT_BRIEF}
    payload.update(overrides)
    return payload


def _source_step(uri: str, **overrides) -> dict:
    payload = {
        "action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": uri,
        "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
        "version": "v1", "content": "Adoption grew 42% quarter over quarter across every pilot team surveyed.",
    }
    payload.update(overrides)
    return payload


def _claim_step(uri: str, **overrides) -> dict:
    payload = {
        "action": "propose_claim", "type": "factual", "text": "Adoption grew 42% quarter over quarter.",
        "evidenceLocators": [uri], "approve": True,
    }
    payload.update(overrides)
    return payload


class LazyDefaultRouteGenerationBeforeEachTriggerTests(unittest.TestCase):
    """A source-driven ordered document with no explicit `propose_route`/
    `routeDrafts` action still gets exactly two default route candidates,
    generated exactly once, lazily, right before whichever of
    `select_narrative_route`/`compile_deck`/`rehearse` is the first to
    need one -- never proposed twice, and never auto-selected merely by
    being proposed."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _run(self, trailing_action: dict) -> dict:
        doc = [_brief_step(), _source_step("paste:lazy-route"), _claim_step("paste:lazy-route"), trailing_action]
        store = persistence.Store(root=self.root / "ws")
        return scenario.run_scenario(store, doc, self.root / "report")

    def test_select_narrative_route_lazily_generates_defaults(self):
        report = self._run({"action": "select_narrative_route", "value": 0})
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["route"]["candidates"]), 2)
        self.assertIsNotNone(report["route"]["active"])

    def test_compile_deck_lazily_generates_defaults_with_no_explicit_selection(self):
        report = self._run({"action": "compile_deck"})
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["route"]["candidates"]), 2)
        self.assertGreater(len(report.get("slides", [])), 0)

    def test_rehearse_lazily_generates_defaults_with_no_explicit_selection_or_compile(self):
        report = self._run({"action": "rehearse"})
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["route"]["candidates"]), 2)
        self.assertIn("rehearsal", report)

    def test_ordered_list_end_of_walk_finalization_also_lazily_generates_defaults(self):
        """No trailing narrative action at all -- the implicit tail
        phase is the one that first needs a route."""
        doc = [_brief_step(), _source_step("paste:lazy-tail"), _claim_step("paste:lazy-tail")]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["route"]["candidates"]), 2)
        self.assertIn("package", report)

    def test_default_generation_never_happens_twice_even_with_two_triggers(self):
        """`compile_deck` already ensures a route is selected/compiled;
        a later explicit `rehearse` action must reuse the identical
        already-proposed/selected route, never propose or select again."""
        doc = [
            _brief_step(), _source_step("paste:lazy-twice"), _claim_step("paste:lazy-twice"),
            {"action": "compile_deck"}, {"action": "rehearse"},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["route"]["candidates"]), 2)
        select_steps = [s for s in report["steps"] if s["action"] == "narrative.select_route"]
        self.assertEqual(len(select_steps), 1, "a route is only ever selected once per run")

    def test_default_generation_alone_never_auto_selects(self):
        """Direct, in-process coverage: proposing default routes commits
        two genuinely unselected candidates -- `select_narrative_route`'s
        own explicit resolution is what selects one, never the proposal
        step itself."""
        store = persistence.Store(root=self.root / "ws")
        doc = [_brief_step(), _source_step("paste:no-auto-select"), _claim_step("paste:no-auto-select")]
        report = scenario.run_scenario(store, doc, self.root / "report")
        conn = store.connect(report["workspaceId"])
        try:
            from helpers import models, persistence as persistence_mod
            routes = persistence_mod.list_all(conn, "route", report["workspaceId"], models.NarrativeRoute)
        finally:
            conn.close()
        self.assertEqual(len(routes), 2)
        self.assertEqual(sum(1 for r in routes if r.selected), 1, "exactly one route is selected overall")


class RouteCandidatePersistenceAfterALaterRefusalTests(unittest.TestCase):
    """Once `narrative.propose_routes` durably persists candidates, they
    remain visible in `report["route"]["candidates"]` even if the very
    same `select_narrative_route` action's own selection then fails."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_an_out_of_range_select_index_still_reports_the_proposed_candidates(self):
        doc = [
            _brief_step(), _source_step("paste:bad-index"), _claim_step("paste:bad-index"),
            {"action": "select_narrative_route", "value": 99},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("route", report)
        self.assertEqual(len(report["route"]["candidates"]), 2)
        self.assertIsNone(report["route"]["active"])

    def test_the_action_results_ledger_still_records_the_route_selection_as_failed(self):
        doc = [
            _brief_step(), _source_step("paste:bad-index-ledger"), _claim_step("paste:bad-index-ledger"),
            {"action": "select_narrative_route", "value": 99},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        last = report["actionResults"][-1]
        self.assertEqual(last["action"], "select_narrative_route")
        self.assertEqual(last["status"], "failed")
        self.assertEqual(len(report["route"]["candidates"]), 2)

    def test_candidates_are_durably_persisted_on_disk_despite_the_refusal(self):
        doc = [
            _brief_step(), _source_step("paste:bad-index-disk"), _claim_step("paste:bad-index-disk"),
            {"action": "select_narrative_route", "value": 99},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        from helpers import models, persistence as persistence_mod
        conn = store.connect(report["workspaceId"])
        try:
            routes = persistence_mod.list_all(conn, "route", report["workspaceId"], models.NarrativeRoute)
        finally:
            conn.close()
        self.assertEqual(len(routes), 2)


class OrderedFinalizationNoDuplicateRefusalTests(unittest.TestCase):
    """Ordered-list tail finalization (`scenario.tail`) and an explicit
    action's own refusal never both record the same domain refusal --
    exactly one `actionResults` entry describes any single failure,
    whichever phase (an explicit action, or the automatic end-of-walk
    tail) actually raised it."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_a_bare_brief_ordered_list_records_exactly_one_tail_refusal(self):
        doc = [_brief_step()]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        tail_entries = [e for e in report["actionResults"] if e["action"] == "scenario.tail"]
        self.assertEqual(len(tail_entries), 1)
        refusal_like_entries = [e for e in report["actionResults"] if not e["ok"]]
        self.assertEqual(len(refusal_like_entries), 1, "the walk-ending refusal is recorded exactly once")
        self.assertEqual(refusal_like_entries[0]["error"]["code"], report["refusal"]["code"])
        self.assertEqual(refusal_like_entries[0]["error"]["message"], report["refusal"]["message"])

    def test_an_explicit_mid_list_refusal_never_also_produces_a_tail_entry(self):
        """When an explicit action itself fails, the walk stops there --
        no `scenario.tail` entry is ever additionally appended for the
        very same run."""
        doc = [
            _brief_step(),
            {"action": "select_route", "value": 0},  # no routes proposed or derivable -> refused here
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        tail_entries = [e for e in report["actionResults"] if e["action"] == "scenario.tail"]
        self.assertEqual(tail_entries, [])
        refusal_like_entries = [e for e in report["actionResults"] if not e["ok"]]
        self.assertEqual(len(refusal_like_entries), 1)

    def test_the_batch_object_form_also_records_its_own_refusal_exactly_once(self):
        """Parallel coverage for the unrelated batch/object-form executor
        (`_run_steps` / `_attach_action_results_ledger`'s own
        `scenario.refusal` tail entry) -- included here purely so both
        documented "runner-generated" shapes are pinned side by side."""
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, {"actor": "T", "brief": dict(DEFAULT_BRIEF)}, self.root / "report")
        self.assertFalse(report["ok"])
        refusal_like_entries = [e for e in report["actionResults"] if not e["ok"]]
        self.assertEqual(len(refusal_like_entries), 1)
        self.assertEqual(refusal_like_entries[0]["action"], "scenario.refusal")


class FullOrderedJourneyWrappedSourceAndOutDirTests(unittest.TestCase):
    """A complete, manual-only ordered journey -- a deeply wrapped,
    originless source descriptor plus the `out_dir` export alias --
    reaches the Stage package through the existing, unweakened domain
    controls (authorization, evidence provenance, gate ordering, named
    human approval)."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _doc(self, out_dir) -> list[dict]:
        beats = [
            {"role": "HOOK", "headline": "A stat that changes the room", "timeBudgetSeconds": 60},
            {"role": "STAKES", "headline": "Talks fail without provenance", "timeBudgetSeconds": 90},
            {"role": "TURN", "headline": "What changes the outcome", "timeBudgetSeconds": 90},
            {"role": "MECHANISM", "headline": "How the ledger works", "timeBudgetSeconds": 120, "isDemo": True},
            {"role": "PROOF", "headline": "Adoption grew 42%", "timeBudgetSeconds": 90, "claimIds": [0]},
            {"role": "OBJECTION", "headline": "Is it worth it", "timeBudgetSeconds": 90},
            {"role": "ASK", "headline": "Start this way", "timeBudgetSeconds": 60},
        ]
        return [
            _brief_step(),
            {"action": "add_source", "payload": {"source": {"descriptor": {
                "sourceType": "local_paste", "uri": "paste:full-journey", "owner": "speaker@example.com",
                "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
                "content": "Adoption grew 42% quarter over quarter across every pilot team surveyed.",
            }}}},
            {"action": "propose_claim", "type": "factual", "text": "Adoption grew 42% quarter over quarter.",
             "evidenceLocators": ["paste:full-journey"], "approve": True},
            {"action": "select_throughline", "value": 0},
            {"action": "propose_route", "label": "Primary route", "beats": beats},
            {"action": "propose_route", "label": "Alternate route", "beats": [
                {"role": "HOOK", "headline": "Alt hook", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "Alt ask", "timeBudgetSeconds": 60},
            ]},
            {"action": "select_route", "value": 0},
            {"action": "set_demo_asset", "slideRole": "MECHANISM", "livePath": "cli-session://live-terminal",
             "prerecordedAssetPath": str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt"),
             "staticAssetPath": str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt"),
             "verbalRecoveryScript": "If the demo fails, describe the ledger verbally."},
            {"action": "rehearse", "run": {slide["role"]: slide["timeBudgetSeconds"] for slide in beats}},
            {"action": "approve_stage", "human": "Ada Lovelace"},
            {"action": "export", "target": "package", "out_dir": str(out_dir)},
        ]

    def test_the_full_journey_reaches_stage_package_via_out_dir(self):
        out_dir = self.root / "full-journey-out-dir"
        doc = self._doc(out_dir)
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)
        self.assertEqual(report["exports"][-1]["exportDir"], str(out_dir))
        self.assertTrue((out_dir / "manifest.json").exists())
        statuses = [e["status"] for e in report["actionResults"]]
        self.assertTrue(all(s == "completed" for s in statuses), report["actionResults"])

    def test_the_full_journey_via_the_cli_subprocess_exits_zero(self):
        out_dir = self.root / "full-journey-cli-out-dir"
        doc = self._doc(out_dir)
        scenario_path = self.root / "full-journey-scenario.json"
        scenario_path.write_text(json.dumps(doc))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        data = envelope["data"]
        self.assertTrue(data["ok"], data.get("refusal"))
        self.assertIn("package", data)
        self.assertTrue((out_dir / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
