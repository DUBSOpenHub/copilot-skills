"""Integrated public action-list regression test: a single, realistic
black-box journey -- a talk brief plus representative source descriptors
(manual/uploaded local content, a GitHub-shaped descriptor, and a
WorkIQ-shaped descriptor, using the wrapper/field-alias/omitted-origin
shapes a public caller commonly sends) -- exercised entirely through the
public action-list `run-scenario` interface, driving existing evidence
extraction, claim derivation/approval, default throughline/route
proposal, compile, rehearsal, readiness, and package logic end to end,
plus a set of targeted malformed/blocked cases that must still be
refused cleanly rather than silently accepted.

This is a single integration pass over hardening-cycle-5's fixes working
together (`engine/scenario.py`'s action-list adapter normalization,
`engine/ingest.py`'s origin inference, `engine/narrative.py`'s default
route generation, and `engine/rehearsal.py`'s source-change reporting) --
the individual unit-level contracts for each are covered by their own
dedicated test files (`test_compile_action_aliases.py`,
`test_source_action_list_payload_wrappers.py`,
`test_origin_inference_from_context.py`, `test_default_route_generation.py`,
`test_rehearsal_timing_aliases.py`, `test_rehearsal_source_changes.py`).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, cleanup, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


class PublicActionListIntegrationTests(unittest.TestCase):
    """The full, valid source-driven journey."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _upload_path(self) -> str:
        upload_dir = self.root / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_file = upload_dir / "adoption-notes.txt"
        upload_file.write_text(
            "Structured evidence review reduced talk-prep time by half across every pilot team.\n"
        )
        return str(upload_file)

    def _full_doc(self) -> list[dict]:
        return [
            {"action": "set_actor", "value": "Dr. Jamie Rivera"},
            {"action": "set_talk_brief", "audience": "Conference attendees", "eventType": "keynote",
             "durationMinutes": 20, "takeaway": "Structured evidence review de-risks talks",
             "proofPoints": ["adoption stat"], "excludedTopics": [], "tone": "confident"},

            # -- Representative source descriptors ---------------------------
            # 1) Manual/uploaded local content, via the "descriptor" wrapper
            #    and the "path"/"type"/"access" field-name aliases (never
            #    the exact documented "uri"/"sourceType"/"permissionState").
            {"action": "add_source", "descriptor": {
                "origin": "manual", "path": self._upload_path(), "type": "local_upload",
                "owner": "speaker@example.com", "access": "authorized", "aclSnapshot": "owner-only",
                "version": "v1",
            }},
            # 2) A GitHub-shaped descriptor with `origin` omitted entirely
            #    (inferred from `sourceType`), via the "source" wrapper.
            {"action": "ingest_source", "source": {
                "sourceType": "github_issue", "uri": "gh://org/repo/issues/42",
                "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
                "version": "v1", "content": "Issue discussion: adoption grew 42% quarter over quarter.",
            }},
            # 3) A WorkIQ-shaped descriptor using a staged, case-varied
            #    origin alias ("SharePoint" -> "workiq"), supplied via the
            #    "sources" list wrapper (one item).
            {"action": "add_source", "sources": [{
                "origin": "SharePoint", "sourceType": "sharepoint_doc", "uri": "sharepoint://deck/notes",
                "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
                "version": "v1", "content": "Notes retrieved from a SharePoint document via WorkIQ.",
            }]},

            # -- Claims (referencing the ingested sources by bare uri) ------
            {"action": "propose_claim", "type": "factual",
             "text": "Adoption grew 42% quarter over quarter.",
             "evidenceLocators": ["gh://org/repo/issues/42"], "approve": True},
            {"action": "propose_claim", "type": "interpretive",
             "text": "This suggests structured evidence review meaningfully reduces talk-prep risk.",
             "evidenceLocators": [self._upload_path()],
             "rationale": "Both the uploaded notes and the GitHub discussion agree on the same effect.",
             "approve": True},

            # -- No explicit throughlineDrafts/routeDrafts: both fall back --
            # to their deterministic, source-driven defaults.

            # -- Explicitly name the (already-automatic) compile step -------
            {"action": "compile_deck"},

            # -- Rehearsal: alias timing shapes for every default beat ------
            {"action": "rehearse", "slideRole": "HOOK", "seconds": 20},
            {"action": "set_rehearsal_timing", "slideRole": "STAKES", "duration": 20},
            {"action": "rehearse", "slideRole": "TURN", "durationSeconds": 20},
            {"action": "set_rehearsal_timing", "slideRole": "MECHANISM", "actualSeconds": 20},
            {"action": "rehearse", "slideRole": "PROOF", "seconds": 20},
            {"action": "set_rehearsal_timing", "slideRole": "OBJECTION", "duration": 20},
            {"action": "rehearse", "slideRole": "ASK", "actualSeconds": 20},

            {"action": "approve_stage", "value": "Dr. Jamie Rivera"},
        ]

    def test_the_full_source_driven_journey_reaches_stage_and_package(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, self._full_doc(), self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertIsNone(report["refusal"])

        # -- Sources: all three ingest and authorize -------------------------
        ingest_steps = [s for s in report["steps"] if s["action"] == "source.ingest"]
        self.assertEqual(len(ingest_steps), 3)
        self.assertTrue(all(s["state"] == "AUTHORIZED" for s in ingest_steps))

        # -- Evidence: extracted for every authorized source -----------------
        evidence_steps = [s for s in report["steps"] if s["action"] == "evidence.extract"]
        self.assertEqual(len(evidence_steps), 3)
        self.assertTrue(all(s["atomCount"] > 0 for s in evidence_steps))

        # -- Claims: both proposed and approved ------------------------------
        claim_propose_step = next(s for s in report["steps"] if s["action"] == "claim.propose")
        self.assertEqual(claim_propose_step["count"], 2)
        self.assertEqual(len([s for s in report["steps"] if s["action"] == "claim.approve"]), 2)

        # -- Throughline: exactly 3 candidates, one active -------------------
        self.assertEqual(len(report["throughline"]["candidates"]), 3)
        self.assertIn("active", report["throughline"])

        # -- Routes: 2 or 3 candidates (source-driven default), one active --
        self.assertIn(len(report["route"]["candidates"]), (2, 3))
        self.assertIn("active", report["route"])

        # -- Compile -----------------------------------------------------------
        compile_step = next(s for s in report["steps"] if s["action"] == "compile")
        self.assertGreaterEqual(compile_step["slideCount"], 7)

        # -- Gates: readiness (and the rest) pass ----------------------------
        self.assertTrue(report["preStageGates"]["readiness"]["passed"], report["preStageGates"]["readiness"])
        self.assertTrue(report["preStageGates"]["narrative"]["passed"], report["preStageGates"]["narrative"])
        self.assertTrue(report["preStageGates"]["claims"]["passed"], report["preStageGates"]["claims"])

        # -- Rehearsal: every alias timing shape resolved, no source drift --
        self.assertIn("rehearsal", report)
        self.assertEqual(len(report["rehearsal"]["perSlide"]), 7)
        self.assertEqual(report["rehearsal"]["totalActualSeconds"], 140)
        self.assertEqual(report["rehearsal"]["sourceChanges"], [])

        # -- Stage + package --------------------------------------------------
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)
        self.assertIn("EDITABLE_DECK", report["package"]["artifactKinds"])

        # -- Audit: every step is durably recorded ---------------------------
        self.assertGreater(len(report["auditEvents"]), 0)

    def test_the_same_journey_via_the_cli_subprocess_exits_zero(self):
        scenario_path = self.root / "integration-scenario.json"
        scenario_path.write_text(json.dumps(self._full_doc()))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertIn("package", envelope["data"])
        self.assertEqual(envelope["workspace_id"], envelope["data"]["workspaceId"])
        self.assertEqual(envelope["deck_id"], envelope["data"]["package"]["deckId"])


class PublicActionListMalformedAndBlockedCaseTests(unittest.TestCase):
    """Targeted malformed/blocked cases alongside the same valid journey
    above -- authorization, source limits, and validation are never
    weakened by any of the new acceptance shapes."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _brief_step(self) -> dict:
        return {
            "action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
            "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident",
        }

    def test_an_unknown_action_verb_fails_the_entire_scenario_before_any_step_runs(self):
        doc = [self._brief_step(), {"action": "doSomethingUnknown", "foo": "bar"}]
        scenario_path = self.root / "unknown-action.json"
        scenario_path.write_text(json.dumps(doc))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 1)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "VALIDATION_ERROR")
        self.assertFalse((self.root / "ws" / "run-report.json").exists())

    def test_an_unallowlisted_compile_verb_is_still_rejected(self):
        doc = [self._brief_step(), {"action": "compile_slides"}]
        store = persistence.Store(root=self.root / "ws")
        with self.assertRaises(Exception):
            scenario.run_scenario(store, doc, self.root / "report")

    def test_a_denied_permission_source_is_still_correctly_blocked_not_authorized(self):
        doc = [
            self._brief_step(),
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:denied",
             "owner": "a@example.com", "permissionState": "denied", "aclSnapshot": "owner-only",
             "version": "v1", "content": "irrelevant"},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "SOURCE_UNAUTHORIZED")

    def test_an_unrecognized_origin_with_no_inference_signal_is_still_refused(self):
        doc = [
            self._brief_step(),
            {"action": "add_source", "origin": "carrier_pigeon", "sourceType": "local_paste", "uri": "paste:bogus",
             "owner": "a@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "irrelevant"},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_an_ambiguous_source_wrapper_mixture_is_a_clean_validation_error(self):
        doc = [
            self._brief_step(),
            {"action": "add_source", "source": {"uri": "paste:a"}, "descriptor": {"uri": "paste:b"}},
        ]
        store = persistence.Store(root=self.root / "ws")
        with self.assertRaises(Exception) as ctx:
            scenario.run_scenario(store, doc, self.root / "report")
        self.assertEqual(getattr(ctx.exception, "code", None), "VALIDATION_ERROR")

    def test_a_bare_brief_with_no_source_context_is_still_refused_for_missing_routes(self):
        """Pins the pre-existing, unaffected behavior alongside every new
        acceptance shape above: no source context at all still means no
        default routes."""
        doc = [self._brief_step()]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("narrative route", report["refusal"]["message"])

    def test_the_bundle_limit_is_never_weakened_for_an_action_list_sources_list_wrapper(self):
        """A single `sources` list-wrapper action element contributing
        many descriptors at once still counts against the 25-artifact
        bundle cap exactly like that many separate elements would."""
        many_sources = [
            {"origin": "local", "sourceType": "local_paste", "uri": f"paste:bulk-{i}",
             "owner": "a@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": f"Bulk source number {i}."}
            for i in range(26)
        ]
        doc = [self._brief_step(), {"action": "add_source", "sources": many_sources}]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "BUNDLE_LIMIT_REACHED")
        ingest_steps = [s for s in report["steps"] if s["action"] == "source.ingest"]
        self.assertEqual(len(ingest_steps), 25, "exactly the cap ingested before the 26th is refused")


if __name__ == "__main__":
    unittest.main()
