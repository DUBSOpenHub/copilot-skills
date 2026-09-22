"""Regression tests for top-level report response compatibility (Dark
Factory hardening cycle 7, `engine.models.add_report_compat_aliases`):
established camelCase report/command-result fields gain top-level
snake_case aliases (`source_ledger`/`sources`, `evidence_atoms`/
`evidence`, `conflict_cards`/`conflicts`, `gate_results`/`gates`/
`gateResults`, `audit_trail`/`audit_events`/`auditEvents`,
`candidate_throughlines`, `narrative_routes`, `restore_points`,
`export`/`package`, `workspace_id`, `deck_id`), plus a compatibility
action-results ledger (`actionResults`/`action_results`) so callers can
see every attempted action's outcome -- success or the walk's final
refusal -- from one list.

Compatibility gap this closes: a public caller expecting a snake_case
field name (or a single ledger of per-action outcomes) on the
`run-scenario` report -- whether read from the CLI's JSON envelope or
directly from the written `run-report.json` file -- previously found
neither; only the pre-existing camelCase names existed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, cleanup, models, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _as_field_list(doc: dict) -> list[dict]:
    return [{k: v} for k, v in doc.items()]


class AddReportCompatAliasesUnitTests(unittest.TestCase):
    """Direct, in-process coverage of `models.add_report_compat_aliases`
    itself."""

    def test_non_dict_input_is_returned_unchanged(self):
        self.assertIsNone(models.add_report_compat_aliases(None))
        self.assertEqual(models.add_report_compat_aliases([1, 2]), [1, 2])

    def test_every_alias_references_the_identical_underlying_value(self):
        data = {
            "sources": [{"id": "source:1"}], "evidence": [{"id": "evidence:1"}], "conflicts": [],
            "gateResults": [{"gate": "SCOPE", "passed": True}], "auditEvents": [{"action": "workspace.create"}],
            "throughlines": [{"id": "t:1"}], "routes": [{"id": "r:1"}], "restorePoints": [{"id": "rp:1"}],
            "package": {"deckId": "deck:1"},
        }
        models.add_report_compat_aliases(data)
        self.assertIs(data["source_ledger"], data["sources"])
        self.assertIs(data["evidence_atoms"], data["evidence"])
        self.assertIs(data["conflict_cards"], data["conflicts"])
        self.assertIs(data["gate_results"], data["gateResults"])
        self.assertIs(data["gates"], data["gateResults"])
        self.assertIs(data["audit_trail"], data["auditEvents"])
        self.assertIs(data["audit_events"], data["auditEvents"])
        self.assertIs(data["candidate_throughlines"], data["throughlines"])
        self.assertIs(data["narrative_routes"], data["routes"])
        self.assertIs(data["restore_points"], data["restorePoints"])
        self.assertIs(data["export"], data["package"])
        self.assertEqual(data["deck_id"], "deck:1")

    def test_absent_source_fields_never_fabricate_an_alias(self):
        data = {"ok": False, "refusal": {"code": "WORKSPACE_ALREADY_ACTIVE", "details": {}}}
        models.add_report_compat_aliases(data)
        for alias in ("source_ledger", "evidence_atoms", "conflict_cards", "gate_results", "gates",
                      "audit_trail", "audit_events", "candidate_throughlines", "narrative_routes",
                      "restore_points", "export", "workspace_id", "deck_id"):
            self.assertNotIn(alias, data)

    def test_workspace_id_resolves_from_the_refusal_details_when_nothing_else_is_present(self):
        data = {"ok": False, "refusal": {"code": "WORKSPACE_ALREADY_ACTIVE", "details": {"workspaceId": "workspace:x"}}}
        models.add_report_compat_aliases(data)
        self.assertEqual(data["workspace_id"], "workspace:x")

    def test_deck_id_resolves_from_a_camelcase_workspace_summary_once_compiled(self):
        """`run_scenario`'s own hand-built `report["workspace"]` summary
        uses camelCase keys (`deckId`), unlike the raw dataclass
        serialization (`workspace.deck_id`) `workspace new`/`show`/
        `resume` use -- both shapes resolve `deck_id`."""
        data = {"workspace": {"id": "workspace:x", "deckId": "deck:x"}}
        models.add_report_compat_aliases(data)
        self.assertEqual(data["deck_id"], "deck:x")

    def test_deck_id_resolves_from_the_snake_case_dataclass_workspace_shape(self):
        data = {"workspace": {"id": "workspace:x", "deck_id": "deck:y"}}
        models.add_report_compat_aliases(data)
        self.assertEqual(data["deck_id"], "deck:y")

    def test_is_idempotent(self):
        data = {"sources": [{"id": "source:1"}]}
        models.add_report_compat_aliases(data)
        first = dict(data)
        models.add_report_compat_aliases(data)
        self.assertEqual(data, first)


class FullJourneyReportAliasEndToEndTests(unittest.TestCase):
    """The complete set of aliases, exercised through a real
    `run_scenario` walk that reaches Stage and package."""

    def setUp(self):
        self.root = new_root()
        self.store = persistence.Store(root=self.root / "ws")
        doc = json.loads(FIXTURE.read_text())
        self.report = scenario.run_scenario(self.store, doc, self.root / "report")

    def tearDown(self):
        cleanup(self.root)

    def test_the_journey_completed(self):
        self.assertTrue(self.report["ok"], self.report.get("refusal"))

    def test_every_documented_alias_is_present_and_correct(self):
        r = self.report
        self.assertEqual(r["source_ledger"], r["sources"])
        self.assertEqual(r["evidence_atoms"], r["evidence"])
        self.assertEqual(r["conflict_cards"], r["conflicts"])
        self.assertEqual(r["gate_results"], r["gateResults"])
        self.assertEqual(r["gates"], r["gateResults"])
        self.assertEqual(r["audit_trail"], r["auditEvents"])
        self.assertEqual(r["audit_events"], r["auditEvents"])
        self.assertEqual(r["candidate_throughlines"], r["throughlines"])
        self.assertEqual(r["narrative_routes"], r["routes"])
        self.assertEqual(r["restore_points"], r["restorePoints"])
        self.assertEqual(r["export"], r["package"])
        self.assertEqual(r["workspace_id"], r["workspaceId"])
        self.assertEqual(r["deck_id"], r["package"]["deckId"])

    def test_action_results_ledger_mirrors_steps_with_ok_true(self):
        r = self.report
        self.assertEqual(r["action_results"], r["actionResults"])
        self.assertEqual(len(r["actionResults"]), len(r["steps"]))
        self.assertTrue(all(entry["ok"] is True for entry in r["actionResults"]))
        for step, result in zip(r["steps"], r["actionResults"]):
            self.assertEqual(result["action"], step["action"])

    def test_run_report_json_file_on_disk_carries_every_alias_too(self):
        on_disk = json.loads((self.root / "report" / "run-report.json").read_text())
        self.assertEqual(on_disk["source_ledger"], on_disk["sources"])
        self.assertEqual(on_disk["workspace_id"], on_disk["workspaceId"])
        self.assertIn("action_results", on_disk)

    def test_the_journey_via_the_cli_subprocess_exposes_every_alias(self):
        scenario_path = self.root / "scenario.json"
        scenario_path.write_text(json.dumps(_as_field_list(json.loads(FIXTURE.read_text()))))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "cli-ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        data = envelope["data"]
        self.assertEqual(data["source_ledger"], data["sources"])
        self.assertEqual(data["gates"], data["gateResults"])
        self.assertEqual(envelope["workspace_id"], data["workspace_id"])


class RefusedJourneyActionResultsTests(unittest.TestCase):
    """The action-results ledger still surfaces a refused walk's final
    outcome, appended after every step that actually executed."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_a_denied_source_appears_as_a_refusal_entry_after_prior_steps(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:denied",
             "owner": "a@example.com", "permissionState": "denied", "aclSnapshot": "owner-only",
             "version": "v1", "content": "irrelevant"},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["actionResults"][-1]["ok"], False)
        self.assertEqual(report["actionResults"][-1]["error"]["code"], "SOURCE_UNAUTHORIZED")

    def test_prior_successful_steps_still_show_ok_true_before_the_refusal_entry(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:ok-first",
             "owner": "a@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "Some content worth citing for this refusal test."},
        ]
        report = scenario.run_scenario(store, doc, self.root / "r1")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(all(e["ok"] for e in report["actionResults"]))

        over_cap_doc = [
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:denied-2",
             "owner": "a@example.com", "permissionState": "denied", "aclSnapshot": "owner-only",
             "version": "v1", "content": "irrelevant"},
        ]
        second = scenario.run_scenario(store, over_cap_doc, self.root / "r2")
        self.assertFalse(second["ok"])
        self.assertEqual(second["actionResults"][-1]["ok"], False)


class GranularCommandAliasTests(unittest.TestCase):
    """The identical alias mechanism also applies to granular (non
    `run-scenario`) commands through `cli.main`'s own `emit()` path."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_source_list_response_carries_the_source_ledger_alias(self):
        scenario_path = self.root / "scenario.json"
        scenario_path.write_text(json.dumps(_as_field_list(json.loads(FIXTURE.read_text()))))
        ws_dir = self.root / "ws"
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(ws_dir))
        self.assertEqual(proc.returncode, 0, proc.stderr)

        proc2 = _run_cli("--workspace-root", str(ws_dir), "source", "list")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        data = json.loads(proc2.stdout)["data"]
        self.assertIn("source_ledger", data)
        self.assertEqual(data["source_ledger"], data["sources"])


if __name__ == "__main__":
    unittest.main()
