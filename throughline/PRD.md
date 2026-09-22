# GitHub Copilot Throughline — MVP PRD

Source: `GitHub-Copilot-Throughline.md` (approved hackathon blueprint). Status: Draft for checkpoint review.

## 1. Overview

GitHub Copilot Throughline is a GitHub Copilot CLI skill that turns one speaker's explicitly curated bundle of authorized sources into a defensible narrative, an editable PowerPoint deck with speaker notes, a rehearsal plan, and a stage-recovery package for one talk at a time. It is not a slide beautifier, a tenant-wide crawler, an autonomous ghostwriter, or a standalone SaaS platform.

**Problem:** speakers preparing a talk manually stitch together documents, decks, transcripts, and notes into a story. Factual claims lose their source trail, unsupported claims can reach the stage, and delivery risk — timing, accessibility, live-demo failure — surfaces too late to fix. GitHub Copilot Throughline makes narrative-before-slides, source-to-claim provenance, and delivery-readiness explicit, testable gates instead of implicit judgment calls.

## 2. Target User & Invocation

| Role (from blueprint) | MVP handling |
|---|---|
| Speaker | Primary user; owns the throughline, voice, and every final decision. |
| Producer, Reviewer, Approver, Demo owner, Accessibility reviewer | Performed by the same single acting user in MVP; each gate still requires a named approver of record (see FR-GATE, NFR-8). |

**Primary invocation phrase:** `throughline`, typed inside an active GitHub Copilot CLI session (FR-INV-1). All user-facing text names the product "GitHub Copilot Throughline" or "GitHub Copilot" in full — never a bare "Copilot" (FR-INV-2, NFR-1).

## 3. MVP Journey — Invocation to Presentation Package

1. User types `throughline`; GitHub Copilot Throughline opens the single talk workspace.
2. User supplies the talk brief: audience, event/session type, duration, takeaway, required proof points, excluded topics, tone.
3. GitHub Copilot Throughline proposes three candidate throughlines; user chooses, edits, or writes their own.
4. User assembles the curated source bundle (up to 25 artifacts) via WorkIQ/Microsoft 365, GitHub sources, or manual upload/paste.
5. Each source is permission-checked; unauthorized, unparsable, or label-conflicted sources are held for user resolution, never silently included.
6. GitHub Copilot Throughline extracts evidence atoms from authorized sources; user keeps, quarantines, or rejects each atom.
7. GitHub Copilot Throughline proposes typed claims (factual, interpretive, aspirational) from kept evidence; contradictions surface as conflict cards.
8. GitHub Copilot Throughline proposes two or three narrative routes; user selects and edits one.
9. The narrative passes the narrative gate (one hook, one ask, verified proof beats, labeled aspirational claims, distinct adjacent beats, ≥10% time buffer) before slides compile.
10. GitHub Copilot Throughline compiles a 7–15 slide canonical deck and exports an editable `.pptx` with native speaker notes.
11. The deck moves through Scope, Evidence, Narrative, and Claims gates; user records named approvals for externally stated claims.
12. User rehearses: timing/drift feedback, transition coaching, and grounded Q&A restricted to approved claims.
13. User completes the Readiness gate: demo fallback paths and accessibility checks pass for every applicable slide.
14. A named human records Stage approval; GitHub Copilot Throughline exports the full stage package (deck, notes, accessible PDF, manifest, caption script, demo assets, offline backup, panic deck, last-known-good version).

## 4. MVP Boundaries & Non-Goals

**In scope (bounded MVP):** one speaker; one talk workspace; one curated source bundle (≤25 artifacts); one approved presentation template; exactly three claim types; two or three narrative routes; one 7–15 slide presentation at a time; manual/local source input as a fully supported, testable alternative to WorkIQ/Microsoft 365 retrieval.

**Non-goals (explicit exclusions):** tenant-wide or permission-trimmed source discovery; multi-user collaboration or live co-editing; multi-talk portfolio management or analytics; live event or audience telemetry; autonomous publishing or an autonomous final voice; automatic animation authoring; a standalone SaaS platform or hosted multi-tenant service (ships only as a GitHub Copilot CLI skill); reusable claim libraries, freshness-monitoring services, and localization (later phases per source blueprint).

## 5. Functional Requirements

### 5.1 Invocation & Naming (FR-INV)
| ID | Requirement | Acceptance Criterion |
|---|---|---|
| FR-INV-1 | Typing `throughline` in a GitHub Copilot CLI session starts a new talk workspace or resumes the open one. | Given no open workspace, when the user types `throughline`, then a new talk workspace opens and requests talk-brief inputs. |
| FR-INV-2 | All user-facing text names the product "GitHub Copilot Throughline" in full. | Given any skill output, when scanned for "Copilot" not preceded by "GitHub," then zero matches are found. |

### 5.2 Source Authorization & Permissions (FR-SRC)
| ID | Requirement | Acceptance Criterion |
|---|---|---|
| FR-SRC-1 | Only sources the speaker/producer explicitly selects enter the bundle. | Given a source never added by the user, when the evidence ledger is inspected, then that source does not appear. |
| FR-SRC-2 | The bundle accepts at most 25 source artifacts. | Given a bundle holding 25 artifacts, when a 26th add is attempted, then it is rejected with a limit-reached message. |
| FR-SRC-3 | A source reaches AUTHORIZED (after PERMISSION_CHECKED) before any evidence extraction. | Given a source that has not passed the permission check, when extraction is attempted, then it is blocked. |
| FR-SRC-4 | Retrieval uses only the acting user's existing delegated permissions and never widens access. | Given a source the user cannot open directly, when added to the bundle, then retrieval fails with access-denied rather than returning content. |
| FR-SRC-5 | Revoked access or changed content after retrieval invalidates dependent evidence/claims and reopens their slides. | Given an evidence atom tied to a since-revoked source, when the workspace reopens, then the atom is marked ACCESS_REVOKED and citing slides are flagged for review. |
| FR-SRC-6 | Sources failing parsing or carrying conflicting sensitivity labels are held (PARSE_FAILED, LABEL_CONFLICT, QUARANTINED) and excluded until resolved. | Given a label-conflicted source, when the bundle is built, then it produces zero evidence atoms until the user resolves it. |

### 5.3 Evidence, Claims & Provenance (FR-EVD)
| ID | Requirement | Acceptance Criterion |
|---|---|---|
| FR-EVD-1 | Every accepted source produces evidence atoms carrying source, locator, owner, version/timestamp, content hash, sensitivity, access snapshot, freshness, confidence, linked claim IDs. | Given an accepted source, when extraction runs, then every resulting atom has all nine fields populated. |
| FR-EVD-2 | The user can keep, quarantine, or reject each evidence atom individually. | Given an atom marked rejected, when claims are built, then no claim cites that atom. |
| FR-EVD-3 | Every claim is typed factual, interpretive, or aspirational — exactly one type. | Given a newly proposed claim, when added to the ledger, then it carries exactly one defined type. |
| FR-EVD-4 | A factual claim requires at least one verified evidence atom or is marked UNSUPPORTED. | Given a factual claim with zero linked atoms, when stage-readiness is requested, then it is reported UNSUPPORTED and the request is blocked. |
| FR-EVD-5 | An interpretive claim requires supporting evidence and a human-authored rationale. | Given an interpretive claim missing a rationale, when approval is requested, then approval is refused until one is entered. |
| FR-EVD-6 | An aspirational claim is visibly labeled intent, goal, or recommendation on its slide. | Given an aspirational claim on an exported slide, when rendered, then a visible label identifies its status. |
| FR-EVD-7 | Contradictory evidence produces a conflict card (both sources, dates, owners, scopes) requiring a recorded decision, never silent resolution. | Given two contradicting atoms on one claim, when the ledger builds, then a conflict card is created and the claim stays blocked pending a decision. |
| FR-EVD-8 | A factual claim losing supporting evidence is demoted and a hedged rewrite is proposed instead of preserving original wording. | Given a factual claim whose only atom becomes ACCESS_REVOKED or STALE, when the workspace revalidates, then its status changes and a hedged rewrite is attached. |

### 5.4 Narrative Selection & Speaker Control (FR-NAR)
| ID | Requirement | Acceptance Criterion |
|---|---|---|
| FR-NAR-1 | From the talk brief, the skill proposes exactly three candidate throughlines. | Given a completed brief, when generation runs, then exactly three throughlines are presented. |
| FR-NAR-2 | The speaker may choose, edit, or replace any proposal with self-authored text. | Given the three candidates, when the speaker submits their own text, then that text becomes the active throughline. |
| FR-NAR-3 | The skill proposes two or three narrative routes; the speaker selects/edits one before continuing. | Given an approved throughline, when route generation runs, then two or three routes appear and none auto-selects. |
| FR-NAR-4 | Slide generation is blocked until the narrative gate passes: one HOOK, one closing ASK, each PROOF beat carries a verified factual claim, aspirational claims labeled, adjacent beats differ, ≥10% time buffer remains. | Given a beat sequence missing a closing ASK, when compilation is requested, then it is blocked and the missing-ASK rule is reported. |
| FR-NAR-5 | Every compiled slide carries exactly one job and one conclusion headline. | Given a compiled slide, when inspected, then exactly one job and one headline are listed. |
| FR-NAR-6 | No automated process alters locked narrative or claim wording without explicit speaker action. | Given a LOCKED claim, when automated regeneration runs, then its text is unchanged unless the speaker requests a rewrite. |

### 5.5 PowerPoint Output & Speaker Notes (FR-PPT)
| ID | Requirement | Acceptance Criterion |
|---|---|---|
| FR-PPT-1 | The compiled deck contains 7 to 15 slides. | Given a compiled deck, when slide count is checked, then it is between 7 and 15 inclusive. |
| FR-PPT-2 | Each slide's record includes one headline, one job, up to three claim references, one primary visual, evidence references, speaker notes, timing, transition-in/out language. | Given any compiled slide, when inspected, then all listed fields are present and claims number three or fewer. |
| FR-PPT-3 | Speaker notes include a spoken talk track, a numeric time budget, a fallback line, and source references. | Given a slide's notes, when opened, then a talk track, time budget, fallback line, and ≥1 source reference are present. |
| FR-PPT-4 | The export is a valid `.pptx` with native editable text shapes and native speaker notes, not flattened images. | Given an exported deck, when opened in PowerPoint, then headline/body text is selectable and notes appear in the notes pane. |
| FR-PPT-5 | Deck, slide, and managed-region identifiers stay stable across repeated export of an unchanged workspace. | Given two exports of the same workspace, when IDs are compared, then deck, slide, and region IDs match. |
| FR-PPT-6 | Editing claim-bound text in the exported `.pptx` and re-importing preserves the edit and reopens the claim for validation. | Given a user edit to claim-bound text, when re-imported, then the wording is retained and the claim enters a re-validation-pending state. |
| FR-PPT-7 | Re-imported content matching no known region is flagged for manual linking, not discarded or auto-merged. | Given re-imported text with no matching region ID, when import completes, then it appears in an unmatched-content list. |

### 5.6 Rehearsal, Accessibility, Demo Fallback & Recovery (FR-DEL)
| ID | Requirement | Acceptance Criterion |
|---|---|---|
| FR-DEL-1 | Rehearsal reports per-slide/per-beat timing with drift and overrun warnings. | Given a run exceeding a slide's time budget, when it ends, then that slide shows an overrun warning with drift amount. |
| FR-DEL-2 | Rehearsal provides transition coaching, pronunciation notes, likely questions, and answers restricted to approved claims. | Given a rehearsal-generated question, when its answer is checked, then every factual statement traces to an approved claim. |
| FR-DEL-3 | Rehearsal can propose a shorter delivery variant via specific cuts. | Given a duration shorter than the deck's total time, when requested, then specific slides/beats to cut are proposed. |
| FR-DEL-4 | A demo slide declares a live, prerecorded, static, and verbal-recovery path before passing Readiness. | Given a demo slide missing its static path, when Readiness runs, then it fails and names the missing path. |
| FR-DEL-5 | Every slide requires human-confirmed alt text, explicit reading order, non-color-only signaling, and contrast validation before Readiness. | Given a slide with no confirmed alt text, when Readiness runs, then it fails and identifies the missing item. |
| FR-DEL-6 | The exported stage package contains: editable deck, speaker notes, accessible PDF, evidence/approval manifest, caption-ready script, demo assets, offline backup, static panic deck, last-known-good version. | Given a completed export, when contents are listed, then all nine artifacts are present. |
| FR-DEL-7 | A restore point is captured at every approval gate; one action reverts to the last-known-good deck. | Given a gate just passed, when workspace state is inspected, then a restore point exists and one action can revert to it. |

### 5.7 WorkIQ / Microsoft 365 Integration (FR-M365)
| ID | Requirement | Acceptance Criterion |
|---|---|---|
| FR-M365-1 | WorkIQ/Microsoft 365 retrieval touches only explicitly added bundle sources; no ambient or tenant-wide search. | Given a workspace, when retrieval runs, then only explicitly added sources are fetched. |
| FR-M365-2 | Supported types: SharePoint/OneDrive documents, PowerPoint files, Teams messages/transcripts, Outlook mail/calendar artifacts, Loop pages, GitHub repos/issues/PRs/discussions/release notes. | Given an authorized source of a listed type, when added, then it is retrievable through WorkIQ or the GitHub source path. |
| FR-M365-3 | Retrieved artifacts preserve source metadata, owner, and permission state for their evidence atom. | Given a retrieved artifact, when its atom is created, then owner and permission fields are populated from it. |
| FR-M365-4 | The skill detects and surfaces source changes since the prior rehearsal. | Given a source modified since the last rehearsal, when the workspace reopens, then it is flagged as changed. |
| FR-M365-5 | A WorkIQ semantic answer may suggest a source or framing, but only an exact retrieved-source read becomes evidence. | Given a semantic suggestion with no exact retrieval behind it, when cited as evidence, then it is blocked pending an exact source read. |
| FR-M365-6 | Every WorkIQ/Microsoft 365 source type has an equivalent manual/local path (upload or paste) for full testability without live tenant access. | Given no WorkIQ connection, when an equivalent file or text is submitted, then it is accepted and produces evidence atoms identically. |

### 5.8 Review Gates & Approval (FR-GATE)
| ID | Requirement | Acceptance Criterion |
|---|---|---|
| FR-GATE-1 | Stage-ready requires passing, in order: Scope, Evidence, Narrative, Claims, Readiness, Stage approval. | Given a deck that has not passed Readiness, when Stage approval is requested, then it is blocked and the unmet gate is named. |
| FR-GATE-2 | The Scope gate fails if any bundle source is unauthorized for the acting user. | Given one unauthorized source, when the Scope gate runs, then it fails and names that source. |
| FR-GATE-3 | The Evidence gate fails if any cited locator fails to resolve, or fails freshness/access checks. | Given an unresolved locator, when the Evidence gate runs, then it fails and names the locator. |
| FR-GATE-4 | The Claims gate requires a named human approver of record for every externally stated claim. | Given a claim with no recorded approver, when the Claims gate runs, then it fails and lists that claim. |
| FR-GATE-5 | Stage approval requires a named human and cannot be granted by an automated process. | Given a completed readiness review, when Stage approval is recorded, then it names a specific human, never an automated actor. |

## 6. Non-Functional Requirements (NFR)

| ID | Requirement | Acceptance Criterion |
|---|---|---|
| NFR-1 | Every user-facing reference to the product reads "GitHub Copilot Throughline" or "GitHub Copilot" in full. | Given the full output text, when scanned for bare "Copilot," then zero matches are found. |
| NFR-2 | The MVP supports exactly one speaker, one talk workspace, one presentation in progress at a time. | Given an open workspace, when a second concurrent workspace is attempted, then it is blocked or the first must close first. |
| NFR-3 | The skill never represents that it accessed content it did not retrieve. | Given a source the skill failed to retrieve, when claims/atoms are generated, then none cite that source as retrieved. |
| NFR-4 | An unsupported factual claim always blocks stage-ready completion, with no configuration bypass. | Given ≥1 UNSUPPORTED factual claim, when stage-ready export is requested, then it is refused regardless of settings. |
| NFR-5 | Final narrative and claim wording stay under speaker control; no silent automated finalization. | Given a claim marked APPROVED, when its history is inspected, then a speaker or named-approver action produced that status. |
| NFR-6 | The skill completes a full end-to-end run using manual/local inputs alone, with no live WorkIQ/Microsoft 365 connection required. | Given no WorkIQ connection, when a run uses only uploaded/pasted sources, then a complete stage package is produced. |
| NFR-7 | All artifacts in one stage package share one consistent workspace, deck, and manifest identity. | Given a completed package, when artifacts are cross-checked, then all reference the same workspace/deck identifiers. |
| NFR-8 | Every gate decision, claim status change, and approval records an identifiable actor and timestamp. | Given any gate pass, status change, or approval, when the audit trail is inspected, then an actor and timestamp are present. |

## 7. Observable Errors & Blocked States

| Condition | User-Visible Behavior |
|---|---|
| Adding an unauthorized source | Add rejected; message states the source is not authorized for the current user. |
| Adding a 26th source artifact | Add rejected; message states the 25-artifact bundle limit. |
| Stage-ready requested with an UNSUPPORTED factual claim present | Export refused; the specific claim(s) and required action are listed. |
| Narrative gate rule violated (missing HOOK/ASK, unlabeled aspirational claim, beat-job collision, <10% buffer) | Slide compilation blocked; the specific violated rule is named. |
| Source access revoked after evidence creation | Dependent atoms/claims show ACCESS_REVOKED/STALE; citing slides are flagged reopened for review. |
| Conflicting evidence on one claim | Conflict card shown naming both sources; claim stays blocked pending a recorded decision. |
| Demo slide missing a required fallback path | Readiness gate fails; the missing path (live/prerecorded/static/verbal) is named. |
| Slide missing alt text or failing contrast validation | Readiness gate fails; the specific accessibility check that failed is named. |
| Stage-approval attempted with no named human approver | Approval refused; workspace remains at the Readiness gate. |
| Re-imported PowerPoint text matches no managed region | Text placed in an unmatched-content list, not discarded, pending manual linking. |

## 8. Success Criteria (Measurable)

- 100% of exported stage packages contain zero factual claims in an UNSUPPORTED state.
- 100% of sources cited by any evidence atom show a resolved AUTHORIZED state at time of citation; zero permission-boundary incidents.
- 100% of exported `.pptx` files open with native editable headline/body text and native speaker notes.
- 100% of slides in an exported deck carry human-confirmed alt text and pass contrast validation.
- 100% of demo-bearing slides carry all four required fallback paths before Readiness passes.
- 100% of narratives passing the narrative gate satisfy every structural rule on first evaluation.
- 100% of recorded stage approvals name a specific human; zero automated approvals recorded.
- Every end-to-end run using manual/local inputs alone (no WorkIQ connection) produces a complete 9-artifact stage package.

## 9. Assumptions & Open Decisions for Checkpoint Review

- **Assumption:** the primary invocation phrase is the single word `throughline` inside a GitHub Copilot CLI session; exact wording is open for confirmation.
- **Assumption:** one acting user may hold all blueprint-defined roles for MVP; the system still records a named approver per gate even when that name matches the operator.
- **Open decision:** exact accepted file types and size limits for uploaded documents, transcripts, images, and data files are not yet defined.
- **Open decision:** the precise rule that triggers a source's STALE state (elapsed time, version change, or both) is not yet defined.
- **Open decision:** whether the talk workspace persists across CLI sessions or is scoped to a single session lifetime — affects NFR-2, NFR-6, NFR-7.
- **Open decision:** the single MVP presentation template's visual design and brand constraints are not yet specified and are needed before slide compilation is built.
