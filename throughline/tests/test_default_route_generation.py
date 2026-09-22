"""Regression tests for deterministic candidate-route generation (FR-NAR-3;
`engine/narrative.default_route_drafts`): a *source-driven* scenario
(one that has actually ingested at least one source) that doesn't stage
its own `routeDrafts`/`propose_route` entries still deterministically
gets exactly two real, brief/throughline/claim-derived route candidates
-- with no automatic selection -- rather than an empty list and the
"exactly 2 or 3 narrative routes are required (got 0)" refusal.

Compatibility gap this closes: a scenario with sources/claims/a selected
throughline but no explicit route drafts previously called
`narrative.propose_routes` with zero drafts, which always raised
`VALIDATION_ERROR`; every downstream step (compile, gates, rehearsal,
package) was then unreachable -- candidate/route/readiness state stayed
empty even though the source-driven journey up to that point was
otherwise entirely valid.

Deliberately narrower than the throughline fallback (which fires for any
completed brief, sources or not): a bare brief-only scenario with no
source context at all still gets *no* default routes and is still
correctly refused for missing routes, exactly as before -- this is the
literal, pinned behavior of `tests/test_candidate_persistence_on_refusal.py`
and `tests/test_default_throughline_generation.py`'s own
`ScenarioRunnerDefaultGenerationTests`, both left completely unaffected by
this change (see the tests below that assert this explicitly).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import (
    DEFAULT_BRIEF, REPO_ROOT, cleanup, make_workspace, models, narrative, new_root, new_store, persistence, scenario,
)

BIN = str(REPO_ROOT / "bin" / "throughline")


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


class DefaultRouteDraftsHelperUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the pure derivation function."""

    def _brief(self, **overrides) -> models.TalkBrief:
        payload = {"audience": "Developers", "event_type": "meetup", "takeaway": "Ship faster",
                   "duration_minutes": 20.0, "proof_points": ["adoption stat"], "tone": "confident"}
        payload.update(overrides)
        return models.TalkBrief(id="brief:x", workspace_id="workspace:x", **payload)

    def _throughline(self, text: str = "Ship faster with confidence") -> models.NarrativeThroughline:
        return models.NarrativeThroughline(id="throughline:x", workspace_id="workspace:x", brief_id="brief:x", text=text)

    def test_returns_exactly_two_route_drafts(self):
        drafts = narrative.default_route_drafts(self._brief(), self._throughline(), [])
        self.assertEqual(len(drafts), 2)
        self.assertIn(len(drafts), narrative.VALID_ROUTE_COUNT)

    def test_each_draft_is_a_narrative_gate_passable_seven_beat_spine(self):
        drafts = narrative.default_route_drafts(self._brief(), self._throughline(), [])
        for draft in drafts:
            with self.subTest(label=draft["label"]):
                roles = [b["role"] for b in draft["beats"]]
                self.assertGreaterEqual(len(roles), narrative.MIN_SLIDES)
                self.assertLessEqual(len(roles), narrative.MAX_SLIDES)
                self.assertEqual(roles[0], "HOOK")
                self.assertEqual(roles[-1], "ASK")
                self.assertTrue(all(roles[i] != roles[i + 1] for i in range(len(roles) - 1)), roles)
                self.assertTrue(all(b["headline"].strip() for b in draft["beats"]))

    def test_the_two_drafts_have_distinct_labels(self):
        drafts = narrative.default_route_drafts(self._brief(), self._throughline(), [])
        self.assertEqual(len({d["label"] for d in drafts}), 2)

    def test_is_a_pure_deterministic_function_of_its_inputs(self):
        brief, throughline = self._brief(), self._throughline()
        self.assertEqual(
            narrative.default_route_drafts(brief, throughline, []),
            narrative.default_route_drafts(brief, throughline, []),
        )

    def test_handles_a_missing_brief_or_throughline_without_ever_being_empty(self):
        drafts = narrative.default_route_drafts(None, None, None)
        self.assertEqual(len(drafts), 2)
        for draft in drafts:
            self.assertTrue(all(b["headline"].strip() for b in draft["beats"]))

    def test_no_proof_beat_is_included_without_a_qualifying_claim(self):
        drafts = narrative.default_route_drafts(self._brief(), self._throughline(), [])
        for draft in drafts:
            roles = [b["role"] for b in draft["beats"]]
            self.assertNotIn("PROOF", roles, "never an uncited PROOF beat")

    def test_an_unapproved_verified_claim_still_does_not_earn_a_proof_beat(self):
        """A claim must be *approved* (not merely VERIFIED) before a
        default route will cite it -- referencing an unapproved claim in
        a compiled slide would otherwise fail the CLAIMS gate."""
        claim = models.Claim(id="claim:1", workspace_id="workspace:x", type="FACTUAL", text="X grew 42%.", state="VERIFIED")
        drafts = narrative.default_route_drafts(self._brief(), self._throughline(), [claim])
        for draft in drafts:
            roles = [b["role"] for b in draft["beats"]]
            self.assertNotIn("PROOF", roles)

    def test_a_qualifying_approved_factual_claim_earns_a_cited_proof_beat(self):
        claim = models.Claim(
            id="claim:1", workspace_id="workspace:x", type="FACTUAL", text="X grew 42%.",
            state="VERIFIED", approver="Jane Doe",
        )
        drafts = narrative.default_route_drafts(self._brief(), self._throughline(), [claim])
        for draft in drafts:
            proof_beats = [b for b in draft["beats"] if b["role"] == "PROOF"]
            self.assertEqual(len(proof_beats), 1)
            self.assertEqual(proof_beats[0]["claimIds"], ["claim:1"])

    def test_drafts_pass_straight_into_propose_routes_and_the_narrative_gate_unchanged(self):
        """The helper only derives beats -- persistence/validation still
        flows entirely through the existing `propose_routes`/narrative
        gate contract, and the resulting route is immediately selectable
        and compile-ready."""
        store, root = new_store()
        try:
            ws, brief, conn = make_workspace(store)
            throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, narrative.default_throughline_drafts(brief), actor="T")
            selected_t = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
            drafts = narrative.default_route_drafts(brief, selected_t, [])
            routes = narrative.propose_routes(conn, ws.id, selected_t.id, drafts, actor="T")
            self.assertEqual(len(routes), 2)
            self.assertTrue(all(not r.selected for r in routes), "generation alone must not auto-select")
            narrative.select_route(conn, ws.id, routes[0].id, actor="T")
            gate = narrative.run_narrative_gate(conn, ws.id, actor="T")
            self.assertTrue(gate.passed, gate.failed_checks)
            conn.close()
        finally:
            cleanup(root)


class ScenarioRunnerDefaultRouteGenerationTests(unittest.TestCase):
    """"Through the public scenario interface": a source-driven
    `run_scenario` document with no `routeDrafts` field at all."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _source_driven_doc(self, **extra) -> dict:
        doc = {
            "actor": "Test Speaker",
            "brief": dict(DEFAULT_BRIEF),
            "sources": [{
                "origin": "local", "sourceType": "local_paste", "uri": "paste:adoption-note",
                "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
                "version": "v1",
                "content": "Adoption grew 42% quarter over quarter across every pilot team surveyed.",
            }],
            "claims": [{
                "type": "factual", "text": "Adoption grew 42% quarter over quarter.",
                # Bare source URI (no "#pN" suffix) pulls in every
                # paragraph-atom extracted from it -- this content is a
                # single paragraph, so its one atom's own locator has no
                # "#p0" suffix (see `engine/evidence.py`).
                "evidenceLocators": ["paste:adoption-note"], "approve": True,
            }],
        }
        doc.update(extra)
        return doc

    def test_a_source_driven_scenario_with_no_route_drafts_reaches_stage_and_package(self):
        store = persistence.Store(root=self.root / "workspace-root")
        report = scenario.run_scenario(store, self._source_driven_doc(), self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertIsNone(report["refusal"])
        self.assertEqual(len(report["route"]["candidates"]), 2)
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)

    def test_the_default_route_cites_the_approved_factual_claim_in_a_proof_beat(self):
        store = persistence.Store(root=self.root / "workspace-root")
        report = scenario.run_scenario(store, self._source_driven_doc(), self.root / "report")
        conn = store.connect(report["workspaceId"])
        try:
            routes = persistence.list_all(conn, "route", report["workspaceId"], models.NarrativeRoute)
        finally:
            conn.close()
        self.assertTrue(any(b.role == "PROOF" for r in routes for b in r.beats))

    def test_an_action_list_source_driven_scenario_also_generates_default_routes(self):
        doc = [
            {"action": "set_talk_brief", **DEFAULT_BRIEF},
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:al-note",
             "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "A single paragraph of authorized evidence content for this test."},
            {"action": "propose_claim", "type": "factual", "text": "A cited figure.",
             "evidenceLocators": ["paste:al-note"], "approve": True},
            {"action": "compile_deck"},
        ]
        store = persistence.Store(root=self.root / "workspace-root")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(len(report["route"]["candidates"]), 2)
        self.assertIn("package", report)

    def test_explicit_route_drafts_are_still_used_unchanged_even_with_sources_present(self):
        """Backward compatibility: supplying real route drafts is
        completely unaffected by the new source-driven fallback."""
        doc = self._source_driven_doc(routeDrafts=[
            {"label": "Alpha", "beats": [
                {"role": "HOOK", "headline": "Alpha hook"}, {"role": "ASK", "headline": "Alpha ask"},
            ]},
            {"label": "Beta", "beats": [
                {"role": "HOOK", "headline": "Beta hook"}, {"role": "ASK", "headline": "Beta ask"},
            ]},
        ])
        store = persistence.Store(root=self.root / "workspace-root")
        report = scenario.run_scenario(store, doc, self.root / "report")
        labels = {c["label"] for c in report["route"]["candidates"]}
        self.assertEqual(labels, {"Alpha", "Beta"})

    def test_a_bare_brief_only_scenario_with_no_sources_is_still_correctly_refused(self):
        """Pins the pre-existing, unaffected behavior: no source context
        at all means no default routes, exactly as before."""
        doc = {"actor": "Test Speaker", "brief": dict(DEFAULT_BRIEF)}
        store = persistence.Store(root=self.root / "workspace-root")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("narrative route", report["refusal"]["message"])
        self.assertNotIn("route", report)

    def test_a_source_driven_scenario_via_the_cli_subprocess_reaches_package(self):
        scenario_path = self.root / "source-driven-scenario.json"
        scenario_path.write_text(json.dumps(self._source_driven_doc()))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))
        self.assertIn("package", envelope["data"])


if __name__ == "__main__":
    unittest.main()
