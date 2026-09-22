#!/usr/bin/env python3
"""Builds `assets/template.pptx`: the one bundled, versioned
"throughline-standard-v1" template asset (ARCH §16.4), rendered with the
same `engine.pptx.ooxml_engine` code the real Engine uses for every export
— so this shipped, inspectable file is guaranteed structurally identical
(same master/layouts/theme/notes-master) to what a real talk's deck.pptx
contains. It ships with two example slides (one per layout) purely so a
human can open it in PowerPoint and see the template; the Engine's actual
export path never reads this file at runtime (see docs/template-spec.md
for the disclosed reasoning).

Run this script only when the template design changes:
    python3 scripts/build_template_asset.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine import models  # noqa: E402
from engine.pptx import ooxml_engine  # noqa: E402


def _region(role: str, text: str, claim_ids=None) -> models.Region:
    return models.Region(role=role, text=text, content_hash=ooxml_engine.sha256_hex(text), claim_ids=claim_ids or [])


def build_example_slides(workspace_id: str, deck_id: str) -> list[models.SlideSpec]:
    hook_regions = {
        "headline": _region("headline", "This is the Hook/Title layout"),
        "body": _region("body", "One-line subhead establishes context before the story begins."),
        "notes.spoken": _region("notes.spoken", "Open cold with a concrete number or a vivid scene."),
        "notes.transitionIn": _region("notes.transitionIn", ""),
        "notes.transitionOut": _region("notes.transitionOut", "Pause, then name the stakes."),
        "notes.timeBudget": _region("notes.timeBudget", "45"),
        "notes.fallback": _region("notes.fallback", "If cut for time, state the headline verbally and move on."),
        "notes.sources": _region("notes.sources", "template-spec"),
    }
    hook_slide = models.SlideSpec(
        id=models.slide_id(deck_id, 0), workspace_id=workspace_id, deck_id=deck_id, beat_id="beat:example-hook",
        order=0, role="HOOK", layout="hook", regions=hook_regions, reading_order=list(hook_regions.keys()),
    )

    standard_regions = {
        "headline": _region("headline", "This is the Standard Beat layout"),
        "visual": _region("visual", "Primary visual placeholder — a chart, screenshot, or diagram."),
        "body": _region("body", "- [GOAL] Example aspirational claim bullet\n- Example factual claim bullet (\u22643 per slide)", claim_ids=["claim:example"]),
        "notes.spoken": _region("notes.spoken", "Walk through the mechanism in plain language."),
        "notes.transitionIn": _region("notes.transitionIn", "Building on the hook,"),
        "notes.transitionOut": _region("notes.transitionOut", "Which brings us to the proof."),
        "notes.timeBudget": _region("notes.timeBudget", "90"),
        "notes.fallback": _region("notes.fallback", "If cut for time, summarize the headline verbally in one sentence."),
        "notes.sources": _region("notes.sources", "template-spec"),
    }
    standard_slide = models.SlideSpec(
        id=models.slide_id(deck_id, 1), workspace_id=workspace_id, deck_id=deck_id, beat_id="beat:example-standard",
        order=1, role="MECHANISM", layout="standard", regions=standard_regions, reading_order=list(standard_regions.keys()),
    )
    return [hook_slide, standard_slide]


def main() -> None:
    workspace_id = "workspace:template-example"
    deck_id = models.deck_id(workspace_id)
    slides = build_example_slides(workspace_id, deck_id)
    result = ooxml_engine.export_pptx(
        slides, workspace_id, deck_id, manifest_id="manifest:template-example",
        actor="GitHub Copilot Throughline", created_iso=models.now_iso(),
    )
    out_path = REPO_ROOT / "assets" / "template.pptx"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(result.pptx_bytes)
    print(f"Wrote {out_path} ({len(result.pptx_bytes)} bytes, {len(slides)} example slides)")


if __name__ == "__main__":
    main()
