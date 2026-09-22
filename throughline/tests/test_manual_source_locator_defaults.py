"""Regression tests for Dark Factory hardening cycle 13: the narrow,
`add_source`/`ingest_source`-only manual-source fallback that closes the
remaining originless-source gap `_apply_default_local_origin` (Dark
Factory hardening cycle 12) never covered.

Compatibility gap this closes: a scenario `add_source`/`ingest_source`
descriptor naming an explicit, non-remote source locator with no
recognized extension/type (an opaque fixture/manual pseudo-scheme
reference, e.g. `fixture:widget-42`, or a relative filesystem-shaped path
with no recognized extension) still reached `ingest_source` with no
`origin` at all and was refused `VALIDATION_ERROR: origin must be one of
[...]` before a ledger row could ever be created -- even though the
descriptor was unambiguously local and safe. This file covers, in one
place:

  1. The widened `_apply_default_local_origin` non-remote-locator rule
     (`engine/scenario.py`), and that it still never reclassifies an
     unknown remote scheme/host or a bare, scheme-less, separator-less
     opaque identifier (`UnknownRemoteReferenceRejectionTests`' own
     pre-existing "never a guess" contract).
  2. The further `sourceType`/`owner`/`permissionState` defaults
     (`_apply_add_source_local_defaults`) applied only to a descriptor
     already classified `local` through this exact add_source/
     ingest_source path -- never to a raw, directly-documented
     `{"sources": [...]}` field entry, and never to `ingest.
     ingest_source`'s own direct/raw-CLI contract.
  3. The `authorized`/`is_authorized`/`isAuthorized` boolean aliases for
     `permissionState` (`engine/ingest.py`'s `_apply_authorization_
     aliases`), including their conflict-rejection behavior.
  4. The opaque-locator byte-acquisition behavior: inline content is used
     directly when a `uri` has no recognized local-upload extension, and
     a still-unresolved opaque locator without content is held
     (`PARSE_FAILED`) rather than raising a bare validation failure.
  5. A full manual-only journey using only opaque fixture-style locators
     reaching the same downstream success (Stage approval, package
     export) as an equivalent journey using ordinary local descriptors.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import unittest

from helpers import DEFAULT_BRIEF, EngineError, REPO_ROOT, cleanup, ingest_mod, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _brief_step(**overrides) -> dict:
    payload = {"action": "set_talk_brief", **DEFAULT_BRIEF}
    payload.update(overrides)
    return payload


def _source_ingest_step(report: dict) -> dict:
    """The `source.ingest` entry `report["steps"]` records immediately
    after ingestion -- the ledger metadata *at ingest time*, before any
    later gate/compile phase might further transition the source's own
    `state` (e.g. `AUTHORIZED` -> `CURATED`), unlike `report["sources"]`
    (a fresh read of the *current* persisted state, attached at the very
    end of the walk)."""
    (step,) = (s for s in report["steps"] if s["action"] == "source.ingest")
    return step


class NonRemoteLocatorClassificationTests(unittest.TestCase):
    """`_apply_default_local_origin`'s widened rule (item 1): a
    non-empty `uri` that is unambiguously not a network locator
    classifies `local` even with no inline content and no manual-upload
    hint at all -- but only for a recognized local pseudo-scheme, a
    Windows drive letter, or a schemeless string that itself looks like
    a filesystem path/relative identifier (a path separator)."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")

    def tearDown(self):
        cleanup(self.root)

    def _run(self, source_entry: dict) -> dict:
        doc = [_brief_step(), {"action": "add_source", **source_entry}]
        return scenario.run_scenario(self.store, doc, self.root / "report")

    def test_every_local_pseudo_scheme_classifies_local_and_ingests(self):
        for scheme in ("file", "paste", "manual-upload", "fixture", "upload", "local"):
            with self.subTest(scheme=scheme):
                report = self._run({
                    "uri": f"{scheme}:opaque-id-{scheme}", "content": "Opaque pseudo-scheme content.",
                })
                self.assertTrue(report["ok"], report.get("refusal"))
                step = _source_ingest_step(report)
                self.assertEqual(step["origin"], "local")
                self.assertEqual(step["state"], "AUTHORIZED")

    def test_a_relative_path_with_a_separator_and_no_recognized_extension_classifies_local(self):
        """No scheme, no recognized extension, but a genuine path
        separator -- a relative filesystem-shaped identifier -- still
        classifies `local`; with no real file on disk and no inline
        content, it is held (see `OpaqueLocatorBytesTests` below), never
        refused for lacking an `origin`."""
        report = self._run({
            "uri": "fixtures/widget-without-extension", "owner": "speaker@example.com",
            "permissionState": "authorized",
        })
        self.assertTrue(report["ok"], report.get("refusal"))
        (source,) = report["sources"]
        self.assertEqual(source["origin"], "local")
        self.assertEqual(source["state"], "PARSE_FAILED")

    def test_a_windows_drive_letter_scheme_classifies_local(self):
        report = self._run({
            "uri": "C:\\fixtures\\widget-without-extension", "content": "Drive-letter opaque content.",
        })
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(_source_ingest_step(report)["origin"], "local")

    def test_a_bare_opaque_identifier_with_no_scheme_or_separator_still_refuses(self):
        """FR-SRC-1's own "never a guess" contract, unaffected by this
        hardening cycle: a schemeless, separator-less bare token (no
        inline content either) is never treated as a locator merely for
        having been supplied through `uri`."""
        report = self._run({
            "uri": "widget-42", "owner": "speaker@example.com", "permissionState": "authorized",
        })
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("origin must be one of", report["refusal"]["message"])

    def test_the_document_alias_bare_ticket_id_regression_still_refuses(self):
        """Direct regression lock for `UnknownRemoteReferenceRejectionTests.
        test_a_bare_arbitrary_id_via_the_document_alias_is_refused_never_
        accepted` (Dark Factory hardening cycle 12): a bare, ticket-shaped
        identifier given through the `document` -> `uri` alias is still
        never accepted, even after this cycle's own widened rule."""
        report = self._run({
            "document": "PROJ-1234", "owner": "speaker@example.com", "permissionState": "authorized",
        })
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_unknown_custom_remote_schemes_still_refuse_with_no_content(self):
        for uri in ("s3://bucket/key", "ftp://ftp.example.com/report.pdf", "sharepoint://doc/1",
                    "opaque-service://record/12345"):
            with self.subTest(uri=uri):
                report = self._run({
                    "uri": uri, "owner": "speaker@example.com", "permissionState": "authorized",
                })
                self.assertFalse(report["ok"])
                self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
                self.assertIn("origin must be one of", report["refusal"]["message"])


class AddSourceLocalDefaultsScopingTests(unittest.TestCase):
    """Item 2 + item 5's "prove these defaults are scenario-add-source-
    only" requirement: `sourceType`/`owner`/`permissionState` default for
    a `local`-classified `add_source`/`ingest_source` element, but never
    for a raw `{"sources": [...]}` field entry (object-form or
    field-list-form), and never for `ingest.ingest_source`'s own direct
    API -- both of which still require every field spelled out
    explicitly, exactly as before this hardening cycle."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")

    def tearDown(self):
        cleanup(self.root)

    def test_sourcetype_owner_and_permission_state_all_default_for_add_source(self):
        doc = [_brief_step(), {"action": "add_source", "uri": "fixture:defaults-widget", "content": "Some content."}]
        report = scenario.run_scenario(self.store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        step = _source_ingest_step(report)
        self.assertEqual(step["sourceType"], "local_upload")
        self.assertEqual(step["owner"], "Scenario Runner")
        self.assertEqual(step["permissionState"], "authorized")

    def test_owner_defaults_to_the_scenario_actor_not_a_fixed_string(self):
        doc = [
            {"action": "set_actor", "value": "Jamie Presenter"}, _brief_step(),
            {"action": "add_source", "uri": "fixture:owner-actor-widget", "content": "Some content."},
        ]
        report = scenario.run_scenario(self.store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(_source_ingest_step(report)["owner"], "Jamie Presenter")

    def test_ingest_source_verb_gets_the_identical_defaults_as_add_source(self):
        """`add_source` and `ingest_source` are the same public verb --
        see `_ACTION_ALIASES` -- so both must share the identical
        defaulting behavior."""
        doc = [_brief_step(), {"action": "ingest_source", "uri": "fixture:ingest-source-widget", "content": "x"}]
        report = scenario.run_scenario(self.store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        step = _source_ingest_step(report)
        self.assertEqual(step["sourceType"], "local_upload")
        self.assertEqual(step["permissionState"], "authorized")

    def test_defaults_never_apply_to_a_raw_object_form_sources_field(self):
        """The identical, otherwise-eligible descriptor -- a `local`
        pseudo-scheme locator with content, missing sourceType/owner/
        permissionState -- given through the raw, directly-documented
        `sources` field (never through `add_source`/`ingest_source`) is
        still refused exactly as before this hardening cycle."""
        doc = {"brief": DEFAULT_BRIEF, "sources": [
            {"uri": "fixture:raw-object-form-widget", "content": "Some content."},
        ]}
        report = scenario.run_scenario(self.store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_defaults_never_apply_to_a_raw_field_list_form_sources_field(self):
        doc = [
            {"brief": DEFAULT_BRIEF},
            {"sources": [{"uri": "fixture:raw-field-list-widget", "content": "Some content."}]},
        ]
        report = scenario.run_scenario(self.store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_defaults_never_apply_to_ingest_source_direct_engine_api(self):
        conn = self.store.connect("workspace:direct-probe")
        staging_dir = self.store.workspace_dir("workspace:direct-probe") / "staging"
        try:
            with self.assertRaises(EngineError) as ctx:
                ingest_mod.ingest_source(conn, "workspace:direct-probe", {
                    "uri": "fixture:direct-api-widget", "content": "Some content.",
                }, actor="T", staging_dir=staging_dir)
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
            self.assertIn("origin must be one of", ctx.exception.message)
        finally:
            conn.close()

    def test_defaults_still_apply_when_add_source_is_mixed_with_a_non_action_element(self):
        """A document mixing a plain, non-action field-list element
        (`{"actor": ...}`) with an `add_source` action is not a *true*
        action-list document (`_is_action_list_document` requires every
        element to name an action), so it executes through `_run_steps`'s
        batch path -- proving the identity-based `add_source_scope`
        tracking (rather than a marker on the descriptor dict itself)
        correctly recognizes the add_source item as eligible even on
        this code path."""
        doc = [
            {"actor": "Mixed Document Actor"}, _brief_step(),
            {"action": "add_source", "uri": "fixture:mixed-doc-widget", "content": "Some content."},
        ]
        report = scenario.run_scenario(self.store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        step = _source_ingest_step(report)
        self.assertEqual(step["owner"], "Mixed Document Actor")
        self.assertEqual(step["sourceType"], "local_upload")
        self.assertEqual(step["permissionState"], "authorized")

    def test_a_true_ordered_action_list_document_also_applies_the_defaults(self):
        """The other executor (`_run_ordered_action_list`, used for a
        *true* action-list document) applies the identical defaults --
        every element there names an action, so every "sources"
        contribution is already add_source-scoped by construction."""
        doc = [
            _brief_step(),
            {"action": "add_source", "uri": "fixture:ordered-list-widget", "content": "Some content."},
        ]
        report = scenario.run_scenario(self.store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        step = _source_ingest_step(report)
        self.assertEqual(step["sourceType"], "local_upload")
        self.assertEqual(step["owner"], "Scenario Runner")
        self.assertEqual(step["permissionState"], "authorized")


class ExplicitSignalsAreNeverUpgradedTests(unittest.TestCase):
    """Item 2's own "explicit denied/blocked/held/label-conflict states
    must remain untouched" contract: "omitted" never means "explicit but
    unwelcome" -- an explicit value of any kind always wins over these
    defaults."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")

    def tearDown(self):
        cleanup(self.root)

    def _run(self, source_entry: dict) -> dict:
        doc = [_brief_step(), {"action": "add_source", **source_entry}]
        return scenario.run_scenario(self.store, doc, self.root / "report")

    def test_explicit_denied_permission_state_is_never_upgraded_to_authorized(self):
        report = self._run({
            "uri": "fixture:explicit-denied-widget", "content": "x", "owner": "speaker@example.com",
            "permissionState": "denied",
        })
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "SOURCE_UNAUTHORIZED")

    def test_explicit_authorized_false_boolean_is_never_upgraded(self):
        report = self._run({
            "uri": "fixture:explicit-denied-bool-widget", "content": "x", "owner": "speaker@example.com",
            "authorized": False,
        })
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "SOURCE_UNAUTHORIZED")

    def test_explicit_owner_is_never_overridden_by_the_scenario_actor(self):
        doc = [
            {"action": "set_actor", "value": "Scenario Actor"}, _brief_step(),
            {"action": "add_source", "uri": "fixture:explicit-owner-widget", "content": "x",
             "owner": "explicit-owner@example.com", "permissionState": "authorized"},
        ]
        report = scenario.run_scenario(self.store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(_source_ingest_step(report)["owner"], "explicit-owner@example.com")

    def test_explicit_source_type_is_never_overridden_by_the_local_upload_default(self):
        report = self._run({
            "uri": "fixture:explicit-source-type-widget", "content": "x", "sourceType": "local_paste",
            "owner": "speaker@example.com", "permissionState": "authorized",
        })
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(_source_ingest_step(report)["sourceType"], "local_paste")

    def test_a_label_conflict_hold_is_never_touched_by_these_defaults(self):
        """FR-SRC-6: a re-ingested source whose sensitivity label changed
        since the last snapshot is held `LABEL_CONFLICT` -- this
        hardening cycle's own new defaults never interfere with that
        pre-existing hold outcome."""
        first = self._run({
            "uri": "fixture:label-conflict-widget", "content": "v1 content", "owner": "speaker@example.com",
            "permissionState": "authorized", "sensitivityLabel": "Internal",
        })
        self.assertTrue(first["ok"], first.get("refusal"))
        second_doc = [
            {"action": "add_source", "uri": "fixture:label-conflict-widget", "content": "v2 content",
             "owner": "speaker@example.com", "permissionState": "authorized", "sensitivityLabel": "Confidential"},
        ]
        second = scenario.run_scenario(self.store, second_doc, self.root / "report2")
        self.assertTrue(second["ok"], second.get("refusal"))
        conflicted = next(s for s in second["sources"] if s["sensitivity_label"] == "Confidential")
        self.assertEqual(conflicted["state"], "LABEL_CONFLICT")


class AuthorizationBooleanAliasTests(unittest.TestCase):
    """Item 3: `authorized`/`is_authorized`/`isAuthorized` boolean
    aliases for `permissionState`, normalized by `ingest.
    _apply_authorization_aliases` -- shared by every caller (raw CLI,
    scenario), never scenario-only."""

    def test_authorized_true_normalizes_to_the_authorized_string(self):
        result = ingest_mod.normalize_source_payload({"authorized": True})
        self.assertEqual(result["permissionState"], "authorized")

    def test_authorized_false_normalizes_to_the_denied_string(self):
        result = ingest_mod.normalize_source_payload({"authorized": False})
        self.assertEqual(result["permissionState"], "denied")

    def test_is_authorized_snake_case_alias_resolves(self):
        result = ingest_mod.normalize_source_payload({"is_authorized": True})
        self.assertEqual(result["permissionState"], "authorized")

    def test_is_authorized_camel_case_alias_resolves(self):
        result = ingest_mod.normalize_source_payload({"isAuthorized": True})
        self.assertEqual(result["permissionState"], "authorized")

    def test_agreeing_signals_across_multiple_fields_is_a_safe_no_op(self):
        result = ingest_mod.normalize_source_payload({
            "authorized": True, "is_authorized": True, "access": "authorized",
        })
        self.assertEqual(result["permissionState"], "authorized")

    def test_a_boolean_alias_conflicting_with_an_explicit_permission_state_rejects(self):
        with self.assertRaises(EngineError) as ctx:
            ingest_mod.normalize_source_payload({"permissionState": "authorized", "authorized": False})
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertIn("permissionState", ctx.exception.message)

    def test_two_disagreeing_boolean_aliases_rejects(self):
        with self.assertRaises(EngineError) as ctx:
            ingest_mod.normalize_source_payload({"authorized": True, "is_authorized": False})
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_authorized_alias_preserves_owner_and_acl_snapshot_metadata(self):
        result = ingest_mod.normalize_source_payload({
            "authorized": True, "author": "me@example.com", "permission_snapshot": "owner-only",
        })
        self.assertEqual(result["owner"], "me@example.com")
        self.assertEqual(result["aclSnapshot"], "owner-only")
        self.assertEqual(result["permissionState"], "authorized")

    def test_authorized_false_refuses_end_to_end_through_a_scenario(self):
        root = new_root()
        try:
            store = persistence.Store(root=root / "ws")
            doc = [_brief_step(), {
                "action": "add_source", "uri": "fixture:auth-alias-widget", "content": "x",
                "owner": "speaker@example.com", "authorized": False,
            }]
            report = scenario.run_scenario(store, doc, root / "report")
            self.assertFalse(report["ok"])
            self.assertEqual(report["refusal"]["code"], "SOURCE_UNAUTHORIZED")
        finally:
            cleanup(root)

    def test_is_authorized_true_ingests_end_to_end_through_a_scenario(self):
        root = new_root()
        try:
            store = persistence.Store(root=root / "ws")
            doc = [_brief_step(), {
                "action": "add_source", "uri": "fixture:is-auth-alias-widget", "content": "x",
                "owner": "speaker@example.com", "is_authorized": True,
            }]
            report = scenario.run_scenario(store, doc, root / "report")
            self.assertTrue(report["ok"], report.get("refusal"))
            self.assertEqual(_source_ingest_step(report)["permissionState"], "authorized")
        finally:
            cleanup(root)


class OpaqueLocatorBytesTests(unittest.TestCase):
    """Item 4: an opaque local locator's own byte-acquisition behavior --
    inline content is used directly when the `uri` carries no recognized
    local-upload extension; without content, the same descriptor is held
    (`PARSE_FAILED`), never a bare origin/validation failure, so the
    attempted source is still observable in the ledger."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")

    def tearDown(self):
        cleanup(self.root)

    def _run(self, source_entry: dict) -> dict:
        doc = [_brief_step(), {"action": "add_source", **source_entry}]
        return scenario.run_scenario(self.store, doc, self.root / "report")

    def test_opaque_locator_with_inline_content_ingests_in_memory(self):
        report = self._run({"uri": "fixture:opaque-with-content", "content": "Inline content, in memory only."})
        self.assertTrue(report["ok"], report.get("refusal"))
        step = _source_ingest_step(report)
        self.assertEqual(step["state"], "AUTHORIZED")
        self.assertEqual(step["origin"], "local")

    def test_opaque_locator_with_content_base64_ingests_in_memory(self):
        payload = base64.b64encode(b"Inline base64 bytes.").decode()
        report = self._run({"uri": "fixture:opaque-with-base64", "contentBase64": payload})
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(_source_ingest_step(report)["state"], "AUTHORIZED")

    def test_opaque_locator_without_content_is_held_and_observable_in_the_ledger(self):
        report = self._run({"uri": "fixture:opaque-no-content", "owner": "speaker@example.com",
                             "permissionState": "authorized"})
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertIsNone(report["refusal"])
        (source,) = report["sources"]
        self.assertEqual(source["origin"], "local")
        self.assertEqual(source["state"], "PARSE_FAILED")
        self.assertIn("not found", source["hold_reason"])
        self.assertIn("fixture:opaque-no-content", source["hold_reason"])

    def test_an_unrecognized_but_present_extension_with_content_ingests_via_content(self):
        """An unusual extension the MVP category allowlist doesn't
        recognize (`.customext`) still combines with a recognized local
        pseudo-scheme to classify `local`; carrying its own inline
        content, it is ingested from that content, never treated as a
        typed file the Engine must find on disk."""
        report = self._run({"uri": "fixture:widget.customext", "content": "Custom extension content."})
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(_source_ingest_step(report)["state"], "AUTHORIZED")

    def test_an_unrecognized_extension_without_content_still_hard_refuses(self):
        """No content to fall back to, and the extension isn't one of
        the MVP-supported local upload/paste families -- still a clean,
        immediate refusal, never held (held is reserved for a
        *recognized* extension, or a genuinely opaque, extension-less
        locator -- FR-SRC-1's file-type allowlist is never widened by
        this hardening cycle)."""
        report = self._run({"uri": "fixture:widget.customext", "owner": "speaker@example.com",
                             "permissionState": "authorized"})
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("local file not found", report["refusal"]["message"])

    def test_a_real_recognized_extension_locator_still_prefers_disk_over_sibling_content(self):
        """Regression lock, at the scenario layer, for `ingest.py`'s own
        `test_a_real_uri_is_never_overridden_by_a_sibling_filename_hint`:
        a genuine, typed file reference (a recognized `.md` extension)
        that doesn't exist on disk is still held for that reason, even
        when inline content also happens to be present -- a real,
        explicit locator's own extension is never silently second-
        guessed by sibling content."""
        report = self._run({
            "uri": "a-scenario-path-that-does-not-exist-anywhere.md", "content": "Should be ignored.",
            "owner": "speaker@example.com", "permissionState": "authorized",
        })
        self.assertTrue(report["ok"], report.get("refusal"))
        (source,) = report["sources"]
        self.assertEqual(source["state"], "PARSE_FAILED")
        self.assertIn("local file not found", source["hold_reason"])


class FullManualJourneyWithOpaqueFixtureIdentifiersTests(unittest.TestCase):
    """(PRD/ARCH end-to-end success criteria) A complete, manual-only
    public `run-scenario` journey whose sources are named only by opaque
    fixture-style locators -- never a real on-disk path, never an
    explicit `origin`/`sourceType`/`owner`/`permissionState` -- still
    reaches the narrative gate, a named human Stage approval, and the
    complete nine-artifact package, proving this hardening cycle's own
    fallback composes with the full existing pipeline end to end, not
    just `ingest_source` in isolation."""

    ARTIFACT_KINDS = {
        "EDITABLE_DECK", "SPEAKER_NOTES_DOC", "ACCESSIBLE_PDF", "EVIDENCE_APPROVAL_MANIFEST",
        "CAPTION_SCRIPT", "DEMO_ASSETS", "OFFLINE_BACKUP", "PANIC_DECK", "LAST_KNOWN_GOOD",
    }

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _doc(self) -> list[dict]:
        demo_asset_path = str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt")
        return [
            {"action": "set_actor", "value": "Dr. Jamie Rivera"},
            {"action": "set_talk_brief", "audience": "Conference attendees", "eventType": "keynote",
             "durationMinutes": 20, "takeaway": "Structured evidence review de-risks talks",
             "proofPoints": ["adoption stat"], "excludedTopics": [], "tone": "confident"},
            # Both sources below are opaque fixture-style locators (never
            # a real on-disk path) with no `origin`/`sourceType`/`owner`/
            # `permissionState` of their own at all -- classified `local`
            # by this hardening cycle's own widened rule, then fully
            # defaulted (sourceType -> local_upload, owner -> the actor
            # above, permissionState -> authorized).
            {"action": "add_source", "uri": "fixture:adoption-metrics",
             "content": "Adoption of structured evidence review grew 42% quarter over quarter across pilot teams."},
            {"action": "add_source", "uri": "manual-upload:qa-confidence-notes",
             "content": "Speakers using structured evidence review reported higher confidence rehearsing Q&A."},
            {"action": "propose_claim", "type": "factual",
             "text": "Adoption of structured evidence review grew 42% quarter over quarter.",
             "evidenceLocators": ["fixture:adoption-metrics"], "approve": True},
            {"action": "propose_claim", "type": "interpretive",
             "text": "This suggests structured evidence review meaningfully reduces talk-prep risk.",
             "evidenceLocators": ["manual-upload:qa-confidence-notes"],
             "rationale": "Higher rehearsal confidence correlates with reduced talk-prep risk.", "approve": True},
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

    def test_the_journey_completes_with_no_refusal(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, self._doc(), self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))

    def test_both_opaque_sources_ingest_fully_defaulted_and_classified_local(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, self._doc(), self.root / "report")
        self.assertEqual(len(report["sources"]), 2)
        self.assertTrue(all(s["origin"] == "local" for s in report["sources"]))
        self.assertTrue(all(s["source_type"] == "local_upload" for s in report["sources"]))
        self.assertTrue(all(s["owner"] == "Dr. Jamie Rivera" for s in report["sources"]))
        self.assertTrue(all(s["permission_state"] == "authorized" for s in report["sources"]))

    def test_reaches_named_human_stage_approval_and_the_full_nine_artifact_package(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, self._doc(), self.root / "report")
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertEqual(report["workspace"]["stageApprovedBy"], "Dr. Jamie Rivera")
        self.assertEqual(set(report["exports"][1]["artifactKinds"]), self.ARTIFACT_KINDS)
        self.assertEqual(report["exports"][0]["target"], "pptx")
        self.assertTrue(report["exports"][0]["path"].endswith(".pptx"))

    def test_the_identical_journey_via_the_cli_subprocess_exits_zero(self):
        scenario_path = self.root / "opaque-fixture-journey-scenario.json"
        scenario_path.write_text(json.dumps(self._doc()))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))
        self.assertTrue(envelope["data"]["stageGate"]["passed"])


if __name__ == "__main__":
    unittest.main()
