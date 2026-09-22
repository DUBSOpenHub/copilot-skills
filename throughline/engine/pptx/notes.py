"""Structured native-notes template: the fixed, labeled section layout
written into every slide's notes text frame, and the matching parser used
by `reimport.py` to recover each notes region from raw notes text (ARCH
§9's "Notes-region parsing uses the same fixed labels ... as anchors").

There are exactly six notes regions, in a fixed order: the unlabeled
spoken talk track first, then four/five labeled lines. Labels are the
*only* thing reimport can anchor on, so they are treated as load-bearing
constants — never localized or reworded without updating the parser here
too.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

from .. import models

NOTES_ORDER = (
    "notes.spoken", "notes.transitionIn", "notes.transitionOut",
    "notes.timeBudget", "notes.fallback", "notes.sources",
)
NOTES_LABELS = {
    "notes.transitionIn": "Transition in:",
    "notes.transitionOut": "Transition out:",
    "notes.timeBudget": "Time budget:",
    "notes.fallback": "Fallback:",
    "notes.sources": "Sources:",
}
LABELED_ROLES = tuple(NOTES_LABELS.keys())


def _paragraph_xml(label: str | None, value: str) -> str:
    value = value or ""
    if label:
        return (
            f'<a:p><a:r><a:rPr lang="en-US" b="1" dirty="0"/><a:t>{escape(label)} </a:t></a:r>'
            f'<a:r><a:rPr lang="en-US" dirty="0"/><a:t>{escape(value)}</a:t></a:r></a:p>'
        )
    lines = value.split("\n") or [""]
    out = []
    for line in lines:
        if line:
            out.append(f'<a:p><a:r><a:rPr lang="en-US" dirty="0"/><a:t>{escape(line)}</a:t></a:r></a:p>')
        else:
            out.append('<a:p><a:endParaRPr lang="en-US" dirty="0"/></a:p>')
    return "".join(out)


def render_notes_body_xml(slide: models.SlideSpec) -> str:
    """The exact paragraph sequence written into a slide's notes text
    frame: talk track first (unlabeled, may be multi-paragraph), then one
    labeled line per remaining notes region, always present (even if the
    value is empty) so every anchor is reliably findable on reimport."""
    paras = [_paragraph_xml(None, slide.regions["notes.spoken"].text)]
    for role in NOTES_ORDER[1:]:
        paras.append(_paragraph_xml(NOTES_LABELS[role], slide.regions[role].text))
    return "".join(paras)


def plain_text_notes(slide: models.SlideSpec) -> str:
    """Plain-text rendering of the same structure, used by
    `package.py` for the human-readable `speaker-notes.md` companion
    artifact (ARCH §10)."""
    lines = [slide.regions["notes.spoken"].text]
    for role in NOTES_ORDER[1:]:
        lines.append(f"{NOTES_LABELS[role]} {slide.regions[role].text}")
    return "\n".join(lines)


def parse_notes_text(raw_text: str) -> dict[str, str]:
    """Inverse of `render_notes_body_xml`/`plain_text_notes`: given the
    full text of a notes shape (as read back out of a `.pptx`, one
    paragraph per line), recover `{role: value}` for every notes region by
    anchoring on the fixed labels. Everything before the first recognized
    label is treated as `notes.spoken`. A label whose line is missing
    entirely is simply absent from the result (caller decides whether that
    counts as an unmatched/edited region)."""
    lines = raw_text.split("\n")
    result: dict[str, str] = {}
    spoken_lines: list[str] = []
    current_role: str | None = None
    current_value: list[str] = []

    def _flush():
        if current_role is not None:
            result[current_role] = "\n".join(current_value).strip()

    for line in lines:
        matched_role = None
        for role, label in NOTES_LABELS.items():
            if line.strip().startswith(label):
                matched_role = role
                remainder = line.strip()[len(label):].strip()
                break
        if matched_role is not None:
            _flush()
            current_role = matched_role
            current_value = [remainder]
        elif current_role is not None:
            current_value.append(line)
        else:
            spoken_lines.append(line)
    _flush()
    result["notes.spoken"] = "\n".join(spoken_lines).strip()
    return result
