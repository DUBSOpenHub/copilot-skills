"""Regression tests for the scenario report's persisted-workspace-state
exposure, even when a later action is correctly refused/blocked
(`engine/scenario._attach_workspace_state` / `run_scenario`).

Compatibility gap this closes: `sources`/`evidence`/`claims`/`conflicts`/
`throughlines`/`routes`/`slides`/`restorePoints`/a `workspace` status
summary were never exposed at all in the report, and `gateResults`/
`auditEvents` (the two collections that *were* previously exposed) were
only ever computed at the very unconditional end of `_run_steps` -- so
any walk that was correctly refused/blocked partway (a rejected source,
an unresolved conflict, a failed gate, a blocked export, ...) left every
one of these collections either completely absent or (for the two
pre-existing ones) empty, even though the engine had already durably
persisted real state before the refusal.

Contract:
- Regardless of how the walk ends (a clean completion, or an `EngineError`
  caught partway through `_run_steps`), the *same* fresh read of every
  persisted, workspace-scoped collection is attached to the report before
  the connection closes.
- This is true both for a refusal on a workspace's very first call (no
  prior state at all beyond whatever this call itself persisted before
  the refusal) and for a refusal on a *resumed* call (everything
  accumulated by every earlier call is included too).
- A refusal raised before any workspace/connection exists at all (e.g.
  `WORKSPACE_ALREADY_ACTIVE`) has no persisted state to attach, and the
  report simply omits these collections -- never a crash trying to
  attach state that was never created.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, cleanup, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _as_field_list(doc: dict) -> list[dict]:
    return [{k: v} for k, v in doc.items()]


def _brief_step(**overrides) -> dict:
    payload = {
        "action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
        "takeaway": "Provenance beats persuasion", "proofPoints": ["adoption stat"],
        "excludedTopics": [], "tone": "confident",
    }
    payload.update(overrides)
    return payload


def _source_step(uri: str, content: str = "Some evidence content.") -> dict:
    return {
        "action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": uri,
        "owner": "a@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
        "version": "v1", "content": content,
    }


class RefusalBeforeAnyWorkspaceExistsTests(unittest.TestCase):
    """A refusal with no workspace/connection ever created has nothing to
    attach -- never a crash."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_a_workspace_already_active_refusal_via_run_scenario_has_no_state_collections(self):
        """A pre-existing lock pointing at a workspace id with no
        persisted workspace row (e.g. a stale/corrupted lock) makes
        `show_workspace` return `None`, so `_open_or_resume_workspace`
        falls through to `create_workspace` -- which then loses the
        atomic lock race and raises `WORKSPACE_ALREADY_ACTIVE` before any
        connection for *this* call is ever opened."""
        store = persistence.Store(root=self.root / "ws")
        store.acquire_lock("workspace:ghost-does-not-exist")

        report = scenario.run_scenario(store, [_brief_step()], self.root / "report")

        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "WORKSPACE_ALREADY_ACTIVE")
        self.assertNotIn("sources", report)
        self.assertNotIn("workspace", report)
        self.assertNotIn("workspaceId", report)


class PartialStateOnEarlyRefusalTests(unittest.TestCase):
    """A workspace's very first call, refused partway through, still
    exposes whatever it durably persisted before the refusal."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_a_bare_brief_with_no_sources_is_refused_but_still_a_populated_report(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, [_brief_step()], self.root / "report")

        self.assertFalse(report["ok"])
        # Never a KeyError -- every collection is at least an empty list.
        self.assertEqual(report["sources"], [])
        self.assertEqual(report["evidence"], [])
        self.assertEqual(report["claims"], [])
        self.assertEqual(report["conflicts"], [])
        self.assertEqual(report["slides"], [])
        self.assertEqual(report["restorePoints"], [])
        # Three default throughline candidates were still proposed and
        # persisted before the missing-routes refusal (pre-existing
        # behavior, `tests/test_candidate_persistence_on_refusal.py`).
        self.assertEqual(len(report["throughline"]["candidates"]), 3)
        self.assertEqual(len(report["throughlines"]), 3)
        self.assertIn("workspace", report)
        # `_brief_step()` supplies a complete brief, so the workspace
        # already advanced past BRIEFING at creation time (`workspace.
        # create_workspace`'s own pre-existing phase-assignment rule).
        self.assertEqual(report["workspace"]["phase"], "SOURCING")

    def test_a_source_that_is_denied_still_shows_up_in_the_ledger(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(),
            {**_source_step("paste:denied"), "permissionState": "denied"},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "SOURCE_UNAUTHORIZED")
        # A denied fetch never becomes a source (FR-M365-1/FR-SRC-4) --
        # the ledger genuinely has nothing to show, which is itself the
        # correct, observable outcome (never a crash reading it).
        self.assertEqual(report["sources"], [])

    def test_an_unresolved_conflict_is_refused_but_the_full_ledger_is_still_exposed(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(),
            {**_source_step("paste:conflict-a", content="A confidential figure worth citing."), "sensitivityLabel": "Confidential"},
            {**_source_step("paste:conflict-b", content="A public figure worth citing."), "sensitivityLabel": "Public"},
            {"action": "propose_claim", "type": "factual", "text": "A cited figure.",
             "evidenceLocators": ["paste:conflict-a", "paste:conflict-b"]},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertEqual(len(report["sources"]), 2)
        self.assertEqual(len(report["evidence"]), 2)
        self.assertEqual(len(report["claims"]), 1)
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(report["conflicts"][0]["status"], "OPEN")


class PartialStateOnAResumedRefusalTests(unittest.TestCase):
    """A resumed call's refusal still exposes everything accumulated by
    every earlier call, not just this call's own additions."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_a_later_refused_call_still_shows_sources_from_earlier_calls(self):
        store = persistence.Store(root=self.root / "ws")
        scenario.run_scenario(store, [_brief_step(), _source_step("paste:one")], self.root / "r1")
        scenario.run_scenario(store, [_source_step("paste:two")], self.root / "r2")

        # A third call whose own new source is denied is refused, but the
        # first two sources (from earlier calls) are still fully visible.
        third = scenario.run_scenario(
            store, [{**_source_step("paste:three"), "permissionState": "denied"}], self.root / "r3",
        )
        self.assertFalse(third["ok"])
        self.assertEqual(sorted(s["uri"] for s in third["sources"]), ["paste:one", "paste:two"])

    def test_a_bundle_limit_refusal_still_shows_all_25_accumulated_sources(self):
        store = persistence.Store(root=self.root / "ws")
        first_doc = [_brief_step()] + [_source_step(f"paste:bulk-{i}") for i in range(25)]
        scenario.run_scenario(store, first_doc, self.root / "r1")

        over_cap = scenario.run_scenario(store, [_source_step("paste:the-26th")], self.root / "r2")
        self.assertEqual(over_cap["refusal"]["code"], "BUNDLE_LIMIT_REACHED")
        self.assertEqual(len(over_cap["sources"]), 25)


class GateResultsAndAuditEventsSurviveAnyRefusalTests(unittest.TestCase):
    """`gateResults`/`auditEvents` (previously only ever populated at the
    very end of a clean walk) now survive a refusal at any point,
    including inside the pre-Stage gate pipeline itself."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_gate_results_and_audit_events_are_populated_even_when_stage_never_runs(self):
        """A refusal raised well before the gate pipeline ever runs (a
        denied source, early in ingestion) still leaves every audit event
        already recorded (workspace/brief creation) fully visible --
        `gateResults` legitimately stays empty (no gate ever ran), which
        is itself the correct, observable outcome, never a crash reading
        it."""
        store = persistence.Store(root=self.root / "ws")
        doc = [_brief_step(), {**_source_step("paste:denied-early"), "permissionState": "denied"}]
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "SOURCE_UNAUTHORIZED")
        self.assertGreater(len(report["auditEvents"]), 0)
        audit_actions = {e["action"] for e in report["auditEvents"]}
        self.assertIn("workspace.create", audit_actions)
        self.assertEqual(report["gateResults"], [])

    def test_claims_gate_failure_exposes_readiness_and_full_gate_results(self):
        """An unapproved-but-cited claim leaves CLAIMS (and therefore
        STAGE) failing; an explicit `export` action targeting the Stage
        package then surfaces the identical, pre-existing `GATE_NOT_
        PASSED` refusal -- while every gate's own result, including
        READINESS (a distinct top-level key, not just nested under
        `preStageGates`), remains fully observable."""
        base = json.loads(FIXTURE.read_text())
        for claim in base["claims"]:
            claim.pop("approve", None)
        base.pop("rehearsalTimings", None)
        base.pop("qaPairs", None)
        base.pop("stageApprover", None)
        doc = _as_field_list(base) + [{"action": "export", "target": "package"}]

        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "GATE_NOT_PASSED")
        gate_by_name = {g["gate"]: g["passed"] for g in report["gateResults"]}
        self.assertFalse(gate_by_name["CLAIMS"])
        self.assertFalse(gate_by_name["STAGE"])
        # `readiness` (a distinct top-level key, not just nested under
        # `preStageGates`) reflects the READINESS gate's own latest result.
        self.assertIsNotNone(report["readiness"])
        self.assertTrue(report["readiness"]["passed"])
        self.assertEqual(len(report["slides"]), 7)
        self.assertEqual(len(report["routes"]), 2)


class WorkspaceSummaryTests(unittest.TestCase):
    """`report["workspace"]` is a durable, always-available status
    summary regardless of what this particular call's own walk reached."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_workspace_summary_reflects_phase_progression_across_sequential_calls(self):
        store = persistence.Store(root=self.root / "ws")
        first = scenario.run_scenario(store, [_brief_step()], self.root / "r1")
        # A complete brief (as `_brief_step()` always supplies) advances
        # the workspace past BRIEFING immediately at creation.
        self.assertEqual(first["workspace"]["phase"], "SOURCING")

        base = json.loads(FIXTURE.read_text())
        base.pop("brief", None)
        full = scenario.run_scenario(store, _as_field_list(base), self.root / "r2")
        self.assertTrue(full["ok"], full.get("refusal"))
        self.assertEqual(full["workspace"]["phase"], "PACKAGED")
        self.assertIsNotNone(full["workspace"]["manifestId"])
        self.assertIsNotNone(full["workspace"]["lastRehearsalAt"])
        self.assertEqual(full["workspace"]["stageApprovedBy"], "Dr. Jamie Rivera")

    def test_the_partial_state_contract_holds_through_the_cli_subprocess_too(self):
        doc = [_brief_step(), {**_source_step("paste:x"), "permissionState": "denied"}]
        scenario_path = self.root / "denied-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["data"]["ok"])
        self.assertEqual(envelope["data"]["sources"], [])
        self.assertIn("workspace", envelope["data"])


if __name__ == "__main__":
    unittest.main()
