"""Regression tests for the `compile_deck`/`compile_presentation`
action-list verbs (`engine/scenario._ACTION_ALIASES`): two public names
for the one deck-compilation step every scenario already runs
automatically and unconditionally once a route is selected
(`compiler.compile_deck` in `_run_steps`).

Compatibility gap this closes: an action-list scenario using either verb
was previously rejected with `VALIDATION_ERROR: unknown action`
(normalization happens up front, so nothing after it -- evidence, claims,
routes, compile, gates, rehearsal, package -- ever ran).

Contract:
- Both verbs are recognized and map to the same marker field
  (`compileRequested`); neither accepts any inline payload at all (there
  is nothing for either to configure -- compilation already runs
  unconditionally regardless of whether either verb is present).
- Their presence never re-triggers, gates, reorders, or substitutes for
  the mandatory automatic `compiler.compile_deck` call every scenario
  already makes -- purely additive/no-op besides accepting the verb.
- Do not accept arbitrary verbs: any other unknown action name is still a
  clean `VALIDATION_ERROR`, exactly as before.
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


class CompileActionVocabularyUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the normalization function itself."""

    def test_both_compile_verbs_are_known_actions(self):
        self.assertIn("compile_deck", scenario._ACTION_ALIASES)
        self.assertIn("compile_presentation", scenario._ACTION_ALIASES)

    def test_both_compile_verbs_target_the_identical_field(self):
        self.assertEqual(scenario._ACTION_ALIASES["compile_deck"], "compileRequested")
        self.assertEqual(scenario._ACTION_ALIASES["compile_presentation"], "compileRequested")

    def test_a_bare_compile_deck_action_normalizes_cleanly(self):
        merged = scenario._normalize_scenario_doc([{"action": "compile_deck"}])
        self.assertEqual(merged, {"compileRequested": True})

    def test_a_bare_compile_presentation_action_normalizes_identically(self):
        merged = scenario._normalize_scenario_doc([{"action": "compile_presentation"}])
        self.assertEqual(merged, {"compileRequested": True})

    def test_an_inline_payload_field_is_a_validation_error(self):
        from helpers import EngineError
        for action in ("compile_deck", "compile_presentation"):
            with self.subTest(action=action):
                with self.assertRaises(EngineError) as ctx:
                    scenario._normalize_scenario_doc([{"action": action, "renderMode": "panic"}])
                self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_unrelated_unknown_compile_verb_is_still_rejected(self):
        """Do not accept arbitrary verbs -- only the two allowlisted
        aliases above are recognized."""
        from helpers import EngineError
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "compile_slides"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["action"], "compile_slides")


class CompileActionEndToEndTests(unittest.TestCase):
    """End-to-end coverage through `run_scenario`: a `compile_deck`/
    `compile_presentation` step composes with a full, otherwise-valid
    journey and still reaches compile/gates/rehearsal/package exactly as
    the identical scenario without either verb already does."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_compile_deck_action_composes_with_the_full_happy_path(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "compile_deck"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(any(s["action"] == "compile" for s in report["steps"]))
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)

    def test_compile_presentation_action_composes_with_the_full_happy_path(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "compile_presentation"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)

    def test_compile_deck_via_the_cli_subprocess_entry_point_exits_zero(self):
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "compile_deck"})
        scenario_path = self.root / "compile-deck-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertIn("package", envelope["data"])

    def test_an_unrelated_unknown_action_still_fails_the_whole_scenario(self):
        """Regression guard for the original reported defect: an unknown
        deck-compilation verb previously made the *entire* scenario fail
        before any step ran -- this pins that an unknown verb still fails
        cleanly (never silently ignored), while the two allowlisted verbs
        above no longer do."""
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "compile_slides"})
        scenario_path = self.root / "unknown-compile-verb-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 1)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "VALIDATION_ERROR")
        self.assertFalse((self.root / "ws" / "run-report.json").exists(), "no step ever ran")


if __name__ == "__main__":
    unittest.main()
