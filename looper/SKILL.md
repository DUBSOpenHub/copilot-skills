---
name: looper
description: >
  GitHub Copilot turns any request into small, testable steps, implements and
  validates them, repairs failures, and resumes from project-local files after
  context resets. Stops only with verified acceptance, a genuine blocker, or
  the hard limit of 20 passes. Say "looper" or "run looper" to start or resume.
---

# Looper

Execute the request, not just a plan. Repeat **read state → reserve → implement
→ validate → repair → revalidate → checkpoint**. Disk is the source of truth.
Never equate a successful edit, a green subset, or exhausted effort with success.

## 1. Establish the goal and durable state

1. Identify the target project and read its applicable instructions. Accept
   coding, documentation, investigation, and other requests; choose verifiers
   appropriate to the deliverable. Inspect existing work without overwriting it.
   Make safe, reversible assumptions explicit. Use `ask_user` only for an
   essential ambiguity, permission, credential, or decision; if unavailable,
   persist a blocker rather than guess.
2. Resolve `SKILL_DIR` to the directory containing this skill, **not** the project
   directory. Use `STATE=<project-root>/.ralph-loop`. Keep all loop state inside
   the target project. Do not follow state-directory symlinks outside it.
   The skill is named `looper`: canonical `skills/looper/`, installed
   `~/.copilot/skills/looper/`. Retain the existing
   `.ralph-loop/` state directory and `ralph-loop-pass-ledger-v1` protocol marker
   for backward compatibility. Renaming the skill never migrates state, resets
   the budget, or discards prior histories.
3. Before initialization, look for `STATE`. If it exists, read `state.md`,
   `progress.md`, and the pass ledger. If `STATE` is missing but prior loop
   evidence, logs, or temporary state remain, stop and reconcile them; never
   assume a fresh budget. **Resume; never recopy templates, clear history,
   reset the budget, or start a second loop to escape the limit.**
   A different request does not authorize discarding the existing goal:
   resolve the conflict with the user, or checkpoint it as blocked.
4. For a new loop, initialize with the bundled helper:

   ```bash
   bash "$SKILL_DIR/scripts/pass-ledger.sh" "$STATE" init
   ```

   Copy `templates/state.md` to `STATE/state.md` once; fill in the original
   request verbatim, project root, scope, assumptions, and acceptance criteria.
   Create `STATE/progress.md` for append-only checkpoint entries.
5. Translate the request into numbered **AC01, AC02, …** criteria. Each needs
   an observable assertion, a concrete verification command/procedure, expected
   output, and a failure condition. Include requested behavior, edge cases,
   compatibility, and relevant quality requirements. Existence-only checks are
   insufficient for semantic requirements. Do not mark untested items passed.
6. Break criteria into small **S01, S02, …** steps, each with dependencies,
   affected criteria, and a check that can fail independently. Preserve stable
   IDs. Do not remove, weaken, skip, or redefine a criterion to obtain green
   results. Record necessary additions; material scope changes need user approval.

Initial read-only discovery and planning do not consume a pass. Every subsequent
deliverable edit or acceptance/baseline test run must belong to a reserved pass.
Use `bash`, `view`, `edit`, `create`, `grep`, and `glob` as available. Session
`sql` todos may mirror the plan, but are never the durable authority. Do not
rely on conversation memory, background self-invocation, or recursive delegation.

### State layout and authority

```text
.ralph-loop/
  format                 # helper protocol marker
  state.md               # goal, criteria, task graph, latest evidence, next action
  progress.md            # append-only decisions, failures, checkpoints
  passes/01..20/
    reservation          # immutable mode, target, reservation time
    result               # immutable passed / failed / blocked / interrupted
    ...                  # exact commands, outputs, exit codes, snapshots
```

The **highest reserved directory** is the authoritative number of passes used.
`state.md` is a readable projection, not permission to refund a reservation.
Update it via a sibling `state.md.new` followed by same-directory rename; append
progress before closing a pass. Stop on persistence errors: do not continue
untracked. Never put secrets in state, commands, or logs.

Before **any** state read/write, verify containment in the selected project and
reject symlink components, including inherited parent links and trailing-slash
aliases. Check `state.md`, `progress.md`, evidence output paths, and all staging
destinations: existing files must be regular, not symlinks or directories.
Never append through a multiply linked progress file. Create sibling candidates
exclusively; never truncate or reuse an existing `.new` file. Write the full
candidate, check write/rename exits, and recheck the destination before rename
so a directory cannot absorb the candidate. Preserve existing progress bytes.
On partial append/publication, retain the partial bytes and candidates as
evidence; reconcile before retrying. Preserve an obstructing candidate's contents
before safely moving it aside; never promote uncertain evidence to passing.
These checks assume cooperating local writers, not malicious concurrent pathname
replacement. Individual renames are not a multi-file transaction or a guarantee
against power loss.

## 2. Count passes mechanically

A **pass** is one durably reserved attempt at one selected step, or one final
verification attempt. A work pass has one implementation attempt, an initial
validation bundle, and **at most one repair batch and one revalidation bundle**.
If still failing, close it and use a new pass. No unbounded inner repair loop.
Final passes are read-only with respect to deliverables.

Reserve **before** edits or tests:

```bash
bash "$SKILL_DIR/scripts/pass-ledger.sh" "$STATE" status
bash "$SKILL_DIR/scripts/pass-ledger.sh" "$STATE" reserve work S01
# Prints the reserved two-digit ID; use that directory for all pass evidence.
# For final verification instead: reserve final ALL
```

- Creating `passes/NN` consumes pass NN immediately, even if a crash interrupts
  writing its metadata. Failures, blockers, interruptions, and final verification
  all count. The helper has no reset or configurable-limit operation.
- Close a checkpointed attempt with:

  ```bash
  bash "$SKILL_DIR/scripts/pass-ledger.sh" "$STATE" close 01 passed
  # Other outcomes: failed, blocked, interrupted
  ```

  `passed` means this attempt passed its checks, **not** that the request is done.
- Never allocate pass 21. Plan to leave room for final verification: a successful
  implementation in pass 20 cannot substitute for a later full verification.
  Final verification may succeed in pass 20; otherwise the run is exhausted.
- One active writer only. A second reservation is rejected while a pass is open.
  The helper's short-lived `.lock` guards ledger mutations, not project edits.
  Record the active GitHub Copilot writer's host/process/session identity and
  associated command identities, start times, and liveness observations in state.
  No `.lock` does **not** mean no active writer; never take over an open pass
  until both its writer and associated commands are demonstrably inactive.
  On a lock conflict, inspect its owner and stop; never steal a live lock.
  Remove only a demonstrably abandoned `.lock/owner` and empty `.lock` after
  proving the recorded process/host and any associated commands are inactive.
  If that cannot be established, report blocked.

### Recovery after reset or interruption

Read the goal, complete criteria/task table, checkpoints, ledger, recent logs,
and current working changes before doing anything. Run `status`. Reconcile
partial edits and side effects; never blindly repeat a deployment or migration.
Compare current tracked and untracked deliverables, relevant inputs, and
environment/configuration with the saved snapshot recipe. Mark affected
criteria stale and revoke any completion claim when they differ; if the impact
is uncertain, mark all criteria stale. Preserve the old evidence as history.
If a previous pass is open and no writer/command is alive, append a recovery
entry and close it `interrupted`, even if it appeared almost finished. Its
reservation remains spent; continue with the next number. Missing metadata
does not refund a pass and permits only an `interrupted` close. Malformed
published metadata, impossible open-pass ordering, and corrupt/gapped ledgers
must be investigated, not rewritten or rebuilt. Preserve immutable results even
when later timestamp, cleanup, or checkpoint work fails. Check the helper's exit
status, not stdout alone: a nonzero exit may follow a committed reservation or
result. Inspect disk before deciding the recovery action; never retry as fresh
work, overwrite the outcome, or refund the reservation.

Treat cached passing evidence as stale after reset or relevant project/environment
changes. Historical completion is not fresh verification. Resume remaining work,
or reserve a new final pass if everything otherwise appears ready and budget
remains. If the runtime ends, these files enable the next invocation; do not
pretend this skill runs while no GitHub Copilot session is active.

## 3. Execute one bounded work pass

1. **Select:** prioritize a regression, then an unblocked dependency, then the
   highest-impact remaining criterion. Pick one small step. Record its ID,
   acceptance mapping, hypothesis, planned commands, and expected results.
   In the first reserved work pass, run available relevant baseline test/lint/build
   commands **before the first deliverable edit**. Record existing failures
   separately, or explicitly record that no baseline validation exists.
2. **Implement:** make the smallest complete change, preserving unrelated work.
   Add focused regression/behavior checks. Never mislabel pre-existing failures
   fixed without fresh evidence.
3. **Validate:** run the selected checks and affected previously passing checks,
   plus the project's cheap regression/smoke checks. Observe actual output;
   verify that tests executed, assertions matched, and none were silently skipped.
4. **Capture evidence:** for every command save the exact invocation, working
   directory, start/end time, output, actual exit code, relevant test counts,
   observations, and AC IDs in the reserved directory. Use separate files for
   each attempt. Capture the underlying command's status, not `tee`'s; use
   `pipefail` for pipelines. Never use `|| true`, fabricated logs, or merely
   writing “verified” as proof. Set a finite deadline suitable for each command;
   a tool's wait interval is not a process timeout. Monitor/stop a hung command
   using its specific process ID if no runner timeout is available.
   Identify the implementation attempt, initial validation phase, and optional
   repair/revalidation phase separately. Record the repair-batch count (0 or 1),
   each check's execution number/count within its phase, and all flaky failures
   and no-progress history; a new evidence filename does not reset these limits.
5. **Repair once:** diagnose any failure from evidence, make one bounded repair
   batch, and rerun the failing and impacted regression checks. Further failures
   become the next pass, not an unlimited retry loop inside this pass.
6. **Checkpoint:** append changes, all evidence paths/results, failure signature,
   decisions, blockers, and the precise next action to `progress.md`; update
   `state.md` atomically; then close the pass. Continue immediately if actionable
   work remains and budget permits. Do not ask “shall I continue?” each pass.

### Exceptional cases

| Condition | Required response |
|---|---|
| No test framework | Create minimal executable validation in the project using available tools: focused assertions, a small standard-library test, schema/content checks, or a reproducible smoke test. Include a negative/edge case. For non-code work, combine deterministic checks with documented inspection of the requested substance. Human-only approval remains blocked until obtained. Do not install a framework merely for the loop. |
| Flaky or nondeterministic result | Preserve every failure. Reproduce in a controlled environment, at most **three executions per check per validation phase**, and diagnose/fix the cause. Never cherry-pick a green retry, average failures away, or silently quarantine/skip a required test. An unresolved flaky criterion is not passed. |
| Repeated failure/no progress | Track consecutive failed passes per step and failure signature. After **two** no-progress passes, re-plan before another implementation: split the step, test a new root-cause hypothesis, or change approach. Persist the new dependency graph and rationale without weakening acceptance. Do not repeat an unchanged failing attempt. |
| Blocked human input/permissions/service | Record the exact missing input, evidence, minimal question, and unblocking action. Use `ask_user` if available. Work on independent ready steps meanwhile. If all remaining work is blocked, stop honestly with a checkpoint; do not burn remaining passes polling or invent approval. |
| Previously passing criterion regresses | Immediately change it to failed/stale, reopen dependent steps, and prioritize repair. Earlier green logs cannot override current failures. Revalidate affected criteria after every change, and every criterion in the final pass. |
| New external/destructive action | Honor permissions and seek required consent. Never bypass safeguards, leak secrets, or repeat uncertain side effects just to keep the loop moving. |

## 4. Final verification gate — mandatory, separately counted

Enter a **final** pass only when every implementation step is done and every
criterion has preliminary passing evidence, with no unresolved blockers.

1. Reserve `final ALL`. Freeze deliverables. Record the criterion revision,
   environment/configuration, and a content fingerprint covering tracked,
   untracked, and non-Git deliverables. A commit SHA alone misses dirty changes.
   Save the exact snapshot command and manifest, relevant input paths/content
   and environment/configuration identifiers, and explicit exclusion reasons.
   Exclude loop logs and disposable caches, never actual deliverables or relevant
   inputs. Use the same saved recipe on resume and before/after the final gate.
2. Run **all** criterion verifiers and the relevant full test/lint/build suite,
   not just the last changed tests. For non-code requests, run the complete
   equivalent verification matrix. Recheck baseline failures: a required check
   still failing is not green because it was already broken.
3. Map each AC ID to fresh commands, outputs, exit codes, and observed assertions
   from this final pass. All required checks must actually run and pass.
   Previously flaky checks require **three fresh consecutive passes** here;
   any failure fails this final attempt. Skipped, unavailable, interrupted, or
   inconclusive checks are not passes.
4. Recompute the deliverable fingerprint and relevant-input/environment snapshot
   and check for regressions. If anything relevant changed, invalidate the final
   evidence; invalidate all criteria when the impact is uncertain. Do not repair deliverables
   inside this read-only gate: checkpoint/close `failed`, then return to a work
   pass only if capacity remains for both repair work and another separate final
   reservation; otherwise checkpoint incomplete. Any later deliverable, criterion, or environment
   change invalidates this gate and requires another counted final pass.
5. Only when the full matrix passes on the unchanged result: append/persist the
   AC-to-evidence matrix, final fingerprint, and relevant-input/environment
   snapshots **while state is still not complete**. Then close the final pass
   `passed`, check its exit, and atomically publish `state.md` as `complete` with
   its pass/evidence references. Verify successful completion publication.
   **Only now may you declare completion or call `task_complete`.** If any
   persistence operation fails, do not announce completion. A persisted `passed`
   result with a missing or failed completion checkpoint is not success on
   resume: retain it, reconcile the failure and freshness, and use a new final
   reservation if evidence was invalidated. Never change an immutable result.

## 5. Stop truthfully

At 20 reserved passes, perform no more implementation or verification commands,
even “one last quick fix.” Ledger reconciliation and a truthful status report
are allowed; finishing checks already reserved in pass 20 is allowed.
Never restart the counter, split the same goal into a fresh loop, or move work
outside the ledger to continue. Exhaustion is not success.

For success, report passes used, verified criteria, final evidence locations,
and any explicitly agreed limitations. For exhaustion or a genuine blocker,
record `exhausted`/`blocked` and report **not complete**, passes used out of 20,
what is currently verified versus stale/unverified, exact failures/blockers,
and the next actionable step. Do not call `task_complete` for incomplete work.
Use “GitHub Copilot” in full whenever naming the assistant.

## Helper contract and self-test

The helper requires Bash and a writable local project directory. It enforces
reservations and the budget, **not acceptance correctness**; the final gate above
is mandatory. Exit codes: `2` exhausted, `3` open/already closed pass, `4` locked,
`5` invalid state, `64` invalid usage. Any unexpected I/O failure is also a stop.

From `skills/looper/` (or the installed `looper` skill directory), run
`/bin/bash -n scripts/pass-ledger.sh` and
`python3 -B scripts/test_pass_ledger.py`; optionally run
`shellcheck scripts/pass-ledger.sh`. Python 3 is needed only for these
standard-library self-tests, which create and remove fixtures inside this directory.
