#!/usr/bin/env python3
"""Looper standard-library self-tests; fixtures stay beneath this skill directory."""

import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "scripts" / "pass-ledger.sh"


class PassLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if Path.cwd().resolve() != ROOT:
            raise RuntimeError("Run self-tests from the looper skill directory.")
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
            ["/bin/bash", str(LEDGER), str(self.state), *args],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout.strip()

    def initialize(self):
        self.run_ledger("init")

    def new_case(self, name, reserve=True):
        self.state = self.home / name
        self.initialize()
        if reserve:
            self.run_ledger("reserve", "work", "S01")
        return self.state / "passes" / "01"

    def fault(self, tool, body, *args, expected=1):
        """A fixture-local command fault; the product has no injection interface."""
        directory = self.home / f"fault-{tool}"
        directory.mkdir()
        command = directory / tool
        command.write_text("#!/bin/bash\n" + body + "\n")
        command.chmod(0o700)
        env = {
            "PATH": str(directory.resolve()) + os.pathsep + os.environ["PATH"],
            "LEDGER_TEST_STATE": str(self.state.resolve()),
            "LEDGER_TEST_COUNTER": str((directory / "counter").resolve()),
        }
        try:
            with patch.dict(os.environ, env):
                return self.run_ledger(*args, expected=expected)
        finally:
            shutil.rmtree(directory)

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

    def test_exact_stdout_idempotence_and_existing_target_syntax(self):
        self.assertEqual(self.run_ledger("init"), "used=0 limit=20 remaining=20 open=none")
        for number, target in enumerate(("a", "9._-step", "ALL"), 1):
            identifier = f"{number:02d}"
            self.assertEqual(self.run_ledger("reserve", "work", target), identifier)
            self.assertEqual(
                self.run_ledger("init"),
                f"used={number} limit=20 remaining={20-number} open={identifier}",
            )
            self.assertEqual(
                self.run_ledger("close", identifier, "passed"),
                f"closed={identifier} outcome=passed",
            )
        self.assertEqual(self.run_ledger("reserve", "final", "ALL"), "04")

    def test_malformed_published_reservations_block_without_rewriting(self):
        for index, change in enumerate((
            lambda text: text.replace("mode=work", "mode=other"),
            lambda text: text.replace("mode=work", "mode=final"),
            lambda text: text.replace("target=S01", "target=../escape"),
            lambda text: text.replace("target=S01", "target="),
            lambda text: text.replace("started=", "unknown="),
            lambda text: text.split("started=")[0] + "started=\n",
            lambda text: text + "target=S02\n",
            lambda text: text.rstrip("\n"),
            lambda text: text.replace("mode=work", "mode=wo\x00rk"),
        )):
            with self.subTest(index=index):
                record = self.new_case(f"record-{index}") / "reservation"
                record.write_text(change(record.read_text()))
                before = record.read_bytes()
                self.run_ledger("status", expected=5)
                self.run_ledger("close", "01", "interrupted", expected=5)
                self.assertEqual(record.read_bytes(), before)
                self.assertFalse((record.parent / "result").exists())

    def test_missing_metadata_cannot_legitimize_noninterrupted_result(self):
        for outcome in ("passed", "failed", "blocked", "interrupted"):
            with self.subTest(outcome=outcome):
                directory = self.new_case(outcome)
                self.run_ledger("close", "01", outcome)
                (directory / "reservation").unlink()
                if outcome == "interrupted":
                    self.assertEqual(
                        self.run_ledger("status"),
                        "used=1 limit=20 remaining=19 open=none",
                    )
                    self.assertEqual(self.run_ledger("reserve", "work", "S02"), "02")
                else:
                    self.run_ledger("status", expected=5)
                    self.run_ledger("reserve", "work", "S02", expected=5)
                self.assertEqual((directory / "result").read_text(), outcome + "\n")

    def test_malformed_results_and_impossible_order_block(self):
        for index, content in enumerate(("passed\n\n", "passed", "pa\x00ssed\n", "unknown\n")):
            with self.subTest(content=content):
                directory = self.new_case(f"result-{index}")
                self.run_ledger("close", "01", "passed")
                (directory / "result").write_text(content)
                self.run_ledger("status", expected=5)
                self.run_ledger("close", "01", "interrupted", expected=5)
                self.assertEqual((directory / "result").read_text(), content)
        first = self.new_case("order")
        self.run_ledger("close", "01", "passed")
        self.run_ledger("reserve", "work", "S02")
        self.run_ledger("close", "02", "failed")
        (first / "result").unlink()
        self.run_ledger("status", expected=5)
        self.run_ledger("close", "01", "interrupted", expected=5)
        (first.parent / "02" / "result").unlink()
        self.run_ledger("status", expected=5)

    def test_state_path_links_and_trailing_slash_aliases_are_rejected(self):
        self.initialize()
        original = self.state
        link = self.home / "linked-state"
        link.symlink_to(original.resolve(), target_is_directory=True)
        parent_link = self.home / "linked-parent"
        parent_link.symlink_to(self.home.resolve(), target_is_directory=True)
        aliases = (
            str(link) + "/",
            str(link) + "/.",
            str(parent_link / original.name),
            str(link) + "/../" + original.name,
            str(link.resolve().parent / "linked-state") + "/",
        )
        for alias in aliases:
            with self.subTest(alias=alias):
                self.state = alias
                self.run_ledger("init", expected=5)
                self.run_ledger("status", expected=5)
        self.state = str(original) + "/"
        self.assertEqual(self.run_ledger("init"), "used=0 limit=20 remaining=20 open=none")
        self.state = original.resolve()
        self.assertEqual(self.run_ledger("reserve", "work", "S01"), "01")

    def test_relative_state_path_ignores_cdpath_and_option_spelling(self):
        elsewhere = self.home / "elsewhere"
        (elsewhere / "-state").mkdir(parents=True)
        result = subprocess.run(
            ["/bin/bash", str(LEDGER), "-state", "init"],
            cwd=self.home,
            env=dict(os.environ, CDPATH=str(elsewhere.resolve())),
            text=True, capture_output=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "used=0 limit=20 remaining=20 open=none\n")
        self.assertEqual(list((elsewhere / "-state").iterdir()), [])
        self.state = self.home / "-state"
        self.assertEqual(self.run_ledger("reserve", "work", "S01"), "01")

    def test_helper_owned_file_types_are_rejected_without_touching_targets(self):
        sentinel = self.home / "sentinel"
        sentinel.write_text("keep\n")
        paths = ("format", "format.new", "passes/01/reservation",
                 "passes/01/reservation.new", "passes/01/result",
                 "passes/01/result.new", "passes/01/finished-at",
                 "passes/01/finished-at.new")
        for index, relative in enumerate(paths):
            for kind in ("symlink", "directory", "fifo"):
                with self.subTest(path=relative, kind=kind):
                    self.new_case(f"unsafe-{index}-{kind}")
                    destination = self.state / relative
                    if destination.exists():
                        destination.unlink()
                    if kind == "symlink":
                        destination.symlink_to(sentinel.resolve())
                    elif kind == "directory":
                        destination.mkdir()
                    else:
                        os.mkfifo(destination)
                    self.run_ledger("status", expected=5)
                    self.run_ledger("close", "01", "passed", expected=5)
                    self.assertEqual(sentinel.read_text(), "keep\n")

    def test_stale_candidates_are_preserved_not_clobbered(self):
        for name in ("result.new", "finished-at.new"):
            with self.subTest(name=name):
                directory = self.new_case(name)
                candidate = directory / name
                candidate.write_text("incomplete evidence\n")
                self.run_ledger("close", "01", "passed", expected=5)
                self.assertEqual(candidate.read_text(), "incomplete evidence\n")
                self.assertFalse((directory / "result").exists())
                self.assertEqual(
                    self.run_ledger("status"), "used=1 limit=20 remaining=19 open=01"
                )
                candidate.rename(directory / (name + ".retained"))
                self.run_ledger("close", "01", "interrupted")
        directory = self.new_case("partial")
        (directory / "reservation").rename(directory / "reservation.new")
        partial = (directory / "reservation.new").read_bytes()
        self.run_ledger("close", "01", "failed", expected=5)
        self.run_ledger("close", "01", "interrupted")
        self.assertEqual((directory / "reservation.new").read_bytes(), partial)
        self.assertEqual(self.run_ledger("reserve", "work", "S02"), "02")

    def test_hard_linked_timestamp_is_replaced_without_truncating_target(self):
        directory = self.new_case("hard-links")
        sentinel = self.home / "sentinel"
        sentinel.write_text("keep\n")
        os.link(sentinel, directory / "finished-at")
        os.link(sentinel, directory / "result.new")
        self.run_ledger("close", "01", "passed", expected=5)
        self.assertEqual(sentinel.read_text(), "keep\n")
        (directory / "result.new").rename(directory / "result.new.retained")
        self.run_ledger("close", "01", "passed")
        self.assertEqual(sentinel.read_text(), "keep\n")
        self.assertEqual((directory / "result.new.retained").read_text(), "keep\n")
        self.assertFalse(os.path.samefile(sentinel, directory / "finished-at"))

    def test_failed_initialization_is_not_silently_restarted(self):
        output = self.fault("mv", "exit 7", "init")
        self.assertEqual(output, "")
        self.assertFalse((self.state / "format").exists())
        staged = (self.state / "format.new").read_bytes()
        self.run_ledger("init", expected=5)
        self.run_ledger("status", expected=5)
        self.assertEqual((self.state / "format.new").read_bytes(), staged)
        self.assertTrue((self.state / "passes").is_dir())
        self.assertFalse((self.state / ".lock").exists())

    def test_failed_reservation_publication_spends_pass_and_retains_staging(self):
        self.initialize()
        output = self.fault("mv", "exit 7", "reserve", "work", "S01")
        self.assertEqual(output, "")
        directory = self.state / "passes" / "01"
        staged = (directory / "reservation.new").read_bytes()
        self.assertFalse((directory / "reservation").exists())
        self.assertEqual(self.run_ledger("status"), "used=1 limit=20 remaining=19 open=01")
        self.run_ledger("close", "01", "passed", expected=5)
        self.run_ledger("close", "01", "interrupted")
        self.assertEqual((directory / "reservation.new").read_bytes(), staged)
        self.assertEqual(self.run_ledger("reserve", "final", "ALL"), "02")

    def test_failed_timestamp_generation_never_publishes_partial_data(self):
        real_date = shutil.which("date")
        body = (
            'if [[ -e "$LEDGER_TEST_COUNTER" ]]; then printf partial; exit 7; fi\n'
            'printf first > "$LEDGER_TEST_COUNTER"\n'
            f'exec "{real_date}" "$@"'
        )
        for operation in ("reserve", "close"):
            with self.subTest(operation=operation):
                directory = self.new_case(operation, reserve=operation == "close")
                args = ("reserve", "work", "S01") if operation == "reserve" else ("close", "01", "passed")
                self.assertEqual(self.fault("date", body, *args), "")
                self.assertEqual(self.run_ledger("status"), "used=1 limit=20 remaining=19 open=01")
                self.assertFalse((directory / "result").exists())
                self.assertFalse((directory / "finished-at").exists())
                if operation == "reserve":
                    self.assertFalse((directory / "reservation").exists())
                self.run_ledger("close", "01", "interrupted")

    def test_failed_stage_write_keeps_partial_evidence_and_spent_reservation(self):
        self.initialize()
        environment = self.home / "write-fault.bash"
        environment.write_text(
            "printf() {\n"
            "  if [[ \"$1\" == 'mode=%s\\ntarget=%s\\nstarted=%s\\n' ]]; then\n"
            "    builtin printf 'mode=work\\npartial'; return 7\n"
            "  fi\n"
            "  builtin printf \"$@\"\n"
            "}\n"
        )
        with patch.dict(os.environ, {"BASH_ENV": str(environment.resolve())}):
            self.assertEqual(self.run_ledger("reserve", "work", "S01", expected=1), "")
        directory = self.state / "passes" / "01"
        self.assertEqual((directory / "reservation.new").read_text(), "mode=work\npartial")
        self.assertFalse((directory / "reservation").exists())
        self.assertEqual(self.run_ledger("status"), "used=1 limit=20 remaining=19 open=01")
        self.run_ledger("close", "01", "interrupted")
        self.assertEqual((directory / "reservation.new").read_text(), "mode=work\npartial")

    def test_close_publication_failures_preserve_open_or_immutable_result(self):
        real_mv = shutil.which("mv")
        for stage in ("finished-at.new", "result.new", "after-result"):
            with self.subTest(stage=stage):
                directory = self.new_case(stage)
                if stage == "after-result":
                    body = f'"{real_mv}" "$@" || exit $?\n[[ "$1" != */result.new ]] || exit 7'
                else:
                    body = f'[[ "$1" != */{stage} ]] || exit 7\nexec "{real_mv}" "$@"'
                self.assertEqual(self.fault("mv", body, "close", "01", "passed"), "")
                if stage == "after-result":
                    self.assertEqual((directory / "result").read_text(), "passed\n")
                    self.assertEqual(self.run_ledger("status"), "used=1 limit=20 remaining=19 open=none")
                    self.run_ledger("close", "01", "failed", expected=3)
                else:
                    self.assertFalse((directory / "result").exists())
                    self.assertEqual((directory / "result.new").read_text(), "passed\n")
                    self.assertEqual(self.run_ledger("status"), "used=1 limit=20 remaining=19 open=01")
                    self.run_ledger("close", "01", "passed", expected=5)
                self.assertFalse((self.state / ".lock").exists())

    def test_cleanup_failure_is_nonzero_after_publication_and_preserves_lock(self):
        real_mv = shutil.which("mv")
        for kind in ("foreign-owner", "foreign-content", "remove-failure"):
            with self.subTest(kind=kind):
                directory = self.new_case(kind)
                if kind == "remove-failure":
                    output = self.fault("rm", "exit 7", "close", "01", "passed")
                else:
                    target = "owner" if kind == "foreign-owner" else "foreign"
                    body = (
                        f'"{real_mv}" "$@" || exit $?\n'
                        'if [[ "$1" == */result.new ]]; then\n'
                        f'  printf foreign > "$LEDGER_TEST_STATE/.lock/{target}"\n'
                        'fi'
                    )
                    output = self.fault("mv", body, "close", "01", "passed")
                    self.assertEqual((self.state / ".lock" / target).read_text(), "foreign")
                self.assertEqual(output, "closed=01 outcome=passed")
                self.assertTrue((self.state / ".lock").is_dir())
                self.assertEqual((directory / "result").read_text(), "passed\n")
                self.assertEqual(self.run_ledger("status"), "used=1 limit=20 remaining=19 open=none")
                self.run_ledger("close", "01", "failed", expected=4)

    def test_cleanup_does_not_replace_original_failure_status(self):
        self.initialize()
        output = self.fault("rm", "exit 7", "reserve", "other", "S01", expected=64)
        self.assertEqual(output, "")
        self.assertTrue((self.state / ".lock" / "owner").is_file())
        self.assertEqual(self.run_ledger("status"), "used=0 limit=20 remaining=20 open=none")

    def test_catchable_signals_preserve_status_and_release_only_owned_lock(self):
        real_mv = shutil.which("mv")
        for signal, code in (("TERM", 143), ("HUP", 129), ("INT", 130)):
            for committed in (False, True):
                with self.subTest(signal=signal, committed=committed):
                    directory = self.new_case(f"{signal}-{committed}")
                    body = (
                        'if [[ "$1" == */result.new ]]; then\n'
                        + (f'  "{real_mv}" "$@" || exit $?\n' if committed else "")
                        + f'  kill -{signal} "$PPID"\n  exit 0\nfi\n'
                        + f'exec "{real_mv}" "$@"'
                    )
                    self.assertEqual(
                        self.fault("mv", body, "close", "01", "passed", expected=code), ""
                    )
                    self.assertFalse((self.state / ".lock").exists())
                    if committed:
                        self.assertEqual((directory / "result").read_text(), "passed\n")
                        self.run_ledger("close", "01", "failed", expected=3)
                    else:
                        self.assertFalse((directory / "result").exists())
                        (directory / "result.new").rename(directory / "result.new.retained")
                        self.run_ledger("close", "01", "interrupted")
                    self.assertEqual(self.run_ledger("reserve", "work", "S02"), "02")

    def test_uncatchable_termination_leaves_lock_and_spent_reservation(self):
        self.initialize()
        self.assertEqual(
            self.fault("mv", 'kill -KILL "$PPID"\nexit 0', "reserve", "work", "S01", expected=-9),
            "",
        )
        owner = self.state / ".lock" / "owner"
        record = owner.read_bytes()
        self.assertEqual(self.run_ledger("status"), "used=1 limit=20 remaining=19 open=01")
        self.run_ledger("reserve", "work", "S02", expected=4)
        self.assertEqual(owner.read_bytes(), record)


if __name__ == "__main__":
    unittest.main(verbosity=2)
