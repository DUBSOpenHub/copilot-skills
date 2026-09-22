"""Regression tests for sequential, multi-origin source accumulation
into one curated bundle, and for the metadata/report-exposure gaps
around it (`engine/ingest.ingest_source`, `engine/scenario._run_steps`'s
per-source step reporting, and `engine/scenario._attach_workspace_state`'s
`report["sources"]`).

Compatibility gap this closes: explicitly staged local, uploaded,
GitHub, and WorkIQ sources -- added across separate, sequential
`run-scenario` calls against the same resumed workspace, mirroring how a
real speaker builds a bundle incrementally -- previously left the
accumulated ledger's full metadata undiscoverable from the report (only
a thin `{"uri", "state"}` step existed), and one spacing/punctuation
variant of the canonical "workiq" origin word itself (e.g. "Work IQ")
was incorrectly refused as an unrecognized origin even though every
other canonical-origin spelling already resolved.

Contract:
- Local (`origin: local`), uploaded (`origin: upload`, an existing alias
  for `local`), GitHub (`origin: github`), and WorkIQ (`origin: workiq`,
  including internally spaced/hyphenated spellings of the word itself)
  sources all ingest successfully and accumulate into the *one* curated
  bundle, whether staged in one call or across several sequential calls
  against the same resumed workspace.
- `report["sources"]` (attached regardless of how the current call's own
  walk ends) always reflects the *full*, reloaded accumulated ledger --
  not just whichever sources this particular call itself added -- with
  each entry's canonical origin/sourceType/owner/permissionState/
  sensitivityLabel metadata intact.
- Re-adding the identical `uri` never creates a duplicate ledger entry
  (the pre-existing supersession contract) and the bundle limit is still
  enforced cumulatively across origins.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, cleanup, ingest_mod, models, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _brief_step(**overrides) -> dict:
    payload = {
        "action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
        "takeaway": "Provenance beats persuasion", "proofPoints": ["adoption stat"],
        "excludedTopics": [], "tone": "confident",
    }
    payload.update(overrides)
    return payload


def _local_source(uri="paste:local-notes") -> dict:
    return {
        "action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": uri,
        "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
        "sensitivityLabel": "Internal", "version": "v1",
        "content": "Locally authored speaker notes worth citing in the talk.",
    }


def _uploaded_source(uri=None) -> dict:
    # "upload" is an existing, conservative alias for the canonical
    # "local" origin (a caller describing a manually-supplied artifact).
    # `local_upload` (unlike `local_paste`) independently re-reads the
    # actual file from disk (FR-SRC-4) -- `uri` must be a real, readable
    # path, so this points at the repository's own existing local-fixture
    # file rather than an inline `content` string (which `local_upload`
    # ignores entirely).
    return {
        "action": "add_source", "origin": "upload", "sourceType": "local_upload",
        "uri": uri or str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt"),
        "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
        "sensitivityLabel": "Public", "version": "v1",
    }


def _github_source(uri="https://github.com/example-org/throughline-pilot/releases/tag/v1.4.0") -> dict:
    payload = json.loads((REPO_ROOT / "tests" / "fixtures" / "github" / "release_notes.json").read_text())
    payload["uri"] = uri
    return {"action": "add_source", **payload}


def _workiq_source(uri="https://contoso.sharepoint.com/sites/talks/Shared%20Documents/adoption-report.docx", origin="workiq") -> dict:
    payload = json.loads((REPO_ROOT / "tests" / "fixtures" / "workiq" / "sharepoint_doc.json").read_text())
    payload["uri"] = uri
    payload["origin"] = origin
    return {"action": "add_source", **payload}


class WorkiqOriginSpacingSquashUnitTests(unittest.TestCase):
    """Direct coverage of the origin-squashing fix
    (`engine/ingest._ORIGIN_ALIASES_SQUASHED`'s new canonical
    self-mapping): every canonical origin word itself resolves regardless
    of internal spacing/hyphenation, not just its listed connector-shaped
    aliases."""

    def test_a_spaced_workiq_spelling_resolves_to_the_canonical_origin(self):
        self.assertEqual(ingest_mod.normalize_origin("Work IQ"), "workiq")
        self.assertEqual(ingest_mod.normalize_origin("work iq"), "workiq")

    def test_a_hyphenated_workiq_spelling_resolves_to_the_canonical_origin(self):
        self.assertEqual(ingest_mod.normalize_origin("work-iq"), "workiq")
        self.assertEqual(ingest_mod.normalize_origin("WORK-IQ"), "workiq")

    def test_spaced_and_hyphenated_github_and_local_still_resolve_too(self):
        self.assertEqual(ingest_mod.normalize_origin("git hub"), "github")
        self.assertEqual(ingest_mod.normalize_origin("git-hub"), "github")

    def test_a_workiq_style_source_ingests_through_ingest_source_directly(self):
        store = persistence.Store(root=new_root())
        try:
            conn = store.connect("workspace:probe")
            try:
                payload = {k: v for k, v in _workiq_source().items() if k != "action"}
                payload["origin"] = "Work IQ"
                source = ingest_mod.ingest_source(
                    conn, "workspace:probe", payload, actor="T",
                    staging_dir=store.workspace_dir("workspace:probe") / "staging",
                )
                self.assertEqual(source.origin, "workiq")
                self.assertEqual(source.state, "AUTHORIZED")
            finally:
                conn.close()
        finally:
            cleanup(store.root)


class SequentialMultiOriginAccumulationTests(unittest.TestCase):
    """The literal acceptance scenario: local, uploaded, GitHub, and
    WorkIQ sources, added across separate sequential calls, all land in
    the one accumulated ledger."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_four_distinct_origin_sources_added_sequentially_all_accumulate(self):
        store = persistence.Store(root=self.root / "ws")

        first = scenario.run_scenario(store, [_brief_step(), _local_source()], self.root / "r1")
        self.assertFalse(first["workspaceResumed"])
        second = scenario.run_scenario(store, [_uploaded_source()], self.root / "r2")
        self.assertTrue(second["workspaceResumed"])
        third = scenario.run_scenario(store, [_github_source()], self.root / "r3")
        self.assertTrue(third["workspaceResumed"])
        fourth = scenario.run_scenario(store, [_workiq_source(origin="Work IQ")], self.root / "r4")
        self.assertTrue(fourth["workspaceResumed"])

        # Every ingest step along the way reported AUTHORIZED -- no
        # sequential addition was refused.
        for report in (first, second, third, fourth):
            ingest_steps = [s for s in report["steps"] if s["action"] == "source.ingest"]
            self.assertEqual(len(ingest_steps), 1, report)
            self.assertEqual(ingest_steps[0]["state"], "AUTHORIZED")

        # The final report's `sources` ledger is reloaded fresh and shows
        # all four, across all three origins, not just this last call's
        # own addition.
        origins = sorted(s["origin"] for s in fourth["sources"])
        self.assertEqual(origins, ["github", "local", "local", "workiq"])
        self.assertEqual(len(fourth["sources"]), 4)

        # Cross-checked directly against the persisted ledger too.
        conn = store.connect(fourth["workspaceId"])
        try:
            sources = persistence.list_all(conn, "source", fourth["workspaceId"], models.SourceArtifact)
        finally:
            conn.close()
        self.assertEqual(len(sources), 4)

    def test_all_four_origins_in_a_single_call_also_accumulate(self):
        doc = [_brief_step(), _local_source(), _uploaded_source(), _github_source(), _workiq_source()]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        ingest_steps = [s for s in report["steps"] if s["action"] == "source.ingest"]
        self.assertEqual(len(ingest_steps), 4)
        self.assertTrue(all(s["state"] == "AUTHORIZED" for s in ingest_steps))
        self.assertEqual(len(report["sources"]), 4)

    def test_source_metadata_is_preserved_across_origins_in_the_report(self):
        doc = [_brief_step(), _local_source(), _uploaded_source(), _github_source(), _workiq_source()]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        by_uri = {s["uri"]: s for s in report["sources"]}
        local_entry = by_uri["paste:local-notes"]
        self.assertEqual(local_entry["origin"], "local")
        self.assertEqual(local_entry["source_type"], "local_paste")
        self.assertEqual(local_entry["owner"], "speaker@example.com")
        self.assertEqual(local_entry["permission_state"], "authorized")
        self.assertEqual(local_entry["sensitivity_label"], "Internal")

        uploaded_entry = next(s for s in report["sources"] if s["source_type"] == "local_upload")
        self.assertEqual(uploaded_entry["origin"], "local")

        github_entry = next(s for s in report["sources"] if s["origin"] == "github")
        self.assertEqual(github_entry["source_type"], "github_release_notes")

        workiq_entry = next(s for s in report["sources"] if s["origin"] == "workiq")
        self.assertEqual(workiq_entry["source_type"], "sharepoint_doc")

        # The per-step ingest entry also carries the richer metadata now
        # (not just uri/state).
        local_step = next(s for s in report["steps"] if s["action"] == "source.ingest" and s["uri"] == "paste:local-notes")
        self.assertEqual(local_step["origin"], "local")
        self.assertEqual(local_step["sensitivityLabel"], "Internal")

    def test_a_workiq_source_participates_in_rehearsal_change_detection(self):
        """FR-M365-4 change detection composes with multi-origin
        accumulation -- a WorkIQ source added after the first rehearsal
        is reported as `added`, exactly like a local one already is."""
        store = persistence.Store(root=self.root / "ws")
        scenario.run_scenario(store, [
            _brief_step(), _local_source(), {"action": "rehearse"},
        ], self.root / "r1")

        second = scenario.run_scenario(store, [
            _workiq_source(), {"action": "rehearse"},
        ], self.root / "r2")

        changes = second["rehearsal"]["sourceChanges"]
        self.assertEqual(len(changes), 1)
        self.assertTrue(changes[0]["uri"].endswith("adoption-report.docx"))
        self.assertEqual(changes[0]["status"], "added")

    def test_re_adding_the_identical_uri_supersedes_rather_than_duplicates(self):
        store = persistence.Store(root=self.root / "ws")
        scenario.run_scenario(store, [_brief_step(), _local_source(uri="paste:stable")], self.root / "r1")
        report = scenario.run_scenario(
            store, [{**_local_source(uri="paste:stable"), "content": "Updated content."}], self.root / "r2",
        )

        active_sources = [s for s in report["sources"] if s["state"] != "STALE"]
        self.assertEqual(len(active_sources), 1)
        self.assertEqual(active_sources[0]["uri"], "paste:stable")

    def test_the_bundle_limit_is_enforced_cumulatively_across_origins(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [_brief_step()] + [_local_source(uri=f"paste:bulk-{i}") for i in range(24)]
        first_report = scenario.run_scenario(store, doc, self.root / "r1")
        self.assertEqual(len(first_report["sources"]), 24)

        # The 25th source (any origin) still fits exactly at the cap...
        exactly_at_cap = scenario.run_scenario(store, [_github_source()], self.root / "r2")
        self.assertEqual(len(exactly_at_cap["sources"]), 25)

        # ...and a 26th, regardless of origin, is refused -- the cap is
        # never bypassed just because the new source is a different
        # origin than the ones already in the bundle.
        over_cap = scenario.run_scenario(store, [_workiq_source()], self.root / "r3")
        self.assertFalse(over_cap["ok"])
        self.assertEqual(over_cap["refusal"]["code"], "BUNDLE_LIMIT_REACHED")
        # Partial state is still fully observable despite the refusal.
        self.assertEqual(len(over_cap["sources"]), 25)

    def test_the_full_multi_origin_journey_also_works_through_the_cli_subprocess(self):
        doc = [_brief_step(), _local_source(), _uploaded_source(), _github_source(), _workiq_source()]
        scenario_path = self.root / "multi-origin-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))
        self.assertEqual(len(envelope["data"]["sources"]), 4)


if __name__ == "__main__":
    unittest.main()
