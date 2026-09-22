"""Regression tests for the public CLI discovery contract: a black-box
caller must be able to discover an executable at one of the conventional
repository entry points (this project ships `bin/throughline`) and drive
it identically to `bin/throughline-engine`, the retained backward-
compatible alias. Both are thin wrappers around the identical
`engine.cli.main` (ARCH §3, §4), so every assertion here about
`bin/throughline` has a mirrored assertion proving `bin/throughline-engine`
still behaves the same way.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO_ROOT, cleanup, new_root

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"
PRIMARY_BIN = REPO_ROOT / "bin" / "throughline"
LEGACY_BIN = REPO_ROOT / "bin" / "throughline-engine"


class ConventionalEntryPointExistsTests(unittest.TestCase):
    """S1 (public interface discovery): a black-box harness scans for an
    executable named `throughline`/`bin/throughline`/etc. before it ever
    runs a behavioral scenario. This must be satisfiable with no special
    knowledge of `throughline-engine`."""

    def test_bin_throughline_exists_as_a_regular_file(self):
        self.assertTrue(PRIMARY_BIN.is_file(), f"expected {PRIMARY_BIN} to exist")

    def test_bin_throughline_is_directly_executable(self):
        self.assertTrue(os.access(PRIMARY_BIN, os.X_OK), f"expected {PRIMARY_BIN} to be executable")

    def test_bin_throughline_has_a_python_shebang(self):
        first_line = PRIMARY_BIN.read_text().splitlines()[0]
        self.assertTrue(first_line.startswith("#!"), "expected an executable shebang line")
        self.assertIn("python3", first_line)

    def test_legacy_bin_throughline_engine_remains_executable(self):
        """Backward compatibility: the pre-existing entry point must keep
        working exactly as before — this cycle is additive, never a
        rename or removal."""
        self.assertTrue(LEGACY_BIN.is_file())
        self.assertTrue(os.access(LEGACY_BIN, os.X_OK))


class ConventionalEntryPointHelpTests(unittest.TestCase):
    """`--help` must succeed with no crash, invoked either directly (the
    way a black-box harness discovers and probes an executable) or via
    the interpreter (matching this suite's existing CLI-test style)."""

    def test_direct_invocation_of_bin_throughline_returns_help_and_exits_zero(self):
        proc = subprocess.run([str(PRIMARY_BIN), "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stdout)
        self.assertIn("usage:", proc.stdout.lower())

    def test_direct_invocation_of_legacy_bin_throughline_engine_still_returns_help(self):
        proc = subprocess.run([str(LEGACY_BIN), "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stdout)
        self.assertIn("usage:", proc.stdout.lower())

    def test_bin_throughline_help_via_interpreter_matches_test_cli_conventions(self):
        proc = subprocess.run([sys.executable, str(PRIMARY_BIN), "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stdout)

    def test_both_entry_points_produce_identical_help_text(self):
        """Both are thin wrappers around the same `engine.cli.main` — the
        help banner they produce must be byte-identical, proving neither
        is a diverging or stale copy of the other."""
        new_proc = subprocess.run([str(PRIMARY_BIN), "--help"], capture_output=True, text=True, timeout=30)
        legacy_proc = subprocess.run([str(LEGACY_BIN), "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(new_proc.stdout, legacy_proc.stdout)


class ConventionalEntryPointScenarioParityTests(unittest.TestCase):
    """The flagship black-box path — `run-scenario` — must behave
    identically through `bin/throughline` and `bin/throughline-engine`:
    same success/refusal outcome, same gate results, same package
    artifacts. Proves the new entry point invokes real production code,
    not a stub."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _run(self, binary: Path, workspace_dir: Path):
        return subprocess.run(
            [str(binary), "run-scenario", "--scenario", str(FIXTURE), "--workspace", str(workspace_dir)],
            capture_output=True, text=True, timeout=120,
        )

    def test_bin_throughline_runs_the_full_scenario_successfully(self):
        proc = self._run(PRIMARY_BIN, self.root / "primary-workspace")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"])
        self.assertIsNone(envelope["data"]["refusal"])
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertIn("package", envelope["data"])

    def test_bin_throughline_and_legacy_engine_agree_on_scenario_outcome(self):
        primary_proc = self._run(PRIMARY_BIN, self.root / "primary-workspace")
        legacy_proc = self._run(LEGACY_BIN, self.root / "legacy-workspace")

        self.assertEqual(primary_proc.returncode, legacy_proc.returncode)
        primary_envelope = json.loads(primary_proc.stdout)
        legacy_envelope = json.loads(legacy_proc.stdout)

        self.assertEqual(primary_envelope["ok"], legacy_envelope["ok"])
        self.assertEqual(primary_envelope["data"]["ok"], legacy_envelope["data"]["ok"])
        self.assertEqual(primary_envelope["data"]["refusal"], legacy_envelope["data"]["refusal"])
        self.assertEqual(primary_envelope["data"]["stageGate"]["passed"], legacy_envelope["data"]["stageGate"]["passed"])
        self.assertEqual(
            set(primary_envelope["data"]["package"]["artifactKinds"]),
            set(legacy_envelope["data"]["package"]["artifactKinds"]),
        )

        primary_export = Path(primary_envelope["data"]["package"]["exportDir"])
        legacy_export = Path(legacy_envelope["data"]["package"]["exportDir"])
        self.assertTrue((primary_export / "deck.pptx").exists())
        self.assertTrue((legacy_export / "deck.pptx").exists())

    def test_repeated_invocation_semantics_are_identical_through_bin_throughline(self):
        """The "a later call against the same explicit workspace resumes
        it" contract (`scenario.run_scenario`'s own contract) must hold
        through the new entry point exactly as it does through the legacy
        one — this cycle must not weaken it."""
        workspace_dir = self.root / "shared-workspace"
        first = self._run(PRIMARY_BIN, workspace_dir)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_envelope = json.loads(first.stdout)
        self.assertTrue(first_envelope["data"]["ok"])

        second = self._run(PRIMARY_BIN, workspace_dir)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("Traceback", second.stdout)
        second_envelope = json.loads(second.stdout)
        self.assertTrue(second_envelope["ok"], second_envelope.get("error"))
        self.assertTrue(second_envelope["data"]["ok"])
        self.assertIsNone(second_envelope["data"]["refusal"])
        self.assertTrue(second_envelope["data"]["workspaceResumed"])
        self.assertEqual(second_envelope["data"]["workspaceId"], first_envelope["data"]["workspaceId"])


class InstallAndCatalogConsistencyTests(unittest.TestCase):
    """`bin/throughline` must be installable by `install.sh` and declared
    in `catalog.yml`'s engine surface — not just present in the source
    tree."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_install_sh_copies_and_chmods_bin_throughline(self):
        target = self.root / "installed-skill"
        env = dict(os.environ)
        env["THROUGHLINE_SKILL_HOME"] = str(target)
        proc = subprocess.run(
            ["bash", str(REPO_ROOT / "install.sh")], capture_output=True, text=True, timeout=60, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        installed_primary = target / "bin" / "throughline"
        installed_legacy = target / "bin" / "throughline-engine"
        self.assertTrue(installed_primary.is_file())
        self.assertTrue(os.access(installed_primary, os.X_OK))
        self.assertTrue(installed_legacy.is_file())
        self.assertTrue(os.access(installed_legacy, os.X_OK))

        help_proc = subprocess.run([str(installed_primary), "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(help_proc.returncode, 0, help_proc.stderr)

    def test_catalog_yml_declares_bin_throughline_as_an_engine_surface(self):
        catalog_text = (REPO_ROOT / "catalog.yml").read_text()
        self.assertIn("- bin/throughline\n", catalog_text)
        self.assertIn("- bin/throughline-engine\n", catalog_text)


if __name__ == "__main__":
    unittest.main()
