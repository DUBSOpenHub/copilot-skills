"""Regression tests for `run_scenario`'s two accepted scenario-document
wire shapes (`engine/scenario._normalize_scenario_doc`): the documented
object-form (unchanged), and the list-form some black-box callers send
instead — a JSON array whose every element names exactly one top-level
field, e.g. `[{"actor": "..."}, {"sources": [...]}, ...]`. Both normalize
to, and drive, the exact same execution model; a scenario document that is
neither shape (or a list with a malformed element) is a clean
`VALIDATION_ERROR`, never the `AttributeError` a bare `.get()` call on a
list used to raise.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import EngineError, REPO_ROOT, cleanup, new_root, persistence, scenario

OBJECT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"
LIST_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path_list_form.json"
BIN = str(REPO_ROOT / "bin" / "throughline-engine")


def _run_cli(*args, timeout=120):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


class ListFormNormalizationUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the normalization function itself —
    fast, and pins the exact accepted/rejected shapes independent of the
    full end-to-end run."""

    def test_object_form_passes_through_unchanged(self):
        doc = {"actor": "someone", "sources": []}
        self.assertIs(scenario._normalize_scenario_doc(doc), doc)

    def test_list_form_of_single_key_objects_merges_into_the_equivalent_dict(self):
        object_doc = json.loads(OBJECT_FIXTURE.read_text())
        list_doc = json.loads(LIST_FIXTURE.read_text())
        self.assertIsInstance(list_doc, list)
        self.assertEqual(scenario._normalize_scenario_doc(list_doc), object_doc)

    def test_empty_list_normalizes_to_an_empty_dict(self):
        self.assertEqual(scenario._normalize_scenario_doc([]), {})

    def test_a_string_or_number_or_null_document_is_a_validation_error_not_a_crash(self):
        for bad_doc in ("not-an-object", 42, None, True):
            with self.subTest(bad_doc=bad_doc):
                with self.assertRaises(EngineError) as ctx:
                    scenario._normalize_scenario_doc(bad_doc)
                self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_list_element_that_is_not_an_object_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc(["not-an-object"])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["index"], 0)

    def test_a_list_element_with_more_than_one_key_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"actor": "a", "stageApprover": "b"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_list_element_with_zero_keys_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_field_repeated_across_list_elements_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"actor": "a"}, {"actor": "b"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["field"], "actor")


class ListFormEndToEndTests(unittest.TestCase):
    """The list-form fixture, run through the exact same code path as the
    documented object-form fixture (`test_scenario_local_happy_path.py`),
    must reach the identical successful outcome — proving normalization
    happens once, up front, rather than duplicating pipeline logic."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_list_form_fixture_produces_a_complete_stage_package_via_run_scenario_directly(self):
        store = persistence.Store(root=self.root / "workspace-root")
        doc = json.loads(LIST_FIXTURE.read_text())

        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"])
        self.assertIsNone(report["refusal"])
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)
        self.assertTrue((self.root / "report" / "run-report.json").exists())

    def test_list_form_fixture_produces_the_same_outcome_as_the_object_form_fixture(self):
        object_report = scenario.run_scenario(
            persistence.Store(root=self.root / "object-root"),
            json.loads(OBJECT_FIXTURE.read_text()),
            self.root / "object-report",
        )
        list_report = scenario.run_scenario(
            persistence.Store(root=self.root / "list-root"),
            json.loads(LIST_FIXTURE.read_text()),
            self.root / "list-report",
        )
        self.assertEqual(object_report["ok"], list_report["ok"])
        self.assertEqual(object_report["stageGate"]["passed"], list_report["stageGate"]["passed"])
        self.assertEqual(set(object_report["package"]["artifactKinds"]), set(list_report["package"]["artifactKinds"]))

    def test_list_form_fixture_via_the_cli_subprocess_entry_point(self):
        proc = _run_cli(
            "--workspace-root", str(self.root / "cli-workspace-root"),
            "run-scenario", "--scenario", str(LIST_FIXTURE), "--out", str(self.root / "cli-report"),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertIn("package", envelope["data"])

    def test_a_malformed_list_form_document_is_a_clean_validation_error_through_the_cli(self):
        """The full black-box path (subprocess -> CLI -> run_scenario)
        never surfaces the fixed `AttributeError` — a malformed list-form
        document is a clean, observable `VALIDATION_ERROR` envelope
        (exit 1), never a stack trace on stdout, and never a fabricated
        'refusal' (this is a structural input error, not a domain
        refusal)."""
        bad_path = self.root / "bad-scenario.json"
        bad_path.write_text(json.dumps([{"actor": "a", "brief": {}}]))  # two keys in one element

        proc = _run_cli(
            "run-scenario", "--scenario", str(bad_path), "--workspace", str(self.root / "workspace-dir"),
        )
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("Traceback", proc.stdout)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "VALIDATION_ERROR")
        self.assertFalse((self.root / "workspace-dir" / "run-report.json").exists())


if __name__ == "__main__":
    unittest.main()
