"""Regression tests for the `revoke_source`/`quarantine_source`/
`resolve_source_hold`/`retire_source` action-list verbs (Dark Factory
hardening cycle 7, `engine/scenario.py`): explicit source-lifecycle
transitions (FR-SRC-5/FR-SRC-6), reachable through the scenario/
action-list interface through the identical, already-existing
`ingest.revoke_access`/`ingest.quarantine_source`/`ingest.resolve_hold`/
`ingest.retire_source` calls the CLI's own granular `source revoke`/
`source quarantine`/`source resolve-hold`/`source retire` subcommands
use -- never a second lifecycle code path.

Compatibility gap this closes: a scenario/action-list document had no
way at all to revoke, quarantine, resolve a hold on, or retire a source
-- these state transitions were reachable only through the granular CLI
subcommands, which require a source's own server-generated id (unknown
to a declarative, one-pass scenario document ahead of time). Each new
verb may instead reference its target source by the `uri` it was
ingested under, so "blocked"/"held"/"revoked" source states are fully
observable, and drivable, from one scenario document.
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


def _brief_step(**overrides) -> dict:
    payload = {
        "action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
        "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident",
    }
    payload.update(overrides)
    return payload


def _source_step(uri: str, **overrides) -> dict:
    payload = {
        "action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": uri,
        "owner": "a@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
        "version": "v1", "content": f"Some evidence content worth citing about {uri}.",
    }
    payload.update(overrides)
    return payload


class ActionVocabularyUnitTests(unittest.TestCase):
    def test_all_four_lifecycle_verbs_are_known_actions(self):
        for verb in ("revoke_source", "quarantine_source", "resolve_source_hold", "retire_source"):
            self.assertIn(verb, scenario._ACTION_ALIASES)

    def test_each_verb_targets_its_own_dedicated_field(self):
        self.assertEqual(scenario._ACTION_ALIASES["revoke_source"], "sourceRevocations")
        self.assertEqual(scenario._ACTION_ALIASES["quarantine_source"], "sourceQuarantines")
        self.assertEqual(scenario._ACTION_ALIASES["resolve_source_hold"], "sourceHoldResolutions")
        self.assertEqual(scenario._ACTION_ALIASES["retire_source"], "sourceRetirements")


class RevokeSourceEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_revoke_by_uri_marks_the_source_access_revoked(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [_brief_step(), _source_step("paste:revoke-by-uri"), {"action": "revoke_source", "uri": "paste:revoke-by-uri"}]
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        revoke_steps = [s for s in report["steps"] if s["action"] == "source.revoke"]
        self.assertEqual(len(revoke_steps), 1)
        self.assertEqual(revoke_steps[0]["state"], "ACCESS_REVOKED")
        self.assertEqual(report["sources"][0]["state"], "ACCESS_REVOKED")

    def test_revoke_by_source_id_also_works(self):
        store = persistence.Store(root=self.root / "ws")
        first = scenario.run_scenario(
            store, [_brief_step(), _source_step("paste:revoke-by-id")], self.root / "r1",
        )
        source_id = first["sources"][0]["id"]
        second = scenario.run_scenario(
            store, [{"action": "revoke_source", "sourceId": source_id}], self.root / "r2",
        )
        self.assertTrue(second["ok"], second.get("refusal"))
        self.assertEqual(second["sources"][0]["state"], "ACCESS_REVOKED")

    def test_revoke_by_snake_case_source_id_also_works(self):
        store = persistence.Store(root=self.root / "ws")
        first = scenario.run_scenario(
            store, [_brief_step(), _source_step("paste:revoke-by-snake-id")], self.root / "r1",
        )
        source_id = first["sources"][0]["id"]
        second = scenario.run_scenario(
            store, [{"action": "revoke_source", "source_id": source_id}], self.root / "r2",
        )
        self.assertTrue(second["ok"], second.get("refusal"))
        self.assertEqual(second["sources"][0]["state"], "ACCESS_REVOKED")

    def test_revocation_cascades_to_dependent_evidence(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(), _source_step("paste:revoke-cascade"),
            {"action": "revoke_source", "uri": "paste:revoke-cascade"},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertGreater(len(report["evidence"]), 0)
        self.assertTrue(all(a["access_state"] == "ACCESS_REVOKED" for a in report["evidence"]))

    def test_missing_reference_is_a_validation_error(self):
        store = persistence.Store(root=self.root / "ws")
        # A completely empty payload is rejected at normalization time
        # (the generic `_ACTION_LIST_OBJECT_FIELDS` "no inline payload
        # fields" check, shared with every other list-object verb) --
        # propagated immediately, per `run_scenario`'s own documented
        # contract for a malformed document shape, never treated as a
        # mid-run refusal.
        doc = [_brief_step(), {"action": "revoke_source"}]
        with self.assertRaises(EngineError) as ctx:
            scenario.run_scenario(store, doc, self.root / "report")
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_non_reference_field_with_no_id_or_uri_is_a_mid_run_refusal(self):
        """`quarantine_source` accepts a `reason` field in addition to a
        reference field, so a payload that supplies only `reason` is
        non-empty (passes normalization) but still has no way to
        identify its target source -- this reaches
        `_resolve_source_lifecycle_target`'s own check and is a normal,
        structured mid-run refusal (exit 0, `report["refusal"]`), not a
        propagated exception."""
        store = persistence.Store(root=self.root / "ws")
        doc = [_brief_step(), {"action": "quarantine_source", "reason": "no source named"}]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_both_id_and_uri_together_is_ambiguous(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(), _source_step("paste:ambiguous"),
            {"action": "revoke_source", "uri": "paste:ambiguous", "sourceId": "source:doesnotexist"},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_an_unresolvable_uri_is_not_found(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [_brief_step(), {"action": "revoke_source", "uri": "paste:never-existed"}]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "NOT_FOUND")

    def test_via_the_cli_subprocess_exits_zero(self):
        doc = [_brief_step(), _source_step("paste:cli-revoke"), {"action": "revoke_source", "uri": "paste:cli-revoke"}]
        scenario_path = self.root / "revoke-scenario.json"
        scenario_path.write_text(json.dumps(doc))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))
        self.assertEqual(envelope["data"]["sources"][0]["state"], "ACCESS_REVOKED")


class QuarantineAndResolveHoldEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_quarantine_holds_the_source_with_a_reason(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(), _source_step("paste:quarantine-me"),
            {"action": "quarantine_source", "uri": "paste:quarantine-me", "reason": "needs legal review"},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["sources"][0]["state"], "QUARANTINED")
        self.assertEqual(report["sources"][0]["hold_reason"], "needs legal review")
        quarantine_steps = [s for s in report["steps"] if s["action"] == "source.quarantine"]
        self.assertEqual(quarantine_steps[0]["reason"], "needs legal review")

    def test_a_missing_reason_is_a_validation_error(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [_brief_step(), _source_step("paste:no-reason"), {"action": "quarantine_source", "uri": "paste:no-reason"}]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_resolve_hold_with_authorize_decision_reauthorizes_the_source(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(), _source_step("paste:hold-authorize"),
            {"action": "quarantine_source", "uri": "paste:hold-authorize", "reason": "manual check"},
            {"action": "resolve_source_hold", "uri": "paste:hold-authorize", "decision": "authorize"},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["sources"][0]["state"], "AUTHORIZED")

    def test_resolve_hold_with_retire_decision_retires_the_source(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(), _source_step("paste:hold-retire"),
            {"action": "quarantine_source", "uri": "paste:hold-retire", "reason": "manual check"},
            {"action": "resolve_source_hold", "uri": "paste:hold-retire", "decision": "retire"},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["sources"][0]["state"], "RETIRED")

    def test_resolve_hold_on_a_non_held_source_is_a_validation_error(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(), _source_step("paste:not-held"),
            {"action": "resolve_source_hold", "uri": "paste:not-held", "decision": "authorize"},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_an_invalid_decision_is_a_validation_error(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(), _source_step("paste:bad-decision"),
            {"action": "quarantine_source", "uri": "paste:bad-decision", "reason": "x"},
            {"action": "resolve_source_hold", "uri": "paste:bad-decision", "decision": "explode"},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")


class RetireSourceEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_retire_frees_the_bundle_slot(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [_brief_step(), _source_step("paste:retire-me"), {"action": "retire_source", "uri": "paste:retire-me"}]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["sources"][0]["state"], "RETIRED")
        retire_steps = [s for s in report["steps"] if s["action"] == "source.retire"]
        self.assertEqual(len(retire_steps), 1)


if __name__ == "__main__":
    unittest.main()
