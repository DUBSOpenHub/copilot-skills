"""Regression tests for narrative-throughline candidate/selection
persistence in the `run-scenario` report, even when a later step is
correctly refused (`engine/scenario._run_steps`'s `report["throughline"]`
block): a valid proposal flow always yields exactly three candidate
throughlines (FR-NAR-1, `narrative.default_throughline_drafts`), and
whichever one is selected -- including a wholly new, speaker-authored
replacement text (`select_throughline`'s `"text"` alias /
`select_custom_throughline`) -- becomes the active throughline and is
recorded in the report, *before* any later route/gate step gets a chance
to refuse the rest of the walk.

Compatibility gap this closes: the report exposed no `candidates`/active-
replacement information at all -- only a `narrative.select_throughline`
step naming the selected throughline's id -- so a black-box caller
inspecting a run that was later, correctly refused (e.g. for missing
narrative routes) saw no evidence the three-candidate proposal or the
speaker-authored selection had happened at all, even though both had
already durably completed and persisted before the refusal.

Contract: `report["throughline"]` is populated immediately once a
throughline is selected -- `report["throughline"]["candidates"]` is
always a list of exactly the three proposed candidates
(`{"id", "text", "origin"}` each), and `report["throughline"]["active"]`
is the one that was actually selected. Because `report` is mutated in
place, this survives an `EngineError` raised by any later step
(`run_scenario`'s own contract: a domain refusal is recorded, never
rolled back) -- so it is present in the *final* report/result document
exactly as it would be in a fully successful run.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, cleanup, new_root, persistence, scenario

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


class DefaultCandidatesPersistOnALaterRefusalTests(unittest.TestCase):
    """A "just run a valid proposal flow" scenario -- no explicit
    `throughlineDrafts`, no route drafts -- still gets exactly three real
    candidates persisted in the report, even though the walk is
    necessarily, correctly refused further down for missing routes."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_report_exposes_exactly_three_candidates_despite_the_later_missing_routes_refusal(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, [_brief_step()], self.root / "report")

        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("narrative route", report["refusal"]["message"])

        self.assertIn("throughline", report)
        candidates = report["throughline"]["candidates"]
        self.assertEqual(len(candidates), 3)
        self.assertEqual(len({c["text"] for c in candidates}), 3, "candidates must be distinct")
        for c in candidates:
            self.assertTrue(c["id"].startswith("throughline:"))
            self.assertEqual(c["origin"], "proposed")

    def test_the_default_selected_candidate_is_recorded_as_active(self):
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, [_brief_step()], self.root / "report")
        active = report["throughline"]["active"]
        candidates = report["throughline"]["candidates"]
        self.assertEqual(active["id"], candidates[0]["id"])
        self.assertEqual(active["origin"], "proposed")

    def test_the_narrative_select_throughline_step_is_still_recorded_too(self):
        """Purely additive: the pre-existing `steps` entry is unaffected."""
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, [_brief_step()], self.root / "report")
        select_step = next(s for s in report["steps"] if s["action"] == "narrative.select_throughline")
        self.assertEqual(select_step["throughlineId"], report["throughline"]["active"]["id"])


class SpeakerAuthoredReplacementPersistsOnALaterRefusalTests(unittest.TestCase):
    """The literal acceptance requirement: speaker-authored replacement
    text (never one of the three generated candidates) becomes the active
    throughline, and that fact is recorded in the report even when the
    later route requirement (two or three routes) is not yet satisfied."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _doc(self, selector_action: dict) -> list[dict]:
        return [_brief_step(), selector_action]

    def test_select_throughline_text_replacement_becomes_active_before_the_route_refusal(self):
        store = persistence.Store(root=self.root / "ws")
        doc = self._doc({"action": "select_throughline", "text": "An entirely new custom throughline"})
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        self.assertIn("narrative route", report["refusal"]["message"])

        self.assertEqual(len(report["throughline"]["candidates"]), 3)
        active = report["throughline"]["active"]
        self.assertEqual(active["text"], "An entirely new custom throughline")
        self.assertEqual(active["origin"], "custom")
        self.assertNotIn(active["id"], {c["id"] for c in report["throughline"]["candidates"]})

    def test_select_custom_throughline_replacement_also_persists_before_the_route_refusal(self):
        store = persistence.Store(root=self.root / "ws")
        doc = self._doc({"action": "select_custom_throughline", "value": "Another speaker-authored replacement"})
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertFalse(report["ok"])
        active = report["throughline"]["active"]
        self.assertEqual(active["text"], "Another speaker-authored replacement")
        self.assertEqual(active["origin"], "custom")

    def test_the_replacement_is_durably_persisted_on_disk_not_just_in_memory(self):
        """`report` reflects what `narrative.select_throughline` already
        committed to SQLite before the later refusal -- proven here by
        reopening the workspace's own store directly."""
        from helpers import models, persistence as persistence_mod

        store = persistence.Store(root=self.root / "ws")
        doc = self._doc({"action": "select_throughline", "text": "Persisted replacement text"})
        report = scenario.run_scenario(store, doc, self.root / "report")

        conn = store.connect(report["workspaceId"])
        try:
            all_throughlines = persistence_mod.list_all(conn, "throughline", report["workspaceId"], models.NarrativeThroughline)
        finally:
            conn.close()
        self.assertEqual(len(all_throughlines), 4, "the 3 proposed drafts plus the 1 new custom entry")
        selected = [t for t in all_throughlines if t.selected]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].text, "Persisted replacement text")
        self.assertEqual(selected[0].id, report["throughline"]["active"]["id"])

    def test_speaker_authored_replacement_persists_through_the_cli_subprocess_too(self):
        doc = self._doc({"action": "select_throughline", "text": "CLI speaker-authored replacement"})
        scenario_path = self.root / "speaker-authored-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertFalse(envelope["data"]["ok"])  # the later route requirement is still correctly unmet
        data = envelope["data"]
        self.assertEqual(len(data["throughline"]["candidates"]), 3)
        self.assertEqual(data["throughline"]["active"]["text"], "CLI speaker-authored replacement")
        self.assertEqual(data["throughline"]["active"]["origin"], "custom")

    def test_a_replacement_that_does_satisfy_every_later_requirement_still_reaches_stage(self):
        """The candidate/active reporting is purely additive -- a
        scenario that *does* go on to satisfy every later requirement
        still reaches Stage exactly as before, with the same reporting
        now included."""
        fixture = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"
        doc = json.loads(fixture.read_text())
        doc.pop("selectThroughlineIndex")
        doc["selectThroughlineText"] = "A fully-completed speaker replacement"

        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertEqual(len(report["throughline"]["candidates"]), 3)
        self.assertEqual(report["throughline"]["active"]["text"], "A fully-completed speaker replacement")
        self.assertEqual(report["throughline"]["active"]["origin"], "custom")
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)


if __name__ == "__main__":
    unittest.main()
