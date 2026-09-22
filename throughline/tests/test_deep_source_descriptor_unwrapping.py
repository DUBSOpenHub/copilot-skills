"""Regression tests for deeply-nested source descriptor unwrapping and
generic field/manual-upload recognition (Dark Factory hardening cycle 10,
acceptance pass 13: `engine/scenario._unwrap_nested_source_descriptor` /
`engine/ingest.py`'s widened `SOURCE_PAYLOAD_FIELD_ALIASES` and new
`_apply_manual_upload_hint`).

Compatibility gap this closes: an `add_source`/`ingest_source` action-list
element's inline payload previously unwrapped only *one* layer of the six
generic wrapper keys (`source`/`descriptor`/`value`/`payload`/`params`/
`input`) or a `sources` list -- a caller composing its own generic
envelope conventions two or more layers deep (e.g. `{"payload":
{"source": {...}}}`, or a `sources` list entry that is itself
`{"descriptor": {...}}`) left the real `FetchResult` fields nested one
level too deep for connector/origin inference to ever see them, so the
descriptor's `origin` (and every other field) stayed unresolved and the
whole ingestion was refused with `VALIDATION_ERROR: origin must be one of
[...]` -- leaving `sources`/`evidence` empty even though the descriptor's
real fields were present, just more deeply wrapped than the prior single-
layer unwrap reached.

Separately, a descriptor naming its own resource only via a `filename`/
`file` display hint (never a real filesystem path) plus literal inline
`content` -- or via an explicit `sourceType`/`origin` plus content and no
location field at all -- previously failed `uri is required` or (if a
bare hint happened to coincide with a real on-disk file) attempted a
filesystem read for content that was never meant to be read from disk.
Both are now recognized, conservatively, as an authorized local/manual
upload through the exact same in-memory ingestion path an explicit
`sourceType: "local_paste"` descriptor already uses.
"""
from __future__ import annotations

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


def _fetch_result(uri: str, **overrides) -> dict:
    payload = {
        "sourceType": "local_paste", "uri": uri, "owner": "speaker@example.com",
        "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
        "content": "Some evidence content worth citing in the talk.",
    }
    payload.update(overrides)
    return payload


class DeeplyNestedWrapperUnwrapUnitTests(unittest.TestCase):
    """Direct, in-process coverage of `_unwrap_nested_source_descriptor`
    and its wiring into `_normalize_source_action_entries`."""

    def test_a_two_level_wrapper_nest_unwraps_fully(self):
        doc = [{"action": "add_source", "payload": {"source": _fetch_result("paste:two-level")}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [_fetch_result("paste:two-level")])

    def test_a_three_level_wrapper_nest_unwraps_fully(self):
        doc = [{"action": "add_source", "params": {"input": {"descriptor": _fetch_result("paste:three-level")}}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [_fetch_result("paste:three-level")])

    def test_a_four_level_wrapper_nest_unwraps_fully(self):
        doc = [{"action": "add_source", "value": {"payload": {"params": {"input": _fetch_result("paste:four-level")}}}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [_fetch_result("paste:four-level")])

    def test_a_sources_list_entry_that_is_itself_wrapped_unwraps(self):
        doc = [{"action": "add_source", "sources": [{"descriptor": _fetch_result("paste:list-wrapped")}]}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [_fetch_result("paste:list-wrapped")])

    def test_a_one_element_sources_list_nested_inside_another_wrapper_unwraps(self):
        """The mission's seventh recursively-unwrappable form: a
        one-element `sources` list is itself just another synonym for
        "this value, unwrapped", so it may also appear *nested* inside
        one of the six generic wrapper keys."""
        doc = [{"action": "add_source", "source": {"sources": [_fetch_result("paste:nested-list")]}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [_fetch_result("paste:nested-list")])

    def test_nested_sibling_metadata_merges_safely_with_a_deeper_wrapper(self):
        """A wrapper key at a *nested* level (never the outermost
        action-entry level, which keeps its own pre-existing strict
        no-mixing rule) may coexist with genuine sibling metadata; the
        two merge into one flat descriptor."""
        doc = [{
            "action": "add_source",
            "payload": {"descriptor": _fetch_result("paste:merge-safely", owner="ada@example.com"), "title": "Adoption Notes"},
        }]
        merged = scenario._normalize_scenario_doc(doc)
        item = merged["sources"][0]
        self.assertEqual(item["uri"], "paste:merge-safely")
        self.assertEqual(item["owner"], "ada@example.com")
        self.assertEqual(item["title"], "Adoption Notes")

    def test_conflicting_nested_sibling_metadata_is_a_clean_validation_error(self):
        doc = [{
            "action": "add_source",
            "payload": {"descriptor": _fetch_result("paste:conflict", owner="ada@example.com"), "owner": "grace@example.com"},
        }]
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc(doc)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_two_wrapper_keys_at_the_same_nested_level_is_ambiguous(self):
        doc = [{
            "action": "add_source",
            "payload": {"source": _fetch_result("paste:a"), "descriptor": _fetch_result("paste:b")},
        }]
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc(doc)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_the_outermost_level_still_rejects_a_wrapper_mixed_with_a_sibling(self):
        """Pins the pre-existing, unaffected outermost-level behavior: a
        wrapper key alongside a sibling field at the very top of the
        action-list element's own payload (as opposed to a level
        *underneath* an already-chosen wrapper) is still unconditionally
        ambiguous, never merged."""
        doc = [{"action": "add_source", "source": _fetch_result("paste:a"), "owner": "someone@example.com"}]
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc(doc)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_non_object_value_at_the_bottom_of_the_nest_is_returned_unchanged(self):
        self.assertEqual(scenario._unwrap_nested_source_descriptor("plain-string", "add_source", 0), "plain-string")
        self.assertEqual(scenario._unwrap_nested_source_descriptor(42, "add_source", 0), 42)
        self.assertEqual(scenario._unwrap_nested_source_descriptor({}, "add_source", 0), {})


class DeeplyNestedWrapperEndToEndTests(unittest.TestCase):
    """End-to-end coverage: a deeply wrapped, originless descriptor
    ingests and derives evidence exactly like the identical direct-field
    descriptor would."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_a_deeply_wrapped_originless_descriptor_ingests_and_derives_evidence(self):
        doc = [
            _brief_step(),
            {"action": "add_source", "payload": {"source": {
                "sourceType": "local_paste", "uri": "paste:deep-originless", "owner": "speaker@example.com",
                "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
                "content": "Adoption grew 42% quarter over quarter across every pilot team surveyed.",
            }}},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["sources"]), 1)
        self.assertEqual(report["sources"][0]["origin"], "local")
        self.assertTrue(any(s["action"] == "evidence.extract" and s["atomCount"] > 0 for s in report["steps"]))

    def test_a_deeply_wrapped_descriptor_reaches_the_stage_package(self):
        """A full journey using a source nested four wrappers deep,
        proving the fix composes with narrative/compile/gates/export
        exactly like an unwrapped descriptor would."""
        doc = [
            _brief_step(),
            {"action": "add_source", "params": {"payload": {"source": {"descriptor": {
                "sourceType": "local_paste", "uri": "paste:deep-stage", "owner": "speaker@example.com",
                "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
                "content": "Adoption grew 42% quarter over quarter across every pilot team surveyed.",
            }}}}},
            {"action": "propose_claim", "type": "factual", "text": "Adoption grew 42% quarter over quarter.",
             "evidenceLocators": ["paste:deep-stage"], "approve": True},
            {"action": "select_narrative_route", "value": 0},
            {"action": "compile_deck"},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)

    def test_the_identical_deep_wrap_via_the_cli_subprocess_exits_zero(self):
        doc = [
            _brief_step(),
            {"action": "add_source", "payload": {"source": {
                "sourceType": "local_paste", "uri": "paste:deep-cli", "owner": "speaker@example.com",
                "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
                "content": "Adoption grew 42% quarter over quarter across every pilot team surveyed.",
            }}},
        ]
        scenario_path = self.root / "deep-wrap-scenario.json"
        scenario_path.write_text(json.dumps(doc))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))


class GenericFieldAliasUnitTests(unittest.TestCase):
    """Direct coverage of the widened `SOURCE_PAYLOAD_FIELD_ALIASES`
    table: `kind`/`format` as `sourceType`, `url`/`href`/`web_url` as
    `uri`."""

    def test_kind_resolves_to_source_type(self):
        result = ingest_mod.normalize_source_payload({"kind": "github_issue"})
        self.assertEqual(result["sourceType"], "github_issue")

    def test_format_resolves_to_source_type(self):
        result = ingest_mod.normalize_source_payload({"format": "pdf"})
        self.assertEqual(result["sourceType"], "pdf")

    def test_url_resolves_to_uri(self):
        result = ingest_mod.normalize_source_payload({"url": "https://github.com/org/repo/issues/1"})
        self.assertEqual(result["uri"], "https://github.com/org/repo/issues/1")

    def test_href_resolves_to_uri(self):
        result = ingest_mod.normalize_source_payload({"href": "https://contoso.sharepoint.com/doc.docx"})
        self.assertEqual(result["uri"], "https://contoso.sharepoint.com/doc.docx")

    def test_web_url_resolves_to_uri(self):
        result = ingest_mod.normalize_source_payload({"web_url": "https://contoso.sharepoint.com/doc.docx"})
        self.assertEqual(result["uri"], "https://contoso.sharepoint.com/doc.docx")

    def test_an_explicit_uri_is_never_overridden_by_url_href_or_web_url(self):
        result = ingest_mod.normalize_source_payload({"uri": "kept", "url": "ignored", "href": "also-ignored"})
        self.assertEqual(result["uri"], "kept")

    def test_conflicting_kind_and_format_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            ingest_mod.normalize_source_payload({"kind": "markdown", "format": "pdf"})
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_kind_field_ingests_end_to_end_through_the_action_list(self):
        doc = [{"action": "add_source", "kind": "github_issue", "url": "https://github.com/example-org/repo/issues/9",
                "owner": "example-org/repo", "permissionState": "authorized", "aclSnapshot": "public-repo",
                "version": "v1", "content": "GitHub-sourced evidence text."}]
        merged = scenario._normalize_scenario_doc(doc)
        item = merged["sources"][0]
        self.assertEqual(item["sourceType"], "github_issue")
        self.assertEqual(item["uri"], "https://github.com/example-org/repo/issues/9")


class ManualUploadHintUnitTests(unittest.TestCase):
    """Direct, in-process coverage of `ingest._apply_manual_upload_hint`
    -- a `filename`/`file` naming hint, or a bare `sourceType`, together
    with literal inline content and *no* real location field at all,
    never has to name a real on-disk file."""

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

    def test_filename_plus_content_and_no_other_signal_ingests_as_local(self):
        source = self._ingest(
            filename="adoption-notes.md", owner="speaker@example.com", permissionState="authorized",
            aclSnapshot="owner-only", version="v1", content="Adoption grew 42% quarter over quarter.",
        )
        self.assertEqual(source.origin, "local")
        self.assertEqual(source.uri, "adoption-notes.md")
        self.assertEqual(source.state, "AUTHORIZED")

    def test_file_field_is_an_equally_accepted_naming_hint(self):
        source = self._ingest(
            file="report.pdf", owner="speaker@example.com", permissionState="authorized",
            aclSnapshot="owner-only", version="v1", content="Some pasted report content.",
        )
        self.assertEqual(source.origin, "local")
        self.assertEqual(source.uri, "report.pdf")

    def test_an_explicit_source_type_survives_the_filename_hint_completely_untouched(self):
        source = self._ingest(
            filename="adoption-notes.md", sourceType="markdown", owner="speaker@example.com",
            permissionState="authorized", aclSnapshot="owner-only", version="v1",
            content="Adoption grew 42% quarter over quarter.",
        )
        self.assertEqual(source.source_type, "markdown")
        self.assertEqual(source.origin, "local")

    def test_no_real_on_disk_file_is_ever_required_for_a_filename_hinted_upload(self):
        """The whole point of the hint: `adoption-notes.md` is not read
        from any real filesystem location, so a nonexistent path never
        raises `local file not found`."""
        source = self._ingest(
            filename="a-file-that-does-not-exist-anywhere.md", owner="speaker@example.com",
            permissionState="authorized", aclSnapshot="owner-only", version="v1",
            content="Content that only ever lives in memory.",
        )
        self.assertEqual(source.state, "AUTHORIZED")

    def test_content_plus_explicit_source_type_with_no_filename_or_uri_ingests(self):
        source = self._ingest(
            sourceType="markdown", owner="speaker@example.com", permissionState="authorized",
            aclSnapshot="owner-only", version="v1", content="Type-only inline content, no filename or uri.",
        )
        self.assertEqual(source.origin, "local")
        self.assertEqual(source.source_type, "markdown")
        self.assertTrue(source.uri)

    def test_two_byte_identical_type_only_uploads_resolve_to_the_same_synthetic_identity(self):
        first = self._ingest(
            sourceType="markdown", owner="speaker@example.com", permissionState="authorized",
            aclSnapshot="owner-only", version="v1", content="Identical inline content.",
        )
        second = ingest_mod.normalize_source_payload({
            "sourceType": "markdown", "content": "Identical inline content.",
        })
        self.assertEqual(first.uri, second["uri"])

    def test_two_different_type_only_uploads_never_collide(self):
        first = ingest_mod.normalize_source_payload({"sourceType": "markdown", "content": "Content A."})
        second = ingest_mod.normalize_source_payload({"sourceType": "markdown", "content": "Content B."})
        self.assertNotEqual(first["uri"], second["uri"])

    def test_no_hint_and_no_source_type_at_all_never_synthesizes_a_uri(self):
        """Direct coverage of the hint function itself: bare content with
        neither a naming hint nor an explicit `sourceType` gives no
        confident signal at all, so no `uri` is synthesized -- whichever
        pre-existing validation applies first (here, `origin`) still
        refuses exactly as before."""
        result = ingest_mod.normalize_source_payload({
            "owner": "speaker@example.com", "permissionState": "authorized",
            "aclSnapshot": "owner-only", "version": "v1", "content": "Bare content, nothing else.",
        })
        self.assertNotIn("uri", result)
        with self.assertRaises(EngineError) as ctx:
            self._ingest(
                owner="speaker@example.com", permissionState="authorized", aclSnapshot="owner-only",
                version="v1", content="Bare content, nothing else.",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_github_source_type_with_no_uri_is_still_correctly_refused(self):
        """The manual-upload hint never rescues a connector that always
        names a real remote resource -- github/workiq still require a
        genuine `uri`, never a synthesized one."""
        with self.assertRaises(EngineError) as ctx:
            self._ingest(
                sourceType="github_issue", owner="example-org/repo", permissionState="authorized",
                aclSnapshot="public-repo", version="v1", content="GitHub content with no uri.",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertIn("uri is required", ctx.exception.message)

    def test_an_explicit_workiq_origin_with_no_uri_is_still_correctly_refused(self):
        with self.assertRaises(EngineError) as ctx:
            self._ingest(
                origin="workiq", sourceType="sharepoint_doc", filename="notes.md", owner="speaker@example.com",
                permissionState="authorized", aclSnapshot="site:talks", version="v1",
                content="WorkIQ content with a filename hint.",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertIn("uri is required", ctx.exception.message)

    def test_a_real_uri_is_never_overridden_by_a_sibling_filename_hint(self):
        """A genuine location-claiming field always wins -- the hint is
        only ever consulted when `uri` (and every one of its existing
        aliases) is completely absent. (Dark Factory hardening cycle 12:
        a nonexistent path with a recognized local extension no longer
        aborts ingestion outright -- it is held, `PARSE_FAILED` -- but
        the held source's own `uri`/`hold_reason` still prove the real,
        explicit `uri` was never overridden by the sibling hint.)"""
        # Points at a real, nonexistent path -- the hint must not rescue
        # it, since a real `uri` was explicitly claimed.
        source = self._ingest(
            uri="a-path-that-does-not-exist.md", filename="ignored-hint.md", owner="speaker@example.com",
            permissionState="authorized", aclSnapshot="owner-only", version="v1", content="text",
        )
        self.assertEqual(source.uri, "a-path-that-does-not-exist.md")
        self.assertEqual(source.state, "PARSE_FAILED")
        self.assertIn("local file not found", source.hold_reason)
        self.assertIn("a-path-that-does-not-exist.md", source.hold_reason)
        self.assertNotIn("ignored-hint.md", source.hold_reason)

    def test_is_idempotent_through_normalize_source_payload(self):
        once = ingest_mod.normalize_source_payload({
            "filename": "notes.md", "content": "hello", "owner": "a@example.com",
        })
        twice = ingest_mod.normalize_source_payload(once)
        self.assertEqual(once, twice)


class ManualUploadHintActionListEndToEndTests(unittest.TestCase):
    """End-to-end coverage through the ordered action-list executor."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_an_inline_content_upload_with_no_path_reaches_the_stage_package(self):
        doc = [
            _brief_step(),
            {"action": "add_source", "filename": "adoption-notes.md", "owner": "speaker@example.com",
             "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
             "content": "Adoption grew 42% quarter over quarter across every pilot team surveyed."},
            {"action": "propose_claim", "type": "factual", "text": "Adoption grew 42% quarter over quarter.",
             "evidenceLocators": ["adoption-notes.md"], "approve": True},
            {"action": "select_narrative_route", "value": 0},
            {"action": "compile_deck"},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)

    def test_a_wrapped_filename_content_descriptor_also_ingests(self):
        """Compositional coverage: the deep-unwrap fix and the manual-
        upload-hint fix apply together, in either order."""
        doc = [
            _brief_step(),
            {"action": "add_source", "source": {
                "filename": "wrapped-notes.md", "owner": "speaker@example.com", "permissionState": "authorized",
                "aclSnapshot": "owner-only", "version": "v1", "content": "Wrapped inline content, no path.",
            }},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["sources"][0]["uri"], "wrapped-notes.md")


if __name__ == "__main__":
    unittest.main()
