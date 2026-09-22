"""End-to-end regression coverage for a complete, manual-only public
action-list journey -- brief through Stage package and restore -- built
almost entirely from the *snake_case* aliases introduced in Dark Factory
hardening cycle 7 (source descriptors, rehearsal timings/cuts, gate
names, the Stage approver, and an explicit export's output directory),
mixed with a few pre-existing camelCase fields to prove both casings
compose freely within one document.

This is the capstone test for hardening cycle 7: every individual
snake_case/camelCase gap closed this cycle has its own focused
regression file; this one instead proves they all compose into one
real, uninterrupted journey a black-box caller using a snake_case-heavy
vocabulary could actually run, reaching the identical named Stage
approval, editable `.pptx` with native notes, full nine-artifact
package, and restore points that the pre-existing camelCase-only
journey (`tests/test_full_manual_journey.py`) already reaches.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
import zipfile

from helpers import REPO_ROOT, cleanup, new_root, persistence, scenario

try:
    from pptx import Presentation
    HAVE_PPTX = True
except ImportError:  # pragma: no cover - environment always has it, but stay honest
    HAVE_PPTX = False

BIN = str(REPO_ROOT / "bin" / "throughline")
ARTIFACT_KINDS = {
    "EDITABLE_DECK", "SPEAKER_NOTES_DOC", "ACCESSIBLE_PDF", "EVIDENCE_APPROVAL_MANIFEST",
    "CAPTION_SCRIPT", "DEMO_ASSETS", "OFFLINE_BACKUP", "PANIC_DECK", "LAST_KNOWN_GOOD",
}


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _snake_case_journey_doc(export_dir) -> list[dict]:
    demo_asset_path = str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt")
    github_payload = json.loads((REPO_ROOT / "tests" / "fixtures" / "github" / "release_notes.json").read_text())
    workiq_payload = json.loads((REPO_ROOT / "tests" / "fixtures" / "workiq" / "sharepoint_doc.json").read_text())

    return [
        {"action": "set_talk_brief", "audience": "Conference attendees", "eventType": "keynote", "durationMinutes": 20,
         "takeaway": "Structured evidence review de-risks talks", "proofPoints": ["adoption stat"],
         "excludedTopics": [], "tone": "confident"},
        # Local source: every field expressed via its snake_case alias.
        {"action": "add_source", "origin": "local", "source_type": "local_paste", "source_uri": "paste:adoption-note",
         "author": "speaker@example.com", "access_state": "authorized", "permission_snapshot": "owner-only",
         "version": "v1",
         "content": "Throughline adoption grew 42% quarter over quarter across pilot teams.\n\n"
                    "Speakers using structured evidence review reported higher confidence rehearsing Q&A."},
        # GitHub source: snake_case descriptor built from the shared fixture.
        {"action": "add_source", "origin": github_payload["origin"], "source_type": github_payload["sourceType"],
         "source_uri": github_payload["uri"], "author": github_payload["owner"],
         "access_state": github_payload["permissionState"], "permission_snapshot": github_payload["aclSnapshot"],
         "version": github_payload["version"], "authorized_at": github_payload["retrievedAt"],
         "content": github_payload["content"]},
        # WorkIQ source: snake_case descriptor built from the shared fixture.
        {"action": "add_source", "origin": workiq_payload["origin"], "source_type": workiq_payload["sourceType"],
         "source_uri": workiq_payload["uri"], "author": workiq_payload["owner"],
         "access_state": workiq_payload["permissionState"], "permission_snapshot": workiq_payload["aclSnapshot"],
         "label_state": workiq_payload["sensitivityLabel"], "version": workiq_payload["version"],
         "content": workiq_payload["content"]},
        {"action": "propose_claim", "type": "factual", "text": "Throughline adoption grew 42% quarter over quarter.",
         "evidenceLocators": ["paste:adoption-note#p0"], "approve": True},
        {"action": "propose_claim", "type": "interpretive",
         "text": "This suggests structured evidence review meaningfully reduces talk-prep risk.",
         "evidenceLocators": ["paste:adoption-note#p1"],
         "rationale": "Confidence increase correlates with the adoption stat.", "approve": True},
        {"action": "propose_claim", "type": "aspirational", "text": "We recommend every team adopt structured evidence review.",
         "aspirationalLabel": "RECOMMENDATION", "approve": True},
        {"action": "select_throughline", "value": 0},
        {"action": "propose_route", "label": "Primary route", "beats": [
            {"role": "HOOK", "headline": "A stat that changes the room", "timeBudgetSeconds": 60, "spokenTalkTrack": "Open cold with the number."},
            {"role": "STAKES", "headline": "Talks fail without provenance", "timeBudgetSeconds": 90, "spokenTalkTrack": "Stakes.", "visualDescription": "Cluttered desk photo"},
            {"role": "TURN", "headline": "What changes the outcome", "timeBudgetSeconds": 90, "spokenTalkTrack": "Turn.", "visualDescription": "Ledger flow diagram"},
            {"role": "MECHANISM", "headline": "How the ledger works end to end", "timeBudgetSeconds": 120, "spokenTalkTrack": "Mechanism walkthrough.", "visualDescription": "Live CLI demo", "isDemo": True},
            {"role": "PROOF", "headline": "Adoption grew 42% in one quarter", "timeBudgetSeconds": 90, "spokenTalkTrack": "Proof.", "claimIds": [0], "visualDescription": "Bar chart"},
            {"role": "OBJECTION", "headline": "Is the overhead worth it", "timeBudgetSeconds": 90, "spokenTalkTrack": "Objection.", "claimIds": [1], "visualDescription": "Quote"},
            {"role": "ASK", "headline": "Start your next talk this way", "timeBudgetSeconds": 60, "spokenTalkTrack": "Close with the ask.", "claimIds": [2], "visualDescription": "CTA graphic"},
        ]},
        {"action": "propose_route", "label": "Short alt route", "beats": [
            {"role": "HOOK", "headline": "Alt hook", "timeBudgetSeconds": 60},
            {"role": "ASK", "headline": "Alt ask", "timeBudgetSeconds": 60},
        ]},
        {"action": "select_narrative_route", "value": 0},
        {"action": "set_demo_asset", "slide_role": "MECHANISM", "livePath": "cli-session://live-terminal",
         "prerecordedAssetPath": demo_asset_path, "staticAssetPath": demo_asset_path,
         "verbalRecoveryScript": "I will narrate the ledger flow verbally if the live demo fails."},
        # `run_gate` via the new `gate_name` snake_case alias.
        {"action": "run_gate", "gate_name": "narrative"},
        # `rehearse` via `slide_order`/`actual_seconds` per-slide aliases.
        {"action": "rehearse", "slide_order": 0, "actual_seconds": 58},
        {"action": "rehearse", "slide_order": 1, "actual_seconds": 95},
        {"action": "rehearse", "slide_order": 2, "actual_seconds": 88},
        {"action": "rehearse", "slide_order": 3, "actual_seconds": 130},
        {"action": "rehearse", "slide_order": 4, "actual_seconds": 85},
        {"action": "rehearse", "slide_order": 5, "actual_seconds": 92},
        {"action": "rehearse", "slide_order": 6, "actual_seconds": 55},
        {"action": "rehearse", "question": "What if adoption growth was seasonal?",
         "answer": "The 42% figure is quarter-over-quarter, which controls for that.", "claim_indices": [0]},
        # `rehearse`'s cuts sub-shape via the newly-fixed snake_case
        # `target_minutes` (the one explicitly-known adapter mismatch
        # going into this cycle).
        {"action": "rehearse", "target_minutes": 9},
        # `export` via the new `output_dir`/`render_mode` snake_case
        # aliases, plus the pre-existing camelCase `target`.
        {"action": "export", "target": "pptx", "render_mode": "normal"},
        {"action": "export", "target": "package", "output_dir": str(export_dir)},
        # Stage approval via the new `approver_name` snake_case alias.
        {"action": "approve_stage", "approver_name": "Dr. Jamie Rivera"},
    ]


class SnakeCaseFullJourneyTests(unittest.TestCase):
    """The complete, manual-only public action-list journey, built from
    snake_case field names throughout, run in-process against
    `engine.scenario.run_scenario` directly."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")
        self.export_dir = self.root / "stage-export"
        self.report = scenario.run_scenario(self.store, _snake_case_journey_doc(self.export_dir), self.root / "report")

    def tearDown(self):
        cleanup(self.root)

    def test_the_journey_completes_with_no_refusal(self):
        self.assertTrue(self.report["ok"], self.report.get("refusal"))
        self.assertIsNone(self.report["refusal"])

    def test_three_distinct_origin_sources_all_ingest_and_accumulate(self):
        self.assertEqual(len(self.report["sources"]), 3)
        self.assertEqual(sorted(s["origin"] for s in self.report["sources"]), ["github", "local", "workiq"])

    def test_evidence_claims_and_gates_are_all_observable(self):
        self.assertGreater(len(self.report["evidence"]), 0)
        self.assertEqual(len(self.report["claims"]), 3)
        gate_by_name = {g["gate"]: g["passed"] for g in self.report["gateResults"]}
        self.assertTrue(all(gate_by_name.values()), gate_by_name)
        self.assertTrue(self.report["stageGate"]["passed"])
        self.assertTrue(self.report["readiness"]["passed"])

    def test_rehearsal_reflects_the_snake_case_timings_and_cuts_target(self):
        self.assertEqual(self.report["rehearsal"]["totalActualSeconds"], 603.0)
        self.assertEqual(self.report["rehearsal"]["cutsTargetSeconds"], 540)
        self.assertEqual(len(self.report["qa"]), 1)

    def test_the_named_stage_approval_is_recorded(self):
        self.assertEqual(self.report["workspace"]["stageApprovedBy"], "Dr. Jamie Rivera")
        self.assertEqual(self.report["workspace"]["phase"], "PACKAGED")

    def test_the_explicit_output_dir_export_produced_the_full_nine_artifact_package(self):
        package_export = next(e for e in self.report["exports"] if e["target"] == "package")
        self.assertEqual(package_export["exportDir"], str(self.export_dir))
        self.assertEqual(set(package_export["artifactKinds"]), ARTIFACT_KINDS)
        self.assertTrue((self.export_dir / "manifest.json").exists())

    def test_every_top_level_report_compat_alias_is_present(self):
        r = self.report
        for camel, snake in (
            ("sources", "source_ledger"), ("evidence", "evidence_atoms"), ("conflicts", "conflict_cards"),
            ("gateResults", "gate_results"), ("auditEvents", "audit_trail"), ("routes", "narrative_routes"),
            ("restorePoints", "restore_points"), ("package", "export"),
        ):
            self.assertEqual(r[snake], r[camel], snake)
        self.assertEqual(r["workspace_id"], r["workspaceId"])
        self.assertEqual(r["deck_id"], r["package"]["deckId"])

    @unittest.skipUnless(HAVE_PPTX, "python-pptx not available for validation")
    def test_the_exported_deck_is_a_genuinely_editable_pptx_with_native_notes(self):
        pptx_export = next(e for e in self.report["exports"] if e["target"] == "pptx")
        pptx_path = pptx_export["path"]
        with zipfile.ZipFile(pptx_path) as zf:
            self.assertIsNone(zf.testzip())
            self.assertIn("[Content_Types].xml", zf.namelist())

        pres = Presentation(pptx_path)
        self.assertEqual(len(pres.slides), 7)
        for slide in pres.slides:
            self.assertTrue(slide.has_notes_slide)
            notes_text = slide.notes_slide.notes_text_frame.text
            self.assertIn("Time budget:", notes_text)
            self.assertIn("Sources:", notes_text)

    def test_restore_points_exist_for_every_major_milestone(self):
        triggers = {rp["trigger"] for rp in self.report["restorePoints"]}
        self.assertIn("compile", triggers)
        self.assertIn("export", triggers)
        self.assertTrue(any(t.startswith("gate:") for t in triggers))

    def test_applying_a_restore_point_reverts_state(self):
        from helpers import models, persistence as persistence_mod, restore_mod

        workspace_id = self.report["workspaceId"]
        conn = self.store.connect(workspace_id)
        restore_points = restore_mod.list_restore_points(conn, workspace_id)
        compile_point = next(rp for rp in restore_points if rp.trigger == "compile")
        rp, pre_revert = restore_mod.apply_restore_point(conn, workspace_id, compile_point.id, actor="Dr. Jamie Rivera")
        self.assertEqual(rp.id, compile_point.id)
        self.assertTrue(pre_revert.id)

        conn2 = self.store.connect(workspace_id)
        try:
            ws_after = persistence_mod.get(conn2, "workspace", workspace_id, models.Workspace)
            self.assertEqual(ws_after.phase, "COMPILED")
        finally:
            conn2.close()


class SnakeCaseFullJourneyCliSubprocessTests(unittest.TestCase):
    """The identical snake_case-heavy journey through the public
    `bin/throughline` CLI entry point end to end."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_the_full_journey_exits_zero_through_the_cli(self):
        export_dir = self.root / "stage-export-cli"
        scenario_path = self.root / "snake-case-full-journey.json"
        scenario_path.write_text(json.dumps(_snake_case_journey_doc(export_dir)))

        proc = _run_cli(
            "run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        data = envelope["data"]
        self.assertTrue(data["ok"], data.get("refusal"))
        self.assertEqual(data["workspace"]["stageApprovedBy"], "Dr. Jamie Rivera")
        self.assertEqual(set(next(e for e in data["exports"] if e["target"] == "package")["artifactKinds"]), ARTIFACT_KINDS)
        self.assertEqual(envelope["workspace_id"], data["workspaceId"])
        self.assertEqual(envelope["deck_id"], data["package"]["deckId"])


if __name__ == "__main__":
    unittest.main()
