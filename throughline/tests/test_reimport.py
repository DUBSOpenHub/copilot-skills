"""Re-import round trip (ARCH §15's flagship open test): export, mutate
exactly one region's text via the OOXML layer directly, reimport, and
assert exactly that region is flagged as a pending edit and nothing else
moved. Also covers the manifest and positional fallback resolution tiers,
and the "accept" merge path reopening a claim for FR-PPT-6."""
from __future__ import annotations

import io
import re
import unittest
import zipfile

from helpers import claims_mod, cleanup, evidence_mod, ingest_paste, make_workspace, models, narrative, new_store
from engine import compiler
from engine.pptx import ooxml_engine, reimport

FILLER_ROUTE = {"label": "Filler (unselected)", "beats": [
    {"role": "HOOK", "headline": "Filler hook", "timeBudgetSeconds": 60},
    {"role": "ASK", "headline": "Filler ask", "timeBudgetSeconds": 60},
]}


def _build_and_export(store):
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
        {"role": "STAKES", "headline": "Why this matters now", "timeBudgetSeconds": 60},
        {"role": "TURN", "headline": "What changes", "timeBudgetSeconds": 60},
        {"role": "MECHANISM", "headline": "How it works", "timeBudgetSeconds": 60},
        {"role": "PROOF", "headline": "The 42% figure", "timeBudgetSeconds": 60, "claimIds": [factual.id]},
        {"role": "OBJECTION", "headline": "Is it worth it", "timeBudgetSeconds": 60},
        {"role": "ASK", "headline": "Start today", "timeBudgetSeconds": 60},
    ]
    routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
    narrative.select_route(conn, ws.id, routes[0].id, actor="T")
    slides = compiler.compile_deck(conn, ws.id, actor="T")
    result = ooxml_engine.export_pptx(slides, ws.id, models.deck_id(ws.id), "manifest:1", actor="T", created_iso=models.now_iso())
    return ws, conn, slides, factual, result


def _mutate_slide_headline(pptx_bytes: bytes, slide_file_index: int, old: str, new: str) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(pptx_bytes))
    target = f"ppt/slides/slide{slide_file_index}.xml"
    xml = zin.read(target).decode("utf-8")
    mutated = xml.replace(old, new)
    assert mutated != xml, "mutation must actually change the XML"
    out = io.BytesIO()
    zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == target:
            data = mutated.encode("utf-8")
        zout.writestr(item, data)
    zout.close()
    return out.getvalue()


class ReimportRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_editing_exactly_one_region_flags_exactly_that_region(self):
        ws, conn, slides, factual, result = _build_and_export(self.store)
        proof_slide = [s for s in slides if s.role == "PROOF"][0]
        proof_index = sorted(slides, key=lambda s: s.order).index(proof_slide) + 1
        mutated_bytes = _mutate_slide_headline(result.pptx_bytes, proof_index, "The 42% figure", "The 55% figure (edited)")

        report = reimport.run_reimport(conn, ws.id, mutated_bytes, actor="T")
        self.assertEqual(len(report["pendingEdits"]), 1)
        pe = report["pendingEdits"][0]
        self.assertEqual(pe.region_id, f"{proof_slide.id}:headline")
        self.assertIn("55%", pe.new_text)
        self.assertEqual(len(report["unmatched"]), 0)
        # Every other region across every slide is unchanged.
        expected_unchanged_count = sum(len(s.regions) for s in slides) - 1
        self.assertEqual(len(report["unchanged"]), expected_unchanged_count)
        conn.close()

    def test_accepting_a_single_claim_body_edit_reopens_that_claim(self):
        ws, conn, slides, factual, result = _build_and_export(self.store)
        proof_slide = [s for s in slides if s.role == "PROOF"][0]
        proof_index = sorted(slides, key=lambda s: s.order).index(proof_slide) + 1
        mutated_bytes = _mutate_slide_headline(result.pptx_bytes, proof_index, "Adoption grew 42%.", "Adoption grew 61%.")

        report = reimport.run_reimport(conn, ws.id, mutated_bytes, actor="T")
        body_edit = [pe for pe in report["pendingEdits"] if pe.region_role == "body"][0]
        accept_result = reimport.accept_pending_edit(conn, ws.id, body_edit.id, actor="T")
        self.assertEqual(accept_result["claim"].text, "Adoption grew 61%.")
        self.assertIsNone(accept_result["claim"].approver)  # re-validation-pending
        conn.close()

    def test_discarding_a_pending_edit_leaves_canonical_text_untouched(self):
        ws, conn, slides, factual, result = _build_and_export(self.store)
        proof_slide = [s for s in slides if s.role == "PROOF"][0]
        proof_index = sorted(slides, key=lambda s: s.order).index(proof_slide) + 1
        mutated_bytes = _mutate_slide_headline(result.pptx_bytes, proof_index, "The 42% figure", "Something else entirely")

        report = reimport.run_reimport(conn, ws.id, mutated_bytes, actor="T")
        pe = report["pendingEdits"][0]
        reimport.discard_pending_edit(conn, ws.id, pe.id, actor="T", reason="Speaker changed their mind")
        import engine.persistence as persistence
        slide = persistence.get(conn, "slide", proof_slide.id, models.SlideSpec)
        self.assertEqual(slide.regions["headline"].text, "The 42% figure")
        conn.close()

    def test_completely_unrelated_text_is_unmatched_not_discarded(self):
        ws, conn, slides, factual, result = _build_and_export(self.store)
        zin = zipfile.ZipFile(io.BytesIO(result.pptx_bytes))
        target = "ppt/slides/slide1.xml"
        xml = zin.read(target).decode("utf-8")
        mutated = xml.replace(
            "</p:spTree>",
            '<p:sp><p:nvSpPr><p:cNvPr id="123" name="Brand New Shape"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            '<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/>'
            '<a:t>Totally unexpected orphan content</a:t></a:r></a:p></p:txBody></p:sp></p:spTree>',
        )
        out = io.BytesIO()
        zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == target:
                data = mutated.encode("utf-8")
            zout.writestr(item, data)
        zout.close()

        report = reimport.run_reimport(conn, ws.id, out.getvalue(), actor="T")
        self.assertEqual(len(report["unmatched"]), 1)
        self.assertIn("orphan", report["unmatched"][0].text)
        conn.close()

    def test_manual_linking_of_unmatched_content(self):
        ws, conn, slides, factual, result = _build_and_export(self.store)
        zin = zipfile.ZipFile(io.BytesIO(result.pptx_bytes))
        target = "ppt/slides/slide1.xml"
        xml = zin.read(target).decode("utf-8")
        mutated = xml.replace(
            "</p:spTree>",
            '<p:sp><p:nvSpPr><p:cNvPr id="123" name="Brand New Shape"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            '<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/>'
            '<a:t>Manually linkable text</a:t></a:r></a:p></p:txBody></p:sp></p:spTree>',
        )
        out = io.BytesIO()
        zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == target:
                data = mutated.encode("utf-8")
            zout.writestr(item, data)
        zout.close()
        report = reimport.run_reimport(conn, ws.id, out.getvalue(), actor="T")
        unmatched_item = report["unmatched"][0]
        hook_slide = [s for s in slides if s.role == "HOOK"][0]
        pe = reimport.link_unmatched(conn, ws.id, unmatched_item.id, hook_slide.id, "body", actor="T")
        self.assertEqual(pe.new_text, "Manually linkable text")
        conn.close()

    def test_stripped_shape_name_still_resolves_via_manifest_when_unedited(self):
        """Simulates PowerPoint's 'Reduce File Size' stripping a shape's
        custom name: content is unchanged, so the content-hash fallback
        (tier 2) recovers identity without any name at all."""
        ws, conn, slides, factual, result = _build_and_export(self.store)
        zin = zipfile.ZipFile(io.BytesIO(result.pptx_bytes))
        target = "ppt/slides/slide1.xml"
        xml = zin.read(target).decode("utf-8")
        # Strip the headline shape's name to something generic, but leave its text untouched.
        stripped = re.sub(r'name="deck:[^"]+:headline"', 'name="Text Placeholder 1"', xml, count=1)
        self.assertNotEqual(stripped, xml)
        out = io.BytesIO()
        zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == target:
                data = stripped.encode("utf-8")
            zout.writestr(item, data)
        zout.close()

        report = reimport.run_reimport(conn, ws.id, out.getvalue(), actor="T")
        hook_slide = [s for s in slides if s.role == "HOOK"][0]
        self.assertIn(f"{hook_slide.id}:headline", report["unchanged"])
        self.assertEqual(len(report["pendingEdits"]), 0)
        self.assertEqual(len(report["unmatched"]), 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
