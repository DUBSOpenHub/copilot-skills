"""Regression tests for the `add_source` action-list verb
(`engine/scenario._ACTION_ALIASES`): the public black-box vocabulary's
canonical name for staging a source, accepted as an exact synonym for the
pre-existing `ingest_source` verb -- both target the identical `sources`
object-form field and drive the identical `ingest_mod.ingest_source` code
path, never a second implementation.

Compatibility gap this closes: a staged scenario using `add_source`
previously failed normalization with a `VALIDATION_ERROR` naming only
`ingest_source` as the recognized verb (exit 1); `add_source` must now be
accepted and continue the scenario exactly like `ingest_source` would.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, cleanup, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")

_SOURCE_PAYLOAD = {
    "origin": "local", "sourceType": "local_paste", "uri": "paste:add-source-test",
    "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
    "version": "v1", "content": "A paragraph of authorized evidence content for this test.",
}


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


class AddSourceAliasNormalizationUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the normalization function itself."""

    def test_add_source_is_a_known_action(self):
        self.assertIn("add_source", scenario._ACTION_ALIASES)

    def test_add_source_and_ingest_source_target_the_identical_field(self):
        self.assertEqual(scenario._ACTION_ALIASES["add_source"], scenario._ACTION_ALIASES["ingest_source"])
        self.assertEqual(scenario._ACTION_ALIASES["add_source"], "sources")

    def test_add_source_normalizes_identically_to_ingest_source(self):
        add_doc = [{"action": "add_source", **_SOURCE_PAYLOAD}]
        ingest_doc = [{"action": "ingest_source", **_SOURCE_PAYLOAD}]
        self.assertEqual(scenario._normalize_scenario_doc(add_doc), scenario._normalize_scenario_doc(ingest_doc))

    def test_add_source_appends_one_item_per_element_like_ingest_source(self):
        doc = [
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:a"},
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:b"},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual([s["uri"] for s in merged["sources"]], ["paste:a", "paste:b"])

    def test_add_source_and_ingest_source_can_compose_in_the_same_document(self):
        """Both verbs may appear side by side (e.g. a migration in
        progress) and simply append into the same `sources` list -- they
        are the same field, not two competing ones."""
        doc = [
            {"action": "ingest_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:a"},
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:b"},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual([s["uri"] for s in merged["sources"]], ["paste:a", "paste:b"])

    def test_add_source_with_no_inline_payload_is_a_validation_error(self):
        from helpers import EngineError
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "add_source"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["field"], "sources")

    def test_add_source_still_rejects_a_raw_field_name(self):
        """`"sources"` itself remains an unknown action -- the public
        vocabulary is always a verb, never a raw object-form field name,
        exactly like `ingest_source`'s own existing regression guard."""
        from helpers import EngineError
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "sources", "uri": "paste:a"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class AddSourceAliasEndToEndTests(unittest.TestCase):
    """End-to-end coverage: a scenario built entirely from `add_source`
    steps must reach the identical outcome as the same scenario built
    from `ingest_source` steps."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _brief_and_source_doc(self, source_action: str) -> list[dict]:
        return [
            {"action": "set_talk_brief", "audience": "Developers", "eventType": "meetup",
             "durationMinutes": 20, "takeaway": "Provenance beats persuasion",
             "proofPoints": ["adoption stat"], "excludedTopics": [], "tone": "confident"},
            {"action": source_action, **_SOURCE_PAYLOAD},
        ]

    def test_add_source_ingests_and_continues_the_scenario_via_run_scenario_directly(self):
        store = persistence.Store(root=self.root / "workspace-root")
        doc = self._brief_and_source_doc("add_source")

        report = scenario.run_scenario(store, doc, self.root / "report")

        ingest_steps = [s for s in report["steps"] if s["action"] == "source.ingest"]
        self.assertEqual(len(ingest_steps), 1)
        self.assertEqual(ingest_steps[0]["uri"], _SOURCE_PAYLOAD["uri"])
        self.assertEqual(ingest_steps[0]["state"], "AUTHORIZED")
        # Continued past ingestion (evidence was extracted) -- not stuck
        # on an "unknown action" refusal.
        self.assertTrue(any(s["action"] == "evidence.extract" for s in report["steps"]))

    def test_add_source_and_ingest_source_produce_the_identical_outcome(self):
        add_report = scenario.run_scenario(
            persistence.Store(root=self.root / "add-root"),
            self._brief_and_source_doc("add_source"),
            self.root / "add-report",
        )
        ingest_report = scenario.run_scenario(
            persistence.Store(root=self.root / "ingest-root"),
            self._brief_and_source_doc("ingest_source"),
            self.root / "ingest-report",
        )
        add_ingest = next(s for s in add_report["steps"] if s["action"] == "source.ingest")
        ingest_ingest = next(s for s in ingest_report["steps"] if s["action"] == "source.ingest")
        self.assertEqual(add_ingest["state"], ingest_ingest["state"])
        self.assertEqual(add_ingest["uri"], ingest_ingest["uri"])

    def test_add_source_via_the_cli_subprocess_entry_point_exits_zero(self):
        scenario_path = self.root / "add-source-scenario.json"
        scenario_path.write_text(json.dumps(self._brief_and_source_doc("add_source")))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        # The minimal fixture here has no claims/routes, so the walk is
        # correctly *refused* further downstream (missing routes) -- the
        # point under test is only that `add_source` itself ingested and
        # let the scenario continue past it (evidence was extracted),
        # not that it reached Stage.
        steps = envelope["data"]["steps"]
        self.assertTrue(any(s["action"] == "source.ingest" and s["state"] == "AUTHORIZED" for s in steps))
        self.assertTrue(any(s["action"] == "evidence.extract" for s in steps))

    def test_an_unknown_source_like_verb_is_still_rejected_through_the_cli(self):
        """Regression guard: only the two allowlisted verbs
        (`add_source`, `ingest_source`) work -- an unrelated made-up verb
        is still a clean `VALIDATION_ERROR`, never silently accepted."""
        doc = self._brief_and_source_doc("stage_source")
        scenario_path = self.root / "bad-verb-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 1)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(envelope["error"]["details"]["action"], "stage_source")


if __name__ == "__main__":
    unittest.main()
