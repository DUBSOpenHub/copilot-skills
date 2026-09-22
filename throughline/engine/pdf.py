"""Accessible PDF export: LibreOffice headless first, a real stdlib-only
PDF composer as the always-available fallback (ARCH §2, §10). Which path
ran is recorded as an advisory flag on the result, never silently
substituted (ARCH §12 `PDF_FALLBACK_USED`).
"""
from __future__ import annotations

import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import models

PAGE_W, PAGE_H = 612, 792  # US Letter, points
MARGIN = 54
LINE_HEIGHT = 16
FONT_SIZE = 11
TITLE_FONT_SIZE = 16
WRAP_CHARS = 84


@dataclass
class PdfExportResult:
    pdf_bytes: bytes
    used_fallback: bool
    soffice_path: Optional[str] = None


def find_soffice() -> Optional[str]:
    return shutil.which("soffice") or shutil.which("libreoffice")


def export_via_soffice(pptx_path: Path, out_dir: Path, soffice_bin: str, timeout: int = 90) -> bytes:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice_bin, "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(out_dir), str(pptx_path)],
        check=True, timeout=timeout, capture_output=True,
    )
    candidate = out_dir / (pptx_path.stem + ".pdf")
    if not candidate.exists():
        raise RuntimeError(f"soffice did not produce the expected output at {candidate}")
    return candidate.read_bytes()


# ---------------------------------------------------------------------------
# Stdlib fallback composer — a genuine, minimal, valid PDF writer (no
# third-party dependency). One page per slide; text is written in the
# slide's own `readingOrder`, so reading order is faithfully preserved even
# though visual fidelity is intentionally low.
# ---------------------------------------------------------------------------

REGION_LABELS = {
    "headline": "Headline", "visual": "Visual", "body": "Claims",
    "notes.spoken": "Speaker notes", "notes.transitionIn": "Transition in",
    "notes.transitionOut": "Transition out", "notes.timeBudget": "Time budget",
    "notes.fallback": "Fallback", "notes.sources": "Sources",
}


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", "").encode("latin-1", errors="replace").decode("latin-1")


def _wrap(text: str, width: int = WRAP_CHARS) -> list[str]:
    out: list[str] = []
    for paragraph in (text or "").split("\n"):
        if not paragraph.strip():
            out.append("")
            continue
        out.extend(textwrap.wrap(paragraph, width) or [""])
    return out


def _slide_page_lines(slide: models.SlideSpec) -> list[tuple[str, int]]:
    """Returns [(line_text, font_size)] for one slide, in `readingOrder`."""
    lines: list[tuple[str, int]] = [(f"Slide {slide.order + 1} - {slide.role}", TITLE_FONT_SIZE), ("", FONT_SIZE)]
    order = slide.reading_order or list(slide.regions.keys())
    for role in order:
        region = slide.regions.get(role)
        if region is None:
            continue
        label = "Context" if (role == "body" and slide.layout == "hook") else REGION_LABELS.get(role, role)
        if role == "headline":
            for wl in _wrap(region.text, WRAP_CHARS):
                lines.append((wl, TITLE_FONT_SIZE if wl else FONT_SIZE))
            lines.append(("", FONT_SIZE))
            continue
        if not region.text and not region.alt_text:
            continue
        lines.append((f"{label}:", FONT_SIZE))
        for wl in _wrap(region.text):
            lines.append((f"  {wl}" if wl else "", FONT_SIZE))
        if region.alt_text:
            lines.append((f"  [Alt text: {region.alt_text}]", FONT_SIZE))
        lines.append(("", FONT_SIZE))
    if slide.is_demo and slide.demo_asset:
        lines.append(("Demo fallback paths:", FONT_SIZE))
        lines.append((f"  Live: {slide.demo_asset.live_path or '(none)'}", FONT_SIZE))
        lines.append((f"  Prerecorded: {slide.demo_asset.prerecorded_asset_path or '(none)'}", FONT_SIZE))
        lines.append((f"  Static: {slide.demo_asset.static_asset_path or '(none)'}", FONT_SIZE))
        lines.append((f"  Verbal recovery: {slide.demo_asset.verbal_recovery_script or '(none)'}", FONT_SIZE))
    return lines


def _paginate(lines: list[tuple[str, int]]) -> list[list[tuple[str, int]]]:
    usable_height = PAGE_H - 2 * MARGIN
    max_lines_per_page = usable_height // LINE_HEIGHT
    pages = []
    for i in range(0, len(lines), max_lines_per_page):
        pages.append(lines[i:i + max_lines_per_page])
    return pages or [[]]


def compose_fallback_pdf(
    slides: list[models.SlideSpec], workspace_id: str, deck_id: str, manifest_id: str, title: str,
) -> bytes:
    ordered = sorted(slides, key=lambda s: s.order)
    all_pages: list[list[tuple[str, int]]] = []
    for slide in ordered:
        all_pages.extend(_paginate(_slide_page_lines(slide)))

    objects: list[bytes] = [b""]  # 1-indexed; index 0 unused
    catalog_num = 1
    pages_num = 2
    font_num = 3
    objects.append(b"")  # placeholder for catalog (filled below)
    objects.append(b"")  # placeholder for pages
    objects.append(f"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>".encode("latin-1"))

    page_obj_nums = []
    next_obj = 4
    page_content_pairs = []
    for page_lines in all_pages:
        page_obj_num = next_obj
        content_obj_num = next_obj + 1
        next_obj += 2
        page_obj_nums.append(page_obj_num)
        page_content_pairs.append((page_obj_num, content_obj_num, page_lines))

    for page_obj_num, content_obj_num, page_lines in page_content_pairs:
        stream_lines = ["BT", f"/F1 {FONT_SIZE} Tf"]
        y = PAGE_H - MARGIN
        stream_lines.append(f"1 0 0 1 {MARGIN} {y} Tm")
        prev_size = None
        for text, size in page_lines:
            if prev_size != size:
                stream_lines.append(f"/F1 {size} Tf")
                prev_size = size
            stream_lines.append(f"({_pdf_escape(text)}) Tj")
            stream_lines.append(f"0 -{LINE_HEIGHT} Td")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
        content_obj = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"
        )
        while len(objects) <= content_obj_num:
            objects.append(b"")
        objects[content_obj_num] = content_obj
        page_obj = (
            f"<< /Type /Page /Parent {pages_num} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 {font_num} 0 R >> >> /Contents {content_obj_num} 0 R >>"
        ).encode("latin-1")
        while len(objects) <= page_obj_num:
            objects.append(b"")
        objects[page_obj_num] = page_obj

    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects[pages_num] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_obj_nums)} >>".encode("latin-1")
    objects[catalog_num] = f"<< /Type /Catalog /Pages {pages_num} 0 R >>".encode("latin-1")

    info_num = next_obj
    next_obj += 1
    info_dict = (
        f"<< /Title ({_pdf_escape(title)}) /Producer (GitHub Copilot Throughline) "
        f"/ThroughlineWorkspaceId ({_pdf_escape(workspace_id)}) "
        f"/ThroughlineDeckId ({_pdf_escape(deck_id)}) "
        f"/ThroughlineManifestId ({_pdf_escape(manifest_id)}) >>"
    ).encode("latin-1")
    while len(objects) <= info_num:
        objects.append(b"")
    objects[info_num] = info_dict

    buf = bytearray()
    buf += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0] * len(objects)
    for i in range(1, len(objects)):
        if not objects[i]:
            continue
        offsets[i] = len(buf)
        buf += f"{i} 0 obj\n".encode("latin-1")
        buf += objects[i]
        buf += b"\nendobj\n"

    xref_offset = len(buf)
    real_count = len(objects)
    buf += f"xref\n0 {real_count}\n".encode("latin-1")
    buf += b"0000000000 65535 f \n"
    for i in range(1, real_count):
        buf += f"{offsets[i]:010d} 00000 n \n".encode("latin-1")
    buf += (
        f"trailer\n<< /Size {real_count} /Root {catalog_num} 0 R /Info {info_num} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    ).encode("latin-1")
    return bytes(buf)


def export_accessible_pdf(
    slides: list[models.SlideSpec], workspace_id: str, deck_id: str, manifest_id: str, title: str,
    pptx_path: Optional[Path] = None, work_dir: Optional[Path] = None,
) -> PdfExportResult:
    soffice_bin = find_soffice()
    if soffice_bin and pptx_path is not None and work_dir is not None:
        try:
            pdf_bytes = export_via_soffice(pptx_path, work_dir, soffice_bin)
            return PdfExportResult(pdf_bytes=pdf_bytes, used_fallback=False, soffice_path=soffice_bin)
        except (subprocess.SubprocessError, RuntimeError, OSError):
            pass  # fall through to the stdlib composer — never a silent failure, an ADVISORY is attached by the caller
    pdf_bytes = compose_fallback_pdf(slides, workspace_id, deck_id, manifest_id, title)
    return PdfExportResult(pdf_bytes=pdf_bytes, used_fallback=True, soffice_path=None)
