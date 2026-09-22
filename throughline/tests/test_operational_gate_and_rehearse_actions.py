"""Regression tests for the `run_gate` and `rehearse` action-list verbs
(`engine/scenario._ACTION_ALIASES`): two "operational" action verbs
(named after their CLI counterparts, `gate run <name>` and `rehearse
run`) that execute through the Engine's existing gate/rehearsal logic
rather than only declaring data.

Compatibility gap this closes: `run_gate`/`rehearse` were previously
rejected as unknown actions (`VALIDATION_ERROR`, exit 1) -- a staged
scenario using either verb never got past normalization.

Contract:
- `rehearse` is a pure, exact synonym for the pre-existing
  `set_rehearsal_timing` verb -- both target the identical
  `rehearsalTimings` mapping field (`{"slideRole": <seconds>}`) and drive
  the identical, already-existing `rehearsal.run_rehearsal` call in
  `_run_steps`. Malformed payloads (missing `slideRole`/`seconds`,
  unexpected extra fields, a repeated `slideRole`) are rejected exactly
  as `set_rehearsal_timing`'s own existing validation already does.
- `run_gate` explicitly, additionally invokes one named gate (`scope`,
  `evidence`, `narrative`, `claims`, `readiness`, or `stage`) through the
  existing `gates.run_gate` logic, recording a `{"action": "gate.run",
  "gate": <name>, "passed": <bool>}` step in the report. It is purely
  additive: the mandatory automatic gate pipeline (`preStageGates`,
  `stageGate`) still always runs in its existing fixed order regardless
  of whether any `run_gate` entries were given -- gate order is never
  reordered or skipped. Its inline payload must be exactly one non-empty
  `"gate"` field; a missing/blank/non-string `"gate"`, an unexpected
  extra field, or an unrecognized gate name is a clean `VALIDATION_ERROR`
  (the last delegated to the identical check `gates.run_gate` already
  raises for a direct `gate run <name>` CLI call), never a crash or a
  silent no-op.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, cleanup, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _as_field_list(doc: dict) -> list[dict]:
    return [{k: v} for k, v in doc.items()]


class RehearseActionAliasTests(unittest.TestCase):
    """`rehearse` is an exact synonym for `set_rehearsal_timing`."""

    def test_rehearse_is_a_known_action(self):
        self.assertIn("rehearse", scenario._ACTION_ALIASES)

    def test_rehearse_and_set_rehearsal_timing_target_the_identical_field(self):
        self.assertEqual(scenario._ACTION_ALIASES["rehearse"], scenario._ACTION_ALIASES["set_rehearsal_timing"])
        self.assertEqual(scenario._ACTION_ALIASES["rehearse"], "rehearsalTimings")

    def test_rehearse_normalizes_identically_to_set_rehearsal_timing(self):
        rehearse_doc = [{"action": "rehearse", "slideRole": "HOOK", "seconds": 58}]
        legacy_doc = [{"action": "set_rehearsal_timing", "slideRole": "HOOK", "seconds": 58}]
        self.assertEqual(scenario._normalize_scenario_doc(rehearse_doc), scenario._normalize_scenario_doc(legacy_doc))

    def test_rehearse_rejects_a_missing_seconds_field_exactly_like_set_rehearsal_timing(self):
        from helpers import EngineError
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "slideRole": "HOOK"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_rehearse_rejects_a_repeated_slide_role(self):
        from helpers import EngineError
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "rehearse", "slideRole": "HOOK", "seconds": 58},
                {"action": "rehearse", "slideRole": "HOOK", "seconds": 60},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class RehearseEndToEndTests(unittest.TestCase):
    """End-to-end coverage through `run_scenario`: `rehearse` steps drive
    the real `rehearsal.run_rehearsal` call, reaching Stage exactly like
    the pre-existing `rehearsalTimings` object-form field already does."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_rehearse_actions_replacing_rehearsaltimings_still_reach_stage(self):
        base = json.loads(FIXTURE.read_text())
        timings = base.pop("rehearsalTimings")
        doc = _as_field_list(base)
        for role, seconds in timings.items():
            doc.append({"action": "rehearse", "slideRole": role, "seconds": seconds})

        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("rehearsal", report)
        self.assertEqual(len(report["rehearsal"]["perSlide"]), len(timings))
        self.assertIn("package", report)

    def test_rehearse_and_set_rehearsal_timing_produce_the_identical_rehearsal_report(self):
        base = json.loads(FIXTURE.read_text())
        timings = base.pop("rehearsalTimings")

        rehearse_doc = _as_field_list(base) + [
            {"action": "rehearse", "slideRole": role, "seconds": seconds} for role, seconds in timings.items()
        ]
        legacy_doc = _as_field_list(base) + [
            {"action": "set_rehearsal_timing", "slideRole": role, "seconds": seconds} for role, seconds in timings.items()
        ]

        rehearse_report = scenario.run_scenario(persistence.Store(root=self.root / "rehearse-root"), rehearse_doc, self.root / "rehearse-report")
        legacy_report = scenario.run_scenario(persistence.Store(root=self.root / "legacy-root"), legacy_doc, self.root / "legacy-report")

        self.assertEqual(rehearse_report["rehearsal"]["totalActualSeconds"], legacy_report["rehearsal"]["totalActualSeconds"])
        self.assertEqual(rehearse_report["rehearsal"]["totalBudgetSeconds"], legacy_report["rehearsal"]["totalBudgetSeconds"])

    def test_rehearse_via_the_cli_subprocess_entry_point_exits_zero(self):
        base = json.loads(FIXTURE.read_text())
        timings = base.pop("rehearsalTimings")
        doc = _as_field_list(base) + [{"action": "rehearse", "slideRole": role, "seconds": seconds} for role, seconds in timings.items()]
        scenario_path = self.root / "rehearse-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["stageGate"]["passed"])


class RunGateActionTests(unittest.TestCase):
    """`run_gate` explicitly, additionally invokes one named gate through
    the existing `gates.run_gate` logic."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_run_gate_is_a_known_action(self):
        self.assertIn("run_gate", scenario._ACTION_ALIASES)

    def test_an_explicit_narrative_gate_run_is_recorded_and_the_mandatory_pipeline_still_runs(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "gate": "narrative"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        gate_steps = [s for s in report["steps"] if s["action"] == "gate.run"]
        self.assertEqual(gate_steps, [{"action": "gate.run", "gate": "narrative", "passed": True}])
        # The mandatory automatic pipeline (scope/evidence/narrative/
        # claims/readiness, then stage) is completely unaffected.
        self.assertEqual(set(report["preStageGates"]), {"scope", "evidence", "narrative", "claims", "readiness"})
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)

    def test_an_explicit_stage_gate_run_via_run_gate_also_works(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "gate": "stage"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        gate_steps = [s for s in report["steps"] if s["action"] == "gate.run"]
        self.assertEqual(gate_steps, [{"action": "gate.run", "gate": "stage", "passed": True}])
        self.assertTrue(report["stageGate"]["passed"])

    def test_multiple_run_gate_entries_are_all_recorded_in_order(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "gate": "scope"})
        doc.append({"action": "run_gate", "gate": "evidence"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        gate_steps = [s for s in report["steps"] if s["action"] == "gate.run"]
        self.assertEqual([s["gate"] for s in gate_steps], ["scope", "evidence"])

    def test_a_missing_gate_field_is_a_clean_validation_error(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "value": "narrative"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_an_unexpected_extra_field_is_a_clean_validation_error(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "gate": "narrative", "extra": "nope"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("extra", report["refusal"]["details"]["unexpectedFields"])

    def test_an_unrecognized_gate_name_is_a_clean_validation_error_not_a_crash(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "gate": "not_a_real_gate"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_run_gate_correctly_reports_a_failing_gate_not_a_crash(self):
        """`run_gate` reports the gate's genuine outcome -- never a
        hardcoded/fabricated `True` -- and a non-passing result is a
        completely normal, non-crashing outcome, exactly like every other
        gate invocation."""
        doc = json.loads(FIXTURE.read_text())
        doc["claims"][1]["approve"] = False  # leave the interpretive claim unapproved
        doc = _as_field_list(doc)
        doc.append({"action": "run_gate", "gate": "claims"})

        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        gate_steps = [s for s in report["steps"] if s["action"] == "gate.run"]
        # An unapproved (but slide-referenced) claim has no named human
        # approver of record -- the CLAIMS gate correctly reports failing,
        # not a hardcoded/fabricated `True` -- proving `run_gate` reports
        # the gate's *real* outcome, and that a non-passing result is a
        # completely normal, non-crashing outcome.
        self.assertEqual(gate_steps, [{"action": "gate.run", "gate": "claims", "passed": False}])
        self.assertFalse(report["stageGate"]["passed"])

    def test_run_gate_via_the_cli_subprocess_entry_point_exits_zero(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "gate": "readiness"})
        scenario_path = self.root / "run-gate-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        gate_steps = [s for s in envelope["data"]["steps"] if s["action"] == "gate.run"]
        self.assertEqual(gate_steps, [{"action": "gate.run", "gate": "readiness", "passed": True}])


if __name__ == "__main__":
    unittest.main()
