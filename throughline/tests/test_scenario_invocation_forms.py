"""Regression tests for `run-scenario`'s invocation forms — the legacy
`--out` contract, the public black-box `--workspace [--export-dir]`
contract, and the bare (no `--workspace`/`--out`) default-root contract
(ARCH §4; full bare-invocation precedence coverage lives in
`test_scenario_bare_invocation.py`) — plus the "a correctly
refused/blocked scenario step is still a normal, exit-0 completion"
contract: the refusal belongs in the result document, never the exit
code (`cli.py`'s wire contract; `scenario.run_scenario`'s own contract)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO_ROOT, cleanup, models, new_root, persistence, scenario

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"
BIN = str(REPO_ROOT / "bin" / "throughline-engine")


def _run_cli(*args, env=None, timeout=120):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout, env=env)


class WorkspaceAndExportDirInvocationTests(unittest.TestCase):
    """All three `run-scenario` invocation forms living side by side: the
    public black-box form (`--workspace [--export-dir]`), the legacy
    `--out` form, and the bare (neither flag) default-root form — each
    required to be accepted, and each mapped consistently onto the same
    underlying workspace-root/report/export behavior rather than a
    parallel implementation per form."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_workspace_flag_alone_runs_end_to_end_and_writes_the_report_at_its_root(self):
        workspace_dir = self.root / "workspace-dir"
        proc = _run_cli("run-scenario", "--scenario", str(FIXTURE), "--workspace", str(workspace_dir))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"])
        self.assertIsNone(envelope["data"]["refusal"])
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertIn("package", envelope["data"])

        report_path = workspace_dir / "run-report.json"
        self.assertTrue(report_path.exists())
        on_disk = json.loads(report_path.read_text())
        self.assertEqual(on_disk["workspaceId"], envelope["data"]["workspaceId"])

        # --workspace *is* the workspace root (no separate --workspace-root
        # needed): the internal state lives under it too.
        self.assertTrue((workspace_dir / "workspace").is_dir())

    def test_export_dir_places_the_stage_package_at_the_caller_specified_location(self):
        workspace_dir = self.root / "workspace-dir"
        export_dir = self.root / "export-dir"
        proc = _run_cli(
            "run-scenario", "--scenario", str(FIXTURE),
            "--workspace", str(workspace_dir), "--export-dir", str(export_dir),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertEqual(Path(envelope["data"]["package"]["exportDir"]), export_dir)
        self.assertTrue((export_dir / "deck.pptx").exists())
        self.assertTrue((export_dir / "manifest.json").exists())

    def test_legacy_out_form_still_works_unchanged(self):
        """Backward compatibility: the documented `--out` contract, driven
        through the global `--workspace-root` flag, is untouched."""
        out_dir = self.root / "report"
        proc = _run_cli(
            "--workspace-root", str(self.root / "legacy-workspace-root"),
            "run-scenario", "--scenario", str(FIXTURE), "--out", str(out_dir),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertTrue((out_dir / "run-report.json").exists())

    def test_neither_workspace_nor_out_is_the_bare_form_and_succeeds_using_the_default_workspace_root(self):
        """Third invocation form (ARCH §4/§11): `run-scenario --scenario
        <path>` alone is no longer a `VALIDATION_ERROR` — it is a fully
        supported bare invocation that resolves the workspace root (and
        the deterministic `run-report.json` location) via the same
        default-root precedence chain as every other command. Full
        precedence coverage (env vars, `THROUGHLINE_HOME`, refusal
        semantics, etc.) lives in `test_scenario_bare_invocation.py`; this
        test only pins that the exact black-box pattern named in the
        compatibility gap works, right alongside its sibling forms above."""
        resolved_root = self.root / "bare-default-root"
        env = {k: v for k, v in os.environ.items() if k not in ("THROUGHLINE_WORKSPACE_ROOT", "THROUGHLINE_HOME")}
        env["THROUGHLINE_WORKSPACE_ROOT"] = str(resolved_root)

        proc = _run_cli("run-scenario", "--scenario", str(FIXTURE), env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stdout)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"])
        self.assertIsNone(envelope["data"]["refusal"])
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertTrue((resolved_root / "run-report.json").exists())


class BlockedScenarioStepExitSemanticsTests(unittest.TestCase):
    """A scenario step that is correctly refused/blocked by a domain rule
    must still be a normal (`exit 0`) completion, with the refusal
    represented in the result document — never surfaced as a nonzero exit
    code."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_a_second_run_scenario_against_the_same_explicit_workspace_resumes_it(self):
        """`--workspace <dir>` names an explicit workspace by its resolved
        root path (ARCH §11) -- a second call against that same root, with
        no `workspace reset` in between, idempotently *resumes* that same
        workspace rather than being refused `WORKSPACE_ALREADY_ACTIVE`."""
        workspace_dir = self.root / "workspace-dir"
        first = _run_cli("run-scenario", "--scenario", str(FIXTURE), "--workspace", str(workspace_dir))
        self.assertEqual(first.returncode, 0, first.stderr)
        first_envelope = json.loads(first.stdout)
        self.assertTrue(first_envelope["data"]["ok"])
        self.assertFalse(first_envelope["data"]["workspaceResumed"])

        second = _run_cli("run-scenario", "--scenario", str(FIXTURE), "--workspace", str(workspace_dir))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("Traceback", second.stdout)
        second_envelope = json.loads(second.stdout)
        self.assertTrue(second_envelope["ok"], second_envelope.get("error"))
        self.assertTrue(second_envelope["data"]["ok"])
        self.assertIsNone(second_envelope["data"]["refusal"])
        self.assertTrue(second_envelope["data"]["workspaceResumed"])
        self.assertEqual(second_envelope["workspace_id"], first_envelope["workspace_id"])

        # Re-ingesting the identical fixture's source (same URI) a second
        # time is a genuine re-supersession (FR-SRC-5/6): the *first*
        # call's now-superseded evidence atoms are correctly marked STALE
        # and still block the EVIDENCE gate, so Stage correctly does not
        # pass again without a fresh disposition/claim pass over them --
        # NFR-2's exclusivity is relaxed for *resuming the same* workspace,
        # but no other domain rule (staleness included) is weakened by it.
        self.assertFalse(second_envelope["data"]["stageGate"]["passed"])
        self.assertNotIn("package", second_envelope["data"])

        report_path = workspace_dir / "run-report.json"
        self.assertTrue(report_path.exists())
        on_disk = json.loads(report_path.read_text())
        self.assertEqual(on_disk["workspaceId"], first_envelope["workspace_id"])

    def test_run_scenario_function_resumes_the_same_store_root_without_raising(self):
        """Direct (non-subprocess) unit coverage of `scenario.run_scenario`
        itself: a second call against the same store root resumes the
        first call's own workspace (never raising, and never refusing
        `WORKSPACE_ALREADY_ACTIVE`) -- `_open_or_resume_workspace`'s own
        contract, exercised end-to-end through `run_scenario`."""
        store = persistence.Store(root=self.root / "direct-workspace-root")
        out_dir = self.root / "direct-report"
        doc = json.loads(FIXTURE.read_text())

        first_report = scenario.run_scenario(store, doc, out_dir)
        self.assertTrue(first_report["ok"])
        self.assertIsNone(first_report["refusal"])
        self.assertFalse(first_report["workspaceResumed"])

        second_report = scenario.run_scenario(store, doc, out_dir)  # same store root, resumed
        self.assertTrue(second_report["ok"])
        self.assertIsNone(second_report["refusal"])
        self.assertTrue(second_report["workspaceResumed"])
        self.assertEqual(second_report["workspaceId"], first_report["workspaceId"])

    def test_sequential_calls_against_the_same_explicit_workspace_accumulate_sources(self):
        """The literal "sequential scenario calls" acceptance requirement:
        a later call targeting the same explicit `--workspace <dir>`
        resumes it and *accumulates* its own new sources into the single
        curated bundle already holding the first call's, rather than
        starting from (or being refused into) an empty one."""
        workspace_dir = self.root / "workspace-dir"
        store = persistence.Store(root=workspace_dir)

        first_doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:first",
             "owner": "a@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "First accumulated source."},
        ]
        first_report = scenario.run_scenario(store, first_doc, self.root / "report-1")
        self.assertFalse(first_report["workspaceResumed"])
        first_ingest = [s for s in first_report["steps"] if s["action"] == "source.ingest"]
        self.assertEqual([s["uri"] for s in first_ingest], ["paste:first"])

        second_doc = [
            {"action": "add_source", "origin": "manual", "sourceType": "local_paste", "uri": "paste:second",
             "owner": "a@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "Second accumulated source, added via an origin alias."},
        ]
        second_report = scenario.run_scenario(store, second_doc, self.root / "report-2")
        self.assertTrue(second_report["workspaceResumed"])
        self.assertEqual(second_report["workspaceId"], first_report["workspaceId"])
        second_ingest = [s for s in second_report["steps"] if s["action"] == "source.ingest"]
        self.assertEqual([s["uri"] for s in second_ingest], ["paste:second"])

        conn = store.connect(first_report["workspaceId"])
        try:
            sources = persistence.list_all(conn, "source", first_report["workspaceId"], models.SourceArtifact)
        finally:
            conn.close()
        self.assertEqual(sorted(s.uri for s in sources), ["paste:first", "paste:second"], "both calls' sources are in the one bundle")

    def test_a_bundle_limit_refusal_on_a_later_resumed_call_does_not_roll_back_the_first_calls_sources(self):
        """A resumed call's *own* domain refusals are completely
        unaffected by the exclusivity relaxation above: the 25-artifact
        cap (FR-SRC-... `BUNDLE_LIMIT_REACHED`) still applies across the
        accumulated, cross-call bundle, and a later call that would
        exceed it is still cleanly refused (exit 0, refusal recorded) --
        the first call's already-ingested sources are unaffected."""
        workspace_dir = self.root / "workspace-dir"
        store = persistence.Store(root=workspace_dir)

        def _source(uri: str) -> dict:
            return {
                "action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": uri,
                "owner": "a@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
                "version": "v1", "content": f"Content for {uri}.",
            }

        brief_step = {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
                       "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"}
        first_doc = [brief_step] + [_source(f"paste:bulk-{i}") for i in range(25)]
        first_report = scenario.run_scenario(store, first_doc, self.root / "report-1")
        # All 25 sources ingest cleanly regardless of whatever the walk's
        # own later, unrelated narrative-route refusal is (no routes were
        # supplied here) -- only source ingestion is under test.
        self.assertEqual(len([s for s in first_report["steps"] if s["action"] == "source.ingest"]), 25)

        second_report = scenario.run_scenario(store, [_source("paste:one-too-many")], self.root / "report-2")
        self.assertTrue(second_report["workspaceResumed"])
        self.assertFalse(second_report["ok"])
        self.assertEqual(second_report["refusal"]["code"], "BUNDLE_LIMIT_REACHED")

        conn = store.connect(first_report["workspaceId"])
        try:
            sources = persistence.list_all(conn, "source", first_report["workspaceId"], models.SourceArtifact)
        finally:
            conn.close()
        self.assertEqual(len(sources), 25, "the first call's 25 sources are untouched by the later refusal")


    def test_a_genuine_runtime_fault_is_not_swallowed_as_a_refusal(self):
        """Only `EngineError` (a deliberate domain refusal) is caught; a
        real bug must still propagate so the CLI reports it as a nonzero,
        explicit `INTERNAL_ERROR` rather than a fabricated refusal."""
        store = persistence.Store(root=self.root / "fault-workspace-root")
        out_dir = self.root / "fault-report"
        doc = json.loads(FIXTURE.read_text())
        doc["conflictDecisions"] = [{"claimIndex": 999, "decision": "oops"}]

        with self.assertRaises(IndexError):
            scenario.run_scenario(store, doc, out_dir)
        self.assertFalse((out_dir / "run-report.json").exists())

    def test_a_genuine_runtime_fault_still_surfaces_as_internal_error_through_the_cli(self):
        workspace_dir = self.root / "workspace-dir"
        doc = json.loads(FIXTURE.read_text())
        doc["conflictDecisions"] = [{"claimIndex": 999, "decision": "oops"}]
        scenario_path = self.root / "bad-conflict-index.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(workspace_dir))
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("Traceback", proc.stdout)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "INTERNAL_ERROR")
        self.assertIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
