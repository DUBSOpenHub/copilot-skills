"""Regression tests for the general, structural source-descriptor
extractor (Dark Factory hardening cycle 11, acceptance pass 14:
`engine/scenario.py`'s `_is_source_descriptor_container`/
`_has_descriptor_signal`/`_unwrap_nested_source_descriptor`/
`_normalize_source_action_entries`, plus `engine/ingest.py`'s widened
`SOURCE_PAYLOAD_FIELD_ALIASES` and new `_apply_bare_scalar_field_hint`).

Compatibility gap this closes: an `add_source`/`ingest_source` action-list
element's inline payload previously only unwrapped a fixed, guessed
allowlist of six generic container-key spellings (`source`/`descriptor`/
`value`/`params`/`payload`/`input`) plus the literal `sources` list field.
A caller using *any other* wrapper spelling -- an arbitrary/nonstandard
name, however deeply nested, a scalar locator/content payload, or a list
of descriptors under a non-`sources` name -- left the real `FetchResult`
fields completely unreachable: `origin`/`uri`/... were never found, the
descriptor was refused `VALIDATION_ERROR: origin must be one of [...]`
with no origin at all, and the source ledger stayed empty even though a
real, valid descriptor was present, just differently wrapped.

The fix replaces name-based guessing with a structural, semantic-leaf-key
based discovery: a container is recognized by *what it carries*
(locator/content/type/auth metadata), never by *what it is called*.
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


# A representative sample of wrapper spellings that were never part of
# the old fixed six-name allowlist -- arbitrary, third-party-shaped,
# camelCase, snake_case, and even a name that itself looks like a plain
# English word -- proving discovery is genuinely structural, not a
# slightly-longer guessed list. Deliberately excludes `"artifact"` (and
# every other Dark Factory hardening cycle 12 locator-alias spelling,
# e.g. `"fixture"`/`"document"`/`"upload"`/`"reference"`/`"ref"`/...) --
# those now carry their own, specific "this is a `uri`" meaning (see
# `tests/test_source_reference_vocabulary_aliases.py`), so they are no
# longer *arbitrary*, generic wrapper names for this table's own purpose.
ARBITRARY_WRAPPER_NAMES = [
    "envelope", "record", "attachment", "container", "wrapperFoo", "myCustomField",
    "thirdPartyData", "fetch_result", "resource", "item", "blob", "widget",
]


class ArbitraryWrapperNameTableDrivenUnitTests(unittest.TestCase):
    """Table-driven: every wrapper name in `ARBITRARY_WRAPPER_NAMES`
    unwraps identically to the pre-existing, fixed six-name allowlist --
    proving discovery keys on the *content* carried, never the name."""

    def test_every_arbitrary_wrapper_name_unwraps_to_the_single_item(self):
        for name in ARBITRARY_WRAPPER_NAMES:
            with self.subTest(wrapper=name):
                doc = [{"action": "add_source", name: _fetch_result(f"paste:{name}")}]
                merged = scenario._normalize_scenario_doc(doc)
                self.assertEqual(merged["sources"], [_fetch_result(f"paste:{name}")])

    def test_every_arbitrary_wrapper_name_still_rejects_a_sibling_field(self):
        """The outermost level keeps its own pre-existing strict
        single-shape rule regardless of the container's own name."""
        for name in ARBITRARY_WRAPPER_NAMES:
            with self.subTest(wrapper=name):
                doc = [{"action": "add_source", name: _fetch_result("paste:a"), "owner": "someone@example.com"}]
                with self.assertRaises(EngineError) as ctx:
                    scenario._normalize_scenario_doc(doc)
                self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_semantic_leaf_key_is_never_itself_treated_as_a_container(self):
        """`owner`/`title`/... are always this level's own field value --
        never peeled through -- even when a caller supplies an object as
        their value (an unusual, malformed shape, but still never
        silently reinterpreted as a wrapper)."""
        self.assertFalse(scenario._is_source_descriptor_container("owner", {"uri": "x"}))
        self.assertFalse(scenario._is_source_descriptor_container("title", {"uri": "x"}))
        self.assertFalse(scenario._is_source_descriptor_container("uri", {"uri": "x"}))


class NestingDepthTableDrivenTests(unittest.TestCase):
    """Arbitrary wrapper names compose at arbitrary nesting depths -- a
    different, never-before-seen name at every level."""

    def test_two_three_four_and_five_level_arbitrary_nests_all_unwrap(self):
        inner = _fetch_result("paste:deep-arbitrary")
        nests = [
            {"levelOne": inner},
            {"outer": {"middle": inner}},
            {"a": {"b": {"c": inner}}},
            {"first": {"second": {"third": {"fourth": inner}}}},
        ]
        for payload in nests:
            with self.subTest(depth=len(payload)):
                doc = [{"action": "add_source", **payload}]
                merged = scenario._normalize_scenario_doc(doc)
                self.assertEqual(merged["sources"], [inner])

    def test_a_list_of_descriptors_nested_inside_an_arbitrary_container_unwraps(self):
        d1, d2 = _fetch_result("paste:nest-list-a"), _fetch_result("paste:nest-list-b")
        doc = [{"action": "add_source", "outerBox": {"innerList": [d1, d2]}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual([s["uri"] for s in merged["sources"]], ["paste:nest-list-a", "paste:nest-list-b"])


class ListValuedPayloadTableDrivenTests(unittest.TestCase):
    """Lists of descriptors under any (non-`sources`) key name -- any
    length, order always preserved."""

    def test_lists_of_one_two_and_five_descriptors_under_an_arbitrary_key(self):
        for count in (1, 2, 5):
            with self.subTest(count=count):
                items = [_fetch_result(f"paste:batch-{count}-{i}") for i in range(count)]
                doc = [{"action": "add_source", "batch": items}]
                merged = scenario._normalize_scenario_doc(doc)
                self.assertEqual([s["uri"] for s in merged["sources"]], [it["uri"] for it in items])

    def test_order_is_preserved_for_an_unsorted_batch(self):
        items = [_fetch_result("paste:z"), _fetch_result("paste:a"), _fetch_result("paste:m")]
        doc = [{"action": "add_source", "shipment": items}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual([s["uri"] for s in merged["sources"]], ["paste:z", "paste:a", "paste:m"])


class ScalarSourcePayloadTests(unittest.TestCase):
    """A bare string -- found where no recognized field name claimed it
    -- resolves to `uri` (locator-shaped) or `content` (accompanied by a
    naming/type hint), per `ingest._apply_bare_scalar_field_hint`."""

    def test_a_bare_path_like_scalar_under_an_arbitrary_key_becomes_uri(self):
        result = ingest_mod.normalize_source_payload({"reference": "adoption-notes.md"})
        self.assertEqual(result["uri"], "adoption-notes.md")

    def test_a_bare_url_scalar_under_an_arbitrary_key_becomes_uri(self):
        result = ingest_mod.normalize_source_payload({"location": "https://github.com/org/repo/issues/3"})
        self.assertEqual(result["uri"], "https://github.com/org/repo/issues/3")

    def test_a_bare_pseudo_scheme_scalar_becomes_uri(self):
        result = ingest_mod.normalize_source_payload({"handle": "paste:my-note"})
        self.assertEqual(result["uri"], "paste:my-note")

    def test_a_bare_prose_scalar_with_a_filename_sibling_becomes_content(self):
        result = ingest_mod.normalize_source_payload({"body_text": "Plain prose, no locator shape.", "filename": "n.md"})
        self.assertEqual(result["content"], "Plain prose, no locator shape.")
        self.assertEqual(result["uri"], "n.md")

    def test_a_bare_prose_scalar_with_a_source_type_sibling_becomes_content(self):
        result = ingest_mod.normalize_source_payload({"blurb": "Plain prose content.", "sourceType": "markdown"})
        self.assertEqual(result["content"], "Plain prose content.")
        self.assertTrue(result["uri"])

    def test_a_bare_prose_scalar_with_a_title_sibling_becomes_content(self):
        result = ingest_mod.normalize_source_payload({"blurb": "Plain prose content.", "title": "Adoption Notes"})
        self.assertEqual(result["content"], "Plain prose content.")
        self.assertTrue(result["uri"])

    def test_a_bare_prose_scalar_with_no_hint_at_all_is_left_untouched(self):
        """Never a guess: no locator shape and no corroborating
        naming/type hint means this stays exactly as supplied -- still
        correctly refused downstream (`uri is required`), never silently
        promoted."""
        result = ingest_mod.normalize_source_payload({"blurb": "Plain prose content, no hint anywhere."})
        self.assertNotIn("uri", result)
        self.assertNotIn("content", result)

    def test_two_unrecognized_scalar_fields_is_never_a_guess(self):
        result = ingest_mod.normalize_source_payload({"fieldA": "https://example.com/a", "fieldB": "https://example.com/b"})
        self.assertNotIn("uri", result)

    def test_a_scalar_payload_ingests_end_to_end_through_the_action_list(self):
        doc = [{"action": "add_source", "reference": "https://github.com/example-org/repo/issues/4",
                "sourceType": "github_issue", "owner": "example-org/repo", "permissionState": "authorized",
                "aclSnapshot": "public-repo", "version": "v1"}]
        merged = scenario._normalize_scenario_doc(doc)
        item = merged["sources"][0]
        self.assertEqual(item["uri"], "https://github.com/example-org/repo/issues/4")


class AncestorAndSiblingMetadataMergeTests(unittest.TestCase):
    """Metadata from ancestor/sibling containers merges into a nested
    descriptor only when unambiguous -- conflicting values are a clean
    `VALIDATION_ERROR`, never a silent pick."""

    def test_sibling_metadata_at_an_arbitrary_nested_level_merges_safely(self):
        doc = [{
            "action": "add_source",
            "wrapperA": {"wrapperB": _fetch_result("paste:merge", owner="ada@example.com"), "title": "Adoption Notes"},
        }]
        merged = scenario._normalize_scenario_doc(doc)
        item = merged["sources"][0]
        self.assertEqual(item["uri"], "paste:merge")
        self.assertEqual(item["owner"], "ada@example.com")
        self.assertEqual(item["title"], "Adoption Notes")

    def test_ancestor_metadata_merges_into_every_item_of_a_nested_list(self):
        """Shared ancestor metadata (here, a `label`) applies to *each*
        contributed descriptor in a nested list alike."""
        d1 = _fetch_result("paste:list-merge-a")
        d2 = _fetch_result("paste:list-merge-b")
        doc = [{"action": "add_source", "wrapper": {"items": [d1, d2], "label": "Confidential"}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertTrue(all(s["label"] == "Confidential" for s in merged["sources"]))

    def test_conflicting_sibling_metadata_at_a_nested_level_is_a_validation_error(self):
        doc = [{
            "action": "add_source",
            "wrapperA": {"wrapperB": _fetch_result("paste:conflict", owner="ada@example.com"), "owner": "grace@example.com"},
        }]
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc(doc)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class AmbiguousCandidateTableDrivenTests(unittest.TestCase):
    """Multiple structurally-eligible containers at the same level are
    scored (`_meets_source_identity_bar`): exactly one sufficient wins
    silently; two-or-more sufficient, or none at all, is a clear
    `VALIDATION_ERROR` -- never a silent, arbitrary pick."""

    def test_two_fully_valid_competing_containers_is_ambiguous(self):
        doc = [{"action": "add_source", "recordA": _fetch_result("paste:a"), "recordB": _fetch_result("paste:b")}]
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc(doc)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_one_sufficient_and_one_thin_incidental_container_is_not_ambiguous(self):
        """A container carrying only a weak, incidental signal (here, a
        bare `type` field with no locator/content at all) is never a
        real competing candidate -- silently ignored in favor of the one
        genuinely sufficient container."""
        doc = [{
            "action": "add_source",
            "record": _fetch_result("paste:real-one"),
            "hint": {"type": "reminder-only-no-real-signal"},
        }]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [_fetch_result("paste:real-one")])

    def test_two_thin_insufficient_containers_is_a_clear_validation_error(self):
        doc = [{
            "action": "add_source",
            "hintA": {"type": "no-locator-or-content-a"},
            "hintB": {"type": "no-locator-or-content-b"},
        }]
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc(doc)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_empty_wrapper_object_under_an_arbitrary_name_is_a_validation_error(self):
        """Generalizes the pre-existing pinned `{"source": {}}` case to
        any wrapper name: an otherwise-empty, clearly-intended container
        is still a clean refusal, never silently ignored."""
        doc = [{"action": "add_source", "envelope": {}}]
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc(doc)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_incidental_empty_sibling_dict_is_left_alone_when_the_rest_already_suffices(self):
        """An empty dict/list value is only ever a refusal when it is the
        *one* thing standing between the caller and a real descriptor --
        never for incidental, unrelated empty metadata sitting alongside
        an already-sufficient direct descriptor."""
        doc = [{"action": "add_source", **_fetch_result("paste:already-enough"), "tags": []}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"][0]["uri"], "paste:already-enough")


class ContradictoryConnectorHintTests(unittest.TestCase):
    """`connector`/`provider` are conservative synonyms for `origin`
    itself (Dark Factory hardening cycle 11) -- resolved through the
    identical `normalize_origin`/conflict-detection machinery an explicit
    `origin` field already uses."""

    def test_connector_field_resolves_to_origin(self):
        result = ingest_mod.normalize_source_payload({"connector": "github"})
        self.assertEqual(result["origin"], "github")

    def test_provider_field_resolves_to_origin(self):
        result = ingest_mod.normalize_source_payload({"provider": "SharePoint"})
        self.assertEqual(result["origin"], "SharePoint")

    def test_connector_conflicting_with_source_type_is_refused(self):
        store = persistence.Store(root=new_root() / "ws")
        conn = store.connect("workspace:probe")
        try:
            payload = {
                "connector": "workiq", "sourceType": "github_issue", "uri": "gh://org/repo/issues/1",
                "owner": "x", "permissionState": "authorized", "aclSnapshot": "y", "version": "v1", "content": "z",
            }
            with self.assertRaises(EngineError) as ctx:
                ingest_mod.ingest_source(
                    conn, "workspace:probe", payload, actor="T",
                    staging_dir=store.workspace_dir("workspace:probe") / "staging",
                )
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
            self.assertIn("conflicts", ctx.exception.message)
        finally:
            conn.close()

    def test_connector_and_provider_disagreeing_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            ingest_mod.normalize_source_payload({"connector": "github", "provider": "workiq"})
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_agreeing_connector_and_source_type_ingests_normally(self):
        store = persistence.Store(root=new_root() / "ws")
        conn = store.connect("workspace:probe")
        try:
            payload = {
                "connector": "github", "sourceType": "github_issue", "uri": "gh://org/repo/issues/2",
                "owner": "x", "permissionState": "authorized", "aclSnapshot": "y", "version": "v1", "content": "z",
            }
            source = ingest_mod.ingest_source(
                conn, "workspace:probe", payload, actor="T",
                staging_dir=store.workspace_dir("workspace:probe") / "staging",
            )
            self.assertEqual(source.origin, "github")
        finally:
            conn.close()


class ControlFieldExclusionTests(unittest.TestCase):
    """`action`, and this action-list's own actor/approver/gate/export
    field names, are never treated as descriptor content and never
    merged into a resolved descriptor, at any depth."""

    def test_an_approver_shaped_dict_sibling_is_never_treated_as_a_container(self):
        doc = [{
            "action": "add_source", **_fetch_result("paste:control-exclusion"),
            "approver": {"uri": "should-never-be-picked-up", "sourceType": "github_issue"},
        }]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"][0]["uri"], "paste:control-exclusion")

    def test_a_gate_shaped_dict_sibling_is_never_merged_into_a_nested_descriptor(self):
        doc = [{
            "action": "add_source",
            "wrapper": {"descriptorInner": _fetch_result("paste:gate-exclusion"), "gate": "evidence"},
        }]
        merged = scenario._normalize_scenario_doc(doc)
        item = merged["sources"][0]
        self.assertEqual(item["uri"], "paste:gate-exclusion")
        self.assertNotIn("gate", item)

    def test_control_keys_are_never_semantic(self):
        self.assertNotIn("actor", scenario._SOURCE_DESCRIPTOR_SEMANTIC_KEYS)
        self.assertNotIn("approver", scenario._SOURCE_DESCRIPTOR_SEMANTIC_KEYS)
        self.assertNotIn("gate", scenario._SOURCE_DESCRIPTOR_SEMANTIC_KEYS)
        # `name`/`title` remain genuine descriptor signals, never excluded
        # merely because an *unrelated* approval action also happens to
        # accept a field spelled `name`.
        self.assertIn("name", scenario._SOURCE_DESCRIPTOR_SEMANTIC_KEYS)
        self.assertIn("title", scenario._SOURCE_DESCRIPTOR_SEMANTIC_KEYS)


class ProvenanceAuditabilityTests(unittest.TestCase):
    """The original public descriptor is preserved (content redacted)
    under a non-sensitive metadata field so structural normalization
    stays auditable (Dark Factory hardening cycle 11)."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_the_ordered_action_list_ledger_preserves_the_raw_payload(self):
        doc = [
            _brief_step(),
            {"action": "add_source", "envelope": {"record": _fetch_result("paste:provenance")}},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        entry = next(e for e in report["actionResults"] if e["action"] == "add_source")
        self.assertIn("rawPayload", entry)
        self.assertIn("envelope", entry["rawPayload"])
        self.assertEqual(entry["rawPayload"]["envelope"]["record"]["uri"], "paste:provenance")

    def test_the_raw_payload_redacts_inline_content(self):
        doc = [
            _brief_step(),
            {"action": "add_source", "envelope": _fetch_result("paste:redact-check", content="Sensitive pasted text.")},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        entry = next(e for e in report["actionResults"] if e["action"] == "add_source")
        self.assertNotIn("Sensitive pasted text.", json.dumps(entry["rawPayload"]))
        self.assertIn("redacted", json.dumps(entry["rawPayload"]))

    def test_a_refused_source_action_still_preserves_its_raw_payload(self):
        """Do not silently drop attempts: even a held/refused source
        action records its original descriptor."""
        doc = [
            _brief_step(),
            {"action": "add_source", "envelope": _fetch_result("paste:refused-provenance", permissionState="denied")},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        entry = report["actionResults"][-1]
        self.assertEqual(entry["action"], "add_source")
        self.assertFalse(entry["ok"])
        self.assertIn("rawPayload", entry)
        self.assertEqual(entry["rawPayload"]["envelope"]["uri"], "paste:refused-provenance")


class IntegratedNonstandardWrapperFullJourneyTests(unittest.TestCase):
    """Full, end-to-end journey coverage: a source action using
    nonstandard wrapper names and nested descriptor data reaches the
    existing Stage package path exactly like a direct-field descriptor
    would -- proving the fix composes with evidence/claims/narrative/
    gates/export, not just isolated normalization."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_a_three_level_nonstandard_wrapped_source_reaches_the_stage_package(self):
        doc = [
            _brief_step(),
            {"action": "add_source", "thirdPartyEnvelope": {"attachment": {"payloadRecord": {
                "sourceType": "local_paste", "uri": "paste:integrated-nonstandard", "owner": "speaker@example.com",
                "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
                "content": "Adoption grew 42% quarter over quarter across every pilot team surveyed.",
            }}}},
            {"action": "propose_claim", "type": "factual", "text": "Adoption grew 42% quarter over quarter.",
             "evidenceLocators": ["paste:integrated-nonstandard"], "approve": True},
            {"action": "select_narrative_route", "value": 0},
            {"action": "compile_deck"},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)
        self.assertEqual(report["package"]["deckId"], report["package"]["deckId"])

    def test_a_list_of_nonstandard_wrapped_sources_reaches_evidence_extraction(self):
        d1 = {"action": "add_source", "recordBundle": {"items": [
            _fetch_result("paste:multi-a", content="First contributed source content."),
            _fetch_result("paste:multi-b", content="Second contributed source content."),
        ]}}
        doc = [_brief_step(), d1]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["sources"]), 2)
        self.assertTrue(all(s["origin"] == "local" for s in report["sources"]))
        ingest_steps = [s for s in report["steps"] if s["action"] == "source.ingest"]
        self.assertEqual([s["uri"] for s in ingest_steps], ["paste:multi-a", "paste:multi-b"])

    def test_the_identical_nonstandard_wrap_via_the_cli_subprocess_exits_zero(self):
        doc = [
            _brief_step(),
            {"action": "add_source", "customField": {"nestedThing": {
                "sourceType": "local_paste", "uri": "paste:cli-nonstandard", "owner": "speaker@example.com",
                "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
                "content": "Adoption grew 42% quarter over quarter across every pilot team surveyed.",
            }}},
        ]
        scenario_path = self.root / "nonstandard-wrap-scenario.json"
        scenario_path.write_text(json.dumps(doc))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))
        ingest_step = next(s for s in envelope["data"]["steps"] if s["action"] == "source.ingest")
        self.assertEqual(ingest_step["state"], "AUTHORIZED")


if __name__ == "__main__":
    unittest.main()
