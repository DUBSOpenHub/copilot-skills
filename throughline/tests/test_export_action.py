"""Regression tests for the public action-list `export` verb
(`engine/scenario._ACTION_ALIASES["export"]` / `_process_export_request`):
the existing `export pptx`/`export package` domain behavior, reachable
through `run-scenario`'s action-list interface.

Compatibility gap this closes: `export` was not in `_ACTION_ALIASES` at
all, so any action-list document naming it was rejected as an unknown
action (`VALIDATION_ERROR`, exit 1) at scenario-document-normalization
time -- before a single step of the walk ran, aborting the whole
end-to-end setup regardless of how many other steps the same document
also staged.

Contract:
- `target: "pptx"` (or the `deck`/`draft`/`pptx_draft`/`deck_export`
  aliases) runs the identical `package.export_pptx_draft` call `export
  pptx` already performs -- usable any time after compile, independent of
  Stage. An optional `renderMode` (`normal`|`panic`) is accepted; an
  `outputDir`/`exportDir` override is rejected (there is no such override
  anywhere in the domain layer for this target).
- `target: "package"` (or the `stage`/`stage_package`/`stagepackage`
  aliases) runs the identical `package.export_package` call `export
  package` already performs -- re-running the real Stage gate itself.
  An optional `outputDir`/`exportDir` override is accepted.
- Neither target ever bypasses a gate or named-human-approval check: a
  `package` request when Stage has not passed is refused with the
  identical, pre-existing `GATE_NOT_PASSED` `EngineError` -- a structured
  `report["refusal"]`, exit 0, never a crash and never a silent skip.
- An unrecognized `target`, an unexpected field, or an invalid
  `renderMode` is a clean `VALIDATION_ERROR`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
import zipfile

from helpers import EngineError, REPO_ROOT, cleanup, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _as_field_list(doc: dict) -> list[dict]:
    return [{k: v} for k, v in doc.items()]


class ExportActionVocabularyUnitTests(unittest.TestCase):
    """Direct coverage of the action-list normalization itself."""

    def test_export_is_a_known_action(self):
        self.assertIn("export", scenario._ACTION_ALIASES)
        self.assertEqual(scenario._ACTION_ALIASES["export"], "exportRequests")

    def test_an_export_element_contributes_one_export_request(self):
        doc = [{"action": "export", "target": "pptx"}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["exportRequests"], [{"target": "pptx"}])

    def test_multiple_export_elements_accumulate_in_order(self):
        doc = [
            {"action": "export", "target": "pptx"},
            {"action": "export", "target": "package", "outputDir": "/tmp/whatever"},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(len(merged["exportRequests"]), 2)
        self.assertEqual(merged["exportRequests"][0]["target"], "pptx")
        self.assertEqual(merged["exportRequests"][1]["target"], "package")

    def test_an_empty_export_element_is_rejected_at_normalization(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "export"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class ExportActionEndToEndTests(unittest.TestCase):
    """End-to-end coverage through `run_scenario`: explicit export
    requests execute the real domain export calls."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _full_doc(self, extra_actions: list[dict]) -> list[dict]:
        base = json.loads(FIXTURE.read_text())
        return _as_field_list(base) + extra_actions

    def test_a_pptx_target_produces_an_editable_draft_deck(self):
        doc = self._full_doc([{"action": "export", "target": "pptx"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["exports"]), 1)
        export_result = report["exports"][0]
        self.assertEqual(export_result["target"], "pptx")
        deck_path = export_result["path"]
        with zipfile.ZipFile(deck_path) as zf:
            self.assertIsNone(zf.testzip())
            self.assertIn("[Content_Types].xml", zf.namelist())

    def test_deck_draft_and_pptx_draft_target_aliases_are_equivalent(self):
        for alias in ("deck", "draft", "pptx_draft", "deck_export", "PPTX", "Deck"):
            with self.subTest(alias=alias):
                doc = self._full_doc([{"action": "export", "target": alias}])
                store = persistence.Store(root=self.root / f"ws-{alias}")
                report = scenario.run_scenario(store, doc, self.root / f"report-{alias}")
                self.assertTrue(report["ok"], report.get("refusal"))
                self.assertEqual(report["exports"][0]["target"], "pptx")

    def test_a_panic_render_mode_is_accepted(self):
        doc = self._full_doc([{"action": "export", "target": "pptx", "renderMode": "panic"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(report["exports"][0]["path"].endswith("panic-deck.pptx"))

    def test_an_invalid_render_mode_is_a_validation_error(self):
        doc = self._full_doc([{"action": "export", "target": "pptx", "renderMode": "explosive"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_a_pptx_target_rejects_an_output_directory_override(self):
        doc = self._full_doc([{"action": "export", "target": "pptx", "outputDir": str(self.root / "nowhere")}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_a_package_target_produces_all_nine_artifact_kinds_when_a_prior_export_exists(self):
        """The automatic end-of-walk export (once Stage passes) already
        produces 8 kinds (no `LAST_KNOWN_GOOD` -- there is no earlier
        Stage-passed export yet); a second, explicit `package` request in
        the same run finds that first export as its own last-known-good,
        completing the full 9-artifact contract in a single scenario."""
        doc = self._full_doc([{"action": "export", "target": "package"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["target"], "package")
        self.assertEqual(set(report["exports"][0]["artifactKinds"]), {
            "EDITABLE_DECK", "SPEAKER_NOTES_DOC", "ACCESSIBLE_PDF", "EVIDENCE_APPROVAL_MANIFEST",
            "CAPTION_SCRIPT", "DEMO_ASSETS", "OFFLINE_BACKUP", "PANIC_DECK", "LAST_KNOWN_GOOD",
        })

    def test_a_package_target_with_an_output_dir_override_writes_there(self):
        custom_dir = self.root / "custom-export-location"
        doc = self._full_doc([{"action": "export", "target": "package", "outputDir": str(custom_dir)}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["exportDir"], str(custom_dir))
        self.assertTrue((custom_dir / "manifest.json").exists())

    def test_stage_alias_targets_the_identical_package_export(self):
        doc = self._full_doc([{"action": "export", "target": "stage"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["target"], "package")

    def test_an_unrecognized_target_is_a_validation_error(self):
        doc = self._full_doc([{"action": "export", "target": "carrier_pigeon"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_an_unexpected_field_is_a_validation_error(self):
        doc = self._full_doc([{"action": "export", "target": "pptx", "notes": "extra"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_the_same_journey_via_the_cli_subprocess_exits_zero(self):
        doc = self._full_doc([{"action": "export", "target": "pptx"}, {"action": "export", "target": "package"}])
        scenario_path = self.root / "export-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertEqual(len(envelope["data"]["exports"]), 2)


class ExportBlockedOutcomeTests(unittest.TestCase):
    """A `package` export request is a normal, structured domain refusal
    (never a bypass, never a crash) when Stage has not passed -- and the
    rest of the already-persisted workspace state remains observable in
    the report."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _unapproved_claims_doc(self) -> list[dict]:
        """The canonical happy-path fixture, minus every claim's
        `approve: true` -- the compiled deck still *cites* each claim (the
        fixture's own route beats reference them), so CLAIMS (and
        therefore STAGE) is guaranteed to fail, exactly like an
        unapproved-claim talk would in real use."""
        base = json.loads(FIXTURE.read_text())
        for claim in base["claims"]:
            claim.pop("approve", None)
        base.pop("rehearsalTimings", None)
        base.pop("qaPairs", None)
        base.pop("stageApprover", None)
        return _as_field_list(base)

    def test_a_blocked_package_export_is_a_structured_refusal_not_a_crash(self):
        doc = self._unapproved_claims_doc() + [{"action": "export", "target": "package"}]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "GATE_NOT_PASSED")
        # Never bypassed: Stage genuinely did not pass.
        self.assertFalse(report["stageGate"]["passed"])

    def test_a_blocked_export_still_exits_zero_through_the_cli(self):
        doc = self._unapproved_claims_doc() + [{"action": "export", "target": "package"}]
        scenario_path = self.root / "blocked-export-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"])
        self.assertFalse(envelope["data"]["ok"])
        self.assertEqual(envelope["data"]["refusal"]["code"], "GATE_NOT_PASSED")

    def test_a_blocked_export_still_exposes_persisted_sources_claims_and_slides(self):
        doc = self._unapproved_claims_doc() + [{"action": "export", "target": "package"}]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertFalse(report["ok"])
        self.assertEqual(len(report["sources"]), 1)
        self.assertEqual(len(report["claims"]), 3)
        self.assertEqual(len(report["slides"]), 7)
        self.assertNotIn("exports", report)
        gate_by_name = {g["gate"]: g["passed"] for g in report["gateResults"]}
        self.assertFalse(gate_by_name["CLAIMS"])
        self.assertFalse(gate_by_name["STAGE"])
        self.assertTrue(gate_by_name["SCOPE"])

    def test_a_pptx_draft_export_still_works_even_when_stage_would_fail(self):
        """`pptx` never requires Stage -- it is usable any time after
        compile, exactly like the standalone `export pptx` CLI command."""
        doc = self._unapproved_claims_doc() + [{"action": "export", "target": "pptx"}]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["target"], "pptx")
        self.assertFalse(report["stageGate"]["passed"])


if __name__ == "__main__":
    unittest.main()
