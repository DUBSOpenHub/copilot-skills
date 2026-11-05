# Looper state

Protocol: 1
Loop: <default, or the name from .ralph-loop-<name>>
Durable state: <project-root>/.ralph-loop[-<name>]/ (retained for backward compatibility; never migrate/reset history)
Status: running
Project root: <absolute target project root>
Criteria revision: 1
Criteria count: <N, recorded with pass-ledger.sh criteria N; may only grow>
Passes used: <derive from pass-ledger.sh status; never edit the budget>
Last closed pass: none
Verdict: <latest pass-ledger.sh verdict output; complete=yes is required before reporting success>
Next action: <one precise executable action, including step ID>

## Original request (preserve verbatim)

> <request>

## Scope and assumptions

- Deliverables: <paths and behavior>
- Non-goals: <explicit boundaries>
- Assumptions: <safe defaults and rationale>
- Permissions/human decisions required: <none or exact missing approval>
- Environment: <runtime, toolchain, configuration; no secrets>
- Snapshot recipe: <exact commands covering tracked, untracked, non-Git deliverables and relevant inputs>
- Relevant inputs and environment/configuration: <paths/content manifests and identifiers; no secrets>
- Snapshot exclusions and reasons: <loop evidence/caches only; never deliverables or relevant inputs>
- Saved/current snapshot references and freshness: <comparison, changed inputs, affected AC IDs; all stale if uncertain>

## Active writer and recovery

- Active reservation: <NN / work or final / target, or none; derive from ledger>
- GitHub Copilot writer: <host, process/session identity, start time>
- Associated commands: <identities, start times, deadlines, liveness evidence>
- Mutation lock: <owner and observations; absence is not proof of writer inactivity>
- Recovery findings: <proof writer/commands are inactive, partial edits/evidence/uncertain side effects retained>
- Persistence safety: <containment, parent/file/candidate checks, progress link count, write/rename exits>
- Incomplete writes/candidates: <retained paths/bytes, reconciliation and safe move-aside references; never reset history>
- Ledger reconciliation: <spent reservations, immutable results, missing/malformed metadata, blockers and next action>

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

## Current pass attempts and failure history

- Selected step / hypothesis / AC IDs: <SNN, observable expected results>
- Implementation attempts: <0 or 1>
- Repair batches: <0 or 1; diagnosis, changes, revalidation references>
- Consecutive no-progress failures: <step, count, signature, prior pass references>
- Re-plan after two: <new hypothesis/approach/dependencies; unchanged acceptance>

| Pass / phase (baseline, initial, revalidate, final) | Recorded run (passes/NN/runs/NNN) / label / execution count in phase (max 3) | Invocation / cwd / timeout | Output path / actual exit / executed-skipped counts / observations | AC IDs / flaky failure history |
|---|---|---|---|---|
| <NN / phase> | <NNN / label / attempt> | <from the run record> | <from the run record> | <IDs / retained failures and diagnosis> |

## Blockers and decisions

| Item / AC IDs | Missing input or cause + evidence | Exact question / unblock action | Independent work available |
|---|---|---|---|

## Final gate (empty until a counted final pass)

- Final pass: none
- Criteria revision and environment: not verified
- Opening/closing snapshot runs (same command, identical output): not verified
- Before/after deliverable fingerprint and manifest: not verified
- Before/after relevant-input and environment snapshots: not verified
- Full suite commands, outputs, exit codes, executed/skipped counts: not verified
- AC-to-fresh-evidence matrix: not verified
- Previously flaky checks: <three fresh consecutive final passes per check, all attempt references; any failure fails gate>
- All required checks passed on unchanged deliverables: no
- Final capacity if repairs needed: <remaining work + separate final reservations, or incomplete>
- Evidence/progress and not-complete checkpoint publication: <paths and actual exits>
- Immutable final close result and command exit: <pending; passed is accounting, not completion>
- Separate complete-state publication and verification: <pending; report complete only after all persistence succeeds>
- Verdict after close: <pending; must print complete=yes>
- Publication failure/recovery: <retained result/evidence, blocker, freshness decision and next action>

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
Executed/skipped counts / AC mappings for each attempt:
Implementation attempt / repair-batch count / validation phase and execution counts:
Snapshot recipe, manifests, exclusions / relevant inputs / environment / criterion revision:
Failures (including all flaky attempts) / regression impacts:
Consecutive no-progress count / failure signature / re-plan after two:
Writer and command liveness / recovery evidence / retained partial writes:
Checkpoint paths and write/rename exits / immutable close result and exit:
For final: not-complete evidence checkpoint, close, separate completion publication:
Decision / re-plan / blocker:
Next action:
```
