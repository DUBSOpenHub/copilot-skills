"""Regression tests for idempotent workspace resume across sequential
`run-scenario` calls against the same explicit workspace
(`engine/scenario._open_or_resume_workspace`): a later call resolving to
the identical workspace root (identity/path match) resumes that
workspace instead of trying (and always losing) to open a brand-new one
on top of it.

Compatibility gap this closes: every call to `run_scenario` unconditionally
called `workspace_mod.create_workspace`, which always attempts to mint a
*new* workspace id -- so a second call against a root that already had an
active workspace always lost the atomic lock race and was refused
`WORKSPACE_ALREADY_ACTIVE`, even though the caller's intent (the same
explicit `--workspace <dir>`) was obviously to continue that same session.
State (sources, claims, ...) could never accumulate across calls.

Contract:
- A later call whose resolved store root already has an active workspace
  resumes it (`workspaceResumed: true` in the report), reusing the
  identical `workspaceId`/`briefId` -- never creating a second workspace,
  never refusing `WORKSPACE_ALREADY_ACTIVE`.
- Sources ingested by different calls accumulate into the one curated
  bundle (still capped at the 25-artifact limit across all calls
  combined -- NFR-2/FR-SRC's bundle limit is not weakened by resuming).
- A later call's own conflict-resolution/gate/export steps work exactly
  as they would in a first call -- resuming doesn't special-case or skip
  any of the normal per-call walk.
- `workspace_mod.create_workspace` itself (used directly by `workspace
  new` and by this module's own fallback when no workspace is active yet)
  is completely unchanged: it still refuses `WORKSPACE_ALREADY_ACTIVE`
  for a genuinely new open attempt against an already-locked root -- this
  cycle only changes `run_scenario`'s own workspace-opening step, not the
  underlying exclusivity primitive.
- A resumed call's own domain refusals (e.g. missing routes) are recorded
  exactly like a first call's would be, and do not roll back whatever the
  resumed session had already durably persisted before them (see
  `tests/test_candidate_persistence_on_refusal.py` for the narrative-
  specific case of this).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import EngineError, REPO_ROOT, cleanup, models, new_root, persistence, scenario, workspace_mod

BIN = str(REPO_ROOT / "bin" / "throughline")


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _brief_step(**overrides) -> dict:
    payload = {
        "action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
        "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident",
    }
    payload.update(overrides)
    return payload


def _source_step(uri: str, content: str = "Some evidence content.") -> dict:
    return {
        "action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": uri,
        "owner": "a@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
        "version": "v1", "content": content,
    }


class DirectResumeUnitTests(unittest.TestCase):
    """Direct, in-process coverage of `_open_or_resume_workspace` itself."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_first_call_opens_a_fresh_workspace(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, [_brief_step()], self.root / "report")
        self.assertFalse(report["workspaceResumed"])
        self.assertTrue(report["workspaceId"])

    def test_second_call_against_the_same_store_resumes_the_first_workspace(self):
        store = persistence.Store(root=self.root / "ws")
        first = scenario.run_scenario(store, [_brief_step()], self.root / "report-1")
        second = scenario.run_scenario(store, [_source_step("paste:only")], self.root / "report-2")
        self.assertTrue(second["workspaceResumed"])
        self.assertEqual(second["workspaceId"], first["workspaceId"])
        self.assertEqual(second["briefId"], first["briefId"])

    def test_a_third_and_later_call_keeps_resuming_the_identical_workspace(self):
        store = persistence.Store(root=self.root / "ws")
        first = scenario.run_scenario(store, [_brief_step()], self.root / "r1")
        second = scenario.run_scenario(store, [_source_step("paste:a")], self.root / "r2")
        third = scenario.run_scenario(store, [_source_step("paste:b")], self.root / "r3")
        self.assertEqual({first["workspaceId"], second["workspaceId"], third["workspaceId"]}, {first["workspaceId"]})
        self.assertTrue(second["workspaceResumed"])
        self.assertTrue(third["workspaceResumed"])

    def test_create_workspace_directly_still_refuses_a_genuinely_new_open_while_one_is_active(self):
        """NFR-2's exclusivity is unaffected for direct callers (e.g.
        `workspace new`) -- only `run_scenario`'s own opening step gained
        the resume shortcut."""
        store = persistence.Store(root=self.root / "ws")
        scenario.run_scenario(store, [_brief_step()], self.root / "r1")
        with self.assertRaises(EngineError) as ctx:
            workspace_mod.create_workspace(store, actor="Someone Else")
        self.assertEqual(ctx.exception.code, "WORKSPACE_ALREADY_ACTIVE")

    def test_two_independent_store_roots_never_resume_each_other(self):
        """Resume is strictly identity/path-scoped -- a different explicit
        workspace root is always a brand-new workspace, never confused
        with an unrelated one."""
        store_a = persistence.Store(root=self.root / "ws-a")
        store_b = persistence.Store(root=self.root / "ws-b")
        report_a = scenario.run_scenario(store_a, [_brief_step()], self.root / "ra")
        report_b = scenario.run_scenario(store_b, [_brief_step()], self.root / "rb")
        self.assertFalse(report_a["workspaceResumed"])
        self.assertFalse(report_b["workspaceResumed"])
        self.assertNotEqual(report_a["workspaceId"], report_b["workspaceId"])

    def test_a_brief_supplied_on_a_resumed_call_partially_updates_the_existing_brief(self):
        store = persistence.Store(root=self.root / "ws")
        scenario.run_scenario(store, [_brief_step(takeaway="Original takeaway")], self.root / "r1")
        second = scenario.run_scenario(
            store, [_brief_step(takeaway="Updated takeaway", audience="Updated audience")], self.root / "r2",
        )
        self.assertTrue(second["workspaceResumed"])
        conn = store.connect(second["workspaceId"])
        try:
            brief = persistence.get(conn, "brief", second["briefId"], models.TalkBrief)
        finally:
            conn.close()
        self.assertEqual(brief.takeaway, "Updated takeaway")
        self.assertEqual(brief.audience, "Updated audience")


class SourceAccumulationTests(unittest.TestCase):
    """The literal "accumulate sources in the single curated bundle"
    acceptance requirement."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_sources_from_three_separate_calls_all_land_in_the_one_bundle(self):
        store = persistence.Store(root=self.root / "ws")
        report1 = scenario.run_scenario(store, [_brief_step(), _source_step("paste:one")], self.root / "r1")
        scenario.run_scenario(store, [_source_step("paste:two")], self.root / "r2")
        scenario.run_scenario(store, [_source_step("paste:three")], self.root / "r3")

        conn = store.connect(report1["workspaceId"])
        try:
            sources = persistence.list_all(conn, "source", report1["workspaceId"], models.SourceArtifact)
        finally:
            conn.close()
        self.assertEqual(sorted(s.uri for s in sources), ["paste:one", "paste:three", "paste:two"])

    def test_the_bundle_limit_still_applies_cumulatively_across_calls(self):
        """Resuming never resets or bypasses the 25-artifact cap -- it is
        enforced against the *accumulated* bundle, exactly as if all the
        sources had been supplied in one call."""
        store = persistence.Store(root=self.root / "ws")
        first_doc = [_brief_step()] + [_source_step(f"paste:bulk-{i}") for i in range(20)]
        scenario.run_scenario(store, first_doc, self.root / "r1")

        second_doc = [_source_step(f"paste:more-{i}") for i in range(5)]  # brings the total to exactly 25
        second_report = scenario.run_scenario(store, second_doc, self.root / "r2")
        # All 5 ingest cleanly (reaching exactly the 25-artifact cap);
        # whatever unrelated, later refusal the walk reaches (no routes
        # were supplied) is irrelevant to source ingestion under test here.
        self.assertEqual(len([s for s in second_report["steps"] if s["action"] == "source.ingest"]), 5)

        third_report = scenario.run_scenario(store, [_source_step("paste:the-26th")], self.root / "r3")
        self.assertEqual(third_report["refusal"]["code"], "BUNDLE_LIMIT_REACHED")


class ConflictResolutionOnAResumedCallTests(unittest.TestCase):
    """"permit later conflict-resolution steps": a resumed call's own
    `conflictDecisions`/`resolve_conflict` steps work exactly as a first
    call's would -- proving conflict handling isn't disabled or altered by
    the resume path."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_a_conflict_created_and_resolved_within_a_resumed_call_completes_normally(self):
        store = persistence.Store(root=self.root / "ws")
        scenario.run_scenario(store, [_brief_step()], self.root / "r1")

        # A claim referencing two evidence atoms with *different*
        # sensitivity labels auto-creates an OPEN sensitivity-conflict
        # card (`claims._scan_sensitivity_conflicts`, run automatically by
        # `link_evidence` -- no explicit `--contradicts` needed) -- all
        # within this one resumed call, proving `conflictDecisions`
        # resolution is fully functional in a resumed session, not just a
        # first one.
        doc = [
            _source_step("paste:conflict-a", content="A confidential figure worth citing."),
            {**_source_step("paste:conflict-b", content="A public figure worth citing."), "sensitivityLabel": "Public"},
            {"action": "propose_claim", "type": "factual", "text": "A cited figure.",
             "evidenceLocators": ["paste:conflict-a", "paste:conflict-b"]},
            {"action": "resolve_conflict", "claimIndex": 0, "decision": "Reviewed both labels; approved for this talk."},
        ]
        # The first source's sensitivity label is set separately since
        # `_source_step` doesn't take one by default.
        doc[0] = {**doc[0], "sensitivityLabel": "Confidential"}

        report = scenario.run_scenario(store, doc, self.root / "r2")
        self.assertTrue(report["workspaceResumed"])

        conn = store.connect(report["workspaceId"])
        try:
            conflicts = persistence.list_all(conn, "conflict", report["workspaceId"], models.ConflictCard)
        finally:
            conn.close()
        self.assertEqual(len(conflicts), 1, "the sensitivity-label conflict was created")
        self.assertEqual(conflicts[0].status, models.ConflictStatus.RESOLVED.value)
        self.assertEqual(conflicts[0].decision, "Reviewed both labels; approved for this talk.")



class SubprocessResumeTests(unittest.TestCase):
    """End-to-end (subprocess) coverage of the same contract through the
    public CLI entry point."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_sequential_cli_invocations_against_the_same_workspace_dir_resume_and_accumulate(self):
        workspace_dir = self.root / "workspace-dir"

        first_doc = [_brief_step(), _source_step("paste:cli-one")]
        first_path = self.root / "first.json"
        first_path.write_text(json.dumps(first_doc))
        first = _run_cli("run-scenario", "--scenario", str(first_path), "--workspace", str(workspace_dir))
        self.assertEqual(first.returncode, 0, first.stderr)
        first_envelope = json.loads(first.stdout)
        self.assertFalse(first_envelope["data"]["workspaceResumed"])

        second_doc = [_source_step("paste:cli-two")]
        second_path = self.root / "second.json"
        second_path.write_text(json.dumps(second_doc))
        second = _run_cli("run-scenario", "--scenario", str(second_path), "--workspace", str(workspace_dir))
        self.assertEqual(second.returncode, 0, second.stderr)
        second_envelope = json.loads(second.stdout)
        self.assertTrue(second_envelope["ok"], second_envelope.get("error"))
        self.assertTrue(second_envelope["data"]["workspaceResumed"])
        self.assertEqual(second_envelope["workspace_id"], first_envelope["workspace_id"])

        ingest_steps = [s for s in second_envelope["data"]["steps"] if s["action"] == "source.ingest"]
        self.assertEqual([s["uri"] for s in ingest_steps], ["paste:cli-two"])


if __name__ == "__main__":
    unittest.main()
