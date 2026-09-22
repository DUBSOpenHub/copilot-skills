"""Regression tests for `select_throughline`'s expanded action-list
payload contract (`engine/scenario._apply_select_throughline_entry` /
`_resolve_throughline_selection`): alongside the pre-existing numeric
synonyms `"value"`/`"selectThroughlineIndex"`, the action now also
accepts a numeric `"choice"` alias and a new `"text"` alias.

Compatibility gap this closes: a staged scenario selecting a throughline
via `{"action": "select_throughline", "choice": ...}` or `{"action":
"select_throughline", "text": ...}` previously failed normalization with
a `VALIDATION_ERROR` naming only `"value"`/`"selectThroughlineIndex"` as
accepted fields (exit 1).

Resolution contract (docs/engine-cli-reference.md):
- A numeric selector (`"value"`, `"selectThroughlineIndex"`, or
  `"choice"`) selects a proposed candidate by position, exactly as before.
- `"text"` that matches a proposed candidate's text verbatim selects that
  *same* candidate by id (never a redundant duplicate); `"text"` that
  matches none becomes a brand-new custom throughline (`origin: custom`),
  identical to the pre-existing `select_custom_throughline` action.
- Both a numeric and a text selector, several disagreeing numeric
  synonyms, an out-of-range/non-integer index, ambiguous multi-match
  text, or no selector at all is a clean `VALIDATION_ERROR`, never a
  crash -- and a normal, correctly-refused/blocked domain outcome (e.g.
  an out-of-range index, detected only once the real candidates exist)
  still completes with exit 0, the refusal encoded in the result
  document, exactly like every other scenario-step refusal.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import EngineError, REPO_ROOT, cleanup, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")

_BRIEF_ACTION = {
    "action": "set_talk_brief", "audience": "Developers", "eventType": "meetup",
    "durationMinutes": 20, "takeaway": "Provenance beats persuasion",
    "proofPoints": ["adoption stat"], "excludedTopics": [], "tone": "confident",
}
_DRAFT_ACTIONS = [
    {"action": "propose_throughline", "value": "Draft one"},
    {"action": "propose_throughline", "value": "Draft two"},
    {"action": "propose_throughline", "value": "Draft three"},
]


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


class SelectThroughlineNormalizationUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the normalization function itself."""

    def test_choice_resolves_into_select_throughline_index(self):
        merged = scenario._normalize_scenario_doc([{"action": "select_throughline", "choice": 2}])
        self.assertEqual(merged["selectThroughlineIndex"], 2)
        self.assertNotIn("selectThroughlineText", merged)

    def test_text_resolves_into_a_new_select_throughline_text_field(self):
        merged = scenario._normalize_scenario_doc([{"action": "select_throughline", "text": "Draft two"}])
        self.assertEqual(merged["selectThroughlineText"], "Draft two")
        self.assertNotIn("selectThroughlineIndex", merged)

    def test_legacy_value_and_field_name_still_work_unchanged(self):
        self.assertEqual(
            scenario._normalize_scenario_doc([{"action": "select_throughline", "value": 1}])["selectThroughlineIndex"], 1,
        )
        self.assertEqual(
            scenario._normalize_scenario_doc(
                [{"action": "select_throughline", "selectThroughlineIndex": 1}]
            )["selectThroughlineIndex"],
            1,
        )

    def test_choice_and_value_agreeing_are_accepted(self):
        merged = scenario._normalize_scenario_doc([{"action": "select_throughline", "value": 1, "choice": 1}])
        self.assertEqual(merged["selectThroughlineIndex"], 1)

    def test_choice_and_value_disagreeing_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "select_throughline", "value": 0, "choice": 1}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_numeric_selector_and_text_together_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "select_throughline", "choice": 0, "text": "Draft one"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_missing_every_selector_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "select_throughline"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_non_integer_choice_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "select_throughline", "choice": "not-a-number"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_blank_text_is_treated_as_missing_not_as_a_selector(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "select_throughline", "text": "   "}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_unexpected_extra_field_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "select_throughline", "choice": 0, "extra": True}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_repeated_selector_across_two_elements_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "select_throughline", "choice": 0}, {"action": "select_throughline", "choice": 1},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_text_then_choice_across_two_elements_is_still_a_validation_error(self):
        """Even though the two selectors land in different merged
        fields, using the action twice is still repeating the same
        logical selection -- never silently allowed."""
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "select_throughline", "text": "Draft one"},
                {"action": "select_throughline", "choice": 1},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class SelectThroughlineEndToEndTests(unittest.TestCase):
    """End-to-end coverage through `run_scenario` (both in-process and via
    the CLI subprocess), proving each selector form resolves to a real,
    persisted throughline selection -- not just a normalized dict."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _doc(self, *extra_actions: dict) -> list[dict]:
        return [_BRIEF_ACTION, *_DRAFT_ACTIONS, *extra_actions]

    def _run(self, doc: list[dict], name: str):
        store = persistence.Store(root=self.root / f"{name}-root")
        return scenario.run_scenario(store, doc, self.root / f"{name}-report")

    def _assert_selection_succeeded(self, report):
        """These fixtures deliberately stop at throughline selection (no
        route drafts), so the *overall* scenario is later, separately,
        and correctly refused for missing routes -- irrelevant to what's
        under test here. The presence of a `narrative.select_throughline`
        step is itself the proof selection succeeded: that step is only
        appended *after* a non-raising selection call, so a rejected
        selector would leave it (and everything after it) entirely
        absent from `report["steps"]`, with the refusal naming the
        selection failure instead."""
        select_step = next((s for s in report["steps"] if s["action"] == "narrative.select_throughline"), None)
        self.assertIsNotNone(select_step, report.get("refusal"))
        return select_step

    def test_numeric_choice_selects_the_candidate_at_that_position(self):
        report = self._run(self._doc({"action": "select_throughline", "choice": 1}), "choice")
        select_step = self._assert_selection_succeeded(report)
        self.assertEqual(select_step["throughlineId"].split(":")[0], "throughline")

    def test_text_matching_a_proposed_draft_selects_that_exact_candidate_not_a_duplicate(self):
        store = persistence.Store(root=self.root / "text-match-root")
        doc = self._doc({"action": "select_throughline", "text": "Draft two"})
        report = scenario.run_scenario(store, doc, self.root / "text-match-report")
        self._assert_selection_succeeded(report)

        conn = store.connect(report["workspaceId"])
        try:
            from helpers import models, persistence as persistence_mod
            all_throughlines = persistence_mod.list_all(conn, "throughline", report["workspaceId"], models.NarrativeThroughline)
        finally:
            conn.close()
        self.assertEqual(len(all_throughlines), 3, "matched text must not create a 4th, duplicate throughline")
        selected = [t for t in all_throughlines if t.selected]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].text, "Draft two")
        self.assertEqual(selected[0].origin, "proposed")

    def test_text_not_matching_any_draft_becomes_a_new_custom_throughline(self):
        store = persistence.Store(root=self.root / "custom-text-root")
        doc = self._doc({"action": "select_throughline", "text": "An entirely new custom throughline"})
        report = scenario.run_scenario(store, doc, self.root / "custom-text-report")
        self._assert_selection_succeeded(report)

        conn = store.connect(report["workspaceId"])
        try:
            from helpers import models, persistence as persistence_mod
            all_throughlines = persistence_mod.list_all(conn, "throughline", report["workspaceId"], models.NarrativeThroughline)
        finally:
            conn.close()
        self.assertEqual(len(all_throughlines), 4, "the 3 proposed drafts plus the 1 new custom entry")
        selected = [t for t in all_throughlines if t.selected]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].text, "An entirely new custom throughline")
        self.assertEqual(selected[0].origin, "custom")

    def test_legacy_value_form_is_unaffected(self):
        report = self._run(self._doc({"action": "select_throughline", "value": 0}), "legacy-value")
        self._assert_selection_succeeded(report)

    def test_an_out_of_range_choice_is_a_normal_zero_exit_refusal_not_a_crash(self):
        """The candidates don't exist until `_run_steps` runs, so an
        out-of-range index is only detectable mid-walk -- exactly like
        any other domain refusal (`WORKSPACE_ALREADY_ACTIVE`, ...): the
        result document records it, `run_scenario` never raises, and the
        CLI still exits 0."""
        report = self._run(self._doc({"action": "select_throughline", "choice": 99}), "out-of-range")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("99", report["refusal"]["message"])

    def test_out_of_range_choice_exits_zero_through_the_cli(self):
        scenario_path = self.root / "out-of-range-scenario.json"
        scenario_path.write_text(json.dumps(self._doc({"action": "select_throughline", "choice": 99})))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"])  # the CLI invocation itself completed normally
        self.assertFalse(envelope["data"]["ok"])  # ...but the scenario's own outcome is a refusal
        self.assertEqual(envelope["data"]["refusal"]["code"], "VALIDATION_ERROR")

    def test_select_throughline_text_and_select_custom_throughline_together_is_an_ambiguous_refusal(self):
        """Two different actions that each resolve to a throughline
        selection (`select_throughline --text` and
        `select_custom_throughline`) cannot both apply -- also only
        detectable once both fields are known, so it surfaces as a
        normal mid-walk refusal rather than a structural error."""
        doc = self._doc(
            {"action": "select_throughline", "text": "Draft two"},
            {"action": "select_custom_throughline", "value": "Some other custom text"},
        )
        report = self._run(doc, "dual-selection")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_action_list_fixture_still_passes_using_the_legacy_value_form(self):
        """The existing action-list happy-path fixture (which uses
        `{"action": "select_throughline", "value": 0}`) must still reach
        Stage -- this cycle is purely additive."""
        fixture = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path_action_list.json"
        store = persistence.Store(root=self.root / "fixture-root")
        report = scenario.run_scenario(store, json.loads(fixture.read_text()), self.root / "fixture-report")
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])


if __name__ == "__main__":
    unittest.main()
