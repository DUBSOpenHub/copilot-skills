"""ARCH §15: every documented error code (engine/errors.py, mirroring
ARCH.md §12) has at least one test that actually produces it."""
from __future__ import annotations

import unittest
from pathlib import Path

from helpers import (
    EngineError, cleanup, compiler, evidence_mod, gates, ingest_mod, make_factual_claim,
    make_workspace, models, narrative, new_store, claims_mod, package, ingest_paste,
)

FILLER_ROUTE = {"label": "Filler route (unselected)", "beats": [
    {"role": "HOOK", "headline": "Filler hook", "timeBudgetSeconds": 60},
    {"role": "ASK", "headline": "Filler ask", "timeBudgetSeconds": 60},
]}


class ErrorCodeTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_source_unauthorized_on_denied_permission(self):
        ws, brief, conn = make_workspace(self.store)
        payload = {
            "origin": "workiq", "sourceType": "teams_message", "uri": "teams://msg/1",
            "owner": "x@example.com", "permissionState": "denied", "aclSnapshot": "n/a",
            "version": "v1", "content": "should never be ingested",
        }
        with self.assertRaises(EngineError) as ctx:
            ingest_mod.ingest_source(conn, ws.id, payload, actor="T", staging_dir=self.store.workspace_dir(ws.id) / "staging")
        self.assertEqual(ctx.exception.code, "SOURCE_UNAUTHORIZED")
        conn.close()

    def test_bundle_limit_reached_on_26th_source(self):
        ws, brief, conn = make_workspace(self.store)
        for i in range(25):
            ingest_paste(conn, self.store, ws.id, f"note {i}", uri=f"paste:note-{i}")
        with self.assertRaises(EngineError) as ctx:
            ingest_paste(conn, self.store, ws.id, "note 26", uri="paste:note-26")
        self.assertEqual(ctx.exception.code, "BUNDLE_LIMIT_REACHED")
        conn.close()

    def test_file_too_large(self):
        ws, brief, conn = make_workspace(self.store)
        big_path = self.root / "big.txt"
        big_path.write_bytes(b"x" * (20 * 1024 * 1024 + 10))
        payload = {
            "origin": "local", "sourceType": "local_upload", "uri": str(big_path),
            "owner": "x@example.com", "permissionState": "authorized", "aclSnapshot": "owner", "version": "v1",
        }
        with self.assertRaises(EngineError) as ctx:
            ingest_mod.ingest_source(conn, ws.id, payload, actor="T", staging_dir=self.store.workspace_dir(ws.id) / "staging")
        self.assertEqual(ctx.exception.code, "FILE_TOO_LARGE")
        conn.close()

    def test_unsupported_file_type(self):
        ws, brief, conn = make_workspace(self.store)
        bad_path = self.root / "notes.exe"
        bad_path.write_bytes(b"binary")
        payload = {
            "origin": "local", "sourceType": "local_upload", "uri": str(bad_path),
            "owner": "x@example.com", "permissionState": "authorized", "aclSnapshot": "owner", "version": "v1",
        }
        with self.assertRaises(EngineError) as ctx:
            ingest_mod.ingest_source(conn, ws.id, payload, actor="T", staging_dir=self.store.workspace_dir(ws.id) / "staging")
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_FILE_TYPE")
        conn.close()

    def test_label_conflict_on_relabeled_reingest(self):
        ws, brief, conn = make_workspace(self.store)
        p = self.root / "doc.txt"
        p.write_text("original content")
        base_payload = {
            "origin": "local", "sourceType": "local_upload", "uri": str(p),
            "owner": "x@example.com", "permissionState": "authorized", "aclSnapshot": "owner", "version": "v1",
            "sensitivityLabel": "internal",
        }
        staging_dir = self.store.workspace_dir(ws.id) / "staging"
        ingest_mod.ingest_source(conn, ws.id, base_payload, actor="T", staging_dir=staging_dir)
        p.write_text("changed content")
        base_payload["sensitivityLabel"] = "confidential"
        second = ingest_mod.ingest_source(conn, ws.id, base_payload, actor="T", staging_dir=staging_dir)
        self.assertEqual(second.state, models.SourceState.LABEL_CONFLICT.value)
        conn.close()

    def test_parse_failed_on_invalid_json(self):
        ws, brief, conn = make_workspace(self.store)
        p = self.root / "bad.json"
        p.write_text("{not valid json,,,")
        payload = {
            "origin": "local", "sourceType": "local_upload", "uri": str(p),
            "owner": "x@example.com", "permissionState": "authorized", "aclSnapshot": "owner", "version": "v1",
        }
        source = ingest_mod.ingest_source(conn, ws.id, payload, actor="T", staging_dir=self.store.workspace_dir(ws.id) / "staging")
        self.assertEqual(source.state, models.SourceState.PARSE_FAILED.value)
        conn.close()

    def test_claim_unsupported_blocks_approval(self):
        ws, brief, conn = make_workspace(self.store)
        created = claims_mod.propose_claims(conn, ws.id, [{"type": "factual", "text": "Unsupported claim"}], actor="T")
        with self.assertRaises(EngineError) as ctx:
            claims_mod.approve_claim(conn, ws.id, created[0].id, actor="T")
        self.assertEqual(ctx.exception.code, "CLAIM_UNSUPPORTED")
        conn.close()

    def test_rationale_required_blocks_interpretive_approval(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Some evidence text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        created = claims_mod.propose_claims(conn, ws.id, [
            {"type": "interpretive", "text": "An interpretation", "evidenceAtomIds": [atoms[0].id]},
        ], actor="T")
        with self.assertRaises(EngineError) as ctx:
            claims_mod.approve_claim(conn, ws.id, created[0].id, actor="T")
        self.assertEqual(ctx.exception.code, "RATIONALE_REQUIRED")
        conn.close()

    def test_conflict_unresolved_blocks_approval(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "First fact.\n\nSecond fact.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        for a in atoms:
            evidence_mod.set_disposition(conn, ws.id, a.id, "KEEP", actor="T")
        created = claims_mod.propose_claims(conn, ws.id, [{"type": "factual", "text": "A disputed number"}], actor="T")
        claim = created[0]
        claims_mod.link_evidence(conn, ws.id, claim.id, atoms[0].id, actor="T")
        claims_mod.link_evidence(conn, ws.id, claim.id, atoms[1].id, actor="T", contradicts_atom_id=atoms[0].id)
        with self.assertRaises(EngineError) as ctx:
            claims_mod.approve_claim(conn, ws.id, claim.id, actor="T")
        self.assertEqual(ctx.exception.code, "CONFLICT_UNRESOLVED")
        conn.close()

    def test_narrative_gate_failed_blocks_compile(self):
        ws, brief, conn = make_workspace(self.store)
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        sel = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
        # Missing a closing ASK beat -> narrative gate must fail.
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{
            "label": "Bad route", "beats": [
                {"role": "HOOK", "headline": "Hook", "timeBudgetSeconds": 60},
                {"role": "STAKES", "headline": "Stakes", "timeBudgetSeconds": 60},
            ],
        }, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        with self.assertRaises(EngineError) as ctx:
            compiler.compile_deck(conn, ws.id, actor="T")
        self.assertEqual(ctx.exception.code, "NARRATIVE_GATE_FAILED")
        conn.close()

    def test_stage_approver_required(self):
        ws, brief, conn = make_workspace(self.store)
        result = gates.run_gate(conn, ws.id, "stage", actor="")
        self.assertFalse(result.passed)
        self.assertTrue(any(f.code == "STAGE_APPROVER_REQUIRED" for f in result.failed_checks))
        conn.close()

    def test_workspace_already_active(self):
        make_workspace(self.store)
        with self.assertRaises(EngineError) as ctx:
            make_workspace(self.store)
        self.assertEqual(ctx.exception.code, "WORKSPACE_ALREADY_ACTIVE")

    def test_demo_fallback_missing_blocks_readiness(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Fact text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        factual = make_factual_claim(conn, ws.id, atoms[0].id)
        claims_mod.approve_claim(conn, ws.id, factual.id, actor="T")
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        sel = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{
            "label": "R", "beats": [
                {"role": "HOOK", "headline": "Hook", "timeBudgetSeconds": 60},
                {"role": "STAKES", "headline": "Stakes", "timeBudgetSeconds": 60},
                {"role": "TURN", "headline": "Turn", "timeBudgetSeconds": 60},
                {"role": "MECHANISM", "headline": "Live demo", "timeBudgetSeconds": 200, "isDemo": True},
                {"role": "PROOF", "headline": "Proof", "timeBudgetSeconds": 60, "claimIds": [factual.id]},
                {"role": "OBJECTION", "headline": "Objection", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "Ask", "timeBudgetSeconds": 60},
            ],
        }, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        compiler.compile_deck(conn, ws.id, actor="T")
        result = gates.run_gate(conn, ws.id, "readiness", actor="T")
        self.assertFalse(result.passed)
        self.assertTrue(any(f.code == "DEMO_FALLBACK_MISSING" for f in result.failed_checks))
        conn.close()

    def test_accessibility_check_failed_missing_alt_text(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Fact text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        factual = make_factual_claim(conn, ws.id, atoms[0].id)
        claims_mod.approve_claim(conn, ws.id, factual.id, actor="T")
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        sel = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{
            "label": "R", "beats": [
                {"role": "HOOK", "headline": "Hook", "timeBudgetSeconds": 60},
                {"role": "STAKES", "headline": "Stakes", "timeBudgetSeconds": 60},
                {"role": "TURN", "headline": "Turn", "timeBudgetSeconds": 60},
                {"role": "MECHANISM", "headline": "Mechanism", "timeBudgetSeconds": 60},
                {"role": "PROOF", "headline": "Proof", "timeBudgetSeconds": 60, "claimIds": [factual.id], "visualDescription": "chart"},
                {"role": "OBJECTION", "headline": "Objection", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "Ask", "timeBudgetSeconds": 60},
            ],
        }, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        compiler.compile_deck(conn, ws.id, actor="T")
        result = gates.run_gate(conn, ws.id, "readiness", actor="T")
        self.assertFalse(result.passed)
        self.assertTrue(any(f.code == "ACCESSIBILITY_CHECK_FAILED" for f in result.failed_checks))
        conn.close()

    def test_access_revoked_cascades_to_evidence(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Fact text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        ingest_mod.revoke_access(conn, ws.id, source.id, actor="T")
        result = gates.run_gate(conn, ws.id, "evidence", actor="T")
        self.assertFalse(result.passed)
        self.assertTrue(any(f.code == "ACCESS_REVOKED" for f in result.failed_checks))
        conn.close()

    def test_source_stale_at_exact_boundary(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Fact text.")
        # local_paste has no elapsed-time rule; force a type with a 7-day window instead.
        source.source_type = "teams_message"
        source.captured_at = "2020-01-01T00:00:00Z"
        import engine.persistence as persistence
        persistence.commit(conn, "source", source, None)
        updated = ingest_mod.revalidate_staleness(conn, ws.id, source.id, actor="T", now_override="2020-01-08T00:00:01Z")
        self.assertEqual(updated.state, models.SourceState.STALE.value)
        conn.close()

    def test_source_stale_error_code_surfaces_on_evidence_gate(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Fact text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        import engine.persistence as persistence
        kept_atom = persistence.get(conn, "evidence", atoms[0].id, models.EvidenceAtom)
        kept_atom.freshness_state = models.FreshnessState.STALE.value
        persistence.commit(conn, "evidence", kept_atom, None)
        result = gates.run_gate(conn, ws.id, "evidence", actor="T")
        self.assertFalse(result.passed)
        self.assertTrue(any(f.code == "SOURCE_STALE" for f in result.failed_checks))
        conn.close()

    def test_demo_asset_missing_advisory_on_package_export(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Fact text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        factual = make_factual_claim(conn, ws.id, atoms[0].id)
        claims_mod.approve_claim(conn, ws.id, factual.id, actor="T")
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        sel = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{
            "label": "R", "beats": [
                {"role": "HOOK", "headline": "Hook", "timeBudgetSeconds": 60},
                {"role": "STAKES", "headline": "Stakes", "timeBudgetSeconds": 60},
                {"role": "TURN", "headline": "Turn", "timeBudgetSeconds": 60},
                {"role": "MECHANISM", "headline": "Live demo", "timeBudgetSeconds": 60, "isDemo": True},
                {"role": "PROOF", "headline": "Proof", "timeBudgetSeconds": 60, "claimIds": [factual.id]},
                {"role": "OBJECTION", "headline": "Objection", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "Ask", "timeBudgetSeconds": 60},
            ],
        }, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        slides = compiler.compile_deck(conn, ws.id, actor="T")
        for s in slides:
            if "visual" in s.regions:
                compiler.set_alt_text(conn, ws.id, s.id, "visual", "Alt text", confirmed_by="T", actor="T")
        demo_slide = [s for s in slides if s.role == "MECHANISM"][0]
        compiler.set_demo_asset(
            conn, ws.id, demo_slide.id, actor="T", live_path="live",
            prerecorded_asset_path="/no/such/file.mp4", static_asset_path="/no/such/file.png",
            verbal_recovery_script="Narrate it.",
        )
        gates.run_gate(conn, ws.id, "readiness", actor="T")
        result = package.export_package(conn, ws.id, actor="Named Approver")
        self.assertTrue(any(a["code"] == "DEMO_ASSET_MISSING" for a in result["advisories"]))
        conn.close()

    def test_unmatched_content_from_reimport(self):
        from engine.pptx import ooxml_engine, reimport as reimport_mod
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Fact text.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        factual = make_factual_claim(conn, ws.id, atoms[0].id)
        throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, ["A", "B", "C"], actor="T")
        sel = narrative.select_throughline(conn, ws.id, actor="T", throughline_id=throughlines[0].id)
        routes = narrative.propose_routes(conn, ws.id, sel.id, [{
            "label": "R", "beats": [
                {"role": "HOOK", "headline": "Hook", "timeBudgetSeconds": 60},
                {"role": "STAKES", "headline": "Stakes", "timeBudgetSeconds": 60},
                {"role": "TURN", "headline": "Turn", "timeBudgetSeconds": 60},
                {"role": "MECHANISM", "headline": "Mechanism", "timeBudgetSeconds": 60},
                {"role": "PROOF", "headline": "Proof", "timeBudgetSeconds": 60, "claimIds": [factual.id]},
                {"role": "OBJECTION", "headline": "Objection", "timeBudgetSeconds": 60},
                {"role": "ASK", "headline": "Ask", "timeBudgetSeconds": 60},
            ],
        }, FILLER_ROUTE], actor="T")
        narrative.select_route(conn, ws.id, routes[0].id, actor="T")
        compiler.compile_deck(conn, ws.id, actor="T")
        import engine.persistence as persistence
        slides = persistence.list_all(conn, "slide", ws.id, models.SlideSpec)
        deck_id = models.deck_id(ws.id)
        result = ooxml_engine.export_pptx(slides, ws.id, deck_id, "manifest:x", actor="T", created_iso=models.now_iso())
        import zipfile
        import io
        zin = zipfile.ZipFile(io.BytesIO(result.pptx_bytes))
        target = "ppt/slides/slide1.xml"
        xml = zin.read(target).decode("utf-8")
        mutated = xml.replace('name="Footer (decorative)"', 'name="Footer (decorative)"').replace(
            "<a:t>Hook</a:t>", "<a:t>Hook</a:t>"
        )
        # Add a brand-new, never-before-seen shape so it cannot resolve via
        # name, content-hash, or position/placeholder-type fallback.
        mutated = mutated.replace(
            "</p:spTree>",
            '<p:sp><p:nvSpPr><p:cNvPr id="99" name="Unrelated Shape"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            '<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/>'
            '<a:t>Completely unrelated orphan text</a:t></a:r></a:p></p:txBody></p:sp></p:spTree>',
        )
        out_buf = io.BytesIO()
        zout = zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED)
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == target:
                data = mutated.encode("utf-8")
            zout.writestr(item, data)
        zout.close()
        report = reimport_mod.run_reimport(conn, ws.id, out_buf.getvalue(), actor="T")
        self.assertTrue(any("orphan" in u.text for u in report["unmatched"]))
        conn.close()


if __name__ == "__main__":
    unittest.main()
