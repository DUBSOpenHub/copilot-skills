# Ralph Loop state

Protocol: 1
Status: running
Project root: <absolute target project root>
Criteria revision: 1
Passes used: <derive from pass-ledger.sh status; never edit the budget>
Last closed pass: none
Next action: <one precise executable action, including step ID>

## Original request (preserve verbatim)

> <request>

## Scope and assumptions

- Deliverables: <paths and behavior>
- Non-goals: <explicit boundaries>
- Assumptions: <safe defaults and rationale>
- Permissions/human decisions required: <none or exact missing approval>
- Environment: <runtime, toolchain, configuration; no secrets>
- Snapshot recipe: <commands covering all deliverables, including untracked files>

## Acceptance criteria

Keep stable IDs. Status is pending, passed, failed, stale, or blocked.
Every row must have a concrete assertion and expected observable result.
“Passed” outside the final gate is preliminary, not completion.

| ID | Observable requirement / edge case | Verifier command/procedure + expected result | Status | Latest evidence path / pass |
|---|---|---|---|---|
| AC01 | <testable assertion> | <exact command, assertions, failure condition> | pending | none |

## Small independently verifiable steps

| Step | Change / independent check | AC IDs | Depends on | Status | Consecutive no-progress passes / signature |
|---|---|---|---|---|---|
| S01 | <bounded implementation and check> | AC01 | none | pending | 0 / none |

## Baseline and regressions

- Baseline commands/results/evidence: <pending until first work pass>
- Previously passing criteria invalidated by current changes: <none or IDs>
- Known flaky checks and diagnosis: <none or evidence; never hide failures>
- Existing unrelated failures: <evidence, impact, and required resolution>

## Blockers and decisions

| Item / AC IDs | Missing input or cause + evidence | Exact question / unblock action | Independent work available |
|---|---|---|---|

## Final gate (empty until a counted final pass)

- Final pass: none
- Criteria revision and environment: not verified
- Before/after deliverable fingerprint and manifest: not verified
- Full suite commands, outputs, exit codes, executed/skipped counts: not verified
- AC-to-fresh-evidence matrix: not verified
- All required checks passed on unchanged deliverables: no

## Handoff

- Last change and current working-tree condition: <details>
- Interrupted commands/uncertain side effects: <none or inspect before replay>
- Remaining work in priority order: <IDs>
- Resume action: read this file, progress.md, ledger, and logs; reconcile any
  open reservation before reserving another pass.

## Checkpoint entry format for progress.md

Append, do not rewrite history:

```text
Pass NN | work/final | target | UTC start/end | outcome
Changes / hypothesis / criteria affected:
Commands: exact invocation, cwd, deadline, output path, exit code, observations
Snapshot / environment / criterion revision:
Failures (including all flaky attempts) / regression impacts:
Decision / re-plan / blocker:
Next action:
```
