"""Regression tests for `rehearse`'s widened rehearsal-subfeature
vocabulary (`engine/scenario._apply_rehearse_entry` and its family
handlers: `_apply_rehearsal_bulk_entry`, `_apply_rehearsal_total_entry`,
`_apply_rehearse_qa_entry`, `_apply_rehearse_cuts_entry`).

Compatibility gap this closes: the public action-list `rehearse` action
only ever accepted the single, narrow `set_rehearsal_timing`-identical
shape (one `slideRole`/`slideId`/`slideOrder` paired with one
`seconds`/`duration`/`durationSeconds`/`actualSeconds`) -- every other
staged payload shape (a bulk `timings`/`slideTimings`/`rehearsal`/`run`/
`value` wrapper, an aggregate `totalSeconds`/`totalMinutes`-style total
duration, a Q&A pair, a shorter-variant/cuts request, or a bare
source-change re-check) was rejected `VALIDATION_ERROR`, exit 1, aborting
setup before any assertion ran.

Contract (see `engine/scenario.py`'s module comment above
`_apply_rehearse_entry` for the authoritative per-shape rules):
- A bulk wrapper (`timings`/`slideTimings`/`rehearsal`/`run`/`value`)
  holding either a `{slideRef: seconds}` mapping or a list of
  single-entry-shaped objects contributes every entry into the identical
  `rehearsalTimings` dict the narrow shape already produces.
- An aggregate `total*`/`actual*` duration (a `Seconds` or `Minutes`
  suffix) is allocated proportionally to each slide's own configured
  time budget and fed into the identical per-slide `run_rehearsal`
  contract.
- A `question`(+`answer`/`claimIndices`) pair, or a `qaPairs` wrapper
  list, is contributed into the identical `qaPairs` list `record_qa`
  already targets.
- A `targetSeconds`/`targetMinutes` cuts request feeds
  `compiler.propose_cuts`'s existing `target_seconds` contract.
- A bare (fieldless) `rehearse` action, or one with only
  `reportSourceChanges`/`checkSourceChanges`, still triggers a
  `rehearsal.run_rehearsal` pass (timing not required) purely so
  FR-M365-4 `sourceChanges` detection still reports.
- Every duration value (per-slide, bulk, aggregate, or a cuts target)
  rejects a negative, non-finite, or non-numeric value explicitly.
- Mixing fields from two different sub-feature shapes on the same
  element, or combining an aggregate total with a per-slide timing
  anywhere else in the same document, is a clean `VALIDATION_ERROR`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import EngineError, REPO_ROOT, cleanup, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _as_field_list(doc: dict) -> list[dict]:
    return [{k: v} for k, v in doc.items()]


class RehearseBulkWrapperNormalizationUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the bulk-wrapper family."""

    def test_each_wrapper_key_accepts_a_slide_ref_to_seconds_mapping(self):
        for wrapper_key in ("timings", "slideTimings", "rehearsal", "run", "value"):
            with self.subTest(wrapper_key=wrapper_key):
                doc = [{"action": "rehearse", wrapper_key: {"HOOK": 58, "ASK": 55}}]
                merged = scenario._normalize_scenario_doc(doc)
                self.assertEqual(merged["rehearsalTimings"], {"HOOK": 58, "ASK": 55})

    def test_a_bulk_wrapper_accepts_a_list_of_single_entry_objects(self):
        doc = [{"action": "rehearse", "timings": [
            {"slideRole": "HOOK", "seconds": 58}, {"slideId": "slide:x", "actualSeconds": 30},
        ]}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["rehearsalTimings"], {"HOOK": 58, "slide:x": 30})

    def test_a_bulk_wrapper_composes_with_a_later_single_entry_action(self):
        doc = [
            {"action": "rehearse", "run": {"HOOK": 58}},
            {"action": "rehearse", "slideRole": "ASK", "seconds": 55},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["rehearsalTimings"], {"HOOK": 58, "ASK": 55})

    def test_two_different_wrapper_keys_at_once_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "timings": {"HOOK": 1}, "run": {"ASK": 2}}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_wrapper_with_a_sibling_field_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "timings": {"HOOK": 1}, "slideRole": "ASK"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_empty_wrapper_mapping_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "timings": {}}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_repeated_key_across_bulk_and_single_entries_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "rehearse", "run": {"HOOK": 58}},
                {"action": "rehearse", "slideRole": "HOOK", "seconds": 60},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_non_mapping_non_list_wrapper_value_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "timings": "not-a-mapping-or-list"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class RehearseAggregateTotalDurationUnitTests(unittest.TestCase):
    """Direct coverage of the aggregate whole-rehearsal duration family."""

    def test_total_actual_seconds_is_accepted(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "totalActualSeconds": 600}])
        self.assertEqual(merged["rehearsalTotalActualSeconds"], 600.0)

    def test_a_minutes_suffixed_alias_is_converted_to_seconds(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "totalActualMinutes": 10}])
        self.assertEqual(merged["rehearsalTotalActualSeconds"], 600.0)

    def test_total_seconds_and_actual_duration_seconds_are_synonyms(self):
        for field_name in ("totalSeconds", "totalActualSeconds", "actualDurationSeconds"):
            with self.subTest(field_name=field_name):
                merged = scenario._normalize_scenario_doc([{"action": "rehearse", field_name: 300}])
                self.assertEqual(merged["rehearsalTotalActualSeconds"], 300.0)

    def test_repeating_the_aggregate_total_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "rehearse", "totalSeconds": 300},
                {"action": "rehearse", "totalMinutes": 6},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_combining_an_aggregate_total_with_a_per_slide_timing_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "rehearse", "totalSeconds": 300},
                {"action": "rehearse", "slideRole": "HOOK", "seconds": 58},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_combining_a_per_slide_timing_first_then_an_aggregate_total_is_also_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "rehearse", "slideRole": "HOOK", "seconds": 58},
                {"action": "rehearse", "totalSeconds": 300},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_distribute_total_duration_allocates_proportionally_to_time_budget(self):
        from helpers import models, rehearsal as rehearsal_mod

        def _slide(id_, budget):
            return models.SlideSpec(
                id=id_, workspace_id="ws:x", deck_id="deck:x", beat_id=f"beat:{id_}", order=0, role="HOOK",
                layout="standard",
                regions={"notes.timeBudget": models.Region(role="notes.timeBudget", text=str(budget))},
            )

        slides = [_slide("s1", 60), _slide("s2", 180)]
        result = rehearsal_mod.distribute_total_duration(slides, 240)
        self.assertAlmostEqual(result["s1"], 60.0)
        self.assertAlmostEqual(result["s2"], 180.0)

    def test_distribute_total_duration_splits_evenly_when_no_budgets_exist(self):
        from helpers import models, rehearsal as rehearsal_mod

        def _slide(id_):
            return models.SlideSpec(id=id_, workspace_id="ws:x", deck_id="deck:x", beat_id=f"beat:{id_}", order=0, role="HOOK", layout="standard")

        slides = [_slide("s1"), _slide("s2")]
        result = rehearsal_mod.distribute_total_duration(slides, 100)
        self.assertAlmostEqual(result["s1"], 50.0)
        self.assertAlmostEqual(result["s2"], 50.0)


class RehearseQAViaRehearseActionUnitTests(unittest.TestCase):
    """Direct coverage of the Q&A family reached through `rehearse`
    itself (not just the dedicated `record_qa` verb)."""

    def test_a_bare_question_field_contributes_to_qa_pairs(self):
        doc = [{"action": "rehearse", "question": "What about X?", "answer": "Y.", "claimIndices": [0]}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["qaPairs"], [{"question": "What about X?", "answer": "Y.", "claimIndices": [0]}])

    def test_a_qa_pairs_wrapper_contributes_every_item(self):
        doc = [{"action": "rehearse", "qaPairs": [
            {"question": "Q1?", "answer": "A1."}, {"question": "Q2?"},
        ]}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(len(merged["qaPairs"]), 2)

    def test_rehearse_qa_composes_with_the_dedicated_record_qa_action(self):
        doc = [
            {"action": "record_qa", "question": "Q1?", "answer": "A1."},
            {"action": "rehearse", "question": "Q2?", "answer": "A2."},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual([qa["question"] for qa in merged["qaPairs"]], ["Q1?", "Q2?"])

    def test_an_empty_question_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "question": "   "}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_unexpected_field_alongside_question_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "question": "Q?", "notes": "extra"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class RehearseCutsRequestUnitTests(unittest.TestCase):
    """Direct coverage of the shorter-variant/cuts family (FR-DEL-3)."""

    def test_target_seconds_is_accepted(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "targetSeconds": 480}])
        self.assertEqual(merged["rehearsalCutsTargetSeconds"], 480.0)

    def test_target_minutes_is_converted_to_seconds(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "targetMinutes": 8}])
        self.assertEqual(merged["rehearsalCutsTargetSeconds"], 480.0)

    def test_a_redundant_truthy_marker_is_accepted_alongside_the_target(self):
        merged = scenario._normalize_scenario_doc([
            {"action": "rehearse", "targetSeconds": 480, "shorterVariant": True},
        ])
        self.assertEqual(merged["rehearsalCutsTargetSeconds"], 480.0)

    def test_a_falsy_marker_alongside_the_target_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "targetSeconds": 480, "requestCuts": False}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_zero_target_is_rejected_as_impossible(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "targetSeconds": 0}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_negative_target_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "targetSeconds": -10}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_repeating_the_cuts_target_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "rehearse", "targetSeconds": 480},
                {"action": "rehearse", "targetMinutes": 9},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class RehearseBareSourceCheckUnitTests(unittest.TestCase):
    """Direct coverage of the bare re-check family (FR-M365-4): no timing
    is required at all -- "do not require timing when the action only
    requests a supported rehearsal subfeature."""

    def test_a_completely_empty_rehearse_action_requests_a_run(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse"}])
        self.assertTrue(merged["rehearsalRunRequested"])
        self.assertNotIn("rehearsalTimings", merged)

    def test_report_source_changes_marker_requests_a_run(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "reportSourceChanges": True}])
        self.assertTrue(merged["rehearsalRunRequested"])

    def test_check_source_changes_marker_requests_a_run(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "checkSourceChanges": True}])
        self.assertTrue(merged["rehearsalRunRequested"])

    def test_a_falsy_marker_alone_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "reportSourceChanges": False}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class RehearseImpossibleValueUnitTests(unittest.TestCase):
    """Negative/impossible/non-numeric duration values are rejected
    explicitly across every duration-bearing shape."""

    def test_a_negative_per_slide_seconds_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "slideRole": "HOOK", "seconds": -1}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_non_numeric_seconds_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "slideRole": "HOOK", "seconds": "fifty-eight"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_boolean_seconds_is_rejected_rather_than_silently_coerced(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "slideRole": "HOOK", "seconds": True}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_infinite_total_duration_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "totalSeconds": float("inf")}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_nan_bulk_timing_value_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "run": {"HOOK": float("nan")}}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_negative_aggregate_total_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "totalSeconds": -5}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_zero_seconds_is_still_allowed_for_a_per_slide_timing(self):
        """Unlike a cuts target, a zero-second per-slide timing is a
        plausible (if unusual) recorded value -- never rejected."""
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "slideRole": "HOOK", "seconds": 0}])
        self.assertEqual(merged["rehearsalTimings"], {"HOOK": 0})


class RehearseFamilyMixingUnitTests(unittest.TestCase):
    """Mixing fields from two different sub-feature shapes on the same
    element, or an unrecognized field set, is always a clean
    `VALIDATION_ERROR`."""

    def test_mixing_a_per_slide_timing_with_a_question_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "rehearse", "slideRole": "HOOK", "seconds": 58, "question": "Q?"},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_mixing_a_cuts_target_with_a_bulk_wrapper_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "targetSeconds": 300, "run": {"HOOK": 1}}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_unrecognized_field_set_is_rejected(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "mystery": True}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class RehearseSubfeatureEndToEndTests(unittest.TestCase):
    """End-to-end coverage through `run_scenario`: every sub-feature
    shape drives the real domain calls and reaches Stage exactly like the
    pre-existing narrow shape already does."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _base_doc_without_rehearsal(self) -> list[dict]:
        base = json.loads(FIXTURE.read_text())
        base.pop("rehearsalTimings")
        base.pop("qaPairs")
        return _as_field_list(base)

    def test_a_bulk_run_wrapper_reaches_stage_and_package(self):
        base = json.loads(FIXTURE.read_text())
        timings = base.pop("rehearsalTimings")
        base.pop("qaPairs")
        doc = _as_field_list(base) + [{"action": "rehearse", "run": timings}]

        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)
        self.assertEqual(report["rehearsal"]["totalActualSeconds"], sum(timings.values()))

    def test_an_aggregate_total_duration_reaches_stage_with_a_full_perslide_breakdown(self):
        doc = self._base_doc_without_rehearsal() + [{"action": "rehearse", "totalActualSeconds": 700}]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["rehearsal"]["totalActualSeconds"], 700.0)
        self.assertEqual(len(report["rehearsal"]["perSlide"]), 7)

    def test_a_qa_pair_via_rehearse_is_recorded_and_grounded(self):
        base = json.loads(FIXTURE.read_text())
        base.pop("qaPairs")
        doc = _as_field_list(base) + [
            {"action": "rehearse", "question": "Is the stat seasonal?", "answer": "No, it is QoQ.", "claimIndices": [0]},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["qa"]), 1)
        self.assertTrue(report["qa"][0]["grounding"]["allGrounded"])

    def test_a_cuts_request_via_rehearse_proposes_cuts_and_never_cuts_hook_or_ask(self):
        doc = self._base_doc_without_rehearsal() + [{"action": "rehearse", "targetMinutes": 5}]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertIn("proposedCuts", report["rehearsal"])
        self.assertEqual(report["rehearsal"]["cutsTargetSeconds"], 300)
        self.assertGreater(len(report["rehearsal"]["proposedCuts"]), 0)
        cut_beat_ids = set(report["rehearsal"]["proposedCuts"])
        active_route = next(r for r in report["routes"] if r["id"] == report["route"]["active"]["id"])
        protected_ids = {b["id"] for b in active_route["beats"] if b["role"] in ("HOOK", "ASK")}
        self.assertTrue(protected_ids, "expected at least one HOOK/ASK beat in the active route")
        self.assertFalse(cut_beat_ids & protected_ids)

    def test_a_bare_rehearse_action_reports_source_changes_without_any_timing(self):
        doc = self._base_doc_without_rehearsal() + [{"action": "rehearse"}]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertIn("rehearsal", report)
        self.assertEqual(report["rehearsal"]["sourceChanges"], [])
        self.assertEqual(report["rehearsal"]["perSlide"], [])

    def test_an_impossible_value_through_the_full_cli_path_exits_one(self):
        """Widening the accepted shapes never weakens validation -- a
        malformed rehearsal document is still a clean `VALIDATION_ERROR`
        detected at scenario-document-normalization time (exit 1),
        exactly like the pre-existing narrow-shape ambiguity checks."""
        doc = self._base_doc_without_rehearsal() + [{"action": "rehearse", "totalSeconds": -5}]
        scenario_path = self.root / "impossible-total-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 1)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
