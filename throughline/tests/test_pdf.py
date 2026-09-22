"""Accessible PDF export: the stdlib fallback composer is a genuine, valid
PDF (validated with `pypdf`), and ARCH §15's explicitly flagged open test
#2 — the `PDF_FALLBACK_USED` path is itself exercised in CI, where
LibreOffice is normally absent — is asserted directly."""
from __future__ import annotations

import unittest

from helpers import cleanup, models, new_store
from engine import pdf as pdf_mod

try:
    import pypdf
    HAVE_PYPDF = True
except ImportError:  # pragma: no cover
    HAVE_PYPDF = False


def _sample_slides():
    region = lambda role, text, alt=None, confirmed=None: models.Region(
        role=role, text=text, content_hash="h", alt_text=alt, alt_text_confirmed_by=confirmed,
    )
    slide1 = models.SlideSpec(
        id="deck:w:0", workspace_id="w", deck_id="deck:w", beat_id="b0", order=0, role="HOOK", layout="hook",
        regions={
            "headline": region("headline", "A number that matters"),
            "body": region("body", "One-line context"),
            "notes.spoken": region("notes.spoken", "Open cold."),
            "notes.transitionIn": region("notes.transitionIn", ""),
            "notes.transitionOut": region("notes.transitionOut", "Then the stakes."),
            "notes.timeBudget": region("notes.timeBudget", "60"),
            "notes.fallback": region("notes.fallback", "Say the headline aloud."),
            "notes.sources": region("notes.sources", "talk-brief"),
        },
        reading_order=["headline", "body", "notes.spoken", "notes.transitionIn", "notes.transitionOut", "notes.timeBudget", "notes.fallback", "notes.sources"],
    )
    slide2 = models.SlideSpec(
        id="deck:w:1", workspace_id="w", deck_id="deck:w", beat_id="b1", order=1, role="PROOF", layout="standard",
        regions={
            "headline": region("headline", "Proof point"),
            "visual": region("visual", "Bar chart", alt="Bar chart showing 42% growth", confirmed="Speaker"),
            "body": region("body", "Adoption grew 42%."),
            "notes.spoken": region("notes.spoken", "Explain the chart."),
            "notes.transitionIn": region("notes.transitionIn", "Building on that,"),
            "notes.transitionOut": region("notes.transitionOut", ""),
            "notes.timeBudget": region("notes.timeBudget", "90"),
            "notes.fallback": region("notes.fallback", "Summarize the number verbally."),
            "notes.sources": region("notes.sources", "paste:note#p0"),
        },
        reading_order=["headline", "visual", "body", "notes.spoken", "notes.transitionIn", "notes.transitionOut", "notes.timeBudget", "notes.fallback", "notes.sources"],
    )
    return [slide1, slide2]


class FallbackPdfTests(unittest.TestCase):
    def test_soffice_not_present_in_this_environment(self):
        # This environment has no LibreOffice installed; assert that fact
        # directly so the fallback path below is known to be exercised,
        # not silently skipped (ARCH §15 open test #2).
        self.assertIsNone(pdf_mod.find_soffice())

    def test_export_accessible_pdf_uses_fallback_and_flags_it(self):
        slides = _sample_slides()
        result = pdf_mod.export_accessible_pdf(slides, "workspace:w", "deck:w", "manifest:m", title="Test Deck")
        self.assertTrue(result.used_fallback)
        self.assertTrue(result.pdf_bytes.startswith(b"%PDF-1.4"))

    @unittest.skipUnless(HAVE_PYPDF, "pypdf not available for validation")
    def test_fallback_pdf_is_valid_and_readable(self):
        slides = _sample_slides()
        result = pdf_mod.export_accessible_pdf(slides, "workspace:w", "deck:w", "manifest:m", title="Test Deck")
        import io
        reader = pypdf.PdfReader(io.BytesIO(result.pdf_bytes))
        self.assertEqual(len(reader.pages), 2)
        page1_text = reader.pages[0].extract_text()
        self.assertIn("A number that matters", page1_text)
        page2_text = reader.pages[1].extract_text()
        self.assertIn("Proof point", page2_text)
        self.assertIn("Bar chart showing 42% growth", page2_text)  # alt text surfaced

    @unittest.skipUnless(HAVE_PYPDF, "pypdf not available for validation")
    def test_metadata_stamps_workspace_deck_manifest_ids(self):
        slides = _sample_slides()
        result = pdf_mod.export_accessible_pdf(slides, "workspace:w-id", "deck:w-id", "manifest:m-id", title="Test Deck")
        import io
        reader = pypdf.PdfReader(io.BytesIO(result.pdf_bytes))
        meta = reader.metadata
        self.assertEqual(meta["/ThroughlineWorkspaceId"], "workspace:w-id")
        self.assertEqual(meta["/ThroughlineDeckId"], "deck:w-id")
        self.assertEqual(meta["/ThroughlineManifestId"], "manifest:m-id")

    @unittest.skipUnless(HAVE_PYPDF, "pypdf not available for validation")
    def test_reading_order_is_respected_in_page_text(self):
        slides = _sample_slides()
        result = pdf_mod.export_accessible_pdf(slides, "workspace:w", "deck:w", "manifest:m", title="Test Deck")
        import io
        reader = pypdf.PdfReader(io.BytesIO(result.pdf_bytes))
        text = reader.pages[1].extract_text()
        headline_pos = text.find("Proof point")
        visual_pos = text.find("Bar chart")
        body_pos = text.find("Adoption grew")
        self.assertTrue(headline_pos < visual_pos < body_pos)


if __name__ == "__main__":
    unittest.main()
