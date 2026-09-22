"""Regression tests for FR-M365-4 ("the skill detects and surfaces
source changes since the prior rehearsal") --
`engine/rehearsal._source_changes_since_last_rehearsal` /
`run_rehearsal`'s new `sourceChanges` result field.

Compatibility gap this closes: `rehearsal.run_rehearsal` never reported
anything about source drift at all -- a source modified (or added, or
removed) between two rehearsals was invisible to the public rehearsal
action, even though FR-M365-4's acceptance criterion ("given a source
modified since the last rehearsal ... it is flagged as changed") is a
documented requirement.

Contract:
- A workspace's *first* rehearsal ever reports no changes (there is no
  prior snapshot yet to diff against) -- it only establishes the
  baseline `uri -> contentHash` snapshot.
- A source ingested after that baseline is `"added"`.
- A source whose `uri` is re-ingested with different content (creating a
  new `SourceArtifact` id superseding the old one, per FR-SRC-5) is
  `"changed"` -- diffed by `uri`, never by the underlying (unstable
  across a content change) source id.
- A source retired since the last rehearsal (and not superseded by
  anything) is `"removed"`.
- `run-scenario`'s public `rehearse`/`set_rehearsal_timing` actions
  surface this identical `sourceChanges` field in the report.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import (
    REPO_ROOT, cleanup, ingest_paste, make_workspace, new_root, new_store, persistence, rehearsal, scenario,
)

BIN = str(REPO_ROOT / "bin" / "throughline")


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


class SourceChangesSinceRehearsalUnitTests(unittest.TestCase):
    """Direct, in-process coverage of `run_rehearsal`'s new
    `sourceChanges` field."""

    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_the_first_rehearsal_ever_reports_no_source_changes(self):
        ws, brief, conn = make_workspace(self.store)
        ingest_paste(conn, self.store, ws.id, "Some evidence text.", uri="paste:one")
        result = rehearsal.run_rehearsal(conn, ws.id, {}, actor="T")
        self.assertEqual(result["sourceChanges"], [])
        conn.close()

    def test_the_first_rehearsal_still_establishes_a_baseline_for_the_next_one(self):
        ws, brief, conn = make_workspace(self.store)
        ingest_paste(conn, self.store, ws.id, "Some evidence text.", uri="paste:one")
        rehearsal.run_rehearsal(conn, ws.id, {}, actor="T")
        # A second rehearsal with nothing having changed reports no changes.
        result = rehearsal.run_rehearsal(conn, ws.id, {}, actor="T")
        self.assertEqual(result["sourceChanges"], [])
        conn.close()

    def test_a_source_added_after_the_baseline_is_reported_as_added(self):
        ws, brief, conn = make_workspace(self.store)
        ingest_paste(conn, self.store, ws.id, "First source.", uri="paste:one")
        rehearsal.run_rehearsal(conn, ws.id, {}, actor="T")  # establishes the baseline

        ingest_paste(conn, self.store, ws.id, "Second source, added later.", uri="paste:two")
        result = rehearsal.run_rehearsal(conn, ws.id, {}, actor="T")

        self.assertEqual(len(result["sourceChanges"]), 1)
        self.assertEqual(result["sourceChanges"][0]["uri"], "paste:two")
        self.assertEqual(result["sourceChanges"][0]["status"], "added")
        conn.close()

    def test_a_source_re_ingested_with_different_content_is_reported_as_changed(self):
        ws, brief, conn = make_workspace(self.store)
        ingest_paste(conn, self.store, ws.id, "Original content.", uri="paste:one")
        rehearsal.run_rehearsal(conn, ws.id, {}, actor="T")  # establishes the baseline

        # Re-ingesting the *same* uri with different content mints a new
        # SourceArtifact id and marks the old one STALE/superseded -- the
        # diff is by uri, so this is "changed", never "removed"+"added".
        ingest_paste(conn, self.store, ws.id, "Completely different content now.", uri="paste:one")
        result = rehearsal.run_rehearsal(conn, ws.id, {}, actor="T")

        self.assertEqual(len(result["sourceChanges"]), 1)
        self.assertEqual(result["sourceChanges"][0]["uri"], "paste:one")
        self.assertEqual(result["sourceChanges"][0]["status"], "changed")
        conn.close()

    def test_a_retired_source_is_reported_as_removed(self):
        from engine import ingest as ingest_mod

        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Will be retired.", uri="paste:retire-me")
        rehearsal.run_rehearsal(conn, ws.id, {}, actor="T")  # establishes the baseline

        ingest_mod.retire_source(conn, ws.id, source.id, actor="T")
        result = rehearsal.run_rehearsal(conn, ws.id, {}, actor="T")

        self.assertEqual(len(result["sourceChanges"]), 1)
        self.assertEqual(result["sourceChanges"][0]["uri"], "paste:retire-me")
        self.assertEqual(result["sourceChanges"][0]["status"], "removed")
        conn.close()

    def test_a_stable_bundle_across_two_rehearsals_reports_nothing(self):
        ws, brief, conn = make_workspace(self.store)
        ingest_paste(conn, self.store, ws.id, "Stable content.", uri="paste:stable")
        rehearsal.run_rehearsal(conn, ws.id, {}, actor="T")
        result = rehearsal.run_rehearsal(conn, ws.id, {}, actor="T")
        self.assertEqual(result["sourceChanges"], [])
        conn.close()


class SourceChangesScenarioEndToEndTests(unittest.TestCase):
    """End-to-end coverage: the public `rehearse`/`set_rehearsal_timing`
    action surfaces `sourceChanges` identically through `run_scenario`
    and across sequential (resumed) scenario calls."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _brief_step(self) -> dict:
        return {
            "action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
            "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident",
        }

    def _source_step(self, uri: str, content: str) -> dict:
        return {
            "action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": uri,
            "owner": "a@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
            "version": "v1", "content": content,
        }

    def test_a_first_rehearsal_via_run_scenario_reports_no_source_changes(self):
        doc = [
            self._brief_step(),
            self._source_step("paste:one", "First source content."),
            {"action": "rehearse", "slideRole": "HOOK", "seconds": 10},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertIn("rehearsal", report)
        self.assertEqual(report["rehearsal"]["sourceChanges"], [])

    def test_a_second_sequential_call_reports_a_source_added_since_the_first_rehearsal(self):
        store = persistence.Store(root=self.root / "ws")
        first_doc = [
            self._brief_step(),
            self._source_step("paste:one", "First source content."),
            {"action": "rehearse", "slideRole": "HOOK", "seconds": 10},
        ]
        scenario.run_scenario(store, first_doc, self.root / "r1")

        second_doc = [
            self._source_step("paste:two", "Second source, added later."),
            {"action": "rehearse", "slideRole": "HOOK", "seconds": 12},
        ]
        second_report = scenario.run_scenario(store, second_doc, self.root / "r2")

        self.assertTrue(second_report["workspaceResumed"])
        changes = second_report["rehearsal"]["sourceChanges"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["uri"], "paste:two")
        self.assertEqual(changes[0]["status"], "added")

    def test_source_changes_surface_through_the_cli_subprocess_too(self):
        workspace_dir = self.root / "cli-ws"
        first_doc = [
            self._brief_step(),
            self._source_step("paste:one", "First source content."),
            {"action": "rehearse", "slideRole": "HOOK", "seconds": 10},
        ]
        first_path = self.root / "first.json"
        first_path.write_text(json.dumps(first_doc))
        first = _run_cli("run-scenario", "--scenario", str(first_path), "--workspace", str(workspace_dir))
        self.assertEqual(first.returncode, 0, first.stderr)

        second_doc = [
            self._source_step("paste:two", "Second source, added later."),
            {"action": "rehearse", "slideRole": "HOOK", "seconds": 12},
        ]
        second_path = self.root / "second.json"
        second_path.write_text(json.dumps(second_doc))
        second = _run_cli("run-scenario", "--scenario", str(second_path), "--workspace", str(workspace_dir))
        self.assertEqual(second.returncode, 0, second.stderr)
        envelope = json.loads(second.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        changes = envelope["data"]["rehearsal"]["sourceChanges"]
        self.assertEqual([c["uri"] for c in changes], ["paste:two"])
        self.assertEqual(changes[0]["status"], "added")


if __name__ == "__main__":
    unittest.main()
