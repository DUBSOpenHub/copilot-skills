"""Artifact Package Contract (ARCH §10, FR-DEL-6, NFR-7).

`export_package` assembles the full 9-artifact stage package plus
`manifest.json` under `exports/<workspaceId>/<exportedAt>/`, all sharing
one `workspaceId`/`deckId`/`manifestId` identity — stamped redundantly
into the `.pptx` custom properties, the PDF metadata, and every text
artifact's manifest entry, not just the JSON manifest itself.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from . import gates, models, persistence, restore, strings
from . import pdf as pdf_mod
from .errors import Advisory, EngineError
from .pptx import notes as notes_mod
from .pptx import ooxml_engine

ARTIFACT_KINDS = [
    "EDITABLE_DECK", "SPEAKER_NOTES_DOC", "ACCESSIBLE_PDF", "EVIDENCE_APPROVAL_MANIFEST",
    "CAPTION_SCRIPT", "DEMO_ASSETS", "OFFLINE_BACKUP", "PANIC_DECK", "LAST_KNOWN_GOOD",
]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _vtt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def build_captions_vtt(slides: list[models.SlideSpec]) -> str:
    """CAPTION_SCRIPT: derived from each slide's spoken talk track and
    numeric time budget (ARCH §10) — a WebVTT cue per slide, cumulative."""
    lines = ["WEBVTT", ""]
    t = 0.0
    for slide in sorted(slides, key=lambda s: s.order):
        talk = slide.regions["notes.spoken"].text or "(no spoken content authored for this beat)"
        try:
            duration = float(slide.regions["notes.timeBudget"].text)
        except (KeyError, ValueError):
            duration = 60.0
        start, end = t, t + max(duration, 1.0)
        lines.append(f"{_vtt_timestamp(start)} --> {_vtt_timestamp(end)}")
        lines.append(talk)
        lines.append("")
        t = end
    return "\n".join(lines)


def build_evidence_approval_manifest(conn, workspace_id: str) -> dict:
    sources = persistence.list_all(conn, "source", workspace_id, models.SourceArtifact)
    atoms = persistence.list_all(conn, "evidence", workspace_id, models.EvidenceAtom)
    claims_ = persistence.list_all(conn, "claim", workspace_id, models.Claim)
    conflicts = persistence.list_all(conn, "conflict", workspace_id, models.ConflictCard)
    approvals = persistence.list_all(conn, "approval", workspace_id, models.ApprovalRecord)
    gate_results = gates.gate_status(conn, workspace_id)
    return {
        "sources": [models.to_jsonable(s) for s in sources],
        "evidenceAtoms": [models.to_jsonable(a) for a in atoms],
        "claims": [models.to_jsonable(c) for c in claims_],
        "conflicts": [models.to_jsonable(c) for c in conflicts],
        "approvals": [models.to_jsonable(a) for a in approvals],
        "gateResults": [models.to_jsonable(g) for g in gate_results],
    }


def build_speaker_notes_md(slides: list[models.SlideSpec]) -> str:
    parts = []
    for slide in sorted(slides, key=lambda s: s.order):
        parts.append(f"## Slide {slide.order + 1} \u2014 {slide.regions['headline'].text}")
        parts.append("")
        parts.append(notes_mod.plain_text_notes(slide))
        parts.append("")
    return "\n".join(parts)


def _find_last_known_good(exports_root: Path, current_export_dir: Path) -> Optional[Path]:
    if not exports_root.exists():
        return None
    candidates = []
    for d in sorted(exports_root.iterdir()):
        if not d.is_dir() or d == current_export_dir or d.name == "draft":
            continue
        manifest_path, deck_path = d / "manifest.json", d / "deck.pptx"
        if manifest_path.exists() and deck_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
            except json.JSONDecodeError:
                continue
            if any(g.get("gate") == "STAGE" and g.get("passed") for g in manifest.get("gateResults", [])):
                candidates.append(d)
    if not candidates:
        return None
    candidates.sort(key=lambda d: d.name)
    return candidates[-1] / "deck.pptx"


def export_pptx_draft(conn, workspace_id: str, actor: str, render_mode: str = "normal") -> dict:
    """`export pptx` — a standalone draft render, usable any time after
    `compile`, independent of the full 9-artifact package/Stage gate."""
    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    if ws is None:
        raise EngineError("NOT_FOUND", f"workspace '{workspace_id}' not found", {})
    slides = persistence.list_all(conn, "slide", workspace_id, models.SlideSpec)
    if not slides:
        raise EngineError("VALIDATION_ERROR", "no compiled slides exist yet; run 'compile' first", {})
    deck_id = ws.deck_id or models.deck_id(workspace_id)
    manifest_id = ws.manifest_id or "manifest:draft"
    exported_at = models.now_iso()
    result = ooxml_engine.export_pptx(slides, workspace_id, deck_id, manifest_id, actor, exported_at, render_mode=render_mode)

    # Self-check: the bytes we just produced must themselves open as a
    # well-formed zip with the mandatory OPC part present — never trust
    # blindly (an INTERNAL_ERROR here means a genuine Engine bug, not a
    # user-facing blocked state).
    import io
    import zipfile as _zf
    with _zf.ZipFile(io.BytesIO(result.pptx_bytes)) as zf:
        bad = zf.testzip()
        if bad is not None or "[Content_Types].xml" not in zf.namelist():
            raise EngineError("INTERNAL_ERROR", "generated .pptx failed self-validation", {"badEntry": bad})

    workspace_dir = persistence.workspace_dir_from_conn(conn)
    draft_dir = workspace_dir / "exports" / "draft"
    draft_dir.mkdir(parents=True, exist_ok=True)
    filename = "deck.pptx" if render_mode == "normal" else "panic-deck.pptx"
    out_path = draft_dir / filename
    out_path.write_bytes(result.pptx_bytes)

    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="export.pptx_draft", subject_type="workspace", subject_id=workspace_id,
        details={"path": str(out_path), "renderMode": render_mode},
    )
    persistence.append_audit(conn, audit)
    return {"path": str(out_path), "deckId": deck_id, "regionCount": len(result.manifest)}


def export_package(conn, workspace_id: str, actor: str, export_dir_override: Optional[Path] = None) -> dict:
    """`export_dir_override`, if given, is used verbatim as the directory
    the package's files are written into (used by `scenario.run_scenario`'s
    `--export-dir`), instead of the default `<workspace_dir>/exports/<stamp>`
    location. `LAST_KNOWN_GOOD` lookup (below) is unaffected either way: it
    always scans this *workspace's own* default exports directory for a
    prior Stage-passed package, independent of where *this* export lands."""
    ws = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    if ws is None:
        raise EngineError("NOT_FOUND", f"workspace '{workspace_id}' not found", {})

    stage_result = gates.run_gate(conn, workspace_id, "stage", actor)
    if not stage_result.passed:
        raise EngineError(
            "GATE_NOT_PASSED",
            "Stage approval has not passed; package export is refused ("
            + "; ".join(f.message for f in stage_result.failed_checks) + ")",
            {"failedChecks": [models.to_jsonable(f) for f in stage_result.failed_checks]},
        )

    slides = persistence.list_all(conn, "slide", workspace_id, models.SlideSpec)
    deck_id = ws.deck_id or models.deck_id(workspace_id)
    manifest_id = models.new_id("manifest")
    exported_at = models.now_iso()
    stamp = exported_at.replace(":", "").replace("-", "") + "-" + uuid.uuid4().hex[:8]

    workspace_dir = persistence.workspace_dir_from_conn(conn)
    exports_root = workspace_dir / "exports"
    export_dir = Path(export_dir_override) if export_dir_override is not None else exports_root / stamp
    export_dir.mkdir(parents=True, exist_ok=True)
    demo_dir = export_dir / "demo"
    demo_dir.mkdir(exist_ok=True)

    advisories: list[dict] = []
    artifacts: list[tuple[str, Path]] = []

    deck_result = ooxml_engine.export_pptx(slides, workspace_id, deck_id, manifest_id, actor, exported_at, render_mode="normal")
    deck_path = export_dir / "deck.pptx"
    deck_path.write_bytes(deck_result.pptx_bytes)
    artifacts.append(("EDITABLE_DECK", deck_path))

    panic_result = ooxml_engine.export_pptx(slides, workspace_id, deck_id, manifest_id, actor, exported_at, render_mode="panic")
    panic_path = export_dir / "panic-deck.pptx"
    panic_path.write_bytes(panic_result.pptx_bytes)
    artifacts.append(("PANIC_DECK", panic_path))

    notes_path = export_dir / "speaker-notes.md"
    notes_path.write_text(build_speaker_notes_md(slides))
    artifacts.append(("SPEAKER_NOTES_DOC", notes_path))

    pdf_result = pdf_mod.export_accessible_pdf(
        slides, workspace_id, deck_id, manifest_id,
        title=f"GitHub Copilot Throughline deck {deck_id}",
        pptx_path=deck_path, work_dir=export_dir,
    )
    pdf_path = export_dir / "deck-accessible.pdf"
    pdf_path.write_bytes(pdf_result.pdf_bytes)
    artifacts.append(("ACCESSIBLE_PDF", pdf_path))
    if pdf_result.used_fallback:
        advisories.append(Advisory("PDF_FALLBACK_USED", strings.PDF_FALLBACK_USED).to_dict())

    manifest_json_path = export_dir / "evidence-approval-manifest.json"
    manifest_json_path.write_text(json.dumps(build_evidence_approval_manifest(conn, workspace_id), indent=2))
    artifacts.append(("EVIDENCE_APPROVAL_MANIFEST", manifest_json_path))

    captions_path = export_dir / "captions.vtt"
    captions_path.write_text(build_captions_vtt(slides))
    artifacts.append(("CAPTION_SCRIPT", captions_path))

    for slide in slides:
        if not slide.is_demo or slide.demo_asset is None:
            continue
        slide_demo_dir = demo_dir / slide.id.replace(":", "_")
        slide_demo_dir.mkdir(parents=True, exist_ok=True)
        for attr in ("prerecorded_asset_path", "static_asset_path"):
            src = getattr(slide.demo_asset, attr)
            if not src:
                continue
            src_path = Path(src)
            if src_path.exists():
                shutil.copy2(src_path, slide_demo_dir / src_path.name)
            else:
                advisories.append(Advisory(
                    "DEMO_ASSET_MISSING",
                    strings.DEMO_ASSET_MISSING.format(path=src, slide_id=slide.id),
                    {"slideId": slide.id, "path": src},
                ).to_dict())
        if slide.demo_asset.verbal_recovery_script:
            (slide_demo_dir / "verbal-recovery.txt").write_text(slide.demo_asset.verbal_recovery_script)
    artifacts.append(("DEMO_ASSETS", demo_dir))

    lkg_source = _find_last_known_good(exports_root, export_dir)
    if lkg_source is not None:
        lkg_path = export_dir / "last-known-good.pptx"
        shutil.copy2(lkg_source, lkg_path)
        artifacts.append(("LAST_KNOWN_GOOD", lkg_path))
    else:
        advisories.append(Advisory("NO_LKG_AVAILABLE", strings.NO_LKG_AVAILABLE).to_dict())

    gate_results = [models.to_jsonable(g) for g in gates.gate_status(conn, workspace_id)]
    approvals = [models.to_jsonable(a) for a in persistence.list_all(conn, "approval", workspace_id, models.ApprovalRecord)]

    manifest_entries = []
    for kind, path in artifacts:
        rel = path.relative_to(export_dir)
        manifest_entries.append({
            "kind": kind, "relPath": str(rel),
            "sha256": None if path.is_dir() else _sha256_file(path),
        })

    manifest_doc = {
        "workspaceId": workspace_id, "deckId": deck_id, "manifestId": manifest_id,
        "templateId": ooxml_engine.TEMPLATE_ID, "exportedAt": exported_at, "exportedBy": actor,
        "artifacts": manifest_entries, "gateResults": gate_results, "approvalRecords": approvals,
        "advisories": advisories,
    }
    manifest_path = export_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_doc, indent=2))

    offline_zip_path = export_dir / "offline-backup.zip"
    with zipfile.ZipFile(offline_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(export_dir.rglob("*")):
            if p == offline_zip_path or p.is_dir():
                continue
            zf.write(p, p.relative_to(export_dir))
    manifest_entries.append({"kind": "OFFLINE_BACKUP", "relPath": "offline-backup.zip", "sha256": _sha256_file(offline_zip_path)})
    manifest_doc["artifacts"] = manifest_entries
    manifest_path.write_text(json.dumps(manifest_doc, indent=2))

    ws.manifest_id = manifest_id
    ws.phase = models.WorkspacePhase.PACKAGED.value
    ws.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="export.package", subject_type="workspace", subject_id=workspace_id,
        details={"manifestId": manifest_id, "exportDir": str(export_dir)},
    )
    persistence.commit(conn, "workspace", ws, audit)
    restore.create_restore_point(conn, workspace_id, trigger="export", actor=actor)

    return {
        "exportDir": str(export_dir), "manifestId": manifest_id, "deckId": deck_id,
        "manifest": manifest_doc, "advisories": advisories,
        "artifactKinds": sorted({k for k, _ in artifacts} | {"OFFLINE_BACKUP"}),
    }
