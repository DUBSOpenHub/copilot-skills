"""NFR-6 flagship test: a complete end-to-end run using manual/local
inputs alone (no WorkIQ/Microsoft 365 connection of any kind) produces a
full stage package, driven entirely through `run-scenario` — the same
entry point a human, the Skill Prompt Layer agent, or a sealed test
harness would use."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO_ROOT, cleanup, new_root, persistence, scenario

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"
BIN = str(REPO_ROOT / "bin" / "throughline-engine")


class LocalHappyPathTests(unittest.TestCase):
    def setUp(self):
        self.root = new_root()
        self.out_dir = self.root / "report"

    def tearDown(self):
        cleanup(self.root)

    def test_full_local_only_run_produces_a_complete_stage_package(self):
        store = persistence.Store(root=self.root / "workspace-root")
        doc = json.loads(FIXTURE.read_text())
        # NFR-6: assert every source in this fixture is local-origin —
        # this run genuinely requires no WorkIQ/Microsoft 365 connection.
        self.assertTrue(all(s["origin"] == "local" for s in doc["sources"]))

        report = scenario.run_scenario(store, doc, self.out_dir)

        for gate_name, result in report["preStageGates"].items():
            self.assertTrue(result["passed"], f"{gate_name} failed: {result['failedChecks']}")
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)

        artifact_kinds = set(report["package"]["artifactKinds"])
        expected_first_run_kinds = {
            "EDITABLE_DECK", "SPEAKER_NOTES_DOC", "ACCESSIBLE_PDF", "EVIDENCE_APPROVAL_MANIFEST",
            "CAPTION_SCRIPT", "DEMO_ASSETS", "OFFLINE_BACKUP", "PANIC_DECK",
        }
        self.assertEqual(artifact_kinds, expected_first_run_kinds)  # LKG absent on a first run

        export_dir = Path(report["package"]["exportDir"])
        self.assertTrue((export_dir / "deck.pptx").exists())
        self.assertTrue((export_dir / "manifest.json").exists())

        from pptx import Presentation
        pres = Presentation(str(export_dir / "deck.pptx"))
        self.assertTrue(7 <= len(pres.slides) <= 15)
        for slide in pres.slides:
            self.assertTrue(slide.has_notes_slide)

        self.assertTrue((self.out_dir / "run-report.json").exists())
        self.assertTrue(report["qa"][0]["grounding"]["allGrounded"])

    def test_same_fixture_via_the_cli_subprocess_entry_point(self):
        """The documented README quickstart command, exercised for real."""
        proc = subprocess.run(
            [sys.executable, BIN, "--workspace-root", str(self.root / "cli-workspace-root"),
             "run-scenario", "--scenario", str(FIXTURE), "--out", str(self.out_dir / "cli")],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertIn("package", envelope["data"])


if __name__ == "__main__":
    unittest.main()
