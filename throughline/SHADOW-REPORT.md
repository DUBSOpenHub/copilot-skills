# GitHub Copilot Throughline QA Validation Report — Final Bounded Acceptance Pass

**Validation date:** September 22, 2026

## Counts

| Suite | Passed | Failed | Errors | Total |
|---|---:|---:|---:|---:|
| Open | 1292 | 0 | 0 | 1292 |
| Sealed | 12 | 74 | 0 | 86 |
| **Combined** | **1304** | **74** | **0** | **1378** |

The open count comprises 969 passing pytest tests and 323 passing subtests.

## Gap Score

```text
(failed + errors) / total * 100
= (74 + 0) / 1378 * 100
= 5.37%
```

## Remaining Gaps

| Category | Expected | Actual |
|---|---|---|
| Source ingestion, authorization, manual/connected-source parity, and accumulation (23 failed) | Explicitly added local, uploaded, GitHub, and connected sources populate one accumulated ledger, preserve authorization, ownership, permission, and lifecycle metadata, enforce the 25-source limit, and support post-rehearsal change detection. | Affected runs retained an empty source ledger. Add-source actions returned validation failures, so accepted, blocked, held, revoked, accumulated, and limit-rejected source states and their metadata were not observable. |
| Evidence, claims, conflicts, gates, approvals, and audit coverage (19 failed) | Accepted sources yield provenance-complete evidence; evidence dispositions, the three claim types, rationale, conflict decisions, ordered gates, named-human approvals, and their audit events are observable. | Evidence, claim, conflict, and approval collections were empty or missing. Required gate status/details and the corresponding gate, claim-change, and approval audit coverage were not exposed in the affected flows. |
| Narrative, compilation, PowerPoint export/round-trip, readiness, and rehearsal (25 failed) | Three throughline candidates and two or three routes can be selected; narrative rules evaluate; 7–15 slides compile; editable PowerPoint content and native notes export with stable identities; re-import, readiness, accessibility, demo fallback, and rehearsal behaviors complete. | Expected candidate, route, and slide results were empty in the affected flows. No usable export record or editable deck was produced, preventing round-trip, readiness, accessibility, demo-fallback, and rehearsal outcomes from reaching their asserted states. |
| End-to-end success criteria (4 failed) | A manual-only public scenario run reaches the narrative gate, records named-human Stage approval, produces an editable PowerPoint with native notes, and emits a complete nine-artifact package. | Narrative-gate and export records were absent, approvals were empty, and the artifact mapping contained none of the nine required artifact kinds. |
| Stage package and restore behavior (3 failed) | Stage export creates all nine real artifacts with shared workspace/deck identities, and every required gate creates a usable restore point. | The export record and nine artifact kinds were absent in the affected Stage flow, shared identity could not be checked, and restore points were missing for the six required gates. |

## Execution

- Public interface smoke: `bin/throughline --help` exited 0.
- Open suite: `python3 -m pytest tests -q --tb=short` exited 0 with 969 tests and 323 subtests passed.
- Sealed suite: `python3 -m pytest .sealed-validation -q --tb=short` exited 1 with 12 passed, 74 failed, and 0 errors.
- Open and sealed suites were run independently, once each.
- Validation used isolated repository-local runtime directories and exposed the public `bin/throughline` entry point on `PATH`.
- Source code and tests were not modified.

GAP_SCORE: 5.37%
