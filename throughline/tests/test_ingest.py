"""Source Ingest Port: FR-SRC-1..6, FR-EVD-1's field-population contract,
staleness boundaries (§16.2), and real local-document parsing."""
from __future__ import annotations

import json
import unittest
import zipfile
from xml.etree import ElementTree as ET

from helpers import cleanup, evidence_mod, ingest_mod, ingest_paste, make_workspace, models, new_store


class IngestFieldPopulationTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_source_reaches_authorized_before_extraction_allowed(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Hello world.")
        self.assertEqual(source.state, models.SourceState.AUTHORIZED.value)
        conn.close()

    def test_evidence_atom_has_nine_required_fields_populated(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "A single paragraph of evidence.")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        self.assertEqual(len(atoms), 1)
        atom = atoms[0]
        self.assertTrue(atom.has_required_fields())
        for field_name in ("source_id", "locator", "owner", "version", "content_hash", "access_snapshot", "freshness"):
            self.assertTrue(getattr(atom, field_name), f"{field_name} should be populated")
        self.assertIsNotNone(atom.confidence)
        self.assertEqual(atom.linked_claim_ids, [])  # populated as an empty list, not required non-empty
        conn.close()

    def test_content_hash_is_deterministic_sha256(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Deterministic content.")
        import hashlib
        expected = hashlib.sha256(b"Deterministic content.").hexdigest()
        self.assertEqual(source.content_hash, expected)
        conn.close()

    def test_local_file_independently_verified_unreadable_is_unauthorized(self):
        ws, brief, conn = make_workspace(self.store)
        p = self.root / "secret.txt"
        p.write_text("shh")
        p.chmod(0o000)
        try:
            payload = {
                "origin": "local", "sourceType": "local_upload", "uri": str(p),
                "owner": "x@example.com", "permissionState": "authorized", "aclSnapshot": "owner", "version": "v1",
            }
            from engine.errors import EngineError
            with self.assertRaises(EngineError) as ctx:
                ingest_mod.ingest_source(conn, ws.id, payload, actor="T", staging_dir=self.store.workspace_dir(ws.id) / "staging")
            self.assertEqual(ctx.exception.code, "SOURCE_UNAUTHORIZED")
        finally:
            p.chmod(0o644)
        conn.close()

    def test_bundle_cap_does_not_count_retired_sources(self):
        ws, brief, conn = make_workspace(self.store)
        sources = [ingest_paste(conn, self.store, ws.id, f"note {i}", uri=f"paste:n{i}") for i in range(25)]
        ingest_mod.retire_source(conn, ws.id, sources[0].id, actor="T")
        # Retiring one frees a slot; a 25th (well, 26th overall, but only
        # 24 active remain) add should succeed.
        added = ingest_paste(conn, self.store, ws.id, "note extra", uri="paste:extra")
        self.assertEqual(added.state, models.SourceState.AUTHORIZED.value)
        conn.close()


class StalenessBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def _teams_source(self, conn, ws_id, captured_at):
        source = ingest_paste(conn, self.store, ws_id, "Some transcript text.")
        source.source_type = "teams_transcript"
        source.captured_at = captured_at
        import engine.persistence as persistence
        persistence.commit(conn, "source", source, None)
        return source

    def test_just_under_seven_days_stays_fresh(self):
        ws, brief, conn = make_workspace(self.store)
        source = self._teams_source(conn, ws.id, "2020-01-01T00:00:00Z")
        updated = ingest_mod.revalidate_staleness(conn, ws.id, source.id, actor="T", now_override="2020-01-07T23:59:59Z")
        self.assertNotEqual(updated.state, models.SourceState.STALE.value)
        conn.close()

    def test_exactly_seven_days_becomes_stale(self):
        ws, brief, conn = make_workspace(self.store)
        source = self._teams_source(conn, ws.id, "2020-01-01T00:00:00Z")
        updated = ingest_mod.revalidate_staleness(conn, ws.id, source.id, actor="T", now_override="2020-01-08T00:00:00Z")
        self.assertEqual(updated.state, models.SourceState.STALE.value)
        conn.close()

    def test_document_type_uses_fourteen_day_window(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Doc text.")
        source.source_type = "sharepoint_doc"
        source.captured_at = "2020-01-01T00:00:00Z"
        import engine.persistence as persistence
        persistence.commit(conn, "source", source, None)
        still_fresh = ingest_mod.revalidate_staleness(conn, ws.id, source.id, actor="T", now_override="2020-01-14T00:00:00Z")
        self.assertNotEqual(still_fresh.state, models.SourceState.STALE.value)
        now_stale = ingest_mod.revalidate_staleness(conn, ws.id, source.id, actor="T", now_override="2020-01-15T00:00:00Z")
        self.assertEqual(now_stale.state, models.SourceState.STALE.value)
        conn.close()

    def test_local_paste_has_no_elapsed_time_rule(self):
        ws, brief, conn = make_workspace(self.store)
        source = ingest_paste(conn, self.store, ws.id, "Paste text.")
        source.captured_at = "2000-01-01T00:00:00Z"
        import engine.persistence as persistence
        persistence.commit(conn, "source", source, None)
        updated = ingest_mod.revalidate_staleness(conn, ws.id, source.id, actor="T", now_override="2030-01-01T00:00:00Z")
        self.assertNotEqual(updated.state, models.SourceState.STALE.value)
        conn.close()

    def test_stale_cascades_to_dependent_evidence_and_demotes_factual_claim(self):
        from helpers import claims_mod
        ws, brief, conn = make_workspace(self.store)
        source = self._teams_source(conn, ws.id, "2020-01-01T00:00:00Z")
        atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor="T")
        evidence_mod.set_disposition(conn, ws.id, atoms[0].id, "KEEP", actor="T")
        claim = claims_mod.propose_claims(conn, ws.id, [
            {"type": "factual", "text": "A fact", "evidenceAtomIds": [atoms[0].id]},
        ], actor="T")[0]
        claims_mod.approve_claim(conn, ws.id, claim.id, actor="T")
        ingest_mod.revalidate_staleness(conn, ws.id, source.id, actor="T", now_override="2020-01-08T00:00:00Z")
        import engine.persistence as persistence
        refreshed_claim = persistence.get(conn, "claim", claim.id, models.Claim)
        self.assertEqual(refreshed_claim.state, models.ClaimState.REWRITE_REQUIRED.value)
        self.assertIsNotNone(refreshed_claim.hedged_rewrite)
        conn.close()


class RealParserTests(unittest.TestCase):
    """FR-M365-2/§16.1: local documents are genuinely parsed, not stubbed."""

    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def _ingest_and_extract(self, conn, ws_id, path):
        payload = {
            "origin": "local", "sourceType": "local_upload", "uri": str(path),
            "owner": "x@example.com", "permissionState": "authorized", "aclSnapshot": "owner", "version": "v1",
        }
        source = ingest_mod.ingest_source(conn, ws_id, payload, actor="T", staging_dir=self.store.workspace_dir(ws_id) / "staging")
        return source

    def test_csv_is_really_parsed(self):
        ws, brief, conn = make_workspace(self.store)
        p = self.root / "data.csv"
        p.write_text("name,value\nadoption,42\n")
        source = self._ingest_and_extract(conn, ws.id, p)
        self.assertEqual(source.state, models.SourceState.AUTHORIZED.value)
        text = (self.root.parent).exists()  # noop to keep lints calm
        staged_text = open(source.local_path, encoding="utf-8").read()
        self.assertIn("adoption", staged_text)
        self.assertIn("42", staged_text)
        conn.close()

    def test_json_validates_and_reformats(self):
        ws, brief, conn = make_workspace(self.store)
        p = self.root / "data.json"
        p.write_text('{"adoption": 42}')
        source = self._ingest_and_extract(conn, ws.id, p)
        self.assertEqual(source.state, models.SourceState.AUTHORIZED.value)
        staged = json.loads(open(source.local_path, encoding="utf-8").read())
        self.assertEqual(staged, {"adoption": 42})
        conn.close()

    def test_invalid_json_is_parse_failed(self):
        ws, brief, conn = make_workspace(self.store)
        p = self.root / "bad.json"
        p.write_text("{ this is not json")
        source = self._ingest_and_extract(conn, ws.id, p)
        self.assertEqual(source.state, models.SourceState.PARSE_FAILED.value)
        self.assertIsNotNone(source.hold_reason)
        conn.close()

    def test_docx_text_is_extracted_via_ooxml(self):
        ws, brief, conn = make_workspace(self.store)
        p = self.root / "notes.docx"
        _write_minimal_docx(p, ["Adoption grew 42 percent."])
        source = self._ingest_and_extract(conn, ws.id, p)
        self.assertEqual(source.state, models.SourceState.AUTHORIZED.value)
        staged_text = open(source.local_path, encoding="utf-8").read()
        self.assertIn("Adoption grew 42 percent.", staged_text)
        conn.close()

    def test_pptx_text_is_extracted_via_ooxml(self):
        ws, brief, conn = make_workspace(self.store)
        p = self.root / "prior-deck.pptx"
        _write_minimal_pptx(p, ["Prior talk slide one text"])
        source = self._ingest_and_extract(conn, ws.id, p)
        self.assertEqual(source.state, models.SourceState.AUTHORIZED.value)
        staged_text = open(source.local_path, encoding="utf-8").read()
        self.assertIn("Prior talk slide one text", staged_text)
        conn.close()

    def test_image_has_no_text_but_is_not_a_failure(self):
        ws, brief, conn = make_workspace(self.store)
        p = self.root / "photo.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\nnot a real png but has the right extension")
        source = self._ingest_and_extract(conn, ws.id, p)
        self.assertEqual(source.state, models.SourceState.AUTHORIZED.value)
        conn.close()


def _write_minimal_docx(path, paragraphs: list[str]) -> None:
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        zf.writestr("word/document.xml", xml)


def _write_minimal_pptx(path, slide_texts: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        for i, text in enumerate(slide_texts, start=1):
            xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                f'<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>'
                "</p:spTree></p:cSld></p:sld>"
            )
            zf.writestr(f"ppt/slides/slide{i}.xml", xml)


if __name__ == "__main__":
    unittest.main()
