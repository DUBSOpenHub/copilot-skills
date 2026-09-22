# Template Spec — `throughline-standard-v1`

The one bundled, versioned 16:9 template (ARCH §16.4). No template picker, no theme editor, no
per-user branding in MVP. Changing the design later means shipping a new versioned
`templateId`, never an in-place customization feature.

## Bundled asset

`assets/template.pptx` — a genuine, PowerPoint-openable file with two example slides (one per
layout), built by `scripts/build_template_asset.py` using the exact same
`engine/pptx/ooxml_engine.py` code every real export uses. Open it directly to see the layouts.

**Disclosed implementation note:** ARCH §9 describes the Engine "unpacking `assets/template.pptx`
once per export." This implementation instead sources the master/layout/theme/notes-master XML
from one shared Python module (`ooxml_engine.TEMPLATE_PARTS`, built once at import time) used
identically to render both the shipped `assets/template.pptx` asset and every real export. This
achieves the same architectural guarantee — one authored template definition, reused everywhere,
`templateId` stamped consistently — without depending on locating and unzipping a file relative
to wherever the skill happens to be installed. The two are guaranteed byte-identical for the
fixed parts because they are produced by the same functions.

## Layouts

### 1. Hook/Title layout (`HOOK` beat only)

- Large, full-bleed **headline** placeholder (`ctrTitle`), ≤2 lines (compile-time enforced,
  ~100 characters).
- One-line **subhead** placeholder (`subTitle`) carrying job/context — no bullet body.
- No primary-visual placeholder (a Hook slide never has a `visual` region at all — see
  `docs/data-model.md`'s region-role table).

### 2. Standard beat layout (`STAKES|TURN|MECHANISM|PROOF|OBJECTION|ASK`)

- **Headline** placeholder (`title`), ≤2 lines.
- **Primary-visual** placeholder (`pic`) — a textual caption/description in MVP (the Engine does
  not render images); the speaker adds the actual graphic in PowerPoint afterward.
- **Claim-bullets** placeholder (`body`), ≤3 items. Aspirational claims are auto-prefixed
  `[GOAL]` / `[INTENT]` / `[RECOMMENDATION]` at compile time (FR-EVD-6).
- A small, non-branded, decorative **footer** (beat name + slide number) — cosmetic only, not a
  tracked region, and explicitly ignored by re-import (never reported "unmatched").

## Visual style

- Single light theme: background `#FFFFFF`, body/headline text `#1A1A1A`, one neutral accent
  `#2E5AAC` (used sparingly, e.g. for the sparse decorative footer/aspirational labels).
- System font stack (Calibri) — no embedded fonts, keeping export fast and small (explicit
  non-goal per ARCH §17).
- Contrast is validated, not assumed, by the Readiness gate: body text ≥4.5:1, large headline
  text ≥3:1 against the background, computed as a pure function
  (`gates.contrast_ratio`/`relative_luminance`) over these two fixed theme colors — deterministic,
  no rendering required.

## Native shapes, notes, and stable IDs (FR-PPT-4/5, ARCH §9)

- Every tracked shape's `<p:cNvPr name="...">` is set to its **regionId** — visible only in
  PowerPoint's Selection Pane, never on-slide.
- IDs are **structural**: `deckId = "deck:" + workspaceId`, `slideId = deckId + ":" + beatOrder`,
  `regionId = slideId + ":" + role`. A separate per-region `contentHash` (not the ID) changes
  when text changes — this split is what lets re-import detect an edit without breaking identity.
- Native speaker notes carry six regions in a fixed order inside one notes text frame: the
  unlabeled spoken talk track, then four **visibly labeled** lines — `Transition in:`,
  `Transition out:`, `Time budget:`, `Fallback:`, `Sources:` (labels are bold runs). These exact
  labels are the anchors `reimport.py`'s notes parser matches on.
- A redundant custom XML part (`/customXml/item1.xml`, a real Office Custom XML Part with its
  companion `itemProps1.xml`) stores the full `regionId -> {contentHash, claimIds}` manifest as a
  second recovery path if a shape's `name` is ever stripped (e.g. by "Reduce File Size").
- `workspaceId`/`deckId`/`manifestId` are stamped redundantly: in `docProps/custom.xml`
  (`ThroughlineWorkspaceId` etc.), in the PDF's document Info dictionary, and in every text
  artifact's manifest entry (NFR-7).

## Panic deck

`export pptx --render-mode panic` (and the `PANIC_DECK` package artifact) reuse the identical
compiler and template — never a second authoring path. Every demo slide's `visual` region is
replaced with `[STATIC BACKUP] <staticAssetPath>` and its spoken notes are prefixed
`[VERBAL RECOVERY] <verbalRecoveryScript> | <original spoken text>`.
