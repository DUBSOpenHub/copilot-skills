"""Regression tests for the `ingest_source`/`add_source` action-list
inline-payload wrapper normalization (`engine/scenario.
_normalize_source_action_entries` / `_normalize_source_field_aliases`):
a public caller's source descriptor is accepted in any of four
wire-compatible shapes -- direct fields (documented, unchanged), a
`{"source": {...}}` / `{"descriptor": {...}}` / `{"value": {...}}`
wrapper around the same fields, or a `{"sources": [...]}` list wrapper
contributing several descriptors from one action-list element -- plus a
conservative set of field-name aliases (`path` -> `uri`, `type` ->
`sourceType`, `access` -> `permissionState`, `label` -> `sensitivityLabel`)
for callers that use a shorter/alternate name than the documented
`FetchResult` field.

Compatibility gap this closes: a wrapped or field-aliased descriptor
previously either failed validation (missing `uri`/`origin`/etc., since
they were nested under a wrapper key never unwrapped) or silently lost
metadata -- source/evidence/claim/gate collections stayed empty even
though the descriptor's real fields were present, just differently
shaped.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import EngineError, REPO_ROOT, cleanup, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _fetch_result(uri: str, **overrides) -> dict:
    payload = {
        "origin": "local", "sourceType": "local_paste", "uri": uri, "owner": "speaker@example.com",
        "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
        "content": "Some evidence content worth citing in the talk.",
    }
    payload.update(overrides)
    return payload


class SourceWrapperNormalizationUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the normalization function itself."""

    def test_direct_fields_are_unaffected_by_the_new_normalization(self):
        doc = [{"action": "ingest_source", "uri": "paste:a"}]
        merged = scenario._normalize_scenario_doc(doc)
        # Dark Factory hardening cycle 13: a bare "paste:" pseudo-scheme
        # `uri` with no other origin signal now conservatively classifies
        # `origin: "local"` (`_apply_default_local_origin`'s widened
        # non-remote-locator rule) -- this test's own concern (direct
        # fields bypassing wrapper-unwrapping) is otherwise unaffected.
        self.assertEqual(merged["sources"], [{"uri": "paste:a", "origin": "local"}])

    def test_a_source_wrapper_is_unwrapped_to_a_single_item(self):
        doc = [{"action": "add_source", "source": _fetch_result("paste:wrapped")}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [_fetch_result("paste:wrapped")])

    def test_a_descriptor_wrapper_is_unwrapped_identically(self):
        doc = [{"action": "add_source", "descriptor": _fetch_result("paste:wrapped")}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [_fetch_result("paste:wrapped")])

    def test_a_value_wrapper_is_unwrapped_identically(self):
        doc = [{"action": "ingest_source", "value": _fetch_result("paste:wrapped")}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [_fetch_result("paste:wrapped")])

    def test_a_sources_list_wrapper_contributes_every_item(self):
        doc = [{"action": "add_source", "sources": [_fetch_result("paste:one"), _fetch_result("paste:two")]}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual([s["uri"] for s in merged["sources"]], ["paste:one", "paste:two"])

    def test_wrapper_and_list_forms_compose_with_plain_direct_field_elements(self):
        doc = [
            {"action": "ingest_source", "source": _fetch_result("paste:a")},
            {"action": "add_source", **_fetch_result("paste:b")},
            {"action": "ingest_source", "sources": [_fetch_result("paste:c"), _fetch_result("paste:d")]},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual([s["uri"] for s in merged["sources"]], ["paste:a", "paste:b", "paste:c", "paste:d"])

    def test_path_aliases_to_uri_when_uri_is_absent(self):
        doc = [{"action": "add_source", "path": "paste:aliased", "origin": "local", "sourceType": "local_paste"}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"][0]["uri"], "paste:aliased")

    def test_an_explicit_uri_is_never_overridden_by_a_sibling_path_alias(self):
        doc = [{"action": "add_source", "path": "paste:ignored", "uri": "paste:kept"}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"][0]["uri"], "paste:kept")

    def test_type_access_and_label_aliases_fill_in_their_canonical_fields(self):
        doc = [{
            "action": "add_source", "uri": "paste:aliased-fields", "type": "local_paste",
            "access": "authorized", "label": "Confidential",
        }]
        merged = scenario._normalize_scenario_doc(doc)
        item = merged["sources"][0]
        self.assertEqual(item["sourceType"], "local_paste")
        self.assertEqual(item["permissionState"], "authorized")
        self.assertEqual(item["sensitivityLabel"], "Confidential")

    def test_an_unrecognized_field_such_as_title_is_preserved_not_dropped(self):
        doc = [{"action": "add_source", "uri": "paste:has-title", "title": "Adoption Notes"}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"][0]["title"], "Adoption Notes")

    def test_mixing_a_wrapper_with_a_sibling_direct_field_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "add_source", "source": _fetch_result("paste:a"), "owner": "someone@example.com"},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_mixing_two_different_wrappers_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "add_source", "source": _fetch_result("paste:a"), "descriptor": _fetch_result("paste:b")},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_sources_list_wrapper_mixed_with_another_field_is_ambiguous(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "add_source", "sources": [_fetch_result("paste:a")], "owner": "someone@example.com"},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_empty_sources_list_wrapper_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "add_source", "sources": []}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_non_object_sources_list_entry_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "add_source", "sources": ["not-an-object"]}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_empty_wrapper_object_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "add_source", "source": {}}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class SourceWrapperEndToEndTests(unittest.TestCase):
    """End-to-end coverage: wrapped/aliased descriptors ingest exactly
    like the identical direct-field descriptor, and downstream evidence
    extraction proceeds normally."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_a_source_wrapped_descriptor_ingests_and_evidence_extracts(self):
        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", "descriptor": _fetch_result(
                "paste:descriptor-wrapped",
                content="Adoption grew 42% quarter over quarter across every pilot team surveyed.",
            )},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        ingest_step = next(s for s in report["steps"] if s["action"] == "source.ingest")
        self.assertEqual(ingest_step["state"], "AUTHORIZED")
        self.assertTrue(any(s["action"] == "evidence.extract" and s["atomCount"] > 0 for s in report["steps"]))

    def test_a_sources_list_wrapper_ingests_every_item_in_one_action(self):
        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", "sources": [
                _fetch_result("paste:batch-one", content="First batch item."),
                _fetch_result("paste:batch-two", content="Second batch item."),
            ]},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        ingest_steps = [s for s in report["steps"] if s["action"] == "source.ingest"]
        self.assertEqual([s["uri"] for s in ingest_steps], ["paste:batch-one", "paste:batch-two"])
        self.assertTrue(all(s["state"] == "AUTHORIZED" for s in ingest_steps))

    def test_path_and_type_aliased_descriptor_ingests_via_the_cli_subprocess(self):
        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", "path": "paste:aliased-cli", "type": "local_paste", "origin": "local",
             "owner": "speaker@example.com", "access": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "Aliased-field descriptor content."},
        ]
        scenario_path = self.root / "aliased-source-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        ingest_step = next(s for s in envelope["data"]["steps"] if s["action"] == "source.ingest")
        self.assertEqual(ingest_step["state"], "AUTHORIZED")

    def test_a_denied_permission_via_an_access_alias_is_still_correctly_refused(self):
        """Do not weaken authorization: the `access` alias for
        `permissionState` still correctly refuses a denied descriptor,
        exactly like the canonical field name already does."""
        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", "uri": "paste:denied", "sourceType": "local_paste", "origin": "local",
             "owner": "speaker@example.com", "access": "denied", "aclSnapshot": "owner-only",
             "version": "v1", "content": "irrelevant"},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "SOURCE_UNAUTHORIZED")

    def test_wrapped_sources_across_sequential_calls_accumulate_without_duplicating(self):
        """Wrapper normalization composes with the pre-existing sequential-
        resume/accumulation contract (`tests/test_sequential_scenario_
        resume.py`): wrapped descriptors from separate calls all land in
        the one curated bundle, never duplicated, never replacing it."""
        from helpers import models

        store = persistence.Store(root=self.root / "ws")
        first = scenario.run_scenario(store, [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", "source": _fetch_result("paste:seq-one")},
        ], self.root / "r1")
        second = scenario.run_scenario(store, [
            {"action": "add_source", "descriptor": _fetch_result("paste:seq-two")},
        ], self.root / "r2")

        self.assertTrue(second["workspaceResumed"])
        self.assertEqual(second["workspaceId"], first["workspaceId"])
        conn = store.connect(first["workspaceId"])
        try:
            sources = persistence.list_all(conn, "source", first["workspaceId"], models.SourceArtifact)
        finally:
            conn.close()
        self.assertEqual(sorted(s.uri for s in sources), ["paste:seq-one", "paste:seq-two"])

    def test_a_label_aliased_source_still_participates_in_conflict_detection(self):
        """The `label` alias (-> `sensitivityLabel`) is real metadata, not
        cosmetic: a claim citing two atoms whose sources disagree on
        sensitivity still auto-creates an OPEN conflict card exactly as
        the canonical `sensitivityLabel` field name already does."""
        from helpers import models

        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", **_fetch_result("paste:conflict-a", content="A confidential figure."),
             "label": "Confidential"},
            {"action": "add_source", **_fetch_result("paste:conflict-b", content="A public figure."),
             "label": "Public"},
            {"action": "propose_claim", "type": "factual", "text": "A cited figure.",
             "evidenceLocators": ["paste:conflict-a", "paste:conflict-b"]},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        conn = store.connect(report["workspaceId"])
        try:
            conflicts = persistence.list_all(conn, "conflict", report["workspaceId"], models.ConflictCard)
        finally:
            conn.close()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].status, "OPEN")


if __name__ == "__main__":
    unittest.main()
