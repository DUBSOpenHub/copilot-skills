"""Regression tests for Dark Factory hardening cycle 12: the public
source-reference vocabulary (`locator`/`fixture`/`artifact`/`document`/
`upload`/`reference`/`ref`/... field-name aliases and their
`_path`/`_type`/`_kind` siblings), the conservative `add_source`-only
default-local classification rule, relative scenario-fixture path
resolution, and held (never hard-refused) ledger entries for a
recognized-but-not-yet-resolved local file.

Compatibility gap this closes: `add_source`/`ingest_source` actions
staged with this wider, common source-reference vocabulary (a fixture
path, a document/artifact reference, a bare `reference`/`ref`) reached
`ingest_source` with no recognized locator/type/origin signal at all --
even though the structural wrapper/container extractor (Dark Factory
hardening cycle 11) ran successfully -- and were refused
`VALIDATION_ERROR: origin must be one of [...]` before a ledger row could
ever be created, blocking every downstream evidence/claim/gate/export
behavior that depends on a populated source ledger.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from helpers import DEFAULT_BRIEF, EngineError, REPO_ROOT, cleanup, ingest_mod, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")
LOCAL_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "local"


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _brief_step(**overrides) -> dict:
    payload = {"action": "set_talk_brief", **DEFAULT_BRIEF}
    payload.update(overrides)
    return payload


# Every new locator/path field-name alias this hardening cycle adds --
# mapped, in every listed spelling, into the canonical `uri`.
URI_ALIAS_FIELDS = [
    "locator", "source_locator", "sourceLocator", "fixture", "fixture_path", "fixturePath",
    "artifact", "artifact_path", "artifactPath", "document", "document_path", "documentPath",
    "file_path", "filePath", "local_file", "localFile", "input_file", "inputFile",
    "input_path", "inputPath", "content_file", "contentFile", "content_path", "contentPath",
    "upload", "upload_path", "uploadPath", "reference", "ref",
]

# The parallel new `sourceType` field-name aliases.
SOURCE_TYPE_ALIAS_FIELDS = [
    "source_kind", "sourceKind", "document_type", "documentType", "artifact_type", "artifactType",
]

# A representative kebab-case spelling of each alias above (never listed
# verbatim in `engine.ingest.SOURCE_PAYLOAD_FIELD_ALIASES` -- only
# reachable via `normalize_source_payload`'s own generalized,
# `_normalize_field_key`-based fallback pass).
URI_ALIAS_KEBAB_SPELLINGS = [
    "source-locator", "fixture-path", "artifact-path", "document-path", "file-path",
    "local-file", "input-file", "input-path", "content-file", "content-path", "upload-path",
]
SOURCE_TYPE_ALIAS_KEBAB_SPELLINGS = ["source-kind", "document-type", "artifact-type"]


class ReferenceLocatorFieldAliasUnitTests(unittest.TestCase):
    """Direct, in-process coverage of `ingest.normalize_source_payload`
    for every new locator/path alias, in every explicitly listed
    spelling."""

    def test_every_new_uri_alias_resolves_to_the_canonical_uri_field(self):
        for field in URI_ALIAS_FIELDS:
            with self.subTest(field=field):
                resolved = ingest_mod.normalize_source_payload({field: "adoption-notes.md"})
                self.assertEqual(resolved.get("uri"), "adoption-notes.md")
                # Original metadata is preserved verbatim -- never dropped.
                self.assertEqual(resolved.get(field), "adoption-notes.md")

    def test_every_new_source_type_alias_resolves_to_the_canonical_field(self):
        for field in SOURCE_TYPE_ALIAS_FIELDS:
            with self.subTest(field=field):
                resolved = ingest_mod.normalize_source_payload({field: "markdown"})
                self.assertEqual(resolved.get("sourceType"), "markdown")
                self.assertEqual(resolved.get(field), "markdown")

    def test_kebab_case_spellings_of_new_uri_aliases_also_resolve(self):
        for field in URI_ALIAS_KEBAB_SPELLINGS:
            with self.subTest(field=field):
                resolved = ingest_mod.normalize_source_payload({field: "adoption-notes.md"})
                self.assertEqual(resolved.get("uri"), "adoption-notes.md")

    def test_kebab_case_spellings_of_new_source_type_aliases_also_resolve(self):
        for field in SOURCE_TYPE_ALIAS_KEBAB_SPELLINGS:
            with self.subTest(field=field):
                resolved = ingest_mod.normalize_source_payload({field: "markdown"})
                self.assertEqual(resolved.get("sourceType"), "markdown")

    def test_an_explicit_canonical_uri_always_wins_over_a_new_alias(self):
        resolved = ingest_mod.normalize_source_payload({"uri": "real.md", "fixture": "ignored.md"})
        self.assertEqual(resolved["uri"], "real.md")

    def test_two_new_aliases_disagreeing_is_a_clean_conflict(self):
        with self.assertRaises(EngineError) as ctx:
            ingest_mod.normalize_source_payload({"fixture": "a.md", "document": "b.md"})
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_two_new_aliases_agreeing_resolve_normally(self):
        resolved = ingest_mod.normalize_source_payload({"fixture": "a.md", "document": "a.md"})
        self.assertEqual(resolved["uri"], "a.md")

    def test_a_new_alias_and_an_old_alias_disagreeing_is_a_clean_conflict(self):
        with self.assertRaises(EngineError) as ctx:
            ingest_mod.normalize_source_payload({"path": "a.md", "reference": "b.md"})
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class ReferenceLocatorEndToEndIngestTests(unittest.TestCase):
    """Each new alias, used as the *sole* locator field on an otherwise
    complete, real `ingest_source` call against a genuine on-disk
    fixture -- proves the alias is honored all the way through actual
    file acquisition/parsing, not just field-name normalization."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")
        self.conn = self.store.connect("workspace:probe")
        self.staging_dir = self.store.workspace_dir("workspace:probe") / "staging"

    def tearDown(self):
        self.conn.close()
        cleanup(self.root)

    def _ingest(self, **payload):
        return ingest_mod.ingest_source(self.conn, "workspace:probe", payload, actor="T", staging_dir=self.staging_dir)

    def test_every_new_alias_ingests_the_real_notes_fixture(self):
        for field in ("locator", "fixture", "artifact", "document", "upload", "reference", "ref", "input_file"):
            with self.subTest(field=field):
                source = self._ingest(**{
                    field: str(LOCAL_FIXTURES / "notes.md"), "owner": "speaker@example.com",
                    "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
                })
                self.assertEqual(source.origin, "local")
                self.assertEqual(source.state, "AUTHORIZED")
                self.assertEqual(source.source_type, "local_upload")


class StructuralContainerRecognizesReferenceVocabularyTests(unittest.TestCase):
    """The generalized structural wrapper/container extractor
    (`engine.scenario._is_source_descriptor_container`/
    `_has_descriptor_signal`) now also recognizes the new alias field
    names above as real descriptor signal -- so a nested container whose
    *only* signal is one of them is still discovered as a genuine source
    descriptor, at any nesting depth, exactly like the pre-existing
    `uri`/`owner`/`sourceType`/... vocabulary already was."""

    def _wrapped_doc(self, wrapper_key: str, inner: dict) -> list[dict]:
        return [{"action": "add_source", wrapper_key: inner}]

    def test_a_wrapper_whose_only_signal_is_a_new_locator_alias_is_discovered(self):
        for field in ("locator", "fixture", "artifact", "document", "upload", "reference", "ref", "source_kind"):
            with self.subTest(field=field):
                inner = {
                    field: "adoption-notes.md" if field != "source_kind" else "markdown",
                    "uri": "paste:x" if field == "source_kind" else None,
                    "owner": "speaker@example.com", "permissionState": "authorized",
                    "aclSnapshot": "owner-only", "version": "v1", "content": "text",
                }
                inner = {k: v for k, v in inner.items() if v is not None}
                doc = self._wrapped_doc("thirdPartyEnvelope", inner)
                merged = scenario._normalize_scenario_doc(doc)
                self.assertEqual(len(merged["sources"]), 1)

    def test_deeply_nested_reference_only_signal_still_unwraps(self):
        doc = [{"action": "add_source", "outer": {"middle": {"inner": {
            "reference": str(LOCAL_FIXTURES / "notes.md"), "owner": "speaker@example.com",
            "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
        }}}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"][0]["uri"], str(LOCAL_FIXTURES / "notes.md"))


class ScalarSourceActionClassificationTests(unittest.TestCase):
    """A bare-scalar `add_source` action -- no recognized wrapper, no
    recognized field name at all -- still classifies correctly whenever
    its lone value is itself clearly URI-/path-/extension-shaped
    (`ingest._apply_bare_scalar_field_hint`), and every new alias name
    used directly (unwrapped) resolves identically to any other field."""

    def test_a_lone_unrecognized_field_with_a_path_shaped_value_becomes_uri(self):
        doc = [{"action": "add_source", "thirdPartyPointer": "adoption-notes.md", "owner": "speaker@example.com",
                "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1"}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"][0]["uri"], "adoption-notes.md")

    def test_a_lone_unrecognized_field_with_a_url_scheme_becomes_uri(self):
        doc = [{"action": "add_source", "somePointer": "https://github.com/org/repo/issues/9",
                "sourceType": "github_issue", "owner": "org/repo", "permissionState": "authorized",
                "aclSnapshot": "public", "version": "v1"}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"][0]["uri"], "https://github.com/org/repo/issues/9")

    def test_each_new_alias_field_used_bare_at_the_action_top_level_resolves(self):
        for field in ("fixture", "reference", "ref", "document", "artifact", "upload"):
            with self.subTest(field=field):
                doc = [{"action": "add_source", field: "adoption-notes.md", "owner": "speaker@example.com",
                        "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
                        "content": "x"}]
                merged = scenario._normalize_scenario_doc(doc)
                self.assertEqual(merged["sources"][0]["uri"], "adoption-notes.md")


class RelativeScenarioFixtureResolutionTests(unittest.TestCase):
    """`run_scenario`'s new optional `scenario_path` threads the
    scenario document's own directory down to `add_source`/
    `ingest_source` handling, so a *relative* fixture/reference locator
    resolves against it first, before the current working directory --
    while the persisted `uri` (provenance) always stays the original,
    unresolved locator string the caller gave."""

    def setUp(self):
        self.root = new_root()
        self.scenario_dir = self.root / "scenarios"
        self.scenario_dir.mkdir(parents=True)
        (self.scenario_dir / "my-notes.md").write_text("Adoption grew 42% quarter over quarter.")
        self.store = persistence.Store(root=self.root / "ws")

    def tearDown(self):
        cleanup(self.root)

    def _doc(self, uri_field: str = "fixture") -> list[dict]:
        return [
            _brief_step(),
            {"action": "add_source", uri_field: "my-notes.md", "owner": "speaker@example.com",
             "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1"},
        ]

    def test_a_relative_fixture_path_resolves_against_the_scenario_directory(self):
        scenario_path = self.scenario_dir / "scenario.json"
        scenario_path.write_text(json.dumps(self._doc()))
        report = scenario.run_scenario(self.store, self._doc(), self.root / "report", scenario_path=scenario_path)
        self.assertTrue(report["ok"], report.get("refusal"))
        (source,) = report["sources"]
        # Provenance: the persisted `uri` is still the original, relative
        # locator -- never rewritten to the resolved absolute path.
        self.assertEqual(source["uri"], "my-notes.md")
        self.assertEqual(source["state"], "CURATED")  # reached evidence extraction -> real content was read

    def test_every_new_alias_field_also_resolves_relatively(self):
        for field in ("locator", "fixture", "artifact", "document", "reference", "ref"):
            with self.subTest(field=field):
                store = persistence.Store(root=self.root / f"ws-{field}")
                scenario_path = self.scenario_dir / "scenario.json"
                doc = self._doc(field)
                scenario_path.write_text(json.dumps(doc))
                report = scenario.run_scenario(store, doc, self.root / f"report-{field}", scenario_path=scenario_path)
                self.assertTrue(report["ok"], report.get("refusal"))
                self.assertEqual(report["sources"][0]["state"], "CURATED")

    def test_without_a_scenario_path_a_relative_locator_falls_back_to_cwd_unchanged(self):
        """No `scenario_path` at all (every existing/direct caller) --
        behaves exactly as before this hardening cycle: a relative
        locator that doesn't exist under the current working directory
        is held (see `NonexistentSupportedFileHeldLedgerTests`), never
        magically found."""
        report = scenario.run_scenario(self.store, self._doc(), self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["sources"][0]["state"], "PARSE_FAILED")
        self.assertIn("not found", report["sources"][0]["hold_reason"])

    def test_an_absolute_locator_is_unaffected_by_scenario_path(self):
        absolute_fixture = LOCAL_FIXTURES / "notes.md"
        scenario_path = self.scenario_dir / "scenario.json"
        doc = [
            _brief_step(),
            {"action": "add_source", "fixture": str(absolute_fixture), "owner": "speaker@example.com",
             "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1"},
        ]
        scenario_path.write_text(json.dumps(doc))
        report = scenario.run_scenario(self.store, doc, self.root / "report", scenario_path=scenario_path)
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["sources"][0]["uri"], str(absolute_fixture))
        self.assertEqual(report["sources"][0]["state"], "CURATED")

    def test_the_cli_scenario_flag_provides_the_same_base_context(self):
        scenario_path = self.scenario_dir / "cli-scenario.json"
        scenario_path.write_text(json.dumps(self._doc()))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "cli-ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["data"]
        self.assertTrue(data["ok"], data.get("refusal"))
        self.assertEqual(data["sources"][0]["uri"], "my-notes.md")
        self.assertEqual(data["sources"][0]["state"], "CURATED")


class NonexistentSupportedFileHeldLedgerTests(unittest.TestCase):
    """A `local`-origin `uri` ending in a recognized/supported local
    upload extension that doesn't (yet) resolve to a real file on disk is
    held (`PARSE_FAILED`) -- a real ledger row is still created -- rather
    than aborting ingestion before any row exists at all. An unsupported
    extension is still a clean, immediate refusal exactly as before."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")
        self.conn = self.store.connect("workspace:probe")
        self.staging_dir = self.store.workspace_dir("workspace:probe") / "staging"

    def tearDown(self):
        self.conn.close()
        cleanup(self.root)

    def _ingest(self, **payload):
        return ingest_mod.ingest_source(self.conn, "workspace:probe", payload, actor="T", staging_dir=self.staging_dir)

    def test_a_nonexistent_supported_extension_file_is_held_not_refused(self):
        for ext in (".md", ".pdf", ".docx", ".pptx", ".vtt", ".json", ".png"):
            with self.subTest(ext=ext):
                source = self._ingest(
                    fixture=f"missing-{ext.strip('.')}{ext}", owner="speaker@example.com",
                    permissionState="authorized", aclSnapshot="owner-only", version="v1",
                )
                self.assertEqual(source.state, "PARSE_FAILED")
                self.assertIn("not found", source.hold_reason)
                self.assertIn(f"missing-{ext.strip('.')}{ext}", source.hold_reason)

    def test_the_held_source_still_occupies_a_real_bundle_slot_and_is_listed(self):
        source = self._ingest(
            fixture="missing.md", owner="speaker@example.com", permissionState="authorized",
            aclSnapshot="owner-only", version="v1",
        )
        listed = ingest_mod.find_active_source_by_uri(self.conn, "workspace:probe", "missing.md")
        self.assertIsNotNone(listed)
        self.assertEqual(listed.id, source.id)

    def test_an_unsupported_extension_nonexistent_file_still_raises(self):
        with self.assertRaises(EngineError) as ctx:
            self._ingest(
                origin="local", sourceType="local_upload", uri="missing-file.xyz",
                owner="speaker@example.com", permissionState="authorized",
                aclSnapshot="owner-only", version="v1",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertIn("local file not found", ctx.exception.message)

    def test_an_unreadable_existing_file_still_raises_source_unauthorized(self):
        """FR-SRC-4's own independent filesystem re-verification is never
        weakened by the new held-state behavior above -- only a
        genuinely *missing* file is ever held; a real, but unreadable,
        one is still an explicit refusal."""
        unreadable = self.root / "secret.md"
        unreadable.write_text("secret content")
        os.chmod(unreadable, 0o000)
        try:
            if os.access(unreadable, os.R_OK):
                self.skipTest("running with elevated privileges that bypass chmod 000")
            with self.assertRaises(EngineError) as ctx:
                self._ingest(
                    fixture=str(unreadable), owner="speaker@example.com", permissionState="authorized",
                    aclSnapshot="owner-only", version="v1",
                )
            self.assertEqual(ctx.exception.code, "SOURCE_UNAUTHORIZED")
        finally:
            os.chmod(unreadable, 0o644)

    def test_a_held_source_is_observable_through_a_full_run_scenario_walk(self):
        doc = [
            _brief_step(),
            {"action": "add_source", "document": "not-yet-uploaded.pdf", "owner": "speaker@example.com",
             "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1"},
        ]
        report = scenario.run_scenario(self.store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertIsNone(report["refusal"])
        (source,) = report["sources"]
        self.assertEqual(source["state"], "PARSE_FAILED")
        self.assertEqual(source["origin"], "local")


class DefaultLocalClassificationSafetyTests(unittest.TestCase):
    """The conservative, `add_source`-only default-local rule: fires only
    for a descriptor that is unambiguously a manual/local upload once
    every existing, universal inference mechanism has already had its
    chance and found nothing -- never for anything that could plausibly
    be a remote/opaque reference."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")

    def tearDown(self):
        cleanup(self.root)

    def _run(self, source_entry: dict) -> dict:
        doc = [_brief_step(), {"action": "add_source", **source_entry}]
        return scenario.run_scenario(self.store, doc, self.root / "report")

    def test_title_and_content_only_no_filename_or_source_type_classifies_local_and_ingests(self):
        """The gap this rule closes: `_apply_manual_upload_hint` already
        synthesizes a `manual-upload:<hash>` `uri` for this shape, but
        that synthetic `uri` has no extension `infer_origin` can use --
        without this rule the descriptor was refused
        `origin must be one of [...]` despite already being unambiguously
        local."""
        report = self._run({
            "title": "Adoption Notes", "content": "Adoption grew 42% quarter over quarter.",
            "owner": "speaker@example.com", "permissionState": "authorized",
            "aclSnapshot": "owner-only", "version": "v1",
        })
        self.assertTrue(report["ok"], report.get("refusal"))
        (source,) = report["sources"]
        self.assertEqual(source["origin"], "local")
        self.assertEqual(source["source_type"], "local_upload")
        self.assertEqual(source["state"], "CURATED")

    def test_bare_content_only_no_hint_at_all_classifies_local_but_still_needs_a_locator(self):
        """"Contains inline content" alone is enough to classify `local`
        -- but classification is not a substitute for a real locator: a
        descriptor this bare still fails afterward for a separate,
        specific, honest reason (never silently authorized as a source
        with no identity at all)."""
        report = self._run({
            "content": "Bare content, nothing else.", "owner": "speaker@example.com",
            "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
        })
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertNotIn("origin must be one of", report["refusal"]["message"])

    def test_an_http_url_via_a_new_alias_is_never_defaulted_to_local(self):
        report = self._run({
            "reference": "https://example.com/some/unrecognized/host/notes.md",
            "owner": "speaker@example.com", "permissionState": "authorized",
            "aclSnapshot": "owner-only", "version": "v1",
        })
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("origin must be one of", report["refusal"]["message"])

    def test_a_github_locator_is_never_defaulted_to_local(self):
        report = self._run({
            "reference": "https://github.com/org/repo/issues/1", "owner": "org/repo",
            "permissionState": "authorized", "aclSnapshot": "public", "version": "v1",
            "content": "issue body",
        })
        # Classified `github` (never `local`) by the existing, unchanged
        # `infer_origin` host tier -- still correctly refused for lacking
        # a `sourceType`, never silently authorized as anything.
        self.assertFalse(report["ok"])
        self.assertNotIn("origin must be one of", report["refusal"]["message"])

    def test_a_workiq_source_type_with_content_and_no_uri_is_never_defaulted_to_local(self):
        report = self._run({
            "sourceType": "sharepoint_doc", "content": "doc body", "owner": "data-team@example.com",
            "permissionState": "authorized", "aclSnapshot": "site:talks", "version": "v1",
        })
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("uri is required", report["refusal"]["message"])

    def test_a_contradictory_connector_hint_is_never_overridden_by_default_local(self):
        report = self._run({
            "origin": "workiq", "reference": "https://contoso.sharepoint.com/sites/x/doc.docx",
            "sourceType": "sharepoint_doc", "owner": "data-team@example.com",
            "permissionState": "authorized", "aclSnapshot": "site:talks", "version": "v1",
            "content": "doc body",
        })
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["sources"][0]["origin"], "workiq")

    def test_default_local_is_scoped_to_add_source_and_never_applies_to_the_raw_engine_api(self):
        """The identical bare-content-only descriptor that `run_scenario`
        already classifies `local` above is still refused exactly as
        before this hardening cycle when `ingest.ingest_source` is called
        directly (the raw `source ingest` CLI contract) -- proving the
        default-local rule lives only in `engine.scenario`, never in
        `engine.ingest`'s own shared, direct API."""
        conn = self.store.connect("workspace:direct-probe")
        staging_dir = self.store.workspace_dir("workspace:direct-probe") / "staging"
        try:
            with self.assertRaises(EngineError) as ctx:
                ingest_mod.ingest_source(conn, "workspace:direct-probe", {
                    "content": "Bare content, nothing else.", "owner": "speaker@example.com",
                    "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
                }, actor="T", staging_dir=staging_dir)
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        finally:
            conn.close()


class UnknownRemoteReferenceRejectionTests(unittest.TestCase):
    """Opaque/unrecognized remote references -- an unfamiliar scheme, or
    a bare, arbitrary-looking name/id given through one of this hardening
    cycle's own new locator field names -- are never silently accepted as
    a source, with or without the new vocabulary."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")

    def tearDown(self):
        cleanup(self.root)

    def _run(self, source_entry: dict) -> dict:
        doc = [_brief_step(), {"action": "add_source", **source_entry}]
        return scenario.run_scenario(self.store, doc, self.root / "report")

    def test_an_opaque_custom_scheme_reference_is_refused(self):
        report = self._run({
            "reference": "opaque-service://record/12345", "owner": "speaker@example.com",
            "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
        })
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_a_bare_arbitrary_id_via_the_document_alias_is_refused_never_accepted(self):
        """Item 4's own "do not accept arbitrary names/IDs as sources" --
        a bare ticket-shaped identifier is never treated as a genuine
        locator merely for having been given through a new,
        locator-flavored field name."""
        report = self._run({
            "document": "PROJ-1234", "owner": "speaker@example.com", "permissionState": "authorized",
            "aclSnapshot": "owner-only", "version": "v1",
        })
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_a_bare_arbitrary_id_with_no_recognized_field_name_at_all_is_refused(self):
        report = self._run({
            "someInternalTicketId": "PROJ-1234", "owner": "speaker@example.com",
            "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
        })
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")


class DescriptorPresenceWithoutKnownKeyTests(unittest.TestCase):
    """Item 4: a source action naming exactly one non-control child whose
    own content carries no recognized descriptor signal at all is neither
    silently accepted nor left to fail downstream with a confusing,
    generic error -- it is refused with a clear, dedicated message naming
    the offending field, unless the descriptor's *other* fields already
    stand on their own."""

    def test_a_lone_signal_free_object_child_is_refused_with_a_clear_message(self):
        doc = [{"action": "add_source", "myWeirdField": {"blob": "xyz", "nested": {"deep": 1}}}]
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc(doc)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertIn("myWeirdField", ctx.exception.message)
        self.assertIn("does not carry a recognized source", ctx.exception.message)

    def test_a_real_uri_alongside_an_unrelated_signal_free_sibling_object_still_works(self):
        """An incidental, unrelated object sitting next to an
        already-sufficient descriptor is never treated as a competing
        candidate -- the real descriptor is used exactly as before."""
        doc = [{"action": "add_source", "uri": "notes.md", "internalTags": {"team": "x"},
                "owner": "speaker@example.com", "permissionState": "authorized",
                "aclSnapshot": "owner-only", "version": "v1", "content": "text"}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"][0]["uri"], "notes.md")

    def test_two_signal_free_candidates_is_ambiguous_and_falls_through_unchanged(self):
        """Never a guess between two equally opaque candidates -- falls
        through to the pre-existing, unchanged direct-descriptor path,
        which fails its own downstream validation exactly as it always
        has (never this check's own message)."""
        doc = [{"action": "add_source", "fieldA": {"x": 1}, "fieldB": {"y": 2}}]
        merged = scenario._normalize_scenario_doc(doc)
        # No exception from the signal-free check itself; the descriptor
        # is passed through unresolved and refused later at ingest time
        # for lacking any real origin/uri -- proven at the full-pipeline
        # level in `UnknownRemoteReferenceRejectionTests` above.
        self.assertEqual(len(merged["sources"]), 1)

    def test_an_empty_object_child_still_raises_its_own_pre_existing_message(self):
        """The pre-existing (Dark Factory hardening cycle 11) empty-
        candidate check is unaffected by the new signal-free check added
        alongside it."""
        doc = [{"action": "add_source", "envelope": {}}]
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc(doc)
        self.assertIn("non-empty source descriptor", ctx.exception.message)


class FullOrderedJourneyFixtureReferenceVocabularyTests(unittest.TestCase):
    """The complete, manual-only public ordered-action-list journey --
    brief through Stage package -- using *only* this hardening cycle's
    new fixture/reference vocabulary for every source, including one
    resolved relatively against the scenario document's own directory,
    run through the real public `bin/throughline` CLI entry point."""

    def setUp(self):
        self.root = new_root()
        self.scenario_dir = self.root / "scenarios"
        self.scenario_dir.mkdir(parents=True)
        (self.scenario_dir / "adoption-notes.md").write_text(
            "Throughline adoption grew 42% quarter over quarter across pilot teams.\n\n"
            "Speakers using structured evidence review reported higher confidence rehearsing Q&A."
        )

    def tearDown(self):
        cleanup(self.root)

    def _doc(self) -> list[dict]:
        github_payload = json.loads((REPO_ROOT / "tests" / "fixtures" / "github" / "release_notes.json").read_text())
        workiq_payload = json.loads((REPO_ROOT / "tests" / "fixtures" / "workiq" / "sharepoint_doc.json").read_text())
        return [
            _brief_step(),
            # local, via the new `fixture` alias, resolved relatively
            # against the scenario document's own directory.
            {"action": "add_source", "fixture": "adoption-notes.md", "owner": "speaker@example.com",
             "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1"},
            # github, via the new `reference` alias.
            {"action": "add_source", "reference": github_payload.pop("uri"), **github_payload},
            # workiq, via the new `document` alias.
            {"action": "add_source", "document": workiq_payload.pop("uri"), **workiq_payload},
            {"action": "propose_claim", "type": "factual",
             "text": "Throughline adoption grew 42% quarter over quarter.",
             "evidenceLocators": ["adoption-notes.md#p0"], "approve": True},
            {"action": "propose_claim", "type": "interpretive",
             "text": "This suggests structured evidence review meaningfully reduces talk-prep risk.",
             "evidenceLocators": ["adoption-notes.md#p1"],
             "rationale": "Confidence increase correlates with the adoption stat.", "approve": True},
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
            {"action": "propose_route", "label": "Short alt route", "beats": [
                {"role": "HOOK", "headline": "Alt hook", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "Alt ask", "timeBudgetSeconds": 60},
            ]},
            {"action": "select_narrative_route", "value": 0},
            {"action": "set_demo_asset", "slideRole": "MECHANISM", "livePath": "cli-session://live-terminal",
             "prerecordedAssetPath": str(self.scenario_dir / "adoption-notes.md"),
             "staticAssetPath": str(self.scenario_dir / "adoption-notes.md"),
             "verbalRecoveryScript": "I will narrate the ledger flow verbally if the live demo fails."},
            {"action": "rehearse", "run": {
                "HOOK": 58, "STAKES": 95, "TURN": 88, "MECHANISM": 130, "PROOF": 85, "OBJECTION": 92, "ASK": 55,
            }},
            {"action": "export", "target": "pptx"},
            {"action": "export", "target": "package"},
            {"action": "approve_stage", "value": "Dr. Jamie Rivera"},
        ]

    def test_the_full_journey_completes_via_run_scenario_directly(self):
        store = persistence.Store(root=self.root / "ws")
        scenario_path = self.scenario_dir / "scenario.json"
        doc = self._doc()
        scenario_path.write_text(json.dumps(doc))
        report = scenario.run_scenario(store, doc, self.root / "report", scenario_path=scenario_path)
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertIsNone(report["refusal"])
        self.assertEqual(len(report["sources"]), 3)
        self.assertEqual(sorted(s["origin"] for s in report["sources"]), ["github", "local", "workiq"])
        local_source = next(s for s in report["sources"] if s["origin"] == "local")
        self.assertEqual(local_source["uri"], "adoption-notes.md")
        self.assertTrue(report["stageGate"]["passed"])
        self.assertIn("package", report)
        self.assertEqual(report["workspace"]["stageApprovedBy"], "Dr. Jamie Rivera")

    def test_the_full_journey_completes_through_the_public_cli(self):
        scenario_path = self.scenario_dir / "cli-scenario.json"
        scenario_path.write_text(json.dumps(self._doc()))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "cli-ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"])
        data = envelope["data"]
        self.assertTrue(data["ok"], data.get("refusal"))
        self.assertEqual(len(data["sources"]), 3)
        self.assertTrue(data["stageGate"]["passed"])
        self.assertEqual(
            set(data["exports"][1]["artifactKinds"]),
            {
                "EDITABLE_DECK", "SPEAKER_NOTES_DOC", "ACCESSIBLE_PDF", "EVIDENCE_APPROVAL_MANIFEST",
                "CAPTION_SCRIPT", "DEMO_ASSETS", "OFFLINE_BACKUP", "PANIC_DECK", "LAST_KNOWN_GOOD",
            },
        )


if __name__ == "__main__":
    unittest.main()
