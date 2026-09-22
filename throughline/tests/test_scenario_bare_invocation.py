"""Regression tests for the bare `run-scenario` invocation form: `throughline
run-scenario --scenario <path>` with **no** `--workspace`, `--export-dir`, or
`--out`. This is a third, fully supported invocation form alongside the
legacy `--out` and public `--workspace [--export-dir]` forms (ARCH §4,
§11; docs/engine-cli-reference.md) — it is not a special case, it simply
lets the same workspace-root default-precedence chain every other command
already honors (`--workspace-root` / `THROUGHLINE_WORKSPACE_ROOT` /
`THROUGHLINE_HOME` / `~/.copilot/throughline`) apply with no scenario-
specific flag at all, and writes `run-report.json` at that same resolved
root — a deterministic, discoverable location.

Every subprocess test here scrubs `THROUGHLINE_WORKSPACE_ROOT` and
`THROUGHLINE_HOME` from the inherited environment before setting exactly
the ones under test, so behavior is never accidentally influenced by (or
leaks into) the real `~/.copilot/throughline` or another test's env.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO_ROOT, cleanup, new_root, persistence

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"
BIN = str(REPO_ROOT / "bin" / "throughline-engine")
_SCRUBBED_VARS = ("THROUGHLINE_WORKSPACE_ROOT", "THROUGHLINE_HOME")


def _clean_env(**overrides: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_VARS}
    env.update(overrides)
    return env


def _run_cli(*args, env=None, timeout=120):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout, env=env)


class BareInvocationSubprocessTests(unittest.TestCase):
    """End-to-end (subprocess) coverage: the exact black-box invocation
    pattern named in the compatibility gap — `run-scenario --scenario
    <path>` alone — must succeed, not require `--workspace`/`--out`."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_bare_invocation_with_workspace_root_env_var_succeeds_and_writes_report_at_that_root(self):
        resolved_root = self.root / "env-workspace-root"
        proc = _run_cli(
            "run-scenario", "--scenario", str(FIXTURE),
            env=_clean_env(THROUGHLINE_WORKSPACE_ROOT=str(resolved_root)),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"])
        self.assertIsNone(envelope["data"]["refusal"])
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertIn("package", envelope["data"])

        # Deterministic report location: exactly the resolved root, with
        # no scenario-specific flag telling it where to go.
        report_path = resolved_root / "run-report.json"
        self.assertTrue(report_path.exists())
        on_disk = json.loads(report_path.read_text())
        self.assertEqual(on_disk["workspaceId"], envelope["data"]["workspaceId"])
        self.assertTrue((resolved_root / "workspace").is_dir())

    def test_bare_invocation_honors_throughline_home_when_workspace_root_env_var_is_unset(self):
        """The new `THROUGHLINE_HOME` environment variable is honored by
        the bare form exactly like `THROUGHLINE_WORKSPACE_ROOT` is."""
        resolved_root = self.root / "env-home-root"
        proc = _run_cli(
            "run-scenario", "--scenario", str(FIXTURE),
            env=_clean_env(THROUGHLINE_HOME=str(resolved_root)),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"])
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertTrue((resolved_root / "run-report.json").exists())

    def test_throughline_workspace_root_env_var_still_takes_precedence_over_throughline_home(self):
        """Backward compatibility: when both env vars are set, the
        already-documented `THROUGHLINE_WORKSPACE_ROOT` wins, so existing
        deployments that already export it are unaffected by the new
        `THROUGHLINE_HOME` fallback."""
        winning_root = self.root / "winning-root"
        losing_root = self.root / "losing-root"
        proc = _run_cli(
            "run-scenario", "--scenario", str(FIXTURE),
            env=_clean_env(THROUGHLINE_WORKSPACE_ROOT=str(winning_root), THROUGHLINE_HOME=str(losing_root)),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((winning_root / "run-report.json").exists())
        self.assertFalse(losing_root.exists())

    def test_export_dir_still_applies_on_top_of_a_bare_invocation(self):
        resolved_root = self.root / "env-workspace-root"
        export_dir = self.root / "export-dir"
        proc = _run_cli(
            "run-scenario", "--scenario", str(FIXTURE), "--export-dir", str(export_dir),
            env=_clean_env(THROUGHLINE_WORKSPACE_ROOT=str(resolved_root)),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(Path(envelope["data"]["package"]["exportDir"]), export_dir)
        self.assertTrue((export_dir / "deck.pptx").exists())
        # Report still lands at the resolved root, not the export dir.
        self.assertTrue((resolved_root / "run-report.json").exists())

    def test_a_second_bare_invocation_against_the_same_resolved_root_resumes_it(self):
        """The bare form resolves its workspace root exactly like the
        explicit `--workspace` form (ARCH §12; docs/engine-cli-reference.md)
        -- it is the same code path, not a parallel implementation -- so a
        second bare invocation against the identical resolved root
        idempotently resumes that same workspace rather than being refused
        `WORKSPACE_ALREADY_ACTIVE`."""
        resolved_root = self.root / "shared-root"
        env = _clean_env(THROUGHLINE_WORKSPACE_ROOT=str(resolved_root))

        first = _run_cli("run-scenario", "--scenario", str(FIXTURE), env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_envelope = json.loads(first.stdout)
        self.assertTrue(first_envelope["data"]["ok"])

        second = _run_cli("run-scenario", "--scenario", str(FIXTURE), env=env)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("Traceback", second.stdout)
        second_envelope = json.loads(second.stdout)
        self.assertTrue(second_envelope["ok"], second_envelope.get("error"))
        self.assertTrue(second_envelope["data"]["ok"])
        self.assertIsNone(second_envelope["data"]["refusal"])
        self.assertTrue(second_envelope["data"]["workspaceResumed"])
        self.assertEqual(second_envelope["data"]["workspaceId"], first_envelope["data"]["workspaceId"])

        on_disk = json.loads((resolved_root / "run-report.json").read_text())
        self.assertEqual(on_disk["workspaceId"], first_envelope["data"]["workspaceId"])


    def test_explicit_workspace_flag_still_takes_precedence_over_a_bare_default(self):
        """`--workspace` remains the strongest signal even when env vars
        that would otherwise drive a bare invocation are also set."""
        env_root = self.root / "env-root-unused"
        explicit_workspace = self.root / "explicit-workspace"
        proc = _run_cli(
            "run-scenario", "--scenario", str(FIXTURE), "--workspace", str(explicit_workspace),
            env=_clean_env(THROUGHLINE_WORKSPACE_ROOT=str(env_root)),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((explicit_workspace / "run-report.json").exists())
        self.assertFalse(env_root.exists())


class DefaultRootPrecedenceUnitTests(unittest.TestCase):
    """Direct, in-process unit coverage of `persistence.default_root`'s
    precedence chain — fast, and pins the exact ordering contract the
    subprocess tests above exercise end-to-end."""

    def setUp(self):
        self._previous = {k: os.environ.get(k) for k in _SCRUBBED_VARS}
        for k in _SCRUBBED_VARS:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_neither_env_var_set_falls_back_to_the_documented_default(self):
        self.assertEqual(persistence.default_root(), Path.home() / ".copilot" / "throughline")

    def test_throughline_home_alone_is_honored(self):
        os.environ["THROUGHLINE_HOME"] = "/example/home-root"
        self.assertEqual(persistence.default_root(), Path("/example/home-root"))

    def test_throughline_workspace_root_wins_over_throughline_home_when_both_set(self):
        os.environ["THROUGHLINE_HOME"] = "/example/home-root"
        os.environ["THROUGHLINE_WORKSPACE_ROOT"] = "/example/workspace-root"
        self.assertEqual(persistence.default_root(), Path("/example/workspace-root"))

    def test_explicit_constructor_argument_still_wins_over_both_env_vars(self):
        os.environ["THROUGHLINE_HOME"] = "/example/home-root"
        os.environ["THROUGHLINE_WORKSPACE_ROOT"] = "/example/workspace-root"
        explicit_root = new_root()
        try:
            store = persistence.Store(root=explicit_root)
            self.assertEqual(store.root, explicit_root)
        finally:
            cleanup(explicit_root)


if __name__ == "__main__":
    unittest.main()
