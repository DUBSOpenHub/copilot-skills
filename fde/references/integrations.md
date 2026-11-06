# Integration contracts

## Ownership and execution modes

FDE is the engagement layer; Looper is the only implementation/evidence owner.
Havoc Hackathon owns design exploration; Dark Factory supplies the construction
role contract. These integrations do not require changing any dependency.

| Engine | Input | Output | Gate |
|---|---|---|---|
| Looper | Original request, project, stable acceptance IDs, dependency graph | Reserved passes, exact command evidence, final fingerprint/verdict | `complete=yes` plus published complete state |
| Havoc Hackathon | Same brief for all candidates, constraints, public rubric | Alternatives, evidence-backed selection/synthesis, provenance | Selected design recorded before build |
| Dark Factory | Approved brief/blueprint, tests mapped to acceptance IDs | Built skill, validation/gap report, delivery and outcome plan | No required gaps; delivery decision respected |

Record one of these modes per engine in the blueprint and delivery:

- **native**: the actual skill ran. Record its invocation/session and durable
  artifacts. Follow its real phases and checkpoints, not merely this summary.
- **proxy**: this session applies the documented design/role pattern. No claim
  that the native engine, multi-model judging, or independent QA ran.
- **blocked**: unavailable dependency, permissions, required model, or isolation.
  Record the exact missing capability and unblock action.
- **not-requested**: design-only/status scope excluded this engine.

Default: native Looper, proxy Havoc design, proxy Dark Factory roles. Tell the
user these modes before work. Availability does not imply execution. A successful
`doctor` is resource discovery only; it is not native model/tool authentication.

## Looper adapter

Read the installed `looper/SKILL.md` and use its actual helper:

```bash
SKILL_DIR="<resolved-looper-directory>"
STATE="<project>/.ralph-loop"
bash "$SKILL_DIR/scripts/pass-ledger.sh" "<project>" loops
# Reconcile existing loops before init or reserve.
bash "$SKILL_DIR/scripts/pass-ledger.sh" "$STATE" reserve work S01
bash "$SKILL_DIR/scripts/pass-ledger.sh" "$STATE" run 01 \
  --label skill-contract --ac AC01 --timeout 120 -- \
  python3 -B "<resolved-fde-directory>/scripts/fde.py" validate "<built-skill>"
```

Use the printed pass ID, never hardcode `01` on resume. Follow Looper's complete
initialization, containment, writer/liveness, baseline, repair, checkpoint,
snapshot, final gate, and completion publication requirements. FDE's `.fde/`
artifacts are engagement inputs/deliverables, not a replacement pass ledger.

Each design/build/rework step that changes deliverables needs a reserved work
pass. Every child command/check must go through the outer ledger; a child role
cannot quietly perform a second repair cycle. At two no-progress passes,
re-plan without weakening acceptance. Never reserve pass 21.

## Havoc Hackathon adapter

Proxy design comparison is performed directly, not by invoking
`havoc-hackathon` as an agent. Compare three materially different approaches,
write a tradeoff table, and preserve useful dissent. Attribute all reasoning to
the current session. Do not fake numeric judge panels or ELO updates.

For **native** execution, require the user to request a real competition and
confirm scope/tier with the engine's own prompts. Invoke the skill, not the
mass-spawner agent. Follow its actual competition phases, judge separation,
scope isolation, merge choice, and final synthesis. Do not let its optional
Dark Factory offer recursively start a second construction pipeline: finish
the design handoff and return to the outer FDE/Looper owner.

If native behavior cannot honor the bounded outer ledger, configured permissions,
or no-recursion contract, block that path and offer proxy mode. Do not pass an
adapter label that the engine does not understand as though it were a supported
API. No token-burning model availability probes unless actually needed.

## Dark Factory adapter

The installed factory has **six specialist roles**, not a generic
"builder/tester/reviewer" chain:

| Role | FDE responsibility | Artifact / evidence |
|---|---|---|
| Product Manager | Workflow outcome, fit, scope, success criteria | `brief.md` |
| QA Sealed | Independent behavior probes based only on agreed requirements | Isolated test context, sealed hash/manifest, or honest open-test limitation |
| Architect | Trigger, tool/data contracts, error handling, file plan | `blueprint.md` |
| Lead Engineer | Tailored skill/resources and open tests | Skill tree, own validation results |
| QA Validator | Run all open and available independent acceptance checks | `evaluation.md`, observed gaps, actual counts |
| Outcome Evaluator | Compare shipped outcomes to original need after use | Outcome section in `delivery.md` |

In **proxy** mode, apply these responsibilities in order with architecture and
QA specification before implementation. The current context seeing test source
means it is open testing, even when the file is in a directory named "sealed".
If sealed testing is required, use a separate bounded QA leaf context that
receives only public requirements; keep its tests inaccessible to builders.
Store the manifest/hash and have an independent validator run them. Never pass
sealed source to builders; send only observed expected/actual failure summaries.
Verify hashes again before validation. A mismatch blocks delivery.

In **native** mode, read the engine's `config.yml` first, then its actual skill.
Honor its full/express phases and approval checkpoints, including final delivery.
Discover available models; configuration strings are not proof of availability.
Do not rewrite the factory config or silently select replacements.

Factory retries/hardening fit inside Looper's remaining allowance. "Continue
hardening" cannot reset Looper's budget; one repair batch per work pass still
applies. Factory worktrees may not conceal edits or tests from the outer
fingerprint. Before copying/merging results, preserve unrelated user changes,
confirm required approval, then reverify the final delivered tree.

## Conflict and interruption resolution

Honor higher-priority instructions and user permissions first. Native engine
contracts still apply; proxy mode cannot be represented as native execution.
When engine rules conflict, stop that stage and record a concrete blocker;
do not ignore a checkpoint, bypass isolation, or silently change execution mode.

After interruption inspect the outer ledger and any native engine state before
replay. Reconcile non-idempotent effects, open commands, branches, and incomplete
copies. Mark affected evidence stale and reverify; no automatic deletion,
force-merge, budget reset, fleet launch, or unattended continuation.
