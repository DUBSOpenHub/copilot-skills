"""End-to-end regression coverage for a complete, manual-only public
action-list journey -- brief through Stage package and restore -- using
only existing, already-shipped domain code (`engine/scenario.py`'s
action-list interface plus the CLI's own pre-existing `restore list`/
`restore apply` subcommands).

This is the capstone test for hardening cycle 6: every individual gap
(the `rehearse` payload contract, the `export` action, multi-origin
source accumulation, and full-state report exposure) has its own focused
regression file; this one instead proves they all compose into one real,
uninterrupted journey a black-box caller could actually run, and that the
result is a genuinely editable, reopenable `.pptx` with native notes and
all nine required Stage-package artifacts.

Contract exercised end-to-end:
- Multi-origin sources (local, GitHub, WorkIQ) accumulate, are evidenced,
  and back three typed, approved claims.
- A throughline and a route are proposed and selected.
- Accessibility (explicit + automatic alt text) and a full four-path demo
  asset are set before compile's slides reach Readiness.
- An explicit `run_gate` step composes with the mandatory automatic gate
  pipeline.
- `rehearse`'s widened vocabulary (a bulk timings wrapper, a Q&A pair,
  and a cuts request) all drive the real rehearsal/cuts domain calls.
- `export` produces a standalone editable draft deck and, in the same
  run, a second Stage package that (finding the first as its own
  last-known-good) carries all nine required artifact kinds.
- Stage approval is a named human, never bypassed.
- The exported `.pptx` opens as a genuine, editable OOXML deck with
  native (not embedded-image) headline text and per-slide native speaker
  notes.
- The workspace's own restore points (created automatically at compile/
  gate/export, exactly as before) can revert state via the CLI's
  pre-existing `restore apply`, which always snapshots the current state
  first before reverting.
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


def _full_journey_doc() -> list[dict]:
    demo_asset_path = str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt")
    github_payload = json.loads((REPO_ROOT / "tests" / "fixtures" / "github" / "release_notes.json").read_text())
    workiq_payload = json.loads((REPO_ROOT / "tests" / "fixtures" / "workiq" / "sharepoint_doc.json").read_text())

    return [
        {"action": "set_talk_brief", "audience": "Conference attendees", "eventType": "keynote", "durationMinutes": 20,
         "takeaway": "Structured evidence review de-risks talks", "proofPoints": ["adoption stat"],
         "excludedTopics": [], "tone": "confident"},
        # Three distinct-origin sources (local, GitHub, WorkIQ), all
        # explicitly staged public wrappers -- FR-SRC-1/FR-M365-*.
        {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:adoption-note",
         "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
         "content": "Throughline adoption grew 42% quarter over quarter across pilot teams.\n\n"
                    "Speakers using structured evidence review reported higher confidence rehearsing Q&A."},
        {"action": "add_source", **github_payload},
        {"action": "add_source", **workiq_payload},
        # Factual, interpretive, and aspirational claims -- all approved
        # by a named human (FR-GATE-4).
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
        {"action": "set_demo_asset", "slideRole": "MECHANISM", "livePath": "cli-session://live-terminal",
         "prerecordedAssetPath": demo_asset_path, "staticAssetPath": demo_asset_path,
         "verbalRecoveryScript": "I will narrate the ledger flow verbally if the live demo fails."},
        # `run_gate`: additive, explicit -- never a substitute for the
        # mandatory automatic pipeline that still runs regardless.
        {"action": "run_gate", "gate": "narrative"},
        # `rehearse`'s widened vocabulary: a bulk `run` wrapper (the exact
        # `rehearse run --input timings.json` document shape), a Q&A pair,
        # and a shorter-variant/cuts request -- all through the one verb.
        {"action": "rehearse", "run": {
            "HOOK": 58, "STAKES": 95, "TURN": 88, "MECHANISM": 130, "PROOF": 85, "OBJECTION": 92, "ASK": 55,
        }},
        {"action": "rehearse", "question": "What if adoption growth was seasonal?",
         "answer": "The 42% figure is quarter-over-quarter, which controls for that.", "claimIndices": [0]},
        {"action": "rehearse", "targetMinutes": 9},
        # `export`: a standalone editable draft, then a full Stage
        # package (which will find the draft's *sibling* package export
        # below as its own last-known-good once Stage passes).
        {"action": "export", "target": "pptx"},
        {"action": "export", "target": "package"},
        {"action": "approve_stage", "value": "Dr. Jamie Rivera"},
    ]


class FullManualJourneyTests(unittest.TestCase):
    """The complete, manual-only public action-list journey, run
    in-process against `engine.scenario.run_scenario` directly."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")
        self.report = scenario.run_scenario(self.store, _full_journey_doc(), self.root / "report")

    def tearDown(self):
        cleanup(self.root)

    def test_the_journey_completes_with_no_refusal(self):
        self.assertTrue(self.report["ok"], self.report.get("refusal"))
        self.assertIsNone(self.report["refusal"])

    def test_three_distinct_origin_sources_all_ingest_and_accumulate(self):
        self.assertEqual(len(self.report["sources"]), 3)
        self.assertEqual(sorted(s["origin"] for s in self.report["sources"]), ["github", "local", "workiq"])
        self.assertTrue(all(s["state"] in ("AUTHORIZED", "CURATED", "CITED", "APPROVED") for s in self.report["sources"]))

    def test_evidence_claims_and_gates_are_all_observable(self):
        self.assertGreater(len(self.report["evidence"]), 0)
        self.assertEqual(len(self.report["claims"]), 3)
        self.assertEqual({c["type"] for c in self.report["claims"]}, {"FACTUAL", "INTERPRETIVE", "ASPIRATIONAL"})
        self.assertTrue(all(c["approver"] for c in self.report["claims"]))
        gate_by_name = {g["gate"]: g["passed"] for g in self.report["gateResults"]}
        self.assertTrue(all(gate_by_name.values()), gate_by_name)
        self.assertTrue(self.report["stageGate"]["passed"])
        self.assertIsNotNone(self.report["readiness"])
        self.assertTrue(self.report["readiness"]["passed"])

    def test_throughline_and_route_selection_are_recorded(self):
        self.assertEqual(len(self.report["throughline"]["candidates"]), 3)
        self.assertEqual(len(self.report["route"]["candidates"]), 2)
        self.assertEqual(self.report["route"]["active"]["label"], "Primary route")

    def test_rehearsal_reports_timing_qa_and_proposed_cuts(self):
        self.assertEqual(self.report["rehearsal"]["totalActualSeconds"], 603.0)
        self.assertEqual(len(self.report["rehearsal"]["perSlide"]), 7)
        self.assertIn("proposedCuts", self.report["rehearsal"])
        self.assertEqual(self.report["rehearsal"]["cutsTargetSeconds"], 540)
        self.assertEqual(len(self.report["qa"]), 1)
        self.assertTrue(self.report["qa"][0]["grounding"]["allGrounded"])

    def test_both_export_requests_succeed_and_the_package_carries_all_nine_artifacts(self):
        self.assertEqual([e["target"] for e in self.report["exports"]], ["pptx", "package"])
        self.assertEqual(set(self.report["exports"][1]["artifactKinds"]), ARTIFACT_KINDS)
        self.assertIn("package", self.report)
        self.assertEqual(self.report["workspace"]["phase"], "PACKAGED")
        self.assertEqual(self.report["workspace"]["stageApprovedBy"], "Dr. Jamie Rivera")

    @unittest.skipUnless(HAVE_PPTX, "python-pptx not available for validation")
    def test_the_exported_deck_is_a_genuinely_editable_pptx_with_native_notes(self):
        pptx_path = self.report["exports"][0]["path"]
        with zipfile.ZipFile(pptx_path) as zf:
            self.assertIsNone(zf.testzip())
            self.assertIn("[Content_Types].xml", zf.namelist())

        pres = Presentation(pptx_path)
        self.assertEqual(len(pres.slides), 7)
        headline_texts = [
            shape.text_frame.text
            for slide in pres.slides for shape in slide.shapes
            if shape.has_text_frame and "headline" in shape.name
        ]
        self.assertIn("A stat that changes the room", headline_texts)
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

    def test_applying_an_early_restore_point_reverts_state_and_snapshots_current_first(self):
        """Uses the existing, pre-existing `restore` domain module
        directly (no action-list verb needed) to prove the restore points
        created during this journey genuinely revert state, and that the
        engine always snapshots the current state first before reverting
        (FR-DEL-7) -- a physical, restorable backup of the pre-revert
        (`PACKAGED`) state exists on disk with its own valid restore-point
        record, even though this test only exercises reverting forward
        once (`tests/test_restore.py` already separately pins the
        general revert-then-reconnect contract this reuses)."""
        from helpers import models, persistence as persistence_mod, restore_mod

        workspace_id = self.report["workspaceId"]
        conn = self.store.connect(workspace_id)
        restore_points = restore_mod.list_restore_points(conn, workspace_id)
        compile_point = next(rp for rp in restore_points if rp.trigger == "compile")
        # `apply_restore_point` itself closes `conn` (the underlying file
        # is swapped); never touch `conn` again afterward.
        rp, pre_revert = restore_mod.apply_restore_point(conn, workspace_id, compile_point.id, actor="Dr. Jamie Rivera")
        self.assertEqual(rp.id, compile_point.id)
        self.assertTrue(pre_revert.id)
        self.assertEqual(pre_revert.trigger, "pre_revert")
        from pathlib import Path
        self.assertTrue(Path(pre_revert.path).exists(), "the pre-revert snapshot is a real, restorable backup")

        conn2 = self.store.connect(workspace_id)
        try:
            ws_after = persistence_mod.get(conn2, "workspace", workspace_id, models.Workspace)
            self.assertEqual(ws_after.phase, "COMPILED")
            self.assertIsNone(ws_after.manifest_id)
            self.assertIsNone(ws_after.stage_approved_by)
        finally:
            conn2.close()


class FullManualJourneyCliSubprocessTests(unittest.TestCase):
    """The identical journey through the public `bin/throughline` CLI
    entry point end to end, including restore via the CLI's own
    pre-existing `restore list`/`restore apply` subcommands."""

    def setUp(self):
        self.root = new_root()
        self.workspace_dir = self.root / "ws"

    def tearDown(self):
        cleanup(self.root)

    def test_the_full_journey_exits_zero_and_restore_works_through_the_cli(self):
        scenario_path = self.root / "full-journey.json"
        scenario_path.write_text(json.dumps(_full_journey_doc()))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.workspace_dir))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"])
        data = envelope["data"]
        self.assertTrue(data["ok"], data.get("refusal"))
        self.assertEqual(set(data["exports"][1]["artifactKinds"]), ARTIFACT_KINDS)

        # Restore, via the CLI's own existing `restore` subcommands
        # (never a scenario action) -- the public interface for this
        # pre-existing domain behavior.
        listing = _run_cli("--workspace-root", str(self.workspace_dir), "restore", "list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        restore_points = json.loads(listing.stdout)["data"]["restorePoints"]
        compile_point = next(rp for rp in restore_points if rp["trigger"] == "compile")

        applied = _run_cli(
            "--workspace-root", str(self.workspace_dir), "restore", "apply", compile_point["id"],
            "--actor", "Dr. Jamie Rivera",
        )
        self.assertEqual(applied.returncode, 0, applied.stderr)
        applied_envelope = json.loads(applied.stdout)
        self.assertTrue(applied_envelope["ok"])
        self.assertEqual(applied_envelope["data"]["restoredTo"]["id"], compile_point["id"])

        status = _run_cli("--workspace-root", str(self.workspace_dir), "status")
        self.assertEqual(json.loads(status.stdout)["data"]["workspace"]["phase"], "COMPILED")


if __name__ == "__main__":
    unittest.main()
