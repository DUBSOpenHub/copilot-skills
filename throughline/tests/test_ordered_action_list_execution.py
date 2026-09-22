"""Regression tests for the true ordered action-list executor (Dark
Factory hardening cycle 8, `engine/scenario.py`'s
`_run_ordered_action_list`): the root-cause fix for acceptance-pass-11's
empty sources/evidence/claims/routes/slides/gates/exports.

Prior to this hardening cycle, *every* accepted scenario-document shape
-- including a true action-list document, whose elements each name an
explicit `"action"` verb and carry a genuine, caller-authored sequence --
was flattened into one aggregate object (`_normalize_scenario_doc`)
before a single domain call ever ran, then executed as one fixed-order
batch (`_run_steps`). That silently discarded repeated verbs, ordering,
and per-action state transitions: 26 repeated `add_source` actions still
each ingested, but a `run_gate` always saw the *final* fully-ingested
bundle, never the partial one that actually existed at that point in the
caller's own sequence, and a failure anywhere collapsed the whole result.

This file exercises the fix directly: a *true* action-list document (every
element names an `"action"` verb) is now dispatched straight from the
original, ordered document, one element at a time, immediately against the
live connection, using the identical already-existing domain-module calls
`_run_steps`/`cli.py`'s own subcommands use (never a second business-logic
implementation) -- so every action's own effect is durably persisted and
visible to the next action, `report["actionResults"]`/`report
["action_results"]` carries one entry per element (in original order, with
at least `index`, `action`, `status`), and object-form/field-list-form
documents keep using `_run_steps`'s own unchanged batch path.

See `docs/engine-cli-reference.md`'s "run-scenario document shapes" section
for the updated documentation this cycle also adds (actions execute in
order and may repeat).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, cleanup, models, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _brief_step(**overrides) -> dict:
    payload = {
        "action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
        "takeaway": "Ordered execution matters", "proofPoints": ["adoption stat"], "excludedTopics": [],
        "tone": "confident",
    }
    payload.update(overrides)
    return payload


def _source_step(uri: str, **overrides) -> dict:
    payload = {
        "action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": uri,
        "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
        "version": "v1", "content": f"Evidence content worth citing for {uri}. " * 5,
    }
    payload.update(overrides)
    return payload


class TwentySixRepeatedSourceAdditionsTests(unittest.TestCase):
    """26 repeated `add_source` actions in one true action-list document:
    the first 25 must each ingest once, persist immediately, and be
    visible to the next action; the 26th must be cleanly blocked
    (`BUNDLE_LIMIT_REACHED`) while the first 25 remain -- and every one of
    the 26 attempts is its own entry in `actionResults`/`action_results`,
    never a single aggregated last-write-wins field."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _doc(self) -> list[dict]:
        doc = [_brief_step()]
        doc.extend(_source_step(f"paste:bulk-{i}") for i in range(26))
        return doc

    def test_all_26_attempts_are_reported_25_completed_1_blocked(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, self._doc(), self.root / "report")

        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "BUNDLE_LIMIT_REACHED")

        source_results = [e for e in report["actionResults"] if e["action"] == "add_source"]
        self.assertEqual(len(source_results), 26, "every attempted add_source action has its own ledger entry")
        self.assertEqual([e["status"] for e in source_results[:25]], ["completed"] * 25)
        self.assertTrue(all(e["ok"] for e in source_results[:25]))
        self.assertEqual(source_results[25]["status"], "blocked")
        self.assertFalse(source_results[25]["ok"])
        self.assertEqual(source_results[25]["error"]["code"], "BUNDLE_LIMIT_REACHED")

        # `index` is each element's own position in the original document
        # (element 0 is the brief) -- never renumbered/compacted.
        self.assertEqual([e["index"] for e in source_results], list(range(1, 27)))

        # Sequential accumulation, not a last-write-wins field: exactly
        # the first 25 sources, each with a distinct id, are durably
        # persisted -- never zero, and never fewer than 25.
        self.assertEqual(len(report["sources"]), 25)
        self.assertEqual(len({s["id"] for s in report["sources"]}), 25)
        self.assertEqual({s["uri"] for s in report["sources"]}, {f"paste:bulk-{i}" for i in range(25)})

        ingest_steps = [s for s in report["steps"] if s["action"] == "source.ingest"]
        self.assertEqual(len(ingest_steps), 25)

    def test_persisted_state_survives_a_fresh_connection_after_the_refusal(self):
        """Persistence is real and durable, not merely reflected in the
        in-memory report -- a brand-new connection to the same workspace
        after the refusal still finds exactly the first 25 sources."""
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, self._doc(), self.root / "report")
        conn = store.connect(report["workspaceId"])
        try:
            sources = persistence.list_all(conn, "source", report["workspaceId"], models.SourceArtifact)
        finally:
            conn.close()
        self.assertEqual(len(sources), 25)

    def test_the_26th_attempt_via_the_cli_subprocess_still_exits_zero(self):
        """A correctly-blocked domain rule is still a normal, zero-exit-
        code completion (never conflated with a genuine implementation
        fault)."""
        scenario_path = self.root / "scenario.json"
        scenario_path.write_text(json.dumps(self._doc()))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertFalse(envelope["data"]["ok"])
        self.assertEqual(envelope["data"]["refusal"]["code"], "BUNDLE_LIMIT_REACHED")
        self.assertEqual(len(envelope["data"]["sources"]), 25)


class SequentialSourceChangeAndRevocationTests(unittest.TestCase):
    """Source lifecycle transitions interleaved with other actions in one
    true ordered document: each transition takes effect immediately and
    is visible to whatever comes after it -- never batched into a single
    fixed phase regardless of the caller's own sequence."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_add_revoke_add_quarantine_resolve_add_retire_in_one_sequence(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(),
            _source_step("paste:a"),
            {"action": "revoke_source", "uri": "paste:a"},
            _source_step("paste:b"),
            {"action": "quarantine_source", "uri": "paste:b", "reason": "sensitivity review pending"},
            {"action": "resolve_source_hold", "uri": "paste:b", "decision": "authorize"},
            _source_step("paste:c"),
            {"action": "retire_source", "uri": "paste:c"},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        by_uri = {s["uri"]: s for s in report["sources"]}
        self.assertEqual(by_uri["paste:a"]["state"], "ACCESS_REVOKED")
        self.assertEqual(by_uri["paste:b"]["state"], "AUTHORIZED")
        self.assertEqual(by_uri["paste:c"]["state"], "RETIRED")

        # One ledger entry per lifecycle action, in original order, all
        # completed.
        lifecycle_actions = ["revoke_source", "quarantine_source", "resolve_source_hold", "retire_source"]
        lifecycle_results = [e for e in report["actionResults"] if e["action"] in lifecycle_actions]
        self.assertEqual([e["action"] for e in lifecycle_results], lifecycle_actions)
        self.assertTrue(all(e["status"] == "completed" for e in lifecycle_results))

    def test_a_quarantined_source_that_is_never_resolved_is_still_a_clean_gate_failure_not_a_crash(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(),
            _source_step("paste:held"),
            {"action": "quarantine_source", "uri": "paste:held", "reason": "needs review"},
            {"action": "run_gate", "gate": "evidence"},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["sources"][0]["state"], "QUARANTINED")
        gate_step = next(s for s in report["steps"] if s["action"] == "gate.run")
        self.assertEqual(gate_step["gate"], "evidence")


class RepeatedClaimUpdateTests(unittest.TestCase):
    """Repeated `propose_claim` actions each persist independently and
    are individually observable -- never collapsed into a single
    aggregate/last-write-wins entry (only the pre-existing, documented
    `report["steps"]` `claim.propose` *count* summary stays aggregated;
    `actionResults` itself is per-action)."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_three_repeated_claim_proposals_each_persist_and_are_individually_ledgered(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(),
            _source_step("paste:evidence"),
            {"action": "propose_claim", "type": "factual", "text": "Adoption grew 42%.",
             "evidenceLocators": ["paste:evidence"], "approve": True},
            {"action": "propose_claim", "type": "interpretive", "text": "This meaningfully reduces prep risk.",
             "evidenceLocators": ["paste:evidence"], "rationale": "Correlates with the adoption stat.", "approve": True},
            {"action": "propose_claim", "type": "aspirational", "text": "Every team should adopt this.",
             "aspirationalLabel": "RECOMMENDATION", "approve": True},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["claims"]), 3)
        self.assertTrue(all(c["approver"] for c in report["claims"]), report["claims"])
        self.assertEqual({c["type"] for c in report["claims"]}, {"FACTUAL", "INTERPRETIVE", "ASPIRATIONAL"})

        claim_results = [e for e in report["actionResults"] if e["action"] == "propose_claim"]
        self.assertEqual(len(claim_results), 3)
        self.assertEqual(len({e["claimId"] for e in claim_results}), 3, "each proposal has its own distinct claim id")
        self.assertTrue(all(e["status"] == "completed" for e in claim_results))

        # The pre-existing aggregate step summary is unaffected.
        propose_step = next(s for s in report["steps"] if s["action"] == "claim.propose")
        self.assertEqual(propose_step["count"], 3)
        self.assertEqual(len([s for s in report["steps"] if s["action"] == "claim.approve"]), 3)

    def test_a_later_claim_referencing_an_earlier_ones_evidence_still_resolves(self):
        """Sequential visibility: a claim proposed after two sources
        exist can cite either one by its own locator, exactly like a
        human driving the granular CLI would expect."""
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(),
            _source_step("paste:first"),
            _source_step("paste:second"),
            {"action": "propose_claim", "type": "factual", "text": "A cited figure.",
             "evidenceLocators": ["paste:first", "paste:second"]},
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["claims"][0]["evidence_atom_ids"]), 2)


class GateOrderTests(unittest.TestCase):
    """The identical named gate, run twice at two different points in one
    true ordered document, reflects the *true* state at each point --
    failing before a required action and passing after it. A fixed-phase
    batch executor can never represent this (every gate it runs always
    sees the final, fully-processed state, regardless of where a
    `run_gate` entry textually appears)."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _beats(self) -> list[dict]:
        return [
            {"role": "HOOK", "headline": "Hook", "timeBudgetSeconds": 60},
            {"role": "STAKES", "headline": "Stakes", "timeBudgetSeconds": 60},
            {"role": "TURN", "headline": "Turn", "timeBudgetSeconds": 60},
            {"role": "MECHANISM", "headline": "Mechanism", "timeBudgetSeconds": 60, "isDemo": True},
            {"role": "PROOF", "headline": "Proof", "timeBudgetSeconds": 60, "claimIds": [0]},
            {"role": "OBJECTION", "headline": "Objection", "timeBudgetSeconds": 60},
            {"role": "ASK", "headline": "Ask", "timeBudgetSeconds": 60},
        ]

    def test_readiness_gate_fails_before_demo_asset_and_passes_after(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(),
            _source_step("paste:proof"),
            {"action": "propose_claim", "type": "factual", "text": "A cited figure worth noting.",
             "evidenceLocators": ["paste:proof"], "approve": True},
            {"action": "select_throughline", "value": 0},
            {"action": "propose_route", "label": "Primary", "beats": self._beats()},
            {"action": "propose_route", "label": "Alt", "beats": [
                {"role": "HOOK", "headline": "Alt hook", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "Alt ask", "timeBudgetSeconds": 60},
            ]},
            {"action": "select_route", "value": 0},
            {"action": "run_gate", "gate": "readiness"},  # too early: no demo asset yet
            {"action": "set_demo_asset", "slideRole": "MECHANISM", "livePath": "cli-session://live-terminal",
             "prerecordedAssetPath": str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt"),
             "staticAssetPath": str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt"),
             "verbalRecoveryScript": "Narrate the flow verbally if the live demo fails."},
            {"action": "run_gate", "gate": "readiness"},  # now complete
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        gate_steps = [s for s in report["steps"] if s["action"] == "gate.run"]
        self.assertEqual(len(gate_steps), 2)
        self.assertFalse(gate_steps[0]["passed"], "readiness must genuinely fail before the demo asset exists")
        self.assertTrue(gate_steps[1]["passed"], "readiness must genuinely pass once every check is satisfied")

        gate_results = [e for e in report["actionResults"] if e["action"] == "run_gate"]
        self.assertEqual([e["passed"] for e in gate_results], [False, True])

    def test_scope_gate_fails_while_quarantined_and_passes_once_resolved(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(),
            _source_step("paste:held-for-scope"),
            {"action": "quarantine_source", "uri": "paste:held-for-scope", "reason": "needs review"},
            {"action": "run_gate", "gate": "scope"},  # a quarantined source blocks SCOPE
            {"action": "resolve_source_hold", "uri": "paste:held-for-scope", "decision": "authorize"},
            {"action": "run_gate", "gate": "scope"},  # resolved -> SCOPE passes again
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        gate_steps = [s for s in report["steps"] if s["action"] == "gate.run" and s["gate"] == "scope"]
        self.assertEqual(len(gate_steps), 2)
        self.assertFalse(gate_steps[0]["passed"], "a quarantined source must genuinely block SCOPE")
        self.assertTrue(gate_steps[1]["passed"], "an authorized-again source must genuinely restore SCOPE")


class PartialRefusalPersistenceTests(unittest.TestCase):
    """A mid-list domain refusal stops the walk, but every action before
    it is already durably persisted, and both the ledger and the final
    report reflect exactly that -- never rolled back, never fabricated."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_prior_sources_and_a_claim_survive_a_later_denied_source(self):
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(),
            _source_step("paste:ok-one"),
            _source_step("paste:ok-two"),
            {"action": "propose_claim", "type": "factual", "text": "A cited figure.",
             "evidenceLocators": ["paste:ok-one"], "approve": True},
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:denied",
             "owner": "a@example.com", "permissionState": "denied", "aclSnapshot": "owner-only",
             "version": "v1", "content": "irrelevant"},
            # Never reached: the denied source above stops the walk.
            _source_step("paste:never-reached"),
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "SOURCE_UNAUTHORIZED")

        self.assertEqual({s["uri"] for s in report["sources"]}, {"paste:ok-one", "paste:ok-two"})
        self.assertEqual(len(report["claims"]), 1)
        self.assertTrue(report["claims"][0]["approver"])

        # Exactly 5 attempted actions (brief, 2 sources, 1 claim, the
        # denied source) -- the 6th, never-reached element, has no entry
        # at all (the walk stopped, it was never attempted).
        self.assertEqual(len(report["actionResults"]), 5)
        statuses = [e["status"] for e in report["actionResults"]]
        self.assertEqual(statuses, ["completed", "completed", "completed", "completed", "refused"])
        self.assertEqual(report["actionResults"][-1]["error"]["code"], "SOURCE_UNAUTHORIZED")
        self.assertEqual(report["actionResults"][-1]["index"], 4)

        # Durable, not just in-memory: a fresh connection confirms it.
        conn = store.connect(report["workspaceId"])
        try:
            sources = persistence.list_all(conn, "source", report["workspaceId"], models.SourceArtifact)
            claims = persistence.list_all(conn, "claim", report["workspaceId"], models.Claim)
        finally:
            conn.close()
        self.assertEqual(len(sources), 2)
        self.assertEqual(len(claims), 1)

    def test_a_refusal_before_narrative_still_reports_persisted_sources_and_claims(self):
        """No default routes exist (no sources cited -- a bare-brief-only
        walk correctly refuses for missing routes), but a source/claim
        added *before* an explicit, unresolvable `select_route` action
        is still durably persisted and reported."""
        store = persistence.Store(root=self.root / "ws")
        doc = [
            _brief_step(),
            {"action": "select_route", "value": 0},  # no routes proposed or derivable -> refused
        ]
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("narrative route", report["refusal"]["message"])
        self.assertEqual(report["actionResults"][-1]["status"], "failed")


class CompleteManualJourneyOrderedTests(unittest.TestCase):
    """A complete, manual-only journey (brief through Stage package),
    driven entirely by a true ordered action-list document, asserting the
    new per-action ledger contract end to end alongside the final,
    authoritative persisted state."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _doc(self) -> list[dict]:
        beats = [
            {"role": "HOOK", "headline": "A stat that changes the room", "timeBudgetSeconds": 60},
            {"role": "STAKES", "headline": "Talks fail without provenance", "timeBudgetSeconds": 90},
            {"role": "TURN", "headline": "What changes the outcome", "timeBudgetSeconds": 90},
            {"role": "MECHANISM", "headline": "How the ledger works", "timeBudgetSeconds": 120, "isDemo": True},
            {"role": "PROOF", "headline": "Adoption grew 42%", "timeBudgetSeconds": 90, "claimIds": [0]},
            {"role": "OBJECTION", "headline": "Is it worth it", "timeBudgetSeconds": 90},
            {"role": "ASK", "headline": "Start this way", "timeBudgetSeconds": 60},
        ]
        return [
            _brief_step(),
            _source_step("paste:journey-note"),
            {"action": "propose_claim", "type": "factual", "text": "Adoption grew 42% quarter over quarter.",
             "evidenceLocators": ["paste:journey-note"], "approve": True},
            {"action": "select_throughline", "value": 0},
            {"action": "propose_route", "label": "Primary route", "beats": beats},
            {"action": "propose_route", "label": "Alt route", "beats": [
                {"role": "HOOK", "headline": "Alt hook", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "Alt ask", "timeBudgetSeconds": 60},
            ]},
            {"action": "select_route", "value": 0},
            {"action": "set_demo_asset", "slideRole": "MECHANISM", "livePath": "cli-session://live-terminal",
             "prerecordedAssetPath": str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt"),
             "staticAssetPath": str(REPO_ROOT / "tests" / "fixtures" / "local" / "adoption-notes.txt"),
             "verbalRecoveryScript": "Narrate the flow verbally if the live demo fails."},
            {"action": "rehearse", "run": {
                "HOOK": 58, "STAKES": 88, "TURN": 85, "MECHANISM": 115, "PROOF": 85, "OBJECTION": 88, "ASK": 55,
            }},
            {"action": "approve_stage", "value": "Dr. Jamie Rivera"},
        ]

    def test_the_journey_reaches_stage_and_package_with_a_full_per_action_ledger(self):
        store = persistence.Store(root=self.root / "ws")
        doc = self._doc()
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)
        self.assertEqual(report["workspace"]["stageApprovedBy"], "Dr. Jamie Rivera")

        # One ledger entry per original document element, in order, all
        # completed -- the ledger's own `index` is a direct positional
        # map back onto `doc`.
        self.assertEqual(len(report["actionResults"]), len(doc))
        self.assertEqual([e["index"] for e in report["actionResults"]], list(range(len(doc))))
        self.assertEqual([e["action"] for e in report["actionResults"]], [d["action"] for d in doc])
        self.assertTrue(all(e["status"] == "completed" for e in report["actionResults"]))
        self.assertTrue(all(e["ok"] for e in report["actionResults"]))
        self.assertEqual(report["action_results"], report["actionResults"])

        # Restore points exist for the journey's major milestones.
        self.assertGreater(len(report["restorePoints"]), 0)

    def test_the_same_journey_via_the_cli_subprocess_exits_zero(self):
        scenario_path = self.root / "journey.json"
        scenario_path.write_text(json.dumps(self._doc()))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertIn("package", envelope["data"])


class ObjectFormAndFieldListFormStillUseTheBatchPathTests(unittest.TestCase):
    """Batch/object parity (root-cause fix requirement 5): object-form and
    field-list-form documents -- including ones that mix a field-list
    element with a single action-tagged one -- are never routed through
    the new ordered executor; they keep using `_run_steps`'s own
    pre-existing batch path unchanged."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_object_form_is_not_treated_as_an_action_list(self):
        self.assertFalse(scenario._is_action_list_document({"actor": "A"}))

    def test_field_list_form_is_not_treated_as_an_action_list(self):
        self.assertFalse(scenario._is_action_list_document([{"actor": "A"}, {"sources": []}]))

    def test_a_mixed_document_is_not_treated_as_an_action_list(self):
        self.assertFalse(scenario._is_action_list_document([{"actor": "A"}, {"action": "set_actor", "value": "B"}]))

    def test_an_empty_list_is_not_treated_as_an_action_list(self):
        self.assertFalse(scenario._is_action_list_document([]))

    def test_a_true_action_list_is_recognized(self):
        self.assertTrue(scenario._is_action_list_document([{"action": "set_actor", "value": "A"}]))

    def test_a_repeated_source_add_via_object_form_still_only_reflects_the_final_ledger_shape(self):
        """Object-form/field-list-form scenarios never gain the new
        per-action ledger granularity (there is no per-element order to
        preserve in a single JSON object) -- `actionResults` stays the
        pre-existing, `steps`-derived compatibility shape for that path,
        completely unchanged by this hardening cycle."""
        store = persistence.Store(root=self.root / "ws")
        doc = {
            "actor": "Tester",
            "brief": {"audience": "Devs", "eventType": "meetup", "durationMinutes": 20, "takeaway": "T",
                      "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            "sources": [
                {"origin": "local", "sourceType": "local_paste", "uri": "paste:one", "owner": "a@example.com",
                 "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1", "content": "Some content."},
            ],
        }
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(all("ok" in e for e in report["actionResults"]))
        self.assertFalse(any("index" in e for e in report["actionResults"]), "unchanged pre-existing shape, no new fields")


if __name__ == "__main__":
    unittest.main()
