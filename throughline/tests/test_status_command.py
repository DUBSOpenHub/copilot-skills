"""Regression tests for the top-level `status` subcommand
(`engine/cli.py`'s `build_parser`/`cmd_bare_default_workspace`;
docs/engine-cli-reference.md): a discoverable, explicitly-named
compatibility alias for the bare no-subcommand form
(`tests/test_bare_default_workspace.py`) -- `bin/throughline status`
opens/resumes the single default talk workspace and reports its identity,
for callers that specifically probe for a `status` verb rather than
omitting the subcommand entirely.

Compatibility gap this closes: `bin/throughline status` previously failed
argparse's own choice validation (`invalid choice: 'status'`, exit 2)
because no such top-level subcommand was registered.

Contract: `status` returns exactly the shape `workspace show`'s active
branch and the bare form return, including the additive top-level
`workspace_id` identity field (`engine/cli.py`'s `_identity_fields`); a
first `status` call (no workspace yet) opens the default workspace, and
every later `status` call (or bare invocation) against the same resolved
workspace root resumes -- never recreates -- that same identity.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

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


def _status(root, binary=PRIMARY_BIN, timeout=60):
    return _run_cli(binary, "--workspace-root", str(root), "status", timeout=timeout)


def _bare(root, binary=PRIMARY_BIN, timeout=60):
    return _run_cli(binary, "--workspace-root", str(root), timeout=timeout)


class StatusCommandIsRecognizedTests(unittest.TestCase):
    """The exact black-box-reported defect: `status` must parse as a
    valid top-level subcommand and exit 0, never argparse's `invalid
    choice` (exit 2)."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_status_exits_zero_with_no_prior_workspace(self):
        proc = _status(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stdout)
        self.assertNotIn("invalid choice", proc.stderr)

    def test_status_opens_the_default_workspace_when_none_is_active(self):
        proc = _status(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        data = envelope["data"]
        self.assertTrue(data["active"])
        self.assertTrue(data["workspace"]["id"].startswith("workspace:"))
        self.assertEqual(data["brief"]["id"], data["workspace"]["brief_id"])
        self.assertIn("nextAction", data)

    def test_status_reports_a_top_level_snake_case_workspace_id(self):
        """Preserve the additive top-level identity-field contract
        (`_identity_fields`) exactly as every other identity-bearing
        command already does -- the nested envelope is unchanged."""
        proc = _status(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertIn("workspace_id", envelope)
        self.assertEqual(envelope["workspace_id"], envelope["data"]["workspace"]["id"])


class StatusBeforeAndAfterBareInvocationTests(unittest.TestCase):
    """`status` and the bare no-subcommand form must converge on, and
    resume, the identical workspace identity regardless of call order --
    proving `status` is a true alias, not a parallel implementation."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_status_before_any_bare_invocation_then_bare_invocation_resumes_it(self):
        before = _status(self.root)
        self.assertEqual(before.returncode, 0, before.stderr)
        before_id = json.loads(before.stdout)["data"]["workspace"]["id"]

        after_bare = _bare(self.root)
        self.assertEqual(after_bare.returncode, 0, after_bare.stderr)
        self.assertEqual(json.loads(after_bare.stdout)["data"]["workspace"]["id"], before_id)

    def test_bare_invocation_first_then_status_resumes_the_same_identity(self):
        first_bare = _bare(self.root)
        self.assertEqual(first_bare.returncode, 0, first_bare.stderr)
        bare_id = json.loads(first_bare.stdout)["data"]["workspace"]["id"]

        status_after = _status(self.root)
        self.assertEqual(status_after.returncode, 0, status_after.stderr)
        self.assertEqual(json.loads(status_after.stdout)["data"]["workspace"]["id"], bare_id)

    def test_repeated_status_calls_never_create_a_second_workspace(self):
        first = _status(self.root)
        second = _status(self.root)
        third = _status(self.root)
        ids = {json.loads(p.stdout)["data"]["workspace"]["id"] for p in (first, second, third)}
        self.assertEqual(len(ids), 1)

    def test_status_identity_matches_workspace_show_and_the_bare_form(self):
        status_proc = _status(self.root)
        self.assertEqual(status_proc.returncode, 0, status_proc.stderr)
        status_data = json.loads(status_proc.stdout)["data"]

        shown = _run_cli(PRIMARY_BIN, "--workspace-root", str(self.root), "workspace", "show")
        shown_data = json.loads(shown.stdout)["data"]

        bare = _bare(self.root)
        bare_data = json.loads(bare.stdout)["data"]

        self.assertEqual(status_data["workspace"], shown_data["workspace"])
        self.assertEqual(status_data["workspace"], bare_data["workspace"])
        self.assertEqual(status_data["brief"], shown_data["brief"])
        self.assertEqual(status_data["nextAction"], shown_data["nextAction"])


class StatusEntryPointAndPrecedenceParityTests(unittest.TestCase):
    """`status` behaves identically through `bin/throughline` and the
    legacy `bin/throughline-engine` alias, and honors the same
    default-root precedence as every other command -- not a special case."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_both_entry_points_agree_on_status(self):
        primary = _status(self.root / "primary-root", binary=PRIMARY_BIN)
        legacy = _status(self.root / "legacy-root", binary=LEGACY_BIN)
        self.assertEqual(primary.returncode, 0, primary.stderr)
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertTrue(json.loads(primary.stdout)["data"]["active"])
        self.assertTrue(json.loads(legacy.stdout)["data"]["active"])

    def test_status_honors_throughline_home_env_var(self):
        resolved_root = self.root / "env-workspace-root"
        proc = _run_cli(
            PRIMARY_BIN, "status", env=_clean_env(THROUGHLINE_HOME=str(resolved_root)),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["data"]["active"])
        self.assertTrue((resolved_root / "workspace").is_dir())

    def test_status_still_appears_in_help_usage(self):
        proc = _run_cli(PRIMARY_BIN, "--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("status", proc.stdout)


class StatusExplicitWorkspaceFlagTests(unittest.TestCase):
    """`bin/throughline status --workspace <dir>` (ARCH §11): an
    explicit-target alias for the global `--workspace-root`, registered
    directly on the `status` subparser so it may follow the `status`
    token itself -- exactly like `run-scenario`'s own identically-named
    flag. Previously `--workspace` was unrecognized by `status` (argparse
    exit 2, "unrecognized arguments"); `status` only advertised
    `--workspace-root`.

    Contract: identical handler/shape/identity to every other `status`
    invocation form (`_bare`/`_status` above) -- `--workspace` only
    changes *which* directory is resolved as the workspace root, never
    the response shape or resume semantics."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _status_with_workspace(self, workspace_dir, binary=PRIMARY_BIN, timeout=60):
        return _run_cli(binary, "status", "--workspace", str(workspace_dir), timeout=timeout)

    def test_status_workspace_flag_is_recognized_and_exits_zero(self):
        proc = self._status_with_workspace(self.root / "explicit-workspace")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("unrecognized arguments", proc.stderr)
        self.assertNotIn("Traceback", proc.stdout)

    def test_status_workspace_flag_opens_the_default_workspace_at_that_directory(self):
        workspace_dir = self.root / "explicit-workspace"
        proc = self._status_with_workspace(workspace_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        data = envelope["data"]
        self.assertTrue(data["active"])
        self.assertTrue(data["workspace"]["id"].startswith("workspace:"))
        self.assertIn("workspace_id", envelope)
        self.assertEqual(envelope["workspace_id"], data["workspace"]["id"])
        # The named directory itself becomes the workspace root.
        self.assertTrue((workspace_dir / "workspace").is_dir())

    def test_status_workspace_flag_isolates_independent_directories(self):
        proc_a = self._status_with_workspace(self.root / "workspace-a")
        proc_b = self._status_with_workspace(self.root / "workspace-b")
        id_a = json.loads(proc_a.stdout)["data"]["workspace"]["id"]
        id_b = json.loads(proc_b.stdout)["data"]["workspace"]["id"]
        self.assertNotEqual(id_a, id_b)

    def test_repeated_status_workspace_calls_resume_the_same_identity(self):
        workspace_dir = self.root / "explicit-workspace"
        first = self._status_with_workspace(workspace_dir)
        second = self._status_with_workspace(workspace_dir)
        third = self._status_with_workspace(workspace_dir)
        ids = {json.loads(p.stdout)["data"]["workspace"]["id"] for p in (first, second, third)}
        self.assertEqual(len(ids), 1)

    def test_status_workspace_flag_takes_precedence_over_global_workspace_root(self):
        """Mirrors `run-scenario`'s own `--workspace` precedence over the
        global `--workspace-root` (docs/engine-cli-reference.md)."""
        losing_root = self.root / "losing-workspace-root"
        winning_workspace = self.root / "winning-workspace"
        proc = _run_cli(
            PRIMARY_BIN, "--workspace-root", str(losing_root), "status", "--workspace", str(winning_workspace),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((winning_workspace / "workspace").is_dir())
        self.assertFalse(losing_root.exists())

    def test_status_workspace_flag_identity_matches_a_workspace_root_equivalent_bare_invocation(self):
        """`status --workspace <dir>` and a bare invocation resolved via
        `--workspace-root <dir>` against the identical directory converge
        on the same identity -- `--workspace` is an alias, not a second
        resolution rule."""
        shared_dir = self.root / "shared-target"
        via_workspace_flag = self._status_with_workspace(shared_dir)
        self.assertEqual(via_workspace_flag.returncode, 0, via_workspace_flag.stderr)
        flag_id = json.loads(via_workspace_flag.stdout)["data"]["workspace"]["id"]

        via_workspace_root = _run_cli(PRIMARY_BIN, "--workspace-root", str(shared_dir), "status")
        self.assertEqual(via_workspace_root.returncode, 0, via_workspace_root.stderr)
        root_id = json.loads(via_workspace_root.stdout)["data"]["workspace"]["id"]

        self.assertEqual(flag_id, root_id)

    def test_status_workspace_flag_behaves_identically_through_the_legacy_entry_point(self):
        primary = self._status_with_workspace(self.root / "primary-target", binary=PRIMARY_BIN)
        legacy = self._status_with_workspace(self.root / "legacy-target", binary=LEGACY_BIN)
        self.assertEqual(primary.returncode, 0, primary.stderr)
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertTrue(json.loads(primary.stdout)["data"]["active"])
        self.assertTrue(json.loads(legacy.stdout)["data"]["active"])

    def test_status_help_advertises_the_workspace_flag(self):
        proc = _run_cli(PRIMARY_BIN, "status", "--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--workspace", proc.stdout)


if __name__ == "__main__":
    unittest.main()
