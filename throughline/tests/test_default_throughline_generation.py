"""Regression tests for deterministic candidate-throughline generation
(FR-NAR-1; `engine/narrative.default_throughline_drafts`): a proposal step
that isn't given its own explicit drafts (normally the Skill Prompt
Layer's job) must still deterministically produce exactly three real,
non-empty, brief-derived candidates -- with no automatic selection --
rather than an empty list or a hard failure.

Compatibility gap this closes: `narrative propose-throughlines` invoked
with no `--input` (and a `run-scenario` document with no
`throughlineDrafts`) previously called `propose_throughlines` with zero
drafts, which raised `VALIDATION_ERROR` ("exactly 3 ... required, got
0"); nothing was ever persisted, so the observed candidate list was
empty. Both the direct CLI command and `run_scenario` now fall back to
`narrative.default_throughline_drafts(brief)` -- the same helper in both
places -- rather than a fixed, acceptance-only placeholder string.
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


def _run_cli(*args, input=None, timeout=60):  # noqa: A002 - matches subprocess.run's own kwarg name
    return subprocess.run([sys.executable, BIN, *args], input=input, capture_output=True, text=True, timeout=timeout)


class DefaultDraftsHelperUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the pure derivation function."""

    def test_returns_exactly_three_distinct_non_empty_strings(self):
        brief = models.TalkBrief(id="brief:x", workspace_id="workspace:x", **{
            "audience": "Developers", "event_type": "meetup", "takeaway": "Ship faster",
            "proof_points": ["adoption stat"], "tone": "confident",
        })
        drafts = narrative.default_throughline_drafts(brief)
        self.assertEqual(len(drafts), narrative.REQUIRED_THROUGHLINE_COUNT)
        self.assertTrue(all(isinstance(d, str) and d.strip() for d in drafts))
        self.assertEqual(len(set(drafts)), 3, "candidates must be distinct")

    def test_is_a_pure_deterministic_function_of_the_brief(self):
        brief = models.TalkBrief(id="brief:x", workspace_id="workspace:x", **{
            "audience": "Developers", "event_type": "meetup", "takeaway": "Ship faster",
            "proof_points": ["adoption stat"], "tone": "confident",
        })
        self.assertEqual(narrative.default_throughline_drafts(brief), narrative.default_throughline_drafts(brief))

    def test_different_briefs_yield_different_candidates(self):
        brief_a = models.TalkBrief(id="brief:a", workspace_id="workspace:a", **{
            "audience": "Developers", "takeaway": "Ship faster",
        })
        brief_b = models.TalkBrief(id="brief:b", workspace_id="workspace:b", **{
            "audience": "Executives", "takeaway": "Cut costs",
        })
        self.assertNotEqual(narrative.default_throughline_drafts(brief_a), narrative.default_throughline_drafts(brief_b))

    def test_handles_a_bare_minimum_or_missing_brief_without_ever_being_empty(self):
        for brief in (None, models.TalkBrief(id="brief:blank", workspace_id="workspace:blank")):
            with self.subTest(brief=brief):
                drafts = narrative.default_throughline_drafts(brief)
                self.assertEqual(len(drafts), 3)
                self.assertTrue(all(d.strip() for d in drafts))

    def test_drafts_pass_straight_into_propose_throughlines_unchanged(self):
        """The helper only derives text; persistence/validation still
        flows entirely through the existing `propose_throughlines`
        contract -- this is additive, not a second persistence path."""
        store, root = new_store()
        try:
            ws, brief, conn = make_workspace(store)
            drafts = narrative.default_throughline_drafts(brief)
            created = narrative.propose_throughlines(conn, ws.id, brief.id, drafts, actor="T")
            self.assertEqual(len(created), 3)
            self.assertTrue(all(not t.selected for t in created), "generation alone must not auto-select")
            conn.close()
        finally:
            cleanup(root)


class DirectCliPropDefaultGenerationTests(unittest.TestCase):
    """The direct `narrative propose-throughlines` CLI command, exercised
    with no explicit drafts at all."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _open_workspace_with_brief(self):
        proc = _run_cli(
            "--workspace-root", str(self.root), "workspace", "new", "--actor", "T",
            input=json.dumps(DEFAULT_BRIEF),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_propose_throughlines_with_no_input_at_all_still_returns_exactly_three(self):
        self._open_workspace_with_brief()
        proc = subprocess.run(
            [sys.executable, BIN, "--workspace-root", str(self.root), "narrative", "propose-throughlines", "--actor", "T"],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        throughlines = envelope["data"]["throughlines"]
        self.assertEqual(len(throughlines), 3)
        self.assertTrue(all(t["text"].strip() for t in throughlines))
        self.assertTrue(all(not t["selected"] for t in throughlines), "no automatic selection")

    def test_propose_throughlines_with_an_empty_drafts_list_also_falls_back_to_the_default(self):
        self._open_workspace_with_brief()
        proc = _run_cli(
            "--workspace-root", str(self.root), "narrative", "propose-throughlines", "--actor", "T",
            input=json.dumps({"drafts": []}),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(len(envelope["data"]["throughlines"]), 3)

    def test_the_narrative_list_command_confirms_the_candidates_were_actually_persisted(self):
        """The literal regression check: `narrative list` must show 3
        candidates, never the previously-observed empty list."""
        self._open_workspace_with_brief()
        proc = subprocess.run(
            [sys.executable, BIN, "--workspace-root", str(self.root), "narrative", "propose-throughlines", "--actor", "T"],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        listed = _run_cli("--workspace-root", str(self.root), "narrative", "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(len(json.loads(listed.stdout)["data"]["throughlines"]), 3)

    def test_explicit_drafts_still_take_priority_over_the_default(self):
        """Backward compatibility: supplying real drafts is completely
        unaffected by the new fallback."""
        self._open_workspace_with_brief()
        proc = _run_cli(
            "--workspace-root", str(self.root), "narrative", "propose-throughlines", "--actor", "T",
            input=json.dumps(["Custom A", "Custom B", "Custom C"]),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        texts = {t["text"] for t in json.loads(proc.stdout)["data"]["throughlines"]}
        self.assertEqual(texts, {"Custom A", "Custom B", "Custom C"})


class ScenarioRunnerDefaultGenerationTests(unittest.TestCase):
    """"Through the public scenario interface": `run_scenario` given a
    document with no `throughlineDrafts` field at all -- the flagship
    black-box entry point, not just the direct CLI subcommand."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _minimal_doc(self, **extra) -> dict:
        doc = {
            "actor": "Test Speaker",
            "brief": dict(
                audience="Conference attendees", eventType="keynote", durationMinutes=20,
                takeaway="Structured evidence review de-risks talks", proofPoints=["adoption stat"],
                excludedTopics=[], tone="confident",
            ),
        }
        doc.update(extra)
        return doc

    def _persisted_throughlines(self, store, workspace_id):
        conn = store.connect(workspace_id)
        try:
            return persistence.list_all(conn, "throughline", workspace_id, models.NarrativeThroughline)
        finally:
            conn.close()

    def _assert_reached_narrative_selection(self, report):
        """These minimal fixtures deliberately omit route drafts, so the
        overall scenario is later, separately, and correctly refused for
        missing routes -- irrelevant to candidate generation, which
        already ran (and persisted) earlier in the same walk. A
        `narrative.select_throughline` step is only appended after
        `propose_throughlines`/`select_throughline` both ran without
        raising, so its presence is itself the proof generation
        succeeded."""
        self.assertTrue(
            any(s["action"] == "narrative.select_throughline" for s in report["steps"]), report.get("refusal"),
        )

    def test_a_scenario_with_no_throughline_drafts_field_still_persists_exactly_three(self):
        store = persistence.Store(root=self.root / "workspace-root")
        report = scenario.run_scenario(store, self._minimal_doc(), self.root / "report")
        self._assert_reached_narrative_selection(report)

        all_throughlines = self._persisted_throughlines(store, report["workspaceId"])
        self.assertEqual(len(all_throughlines), 3)
        self.assertTrue(all(t.text.strip() for t in all_throughlines))
        self.assertEqual(len({t.text for t in all_throughlines}), 3, "candidates must be distinct")

    def test_an_explicit_but_empty_throughline_drafts_field_also_falls_back_to_the_default(self):
        """Field-list-form callers may send `{"throughlineDrafts": []}`
        explicitly (key present, value empty) rather than omitting the
        key -- this must fall back exactly like omitting it entirely,
        not raise `VALIDATION_ERROR` for "0 candidates supplied"."""
        store = persistence.Store(root=self.root / "empty-drafts-root")
        report = scenario.run_scenario(store, self._minimal_doc(throughlineDrafts=[]), self.root / "empty-drafts-report")
        self._assert_reached_narrative_selection(report)
        self.assertEqual(len(self._persisted_throughlines(store, report["workspaceId"])), 3)

    def test_explicit_throughline_drafts_are_still_used_unchanged(self):
        store = persistence.Store(root=self.root / "explicit-drafts-root")
        doc = self._minimal_doc(throughlineDrafts=["Alpha", "Beta", "Gamma"])
        report = scenario.run_scenario(store, doc, self.root / "explicit-drafts-report")
        self._assert_reached_narrative_selection(report)
        texts = {t.text for t in self._persisted_throughlines(store, report["workspaceId"])}
        self.assertEqual(texts, {"Alpha", "Beta", "Gamma"})

    def test_action_list_scenario_with_no_propose_throughline_steps_also_generates_three(self):
        """The action-list form (no `propose_throughline` actions at all)
        composes with the same fallback -- not a special case of the
        object-form document."""
        doc = [
            {"action": "set_talk_brief", "audience": "Developers", "eventType": "meetup",
             "durationMinutes": 20, "takeaway": "Ship faster", "proofPoints": ["adoption stat"],
             "excludedTopics": [], "tone": "confident"},
        ]
        store = persistence.Store(root=self.root / "action-list-root")
        report = scenario.run_scenario(store, doc, self.root / "action-list-report")
        self._assert_reached_narrative_selection(report)
        self.assertEqual(len(self._persisted_throughlines(store, report["workspaceId"])), 3)

    def test_a_valid_proposal_flow_via_the_cli_subprocess_produces_exactly_three_candidates(self):
        scenario_path = self.root / "minimal-scenario.json"
        scenario_path.write_text(json.dumps(self._minimal_doc()))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))

        listed = _run_cli("--workspace-root", str(self.root / "ws"), "narrative", "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(len(json.loads(listed.stdout)["data"]["throughlines"]), 3)


if __name__ == "__main__":
    unittest.main()
