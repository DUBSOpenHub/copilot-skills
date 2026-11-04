#!/usr/bin/env python3
"""Standard-library self-tests; all fixtures stay beneath the skill directory."""

import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "scripts" / "pass-ledger.sh"


class PassLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if Path.cwd().resolve() != ROOT:
            raise RuntimeError("Run self-tests from the skill directory.")
        cls.fixture = Path(f".ledger-selftest-{os.getpid()}")
        cls.fixture.mkdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fixture)

    def setUp(self):
        self.home = self.fixture / self._testMethodName
        self.home.mkdir()
        self.state = self.home / "state with spaces"

    def run_ledger(self, *args, expected=0):
        result = subprocess.run(
            ["bash", str(LEDGER), str(self.state), *args],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout.strip()

    def initialize(self):
        self.run_ledger("init")

    def test_resume_keeps_counter_and_requires_closing_interrupted_pass(self):
        self.initialize()
        self.assertEqual(self.run_ledger("reserve", "work", "S01"), "01")
        self.run_ledger("reserve", "work", "S02", expected=3)
        self.run_ledger("init")
        self.assertIn("used=1", self.run_ledger("status"))
        self.run_ledger("close", "01", "interrupted")
        self.assertEqual(self.run_ledger("reserve", "work", "S01"), "02")

    def test_hard_cap_includes_final_failed_blocked_and_interrupted_passes(self):
        self.initialize()
        outcomes = ("passed", "failed", "blocked", "interrupted")
        for number in range(1, 21):
            mode = "final" if number % 2 == 0 else "work"
            target = "ALL" if mode == "final" else "S01"
            identifier = f"{number:02d}"
            self.assertEqual(self.run_ledger("reserve", mode, target), identifier)
            if number == 20:
                self.run_ledger("reserve", "work", "S01", expected=2)
            outcome = "passed" if number == 20 else outcomes[(number - 1) % 4]
            self.run_ledger("close", identifier, outcome)
        self.run_ledger("reserve", "work", "S01", expected=2)
        self.run_ledger("init")
        self.assertEqual(
            self.run_ledger("status"), "used=20 limit=20 remaining=0 open=none"
        )
        self.assertFalse((self.state / "passes" / "21").exists())

    def test_partial_reservation_is_spent_and_cannot_claim_passing(self):
        self.initialize()
        (self.state / "passes" / "01").mkdir()
        self.assertIn("used=1", self.run_ledger("status"))
        self.run_ledger("reserve", "work", "S01", expected=3)
        self.run_ledger("close", "01", "passed", expected=5)
        self.run_ledger("close", "01", "interrupted")
        self.assertEqual(self.run_ledger("reserve", "final", "ALL"), "02")

    def test_invalid_commands_do_not_allocate_and_closed_result_is_immutable(self):
        self.initialize()
        self.run_ledger("reserve", "other", "S01", expected=64)
        self.run_ledger("reserve", "final", "S01", expected=64)
        self.run_ledger("reserve", "work", "../outside", expected=64)
        self.assertIn("used=0", self.run_ledger("status"))
        self.run_ledger("reserve", "final", "ALL")
        self.run_ledger("close", "01", "complete", expected=64)
        self.run_ledger("close", "01", "failed")
        self.run_ledger("close", "01", "passed", expected=3)
        self.assertEqual(
            (self.state / "passes" / "01" / "result").read_text(), "failed\n"
        )

    def test_concurrent_reservations_cannot_open_two_passes(self):
        self.initialize()
        command = ["bash", str(LEDGER), str(self.state), "reserve", "work", "S01"]
        first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        second = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        first_output = first.communicate(timeout=10)
        second_output = second.communicate(timeout=10)
        codes = sorted((first.returncode, second.returncode))
        self.assertEqual(codes[0], 0, (first_output, second_output))
        self.assertIn(codes[1], (3, 4), (first_output, second_output))
        self.assertEqual(
            self.run_ledger("status"), "used=1 limit=20 remaining=19 open=01"
        )

    def test_existing_lock_is_never_stolen(self):
        self.initialize()
        lock = self.state / ".lock"
        lock.mkdir()
        (lock / "owner").write_text("pid=unknown\nhost=unknown\n")
        self.run_ledger("reserve", "work", "S01", expected=4)
        self.assertTrue((lock / "owner").exists())
        self.assertIn("used=0", self.run_ledger("status"))

    def test_refuses_unrecognized_state_unknown_format_and_gapped_ledger(self):
        self.state.mkdir()
        unrelated = self.state / "keep.txt"
        unrelated.write_text("unrelated\n")
        self.run_ledger("init", expected=5)
        self.assertEqual(unrelated.read_text(), "unrelated\n")
        unrelated.unlink()
        self.initialize()
        (self.state / "format").write_text("unknown\n")
        self.run_ledger("init", expected=5)
        (self.state / "format").write_text("ralph-loop-pass-ledger-v1\n")
        (self.state / "passes" / "02").mkdir()
        self.run_ledger("status", expected=5)
        self.run_ledger("reserve", "work", "S01", expected=5)

    def test_refuses_symlinked_state_and_checkpoint_outputs(self):
        real = self.home / "real"
        real.mkdir()
        self.state.symlink_to("real", target_is_directory=True)
        self.run_ledger("init", expected=5)
        self.state.unlink()
        self.initialize()
        self.run_ledger("reserve", "work", "S01")
        target = self.home / "untouched"
        target.write_text("keep\n")
        output = self.state / "passes" / "01" / "result.new"
        output.symlink_to(target.resolve())
        self.run_ledger("close", "01", "passed", expected=5)
        self.assertEqual(target.read_text(), "keep\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
