"""Regression tests for the top-level, snake_case identity fields
(`workspace_id`, `deck_id`) added to the CLI's JSON envelope
(`engine/cli.py`'s `emit`/`_identity_fields`) — the "default-workspace
response contract" black-box gap: a no-workspace `run-scenario`
invocation against a fresh `THROUGHLINE_HOME` opened a talk workspace and
exited 0, but the workspace identity was only reachable as
`data.workspaceId`, nested inside the generic `ok`/`data`/`error`
envelope, with no top-level `workspace_id` a caller could read without
already knowing that command's own nested shape.

Contract (docs/engine-cli-reference.md's "Wire contract" section):
- Every successful envelope keeps its existing `ok`/`data`/`error` shape
  and every nested field exactly as documented — this is purely additive.
- Whenever a workspace identity is discoverable anywhere in `data` (a
  `run-scenario` report -- including its bare/default-workspace form --
  or a `workspace new`/`show`/`resume`/bare-no-subcommand response, active
  or freshly opened), the envelope also carries a top-level `workspace_id`
  equal to that same identity.
- Whenever a deck identity is discoverable (a `run-scenario` report's
  `package`, `export package`, `export pptx`, or a `workspace` response
  once a deck has been compiled), the envelope also carries a top-level
  `deck_id`.
- A first and a later invocation against the same resolved workspace root
  (via `THROUGHLINE_HOME`, `THROUGHLINE_WORKSPACE_ROOT`, or
  `--workspace-root`) surface the identical `workspace_id`, whether the
  later call idempotently resumes that same workspace (`run-scenario`'s
  own contract) or is correctly refused for some other reason -- so a
  caller can use the first response's identity to verify resume behavior.
- Neither field is ever fabricated: both are simply absent whenever the
  underlying identity isn't present in `data` (including every error
  envelope, where `data` is always `null`).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, cleanup, new_root, persistence, scenario

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"
BIN = str(REPO_ROOT / "bin" / "throughline-engine")
_SCRUBBED_VARS = ("THROUGHLINE_WORKSPACE_ROOT", "THROUGHLINE_HOME")


def _clean_env(**overrides: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_VARS}
    env.update(overrides)
    return env


def _run_cli(*args, env=None, timeout=120):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout, env=env)


class DefaultWorkspaceScenarioIdentityTests(unittest.TestCase):
    """The exact black-box-reported scenario: a no-workspace
    `run-scenario` invocation against a fresh `THROUGHLINE_HOME`."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_bare_run_scenario_against_a_fresh_throughline_home_returns_top_level_workspace_and_deck_id(self):
        resolved_root = self.root / "fresh-home"
        proc = _run_cli(
            "run-scenario", "--scenario", str(FIXTURE),
            env=_clean_env(THROUGHLINE_HOME=str(resolved_root)),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)

        # Existing envelope/nested compatibility is fully preserved.
        self.assertTrue(envelope["ok"])
        self.assertIsNone(envelope["error"])
        self.assertTrue(envelope["data"]["ok"])
        self.assertIsNone(envelope["data"]["refusal"])

        # New: top-level, snake_case identity, additive alongside the above.
        self.assertIn("workspace_id", envelope)
        self.assertEqual(envelope["workspace_id"], envelope["data"]["workspaceId"])
        self.assertTrue(envelope["workspace_id"].startswith("workspace:"))
        self.assertIn("deck_id", envelope)
        self.assertEqual(envelope["deck_id"], envelope["data"]["package"]["deckId"])

    def test_first_and_repeated_invocation_against_the_same_throughline_home_return_the_same_identity(self):
        """The literal "a later invocation can use that identity to
        verify resume behavior" acceptance requirement: a second call
        against the same resolved root (no `workspace reset` in between)
        idempotently *resumes* the first call's own workspace -- never
        refused `WORKSPACE_ALREADY_ACTIVE` -- and reports the identical
        `workspace_id` throughout."""
        env = _clean_env(THROUGHLINE_HOME=str(self.root / "shared-home"))

        first = _run_cli("run-scenario", "--scenario", str(FIXTURE), env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_envelope = json.loads(first.stdout)
        first_workspace_id = first_envelope["workspace_id"]
        self.assertTrue(first_workspace_id)

        second = _run_cli("run-scenario", "--scenario", str(FIXTURE), env=env)
        self.assertEqual(second.returncode, 0, second.stderr)
        second_envelope = json.loads(second.stdout)
        self.assertTrue(second_envelope["data"]["ok"])
        self.assertIsNone(second_envelope["data"]["refusal"])
        self.assertTrue(second_envelope["data"]["workspaceResumed"])
        self.assertEqual(second_envelope["workspace_id"], first_workspace_id)

        third = _run_cli("run-scenario", "--scenario", str(FIXTURE), env=env)
        self.assertEqual(json.loads(third.stdout)["workspace_id"], first_workspace_id)

        # A plain `workspace show` against the same root agrees too.
        shown = _run_cli("--workspace-root", str(self.root / "shared-home"), "workspace", "show")
        self.assertEqual(json.loads(shown.stdout)["workspace_id"], first_workspace_id)

    def test_export_dir_override_composes_with_the_identity_fields(self):
        resolved_root = self.root / "fresh-home"
        export_dir = self.root / "export-dir"
        proc = _run_cli(
            "run-scenario", "--scenario", str(FIXTURE), "--export-dir", str(export_dir),
            env=_clean_env(THROUGHLINE_HOME=str(resolved_root)),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["workspace_id"], envelope["data"]["workspaceId"])
        self.assertEqual(envelope["deck_id"], envelope["data"]["package"]["deckId"])


class WorkspaceLifecycleIdentityTests(unittest.TestCase):
    """The same top-level identity promotion applies uniformly to every
    workspace-opening/resuming command, not just `run-scenario` -- one
    envelope-level rule (`_identity_fields`), not a special case."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_workspace_new_returns_top_level_workspace_id(self):
        proc = _run_cli("--workspace-root", str(self.root), "workspace", "new", "--actor", "Speaker")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["workspace_id"], envelope["data"]["workspace"]["id"])

    def test_workspace_show_returns_top_level_workspace_id_when_active(self):
        _run_cli("--workspace-root", str(self.root), "workspace", "new", "--actor", "Speaker")
        proc = _run_cli("--workspace-root", str(self.root), "workspace", "show")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["workspace_id"], envelope["data"]["workspace"]["id"])

    def test_workspace_show_omits_the_identity_field_when_no_workspace_is_active(self):
        proc = _run_cli("--workspace-root", str(self.root), "workspace", "show")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["data"]["active"])
        self.assertNotIn("workspace_id", envelope)
        self.assertNotIn("deck_id", envelope)

    def test_bare_no_subcommand_invocation_returns_top_level_workspace_id(self):
        proc = _run_cli("--workspace-root", str(self.root))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["workspace_id"], envelope["data"]["workspace"]["id"])

    def test_workspace_resume_returns_top_level_workspace_id_matching_the_original(self):
        opened = _run_cli("--workspace-root", str(self.root), "workspace", "new", "--actor", "Speaker")
        original_id = json.loads(opened.stdout)["workspace_id"]

        reset = _run_cli("--workspace-root", str(self.root), "workspace", "reset", "--actor", "Speaker")
        self.assertEqual(reset.returncode, 0, reset.stderr)
        self.assertNotIn("workspace_id", json.loads(reset.stdout))  # closing, not opening/resuming

        resumed = _run_cli("--workspace-root", str(self.root), "workspace", "resume", "--id", original_id, "--actor", "Speaker")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        resumed_envelope = json.loads(resumed.stdout)
        self.assertEqual(resumed_envelope["workspace_id"], original_id)
        self.assertEqual(resumed_envelope["data"]["workspace"]["id"], original_id)


class DeckAndPackageIdentityTests(unittest.TestCase):
    """`deck_id` is surfaced "consistently" (per the acceptance
    requirement) everywhere a deck identity is available, including
    commands that never surface a `workspace_id` (e.g. `export
    package`, whose own result has no workspace-identity shape)."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_export_package_returns_top_level_deck_id(self):
        # Drive the full journey in-process (fast) so the on-disk
        # workspace is already Stage-approved and packaged once, then
        # exercise the public CLI's own `export package` on top of it.
        store = persistence.Store(root=self.root)
        report = scenario.run_scenario(store, json.loads(FIXTURE.read_text()), self.root / "report")
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])

        proc = _run_cli("--workspace-root", str(self.root), "export", "package", "--actor", "Speaker")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["deck_id"], envelope["data"]["deckId"])
        self.assertEqual(envelope["deck_id"], report["package"]["deckId"])


class IdentityFieldsNeverFabricatedTests(unittest.TestCase):
    """Absence, not a fabricated placeholder, whenever no identity shape
    is present in `data` -- including every error envelope."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_a_command_with_neither_identity_shape_omits_both_top_level_fields(self):
        _run_cli("--workspace-root", str(self.root), "workspace", "new", "--actor", "Speaker")
        proc = _run_cli("--workspace-root", str(self.root), "evidence", "list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(envelope["data"], {"evidenceAtoms": []})
        self.assertNotIn("workspace_id", envelope)
        self.assertNotIn("deck_id", envelope)

    def test_an_error_envelope_never_carries_a_fabricated_identity_field(self):
        proc = _run_cli("--workspace-root", str(self.root), "workspace", "resume", "--id", "workspace:doesnotexist", "--actor", "Speaker")
        self.assertEqual(proc.returncode, 1)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertIsNone(envelope["data"])
        self.assertNotIn("workspace_id", envelope)
        self.assertNotIn("deck_id", envelope)


if __name__ == "__main__":
    unittest.main()
