"""Re-import: diff-based recovery of user edits made directly in an
exported `.pptx` (ARCH §9, FR-PPT-6/7).

Resolution order for every text block found in the file, from strongest
to weakest evidence of identity:
1. **Shape name** — if it looks like one of our own `regionId`s
   (`deck:...:<order>:<role>`), trust it directly.
2. **Custom XML manifest** — if the name was stripped, but this exact
   text's hash still matches a known region's stored `contentHash`
   anywhere in the manifest, the text is unedited; that region's identity
   is recovered with full confidence (ARCH §9's stated fallback path).
3. **Position + placeholder type** — name stripped *and* content changed:
   the Nth slide in the file is matched to the Nth known slide (by beat
   order), then placeholder type (`title`/`pic`/`body`) selects the role.
   This is a best-effort heuristic, not a certainty — see ARCH §15's
   explicitly acknowledged open test about empirical PowerPoint fixtures.
4. **Unmatched** — none of the above resolves a regionId: the text is
   never discarded or auto-merged; it is reported for manual linking
   (FR-PPT-7).
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from . import notes as notes_mod
from . import ooxml_engine
from .. import models, persistence
from ..errors import EngineError

A_NS = ooxml_engine.NS["a"]
P_NS = ooxml_engine.NS["p"]


def sha256_hex(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class ObservedShape:
    slide_file_index: int
    shape_name: str
    ph_type: str | None
    text: str


@dataclass
class ResolvedRegion:
    slide_file_index: int
    region_id: str | None
    role: str | None
    text: str
    resolution: str  # "name" | "manifest" | "position" | "unmatched"


@dataclass
class PendingEditCandidate:
    region_id: str
    slide_id: str
    role: str
    old_text: str
    new_text: str
    old_hash: str
    new_hash: str
    resolution: str = "name"


@dataclass
class UnmatchedCandidate:
    slide_file_index: int
    text: str
    context: str


@dataclass
class ReimportReport:
    unchanged: list[str] = field(default_factory=list)
    pending_edits: list[PendingEditCandidate] = field(default_factory=list)
    unmatched: list[UnmatchedCandidate] = field(default_factory=list)


def _shape_text(sp_element: ET.Element) -> str:
    paragraphs = []
    for p in sp_element.findall(f".//{{{P_NS}}}txBody/{{{A_NS}}}p"):
        runs = [t.text or "" for t in p.findall(f"{{{A_NS}}}r/{{{A_NS}}}t")]
        paragraphs.append("".join(runs))
    return "\n".join(paragraphs)


def _extract_slide_shapes(slide_xml: bytes, slide_file_index: int) -> list[ObservedShape]:
    root = ET.fromstring(slide_xml)
    out = []
    for sp in root.findall(f".//{{{P_NS}}}sp"):
        cnvpr = sp.find(f"{{{P_NS}}}nvSpPr/{{{P_NS}}}cNvPr")
        name = cnvpr.get("name", "") if cnvpr is not None else ""
        ph = sp.find(f"{{{P_NS}}}nvSpPr/{{{P_NS}}}nvPr/{{{P_NS}}}ph")
        ph_type = ph.get("type") if ph is not None else None
        text = _shape_text(sp)
        out.append(ObservedShape(slide_file_index=slide_file_index, shape_name=name, ph_type=ph_type, text=text))
    return out


def _extract_notes_text(notes_xml: bytes) -> str | None:
    root = ET.fromstring(notes_xml)
    for sp in root.findall(f".//{{{P_NS}}}sp"):
        ph = sp.find(f"{{{P_NS}}}nvSpPr/{{{P_NS}}}nvPr/{{{P_NS}}}ph")
        if ph is not None and ph.get("type") == "body":
            return _shape_text(sp)
    return None


PLACEHOLDER_TO_ROLE = {"title": "headline", "ctrTitle": "headline", "pic": "visual", "body": "body"}


def parse_pptx(pptx_bytes: bytes) -> tuple[list[ObservedShape], dict[int, str]]:
    """Returns (shapes across all slides, {slide_file_index: notes_text})."""
    shapes: list[ObservedShape] = []
    notes_by_index: dict[int, str] = {}
    with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as zf:
        slide_names = sorted(
            (n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
            key=lambda n: int(re.search(r"(\d+)", n).group(1)),
        )
        for name in slide_names:
            idx = int(re.search(r"(\d+)", name).group(1))
            shapes.extend(_extract_slide_shapes(zf.read(name), idx))
            notes_name = f"ppt/notesSlides/notesSlide{idx}.xml"
            if notes_name in zf.namelist():
                text = _extract_notes_text(zf.read(notes_name))
                if text is not None:
                    notes_by_index[idx] = text
    return shapes, notes_by_index


def _positional_fallback(
    slide_file_index: int, ph_type: str | None,
    ordered_known_slide_ids: list[str],
) -> tuple[str | None, str | None]:
    """Best-effort: Nth slide in the file <-> Nth known slide by order,
    then placeholder type selects the role."""
    if slide_file_index - 1 >= len(ordered_known_slide_ids):
        return None, None
    role = PLACEHOLDER_TO_ROLE.get(ph_type or "")
    if role is None:
        return None, None
    return ordered_known_slide_ids[slide_file_index - 1], role


def resolve_and_diff(
    pptx_bytes: bytes,
    known_regions: dict[str, dict],
    ordered_known_slide_ids: list[str],
    manifest: dict[str, dict] | None = None,
) -> ReimportReport:
    """`known_regions`: {regionId: {"text":..., "contentHash":..., "claimIds":[...]}}
    sourced from the workspace's *current* persisted `SlideSpec`s.
    `manifest`: the customXml recovery manifest read from the same file
    (via `ooxml_engine.read_customxml_manifest`), used for tier 2 above."""
    manifest = manifest or {}
    hash_to_region = {info["contentHash"]: rid for rid, info in known_regions.items()}

    report = ReimportReport()
    shapes, notes_by_index = parse_pptx(pptx_bytes)

    for shape in shapes:
        if shape.ph_type == "ftr":
            continue  # cosmetic, derived footer — not a tracked region
        region_id = None
        role = None
        resolution = "unmatched"
        if shape.shape_name in known_regions:
            region_id = shape.shape_name
            role = region_id.rsplit(":", 1)[-1]
            resolution = "name"
        else:
            observed_hash = sha256_hex(shape.text)
            if observed_hash in hash_to_region:
                region_id = hash_to_region[observed_hash]
                role = region_id.rsplit(":", 1)[-1]
                resolution = "manifest"
            else:
                fallback_slide_id, fallback_role = _positional_fallback(shape.slide_file_index, shape.ph_type, ordered_known_slide_ids)
                if fallback_slide_id and fallback_role:
                    region_id = f"{fallback_slide_id}:{fallback_role}"
                    role = fallback_role
                    resolution = "position"

        if region_id is None or region_id not in known_regions:
            if shape.text.strip():
                report.unmatched.append(UnmatchedCandidate(
                    slide_file_index=shape.slide_file_index, text=shape.text,
                    context=f"shape name={shape.shape_name!r} phType={shape.ph_type!r}",
                ))
            continue

        known = known_regions[region_id]
        new_hash = sha256_hex(shape.text)
        if new_hash == known["contentHash"]:
            report.unchanged.append(region_id)
        else:
            report.pending_edits.append(PendingEditCandidate(
                region_id=region_id, slide_id=region_id.rsplit(":", 1)[0], role=role,
                old_text=known["text"], new_text=shape.text,
                old_hash=known["contentHash"], new_hash=new_hash, resolution=resolution,
            ))

    for slide_file_index, notes_text in notes_by_index.items():
        if slide_file_index - 1 >= len(ordered_known_slide_ids):
            continue
        slide_id = ordered_known_slide_ids[slide_file_index - 1]
        parsed = notes_mod.parse_notes_text(notes_text)
        for role, value in parsed.items():
            region_id = f"{slide_id}:{role}"
            if region_id not in known_regions:
                continue
            known = known_regions[region_id]
            new_hash = sha256_hex(value)
            if new_hash == known["contentHash"]:
                report.unchanged.append(region_id)
            else:
                report.pending_edits.append(PendingEditCandidate(
                    region_id=region_id, slide_id=slide_id, role=role,
                    old_text=known["text"], new_text=value,
                    old_hash=known["contentHash"], new_hash=new_hash,
                ))
    return report


# ---------------------------------------------------------------------------
# DB-aware orchestration (the `reimport pptx` / `reimport accept` CLI verbs)
# ---------------------------------------------------------------------------

def build_known_regions(conn, workspace_id: str) -> tuple[dict[str, dict], list[str]]:
    slides = sorted(persistence.list_all(conn, "slide", workspace_id, models.SlideSpec), key=lambda s: s.order)
    known_regions: dict[str, dict] = {}
    for slide in slides:
        for role, region in slide.regions.items():
            known_regions[f"{slide.id}:{role}"] = {
                "text": region.text, "contentHash": region.content_hash, "claimIds": list(region.claim_ids),
            }
    return known_regions, [s.id for s in slides]


def run_reimport(conn, workspace_id: str, pptx_bytes: bytes, actor: str, source_path: str = "<reimport>") -> dict:
    known_regions, ordered_ids = build_known_regions(conn, workspace_id)
    manifest = ooxml_engine.read_customxml_manifest(pptx_bytes)
    report = resolve_and_diff(pptx_bytes, known_regions, ordered_ids, manifest)

    writes = []
    audits = []
    pending_edits: list[models.PendingEdit] = []
    for cand in report.pending_edits:
        pe = models.PendingEdit(
            id=models.new_id("pendingedit"), workspace_id=workspace_id, slide_id=cand.slide_id,
            region_role=cand.role, region_id=cand.region_id, old_text=cand.old_text, new_text=cand.new_text,
            old_hash=cand.old_hash, new_hash=cand.new_hash,
            claim_ids=list(known_regions.get(cand.region_id, {}).get("claimIds", [])),
        )
        pending_edits.append(pe)
        writes.append(("pending_edit", pe))
        audits.append(models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="reimport.pending_edit", subject_type="pending_edit", subject_id=pe.id,
            details={"regionId": cand.region_id, "resolution": cand.resolution},
        ))

    unmatched_items: list[models.UnmatchedContentItem] = []
    for cand in report.unmatched:
        item = models.UnmatchedContentItem(
            id=models.new_id("unmatched"), workspace_id=workspace_id, source_pptx_path=source_path,
            text=cand.text, context=cand.context,
        )
        unmatched_items.append(item)
        writes.append(("unmatched_content", item))
        audits.append(models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="reimport.unmatched", subject_type="unmatched_content", subject_id=item.id, details={},
        ))

    if writes:
        persistence.commit_many(conn, writes, audits)
    else:
        persistence.append_audit(conn, models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="reimport.no_changes", subject_type="workspace", subject_id=workspace_id, details={},
        ))
    return {"unchanged": report.unchanged, "pendingEdits": pending_edits, "unmatched": unmatched_items}


def list_pending_edits(conn, workspace_id: str, status: str | None = "PENDING") -> list[models.PendingEdit]:
    items = persistence.list_all(conn, "pending_edit", workspace_id, models.PendingEdit)
    return [i for i in items if status is None or i.status == status]


def list_unmatched(conn, workspace_id: str) -> list[models.UnmatchedContentItem]:
    return persistence.list_all(conn, "unmatched_content", workspace_id, models.UnmatchedContentItem)


def accept_pending_edit(conn, workspace_id: str, pending_edit_id: str, actor: str) -> dict:
    pe = persistence.get(conn, "pending_edit", pending_edit_id, models.PendingEdit)
    if pe is None or pe.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"pending edit '{pending_edit_id}' not found", {"pendingEditId": pending_edit_id})
    if pe.status != "PENDING":
        raise EngineError("VALIDATION_ERROR", f"pending edit '{pending_edit_id}' is already {pe.status}", {})
    slide = persistence.get(conn, "slide", pe.slide_id, models.SlideSpec)
    if slide is None or pe.region_role not in slide.regions:
        raise EngineError("NOT_FOUND", f"slide/region for pending edit '{pending_edit_id}' no longer exists", {})

    region = slide.regions[pe.region_role]
    region.text = pe.new_text
    region.content_hash = pe.new_hash
    slide.updated_at = models.now_iso()

    pe.status = "ACCEPTED"
    pe.resolved_at = models.now_iso()

    # FR-PPT-6: a claim-bound region with exactly one linked claim gets its
    # canonical wording rewritten (via the normal, audited rewrite path),
    # which reopens it for re-validation. A region backing more than one
    # claim cannot be unambiguously attributed, so the slide is flagged for
    # manual review instead of guessing which claim changed.
    reopened_claim = None
    if pe.claim_ids:
        from .. import claims as claims_mod
        if len(pe.claim_ids) == 1:
            reopened_claim = claims_mod.rewrite_claim(conn, workspace_id, pe.claim_ids[0], pe.new_text, actor)
        else:
            slide.needs_review = True
            slide.needs_review_reason = (
                f"body text edited via reimport; {len(pe.claim_ids)} linked claims need manual review"
            )

    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="reimport.accept", subject_type="pending_edit", subject_id=pe.id,
        details={"regionId": pe.region_id},
    )
    persistence.commit_many(conn, [("slide", slide), ("pending_edit", pe)], [audit])
    return {"slide": slide, "claim": reopened_claim, "pendingEdit": pe}


def discard_pending_edit(conn, workspace_id: str, pending_edit_id: str, actor: str, reason: str) -> models.PendingEdit:
    pe = persistence.get(conn, "pending_edit", pending_edit_id, models.PendingEdit)
    if pe is None or pe.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"pending edit '{pending_edit_id}' not found", {"pendingEditId": pending_edit_id})
    if pe.status != "PENDING":
        raise EngineError("VALIDATION_ERROR", f"pending edit '{pending_edit_id}' is already {pe.status}", {})
    pe.status = "DISCARDED"
    pe.resolved_at = models.now_iso()
    pe.resolution_note = reason
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="reimport.discard", subject_type="pending_edit", subject_id=pe.id, details={"reason": reason},
    )
    persistence.commit(conn, "pending_edit", pe, audit)
    return pe


def link_unmatched(conn, workspace_id: str, unmatched_id: str, slide_id: str, region_role: str, actor: str) -> models.PendingEdit:
    """Manual linking for an unmatched-content item (FR-PPT-7): the user
    tells the Engine which region this orphaned text actually belongs to,
    which converts it into a normal pending edit."""
    item = persistence.get(conn, "unmatched_content", unmatched_id, models.UnmatchedContentItem)
    if item is None or item.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"unmatched content '{unmatched_id}' not found", {})
    slide = persistence.get(conn, "slide", slide_id, models.SlideSpec)
    if slide is None or region_role not in slide.regions:
        raise EngineError("NOT_FOUND", f"slide '{slide_id}' has no region '{region_role}'", {})
    region = slide.regions[region_role]
    pe = models.PendingEdit(
        id=models.new_id("pendingedit"), workspace_id=workspace_id, slide_id=slide_id,
        region_role=region_role, region_id=f"{slide_id}:{region_role}",
        old_text=region.text, new_text=item.text, old_hash=region.content_hash,
        new_hash=sha256_hex(item.text), claim_ids=list(region.claim_ids),
    )
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="reimport.link_unmatched", subject_type="pending_edit", subject_id=pe.id,
        details={"unmatchedId": unmatched_id, "regionId": pe.region_id},
    )
    persistence.commit(conn, "pending_edit", pe, audit)
    return pe
