"""Direct OOXML `.pptx` generation (ARCH §2, §9) — no `python-pptx` in the
Engine's own runtime path (that dependency is reserved for open tests'
*validation* of the output, per docs/data-model.md). Every part is built
with plain string templates over the exact namespace URIs OOXML requires;
`zipfile` assembles the package.

Stable identifiers (ARCH §9): `deckId = "deck:" + workspaceId`,
`slideId = deckId + ":" + beatOrder`, `regionId = slideId + ":" + role`.
These are structural, not content-derived, so editing text never changes
an ID; a per-region `contentHash` is what changes, and that split is what
lets `reimport.py` detect an edit without breaking identity.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from typing import Optional
from xml.sax.saxutils import escape, quoteattr

from .. import models
from . import notes

TEMPLATE_ID = "throughline-standard-v1"

NS = {
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcmitype": "http://purl.org/dc/dcmitype/",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
    "custprop": "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties",
    "ds": "http://schemas.openxmlformats.org/officeDocument/2006/customXml",
    "tl": "https://throughline.dev/schema/manifest/v1",
}
REL_T = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CT_T = "application/vnd.openxmlformats-officedocument.presentationml."

# 16:9 widescreen, in EMU (914400 EMU per inch).
SLIDE_W, SLIDE_H = 12192000, 6858000
NOTES_W, NOTES_H = 6858000, 9144000

XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def sha256_hex(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Small XML builders
# ---------------------------------------------------------------------------

def _rels_xml(rels: list[tuple[str, str, str]]) -> str:
    body = "".join(
        f'<Relationship Id="{rid}" Type="{rtype}" Target="{target}"/>'
        for rid, rtype, target in rels
    )
    return (
        XML_HEADER
        + f'<Relationships xmlns="{NS["pr"]}">{body}</Relationships>'
    )


def _paragraphs_xml(text: str, bullet: bool, size_pt: Optional[int] = None) -> str:
    lines = (text or "").split("\n")
    if not lines:
        lines = [""]
    sz_attr = f' sz="{size_pt * 100}"' if size_pt else ""
    out = []
    for line in lines:
        line = line.strip()
        if bullet:
            ppr = '<a:pPr marL="285750" indent="-285750"><a:buFont typeface="Arial"/><a:buChar char="\u2022"/></a:pPr>'
        else:
            ppr = "<a:pPr><a:buNone/></a:pPr>"
        if line:
            out.append(
                f"<a:p>{ppr}<a:r><a:rPr lang=\"en-US\" dirty=\"0\"{sz_attr}/>"
                f"<a:t>{escape(line)}</a:t></a:r></a:p>"
            )
        else:
            out.append(f"<a:p>{ppr}<a:endParaRPr lang=\"en-US\" dirty=\"0\"{sz_attr}/></a:p>")
    return "".join(out)


def _shape_xml(
    shape_id: int, name: str, x: int, y: int, cx: int, cy: int, text: str,
    ph_type: Optional[str] = None, ph_idx: Optional[int] = None,
    bullet: bool = False, size_pt: Optional[int] = None,
) -> str:
    ph = ""
    if ph_type:
        idx_attr = f' idx="{ph_idx}"' if ph_idx is not None else ""
        ph = f'<p:ph type="{ph_type}"{idx_attr}/>'
    body_xml = _paragraphs_xml(text, bullet=bullet, size_pt=size_pt)
    return (
        "<p:sp>"
        f'<p:nvSpPr><p:cNvPr id="{shape_id}" name={quoteattr(name)}/>'
        f"<p:cNvSpPr>{'<a:spLocks noGrp=\"1\"/>' if ph_type else ''}</p:cNvSpPr>"
        f"<p:nvPr>{ph}</p:nvPr></p:nvSpPr>"
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
        f"<p:txBody><a:bodyPr wrap=\"square\"><a:normAutofit/></a:bodyPr><a:lstStyle/>{body_xml}</p:txBody>"
        "</p:sp>"
    )


def _group_shape_props(shape_id: int = 1) -> str:
    return (
        f'<p:nvGrpSpPr><p:cNvPr id="{shape_id}" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/>"
        "<a:chOff x=\"0\" y=\"0\"/><a:chExt cx=\"0\" cy=\"0\"/></a:xfrm></p:grpSpPr>"
    )


# ---------------------------------------------------------------------------
# Fixed (template-level) parts — one authored definition
# ("throughline-standard-v1", ARCH §16.4), shared by both the shipped
# `assets/template.pptx` inspection asset and every real export.
# ---------------------------------------------------------------------------

def theme_xml() -> str:
    return XML_HEADER + (
        f'<a:theme xmlns:a="{NS["a"]}" name="Throughline Standard">'
        "<a:themeElements>"
        "<a:clrScheme name=\"Throughline\">"
        "<a:dk1><a:sysClr val=\"windowText\" lastClr=\"1A1A1A\"/></a:dk1>"
        "<a:lt1><a:sysClr val=\"window\" lastClr=\"FFFFFF\"/></a:lt1>"
        "<a:dk2><a:srgbClr val=\"1A1A1A\"/></a:dk2>"
        "<a:lt2><a:srgbClr val=\"F2F2F2\"/></a:lt2>"
        "<a:accent1><a:srgbClr val=\"2E5AAC\"/></a:accent1>"
        "<a:accent2><a:srgbClr val=\"1A1A1A\"/></a:accent2>"
        "<a:accent3><a:srgbClr val=\"6E6E6E\"/></a:accent3>"
        "<a:accent4><a:srgbClr val=\"2E5AAC\"/></a:accent4>"
        "<a:accent5><a:srgbClr val=\"1A1A1A\"/></a:accent5>"
        "<a:accent6><a:srgbClr val=\"6E6E6E\"/></a:accent6>"
        "<a:hlink><a:srgbClr val=\"2E5AAC\"/></a:hlink>"
        "<a:folHlink><a:srgbClr val=\"6E6E6E\"/></a:folHlink>"
        "</a:clrScheme>"
        "<a:fontScheme name=\"Throughline\">"
        "<a:majorFont><a:latin typeface=\"Calibri\"/><a:ea typeface=\"\"/><a:cs typeface=\"\"/></a:majorFont>"
        "<a:minorFont><a:latin typeface=\"Calibri\"/><a:ea typeface=\"\"/><a:cs typeface=\"\"/></a:minorFont>"
        "</a:fontScheme>"
        "<a:fmtScheme name=\"Throughline\">"
        "<a:fillStyleLst><a:solidFill><a:schemeClr val=\"accent1\"/></a:solidFill>"
        "<a:solidFill><a:schemeClr val=\"accent1\"/></a:solidFill>"
        "<a:solidFill><a:schemeClr val=\"accent1\"/></a:solidFill></a:fillStyleLst>"
        "<a:lnStyleLst><a:ln w=\"6350\"><a:solidFill><a:schemeClr val=\"tx1\"/></a:solidFill></a:ln>"
        "<a:ln w=\"12700\"><a:solidFill><a:schemeClr val=\"tx1\"/></a:solidFill></a:ln>"
        "<a:ln w=\"19050\"><a:solidFill><a:schemeClr val=\"tx1\"/></a:solidFill></a:ln></a:lnStyleLst>"
        "<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle>"
        "<a:effectStyle><a:effectLst/></a:effectStyle>"
        "<a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>"
        "<a:bgFillStyleLst><a:solidFill><a:schemeClr val=\"lt1\"/></a:solidFill>"
        "<a:solidFill><a:schemeClr val=\"lt1\"/></a:solidFill>"
        "<a:solidFill><a:schemeClr val=\"lt1\"/></a:solidFill></a:bgFillStyleLst>"
        "</a:fmtScheme>"
        "</a:themeElements>"
        "</a:theme>"
    )


def slide_master_xml() -> str:
    return XML_HEADER + (
        f'<p:sldMaster xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}" xmlns:p="{NS["p"]}">'
        f"<p:cSld><p:bg><p:bgRef idx=\"1001\"><a:schemeClr val=\"lt1\"/></p:bgRef></p:bg>"
        f"<p:spTree>{_group_shape_props()}</p:spTree></p:cSld>"
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
        'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        "<p:sldLayoutIdLst>"
        '<p:sldLayoutId id="2147483649" r:id="rIdL1"/>'
        '<p:sldLayoutId id="2147483650" r:id="rIdL2"/>'
        "</p:sldLayoutIdLst>"
        "</p:sldMaster>"
    )


def slide_master_rels_xml() -> str:
    return _rels_xml([
        ("rIdL1", REL_T + "slideLayout", "../slideLayouts/slideLayout1.xml"),
        ("rIdL2", REL_T + "slideLayout", "../slideLayouts/slideLayout2.xml"),
        ("rIdTheme1", REL_T + "theme", "../theme/theme1.xml"),
    ])


def _slide_layout_xml(name: str, layout_type: str, shapes_xml: str) -> str:
    return XML_HEADER + (
        f'<p:sldLayout xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}" xmlns:p="{NS["p"]}" '
        f'type="{layout_type}" preserve="1">'
        f'<p:cSld name="{name}"><p:spTree>{_group_shape_props()}{shapes_xml}</p:spTree></p:cSld>'
        '<p:clrMapOvr><a:overrideClrMapping/></p:clrMapOvr>'
        "</p:sldLayout>"
    )


def slide_layout1_xml() -> str:
    """Hook/Title layout: full-bleed headline + one-line subhead, no bullet body."""
    headline = _shape_xml(2, "Title Placeholder", 685800, 1943100, 10820400, 2011680, "Click to add hook headline", ph_type="ctrTitle", size_pt=44)
    subhead = _shape_xml(3, "Subhead Placeholder", 685800, 3954780, 10820400, 838200, "Click to add one-line context", ph_type="subTitle", ph_idx=1, size_pt=20)
    return _slide_layout_xml("Hook/Title", "title", headline + subhead)


def slide_layout2_xml() -> str:
    """Standard beat layout: headline, primary-visual placeholder, ≤3-item claim-bullets placeholder, footer."""
    headline = _shape_xml(2, "Title Placeholder", 457200, 274638, 11277600, 838200, "Click to add headline", ph_type="title", size_pt=32)
    visual = _shape_xml(3, "Visual Placeholder", 457200, 1310640, 5486400, 4525963, "Click to add primary visual", ph_type="pic", ph_idx=1, size_pt=14)
    body = _shape_xml(4, "Claims Placeholder", 6120130, 1310640, 5614670, 4525963, "Click to add claim bullets", ph_type="body", ph_idx=2, bullet=True, size_pt=18)
    footer = _shape_xml(5, "Footer Placeholder", 457200, 6432550, 11277600, 300038, "", ph_type="ftr", ph_idx=3, size_pt=10)
    return _slide_layout_xml("Standard Beat", "obj", headline + visual + body + footer)


def slide_layout_rels_xml() -> str:
    return _rels_xml([("rIdM1", REL_T + "slideMaster", "../slideMasters/slideMaster1.xml")])


def notes_master_xml() -> str:
    slide_img = (
        '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder"/>'
        '<p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
        '<p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="685800" y="342900"/><a:ext cx="5486400" cy="3086100"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:sp>'
    )
    body = _shape_xml(3, "Notes Placeholder", 685800, 3600450, 5486400, 4991100, "Click to add notes", ph_type="body", ph_idx=1)
    return XML_HEADER + (
        f'<p:notesMaster xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}" xmlns:p="{NS["p"]}">'
        f'<p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="lt1"/></p:bgRef></p:bg>'
        f"<p:spTree>{_group_shape_props()}{slide_img}{body}</p:spTree></p:cSld>"
        "<p:clrMap bg1=\"lt1\" tx1=\"dk1\" bg2=\"lt2\" tx2=\"dk2\" accent1=\"accent1\" accent2=\"accent2\" "
        "accent3=\"accent3\" accent4=\"accent4\" accent5=\"accent5\" accent6=\"accent6\" hlink=\"hlink\" folHlink=\"folHlink\"/>"
        "</p:notesMaster>"
    )


def notes_master_rels_xml() -> str:
    return _rels_xml([("rIdTheme1", REL_T + "theme", "../theme/theme1.xml")])


TEMPLATE_PARTS: dict[str, str] = {
    "ppt/theme/theme1.xml": theme_xml(),
    "ppt/slideMasters/slideMaster1.xml": slide_master_xml(),
    "ppt/slideMasters/_rels/slideMaster1.xml.rels": slide_master_rels_xml(),
    "ppt/slideLayouts/slideLayout1.xml": slide_layout1_xml(),
    "ppt/slideLayouts/slideLayout2.xml": slide_layout2_xml(),
    "ppt/slideLayouts/_rels/slideLayout1.xml.rels": slide_layout_rels_xml(),
    "ppt/slideLayouts/_rels/slideLayout2.xml.rels": slide_layout_rels_xml(),
    "ppt/notesMasters/notesMaster1.xml": notes_master_xml(),
    "ppt/notesMasters/_rels/notesMaster1.xml.rels": notes_master_rels_xml(),
}


# ---------------------------------------------------------------------------
# Per-export (per-slide) parts
# ---------------------------------------------------------------------------

STANDARD_GEOMETRY = {
    "headline": (457200, 274638, 11277600, 838200, 32),
    "visual": (457200, 1310640, 5486400, 4525963, 14),
    "body": (6120130, 1310640, 5614670, 4525963, 18),
}
HOOK_GEOMETRY = {
    "headline": (685800, 1943100, 10820400, 2011680, 44),
    "body": (685800, 3954780, 10820400, 838200, 20),
}
FOOTER_GEOMETRY = (457200, 6432550, 11277600, 300038, 10)


def _slide_shapes_xml(slide: models.SlideSpec) -> tuple[str, dict[str, str]]:
    """Returns (shapes_xml, {role: regionId}) for shape-tracked regions
    (headline/visual/body) — notes regions live inside one notes shape and
    are tracked by label, not by their own `<p:sp>` (ARCH §9)."""
    is_hook = slide.layout == "hook"
    geometry = HOOK_GEOMETRY if is_hook else STANDARD_GEOMETRY
    shapes = []
    region_ids: dict[str, str] = {}
    shape_id = 2
    for role in (("headline", "body") if is_hook else ("headline", "visual", "body")):
        region = slide.regions[role]
        rid = models.region_id(slide.id, role)
        region_ids[role] = rid
        x, y, cx, cy, sz = geometry[role]
        ph_type = {"headline": "title" if not is_hook else "ctrTitle", "visual": "pic", "body": "body"}[role]
        ph_idx = None if role == "headline" else (1 if role == "visual" else (2 if not is_hook else 1))
        shapes.append(_shape_xml(
            shape_id, rid, x, y, cx, cy, region.text,
            ph_type=ph_type, ph_idx=ph_idx, bullet=(role == "body" and not is_hook), size_pt=sz,
        ))
        shape_id += 1
    if not is_hook:
        beat_label = f"{slide.role} \u00b7 Slide {slide.order + 1}"
        fx, fy, fcx, fcy, fsz = FOOTER_GEOMETRY
        shapes.append(_shape_xml(shape_id, "Footer (decorative)", fx, fy, fcx, fcy, beat_label, ph_type="ftr", ph_idx=3, size_pt=fsz))
    return "".join(shapes), region_ids


def _slide_xml(slide: models.SlideSpec) -> str:
    shapes_xml, _ = _slide_shapes_xml(slide)
    return XML_HEADER + (
        f'<p:sld xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}" xmlns:p="{NS["p"]}">'
        f"<p:cSld><p:spTree>{_group_shape_props()}{shapes_xml}</p:spTree></p:cSld>"
        '<p:clrMapOvr><a:overrideClrMapping/></p:clrMapOvr>'
        "</p:sld>"
    )


def _slide_rels_xml(slide: models.SlideSpec, slide_file_index: int) -> str:
    layout_file = "slideLayout1.xml" if slide.layout == "hook" else "slideLayout2.xml"
    return _rels_xml([
        ("rIdLayout", REL_T + "slideLayout", f"../slideLayouts/{layout_file}"),
        ("rIdNotes", REL_T + "notesSlide", f"../notesSlides/notesSlide{slide_file_index}.xml"),
    ])


def _notes_slide_xml(slide: models.SlideSpec) -> str:
    slide_img = (
        '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder"/>'
        '<p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
        '<p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="685800" y="342900"/><a:ext cx="5486400" cy="3086100"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:sp>'
    )
    notes_name = f"Notes {slide.id}"
    body = (
        '<p:sp><p:nvSpPr>'
        f'<p:cNvPr id="3" name={quoteattr(notes_name)}/>'
        '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
        '<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="685800" y="3600450"/><a:ext cx="5486400" cy="4991100"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
        f'<p:txBody><a:bodyPr wrap="square"/><a:lstStyle/>{notes.render_notes_body_xml(slide)}</p:txBody>'
        '</p:sp>'
    )
    return XML_HEADER + (
        f'<p:notes xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}" xmlns:p="{NS["p"]}">'
        f"<p:cSld><p:spTree>{_group_shape_props()}{slide_img}{body}</p:spTree></p:cSld>"
        '<p:clrMapOvr><a:overrideClrMapping/></p:clrMapOvr>'
        "</p:notes>"
    )


def _notes_slide_rels_xml(slide_file_index: int) -> str:
    return _rels_xml([
        ("rIdSlide", REL_T + "slide", f"../slides/slide{slide_file_index}.xml"),
        ("rIdNotesMaster", REL_T + "notesMaster", "../notesMasters/notesMaster1.xml"),
    ])


def _presentation_xml(slide_count: int) -> str:
    sld_id_lst = "".join(
        f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>' for i in range(slide_count)
    )
    return XML_HEADER + (
        f'<p:presentation xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}" xmlns:p="{NS["p"]}">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rIdM1"/></p:sldMasterIdLst>'
        '<p:notesMasterIdLst><p:notesMasterId r:id="rIdNM1"/></p:notesMasterIdLst>'
        f"<p:sldIdLst>{sld_id_lst}</p:sldIdLst>"
        f'<p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}" type="screen16x9"/>'
        f'<p:notesSz cx="{NOTES_W}" cy="{NOTES_H}"/>'
        "</p:presentation>"
    )


def _presentation_rels_xml(slide_count: int) -> str:
    rels = [
        ("rIdM1", REL_T + "slideMaster", "slideMasters/slideMaster1.xml"),
        ("rIdNM1", REL_T + "notesMaster", "notesMasters/notesMaster1.xml"),
        ("rIdCustomXml1", REL_T + "customXml", "../customXml/item1.xml"),
    ]
    for i in range(slide_count):
        rels.append((f"rId{i + 1}", REL_T + "slide", f"slides/slide{i + 1}.xml"))
    return _rels_xml(rels)


def _content_types_xml(slide_count: int) -> str:
    overrides = [
        ("/ppt/presentation.xml", CT_T + "presentation.main+xml"),
        ("/ppt/slideMasters/slideMaster1.xml", CT_T + "slideMaster+xml"),
        ("/ppt/slideLayouts/slideLayout1.xml", CT_T + "slideLayout+xml"),
        ("/ppt/slideLayouts/slideLayout2.xml", CT_T + "slideLayout+xml"),
        ("/ppt/notesMasters/notesMaster1.xml", CT_T + "notesMaster+xml"),
        ("/ppt/theme/theme1.xml", "application/vnd.openxmlformats-officedocument.theme+xml"),
        ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
        ("/docProps/app.xml", "application/vnd.openxmlformats-officedocument.extended-properties+xml"),
        ("/docProps/custom.xml", "application/vnd.openxmlformats-officedocument.custom-properties+xml"),
        ("/customXml/item1.xml", "application/xml"),
        ("/customXml/itemProps1.xml", "application/vnd.openxmlformats-officedocument.customXmlProperties+xml"),
    ]
    for i in range(slide_count):
        overrides.append((f"/ppt/slides/slide{i + 1}.xml", CT_T + "slide+xml"))
        overrides.append((f"/ppt/notesSlides/notesSlide{i + 1}.xml", CT_T + "notesSlide+xml"))
    override_xml = "".join(f'<Override PartName="{p}" ContentType="{ct}"/>' for p, ct in overrides)
    return XML_HEADER + (
        f'<Types xmlns="{NS["ct"]}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{override_xml}</Types>"
    )


def _package_rels_xml() -> str:
    return _rels_xml([
        ("rId1", REL_T + "officeDocument", "ppt/presentation.xml"),
        ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"),
        ("rId3", REL_T + "extended-properties", "docProps/app.xml"),
        ("rId4", REL_T + "custom-properties", "docProps/custom.xml"),
    ])


def _core_props_xml(title: str, creator: str, created_iso: str) -> str:
    return XML_HEADER + (
        f'<cp:coreProperties xmlns:cp="{NS["cp"]}" xmlns:dc="{NS["dc"]}" '
        f'xmlns:dcterms="{NS["dcterms"]}" xmlns:xsi="{NS["xsi"]}">'
        f"<dc:title>{escape(title)}</dc:title>"
        f"<dc:creator>{escape(creator)}</dc:creator>"
        f"<cp:lastModifiedBy>{escape(creator)}</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{created_iso}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{created_iso}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def _app_props_xml(slide_count: int) -> str:
    return XML_HEADER + (
        f'<Properties xmlns="{NS["ep"]}" xmlns:vt="{NS["vt"]}">'
        "<Application>GitHub Copilot Throughline</Application>"
        f"<Slides>{slide_count}</Slides>"
        "<Company>GitHub Copilot Throughline</Company>"
        "</Properties>"
    )


def _custom_props_xml(workspace_id: str, deck_id: str, manifest_id: str, template_id: str) -> str:
    props = [
        ("ThroughlineWorkspaceId", workspace_id),
        ("ThroughlineDeckId", deck_id),
        ("ThroughlineManifestId", manifest_id),
        ("ThroughlineTemplateId", template_id),
    ]
    body = "".join(
        f'<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="{i + 2}" name={quoteattr(name)}>'
        f"<vt:lpwstr>{escape(value)}</vt:lpwstr></property>"
        for i, (name, value) in enumerate(props)
    )
    return XML_HEADER + (
        f'<Properties xmlns="{NS["custprop"]}" xmlns:vt="{NS["vt"]}">{body}</Properties>'
    )


def _customxml_item_xml(manifest: dict[str, dict]) -> str:
    regions_xml = "".join(
        f'<tl:region id={quoteattr(rid)} contentHash={quoteattr(info["contentHash"])} '
        f'claimIds={quoteattr(",".join(info.get("claimIds", [])))}/>'
        for rid, info in manifest.items()
    )
    return XML_HEADER + (
        f'<tl:manifest xmlns:tl="{NS["tl"]}">{regions_xml}</tl:manifest>'
    )


def _customxml_item_props_xml(item_guid: str) -> str:
    return XML_HEADER + (
        f'<ds:datastoreItem ds:itemID="{{{item_guid}}}" xmlns:ds="{NS["ds"]}"><ds:schemaRefs/></ds:datastoreItem>'
    )


def _customxml_item_rels_xml() -> str:
    return _rels_xml([
        ("rId1", REL_T + "customXmlProps", "itemProps1.xml"),
    ])


@dataclass
class ExportResult:
    pptx_bytes: bytes
    manifest: dict[str, dict]


def _apply_panic_mode(slides: list[models.SlideSpec]) -> list[models.SlideSpec]:
    """`--render-mode panic`: every demo slide's visual is forced to its
    static fallback asset and its spoken notes are prefixed with the
    verbal-recovery script — same compiler, same template, one flag
    (ARCH §9)."""
    import copy
    out = []
    for slide in slides:
        if not slide.is_demo or slide.demo_asset is None:
            out.append(slide)
            continue
        clone = copy.deepcopy(slide)
        static_path = clone.demo_asset.static_asset_path or "(no static asset declared)"
        if "visual" in clone.regions:
            clone.regions["visual"].text = f"[STATIC BACKUP] {static_path}"
            clone.regions["visual"].content_hash = sha256_hex(clone.regions["visual"].text)
        verbal = clone.demo_asset.verbal_recovery_script or "(no verbal recovery script declared)"
        original_spoken = clone.regions["notes.spoken"].text
        clone.regions["notes.spoken"].text = f"[VERBAL RECOVERY] {verbal} | {original_spoken}"
        clone.regions["notes.spoken"].content_hash = sha256_hex(clone.regions["notes.spoken"].text)
        out.append(clone)
    return out


def export_pptx(
    slides: list[models.SlideSpec], workspace_id: str, deck_id: str, manifest_id: str,
    actor: str, created_iso: str, render_mode: str = "normal",
) -> ExportResult:
    if render_mode not in ("normal", "panic"):
        raise ValueError(f"unknown render_mode '{render_mode}'")
    ordered = sorted(slides, key=lambda s: s.order)
    if render_mode == "panic":
        ordered = _apply_panic_mode(ordered)

    manifest: dict[str, dict] = {}
    parts: dict[str, bytes] = {}

    for name, xml in TEMPLATE_PARTS.items():
        parts[name] = xml.encode("utf-8")

    for i, slide in enumerate(ordered):
        file_index = i + 1
        parts[f"ppt/slides/slide{file_index}.xml"] = _slide_xml(slide).encode("utf-8")
        parts[f"ppt/slides/_rels/slide{file_index}.xml.rels"] = _slide_rels_xml(slide, file_index).encode("utf-8")
        parts[f"ppt/notesSlides/notesSlide{file_index}.xml"] = _notes_slide_xml(slide).encode("utf-8")
        parts[f"ppt/notesSlides/_rels/notesSlide{file_index}.xml.rels"] = _notes_slide_rels_xml(file_index).encode("utf-8")

        for role, region in slide.regions.items():
            manifest[models.region_id(slide.id, role)] = {
                "contentHash": region.content_hash,
                "claimIds": region.claim_ids,
            }

    parts["ppt/presentation.xml"] = _presentation_xml(len(ordered)).encode("utf-8")
    parts["ppt/_rels/presentation.xml.rels"] = _presentation_rels_xml(len(ordered)).encode("utf-8")
    parts["_rels/.rels"] = _package_rels_xml().encode("utf-8")
    parts["docProps/core.xml"] = _core_props_xml(f"GitHub Copilot Throughline \u2014 {deck_id}", actor, created_iso).encode("utf-8")
    parts["docProps/app.xml"] = _app_props_xml(len(ordered)).encode("utf-8")
    parts["docProps/custom.xml"] = _custom_props_xml(workspace_id, deck_id, manifest_id, TEMPLATE_ID).encode("utf-8")
    parts["customXml/item1.xml"] = _customxml_item_xml(manifest).encode("utf-8")
    parts["customXml/itemProps1.xml"] = _customxml_item_props_xml(manifest_id.replace("manifest:", "").ljust(8, "0")[:8] + "-0000-0000-0000-000000000000").encode("utf-8")
    parts["customXml/_rels/item1.xml.rels"] = _customxml_item_rels_xml().encode("utf-8")
    parts["[Content_Types].xml"] = _content_types_xml(len(ordered)).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return ExportResult(pptx_bytes=buf.getvalue(), manifest=manifest)


def read_customxml_manifest(pptx_bytes: bytes) -> dict[str, dict]:
    """Recovery-path reader (ARCH §9): if shape names are ever stripped,
    `reimport.py` falls back to this manifest to resolve regionIds."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as zf:
        if "customXml/item1.xml" not in zf.namelist():
            return {}
        data = zf.read("customXml/item1.xml")
    root = ET.fromstring(data)
    tl_ns = NS["tl"]
    out = {}
    for region in root.findall(f"{{{tl_ns}}}region"):
        claim_ids = region.get("claimIds", "")
        out[region.get("id")] = {
            "contentHash": region.get("contentHash", ""),
            "claimIds": claim_ids.split(",") if claim_ids else [],
        }
    return out
