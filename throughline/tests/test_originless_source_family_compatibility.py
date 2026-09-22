"""Table-driven public compatibility suite for originless source
descriptors across every MVP-supported source family (Dark Factory
hardening cycle 9, acceptance pass 12: `engine/ingest.py`'s widened
allowlisted classifier).

Compatibility gap this closes: a source descriptor that omits `origin`
but is otherwise a genuine, MVP-supported descriptor -- a locally
uploaded document/image/transcript/email/data file (identified only by
its own recognized extension), a GitHub issue/PR/repository/file/
discussion form (identified only by its `sourceType` or a `github.com`/
API `uri`), or a WorkIQ/Microsoft 365 SharePoint/OneDrive/Teams/Outlook/
Loop form (identified only by its `sourceType` or a recognized Microsoft
URL/`workiq://` scheme) -- was previously refused `VALIDATION_ERROR:
origin must be one of [...]`, leaving every downstream source/evidence/
claim/gate/export flow unreachable.

Every case below is either a genuine acceptance (a recognized connector
is inferred and the source ingests) or a genuine, explicit refusal
(`VALIDATION_ERROR`) for an unknown/ambiguous descriptor or an outright
origin-vs-inferred-connector conflict -- never a silent guess. See
`engine/ingest.py`'s `_ORIGIN_ALIASES`/`_MIME_TYPE_ALIASES`/
`_LOCAL_FILE_EXTENSION_HINTS`/`infer_origin`/`_is_recognized_source_type`
for the underlying, conservative allowlists this suite pins.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import EngineError, REPO_ROOT, cleanup, ingest_mod, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")
LOCAL_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "local"


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


class _IngestHarness(unittest.TestCase):
    """Shared, isolated-workspace scaffolding for direct `ingest_source`
    calls -- every subclass below gets its own fresh store/connection."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")
        self.conn = self.store.connect("workspace:probe")
        self.staging_dir = self.store.workspace_dir("workspace:probe") / "staging"

    def tearDown(self):
        self.conn.close()
        cleanup(self.root)

    def _ingest(self, **payload) -> "ingest_mod.models.SourceArtifact":  # noqa: F821 - typing convenience only
        return ingest_mod.ingest_source(self.conn, "workspace:probe", payload, actor="T", staging_dir=self.staging_dir)


class OriginlessLocalFormatFamilyTests(_IngestHarness):
    """Local/manual/upload/file formats: markdown/text, PDF, PPTX, DOCX,
    VTT/transcript, EML/email, JSON, image -- every one a real,
    genuinely-parseable fixture file, referenced with no `origin` and no
    `sourceType` at all (the fully "originless and typeless" case)."""

    LOCAL_FILES = [
        "notes.md", "transcript.vtt", "data.json", "message.eml",
        "diagram.png", "report.docx", "report.pdf", "deck.pptx",
    ]

    def _payload(self, filename: str) -> dict:
        return {
            "uri": str(LOCAL_FIXTURES / filename), "owner": "speaker@example.com",
            "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
        }

    def test_every_recognized_local_format_ingests_with_no_origin_or_source_type(self):
        for filename in self.LOCAL_FILES:
            with self.subTest(filename=filename):
                source = self._ingest(**self._payload(filename))
                self.assertEqual(source.origin, "local")
                self.assertEqual(source.state, "AUTHORIZED")
                # `sourceType` is never fabricated beyond the one
                # sensible default for a wholly omitted descriptor.
                self.assertEqual(source.source_type, "local_upload")

    def test_original_public_source_type_spelling_is_preserved_verbatim(self):
        """When a caller *does* supply a `sourceType` (in any recognized
        public spelling, however unconventional), it is never rewritten
        -- `origin` is still inferred, but the ledger's own `sourceType`
        field remains exactly what was supplied."""
        matrix = [
            ("markdown", "notes.md"), ("md", "notes.md"), ("text", "notes.md"), ("txt", "notes.md"),
            ("pdf", "report.pdf"), ("PDF", "report.pdf"),
            ("pptx", "deck.pptx"), ("PPTX", "deck.pptx"),
            ("docx", "report.docx"), ("Docx", "report.docx"),
            ("vtt", "transcript.vtt"), ("transcript", "transcript.vtt"),
            ("eml", "message.eml"), ("email", "message.eml"),
            ("json", "data.json"),
            ("image", "diagram.png"), ("png", "diagram.png"),
        ]
        for source_type, filename in matrix:
            with self.subTest(sourceType=source_type, filename=filename):
                source = self._ingest(sourceType=source_type, **self._payload(filename))
                self.assertEqual(source.origin, "local")
                self.assertEqual(source.source_type, source_type)
                self.assertEqual(source.state, "AUTHORIZED")

    def test_camel_case_and_mime_type_source_type_spellings_also_ingest(self):
        matrix = [
            ("text/markdown", "notes.md"),
            ("application/pdf", "report.pdf"),
            ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "deck.pptx"),
            ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "report.docx"),
            ("message/rfc822", "message.eml"),
            ("application/json", "data.json"),
            ("image/png", "diagram.png"),
        ]
        for source_type, filename in matrix:
            with self.subTest(sourceType=source_type):
                source = self._ingest(sourceType=source_type, **self._payload(filename))
                self.assertEqual(source.origin, "local")
                self.assertEqual(source.source_type, source_type)

    def test_a_recognized_extension_on_a_bare_relative_or_absolute_path_infers_local(self):
        self.assertEqual(
            ingest_mod.infer_origin(None, str(LOCAL_FIXTURES / "notes.md")), "local",
        )


class OriginlessGithubFamilyTests(_IngestHarness):
    """GitHub issue, pull request, repository/file/discussion forms, and
    `github.com`/API URLs -- content supplied directly (as a real
    GitHubFetcher would), no local file needed."""

    def _payload(self, uri: str, **overrides) -> dict:
        payload = {
            "uri": uri, "owner": "example-org/throughline-pilot", "permissionState": "authorized",
            "aclSnapshot": "public-repo", "version": "v1", "content": "GitHub-sourced evidence text.",
        }
        payload.update(overrides)
        return payload

    def test_every_recognized_github_source_type_spelling_ingests_with_no_origin(self):
        matrix = [
            "github_issue", "github_pr", "github_repo", "github_discussion", "github_release_notes",
            "issue", "pr", "pull_request", "repo", "repository", "discussion", "release", "release_notes",
            "github_file", "repo_file", "repository_file",
            "githubIssue", "pullRequest", "githubFile",
        ]
        for source_type in matrix:
            with self.subTest(sourceType=source_type):
                source = self._ingest(sourceType=source_type, **self._payload(f"gh://org/repo/{source_type}"))
                self.assertEqual(source.origin, "github")
                self.assertEqual(source.source_type, source_type)

    def test_a_bare_github_com_url_infers_github(self):
        source = self._ingest(
            sourceType="github_issue", **self._payload("https://github.com/example-org/throughline-pilot/issues/9"),
        )
        self.assertEqual(source.origin, "github")

    def test_a_github_api_url_infers_github(self):
        source = self._ingest(
            sourceType="github_issue", **self._payload("https://api.github.com/repos/example-org/throughline-pilot/issues/9"),
        )
        self.assertEqual(source.origin, "github")

    def test_a_githubusercontent_raw_url_infers_github(self):
        source = self._ingest(
            sourceType="github_file",
            **self._payload("https://raw.githubusercontent.com/example-org/throughline-pilot/main/README.md"),
        )
        self.assertEqual(source.origin, "github")


class OriginlessWorkiqFamilyTests(_IngestHarness):
    """WorkIQ/Microsoft 365 SharePoint, OneDrive, Teams transcript/chat,
    Outlook/email, Loop page, and `workiq://`/recognized Microsoft URLs
    -- content supplied directly (as a real WorkIQFetcher would)."""

    def _payload(self, uri: str, **overrides) -> dict:
        payload = {
            "uri": uri, "owner": "speaker@example.com", "permissionState": "authorized",
            "aclSnapshot": "site:talks-members", "version": "v1", "content": "WorkIQ-sourced evidence text.",
        }
        payload.update(overrides)
        return payload

    def test_every_recognized_workiq_source_type_spelling_ingests_with_no_origin(self):
        matrix = [
            "sharepoint_doc", "onedrive_doc", "teams_message", "teams_transcript", "outlook_mail",
            "outlook_calendar", "loop_page", "sharepoint", "onedrive", "teams", "teams_chat",
            "outlook", "loop", "m365", "microsoft365", "office365",
            "sharepointDoc", "teamsTranscript", "outlookMail",
        ]
        for source_type in matrix:
            with self.subTest(sourceType=source_type):
                source = self._ingest(sourceType=source_type, **self._payload(f"workiq://{source_type}/1"))
                self.assertEqual(source.origin, "workiq")
                self.assertEqual(source.source_type, source_type)

    def test_a_sharepoint_url_infers_workiq(self):
        source = self._ingest(
            sourceType="sharepoint_doc", **self._payload("https://contoso.sharepoint.com/sites/talks/adoption-report.docx"),
        )
        self.assertEqual(source.origin, "workiq")

    def test_a_onedrive_url_infers_workiq(self):
        source = self._ingest(sourceType="onedrive_doc", **self._payload("https://onedrive.live.com/redir?resid=1234"))
        self.assertEqual(source.origin, "workiq")

    def test_a_1drv_short_link_infers_workiq(self):
        source = self._ingest(sourceType="onedrive_doc", **self._payload("https://1drv.ms/w/s!AbCdEf"))
        self.assertEqual(source.origin, "workiq")

    def test_a_loop_cloud_microsoft_url_infers_workiq(self):
        source = self._ingest(sourceType="loop_page", **self._payload("https://loop.cloud.microsoft/p/talk-notes"))
        self.assertEqual(source.origin, "workiq")

    def test_a_bare_workiq_scheme_uri_infers_workiq_with_no_hostname_at_all(self):
        source = self._ingest(sourceType="teams_transcript", **self._payload("workiq://teams/transcript/talk-kickoff"))
        self.assertEqual(source.origin, "workiq")


class OriginVsInferredConnectorConflictTests(_IngestHarness):
    """An explicit, valid `origin` that outright conflicts with the
    connector this same descriptor's own `sourceType`/`uri` already,
    confidently implies is refused explicitly -- never silently honored,
    never silently overridden."""

    def test_explicit_local_origin_conflicting_with_a_github_source_type_is_refused(self):
        with self.assertRaises(EngineError) as ctx:
            self._ingest(
                origin="local", sourceType="github_issue", uri="gh://org/repo/issues/1",
                owner="o@example.com", permissionState="authorized", aclSnapshot="x", version="v1",
                content="text",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_explicit_github_origin_conflicting_with_a_workiq_source_type_is_refused(self):
        with self.assertRaises(EngineError) as ctx:
            self._ingest(
                origin="github", sourceType="sharepoint_doc", uri="https://contoso.sharepoint.com/doc.docx",
                owner="o@example.com", permissionState="authorized", aclSnapshot="x", version="v1",
                content="text",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_explicit_workiq_origin_conflicting_with_a_local_file_extension_is_refused(self):
        with self.assertRaises(EngineError) as ctx:
            self._ingest(
                origin="workiq", uri=str(LOCAL_FIXTURES / "notes.md"),
                owner="o@example.com", permissionState="authorized", aclSnapshot="x", version="v1",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_explicit_origin_agreeing_with_the_inferred_connector_is_not_a_conflict(self):
        source = self._ingest(
            origin="github", sourceType="github_issue", uri="gh://org/repo/issues/1",
            owner="o@example.com", permissionState="authorized", aclSnapshot="x", version="v1",
            content="text",
        )
        self.assertEqual(source.origin, "github")


class UnknownOrAmbiguousDescriptorsRemainRefusedTests(_IngestHarness):
    """Unknown/ambiguous descriptors are still held/refused, never
    silently authorized -- an unrecognized extension, an unrecognized
    `sourceType` word, and a network URL with neither a known host nor a
    recognized extension all still refuse exactly as before."""

    def test_an_unrecognized_local_extension_is_still_refused(self):
        with self.assertRaises(EngineError) as ctx:
            self._ingest(
                uri=str(LOCAL_FIXTURES / "nonexistent.xyz"), owner="o@example.com",
                permissionState="authorized", aclSnapshot="x", version="v1",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertIn("origin", ctx.exception.message)

    def test_an_unrecognized_source_type_word_is_still_refused(self):
        with self.assertRaises(EngineError) as ctx:
            self._ingest(
                sourceType="mystery_format", uri="https://example.com/whatever", owner="o@example.com",
                permissionState="authorized", aclSnapshot="x", version="v1", content="text",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_unrecognized_network_url_with_no_hint_at_all_is_still_refused(self):
        with self.assertRaises(EngineError) as ctx:
            self._ingest(
                uri="https://example.com/whatever/notes.md", owner="o@example.com",
                permissionState="authorized", aclSnapshot="x", version="v1", content="text",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class OriginlessManualOnlyJourneyReachesStagePackageTests(unittest.TestCase):
    """(PRD/ARCH end-to-end success criteria) A complete, manual-only
    public `run-scenario` journey whose *every* source descriptor omits
    `origin` (and, for most, `sourceType` too) still reaches the
    narrative gate, a named human Stage approval, an editable PPTX
    export, and the complete nine-artifact package -- proving the
    classifier composes with the full existing pipeline, not just
    `ingest_source` in isolation."""

    ARTIFACT_KINDS = {
        "EDITABLE_DECK", "SPEAKER_NOTES_DOC", "ACCESSIBLE_PDF", "EVIDENCE_APPROVAL_MANIFEST",
        "CAPTION_SCRIPT", "DEMO_ASSETS", "OFFLINE_BACKUP", "PANIC_DECK", "LAST_KNOWN_GOOD",
    }

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _doc(self) -> list[dict]:
        notes_path = str(LOCAL_FIXTURES / "notes.md")
        data_path = str(LOCAL_FIXTURES / "data.json")
        demo_asset_path = str(LOCAL_FIXTURES / "adoption-notes.txt")
        return [
            {"action": "set_talk_brief", "audience": "Conference attendees", "eventType": "keynote",
             "durationMinutes": 20, "takeaway": "Structured evidence review de-risks talks",
             "proofPoints": ["adoption stat"], "excludedTopics": [], "tone": "confident"},
            # Both sources below omit `origin` entirely; the markdown
            # source also omits `sourceType` entirely -- the fully
            # "originless and typeless" case, classified purely from its
            # own recognized `.md` extension.
            {"action": "add_source", "uri": notes_path, "owner": "speaker@example.com",
             "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1"},
            {"action": "add_source", "sourceType": "json", "uri": data_path, "owner": "speaker@example.com",
             "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1"},
            {"action": "propose_claim", "type": "factual",
             "text": "Adoption of structured evidence review grew 42% quarter over quarter.",
             "evidenceLocators": [notes_path], "approve": True},
            {"action": "propose_claim", "type": "interpretive",
             "text": "This suggests structured evidence review meaningfully reduces talk-prep risk.",
             "evidenceLocators": [data_path],
             "rationale": "The recorded growth metric correlates with reduced talk-prep risk.", "approve": True},
            {"action": "propose_claim", "type": "aspirational",
             "text": "We recommend every team adopt structured evidence review.",
             "aspirationalLabel": "RECOMMENDATION", "approve": True},
            {"action": "select_throughline", "value": 0},
            {"action": "propose_route", "label": "Primary route", "beats": [
                {"role": "HOOK", "headline": "A stat that changes the room", "timeBudgetSeconds": 60, "spokenTalkTrack": "Open cold."},
                {"role": "STAKES", "headline": "Talks fail without provenance", "timeBudgetSeconds": 90, "spokenTalkTrack": "Stakes.", "visualDescription": "Desk photo"},
                {"role": "TURN", "headline": "What changes the outcome", "timeBudgetSeconds": 90, "spokenTalkTrack": "Turn.", "visualDescription": "Diagram"},
                {"role": "MECHANISM", "headline": "How the ledger works end to end", "timeBudgetSeconds": 120, "spokenTalkTrack": "Mechanism.", "visualDescription": "Live demo", "isDemo": True},
                {"role": "PROOF", "headline": "Adoption grew 42% in one quarter", "timeBudgetSeconds": 90, "spokenTalkTrack": "Proof.", "claimIds": [0], "visualDescription": "Bar chart"},
                {"role": "OBJECTION", "headline": "Is the overhead worth it", "timeBudgetSeconds": 90, "spokenTalkTrack": "Objection.", "claimIds": [1], "visualDescription": "Quote"},
                {"role": "ASK", "headline": "Start your next talk this way", "timeBudgetSeconds": 60, "spokenTalkTrack": "Ask.", "claimIds": [2], "visualDescription": "CTA graphic"},
            ]},
            # FR-NAR-3: exactly 2 or 3 narrative routes must be proposed.
            {"action": "propose_route", "label": "Short alt route", "beats": [
                {"role": "HOOK", "headline": "Alt hook", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "Alt ask", "timeBudgetSeconds": 60},
            ]},
            {"action": "select_narrative_route", "value": 0},
            {"action": "set_demo_asset", "slideRole": "MECHANISM", "livePath": "cli-session://live-terminal",
             "prerecordedAssetPath": demo_asset_path, "staticAssetPath": demo_asset_path,
             "verbalRecoveryScript": "I will narrate the ledger flow verbally if the live demo fails."},
            {"action": "run_gate", "gate": "narrative"},
            {"action": "rehearse", "run": {
                "HOOK": 58, "STAKES": 95, "TURN": 88, "MECHANISM": 130, "PROOF": 85, "OBJECTION": 92, "ASK": 55,
            }},
            {"action": "export", "target": "pptx"},
            {"action": "export", "target": "package"},
            {"action": "approve_stage", "value": "Dr. Jamie Rivera"},
        ]

    def test_originless_local_only_journey_completes_with_no_refusal(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, self._doc(), self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))

    def test_both_originless_sources_ingest_and_are_classified_local(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, self._doc(), self.root / "report")
        self.assertEqual(len(report["sources"]), 2)
        self.assertTrue(all(s["origin"] == "local" for s in report["sources"]))
        source_types = sorted(s["source_type"] for s in report["sources"])
        self.assertEqual(source_types, ["json", "local_upload"])

    def test_reaches_named_human_stage_approval_and_the_full_nine_artifact_package(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, self._doc(), self.root / "report")
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertEqual(report["workspace"]["stageApprovedBy"], "Dr. Jamie Rivera")
        self.assertEqual(set(report["exports"][1]["artifactKinds"]), self.ARTIFACT_KINDS)
        self.assertEqual(report["exports"][0]["target"], "pptx")
        self.assertTrue(report["exports"][0]["path"].endswith(".pptx"))

    def test_the_identical_journey_via_the_cli_subprocess_exits_zero(self):
        scenario_path = self.root / "originless-journey-scenario.json"
        scenario_path.write_text(json.dumps(self._doc()))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))
        self.assertTrue(envelope["data"]["stageGate"]["passed"])


if __name__ == "__main__":
    unittest.main()
