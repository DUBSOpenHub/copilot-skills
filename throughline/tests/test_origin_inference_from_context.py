"""Regression tests for source-`origin` inference from context
(`engine/ingest.infer_origin` / the punctuation-agnostic
`_ORIGIN_ALIASES_SQUASHED` fallback in `engine/ingest.normalize_origin`):
a source descriptor that omits `origin` entirely still ingests when a
canonical origin can be conservatively inferred from its own `sourceType`
or `uri`, and a staged `origin` value that uses different punctuation
than an already-listed alias (e.g. "Office 365" vs. "office365") still
resolves.

Compatibility gap this closes: a descriptor with no `origin` field at all
(rather than an explicit wrong one) was unconditionally refused
`VALIDATION_ERROR: origin must be one of [...]`, even when `sourceType`,
`uri`, or (Dark Factory hardening cycle 9) the `uri`'s own recognized
local file extension already unambiguously implied one of the three
canonical origins.

Unknown/unsafe descriptors are still held/refused, never silently
authorized: extension-based inference only ever fires for a `uri` that
already looks like a genuine local filesystem reference (no scheme, or an
explicit `file://`/single-letter-drive scheme) *and* carries one of the
conservative, allowlisted MVP local document/image extensions -- never
for a network URL whose host/scheme didn't already match a known
connector, and never for an unrecognized extension. An `origin` that is
explicitly given (even if wrong) is never second-guessed -- only a truly
*omitted* origin is ever inferred -- except that an explicit, *valid*
origin which outright conflicts with a confidently-inferred connector is
now its own explicit `VALIDATION_ERROR` (see
`OriginVsInferredConnectorConflictTests` below).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import EngineError, REPO_ROOT, cleanup, ingest_mod, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


class OriginInferenceFromSourceTypeUnitTests(unittest.TestCase):
    """Direct, in-process coverage of `infer_origin` itself."""

    def test_infers_github_from_a_github_shaped_source_type(self):
        self.assertEqual(ingest_mod.infer_origin("github_issue", None), "github")
        self.assertEqual(ingest_mod.infer_origin("github_pr", None), "github")

    def test_infers_workiq_from_an_m365_shaped_source_type(self):
        self.assertEqual(ingest_mod.infer_origin("sharepoint_doc", None), "workiq")
        self.assertEqual(ingest_mod.infer_origin("teams_transcript", None), "workiq")

    def test_infers_local_from_a_local_shaped_source_type(self):
        self.assertEqual(ingest_mod.infer_origin("local_paste", None), "local")
        self.assertEqual(ingest_mod.infer_origin("local_upload", None), "local")

    def test_infers_github_from_a_github_com_uri_when_source_type_gives_no_match(self):
        self.assertEqual(ingest_mod.infer_origin(None, "https://github.com/org/repo/issues/1"), "github")

    def test_infers_workiq_from_a_sharepoint_uri(self):
        self.assertEqual(ingest_mod.infer_origin(None, "https://contoso.sharepoint.com/sites/x/doc.docx"), "workiq")

    def test_infers_local_from_a_bare_filesystem_path_with_a_recognized_extension(self):
        """(Dark Factory hardening cycle 9) A bare filesystem-looking
        path with no other signal at all now infers `local` from its own
        recognized MVP local document extension -- conservative and
        allowlisted (`engine.ingest._LOCAL_FILE_EXTENSION_HINTS`), never
        a guess for an arbitrary extension (see
        `test_still_never_infers_local_from_an_unrecognized_extension`
        below)."""
        self.assertEqual(ingest_mod.infer_origin(None, "/Users/someone/notes.md"), "local")
        self.assertEqual(ingest_mod.infer_origin(None, "notes.md"), "local")

    def test_still_never_infers_local_from_an_unrecognized_extension(self):
        self.assertIsNone(ingest_mod.infer_origin(None, "/Users/someone/notes.xyz"))
        self.assertIsNone(ingest_mod.infer_origin(None, "/Users/someone/README"))

    def test_never_infers_local_from_a_recognized_extension_on_a_network_url(self):
        """A recognized local extension on a genuine network URL (an
        unrecognized host/scheme) is still never inferred as `local` --
        extension-based inference only applies to a `uri` that already
        looks like a real filesystem reference."""
        self.assertIsNone(ingest_mod.infer_origin(None, "https://example.com/whatever/notes.md"))

    def test_infers_workiq_from_a_workiq_scheme_uri(self):
        self.assertEqual(ingest_mod.infer_origin(None, "workiq://teams/transcript/abc"), "workiq")

    def test_returns_none_when_neither_gives_a_confident_match(self):
        self.assertIsNone(ingest_mod.infer_origin("mystery_type", "https://example.com/whatever"))
        self.assertIsNone(ingest_mod.infer_origin(None, None))

    def test_source_type_takes_priority_over_a_uri_hint(self):
        # sourceType says github; uri looks like a sharepoint link -- sourceType wins.
        self.assertEqual(
            ingest_mod.infer_origin("github_repo", "https://contoso.sharepoint.com/sites/x/doc.docx"), "github",
        )

    def test_uri_host_hint_takes_priority_over_a_local_extension_hint(self):
        # A recognized SharePoint host wins over the .docx extension's
        # own "local" hint -- the more specific/certain signal wins.
        self.assertEqual(
            ingest_mod.infer_origin(None, "https://contoso.sharepoint.com/sites/x/doc.docx"), "workiq",
        )


class OriginSquashedPunctuationFallbackUnitTests(unittest.TestCase):
    """`normalize_origin`'s second-tier, punctuation-agnostic lookup."""

    def test_office_365_with_a_space_resolves_like_office365_does(self):
        self.assertEqual(ingest_mod.normalize_origin("office365"), "workiq")
        self.assertEqual(ingest_mod.normalize_origin("Office 365"), "workiq")

    def test_hyphenated_and_dotted_variants_of_a_known_alias_resolve(self):
        self.assertEqual(ingest_mod.normalize_origin("micro.soft365"), "workiq")

    def test_a_truly_unknown_origin_is_still_returned_unchanged(self):
        for bogus in ("spacecraft", "carrier pigeon", ""):
            with self.subTest(bogus=bogus):
                self.assertEqual(ingest_mod.normalize_origin(bogus), bogus)


class SourceTypeSpellingCompatibilityUnitTests(unittest.TestCase):
    """(Dark Factory hardening cycle 9) camelCase and MIME-type
    `sourceType`/`origin` spellings resolve identically to their already-
    listed snake_case/short-word form -- `engine.ingest.normalize_origin`
    /`engine.ingest._is_recognized_source_type`."""

    def test_camel_case_canonical_source_types_resolve(self):
        self.assertEqual(ingest_mod.normalize_origin("sharepointDoc"), "workiq")
        self.assertEqual(ingest_mod.normalize_origin("teamsTranscript"), "workiq")
        self.assertEqual(ingest_mod.normalize_origin("githubIssue"), "github")
        self.assertEqual(ingest_mod.normalize_origin("localUpload"), "local")

    def test_mime_type_spellings_resolve_to_the_equivalent_format_word(self):
        self.assertEqual(ingest_mod.normalize_origin("text/markdown"), "local")
        self.assertEqual(ingest_mod.normalize_origin("application/pdf"), "local")
        self.assertEqual(
            ingest_mod.normalize_origin("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "local",
        )
        self.assertEqual(ingest_mod.normalize_origin("message/rfc822"), "local")
        self.assertEqual(ingest_mod.normalize_origin("image/png"), "local")

    def test_is_recognized_source_type_accepts_every_new_local_format_word(self):
        for word in (
            "markdown", "md", "text", "txt", "pdf", "pptx", "docx", "vtt", "srt",
            "transcript", "eml", "email", "json", "image", "png", "jpg", "jpeg", "gif",
        ):
            with self.subTest(word=word):
                self.assertTrue(ingest_mod._is_recognized_source_type(word))

    def test_is_recognized_source_type_accepts_camel_case_and_mime_forms(self):
        self.assertTrue(ingest_mod._is_recognized_source_type("sharepointDoc"))
        self.assertTrue(ingest_mod._is_recognized_source_type("application/pdf"))

    def test_is_recognized_source_type_rejects_unknown_words(self):
        for bogus in (None, "", "mystery_format", 42):
            with self.subTest(bogus=bogus):
                self.assertFalse(ingest_mod._is_recognized_source_type(bogus))


class OriginInferenceIngestSourceEndToEndTests(unittest.TestCase):
    """End-to-end coverage: `ingest_source` itself fills in an omitted
    `origin` and persists the source exactly as it would for an explicit
    canonical/aliased spelling -- and never second-guesses an explicit
    (even if wrong) `origin`."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _payload(self, **overrides) -> dict:
        payload = {
            "sourceType": "github_issue", "uri": "gh://org/repo/issues/7", "owner": "speaker@example.com",
            "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
            "content": "Issue body text used as evidence.",
        }
        payload.update(overrides)
        return payload

    def test_an_omitted_origin_is_inferred_from_source_type_and_ingests(self):
        store = persistence.Store(root=self.root / "ws")
        conn = store.connect("workspace:probe")
        try:
            source = ingest_mod.ingest_source(
                conn, "workspace:probe", self._payload(), actor="T",
                staging_dir=store.workspace_dir("workspace:probe") / "staging",
            )
            self.assertEqual(source.origin, "github")
            self.assertEqual(source.state, "AUTHORIZED")
        finally:
            conn.close()

    def test_an_omitted_origin_with_no_confident_signal_is_still_refused(self):
        """Neither `sourceType` (unrecognized/absent) nor `uri` (no known
        hint) gives a confident signal -- `origin` stays exactly as
        omitted and the pre-existing "must be one of [...]" refusal still
        fires, never a silent guess."""
        store = persistence.Store(root=self.root / "ws")
        conn = store.connect("workspace:probe")
        try:
            with self.assertRaises(EngineError) as ctx:
                ingest_mod.ingest_source(
                    conn, "workspace:probe",
                    self._payload(sourceType=None, uri="mystery://not-a-known-hint"),
                    actor="T", staging_dir=store.workspace_dir("workspace:probe") / "staging",
                )
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
            self.assertIn("origin", ctx.exception.message)
        finally:
            conn.close()

    def test_an_explicit_but_wrong_origin_is_never_second_guessed(self):
        """Only a truly *omitted* origin is ever inferred -- an explicit
        (even if wrong/unrecognized) one is never overridden, exactly
        preserving the pre-existing refusal for a bad explicit origin."""
        store = persistence.Store(root=self.root / "ws")
        conn = store.connect("workspace:probe")
        try:
            with self.assertRaises(EngineError) as ctx:
                ingest_mod.ingest_source(
                    conn, "workspace:probe", self._payload(origin="carrier_pigeon"), actor="T",
                    staging_dir=store.workspace_dir("workspace:probe") / "staging",
                )
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        finally:
            conn.close()

    def test_source_type_is_preserved_verbatim_when_origin_was_inferred(self):
        """FR-SRC-1: the original public `sourceType` spelling is never
        rewritten by origin inference -- even a non-canonical, newly
        recognized format word (Dark Factory hardening cycle 9) is
        persisted exactly as supplied."""
        store = persistence.Store(root=self.root / "ws")
        conn = store.connect("workspace:probe")
        try:
            source = ingest_mod.ingest_source(
                conn, "workspace:probe",
                self._payload(
                    sourceType="markdown", origin=None,
                    uri=str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt"),
                ),
                actor="T", staging_dir=store.workspace_dir("workspace:probe") / "staging",
            )
            self.assertEqual(source.origin, "local")
            self.assertEqual(source.source_type, "markdown")
        finally:
            conn.close()


class OriginVsInferredConnectorConflictTests(unittest.TestCase):
    """(Dark Factory hardening cycle 9) An *explicit*, valid `origin`
    that outright conflicts with the connector this same descriptor's
    own `sourceType`/`uri` already, confidently implies is refused
    explicitly -- never silently honored and never silently
    overridden."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _payload(self, **overrides) -> dict:
        payload = {
            "sourceType": "github_issue", "uri": "gh://org/repo/issues/7", "owner": "speaker@example.com",
            "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
            "content": "Issue body text used as evidence.",
        }
        payload.update(overrides)
        return payload

    def test_a_local_origin_conflicting_with_a_github_shaped_source_type_is_refused(self):
        store = persistence.Store(root=self.root / "ws")
        conn = store.connect("workspace:probe")
        try:
            with self.assertRaises(EngineError) as ctx:
                ingest_mod.ingest_source(
                    conn, "workspace:probe", self._payload(origin="local"), actor="T",
                    staging_dir=store.workspace_dir("workspace:probe") / "staging",
                )
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
            self.assertIn("conflicts", ctx.exception.message)
        finally:
            conn.close()

    def test_a_workiq_origin_conflicting_with_a_local_extension_hint_is_refused(self):
        store = persistence.Store(root=self.root / "ws")
        conn = store.connect("workspace:probe")
        try:
            with self.assertRaises(EngineError) as ctx:
                ingest_mod.ingest_source(
                    conn, "workspace:probe",
                    self._payload(origin="workiq", sourceType=None, uri="/Users/someone/notes.md"),
                    actor="T", staging_dir=store.workspace_dir("workspace:probe") / "staging",
                )
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        finally:
            conn.close()

    def test_agreeing_explicit_origin_and_inferred_connector_is_not_a_conflict(self):
        """An explicit origin that *agrees* with the inferred connector
        (the common, already-tested case) still ingests normally --
        conflict detection never fires for a mere match."""
        store = persistence.Store(root=self.root / "ws")
        conn = store.connect("workspace:probe")
        try:
            source = ingest_mod.ingest_source(
                conn, "workspace:probe", self._payload(origin="github"), actor="T",
                staging_dir=store.workspace_dir("workspace:probe") / "staging",
            )
            self.assertEqual(source.origin, "github")
        finally:
            conn.close()


class OriginInferenceScenarioEndToEndTests(unittest.TestCase):
    """The literal compatibility gap through the public `run-scenario`
    action-list interface: an omitted `origin` still lets the source
    ingest and dependent evidence/claim flows proceed."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _brief_step(self) -> dict:
        return {
            "action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
            "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident",
        }

    def test_an_omitted_origin_github_descriptor_ingests_through_run_scenario(self):
        doc = [
            self._brief_step(),
            {"action": "add_source", "sourceType": "github_issue", "uri": "gh://org/repo/issues/9",
             "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "Issue body text used as evidence."},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        ingest_step = next(s for s in report["steps"] if s["action"] == "source.ingest")
        self.assertEqual(ingest_step["state"], "AUTHORIZED")

    def test_an_omitted_origin_uri_only_hint_ingests_via_the_cli_subprocess(self):
        doc = [
            self._brief_step(),
            {"action": "add_source", "sourceType": "sharepoint_doc", "uri": "https://contoso.sharepoint.com/notes.docx",
             "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "Notes retrieved from a SharePoint document."},
        ]
        scenario_path = self.root / "omitted-origin-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        ingest_step = next(s for s in envelope["data"]["steps"] if s["action"] == "source.ingest")
        self.assertEqual(ingest_step["state"], "AUTHORIZED")


if __name__ == "__main__":
    unittest.main()
