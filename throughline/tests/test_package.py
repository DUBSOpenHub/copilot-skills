"""Artifact Package Contract: all 9 FR-DEL-6 kinds present (with
LAST_KNOWN_GOOD appearing only once a prior Stage-approved package
exists), sha256 verification, and shared workspace/deck/manifest identity
(NFR-7)."""
from __future__ import annotations

import hashlib
import json
import unittest
import zipfile
from pathlib import Path

from helpers import claims_mod, cleanup, evidence_mod, gates, ingest_paste, make_workspace, models, narrative, new_store, package
from engine import compiler

FILLER_ROUTE = {"label": "Filler (unselected)", "beats": [
    {"role": "HOOK", "headline": "Filler hook", "timeBudgetSeconds": 60},
    {"role": "ASK", "headline": "Filler ask", "timeBudgetSeconds": 60},
]}


def _stage_ready_workspace(store):
    ws, brief, conn = make_workspace(store)
    source = ingest_paste(conn, store, ws.id, "Adoption grew 42 percent.")
    atom = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")[0]
    evidence_mod.set_disposition(conn, ws.id, atom.id, "KEEP", actor="T")
    factual = claims_mod.propose_claims(conn, ws.id, [
        {"type": "factual", "text": "Adoption grew 42%.", "evidenceAtomIds": [atom.id]},
    ], actor="T")[0]
    claims_mod.approve_claim(conn, ws.id, factual.id, actor="T")
    throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
    sel = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
    beats = [
        {"role": "HOOK", "headline": "A number that matters", "timeBudgetSeconds": 60},
        {"role": "STAKES", "headline": "Why this matters now", "timeBudgetSeconds": 60, "visualDescription": "Photo"},
        {"role": "TURN", "headline": "What changes", "timeBudgetSeconds": 60, "visualDescription": "Diagram"},
        {"role": "MECHANISM", "headline": "How it works", "timeBudgetSeconds": 60, "visualDescription": "Live demo"},
        {"role": "PROOF", "headline": "The 42% figure", "timeBudgetSeconds": 60, "claimIds": [factual.id], "visualDescription": "Bar chart"},
        {"role": "OBJECTION", "headline": "Is it worth it", "timeBudgetSeconds": 60, "visualDescription": "Quote"},
        {"role": "ASK", "headline": "Start today", "timeBudgetSeconds": 60},
    ]
    routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
    narrative.select_route(conn, ws.id, routes[0].id, actor="T")
    slides = compiler.compile_deck(conn, ws.id, actor="T")
    for s in slides:
        if "visual" in s.regions:
            compiler.set_alt_text(conn, ws.id, s.id, "visual", "Descriptive alt text", confirmed_by="Speaker", actor="T")
    gates.run_gate(conn, ws.id, "stage", actor="Named Approver")
    return ws, conn


class PackageCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_first_package_has_eight_kinds_and_no_lkg_advisory(self):
        ws, conn = _stage_ready_workspace(self.store)
        result = package.export_package(conn, ws.id, actor="Named Approver")
        kinds = {a["kind"] for a in result["manifest"]["artifacts"]}
        expected_without_lkg = set(package.ARTIFACT_KINDS) - {"LAST_KNOWN_GOOD"}
        self.assertEqual(kinds, expected_without_lkg)
        self.assertTrue(any(a["code"] == "NO_LKG_AVAILABLE" for a in result["advisories"]))
        conn.close()

    def test_second_package_includes_last_known_good(self):
        ws, conn = _stage_ready_workspace(self.store)
        first = package.export_package(conn, ws.id, actor="Named Approver")
        second = package.export_package(conn, ws.id, actor="Named Approver")
        kinds = {a["kind"] for a in second["manifest"]["artifacts"]}
        self.assertEqual(kinds, set(package.ARTIFACT_KINDS))
        self.assertFalse(any(a["code"] == "NO_LKG_AVAILABLE" for a in second["advisories"]))
        lkg_path = Path(second["exportDir"]) / "last-known-good.pptx"
        first_deck_path = Path(first["exportDir"]) / "deck.pptx"
        self.assertEqual(lkg_path.read_bytes(), first_deck_path.read_bytes())
        conn.close()

    def test_every_file_artifact_sha256_verifies(self):
        ws, conn = _stage_ready_workspace(self.store)
        result = package.export_package(conn, ws.id, actor="Named Approver")
        export_dir = Path(result["exportDir"])
        for artifact in result["manifest"]["artifacts"]:
            if artifact["sha256"] is None:
                continue
            data = (export_dir / artifact["relPath"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), artifact["sha256"])
        conn.close()

    def test_all_artifacts_share_one_workspace_deck_manifest_identity(self):
        ws, conn = _stage_ready_workspace(self.store)
        result = package.export_package(conn, ws.id, actor="Named Approver")
        manifest = result["manifest"]
        self.assertEqual(manifest["workspaceId"], ws.id)
        export_dir = Path(result["exportDir"])
        core_manifest = json.loads((export_dir / "evidence-approval-manifest.json").read_text())
        self.assertTrue(all(s["workspace_id"] == ws.id for s in core_manifest["sources"]))
        with zipfile.ZipFile(export_dir / "deck.pptx") as zf:
            custom_xml = zf.read("docProps/custom.xml").decode("utf-8")
        self.assertIn(manifest["deckId"], custom_xml)
        self.assertIn(manifest["manifestId"], custom_xml)
        conn.close()

    def test_package_export_refused_before_stage_gate_passes(self):
        from engine.errors import EngineError
        ws, brief, conn = make_workspace(self.store)
        with self.assertRaises(EngineError) as ctx:
            package.export_package(conn, ws.id, actor="T")
        self.assertEqual(ctx.exception.code, "GATE_NOT_PASSED")
        conn.close()

    def test_captions_vtt_is_well_formed(self):
        ws, conn = _stage_ready_workspace(self.store)
        result = package.export_package(conn, ws.id, actor="Named Approver")
        vtt_path = Path(result["exportDir"]) / "captions.vtt"
        text = vtt_path.read_text()
        self.assertTrue(text.startswith("WEBVTT"))
        self.assertIn("-->", text)
        conn.close()

    def test_offline_backup_zip_contains_every_other_artifact(self):
        ws, conn = _stage_ready_workspace(self.store)
        result = package.export_package(conn, ws.id, actor="Named Approver")
        export_dir = Path(result["exportDir"])
        with zipfile.ZipFile(export_dir / "offline-backup.zip") as zf:
            names = set(zf.namelist())
        self.assertIn("deck.pptx", names)
        self.assertIn("manifest.json", names)
        self.assertIn("deck-accessible.pdf", names)
        self.assertNotIn("offline-backup.zip", names)
        conn.close()


if __name__ == "__main__":
    unittest.main()
