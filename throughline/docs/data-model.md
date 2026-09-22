# Data Model

Full entity field tables, state machines, and the specific interpretation decisions made where
the PRD/ARCH left a literal ambiguity. Extends PRD.md's JSON shapes; the authoritative Python
definitions are `engine/models.py`.

## Interpretation notes (explicit, disclosed decisions)

### FR-EVD-1 field count

FR-EVD-1 lists ten nouns ("source, locator, owner, version/timestamp, content hash, sensitivity,
access snapshot, freshness, confidence, linked claim IDs") but its acceptance criterion says
"all **nine** fields populated." This implementation reads `version/timestamp` as one combined
field and treats `linkedClaimIds` as a tenth attribute that legitimately starts as an *empty
list* at extraction time (no claims exist yet to link) rather than one of the nine
required-to-be-populated-at-extraction fields. `EvidenceAtom.has_required_fields()` checks
exactly: `source_id, locator, owner, version, content_hash, access_snapshot, freshness,
confidence` (8) plus `sensitivity`'s mere *presence as an attribute* (allowed to be `None`) = 9.
`linked_claim_ids` is present on every atom but excluded from this specific check.

### FR-SRC-6 "conflicting sensitivity labels" — two distinct mechanisms

ARCH §13 assigns "sensitivity/label conflict" detection to `ingest.py` as "a pure data
comparison... across co-cited atoms on one claim," which is a **claim-linking-time** concern —
yet FR-SRC-6 names it a **source state** (`LABEL_CONFLICT`). This implementation resolves the
apparent tension with two distinct, both fully automatic mechanisms:

1. **Source-level `LABEL_CONFLICT`** (FR-SRC-6): triggered purely at `source ingest` time when a
   *re-ingested* source's new `sensitivityLabel` differs from its immediately prior snapshot's
   label. The source is held; it produces zero evidence atoms until resolved
   (`source resolve-hold`).
2. **Claim-level sensitivity conflict** (ARCH §13): when two atoms with *different, both
   non-null* `sensitivity` values become linked to the same claim, `claims.py`'s Conflict
   Detector automatically creates a `ConflictCard` with `kind: "sensitivity_label"` (as opposed
   to `kind: "contradiction"`), blocking that claim until a human records a decision.

### FR-EVD-7 "contradictory evidence" — propose/validate split

Recognizing that two atoms' *content* actually contradicts each other is a comprehension task,
not a deterministic computation — exactly like claim/route/note authorship, which ARCH already
assigns to the agent (`propose_*` functions "never generate text themselves"). This
implementation applies the same split: the human/agent, having read both excerpts, supplies the
judgment via `claim link-evidence ... --contradicts <atomId>`; the Engine's job — building the
structured `ConflictCard` (both sources, dates, owners, scopes), blocking the claim, and
requiring a recorded decision before it can proceed — is fully automatic and deterministic.

### Beat roles and slide count

The template spec (ARCH §16.4) names beat roles `HOOK, STAKES, TURN, MECHANISM, PROOF,
OBJECTION, ASK`. Each beat compiles to exactly one slide (a 1:1 mapping), so a 7–15 slide deck
(FR-PPT-1) is a 7–15 beat route. To exceed 7 beats (one of each role), a route repeats a role
(almost always `PROOF`, for multiple proof points) at a **non-adjacent** position — "distinct
adjacent beats" (FR-NAR-4) forbids only *consecutive* repetition, not repetition overall.

### Headline "≤2 lines"

The Engine has no text-layout/rendering engine, so `compiler.MAX_HEADLINE_CHARS` (100 characters)
is a deterministic, documented proxy for "renders within two lines" at compile time — enforced as
a hard `VALIDATION_ERROR`, never silently truncated.

## Entities

### TalkBrief
`id, workspaceId, audience, eventType, durationMinutes, takeaway, proofPoints[], excludedTopics[], tone, createdAt, updatedAt`

### SourceArtifact
`id, workspaceId, origin(local|workiq|github), sourceType, uri, owner, permissionState, aclSnapshot, sensitivityLabel, version, retrievedAt, contentHash, state, byteSize, localPath, capturedAt, supersededBy, supersedes, holdReason, createdAt, updatedAt`

**State machine** (`engine/models.py::SOURCE_TRANSITIONS`):
```
PROPOSED -> PERMISSION_CHECKED -> AUTHORIZED -> RETRIEVED -> NORMALIZED -> CURATED -> CITED -> APPROVED
Exceptions (reachable from any main-path state): ACCESS_REVOKED, STALE, LABEL_CONFLICT,
PARSE_FAILED, QUARANTINED, RETIRED
```
`source ingest` computes the final landing state directly (PERMISSION_CHECKED/AUTHORIZED/RETRIEVED
are implicit, since bytes arrive already-fetched and are normalized synchronously); `evidence
extract` advances `AUTHORIZED → CURATED`; `claim link-evidence` advances the cited source's
`CURATED → CITED`; a passing `STAGE` gate advances every `CITED` source to `APPROVED`.

### EvidenceAtom
`id, workspaceId, sourceId, locator, owner, version, contentHash, sensitivity, accessSnapshot, freshness, confidence, excerpt, linkedClaimIds[], disposition(PENDING|KEEP|QUARANTINE|REJECT), accessState(AUTHORIZED|ACCESS_REVOKED), freshnessState(FRESH|STALE), createdAt, updatedAt`

One atom per paragraph of normalized source text (capped at 20 per source); a source with no
extractable text (e.g. an image) yields exactly one atom noting that explicitly.

### Claim
`id, workspaceId, type(FACTUAL|INTERPRETIVE|ASPIRATIONAL), text, state, rationale, aspirationalLabel, evidenceAtomIds[], conflictIds[], approver, approvedAt, hedgedRewrite, createdAt, updatedAt`

**State machine** (`engine/models.py::CLAIM_TRANSITIONS`):
```
DRAFT -> CLASSIFIED -> EVIDENCE_LINKED -> VERIFIED -> REVIEWED -> APPROVED -> LOCKED
Exceptions: UNSUPPORTED, CONTESTED, CONFLICTED, STALE, RESTRICTED, REWRITE_REQUIRED, RETIRED
LOCKED -> REWRITE_REQUIRED is the *only* edge out of LOCKED (an explicit speaker rewrite action).
```
State is continuously re-derived (`claims._recompute_state`) from current evidence validity,
rationale presence, and aspirational label — except it never regresses an `APPROVED`/`LOCKED`
claim automatically; only an explicit human action (`approve`, `lock`, `rewrite`) or the FR-EVD-8
demotion path changes those.

### ConflictCard
`id, workspaceId, claimId, atomIdA, atomIdB, sourceA, sourceB, dateA, dateB, ownerA, ownerB, scopeA, scopeB, status(OPEN|RESOLVED), kind(contradiction|sensitivity_label), decision, decidedBy, decidedAt, createdAt`

### NarrativeThroughline / NarrativeRoute / Beat
`NarrativeThroughline: id, workspaceId, briefId, text, origin(proposed|custom), selected, createdAt`
`NarrativeRoute: id, workspaceId, throughlineId, label, beats[Beat], selected, createdAt`
`Beat: id, routeId, order, role, headline, claimIds[]≤3, spokenTalkTrack, transitionIn, transitionOut, timeBudgetSeconds, fallbackLine, sourceRefs[], visualDescription, isDemo`

### SlideSpec / Region / DemoAsset
`SlideSpec: id, workspaceId, deckId, beatId, order, role, layout(hook|standard), regions{role:Region}, readingOrder[], isDemo, demoAsset, needsReview, needsReviewReason, createdAt, updatedAt`
`Region: role, text, contentHash, claimIds[], altText, altTextConfirmedBy, usesColorSignal, nonColorIndicator`
`DemoAsset: slideId, livePath, prerecordedAssetPath, staticAssetPath, verbalRecoveryScript`

Region roles (fixed vocabulary, ARCH §9): `headline, visual, body, notes.spoken,
notes.transitionIn, notes.transitionOut, notes.timeBudget, notes.fallback, notes.sources`. A
`hook`-layout slide omits `visual` (8 regions); a `standard`-layout slide has all 9.

**Stable IDs** (structural, not content-derived — ARCH §9): `deckId = "deck:" + workspaceId`;
`slideId = deckId + ":" + beatOrder`; `regionId = slideId + ":" + role`.

### GateResult / GateResultRecord / GateFailure
`GateResult: gate, passed, failedChecks[GateFailure], evaluatedAt, workspaceSnapshotVersion, actor`
`GateFailure: code, message, subjectId`
`GateResultRecord`: the persisted form, one row per gate name (latest wins).

Gate pipeline (fixed order): `SCOPE -> EVIDENCE -> NARRATIVE -> [compile] -> CLAIMS -> [rehearse] -> READINESS -> STAGE`.

### ApprovalRecord / AuditEvent / RestorePoint
`ApprovalRecord: id, workspaceId, subjectType, subjectId, actor, decision, decidedAt`
`AuditEvent: id, workspaceId, actor, action, subjectType, subjectId, details{}, timestamp`
`RestorePoint: id, workspaceId, trigger, actor, path, createdAt`

### PendingEdit / UnmatchedContentItem (re-import, FR-PPT-6/7)
`PendingEdit: id, workspaceId, slideId, regionRole, regionId, oldText, newText, oldHash, newHash, claimIds[], status(PENDING|ACCEPTED|DISCARDED), resolutionNote, createdAt, resolvedAt`
`UnmatchedContentItem: id, workspaceId, sourcePptxPath, text, context, createdAt`

### Workspace
`id, phase, reopenedReason, briefId, activeThroughlineId, activeRouteId, deckId, manifestId, stageApprovedBy, stageApprovedAt, snapshotVersion, createdAt, updatedAt`

**Phase FSM** (`engine/models.py::WORKSPACE_PHASE_ORDER`):
```
BRIEFING -> SOURCING -> EVIDENCE_REVIEW -> CLAIM_REVIEW -> NARRATIVE_SELECTION -> ROUTE_SELECTION
  -> COMPILED -> GATE_REVIEW -> REHEARSAL -> READINESS_REVIEW -> STAGE_APPROVED -> PACKAGED
Side state: reopenedReason (string|null) — set on any upstream change that should reopen review
(e.g. FR-SRC-5 access revocation demoting a claim); cleared when Stage next passes.
```

## Staleness rule (§16.2, exact)

`STALE` triggers on **either**: (1) a re-ingest reports a different `contentHash`/`version` than
the captured snapshot — immediate, regardless of elapsed time; or (2) elapsed time since
`capturedAt` exceeds a per-type window, re-checked on every `EVIDENCE` gate run:
- **7 days** — Teams messages/transcripts, Outlook mail/calendar.
- **14 days** — SharePoint/OneDrive docs, PowerPoint files, Loop pages, GitHub issues/PRs/discussions/release notes.
- **No elapsed-time rule** — `local_upload`/`local_paste` (content-hash re-check only).

Both numbers live in `engine/ingest.py::STALE_WINDOW_DAYS`.

## File size/type limits (§16.1, exact)

| Category | Extensions | Max size |
|---|---|---|
| Documents/transcripts | `.pdf .docx .pptx .txt .md .vtt .srt` | 20 MB |
| Images | `.png .jpg .jpeg .gif` | 10 MB |
| Data files | `.csv .json .xlsx` | 15 MB |
| Pasted text | — | 200,000 characters |
| Demo prerecorded video (asset, not evidence) | `.mp4 .mov` | 250 MB, referenced by path+hash |

## Local document parsing

`.docx/.pptx/.xlsx` are OOXML zip packages — parsed for real via stdlib `zipfile` +
`xml.etree.ElementTree`. `.csv`/`.json` use stdlib `csv`/`json`. `.pdf` uses a best-effort
stdlib `zlib`-based FlateDecode + text-operator scan (handles the common case; an unrecoverable
PDF yields `PARSE_FAILED`, never fabricated text). Images yield an honest empty excerpt (no OCR)
— see `engine/parsers.py` for the full, disclosed scope of each parser.
