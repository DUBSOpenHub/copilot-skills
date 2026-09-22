"""Regression tests for the remaining snake_case/camelCase field-name
compatibility gaps in the `rehearse`, `export`, `run_gate`, and
`approve_stage` action-list verbs (Dark Factory hardening cycle 7,
`engine/scenario.py`).

Compatibility gap this closes: `rehearse`'s cuts sub-shape rejected a
snake_case `target_minutes` payload with `VALIDATION_ERROR` while the
camelCase `targetMinutes` was accepted (the one explicitly-known
adapter mismatch going into this cycle); several other actions
(`rehearse`'s per-slide timing shape, `export`, `run_gate`,
`approve_stage`) had the identical camelCase-only gap for their own
field names (`slide_id`/`slide_order`, `actual_seconds`/
`actual_minutes`, `output_dir`/`export_dir`/`render_mode`, `gate_name`,
`approver_name`).
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


class RehearseCutsTargetMinutesRegressionTests(unittest.TestCase):
    """The one explicitly-known adapter mismatch going into this
    hardening cycle: `rehearse` with snake_case `target_minutes`."""

    def test_target_minutes_snake_case_is_accepted(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "target_minutes": 10}])
        self.assertEqual(merged["rehearsalCutsTargetSeconds"], 600.0)

    def test_target_minutes_snake_case_matches_camel_case(self):
        snake = scenario._normalize_scenario_doc([{"action": "rehearse", "target_minutes": 9}])
        camel = scenario._normalize_scenario_doc([{"action": "rehearse", "targetMinutes": 9}])
        self.assertEqual(snake["rehearsalCutsTargetSeconds"], camel["rehearsalCutsTargetSeconds"])

    def test_target_seconds_snake_case_is_accepted(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "target_seconds": 540}])
        self.assertEqual(merged["rehearsalCutsTargetSeconds"], 540.0)

    def test_target_minutes_snake_case_through_the_cli_exits_zero(self):
        base = json.loads(FIXTURE.read_text())
        doc = _as_field_list(base) + [{"action": "rehearse", "target_minutes": 9}]
        scenario_path_dir = new_root()
        try:
            scenario_path = scenario_path_dir / "target-minutes-scenario.json"
            scenario_path.write_text(json.dumps(doc))
            proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(scenario_path_dir / "ws"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            envelope = json.loads(proc.stdout)
            self.assertTrue(envelope["ok"], envelope.get("error"))
            self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))
            self.assertEqual(envelope["data"]["rehearsal"]["cutsTargetSeconds"], 540)
        finally:
            cleanup(scenario_path_dir)


class RehearseTimingSnakeCaseAliasTests(unittest.TestCase):
    """`slide_id`/`slide_order` (key aliases) and `actual_seconds`/
    `actual_minutes` (value aliases, the latter converted `* 60`)."""

    def test_slide_id_snake_case_is_accepted(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "slide_id": "slide:abc", "seconds": 42}])
        self.assertEqual(merged["rehearsalTimings"], {"slide:abc": 42})

    def test_slide_order_snake_case_is_accepted(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "slide_order": 2, "seconds": 30}])
        self.assertEqual(merged["rehearsalTimings"], {2: 30})

    def test_actual_seconds_snake_case_is_accepted(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "slideRole": "HOOK", "actual_seconds": 58}])
        self.assertEqual(merged["rehearsalTimings"], {"HOOK": 58})

    def test_actual_minutes_camel_case_converts_to_seconds(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "slideRole": "HOOK", "actualMinutes": 1}])
        self.assertEqual(merged["rehearsalTimings"], {"HOOK": 60.0})

    def test_actual_minutes_snake_case_converts_to_seconds(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "slideRole": "HOOK", "actual_minutes": 2}])
        self.assertEqual(merged["rehearsalTimings"], {"HOOK": 120.0})

    def test_snake_case_key_and_value_aliases_compose(self):
        merged = scenario._normalize_scenario_doc([{"action": "rehearse", "slide_id": "slide:x", "actual_minutes": 1}])
        self.assertEqual(merged["rehearsalTimings"], {"slide:x": 60.0})

    def test_two_snake_case_key_fields_at_once_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "rehearse", "slide_id": "slide:x", "slide_order": 0, "seconds": 30},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_reaches_stage_end_to_end_with_snake_case_timings(self):
        base = json.loads(FIXTURE.read_text())
        timings = base.pop("rehearsalTimings")
        doc = _as_field_list(base) + [
            {"action": "rehearse", "slideRole": role, "actual_seconds": seconds} for role, seconds in timings.items()
        ]
        root = new_root()
        try:
            store = persistence.Store(root=root / "ws")
            report = scenario.run_scenario(store, doc, root / "report")
            self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
            self.assertEqual(report["rehearsal"]["totalActualSeconds"], sum(timings.values()))
        finally:
            cleanup(root)


class ExportRequestSnakeCaseAliasTests(unittest.TestCase):
    """`output_dir`/`export_dir`/`render_mode` snake_case aliases for the
    `export` action-list verb."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _full_doc(self, extra_actions: list[dict]) -> list[dict]:
        base = json.loads(FIXTURE.read_text())
        return _as_field_list(base) + extra_actions

    def test_render_mode_snake_case_is_accepted(self):
        doc = self._full_doc([{"action": "export", "target": "pptx", "render_mode": "panic"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(report["exports"][0]["path"].endswith("panic-deck.pptx"))

    def test_output_dir_snake_case_is_accepted(self):
        custom_dir = self.root / "snake-case-export-dir"
        doc = self._full_doc([{"action": "export", "target": "package", "output_dir": str(custom_dir)}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["exportDir"], str(custom_dir))
        self.assertTrue((custom_dir / "manifest.json").exists())

    def test_export_dir_snake_case_is_accepted(self):
        custom_dir = self.root / "snake-case-export-dir-2"
        doc = self._full_doc([{"action": "export", "target": "package", "export_dir": str(custom_dir)}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["exportDir"], str(custom_dir))

    def test_approver_name_snake_case_on_an_export_request_is_accepted(self):
        doc = self._full_doc([{"action": "export", "target": "package", "approver_name": "Dr. Ada Lovelace"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))


class RunGateNameSnakeCaseAliasTests(unittest.TestCase):
    """`gate_name`/`gateName` aliases for the `run_gate` action-list
    verb's gate-name field (still requires exactly one name)."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_gate_name_snake_case_is_accepted(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "gate_name": "narrative"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        gate_steps = [s for s in report["steps"] if s["action"] == "gate.run"]
        self.assertEqual(gate_steps, [{"action": "gate.run", "gate": "narrative", "passed": True}])

    def test_gate_name_camel_case_is_accepted(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "gateName": "scope"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        gate_steps = [s for s in report["steps"] if s["action"] == "gate.run"]
        self.assertEqual(gate_steps, [{"action": "gate.run", "gate": "scope", "passed": True}])

    def test_conflicting_gate_name_aliases_is_a_validation_error(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "gate": "narrative", "gate_name": "scope"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_missing_gate_name_is_still_a_validation_error(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "value": "narrative"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")


class ApproveStageApproverNameAliasTests(unittest.TestCase):
    """`approverName`/`approver_name` aliases for `approve_stage`'s
    `stageApprover` scalar field."""

    def test_approver_name_snake_case_is_accepted(self):
        merged = scenario._normalize_scenario_doc([{"action": "approve_stage", "approver_name": "Jane Doe"}])
        self.assertEqual(merged["stageApprover"], "Jane Doe")

    def test_approver_name_camel_case_is_accepted(self):
        merged = scenario._normalize_scenario_doc([{"action": "approve_stage", "approverName": "Jane Doe"}])
        self.assertEqual(merged["stageApprover"], "Jane Doe")

    def test_value_still_works_unaffected(self):
        merged = scenario._normalize_scenario_doc([{"action": "approve_stage", "value": "Jane Doe"}])
        self.assertEqual(merged["stageApprover"], "Jane Doe")

    def test_conflicting_approver_name_and_value_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "approve_stage", "value": "Jane Doe", "approver_name": "Someone Else"},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_reaches_stage_end_to_end_with_the_snake_case_approver_alias(self):
        base = json.loads(FIXTURE.read_text())
        base.pop("stageApprover", None)
        doc = _as_field_list(base) + [{"action": "approve_stage", "approver_name": "Dr. Jamie Rivera"}]
        root = new_root()
        try:
            store = persistence.Store(root=root / "ws")
            report = scenario.run_scenario(store, doc, root / "report")
            self.assertTrue(report["ok"], report.get("refusal"))
            self.assertEqual(report["workspace"]["stageApprovedBy"], "Dr. Jamie Rivera")
        finally:
            cleanup(root)


if __name__ == "__main__":
    unittest.main()
