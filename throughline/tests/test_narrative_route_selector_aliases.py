"""Regression tests for the `select_narrative_route` action-list verb
(`engine/scenario._apply_select_narrative_route_entry` /
`_resolve_route_selection`): the public black-box vocabulary's name for
selecting among proposed narrative routes, accepted as a synonym for the
pre-existing `select_route` verb -- both still target the identical
`selectRouteIndex` object-form field for a numeric selector -- plus a new
`"text"` alias that matches a candidate route's own `label` verbatim.

Compatibility gap this closes: a staged scenario using
`select_narrative_route` (rather than `select_route`) previously failed
normalization with a `VALIDATION_ERROR` naming only `select_route` (and
every other existing verb) as recognized (exit 1); `select_narrative_route`
must now be accepted and continue the scenario exactly like `select_route`
would, in either its numeric or (new) text-based form.

Resolution contract (mirrors `select_throughline`'s own numeric/text
contract in `docs/engine-cli-reference.md`, with one deliberate
difference): a numeric selector (`"value"`, `"selectRouteIndex"`, or
`"choice"`) selects a candidate route by position, exactly as
`select_route` already does. `"text"` that matches a candidate route's
`label` verbatim selects that route by id. Unlike a throughline, a route
is a full beat spine, never freeform text -- there is no "custom route"
equivalent -- so `"text"` matching none (or more than one) of the
candidate routes' labels is a clean, correctly-refused `VALIDATION_ERROR`
(result document + exit 0), never a guessed/synthesized route. Both a
numeric and a text selector, disagreeing numeric synonyms, a non-integer/
out-of-range index, or no selector at all is likewise a clean
`VALIDATION_ERROR`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import EngineError, REPO_ROOT, cleanup, models, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _fixture_doc_without_route_index() -> dict:
    doc = json.loads(FIXTURE.read_text())
    doc.pop("selectRouteIndex")
    return doc


def _as_field_list(doc: dict) -> list[dict]:
    return [{k: v} for k, v in doc.items()]


class SelectNarrativeRouteNormalizationUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the normalization function itself."""

    def test_select_narrative_route_is_a_known_action(self):
        self.assertIn("select_narrative_route", scenario._ACTION_ALIASES)

    def test_select_narrative_route_and_select_route_target_the_identical_numeric_field(self):
        self.assertEqual(scenario._ACTION_ALIASES["select_narrative_route"], scenario._ACTION_ALIASES["select_route"])
        self.assertEqual(scenario._ACTION_ALIASES["select_route"], "selectRouteIndex")

    def test_choice_resolves_into_select_route_index(self):
        merged = scenario._normalize_scenario_doc([{"action": "select_narrative_route", "choice": 1}])
        self.assertEqual(merged["selectRouteIndex"], 1)
        self.assertNotIn("selectRouteText", merged)

    def test_text_resolves_into_a_new_select_route_text_field(self):
        merged = scenario._normalize_scenario_doc([{"action": "select_narrative_route", "text": "Primary route"}])
        self.assertEqual(merged["selectRouteText"], "Primary route")
        self.assertNotIn("selectRouteIndex", merged)

    def test_legacy_value_and_field_name_still_work(self):
        self.assertEqual(
            scenario._normalize_scenario_doc([{"action": "select_narrative_route", "value": 0}])["selectRouteIndex"], 0,
        )
        self.assertEqual(
            scenario._normalize_scenario_doc(
                [{"action": "select_narrative_route", "selectRouteIndex": 1}]
            )["selectRouteIndex"],
            1,
        )

    def test_select_route_and_select_narrative_route_normalize_identically(self):
        by_select_route = scenario._normalize_scenario_doc([{"action": "select_route", "value": 1}])
        by_narrative_route = scenario._normalize_scenario_doc([{"action": "select_narrative_route", "choice": 1}])
        self.assertEqual(by_select_route, by_narrative_route)

    def test_choice_and_value_disagreeing_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "select_narrative_route", "value": 0, "choice": 1}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_numeric_selector_and_text_together_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "select_narrative_route", "choice": 0, "text": "Primary route"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_missing_every_selector_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "select_narrative_route"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_non_integer_choice_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "select_narrative_route", "choice": "nope"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_unexpected_extra_field_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "select_narrative_route", "choice": 0, "extra": True}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_repeated_selection_across_select_route_and_select_narrative_route_is_a_validation_error(self):
        """Both verbs write into the same field(s) -- using either one
        twice (even mixed) is still repeating the same logical selection."""
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "select_route", "value": 0},
                {"action": "select_narrative_route", "choice": 1},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class SelectNarrativeRouteEndToEndTests(unittest.TestCase):
    """End-to-end coverage through `run_scenario`: each selector form
    resolves to a real, persisted route selection that lets the scenario
    continue (compile/gates/rehearsal/stage), not just a normalized dict."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_numeric_choice_selects_the_route_at_that_position_and_reaches_stage(self):
        doc = _as_field_list(_fixture_doc_without_route_index())
        doc.append({"action": "select_narrative_route", "choice": 0})
        store = persistence.Store(root=self.root / "numeric-root")
        report = scenario.run_scenario(store, doc, self.root / "numeric-report")

        select_step = next(s for s in report["steps"] if s["action"] == "narrative.select_route")
        self.assertEqual(select_step["routeId"].split(":")[0], "route")
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)

    def test_text_matching_a_proposed_routes_label_selects_that_exact_route(self):
        doc = _as_field_list(_fixture_doc_without_route_index())
        doc.append({"action": "select_narrative_route", "text": "Primary route"})
        store = persistence.Store(root=self.root / "text-root")
        report = scenario.run_scenario(store, doc, self.root / "text-report")

        select_step = next(s for s in report["steps"] if s["action"] == "narrative.select_route")
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])

        conn = store.connect(report["workspaceId"])
        try:
            selected_route = persistence.get(conn, "route", select_step["routeId"], models.NarrativeRoute)
        finally:
            conn.close()
        self.assertEqual(selected_route.label, "Primary route")
        self.assertTrue(selected_route.selected)

    def test_text_matching_the_alternate_routes_label_selects_that_route_not_the_default(self):
        """Proves text-based selection genuinely resolves by label, not
        merely falling back to index 0 -- the alternate (short, 2-beat)
        route correctly then fails the *narrative* gate on its own beat
        count, a distinct and expected refusal proving the *other* route
        was the one actually selected."""
        doc = _as_field_list(_fixture_doc_without_route_index())
        doc.append({"action": "select_narrative_route", "text": "Short route (unselected alternative)"})
        store = persistence.Store(root=self.root / "alt-text-root")
        report = scenario.run_scenario(store, doc, self.root / "alt-text-report")

        select_step = next(s for s in report["steps"] if s["action"] == "narrative.select_route")
        conn = store.connect(report["workspaceId"])
        try:
            selected_route = persistence.get(conn, "route", select_step["routeId"], models.NarrativeRoute)
        finally:
            conn.close()
        self.assertEqual(selected_route.label, "Short route (unselected alternative)")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "NARRATIVE_GATE_FAILED")

    def test_text_not_matching_any_route_label_is_a_clean_refusal_never_a_synthesized_route(self):
        doc = _as_field_list(_fixture_doc_without_route_index())
        doc.append({"action": "select_narrative_route", "text": "A route label nobody proposed"})
        store = persistence.Store(root=self.root / "unmatched-text-root")
        report = scenario.run_scenario(store, doc, self.root / "unmatched-text-report")

        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertFalse(any(s["action"] == "narrative.select_route" for s in report["steps"]))

    def test_out_of_range_choice_is_a_normal_zero_exit_refusal_not_a_crash(self):
        doc = _as_field_list(_fixture_doc_without_route_index())
        doc.append({"action": "select_narrative_route", "choice": 99})
        store = persistence.Store(root=self.root / "out-of-range-root")
        report = scenario.run_scenario(store, doc, self.root / "out-of-range-report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("99", report["refusal"]["message"])

    def test_out_of_range_choice_exits_zero_through_the_cli(self):
        doc = _as_field_list(_fixture_doc_without_route_index())
        doc.append({"action": "select_narrative_route", "choice": 99})
        scenario_path = self.root / "out-of-range-scenario.json"
        scenario_path.write_text(json.dumps(doc))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"])
        self.assertFalse(envelope["data"]["ok"])
        self.assertEqual(envelope["data"]["refusal"]["code"], "VALIDATION_ERROR")

    def test_select_route_and_select_narrative_route_produce_the_identical_outcome(self):
        legacy_doc = _as_field_list(_fixture_doc_without_route_index())
        legacy_doc.append({"action": "select_route", "value": 0})
        legacy_report = scenario.run_scenario(
            persistence.Store(root=self.root / "legacy-root"), legacy_doc, self.root / "legacy-report",
        )

        new_doc = _as_field_list(_fixture_doc_without_route_index())
        new_doc.append({"action": "select_narrative_route", "choice": 0})
        new_report = scenario.run_scenario(
            persistence.Store(root=self.root / "new-root"), new_doc, self.root / "new-report",
        )

        self.assertEqual(legacy_report["stageGate"]["passed"], new_report["stageGate"]["passed"])
        self.assertTrue(new_report["stageGate"]["passed"])

    def test_select_narrative_route_via_the_cli_subprocess_entry_point_reaches_stage(self):
        doc = _as_field_list(_fixture_doc_without_route_index())
        doc.append({"action": "select_narrative_route", "choice": 0})
        scenario_path = self.root / "select-narrative-route-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"])
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertIn("package", envelope["data"])


if __name__ == "__main__":
    unittest.main()
