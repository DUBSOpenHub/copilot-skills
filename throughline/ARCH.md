# Architecture: GitHub Copilot Throughline

## Overview

GitHub Copilot Throughline ships as one installable GitHub Copilot CLI skill with two halves that never blur: a **deterministic Engine** (Python stdlib, no network, no model calls, fully black-box testable) that owns every state machine, gate, ledger, and file format; and a thin **Skill Prompt Layer** where the running GitHub Copilot CLI agent does the only two things an engine cannot do deterministically — generate creative text (throughlines, routes, notes, Q&A) and call MCP tools (WorkIQ, GitHub). The agent never mutates state directly; every mutation flows through one engine CLI, so a test harness can drive the identical entry point the agent uses, with zero WorkIQ dependency.

## 1. Component Diagram and End-to-End Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│ GitHub Copilot CLI session — user types "throughline"            │
└───────────────────────────────┬──────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│ SKILL PROMPT LAYER  (SKILL.md, agent turn — non-deterministic)    │
│  • asks brief questions, drafts 3 throughlines / 2-3 routes /     │
│    claim text / speaker notes / rehearsal Q&A                    │
│  • calls MCP tools to fetch exact user-named sources              │
│  • sends every proposal + fetched bytes to the Engine CLI         │
│  • never writes workspace state itself                           │
└───────┬───────────────────────────────────────┬──────────────────┘
        │ MCP tool calls (retrieval only)       │ subprocess, JSON on
        ▼                                       │ stdin/stdout
┌────────────────────────┐                      ▼
│ Retrieval Fetchers      │      ┌──────────────────────────────────────────┐
│ (agent-orchestrated,    │      │ ENGINE  bin/throughline-engine            │
│  not engine code)       │      │ (Python 3 stdlib only — deterministic)    │
│ • LocalFetcher          │      │                                            │
│   (reads path / staged  │─────▶│ Workspace Controller  (phase FSM, lock)   │
│    paste text; no MCP)  │      │ Source Ingest Port  (validate, hash, ACL) │
│ • WorkIQFetcher         │      │ Evidence Ledger                           │
│   (workiq-fetch/        │      │ Claim Engine + Conflict Detector          │
│    retrieve/fetch_blob) │      │ Narrative Store  (throughlines/routes/    │
│ • GitHubFetcher         │      │   beats) + Narrative Gate                 │
│   (github-mcp-server-   │      │ Gate Runner  (Scope/Evidence/Narrative/   │
│    get_file_contents/   │      │   Claims/Readiness/Stage)                 │
│    search_code)         │      │ Deck Compiler → Slide Contract            │
│                         │      │ PPTX Engine  (compile / export / reimport)│
│  each emits a common    │      │ PDF Exporter  (LibreOffice-first/fallback)│
│  FetchResult envelope   │      │ Package Builder  (9-artifact manifest)    │
└────────────────────────┘      │ Approval Ledger + Audit Log (append-only) │
                                  │ Restore Point Manager                     │
                                  │ Persistence  (SQLite workspace.db)        │
                                  └─────────────────┬──────────────────────────┘
                                                    ▼
                                  ┌──────────────────────────────────────────┐
                                  │ ~/.copilot/throughline/workspace/<id>/    │
                                  │  workspace.db, staging/, exports/,        │
                                  │  restore_points/                          │
                                  │ (skill package assets/template.pptx is    │
                                  │  read-only input, not runtime state)      │
                                  └──────────────────────────────────────────┘
```

### End-to-end data flow (maps to PRD §3 journey steps)

1. **Invoke** — user types `throughline`. Skill runs `workspace show`; if none active, collects the talk brief and runs `workspace new --brief`.
2. **Throughline** — agent drafts 3 candidates; sends them via `narrative propose-throughlines --input`. Engine validates exactly 3, stores them, accepts a user-authored replacement verbatim (FR-NAR-1/2).
3. **Bundle** — user names ≤25 sources with an explicit origin (`local`, `workiq`, `github`). Agent fetches each via the matching Fetcher (or reads/stages local bytes directly) and calls `source ingest`. Engine enforces the 25-cap, computes `contentHash`, and runs the Scope permission check (FR-SRC-1..4).
4. **Evidence** — `evidence extract` turns each `AUTHORIZED` source into evidence atoms (9 required fields). User calls `evidence set-disposition` (keep/quarantine/reject) per atom (FR-EVD-1/2).
5. **Claims** — agent drafts typed claim text from kept atoms; `claim propose --input` registers them (exactly one type each). `ConflictDetector` runs automatically on every propose/link, emitting conflict cards for contradictory atoms on one claim (FR-EVD-3/7).
6. **Narrative route** — agent drafts 2-3 routes; `narrative propose-routes` / `select-route` records the choice; no auto-selection (FR-NAR-3).
7. **Narrative gate** — `gate run narrative` checks beat-spine rules (HOOK/ASK/proof/aspirational-label/adjacent-jobs/10% buffer). Failing blocks `compile` outright (FR-NAR-4).
8. **Compile** — `compile` turns the approved beat sequence into a `SlideSpec[]` (Deck Contract): mechanical assignment of headline/job/≤3 claims/visual/notes fields against the one bundled template's regions (FR-PPT-2, FR-NAR-5).
9. **Gate review** — `gate run scope|evidence|narrative|claims` re-validates the whole chain against current state; Claims gate requires a named approver per externally stated claim (FR-GATE-1..4).
10. **Export (draft)** — `export pptx` renders the compiled contract into a real `.pptx` with native shapes and native notes, stamping stable deck/slide/region IDs (FR-PPT-4/5).
11. **Rehearse** — `rehearse run` ingests actual per-slide timings (agent times the read-aloud, or a fixture in tests), reports drift/overrun, and can propose cuts (FR-DEL-1/3).
12. **Readiness** — `gate run readiness` checks accessibility (alt text/reading order/contrast/non-color signaling) and demo fallback completeness for every applicable slide (FR-DEL-4/5).
13. **Stage approval** — `gate run stage --actor <name>` requires a named human; never satisfiable by an automated actor (FR-GATE-5).
14. **Package** — `export package` assembles the 9-artifact stage package plus `manifest.json` sharing one workspace/deck/manifest identity (FR-DEL-6, NFR-7). A restore point is captured at every gate pass along the way (FR-DEL-7).

## 2. Chosen Stack and Rationale

| Choice | Rationale |
|---|---|
| **Python 3.11+, stdlib-only Engine** | `zipfile` + `xml.etree.ElementTree` + `sqlite3` + `hashlib` cover every Engine need. Zero mandatory third-party packages means the skill installs by copying a folder — no `pip install`, no network, no version drift — which is the strongest guarantee of NFR-6 (full manual/local run, no live connection required) and of clean installability. |
| **Direct OOXML manipulation for `.pptx`** (not `python-pptx`) | This environment already ships a validated `pptx` skill (`~/.copilot/skills/pptx/scripts/office/{unpack,pack,validate}.py`) built on exactly this pattern: unzip the `.pptx`, edit XML parts with precise, minimal changes, rezip, validate. Reusing the same proven technique — rather than a third-party abstraction — gives full control over shape `name` attributes (stable region IDs), the notes-slide part (native notes), and a custom XML part (provenance manifest), which `python-pptx` does not expose as cleanly. |
| **SQLite single-file `workspace.db`** | Atomic transactions protect the ledgers from partial writes on crash mid-gate; the whole workspace is one file, so a restore point is one file copy; queryable for engineering debugging but never the black-box test surface (tests go through the CLI, not the DB). Stdlib `sqlite3`, no server. |
| **JSON as the wire format for the Engine CLI and for exported manifests** | Human-readable, diffable, trivially asserted on in tests, and matches the PRD's own evidence-atom/claim/slide JSON shapes almost field-for-field. |
| **LibreOffice headless (`soffice --headless --convert-to pdf`) as the primary path for the accessible PDF, with a stdlib fallback composer** | Same external tool the environment's own `pptx` skill already relies on (`scripts/office/soffice.py`) for rendering/validation — a proven, already-present dependency, not a novel one. It is optional at the OS level, so its absence must never block a run: the fallback is a minimal stdlib PDF writer that reproduces headline/body/alt-text/captions as tagged, reading-order-correct text (lower visual fidelity, always available). Which path ran is recorded as an advisory flag on the export result, never silently substituted. |
| **`argparse`-based CLI, one JSON envelope in/out per command** | No CLI framework dependency; every command is independently invocable by a human, the agent (via `bash`), or a test harness (via `subprocess`) with identical behavior. |
| **No server, no message queue, no background job runner** | Single-user, single-workspace, one-presentation-at-a-time (NFR-2) has no concurrency to coordinate. A queue or server would be complexity with no user story behind it. |

## 3. Installable GitHub Copilot Skill Structure and Invocation Flow

The repository root **is** the skill package, mirroring the `SKILL.md` + frontmatter + `catalog.yml` convention already used by installed skills in this environment (e.g., `dark-factory/SKILL.md`, `dark-factory/catalog.yml`). Installing means copying/cloning this repository to `~/.copilot/skills/throughline/`; an `install.sh` convenience script performs that copy and checks `python3` is on PATH — nothing more elaborate.

**`SKILL.md` frontmatter (exact fields):**
```
name: throughline
description: >
  GitHub Copilot Throughline — turns a curated, authorized source bundle into a
  defensible narrative, an editable PowerPoint deck with speaker notes, a
  rehearsal plan, and a stage-recovery package. Say "throughline" to start.
tools:
  - bash            # invoke bin/throughline-engine, detect soffice
  - view            # show exported file paths / manifest to the user
  - create          # stage pasted text as local source files
  - edit            # apply narrow re-import merges the user approves
  - glob
  - grep
  - workiq-fetch
  - workiq-retrieve
  - workiq-fetch_blob
  - workiq-ask                       # suggestion-only, never cited directly (FR-M365-5)
  - github-mcp-server-get_file_contents
  - github-mcp-server-search_code
```
Only the MCP tools Throughline actually calls are declared (least privilege) — never Kusto/Trino/Slack surfaces.

**Invocation flow:**
1. User types `throughline` in an active GitHub Copilot CLI session (FR-INV-1). GitHub Copilot CLI's skill matcher activates this skill on the trigger phrase in `description`.
2. The skill body's first instruction is always `throughline-engine workspace show`.
   - No workspace on disk → collect the talk brief conversationally, then `workspace new --brief brief.json`.
   - A workspace exists → report its current phase and the next required action (resume, not restart), satisfying FR-INV-1's "resumes the open one."
3. The skill body proceeds phase-by-phase per the data flow in §1. At every step where content must become canonical (a throughline, a claim, a note), the agent's proposal is written to a JSON file and handed to the matching Engine command — the agent never edits `workspace.db` and never renders `.pptx` bytes itself.
4. All user-facing strings in the skill body and in every Engine-emitted message use "GitHub Copilot Throughline" or "GitHub Copilot" in full, never a bare "Copilot" (FR-INV-2, NFR-1) — enforced by a fixed string-constants module (`engine/strings.py`) that is the *only* place literal product-name text is authored, so there is one place to audit instead of many.

## 4. Public Local Test Interface for Black-Box Acceptance Testing

The Engine is a standalone Python package runnable as `python3 -m engine.cli <command>` (wrapped by `bin/throughline-engine`) from any shell — no GitHub Copilot CLI session, no MCP server, and no model call is required to exercise it. This is the same entry point the agent uses, so sealed tests exercise real production code paths, not a test-only shim.

**Wire contract:** every command reads optional JSON on stdin / `--input file.json` and writes one JSON envelope to stdout: `{ "ok": bool, "data": <result>, "error": null | { "code": string, "message": string, "details": {...} } }`. Exit code `0` iff `ok: true`. Diagnostics/logs go to stderr only, so stdout stays parseable. Command names and JSON field names reuse PRD/blueprint vocabulary verbatim (`source`, `evidence`, `claim`, `narrative`, `gate`, `slide`, `notes`) so that black-box tests written independently from the PRD alone converge on the same surface as this design.

**Primary black-box entry point — scenario runner (flagship for acceptance tests):**
```
throughline-engine run-scenario --scenario <scenario.json> --out <dir>
```
Runs one complete, declarative, non-interactive pass end-to-end: brief → sources (each paired with a pre-built `FetchResult` fixture, so `origin: workiq|github` needs no live MCP call) → evidence dispositions → claim drafts/approvals → conflict decisions → narrative choice → route choice → rehearsal actual-timings → demo asset declarations → stage-approval actor. Emits the full 9-artifact package plus a `run-report.json` recording every intermediate `GateResult`, state transition, and generated ID — enough for one test to assert the entire journey without knowing every sub-command.

**Secondary entry points — granular commands** (used internally by `run-scenario`, and directly by fine-grained tests):

| Command | Purpose |
|---|---|
| `workspace new --brief` / `workspace show` | Create/inspect the single active workspace (NFR-2). |
| `source ingest --origin local\|workiq\|github --ref --fetch-result` | Validate + store one `SourceArtifact` (FR-SRC-1..6). |
| `evidence extract` / `evidence set-disposition <id> keep\|quarantine\|reject --actor` | Build/curate the evidence ledger (FR-EVD-1/2). |
| `claim propose --input` / `claim link-evidence` / `claim approve <id> --actor` | Register, evidence-link, and approve claims (FR-EVD-3..6). |
| `conflict resolve <id> --decision --actor` | Record a non-silent conflict decision (FR-EVD-7). |
| `narrative propose-throughlines --input` / `select-throughline` | Register exactly 3 candidates / the active choice (FR-NAR-1/2). |
| `narrative propose-routes --input` / `select-route` | Register 2-3 routes / the active choice (FR-NAR-3). |
| `compile` | Beat sequence → `SlideSpec[]` Deck Contract (FR-NAR-5, FR-PPT-2). |
| `gate run scope\|evidence\|narrative\|claims\|readiness\|stage [--actor]` | Run/re-run one gate; aggregate failures (FR-GATE-1..5). |
| `export pptx` / `export package` | Render `.pptx` / assemble the 9-artifact package (FR-PPT-4/5, FR-DEL-6). |
| `reimport pptx --path` | Diff-based re-import (FR-PPT-6/7). |
| `rehearse run --timings <file>` | Timing, drift, cut proposals (FR-DEL-1/3). |
| `restore list` / `restore apply <id>` | List/revert to a restore point (FR-DEL-7). |
| `audit tail --since` | Read-only audit stream (NFR-8). |

## 5. File Structure

```
./
├── SKILL.md                        (new) — skill entry: frontmatter + phase-by-phase prompt body
├── README.md                       (new) — install + quickstart
├── install.sh                      (new) — copies repo to ~/.copilot/skills/throughline/
├── catalog.yml                     (new) — skill metadata, mirrors dark-factory's own catalog.yml
├── docs/
│   ├── engine-cli-reference.md     (new) — canonical command/JSON contract (source of truth for §4)
│   ├── data-model.md               (new) — full entity field tables (extends PRD JSON shapes)
│   └── template-spec.md            (new) — the one approved template's layout/region spec
├── engine/                         (new) — deterministic package, zero third-party deps
│   ├── cli.py                      — argparse dispatch, JSON envelope in/out
│   ├── workspace.py                — Workspace Controller: phase FSM, single-workspace lock
│   ├── models.py                   — dataclasses for every entity + state enums
│   ├── persistence.py              — SQLite schema + commit(state_change, audit_event) primitive
│   ├── strings.py                  — sole source of user-facing product-name text (FR-INV-2)
│   ├── ingest.py                   — SourceIngestPort: type/size limits, hashing, ACL recording
│   ├── evidence.py                 — Evidence Ledger
│   ├── claims.py                   — Claim Engine + Conflict Detector
│   ├── narrative.py                — Throughline/Route/Beat store + narrative-gate rules
│   ├── gates.py                    — Gate Runner (all six gates)
│   ├── compiler.py                 — Beat sequence → Slide Contract; cut proposals
│   ├── pptx/
│   │   ├── ooxml_engine.py         — unpack/compile/pack via stdlib zipfile + ElementTree
│   │   ├── reimport.py             — region-matching diff, unmatched-content report
│   │   └── notes.py                — structured native-notes template read/write
│   ├── pdf.py                      — LibreOffice-first, stdlib-fallback accessible PDF export
│   ├── package.py                  — 9-artifact package + manifest.json builder
│   ├── restore.py                  — restore point create/list/apply
│   ├── audit.py                    — append-only audit log (append/list only — no update/delete)
│   └── scenario.py                 — run-scenario declarative end-to-end driver
├── bin/
│   └── throughline-engine          (new) — thin wrapper for `python3 -m engine.cli`
├── assets/
│   └── template.pptx               (new, binary) — the one bundled "Throughline Standard" template
├── tests/                          (new) — OPEN tests only; sealed tests live outside the repo (vault)
│   └── fixtures/                   — sample local documents + FetchResult fixtures for workiq/github
└── .gitignore                      (new) — ignore __pycache__, local workspace runtime dir if ever colocated
```
Runtime workspace data (`~/.copilot/throughline/workspace/`) lives **outside** the installed skill folder so re-installing or updating the skill never touches user data.

## 6. Core Domain Models and State Machines

Entities (all carry `id`, `workspaceId`, `createdAt`, `updatedAt`): `TalkBrief, SourceBundle, SourceArtifact, EvidenceAtom, Claim, ConflictCard, NarrativeThroughline, NarrativeRoute, NarrativeBeat, SlideSpec, SpeakerNote, DemoAsset, GateResult, ApprovalRecord, RehearsalRun, RestorePoint, ExportArtifact, AuditEvent` — field shapes for `EvidenceAtom`, `Claim`, and `SlideSpec` follow the PRD's JSON examples exactly (§"Core data model"); `docs/data-model.md` is the extended reference so this document doesn't repeat every field.

**Workspace phase FSM** (drives what the skill offers next; independent of the gates below):
```
BRIEFING -> SOURCING -> EVIDENCE_REVIEW -> CLAIM_REVIEW -> NARRATIVE_SELECTION
  -> ROUTE_SELECTION -> COMPILED -> GATE_REVIEW -> REHEARSAL -> READINESS_REVIEW
  -> STAGE_APPROVED -> PACKAGED
Side state: REOPENED(reason)  — set on any phase whose upstream input changed
            (e.g. FR-SRC-5 access revocation); clears when the owning gate re-passes.
```

**Source state machine** (verbatim from the blueprint, engine-owned):
```
PROPOSED -> PERMISSION_CHECKED -> AUTHORIZED -> RETRIEVED -> NORMALIZED -> CURATED -> CITED -> APPROVED
Exceptions: ACCESS_REVOKED, STALE, LABEL_CONFLICT, PARSE_FAILED, QUARANTINED, RETIRED
```
`source ingest` can only be called once permission is asserted; the Engine flips `PERMISSION_CHECKED -> AUTHORIZED` itself only after independently verifying local readability (origin `local`) or accepting the caller-declared `permissionState` from a successful MCP fetch (origin `workiq`/`github` — see §7). A failed/denied fetch never reaches the Engine at all, so the state machine structurally cannot represent access it never had (NFR-3).

**Claim state machine** (verbatim from the blueprint):
```
DRAFT -> CLASSIFIED -> EVIDENCE_LINKED -> VERIFIED -> REVIEWED -> APPROVED -> LOCKED
Exceptions: UNSUPPORTED, CONTESTED, CONFLICTED, STALE, RESTRICTED, REWRITE_REQUIRED, RETIRED
```
A factual claim reaching `VERIFIED` requires ≥1 evidence atom in `CURATED`/`CITED`/`APPROVED` state or it is forced to `UNSUPPORTED` (FR-EVD-4). Losing its only supporting atom (revocation/staleness) demotes an `APPROVED`/`LOCKED` factual claim to `REWRITE_REQUIRED` and attaches an auto-drafted hedged rewrite proposal — never silently keeps the confident wording (FR-EVD-8). `LOCKED` claims are immutable except through an explicit speaker rewrite action (FR-NAR-6).

**Gate pipeline** (fixed order; each gate is a pure function over the current workspace snapshot, re-runnable any time state changes):
```
SCOPE -> EVIDENCE -> NARRATIVE -> [compile] -> CLAIMS -> [rehearse] -> READINESS -> STAGE
```
`NARRATIVE` additionally gates the `compile` action directly (FR-NAR-4); the full ordered set is re-checked before `STAGE` can pass (FR-GATE-1). A `GateResult` is `{ gate, pass, failedChecks: [{code, message, subjectId}], evaluatedAt, workspaceSnapshotVersion }`; any dependent-state change invalidates a cached `pass` result rather than leaving it stale.

**Export/package sub-FSM:** `DRAFT_EXPORTED -> VALIDATED -> PACKAGED`, plus `LAST_KNOWN_GOOD` as a pointer (not a state) to the most recent package produced by a workspace that had reached `STAGE_APPROVED` — absent on a first run, surfaced as `NO_LKG_AVAILABLE` rather than fabricated (§12).

## 7. Connector Boundary — WorkIQ/Microsoft 365 and Manual/Local Sources

The Engine performs **no network or MCP I/O of any kind**. It only ever *ingests* an already-fetched, normalized envelope:
```
FetchResult {
  origin: "local" | "workiq" | "github"
  sourceType: enum   # sharepoint_doc, onedrive_doc, pptx_file, teams_message, teams_transcript,
                     # outlook_mail, outlook_calendar, loop_page, github_repo, github_issue,
                     # github_pr, github_discussion, github_release_notes, local_upload, local_paste
  uri: string                       # exact locator the user named — never a search result
  bytesOrText: bytes | string
  owner: string
  permissionState: "authorized" | "denied"
  aclSnapshot: string
  sensitivityLabel: string | null
  version: string | timestamp
  retrievedAt: ISO-8601
}
```
This one envelope shape is the entire connector boundary. Everything upstream of it is agent-orchestrated, not Engine code:

| Fetcher | Used for | Mechanism |
|---|---|---|
| **LocalFetcher** | manual upload/paste — the FR-M365-6 equivalent path for every WorkIQ/M365 type | Agent reads a user-given path, or writes pasted text to `staging/`, and builds the envelope itself (`permissionState` is always `authorized`, since it's the user's own local content); the Engine still independently re-verifies the file is readable before accepting it. |
| **WorkIQFetcher** | SharePoint/OneDrive/PowerPoint/Teams/Outlook/Loop | Agent calls `workiq-fetch` / `workiq-retrieve` / `workiq-fetch_blob` for the **exact URI the user added** — never `workiq-search_paths` for discovery (FR-M365-1). `workiq-ask` may only produce a *suggested* locator for the user to explicitly add next; its output can never itself become a `FetchResult` (FR-M365-5). |
| **GitHubFetcher** | repos/issues/PRs/discussions/release notes | Agent calls `github-mcp-server-get_file_contents` / `search_code` for the named artifact. |

All three fetchers are agent-side, but MCP-backed retrieval inherits the signed-in user's delegated Entra ID SSO permissions by construction (per the environment's WorkIQ auth model): a denied/failed fetch means the Engine is simply never invoked for that source, so the bundle structurally cannot contain something the user could not open (FR-SRC-4, NFR-3).

**Test fakes:** because the Engine's only input is the `FetchResult` envelope, a "test fake" is nothing more than a JSON fixture file per source type (`tests/fixtures/workiq/teams_transcript.json`, etc.) fed straight to `source ingest --fetch-result`. No fake *code*, no mock MCP server, and no live tenant is ever required — this is what makes NFR-6 (a full run using manual/local inputs alone) and "no reliance on live WorkIQ availability for local testing" true by construction rather than by discipline. A companion `FakeWorkIQFetcher`/`FakeGitHubFetcher` module (fixture-driven, agent-side) exists only to let open tests exercise the *skill prompt layer's* branching logic (e.g., "what does the agent do when an MCP call fails") without touching a tenant.

**Change detection (FR-M365-4):** re-running `source ingest` for a previously-seen `uri` with a different `contentHash` or `version` marks the prior `SourceArtifact` `STALE` and creates a new snapshot; dependent evidence/claims/slides reopen per §6.

## 8. Evidence, Claim, Conflict, Narrative, Gates, Approvals, and Audit Interfaces

Signatures only (no bodies) — each is a thin wrapper around one `persistence.commit(state_change, audit_event)` call, so every mutation is audited structurally, not by convention (see §11).

```
# Evidence Ledger
extract_evidence(source_id: str) -> list[EvidenceAtom]
set_disposition(atom_id: str, disposition: KEEP|QUARANTINE|REJECT, actor: str) -> EvidenceAtom
revalidate_atom(atom_id: str) -> EvidenceAtom            # freshness/access re-check (FR-SRC-5)

# Claim Engine
propose_claims(atom_ids: list[str], drafts: list[ClaimDraft]) -> list[Claim]   # drafts are agent-authored text
link_evidence(claim_id: str, atom_id: str) -> Claim
set_rationale(claim_id: str, rationale: str, actor: str) -> Claim              # required for interpretive (FR-EVD-5)
approve_claim(claim_id: str, actor: str) -> ApprovalRecord                     # required for external claims (FR-GATE-4)
demote_claim(claim_id: str, hedged_rewrite: str) -> Claim                      # auto-invoked on lost support (FR-EVD-8)

# Conflict Detector (runs automatically after propose_claims / link_evidence)
scan_conflicts(claim_id: str) -> list[ConflictCard]
resolve_conflict(conflict_id: str, decision: str, actor: str) -> ConflictCard

# Narrative Store + Gate
propose_throughlines(brief_id: str, drafts: list[str]) -> list[NarrativeThroughline]   # exactly 3 (FR-NAR-1)
select_throughline(id: str | None, custom_text: str | None) -> NarrativeThroughline
propose_routes(throughline_id: str, drafts: list[RouteDraft]) -> list[NarrativeRoute]  # 2-3 (FR-NAR-3)
select_route(route_id: str) -> NarrativeRoute
run_narrative_gate(route_id: str) -> GateResult                                       # blocks compile (FR-NAR-4)

# Deck Compiler
compile_deck(route_id: str) -> list[SlideSpec]           # mechanical; ≤3 claims/slide, 1 headline/job (FR-PPT-2, FR-NAR-5)
propose_cuts(target_seconds: int) -> list[str]           # beat/slide ids to cut, HOOK/ASK protected (FR-DEL-3)

# Gate Runner
run_gate(name: SCOPE|EVIDENCE|NARRATIVE|CLAIMS|READINESS|STAGE, actor: str | None) -> GateResult
gate_status(workspace_id: str) -> list[GateResult]       # latest cached result per gate

# Approval Ledger
record_approval(subject_type: str, subject_id: str, actor: str, decision: str) -> ApprovalRecord

# Audit Log — append/list only; no update, no delete exists in the CLI surface at all
append_audit(event: AuditEvent) -> None
tail_audit(since: str | None) -> list[AuditEvent]
```

`propose_*` functions never generate text themselves — the Skill Prompt Layer supplies `drafts`/`ClaimDraft` text; the Engine validates shape (count, non-empty, exactly-one-type) and persists. This is the load-bearing separation for testability: sealed tests can call `propose_throughlines` with three canned strings and assert the *rules* (exactly 3 stored, no auto-select, user replacement wins) without any model in the loop.

## 9. PowerPoint Generation and Re-Import Strategy

**Template:** the Engine ships exactly one bundled asset, `assets/template.pptx` (see §16.4 for its exact layout spec), unpacked once per export via `zipfile`.

**Stable identifiers (FR-PPT-5):** IDs are **structural**, not content-derived, so they survive text edits:
- `deckId = "deck:" + workspaceId`
- `slideId = deckId + ":" + beatIndex` (stable because beat order is fixed once the route is selected)
- `regionId = slideId + ":" + role` (`role ∈ {headline, body, visual, notes.spoken, notes.transitionIn, notes.transitionOut, notes.timeBudget, notes.fallback, notes.sources}`)

A separate `contentHash` per region (not the ID) is what changes when text changes — this split is what lets re-import detect an edit without breaking identity.

**Generation:** for each `SlideSpec`, the compiler clones the template's slide-layout XML, sets each placeholder shape's `<p:nvSpPr><p:cNvPr name="...">` to its `regionId` (visible only in PowerPoint's Selection Pane, never on-slide — satisfies "provenance metadata stored outside visible slide content"), fills the run text, and writes the notes-slide part with four **visibly labeled** sections in the native notes text frame: talk track paragraph, then `Time budget:`, `Fallback:`, `Sources:` lines (FR-PPT-3 requires these to be present when the notes pane is opened — labeled and visible is the requirement, not hidden). A redundant custom XML part (`/customXml/itemN.xml`) stores the full `regionId -> {contentHash, claimIds}` manifest as a second recovery path if PowerPoint ever strips shape names (e.g., "Reduce File Size").

**Re-import (`reimport pptx --path`, FR-PPT-6/7):**
1. Unpack the given `.pptx`; for each shape/notes region, resolve its `regionId` from the shape name, falling back to the custom XML manifest.
2. Compare current text's hash to the stored `contentHash`.
   - Unchanged → no-op.
   - Changed, region recognized → the new text is recorded as a **pending edit** (canonical contract is never silently overwritten); if the region is claim-bound, that claim moves to `REWRITE_REQUIRED`/re-validation-pending (FR-PPT-6). The user runs an explicit "accept re-imported edits" action to merge.
   - Text block with no matching `regionId` at all → appended to an `UnmatchedContentReport`, never discarded or auto-merged (FR-PPT-7); surfaced for manual linking.
3. Notes-region parsing uses the same fixed labels (`Time budget:`, `Fallback:`, `Sources:`) as anchors; a label that survives but whose value changed updates that field; a notes block with the labels removed entirely is reported unmatched for that region.

**Panic deck & PDF are derived, not separately authored:** `export pptx --render-mode panic` reuses the identical compiler with every demo slide's visual forced to its `staticAssetPath` and notes prefixed with the verbal recovery script — one compiler, one template, a render-mode flag, never a second authoring path. The accessible PDF (§2, §10) is produced from the same compiled `.pptx` via LibreOffice headless, or from the same `SlideSpec[]` directly via the stdlib fallback composer if `soffice` is absent.

## 10. Artifact Package Contract

`export package` writes one directory, `exports/<workspaceId>/<exportedAt>/`, containing the 9 FR-DEL-6 artifacts plus `manifest.json`:

| `kind` | File | Produced by |
|---|---|---|
| `EDITABLE_DECK` | `deck.pptx` | PPTX Engine (normal render mode) |
| `SPEAKER_NOTES_DOC` | `speaker-notes.md` | notes.py — plain-text companion of the same native notes |
| `ACCESSIBLE_PDF` | `deck-accessible.pdf` | LibreOffice or stdlib fallback (§9) |
| `EVIDENCE_APPROVAL_MANIFEST` | `evidence-approval-manifest.json` | evidence/claims/approvals/gate results, human- and machine-readable |
| `CAPTION_SCRIPT` | `captions.vtt` | derived from notes' spoken talk track + `timeBudgetSeconds` |
| `DEMO_ASSETS` | `demo/` | user-supplied prerecorded/static files + written verbal scripts, referenced by path + hash |
| `OFFLINE_BACKUP` | `offline-backup.zip` | zips every artifact above so nothing requires network access to open |
| `PANIC_DECK` | `panic-deck.pptx` | PPTX Engine, `--render-mode panic` |
| `LAST_KNOWN_GOOD` | `last-known-good.pptx` | copy of the prior package's `deck.pptx` that had reached `STAGE_APPROVED`; omitted with `NO_LKG_AVAILABLE` on a first run |

`manifest.json`: `{ workspaceId, deckId, manifestId, templateId, exportedAt, exportedBy, artifacts: [{kind, relPath, sha256}], gateResults: GateResult[], approvalRecords: ApprovalRecord[] }`. The same `workspaceId`/`deckId`/`manifestId` trio is also stamped into the `.pptx` custom document properties, the PDF's document metadata, and a header line of every text artifact — satisfying "all artifacts reference the same workspace/deck identifiers" (NFR-7) redundantly, not just in the manifest.

## 11. Persistence and Restore Strategy

**Store:** one SQLite file, `workspace.db`, under `~/.copilot/throughline/workspace/<workspaceId>/` — one table per ledger (sources, evidence, claims, conflicts, narrative, slides, gates, approvals, restore_points, audit), each indexed by `id` and `workspaceId`. This directory is created `0700` (owner-only) since it may hold sensitive excerpts even though everything is local (§13).

**Single active workspace (NFR-2):** a lock file `workspace/.active-lock` records `{workspaceId, pid, startedAt}`. A second `workspace new` while a live lock exists is refused with `WORKSPACE_ALREADY_ACTIVE`; a lock whose `pid` is no longer running is auto-reclaimed with a warning, rather than requiring manual cleanup.

**Restore points (FR-DEL-7):** every gate pass, and every `compile`/`export`, triggers `restore.create()`, which copies `workspace.db` (via `sqlite3`'s backup API, safe against concurrent readers) into `restore_points/<timestamp>-<trigger>/workspace.db` plus a `meta.json` naming the gate/phase and actor. `restore apply <id>` first auto-snapshots the *current* state (so a revert is itself reversible), then swaps in the target copy as the live `workspace.db` — one action, per FR-DEL-7's acceptance criterion.

**Cross-session persistence:** the workspace directory is not cleaned up between CLI invocations; see the exact decision in §16.3.

## 12. Error Handling and Observable Blocked States

Every failure is one of three severities, always returned in the same JSON envelope (`error.code`, `error.message`, optional `error.details`) — never a stack trace or silent success:

- **BLOCKING** — the requested command is refused; workspace state does not advance.
- **ADVISORY** — the command succeeds but a caveat is attached to its result (e.g., a fallback path was used).
- **INFO** — a pure notification surfaced on the next relevant read (e.g., `workspace show`).

| Code | Severity | Condition | User-visible behavior |
|---|---|---|---|
| `SOURCE_UNAUTHORIZED` | BLOCKING | add of a source the user cannot open | rejected, names the source (FR-SRC-4) |
| `BUNDLE_LIMIT_REACHED` | BLOCKING | 26th source add attempted | rejected, states the 25-artifact limit (FR-SRC-2) |
| `FILE_TOO_LARGE` / `UNSUPPORTED_FILE_TYPE` | BLOCKING | local file outside §16.1 limits/types | rejected at ingest, names limit/type |
| `LABEL_CONFLICT` / `PARSE_FAILED` | BLOCKING (source only) | conflicting sensitivity labels / unparsable file | source held, zero evidence atoms until resolved (FR-SRC-6) |
| `CLAIM_UNSUPPORTED` | BLOCKING | stage-ready requested with any UNSUPPORTED factual claim | export refused, claims + required action listed (NFR-4) |
| `NARRATIVE_GATE_FAILED` | BLOCKING | missing HOOK/ASK, unlabeled aspirational claim, beat-job collision, <10% buffer | compile blocked, specific rule named (FR-NAR-4) |
| `ACCESS_REVOKED` / `SOURCE_STALE` | ADVISORY→BLOCKING cascade | source access revoked / staleness rule tripped (§16.2) | dependent atoms/claims flagged, citing slides reopen (FR-SRC-5) |
| `CONFLICT_UNRESOLVED` | BLOCKING | contradicting atoms on one claim | conflict card shown, claim blocked pending decision (FR-EVD-7) |
| `DEMO_FALLBACK_MISSING` | BLOCKING | a demo slide missing a required path | Readiness fails, names the missing path (FR-DEL-4) |
| `ACCESSIBILITY_CHECK_FAILED` | BLOCKING | missing/unconfirmed alt text, contrast, order, color-only signal | Readiness fails, names the failed check (FR-DEL-5) |
| `STAGE_APPROVER_REQUIRED` | BLOCKING | stage approval with no named human | approval refused, stays at Readiness (FR-GATE-5) |
| `UNMATCHED_CONTENT` | ADVISORY | re-imported text matches no region | placed in unmatched list, not discarded (FR-PPT-7) |
| `WORKSPACE_ALREADY_ACTIVE` | BLOCKING | second workspace attempted | refused; existing workspace must close first (NFR-2) |
| `PDF_FALLBACK_USED` | ADVISORY | `soffice` unavailable at export time | export succeeds; caveat attached to the PDF artifact entry |
| `NO_LKG_AVAILABLE` | INFO | first run, no prior Stage approval | package omits `LAST_KNOWN_GOOD` rather than fabricating one |
| `DEMO_ASSET_MISSING` | ADVISORY | a demo asset's referenced path no longer exists at export time | flagged on that artifact, export still proceeds for the rest |

## 13. Security and Permission Boundaries

- **No credentials in the Engine, ever.** All authentication is delegated-user Entra ID SSO happening entirely inside the agent's MCP tool calls; the Engine process never receives, stores, or logs a token — it only receives already-authorized bytes plus declared metadata (§7). This structurally prevents credential leakage into `workspace.db`, restore points, or any exported artifact.
- **Retrieval never widens access (FR-SRC-4).** For `origin: local`, the Engine independently verifies filesystem readability itself rather than trusting the caller. For `origin: workiq`/`github`, a failed/denied fetch means the source never reaches the Engine — there is no "retry with broader scope" path anywhere in the design.
- **Sensitivity/label conflicts are a pure data comparison** (`ingest.py` compares `sensitivityLabel` across co-cited atoms on one claim) — fully unit-testable with no I/O, no external label-taxonomy service. MVP treats labels as opaque strings: any two different non-null labels on co-cited atoms is a conflict; richer label semantics are explicitly deferred (§17).
- **Least-privilege tool declaration.** `SKILL.md` lists only the MCP tools Throughline calls (§3) — never Kusto/Trino/Slack/Kusto-adjacent surfaces, even though they are available in a GitHub Copilot CLI session generally.
- **Filesystem boundary.** The Engine only ever reads/writes inside its own workspace root and explicit user-declared source paths (read-only) — it never scans arbitrary user directories looking for content; that would make it a crawler, which is an explicit non-goal.
- **At-rest hardening.** The workspace root is created `0700` on first use; it may contain sensitive excerpts even though nothing leaves the local machine.
- **Audit identity, not credentials.** `AuditEvent.actor` is a display name/identity claim string, never a token or session identifier.

## 14. Accessibility and Demo-Fallback Validation

The `READINESS` gate aggregates every sub-check in one pass (not one-at-a-time) so a single `gate run readiness` names every outstanding item at once:

| Check | Rule | Data it reads |
|---|---|---|
| Alt text | Non-empty **and** `confirmedBy` set by a human action — an agent-drafted suggestion alone does not pass | `visual.altText`, `visual.altTextConfirmedBy` |
| Reading order | `readingOrder: string[]` must be a total order over every region on the slide (no omissions, no duplicates) | per-slide `readingOrder` |
| Non-color-only signaling | any region with `usesColorSignal: true` must also declare a `nonColorIndicator` (icon/text) | per-region flags |
| Contrast | WCAG ratio computed as a pure function over the one bundled template's two theme colors — ≥4.5:1 body, ≥3:1 large headline text | `template-spec.md` color pair (deterministic, no rendering needed) |
| Demo fallback (FR-DEL-4) | `DemoAsset` requires all four of `livePath`, `prerecordedAssetPath`, `staticAssetPath`, `verbalRecoveryScript` non-empty | `DemoAsset` record per demo slide |

Aspirational-claim labeling (`[GOAL]`/`[INTENT]`/`[RECOMMENDATION]`, FR-EVD-6) is enforced earlier, at `compile`, as a template-region rule rather than at Readiness, since it is a narrative/claims concern, not a delivery concern.

`rehearse run --skip-demos` substitutes each demo slide's static/verbal fallback for its live/prerecorded path and re-checks total timing, giving the one-click skip-demo path (blueprint "Stage resilience") a concrete, testable command rather than a UI-only affordance.

**Acknowledged limit:** grounded Q&A (FR-DEL-2) requires the agent to tag every rehearsal answer with the claim IDs it relies on; the Engine can verify those IDs are `APPROVED` (`claims.verify_grounding`) but cannot semantically verify the prose is fully faithful to them — that remains a speaker-review responsibility the product makes *visible* (a grounding report per Q&A pair), not a claim of full automatic verification.

## 15. Testing Strategy and Open Tests

- **Sealed acceptance tests** (authored from the PRD alone, per the sealed-envelope protocol) run entirely against `run-scenario` and the granular commands in §4, using `--origin local` for the primary path and pre-built `FetchResult` fixtures for `workiq`/`github` origins — no live tenant, no model call, ever required to satisfy a sealed test.
- **Open tests** (Lead Engineer-authored, alongside implementation): state-machine transition tables (§6) for `Source` and `Claim`; every §12 error code has ≥1 test producing it; contrast math (§14) against known color pairs; staleness rule (§16.2) at exact boundary days; ID-stability golden test — compile the same fixture workspace twice and assert `deckId`/`slideId`/`regionId` are byte-identical while `contentHash` values are unaffected by timestamp-only differences; re-import round-trip (export → mutate one region's text via the OOXML layer directly → reimport → assert exactly that region is `EDITED` and nothing else moved); package manifest completeness (all 9 `kind`s present, every `sha256` verifies).
- **Explicitly flagged open tests** (anticipated by this design, not fully resolvable without empirical data):
  1. Real PowerPoint "Reduce File Size" / third-party editors may strip custom shape names — needs an empirical fixture corpus exported from actual PowerPoint, not only Engine-generated files, to validate the custom-XML-manifest fallback in §9.
  2. `soffice` version/availability variance across dev and CI machines — needs an environment-detection test asserting the `PDF_FALLBACK_USED` path is itself exercised in CI (where LibreOffice may be absent), not just the primary path.
  3. Parse-time budget for a near-limit file (e.g., a 20 MB PDF) — needs a perf smoke test confirming a single `source ingest` stays responsive within one CLI turn.
  4. Concurrent-invocation lock race (`workspace/.active-lock`) — needs a test starting two processes against the same workspace root simultaneously.
  5. Sensitivity-label vocabulary is opaque-string equality only in MVP (§13); a richer label hierarchy is Phase 2 and untested by design.

## 16. Exact Decisions for the PRD's Four Open Questions

### 16.1 Accepted file types and size limits

| Category | Extensions | Max size |
|---|---|---|
| Documents/transcripts | `.pdf, .docx, .pptx, .txt, .md, .vtt, .srt` | 20 MB each |
| Images (visual evidence/alt-text source) | `.png, .jpg, .jpeg, .gif` | 10 MB each |
| Data files | `.csv, .json, .xlsx` | 15 MB each |
| Pasted text (not a file) | — | 200,000 characters per paste, synthesized to a `.txt` artifact |
| Demo prerecorded video (stage-package asset, not evidence) | `.mp4, .mov` | 250 MB each, stored by path reference + hash, not copied into `workspace.db`/restore points |

Any file exceeding its category's limit, or of an unrecognized extension, is rejected at ingest with `FILE_TOO_LARGE`/`UNSUPPORTED_FILE_TYPE` — never silently truncated or partially parsed. These limits are enforced independently of, and in addition to, the 25-artifact bundle cap (FR-SRC-2). Chosen to cover every source type the PRD names, keep parse time bounded without a background job queue, and match realistic sizes for a ≤25-item curated bundle.

### 16.2 Staleness rule

`STALE` triggers on **either** condition (first to fire wins), re-evaluated on workspace reopen and before every `EVIDENCE` gate run:
- **Content/version change** — the connector reports a different `contentHash`/`version` than the captured snapshot → immediate `STALE`, regardless of elapsed time.
- **Elapsed time since `capturedAt`**, using a per-type window because different source types age at different rates:
  - **7 days** — "live/conversational" types: Teams messages/transcripts, Outlook mail/calendar.
  - **14 days** — "document/reference" types: SharePoint/OneDrive docs, PowerPoint files, Loop pages, GitHub issues/PRs/discussions/release notes.
  - **No elapsed-time rule** — locally uploaded/pasted manual sources age only on content-hash re-check (the user curated them for this exact talk; there is no upstream that could have "moved on" independent of the user's own machine).

Both numbers live in one constants module (not scattered across the codebase) so they are tunable later without becoming a general configuration system.

### 16.3 Cross-session persistence

**The talk workspace persists on local disk across CLI sessions.** Typing `throughline` again resumes the same on-disk workspace rather than starting fresh — required for FR-INV-1's "resumes the open one" to mean anything, and for NFR-2/NFR-6/NFR-7 to hold across a realistic multi-day talk-prep timeline. Scope: one machine, one workspace root (`~/.copilot/throughline/workspace/`), one active workspace at a time (§11's lock file). Starting a second workspace requires the first to close/export first, or an explicit `workspace reset`.

### 16.4 Presentation template

**One bundled, versioned 16:9 asset, `templateId: "throughline-standard-v1"`, with exactly two slide layouts** used by the compiler — no template picker, no theme editor, no per-user branding surface in MVP:
1. **Hook/Title layout** (HOOK beat only) — large full-bleed headline placeholder, one-line subhead (job/context), no bullet body.
2. **Standard beat layout** (STAKES/TURN/MECHANISM/PROOF/OBJECTION/ASK) — headline placeholder (≤2 lines, enforced at compile), a primary-visual placeholder, a ≤3-item claim-bullets placeholder (aspirational claims auto-prefixed `[GOAL]`/`[INTENT]`/`[RECOMMENDATION]`), and a small non-branded footer reserved for beat name + slide number.

Visual style: a single light theme, system font stack (no embedded fonts — deferred, keeps export fast and small), one neutral accent color, contrast validated by the Readiness gate rather than assumed (§14). Changing the template later means shipping a new versioned asset, never an in-place visual-customization feature.

## 17. Scope Guardrails (Non-Goals Reaffirmed)

Do not build, even if it looks convenient mid-implementation: tenant-wide/permission-trimmed discovery (curated bundle only); multi-user or live co-editing (single acting user holds every blueprint role); a multi-talk portfolio store (one workspace, enforced by the lock file); audience/live-event telemetry; autonomous final-voice publishing (every propose_* call requires a human selection/approval); automatic animation authoring; a hosted/multi-tenant service (Engine is a local CLI, full stop); a template picker or brand-customization system (§16.4); a general configuration system (the two tunable numbers in §16.2 are a constants module, not a settings UI); a background job queue (file-size limits in §16.1 keep every operation synchronous); font embedding in the `.pptx`.

