"""Regression tests for the no-subcommand ("bare") public CLI invocation
form: `bin/throughline` with **no** subcommand at all (ARCH §4/§11;
`docs/engine-cli-reference.md`). This is distinct from — and composes
with — the bare `run-scenario` form covered by
`tests/test_scenario_bare_invocation.py`: that one is "run-scenario with
no --workspace/--out"; this one is "no subcommand named at all."

Contract: with no active workspace, a bare invocation opens the single
default talk workspace (exactly like `workspace new` with no brief) and
returns its identity; a later bare invocation against the same resolved
workspace root resumes (never recreates) that same workspace, returning
the identical identity. The returned shape is exactly what `workspace
show`'s active branch returns, so identity is directly comparable/
consistent with that command's own output. Every subprocess test here
scrubs `THROUGHLINE_WORKSPACE_ROOT`/`THROUGHLINE_HOME` from the inherited
environment so behavior is never accidentally influenced by (or leaks
into) the real `~/.copilot/throughline` or another test's env.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO_ROOT, cleanup, new_root

PRIMARY_BIN = str(REPO_ROOT / "bin" / "throughline")
LEGACY_BIN = str(REPO_ROOT / "bin" / "throughline-engine")
_SCRUBBED_VARS = ("THROUGHLINE_WORKSPACE_ROOT", "THROUGHLINE_HOME")


def _clean_env(**overrides: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_VARS}
    env.update(overrides)
    return env


def _run_cli(binary, *args, env=None, timeout=60):
    return subprocess.run([sys.executable, binary, *args], capture_output=True, text=True, timeout=timeout, env=env)


def _run_bare(root, binary=PRIMARY_BIN, timeout=60):
    return _run_cli(binary, "--workspace-root", str(root), timeout=timeout)


class BareInvocationOpensOrResumesDefaultWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_first_bare_invocation_with_no_existing_workspace_opens_the_default_workspace(self):
        proc = _run_bare(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stdout)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        data = envelope["data"]
        self.assertTrue(data["active"])
        self.assertTrue(data["workspace"]["id"].startswith("workspace:"))
        self.assertEqual(data["brief"]["id"], data["workspace"]["brief_id"])
        self.assertIn("nextAction", data)

    def test_a_second_bare_invocation_resumes_the_same_workspace_instead_of_creating_a_new_one(self):
        first = _run_bare(self.root)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_id = json.loads(first.stdout)["data"]["workspace"]["id"]

        second = _run_bare(self.root)
        self.assertEqual(second.returncode, 0, second.stderr)
        second_envelope = json.loads(second.stdout)
        self.assertTrue(second_envelope["data"]["active"])
        self.assertEqual(second_envelope["data"]["workspace"]["id"], first_id)

        third = _run_bare(self.root)
        self.assertEqual(json.loads(third.stdout)["data"]["workspace"]["id"], first_id)

    def test_bare_invocation_identity_matches_workspace_show(self):
        """Machine-readable identity parity: whatever the bare invocation
        reports must be exactly what an explicit `workspace show`
        reports immediately afterward -- same command surface, same
        state, not a divergent shadow copy of it."""
        bare = _run_bare(self.root)
        self.assertEqual(bare.returncode, 0, bare.stderr)
        bare_data = json.loads(bare.stdout)["data"]

        shown = _run_cli(PRIMARY_BIN, "--workspace-root", str(self.root), "workspace", "show")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        shown_data = json.loads(shown.stdout)["data"]

        self.assertEqual(bare_data["active"], shown_data["active"])
        self.assertEqual(bare_data["workspace"], shown_data["workspace"])
        self.assertEqual(bare_data["brief"], shown_data["brief"])
        self.assertEqual(bare_data["nextAction"], shown_data["nextAction"])

    def test_bare_invocation_honors_the_default_root_precedence_via_env_vars(self):
        """Same `--workspace-root` / `THROUGHLINE_WORKSPACE_ROOT` /
        `THROUGHLINE_HOME` precedence every other command uses
        (`persistence.default_root`) -- the bare form is not a parallel
        implementation with its own resolution rules."""
        resolved_root = self.root / "env-workspace-root"
        proc = _run_cli(PRIMARY_BIN, env=_clean_env(THROUGHLINE_WORKSPACE_ROOT=str(resolved_root)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["data"]["active"])
        self.assertTrue((resolved_root / "workspace").is_dir())

    def test_bare_invocation_and_bare_run_scenario_share_the_same_workspace_root(self):
        """Sanity check that the two independent "bare" contracts (no
        subcommand at all; `run-scenario` with no --workspace/--out) are
        not accidentally divergent: opening the default workspace first,
        then running the bare-form scenario against the identical
        resolved root, must see (and idempotently resume) that same
        workspace -- proving both paths resolve the workspace root
        identically."""
        env = _clean_env(THROUGHLINE_WORKSPACE_ROOT=str(self.root / "shared-root"))
        opened = _run_cli(PRIMARY_BIN, env=env)
        self.assertEqual(opened.returncode, 0, opened.stderr)
        opened_id = json.loads(opened.stdout)["data"]["workspace"]["id"]

        fixture = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"
        scenario_proc = _run_cli(PRIMARY_BIN, "run-scenario", "--scenario", str(fixture), env=env)
        self.assertEqual(scenario_proc.returncode, 0, scenario_proc.stderr)
        scenario_envelope = json.loads(scenario_proc.stdout)
        self.assertTrue(scenario_envelope["data"]["ok"])
        self.assertTrue(scenario_envelope["data"]["workspaceResumed"])
        self.assertEqual(scenario_envelope["data"]["workspaceId"], opened_id)



class BareInvocationEntryPointParityTests(unittest.TestCase):
    """`bin/throughline` and the legacy `bin/throughline-engine` alias
    must agree on the bare form exactly as they do on every explicit
    subcommand (`test_public_entrypoint.py`)."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_both_entry_points_open_the_same_identity_for_independent_roots(self):
        primary = _run_bare(self.root / "primary-root", binary=PRIMARY_BIN)
        legacy = _run_bare(self.root / "legacy-root", binary=LEGACY_BIN)
        self.assertEqual(primary.returncode, 0, primary.stderr)
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        primary_data = json.loads(primary.stdout)["data"]
        legacy_data = json.loads(legacy.stdout)["data"]
        self.assertTrue(primary_data["active"])
        self.assertTrue(legacy_data["active"])
        self.assertEqual(primary_data["nextAction"], legacy_data["nextAction"])

    def test_both_entry_points_resume_the_same_workspace_against_a_shared_root(self):
        shared_root = self.root / "shared-root"
        first = _run_bare(shared_root, binary=PRIMARY_BIN)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_id = json.loads(first.stdout)["data"]["workspace"]["id"]

        second = _run_bare(shared_root, binary=LEGACY_BIN)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["data"]["workspace"]["id"], first_id)


class ExplicitSubcommandsAndParserRegressionTests(unittest.TestCase):
    """Regression coverage for making the top-level subcommand optional
    (`build_parser`'s `add_subparsers(..., required=False)`): every
    existing explicit-subcommand and error-handling behavior must be
    completely unaffected -- only the *absence* of a subcommand changed
    meaning."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_explicit_workspace_show_subcommand_is_unaffected(self):
        proc = _run_cli(PRIMARY_BIN, "--workspace-root", str(self.root), "workspace", "show")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(json.loads(proc.stdout)["data"]["active"])

    def test_explicit_workspace_new_subcommand_is_unaffected(self):
        proc = _run_cli(PRIMARY_BIN, "--workspace-root", str(self.root), "workspace", "new", "--actor", "T")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_an_unrecognized_subcommand_still_exits_2_rather_than_opening_the_default_workspace(self):
        proc = _run_cli(PRIMARY_BIN, "--workspace-root", str(self.root), "not-a-real-command")
        self.assertEqual(proc.returncode, 2)
        # argparse rejects the invalid choice before any command ever
        # runs, so no workspace should have been opened as a side effect.
        self.assertFalse((self.root / "workspace").exists())

    def test_a_subcommand_missing_its_own_required_nested_sub_subcommand_still_exits_2(self):
        """`bin/throughline workspace` (no nested action) is a different
        error than the fully bare form -- still argparse's own required
        nested-subparser error, untouched by this cycle."""
        proc = _run_cli(PRIMARY_BIN, "--workspace-root", str(self.root), "workspace")
        self.assertEqual(proc.returncode, 2)

    def test_help_still_exits_zero_and_stays_identical_between_entry_points(self):
        primary = _run_cli(PRIMARY_BIN, "--help")
        legacy = _run_cli(LEGACY_BIN, "--help")
        self.assertEqual(primary.returncode, 0, primary.stderr)
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertIn("usage:", primary.stdout.lower())
        self.assertEqual(primary.stdout, legacy.stdout)


if __name__ == "__main__":
    unittest.main()
