"""Format-specific text extraction for locally uploaded documents.

Every function here is a genuine, stdlib-only parser — never a stub that
fabricates content. When a format cannot be extracted with confidence
(e.g. an image with no text layer, or a PDF encoding this parser does not
understand), the function returns an honest empty/partial result and the
caller (ingest.py) decides whether that is acceptable (images) or a
`PARSE_FAILED` condition (documents expected to contain text).

Supported, and why each is feasible without third-party packages:
- `.txt/.md/.vtt/.srt` — already plain text; UTF-8 decode only.
- `.docx/.pptx/.xlsx` — OOXML zip packages; `zipfile` + `xml.etree` extract
  every text run deterministically.
- `.csv` — stdlib `csv` module.
- `.json` — stdlib `json` module (also validates well-formedness).
- `.eml` — stdlib `email` module (RFC 822 parsing); extracts the
  Subject/From/To headers plus the best available text body part.
- `.pdf` — best-effort: stdlib `zlib` inflates `FlateDecode` streams, then a
  regex over `Tj`/`TJ` text-showing operators between `BT`/`ET` blocks
  recovers visible text. This handles the common case (simple, single-byte
  encoded, Flate-compressed content streams) and will not perfectly handle
  every PDF (embedded CID fonts, JBIG2 images, encrypted PDFs). That limit
  is intentional and documented rather than hidden: an unrecoverable PDF
  yields empty text and the ingest layer reports `PARSE_FAILED`.
- Images (`.png/.jpg/.jpeg/.gif`) — no OCR is attempted; callers should
  treat empty text as expected, not a failure.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zlib
from email import message_from_bytes, policy
from xml.etree import ElementTree as ET
import zipfile

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DRAWING_TEXT_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
SPREADSHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


class ParseError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def extract_plain_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def extract_csv_text(raw: bytes) -> str:
    text = extract_plain_text(raw)
    try:
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    except csv.Error as exc:
        raise ParseError(f"invalid CSV: {exc}") from exc
    lines = [", ".join(cell for cell in row) for row in rows]
    return "\n".join(lines)


def extract_json_text(raw: bytes) -> str:
    text = extract_plain_text(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc}") from exc
    return json.dumps(parsed, indent=2, sort_keys=True)


def extract_eml_text(raw: bytes) -> str:
    """RFC 822 email export (locally uploaded `.eml`, distinct from a
    live WorkIQ Outlook message): Subject/From/To headers plus the best
    available text body part, via the stdlib `email` module only."""
    try:
        msg = message_from_bytes(raw, policy=policy.default)
    except Exception as exc:  # stdlib parser is lenient; still guard it
        raise ParseError(f"invalid EML message: {exc}") from exc
    header_lines = [
        f"{name}: {msg.get(name)}" for name in ("Subject", "From", "To", "Date") if msg.get(name)
    ]
    body = ""
    try:
        body_part = msg.get_body(preferencelist=("plain", "html"))
    except AttributeError:
        body_part = None  # legacy Message instances (no get_body)
    if body_part is not None:
        content = body_part.get_content()
        body = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
    elif msg.get_payload():
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")
    return "\n".join([*header_lines, "", body.strip()]).strip()


def extract_docx_text(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            with zf.open("word/document.xml") as fh:
                tree = ET.parse(fh)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ParseError(f"invalid DOCX package: {exc}") from exc
    return _join_docx_paragraphs(tree)


def _join_docx_paragraphs(tree) -> str:
    paragraphs = []
    for p in tree.getroot().iter(f"{WORD_NS}p"):
        runs = [t.text or "" for t in p.iter(f"{WORD_NS}t")]
        paragraphs.append("".join(runs))
    return "\n".join(paragraphs)


def extract_pptx_text(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            slide_names = sorted(
                n for n in zf.namelist()
                if re.match(r"ppt/slides/slide\d+\.xml$", n)
            )
            if not slide_names:
                raise ParseError("no slides found in PPTX package")
            slide_names.sort(key=lambda n: int(re.search(r"(\d+)", n).group(1)))
            texts = []
            for name in slide_names:
                with zf.open(name) as fh:
                    tree = ET.parse(fh)
                runs = [t.text or "" for t in tree.getroot().iter(f"{DRAWING_TEXT_NS}t")]
                texts.append(" ".join(r for r in runs if r))
    except zipfile.BadZipFile as exc:
        raise ParseError(f"invalid PPTX package: {exc}") from exc
    return "\n".join(texts)


def extract_xlsx_text(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            shared_strings = []
            if "xl/sharedStrings.xml" in zf.namelist():
                with zf.open("xl/sharedStrings.xml") as fh:
                    tree = ET.parse(fh)
                for si in tree.getroot().iter(f"{SPREADSHEET_NS}si"):
                    texts = [t.text or "" for t in si.iter(f"{SPREADSHEET_NS}t")]
                    shared_strings.append("".join(texts))
            sheet_names = sorted(
                n for n in zf.namelist()
                if re.match(r"xl/worksheets/sheet\d+\.xml$", n)
            )
            lines = []
            for name in sheet_names:
                with zf.open(name) as fh:
                    tree = ET.parse(fh)
                for c in tree.getroot().iter(f"{SPREADSHEET_NS}c"):
                    v = c.find(f"{SPREADSHEET_NS}v")
                    if v is None or v.text is None:
                        continue
                    if c.get("t") == "s":
                        idx = int(v.text)
                        if 0 <= idx < len(shared_strings):
                            lines.append(shared_strings[idx])
                    else:
                        lines.append(v.text)
    except zipfile.BadZipFile as exc:
        raise ParseError(f"invalid XLSX package: {exc}") from exc
    return "\n".join(lines)


_PDF_STREAM_RE = re.compile(rb"stream\r?\n(.*?)endstream", re.DOTALL)
_PDF_TEXT_OP_RE = re.compile(rb"\((?:[^()\\]|\\.)*\)|\[(?:[^\[\]]|\\.)*\]")


def extract_pdf_text(raw: bytes) -> str:
    """Best-effort PDF text extraction (see module docstring for scope)."""
    texts: list[str] = []
    for match in _PDF_STREAM_RE.finditer(raw):
        stream_bytes = match.group(1)
        decoded = None
        try:
            decoded = zlib.decompress(stream_bytes)
        except zlib.error:
            decoded = stream_bytes  # possibly already-plain content stream
        if b"BT" not in decoded or b"ET" not in decoded:
            continue
        for block in re.findall(rb"BT(.*?)ET", decoded, re.DOTALL):
            for token in _PDF_TEXT_OP_RE.finditer(block):
                literal = token.group(0)
                if literal.startswith(b"("):
                    inner = literal[1:-1]
                    inner = inner.replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\", b"\\")
                    try:
                        texts.append(inner.decode("latin-1"))
                    except UnicodeDecodeError:
                        pass
    joined = " ".join(t for t in texts if t.strip())
    return joined.strip()


EXTRACTORS = {
    ".txt": extract_plain_text,
    ".md": extract_plain_text,
    ".vtt": extract_plain_text,
    ".srt": extract_plain_text,
    ".csv": extract_csv_text,
    ".json": extract_json_text,
    ".eml": extract_eml_text,
    ".docx": extract_docx_text,
    ".pptx": extract_pptx_text,
    ".xlsx": extract_xlsx_text,
    ".pdf": extract_pdf_text,
}

NO_TEXT_EXPECTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif"}


def extract_text(extension: str, raw: bytes) -> str:
    ext = extension.lower()
    extractor = EXTRACTORS.get(ext)
    if extractor is None:
        if ext in NO_TEXT_EXPECTED_EXTENSIONS:
            return ""
        raise ParseError(f"no extractor registered for '{ext}'")
    return extractor(raw)
