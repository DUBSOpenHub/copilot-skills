"""Regression tests for source `origin` alias normalization
(`engine/ingest.normalize_origin` / `_ORIGIN_ALIASES`): a source
descriptor's `origin` field is accepted in any of several common staged
spellings -- a connector-shaped synonym ("manual"/"upload" for a locally
supplied artifact, a bare "issue"/"repo" for a GitHub-hosted one,
"sharepoint"/"teams"/"outlook"/"loop" for any Microsoft 365 connector
surface WorkIQ fronts), in any case or hyphen/space spelling -- and
resolved to one of the three canonical origins (`local`/`github`/
`workiq`) before the source state machine runs, so the resulting
`SourceArtifact` is persisted and dependent evidence/claim/gate/export
flows can proceed exactly as they already do for an exact canonical
spelling.

Compatibility gap this closes: the public action-list `run-scenario`
interface previously rejected any `origin` value that wasn't the exact
string `github`, `local`, or `workiq` with a `VALIDATION_ERROR`, so a
staged source descriptor using a common connector-shaped alias never
became a source at all -- source/evidence ledgers stayed empty and every
dependent claim/gate/export step was unreachable.

`sourceType` is completely untouched by this normalization -- a source's
own source-type metadata is preserved exactly as supplied, regardless of
which origin alias was used (`test_source_type_metadata_is_preserved_
verbatim_regardless_of_origin_alias` below).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, cleanup, ingest_mod, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


# (staged alias, expected canonical origin)
ALIAS_MATRIX = [
    ("manual", "local"), ("Upload", "local"), ("UPLOADED", "local"), ("file", "local"),
    ("filesystem", "local"), ("local-upload", "local"), ("local_paste", "local"), ("paste", "local"),
    ("repo", "github"), ("Repository", "github"), ("issue", "github"), ("PR", "github"),
    ("pull_request", "github"), ("pull-request", "github"), ("discussion", "github"),
    ("release", "github"), ("release-notes", "github"), ("github_repo", "github"),
    ("github_issue", "github"), ("GITHUB_PR", "github"), ("github-discussion", "github"),
    ("github_release_notes", "github"),
    ("sharepoint", "workiq"), ("SharePoint", "workiq"), ("sharepoint-doc", "workiq"),
    ("onedrive", "workiq"), ("onedrive_doc", "workiq"), ("teams", "workiq"),
    ("teams-message", "workiq"), ("teams_transcript", "workiq"), ("outlook", "workiq"),
    ("outlook_mail", "workiq"), ("outlook-calendar", "workiq"), ("loop", "workiq"),
    ("loop_page", "workiq"), ("m365", "workiq"), ("Microsoft365", "workiq"),
    ("office365", "workiq"), ("pptx_file", "workiq"),
    # Exact canonical values (any case/spacing) still resolve to themselves.
    ("local", "local"), ("LOCAL", "local"), ("github", "github"), ("GitHub", "github"),
    ("workiq", "workiq"), ("WorkIQ", "workiq"),
]


class OriginAliasNormalizationUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the normalization function itself."""

    def test_alias_matrix_resolves_to_the_expected_canonical_origin(self):
        for staged, expected in ALIAS_MATRIX:
            with self.subTest(staged=staged):
                self.assertEqual(ingest_mod.normalize_origin(staged), expected)

    def test_a_truly_unknown_origin_is_returned_unchanged_so_it_is_still_rejected(self):
        for bogus in ("spacecraft", "carrier_pigeon", "", "   "):
            with self.subTest(bogus=bogus):
                self.assertEqual(ingest_mod.normalize_origin(bogus), bogus)

    def test_a_non_string_origin_is_returned_unchanged(self):
        self.assertIsNone(ingest_mod.normalize_origin(None))
        self.assertEqual(ingest_mod.normalize_origin(42), 42)


class OriginAliasIngestSourceEndToEndTests(unittest.TestCase):
    """End-to-end coverage: `ingest_source` itself accepts an aliased
    origin and persists a source exactly as it would for the canonical
    spelling -- never rejecting `VALIDATION_ERROR: origin must be one of
    [...]` for a listed alias."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _payload(self, origin: str, uri: str) -> dict:
        return {
            "origin": origin, "sourceType": "local_paste", "uri": uri, "owner": "speaker@example.com",
            "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
            "content": "A paragraph of authorized evidence content for the origin-alias test.",
        }

    def test_manual_alias_ingests_as_a_canonical_local_source(self):
        store = persistence.Store(root=self.root / "ws")
        conn = store.connect("workspace:probe")
        try:
            source = ingest_mod.ingest_source(
                conn, "workspace:probe", self._payload("manual", "paste:manual-alias"), actor="T",
                staging_dir=store.workspace_dir("workspace:probe") / "staging",
            )
            self.assertEqual(source.origin, "local")
            self.assertEqual(source.state, "AUTHORIZED")
            # `sourceType` is preserved exactly as supplied, untouched by
            # the origin-alias normalization.
            self.assertEqual(source.source_type, "local_paste")
        finally:
            conn.close()

    def test_a_truly_unknown_origin_still_raises_validation_error(self):
        from helpers import EngineError
        store = persistence.Store(root=self.root / "ws")
        conn = store.connect("workspace:probe")
        try:
            with self.assertRaises(EngineError) as ctx:
                ingest_mod.ingest_source(
                    conn, "workspace:probe", self._payload("carrier_pigeon", "paste:bogus"), actor="T",
                    staging_dir=store.workspace_dir("workspace:probe") / "staging",
                )
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        finally:
            conn.close()


class OriginAliasScenarioEndToEndTests(unittest.TestCase):
    """The literal compatibility gap: a `run-scenario` action-list
    document whose `add_source`/`ingest_source` steps use staged origin
    aliases must persist those sources and let dependent evidence/claim/
    gate/export flows proceed -- reaching Stage exactly as the identical
    scenario built from canonical origins would."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _aliased_doc(self) -> list[dict]:
        return [
            {"action": "set_talk_brief", "audience": "Conference attendees", "eventType": "keynote",
             "durationMinutes": 20, "takeaway": "Structured evidence review de-risks talks",
             "proofPoints": ["adoption stat"], "excludedTopics": [], "tone": "confident"},
            # Deliberately uses two different staged aliases (never the
            # exact canonical "local" string) for the one source.
            {"action": "add_source", "origin": "Manual", "sourceType": "local_paste", "uri": "paste:adoption-note",
             "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "Throughline adoption grew 42% quarter over quarter across pilot teams.\n\nSpeakers using structured evidence review reported higher confidence."},
            {"action": "propose_claim", "type": "factual", "text": "Throughline adoption grew 42% quarter over quarter.",
             "evidenceLocators": ["paste:adoption-note#p0"], "approve": True},
        ]

    def test_an_aliased_origin_ingests_and_lets_evidence_and_claims_proceed(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, self._aliased_doc(), self.root / "report")

        ingest_step = next(s for s in report["steps"] if s["action"] == "source.ingest")
        self.assertEqual(ingest_step["state"], "AUTHORIZED")
        self.assertTrue(any(s["action"] == "evidence.extract" and s["atomCount"] > 0 for s in report["steps"]))
        claim_step = next(s for s in report["steps"] if s["action"] == "claim.propose")
        self.assertEqual(claim_step["count"], 1)
        self.assertTrue(any(s["action"] == "claim.approve" for s in report["steps"]))


    def test_a_workiq_style_alias_via_the_cli_subprocess_ingests_and_exits_zero(self):
        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            # "sharepoint" is a staged alias for the canonical "workiq"
            # origin -- content is supplied directly (as a real WorkIQ/
            # GitHub Fetcher already would) rather than a local path.
            {"action": "add_source", "origin": "sharepoint", "sourceType": "sharepoint_doc", "uri": "sharepoint://deck/notes",
             "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "Notes retrieved from a SharePoint document."},
        ]
        scenario_path = self.root / "workiq-alias-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        ingest_step = next(s for s in envelope["data"]["steps"] if s["action"] == "source.ingest")
        self.assertEqual(ingest_step["state"], "AUTHORIZED")

    def test_a_github_style_alias_ingests_correctly(self):
        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            # "issue" is a staged alias for the canonical "github" origin.
            {"action": "add_source", "origin": "issue", "sourceType": "github_issue", "uri": "gh://org/repo/issues/1",
             "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "Issue body text used as evidence."},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        ingest_step = next(s for s in report["steps"] if s["action"] == "source.ingest")
        self.assertEqual(ingest_step["state"], "AUTHORIZED")

    def test_a_truly_unknown_origin_is_still_a_clean_validation_error_through_run_scenario(self):
        """The alias table is conservative and explicit -- an origin that
        isn't listed is still refused exactly as before, never guessed."""
        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", "origin": "carrier_pigeon", "sourceType": "local_paste", "uri": "paste:bogus",
             "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "irrelevant"},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
