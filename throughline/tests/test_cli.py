"""CLI envelope contract: `bin/throughline-engine` always emits exactly
one JSON envelope, exit code matches `ok`, and stdout never contains a
bare stack trace."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import REPO_ROOT, cleanup, new_root

BIN = str(REPO_ROOT / "bin" / "throughline-engine")


def run_cli(root, *args, input_json=None):
    cmd = [sys.executable, BIN, "--workspace-root", str(root), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                           input=json.dumps(input_json) if input_json is not None else None)
    return proc


class CliEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_workspace_show_with_no_workspace_returns_ok_envelope(self):
        proc = run_cli(self.root, "workspace", "show")
        self.assertEqual(proc.returncode, 0)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"])
        self.assertFalse(envelope["data"]["active"])
        self.assertIsNone(envelope["error"])

    def test_workspace_new_then_show_round_trips(self):
        brief = {"audience": "Devs", "eventType": "meetup", "durationMinutes": 20, "takeaway": "T",
                  "proofPoints": [], "excludedTopics": [], "tone": "neutral"}
        proc = run_cli(self.root, "workspace", "new", "--actor", "CLI Test", input_json=brief)
        self.assertEqual(proc.returncode, 0)
        created = json.loads(proc.stdout)
        self.assertTrue(created["ok"])
        ws_id = created["data"]["workspace"]["id"]

        proc2 = run_cli(self.root, "workspace", "show")
        shown = json.loads(proc2.stdout)
        self.assertTrue(shown["ok"])
        self.assertEqual(shown["data"]["workspace"]["id"], ws_id)

    def test_error_envelope_shape_on_blocking_failure(self):
        brief = {"audience": "Devs", "eventType": "meetup", "durationMinutes": 20, "takeaway": "T",
                  "proofPoints": [], "excludedTopics": [], "tone": "neutral"}
        run_cli(self.root, "workspace", "new", "--actor", "CLI Test", input_json=brief)
        proc = run_cli(self.root, "workspace", "new", "--actor", "CLI Test", input_json=brief)
        self.assertEqual(proc.returncode, 1)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertIsNone(envelope["data"])
        self.assertEqual(envelope["error"]["code"], "WORKSPACE_ALREADY_ACTIVE")
        self.assertIn("message", envelope["error"])
        self.assertIn("details", envelope["error"])

    def test_stdout_never_contains_a_python_traceback(self):
        proc = run_cli(self.root, "claim", "approve", "claim:does-not-exist", "--actor", "T")
        self.assertNotIn("Traceback", proc.stdout)
        envelope = json.loads(proc.stdout)  # must still be valid, parseable JSON
        self.assertFalse(envelope["ok"])

    def test_no_active_workspace_error_for_commands_needing_one(self):
        proc = run_cli(self.root, "source", "list")
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "NO_ACTIVE_WORKSPACE")

    def test_help_exits_cleanly_without_crashing(self):
        proc = subprocess.run([sys.executable, BIN, "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("throughline-engine", proc.stdout)

    def test_internal_error_envelope_never_leaks_a_traceback_to_stdout(self):
        """cli.main()'s last-resort safety net (any *unexpected*, non-
        EngineError exception): still one clean JSON envelope on stdout,
        `INTERNAL_ERROR`, exit code 1 — the traceback goes to stderr only.
        Forced here with a `--workspace-root` that is a real file, not a
        directory, so `Store`'s `mkdir` raises a plain `NotADirectoryError`
        rather than any `EngineError`."""
        import io
        from engine import cli as cli_mod

        bad_root = REPO_ROOT / "README.md"  # a real file, not a directory
        old_stdout, old_stderr = sys.stdout, sys.stderr
        out_buf, err_buf = io.StringIO(), io.StringIO()
        try:
            sys.stdout, sys.stderr = out_buf, err_buf
            code = cli_mod.main(["--workspace-root", str(bad_root), "workspace", "show"])
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

        self.assertEqual(code, 1)
        stdout_text = out_buf.getvalue().strip()
        self.assertNotIn("Traceback", stdout_text)
        envelope = json.loads(stdout_text)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "INTERNAL_ERROR")
        self.assertIn("Traceback", err_buf.getvalue())  # the trace IS preserved, just on stderr


class ReimportAdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_unmatched_content_advisory_surfaces_through_cli(self):
        brief = {"audience": "Devs", "eventType": "meetup", "durationMinutes": 20, "takeaway": "T",
                  "proofPoints": [], "excludedTopics": [], "tone": "neutral"}
        run_cli(self.root, "workspace", "new", "--actor", "T", input_json=brief)
        source_payload = {
            "origin": "local", "sourceType": "local_paste", "uri": "paste:x", "owner": "o@example.com",
            "permissionState": "authorized", "aclSnapshot": "owner", "version": "v1", "content": "Fact text.",
        }
        ingest_proc = run_cli(self.root, "source", "ingest", "--actor", "T", input_json=source_payload)
        source_id = json.loads(ingest_proc.stdout)["data"]["source"]["id"]
        extract_proc = run_cli(self.root, "evidence", "extract", source_id, "--actor", "T")
        atom_id = json.loads(extract_proc.stdout)["data"]["evidenceAtoms"][0]["id"]
        run_cli(self.root, "evidence", "set-disposition", atom_id, "KEEP", "--actor", "T")
        claim_proc = run_cli(self.root, "claim", "propose", "--actor", "T",
                              input_json=[{"type": "factual", "text": "X", "evidenceAtomIds": [atom_id]}])
        claim_id = json.loads(claim_proc.stdout)["data"]["claims"][0]["id"]
        run_cli(self.root, "claim", "approve", claim_id, "--actor", "T")
        tl_proc = run_cli(self.root, "narrative", "propose-throughlines", "--actor", "T", input_json=["A", "B", "C"])
        tl_id = json.loads(tl_proc.stdout)["data"]["throughlines"][0]["id"]
        run_cli(self.root, "narrative", "select-throughline", "--id", tl_id, "--actor", "T")
        route_drafts = [
            {"label": "R", "beats": [
                {"role": "HOOK", "headline": "Hook", "timeBudgetSeconds": 60},
                {"role": "STAKES", "headline": "Stakes", "timeBudgetSeconds": 60},
                {"role": "TURN", "headline": "Turn", "timeBudgetSeconds": 60},
                {"role": "MECHANISM", "headline": "Mechanism", "timeBudgetSeconds": 60},
                {"role": "PROOF", "headline": "Proof", "timeBudgetSeconds": 60, "claimIds": [claim_id]},
                {"role": "OBJECTION", "headline": "Objection", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "Ask", "timeBudgetSeconds": 60},
            ]},
            {"label": "Filler", "beats": [
                {"role": "HOOK", "headline": "H", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "A", "timeBudgetSeconds": 60},
            ]},
        ]
        routes_proc = run_cli(self.root, "narrative", "propose-routes", "--throughline-id", tl_id, "--actor", "T", input_json=route_drafts)
        route_id = json.loads(routes_proc.stdout)["data"]["routes"][0]["id"]
        run_cli(self.root, "narrative", "select-route", route_id, "--actor", "T")
        run_cli(self.root, "compile", "--actor", "T")

        import io
        import zipfile
        from engine import persistence as persistence_mod, models as models_mod
        from engine.pptx import ooxml_engine

        store = persistence_mod.Store(root=self.root)
        wid = store.active_workspace_id()
        conn = store.connect(wid)
        slides = persistence_mod.list_all(conn, "slide", wid, models_mod.SlideSpec)
        result = ooxml_engine.export_pptx(slides, wid, models_mod.deck_id(wid), "manifest:x", actor="T", created_iso=models_mod.now_iso())
        conn.close()

        zin = zipfile.ZipFile(io.BytesIO(result.pptx_bytes))
        target = "ppt/slides/slide1.xml"
        xml = zin.read(target).decode("utf-8")
        mutated = xml.replace(
            "</p:spTree>",
            '<p:sp><p:nvSpPr><p:cNvPr id="999" name="Orphan"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            '<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/>'
            '<a:t>Totally unmatched CLI text</a:t></a:r></a:p></p:txBody></p:sp></p:spTree>',
        )
        out_buf = io.BytesIO()
        zout = zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED)
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == target:
                data = mutated.encode("utf-8")
            zout.writestr(item, data)
        zout.close()
        edited_path = self.root / "edited.pptx"
        edited_path.write_bytes(out_buf.getvalue())

        reimport_proc = run_cli(self.root, "reimport", "pptx", "--path", str(edited_path), "--actor", "T")
        envelope = json.loads(reimport_proc.stdout)
        self.assertTrue(envelope["ok"])
        self.assertTrue(any(a["code"] == "UNMATCHED_CONTENT" for a in envelope["data"]["advisories"]))


if __name__ == "__main__":
    unittest.main()
