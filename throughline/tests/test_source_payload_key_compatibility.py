"""Regression tests for public source-descriptor payload key
compatibility (Dark Factory hardening cycle 7,
`engine.ingest.normalize_source_payload` /
`engine.ingest.SOURCE_PAYLOAD_FIELD_ALIASES`): every `FetchResult`
field accepts an explicit, allowlisted camelCase *and* snake_case
synonym, resolved once, centrally, so the raw `source ingest` CLI
command, every `run_scenario` document shape (object-form, field-list
form, and action-list form), and any future caller share the identical
resolution.

Compatibility gap this closes: a source descriptor using snake_case
field names (`source_type`, `source_uri`/`local_path`, `access_state`,
`label_state`, `permission_snapshot`, `authorized_at`, `author`) failed
`ingest_source`'s validation entirely (missing `sourceType`/`uri`/
`owner`/...), which -- inside a `run_scenario` walk -- aborted the whole
remaining scenario at the very first source, leaving evidence, claims,
conflicts, gates, narrative, slides, and package all empty/missing even
though later steps never got a chance to run.
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


def _brief_step(**overrides) -> dict:
    payload = {
        "action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
        "takeaway": "Provenance beats persuasion", "proofPoints": ["adoption stat"],
        "excludedTopics": [], "tone": "confident",
    }
    payload.update(overrides)
    return payload


class NormalizeSourcePayloadUnitTests(unittest.TestCase):
    """Direct, in-process coverage of `ingest_mod.normalize_source_payload`
    itself -- the single, shared resolution function every entry point
    uses."""

    def test_snake_case_source_type_resolves_to_the_canonical_field(self):
        result = ingest_mod.normalize_source_payload({"source_type": "local_paste"})
        self.assertEqual(result["sourceType"], "local_paste")
        self.assertEqual(result["source_type"], "local_paste")  # never dropped

    def test_snake_case_source_uri_resolves_to_uri(self):
        result = ingest_mod.normalize_source_payload({"source_uri": "paste:a"})
        self.assertEqual(result["uri"], "paste:a")

    def test_camel_case_source_uri_resolves_to_uri(self):
        result = ingest_mod.normalize_source_payload({"sourceUri": "paste:a"})
        self.assertEqual(result["uri"], "paste:a")

    def test_snake_case_local_path_resolves_to_uri(self):
        result = ingest_mod.normalize_source_payload({"local_path": "/tmp/notes.txt".replace("/tmp", str(REPO_ROOT))})
        self.assertTrue(result["uri"].endswith("notes.txt"))

    def test_camel_case_local_path_resolves_to_uri(self):
        result = ingest_mod.normalize_source_payload({"localPath": "/some/path.txt"})
        self.assertEqual(result["uri"], "/some/path.txt")

    def test_author_resolves_to_owner(self):
        result = ingest_mod.normalize_source_payload({"author": "me@example.com"})
        self.assertEqual(result["owner"], "me@example.com")

    def test_snake_case_access_state_resolves_to_permission_state(self):
        result = ingest_mod.normalize_source_payload({"access_state": "authorized"})
        self.assertEqual(result["permissionState"], "authorized")

    def test_camel_case_access_state_resolves_to_permission_state(self):
        result = ingest_mod.normalize_source_payload({"accessState": "authorized"})
        self.assertEqual(result["permissionState"], "authorized")

    def test_snake_case_label_state_resolves_to_sensitivity_label(self):
        result = ingest_mod.normalize_source_payload({"label_state": "Confidential"})
        self.assertEqual(result["sensitivityLabel"], "Confidential")

    def test_camel_case_label_state_resolves_to_sensitivity_label(self):
        result = ingest_mod.normalize_source_payload({"labelState": "Confidential"})
        self.assertEqual(result["sensitivityLabel"], "Confidential")

    def test_snake_case_permission_snapshot_resolves_to_acl_snapshot(self):
        result = ingest_mod.normalize_source_payload({"permission_snapshot": "owner-only"})
        self.assertEqual(result["aclSnapshot"], "owner-only")

    def test_camel_case_permission_snapshot_resolves_to_acl_snapshot(self):
        result = ingest_mod.normalize_source_payload({"permissionSnapshot": "owner-only"})
        self.assertEqual(result["aclSnapshot"], "owner-only")

    def test_snake_case_authorized_at_resolves_to_retrieved_at(self):
        result = ingest_mod.normalize_source_payload({"authorized_at": "2026-01-01T00:00:00Z"})
        self.assertEqual(result["retrievedAt"], "2026-01-01T00:00:00Z")

    def test_camel_case_authorized_at_resolves_to_retrieved_at(self):
        result = ingest_mod.normalize_source_payload({"authorizedAt": "2026-01-01T00:00:00Z"})
        self.assertEqual(result["retrievedAt"], "2026-01-01T00:00:00Z")

    def test_pre_existing_path_and_type_aliases_still_work(self):
        result = ingest_mod.normalize_source_payload({"path": "paste:x", "type": "local_paste"})
        self.assertEqual(result["uri"], "paste:x")
        self.assertEqual(result["sourceType"], "local_paste")

    def test_unrecognized_field_such_as_title_is_preserved_untouched(self):
        result = ingest_mod.normalize_source_payload({"uri": "paste:x", "title": "My Notes"})
        self.assertEqual(result["title"], "My Notes")

    def test_is_idempotent(self):
        once = ingest_mod.normalize_source_payload({"source_type": "local_paste", "author": "a@example.com"})
        twice = ingest_mod.normalize_source_payload(once)
        self.assertEqual(once, twice)

    # -- precedence / conflict rules ----------------------------------------

    def test_an_explicit_canonical_field_always_wins_over_a_differing_alias(self):
        """Pre-existing precedent (`path` vs. `uri`) is preserved for
        every alias group, including the new snake_case ones: the
        canonical field is never silently overridden."""
        result = ingest_mod.normalize_source_payload({"uri": "kept", "source_uri": "ignored", "local_path": "also-ignored"})
        self.assertEqual(result["uri"], "kept")

    def test_agreeing_aliases_with_no_canonical_field_resolve_cleanly(self):
        result = ingest_mod.normalize_source_payload({"source_uri": "paste:x", "local_path": "paste:x"})
        self.assertEqual(result["uri"], "paste:x")

    def test_disagreeing_aliases_with_no_canonical_field_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            ingest_mod.normalize_source_payload({"type": "local_paste", "source_type": "github_repo"})
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["field"], "sourceType")

    def test_disagreeing_access_state_aliases_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            ingest_mod.normalize_source_payload({"access": "authorized", "access_state": "denied"})
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class ActionListSnakeCaseNormalizationTests(unittest.TestCase):
    """The identical resolution, reached through the action-list
    `add_source`/`ingest_source` verbs (`engine.scenario.
    _normalize_scenario_doc`)."""

    def test_a_fully_snake_case_descriptor_normalizes_correctly(self):
        doc = [{
            "action": "add_source", "origin": "local", "source_type": "local_paste", "source_uri": "paste:snake",
            "author": "me@example.com", "access_state": "authorized", "permission_snapshot": "owner-only",
            "version": "v1", "content": "hi",
        }]
        merged = scenario._normalize_scenario_doc(doc)
        item = merged["sources"][0]
        self.assertEqual(item["sourceType"], "local_paste")
        self.assertEqual(item["uri"], "paste:snake")
        self.assertEqual(item["owner"], "me@example.com")
        self.assertEqual(item["permissionState"], "authorized")
        self.assertEqual(item["aclSnapshot"], "owner-only")

    def test_a_mixed_case_descriptor_normalizes_correctly(self):
        doc = [{
            "action": "ingest_source", "origin": "local", "sourceType": "local_paste", "local_path": "paste:mixed",
            "owner": "me@example.com", "access": "authorized", "aclSnapshot": "owner-only", "version": "v1",
            "content": "hi",
        }]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"][0]["uri"], "paste:mixed")


class SourceIngestionEndToEndSnakeCaseTests(unittest.TestCase):
    """End-to-end coverage: representative local, uploaded, GitHub, and
    WorkIQ source descriptors, expressed with snake_case field names,
    actually persist sources and derive evidence through the existing
    engine logic -- the failure this whole file guards against."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _snake_case_local_source(self, uri="paste:snake-local") -> dict:
        return {
            "action": "add_source", "origin": "local", "source_type": "local_paste", "source_uri": uri,
            "author": "speaker@example.com", "access_state": "authorized", "permission_snapshot": "owner-only",
            "label_state": "Internal", "version": "v1",
            "content": "Adoption grew 42 percent across every pilot team surveyed this quarter.",
        }

    def _snake_case_upload_source(self) -> dict:
        return {
            "action": "add_source", "origin": "upload", "source_type": "local_upload",
            "local_path": str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt"),
            "author": "speaker@example.com", "access_state": "authorized", "permission_snapshot": "owner-only",
            "label_state": "Public", "version": "v1",
        }

    def _snake_case_github_source(self) -> dict:
        payload = json.loads((REPO_ROOT / "tests" / "fixtures" / "github" / "release_notes.json").read_text())
        return {
            "action": "add_source", "origin": payload["origin"], "source_type": payload["sourceType"],
            "source_uri": payload["uri"], "author": payload["owner"], "access_state": payload["permissionState"],
            "permission_snapshot": payload["aclSnapshot"], "version": payload["version"],
            "authorized_at": payload["retrievedAt"], "content": payload["content"],
        }

    def _snake_case_workiq_source(self) -> dict:
        payload = json.loads((REPO_ROOT / "tests" / "fixtures" / "workiq" / "sharepoint_doc.json").read_text())
        return {
            "action": "add_source", "origin": payload["origin"], "source_type": payload["sourceType"],
            "source_uri": payload["uri"], "author": payload["owner"], "access_state": payload["permissionState"],
            "permission_snapshot": payload["aclSnapshot"], "label_state": payload["sensitivityLabel"],
            "version": payload["version"], "content": payload["content"],
        }

    def test_all_four_origins_ingest_and_derive_evidence_via_snake_case_descriptors(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(),
            self._snake_case_local_source(),
            self._snake_case_upload_source(),
            self._snake_case_github_source(),
            self._snake_case_workiq_source(),
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["sources"]), 4)
        self.assertEqual(sorted(s["origin"] for s in report["sources"]), ["github", "local", "local", "workiq"])
        self.assertGreater(len(report["evidence"]), 0)
        ingest_steps = [s for s in report["steps"] if s["action"] == "source.ingest"]
        self.assertEqual(len(ingest_steps), 4)
        self.assertTrue(all(s["state"] == "AUTHORIZED" for s in ingest_steps))

    def test_sequential_calls_mixing_snake_case_and_camel_case_accumulate_without_duplicating(self):
        """Sequential accumulation (FR-SRC accumulation contract) holds
        regardless of which casing each call happens to use."""
        store = persistence.Store(root=self.root / "ws")
        scenario.run_scenario(
            store, [_brief_step(), self._snake_case_local_source("paste:seq-snake")], self.root / "r1",
        )
        second = scenario.run_scenario(store, [{
            "action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:seq-camel",
            "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
            "version": "v1", "content": "Camel-cased follow-up source.",
        }], self.root / "r2")

        self.assertTrue(second["ok"], second.get("refusal"))
        self.assertTrue(second["workspaceResumed"])
        self.assertEqual(sorted(s["uri"] for s in second["sources"]), ["paste:seq-camel", "paste:seq-snake"])

    def test_a_denied_snake_case_source_is_still_correctly_refused(self):
        """Widening accepted field names never weakens authorization."""
        store = persistence.Store(root=self.root / "ws")
        doc = [_brief_step(), {**self._snake_case_local_source("paste:denied-snake"), "access_state": "denied"}]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "SOURCE_UNAUTHORIZED")
        self.assertEqual(report["sources"], [])

    def test_the_bundle_limit_is_still_enforced_with_snake_case_descriptors(self):
        store = persistence.Store(root=self.root / "ws")
        first_doc = [_brief_step()] + [self._snake_case_local_source(f"paste:bulk-{i}") for i in range(25)]
        scenario.run_scenario(store, first_doc, self.root / "r1")
        over_cap = scenario.run_scenario(
            store, [self._snake_case_local_source("paste:the-26th")], self.root / "r2",
        )
        self.assertEqual(over_cap["refusal"]["code"], "BUNDLE_LIMIT_REACHED")
        self.assertEqual(len(over_cap["sources"]), 25)

    def test_the_full_journey_via_the_cli_subprocess_exits_zero_with_snake_case_sources(self):
        doc = [
            _brief_step(),
            self._snake_case_local_source(),
            self._snake_case_github_source(),
        ]
        scenario_path = self.root / "snake-case-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))
        self.assertEqual(len(envelope["data"]["sources"]), 2)


class GenericSourceWrapperKeysTests(unittest.TestCase):
    """`params`/`payload`/`input` are now also accepted source-item
    wrappers, alongside the pre-existing `source`/`descriptor`/`value`."""

    def _fetch_result(self, uri: str) -> dict:
        return {
            "origin": "local", "sourceType": "local_paste", "uri": uri, "owner": "speaker@example.com",
            "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1",
            "content": "Some evidence content worth citing in the talk.",
        }

    def test_params_wrapper_is_unwrapped_to_a_single_item(self):
        doc = [{"action": "add_source", "params": self._fetch_result("paste:params-wrapped")}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [self._fetch_result("paste:params-wrapped")])

    def test_payload_wrapper_is_unwrapped_to_a_single_item(self):
        doc = [{"action": "ingest_source", "payload": self._fetch_result("paste:payload-wrapped")}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [self._fetch_result("paste:payload-wrapped")])

    def test_input_wrapper_is_unwrapped_to_a_single_item(self):
        doc = [{"action": "add_source", "input": self._fetch_result("paste:input-wrapped")}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["sources"], [self._fetch_result("paste:input-wrapped")])


if __name__ == "__main__":
    unittest.main()
