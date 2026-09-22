"""Genuine, editable `.pptx` generation: native text shapes, native
speaker notes, and stable IDs across repeated exports of an unchanged
workspace. Uses `python-pptx` (already present in this environment) only
to *validate* the Engine's own OOXML output — the Engine never imports it."""
from __future__ import annotations

import io
import unittest
import zipfile

from helpers import claims_mod, cleanup, evidence_mod, ingest_paste, make_workspace, models, narrative, new_store
from engine import compiler
from engine.pptx import ooxml_engine

try:
    from pptx import Presentation
    HAVE_PPTX = True
except ImportError:  # pragma: no cover - environment always has it, but stay honest
    HAVE_PPTX = False

FILLER_ROUTE = {"label": "Filler (unselected)", "beats": [
    {"role": "HOOK", "headline": "Filler hook", "timeBudgetSeconds": 60},
    {"role": "ASK", "headline": "Filler ask", "timeBudgetSeconds": 60},
]}


def _build_compiled_workspace(store):
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
        {"role": "HOOK", "headline": "A number that matters", "timeBudgetSeconds": 60, "spokenTalkTrack": "Open with the stat."},
        {"role": "STAKES", "headline": "Why this matters now", "timeBudgetSeconds": 60, "spokenTalkTrack": "Stakes talk track.", "visualDescription": "Photo"},
        {"role": "TURN", "headline": "What changes", "timeBudgetSeconds": 60, "spokenTalkTrack": "Turn talk track.", "visualDescription": "Diagram"},
        {"role": "MECHANISM", "headline": "How it works", "timeBudgetSeconds": 60, "spokenTalkTrack": "Mechanism talk track.", "visualDescription": "Live demo", "isDemo": True},
        {"role": "PROOF", "headline": "The 42% figure", "timeBudgetSeconds": 60, "claimIds": [factual.id], "spokenTalkTrack": "Proof talk track.", "visualDescription": "Bar chart"},
        {"role": "OBJECTION", "headline": "Is it worth it", "timeBudgetSeconds": 60, "spokenTalkTrack": "Objection talk track.", "visualDescription": "Quote"},
        {"role": "ASK", "headline": "Start today", "timeBudgetSeconds": 60, "spokenTalkTrack": "Ask talk track."},
    ]
    routes = narrative.propose_routes(conn, ws.id, sel.id, [{"label": "R", "beats": beats}, FILLER_ROUTE], actor="T")
    narrative.select_route(conn, ws.id, routes[0].id, actor="T")
    slides = compiler.compile_deck(conn, ws.id, actor="T")
    return ws, conn, slides, factual


@unittest.skipUnless(HAVE_PPTX, "python-pptx not available for validation")
class GeneratedPptxTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_exported_pptx_opens_and_has_native_editable_text(self):
        ws, conn, slides, factual = _build_compiled_workspace(self.store)
        result = ooxml_engine.export_pptx(slides, ws.id, models.deck_id(ws.id), "manifest:t1", actor="T", created_iso=models.now_iso())
        pres = Presentation(io.BytesIO(result.pptx_bytes))
        self.assertEqual(len(pres.slides), len(slides))
        headline_texts = []
        for slide in pres.slides:
            for shape in slide.shapes:
                if shape.has_text_frame and "headline" in shape.name:
                    headline_texts.append(shape.text_frame.text)
        self.assertIn("A number that matters", headline_texts)
        conn.close()

    def test_every_slide_has_native_notes_with_labeled_sections(self):
        ws, conn, slides, factual = _build_compiled_workspace(self.store)
        result = ooxml_engine.export_pptx(slides, ws.id, models.deck_id(ws.id), "manifest:t1", actor="T", created_iso=models.now_iso())
        pres = Presentation(io.BytesIO(result.pptx_bytes))
        for slide in pres.slides:
            self.assertTrue(slide.has_notes_slide)
            notes_text = slide.notes_slide.notes_text_frame.text
            self.assertIn("Time budget:", notes_text)
            self.assertIn("Fallback:", notes_text)
            self.assertIn("Sources:", notes_text)
        conn.close()

    def test_shape_names_carry_stable_region_ids(self):
        ws, conn, slides, factual = _build_compiled_workspace(self.store)
        result = ooxml_engine.export_pptx(slides, ws.id, models.deck_id(ws.id), "manifest:t1", actor="T", created_iso=models.now_iso())
        pres = Presentation(io.BytesIO(result.pptx_bytes))
        first_slide_names = {sh.name for sh in pres.slides[0].shapes if sh.has_text_frame}
        deck_id = models.deck_id(ws.id)
        expected_headline_region = models.region_id(models.slide_id(deck_id, 0), "headline")
        self.assertIn(expected_headline_region, first_slide_names)
        conn.close()

    def test_ids_stable_across_two_exports_of_unchanged_workspace(self):
        ws, conn, slides, factual = _build_compiled_workspace(self.store)
        r1 = ooxml_engine.export_pptx(slides, ws.id, models.deck_id(ws.id), "manifest:t1", actor="T", created_iso=models.now_iso())
        r2 = ooxml_engine.export_pptx(slides, ws.id, models.deck_id(ws.id), "manifest:t2", actor="T", created_iso=models.now_iso())
        self.assertEqual(set(r1.manifest.keys()), set(r2.manifest.keys()))
        for region_id in r1.manifest:
            self.assertEqual(r1.manifest[region_id]["contentHash"], r2.manifest[region_id]["contentHash"])
        conn.close()

    def test_zip_is_well_formed(self):
        ws, conn, slides, factual = _build_compiled_workspace(self.store)
        result = ooxml_engine.export_pptx(slides, ws.id, models.deck_id(ws.id), "manifest:t1", actor="T", created_iso=models.now_iso())
        zf = zipfile.ZipFile(io.BytesIO(result.pptx_bytes))
        self.assertIsNone(zf.testzip())
        self.assertIn("[Content_Types].xml", zf.namelist())
        self.assertIn("customXml/item1.xml", zf.namelist())
        conn.close()

    def test_custom_properties_stamp_workspace_deck_manifest_ids(self):
        ws, conn, slides, factual = _build_compiled_workspace(self.store)
        deck_id = models.deck_id(ws.id)
        result = ooxml_engine.export_pptx(slides, ws.id, deck_id, "manifest:stamped", actor="T", created_iso=models.now_iso())
        zf = zipfile.ZipFile(io.BytesIO(result.pptx_bytes))
        custom_xml = zf.read("docProps/custom.xml").decode("utf-8")
        self.assertIn(ws.id, custom_xml)
        self.assertIn(deck_id, custom_xml)
        self.assertIn("manifest:stamped", custom_xml)
        conn.close()

    def test_panic_mode_forces_static_asset_and_verbal_script(self):
        ws, conn, slides, factual = _build_compiled_workspace(self.store)
        mechanism = [s for s in slides if s.role == "MECHANISM"][0]
        compiler.set_demo_asset(
            conn, ws.id, mechanism.id, actor="T", live_path="live", prerecorded_asset_path="rec.mp4",
            static_asset_path="static.png", verbal_recovery_script="Narrate it verbally.",
        )
        import engine.persistence as persistence
        refreshed_slides = persistence.list_all(conn, "slide", ws.id, models.SlideSpec)
        result = ooxml_engine.export_pptx(refreshed_slides, ws.id, models.deck_id(ws.id), "manifest:panic", actor="T", created_iso=models.now_iso(), render_mode="panic")
        pres = Presentation(io.BytesIO(result.pptx_bytes))
        mechanism_index = [i for i, s in enumerate(sorted(refreshed_slides, key=lambda s: s.order)) if s.role == "MECHANISM"][0]
        slide = pres.slides[mechanism_index]
        notes_text = slide.notes_slide.notes_text_frame.text
        self.assertIn("VERBAL RECOVERY", notes_text)
        visual_text = next(sh.text_frame.text for sh in slide.shapes if sh.has_text_frame and "visual" in sh.name)
        self.assertIn("STATIC BACKUP", visual_text)
        conn.close()


if __name__ == "__main__":
    unittest.main()
