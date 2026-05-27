# Eval Runner — `decompose` Skill

## Purpose
Orchestrate the full eval suite: load fixtures, run all 14 evals × 9+ fixtures, score rubrics, and write `eval_report.md`.

## Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `fixtures_dir` | dirpath | ✓ | `eval/fixtures/` |
| `evals_dir` | dirpath | ✓ | `eval/evals/` |
| `rubrics_dir` | dirpath | ✓ | `eval/rubrics/` |
| `schemas_dir` | dirpath | ✓ | `schemas/` |
| `output_dir` | dirpath | ✓ | Where to write `eval_report.md` |
| `run_id` | string | optional | Defaults to timestamp |

## Output Contract

Writes `eval_report.md` using `templates/eval_report.md.tmpl`. Must include all 7 required sections. Returns exit code 0 on all-pass, 1 on any failure.

---

## Execution Sequence

### Phase 1: Load

```
1. Enumerate all fixture directories under eval/fixtures/
2. For each fixture:
   a. Load input.md (simulated user responses + metadata)
   b. Load golden/*.json and golden/*.md from golden/ subdir
   c. Note: seeded secrets from input.md are used only by redaction eval
```

### Phase 2: Simulate

```
For each fixture × mode:
  - Replay golden artifacts as "produced" outputs (golden regression mode)
  - For open evals (role_first, task_second, question_budget):
    simulate session transcript from input.md user responses
  - For headless fixtures (headless-missing-role, headless-missing-task, headless-missing-both):
    simulate headless mode with specified args
```

### Phase 3: Run Evals

Run each eval in this order. Evals are independent; run in parallel where possible.

```
Binary evals (must-be-100%):
  1. role_first          → check first turn of each interactive fixture transcript
  2. task_second         → check second turn of each interactive fixture transcript
  3. question_budget     → check questions_asked in clarification_state
  4. schema_validity     → validate genome.json against genome.schema.json
  5. dag_validity        → run 9 DAG semantic rules against genome.json
  6. redaction           → scan all artifacts for seeded secrets
  7. headless_mode       → check headless error outputs for 3 negative cases
  8. replay              → validate replay.jsonl structure and state reconstruction
  9. golden_regression   → compare produced artifacts to golden/

Rubric evals (threshold ≥ floor):
  10. accessibility      → score brief.md for non-technical fixtures (threshold: 0.85)
  11. brief_quality      → score brief.md for all fixtures (threshold: 0.80)
  12. agent_readiness    → score AGENTS.md + genome for all fixtures (threshold: 0.80)
  13. uncertainty_handling → score unknowns/assumptions/gates (threshold: 0.80)
  14. human_gates        → verify gate structure in genome + AGENTS.md (threshold: 1.0)
```

### Phase 4: Aggregate

```
For each eval:
  pass_rate = count(pass) / count(fixtures_applicable)
  aggregate_score = mean(scores) for rubric evals

For report:
  overall_pass = all binary evals at 100% AND all rubric evals at threshold
  critical_failures = [eval for eval in binary_evals if pass_rate < 1.0]
```

### Phase 5: Write Report

```
Load eval_report.md.tmpl
Fill all template variables from aggregated results
Write to output_dir/eval_report.md
```

---

## Fixture × Eval Applicability Matrix

| Eval | nontechnical-newsletter | nontechnical-app-idea | developer-oauth | developer-bugfix | pm-beta-launch | designer-onboarding-flow | ops-incident-runbook | researcher-market-map | ambiguous-low-context |
|---|---|---|---|---|---|---|---|---|---|
| role_first | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| task_second | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| question_budget | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| accessibility | ✓ | ✓ | — | — | — | — | — | — | ✓ |
| brief_quality | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| agent_readiness | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| schema_validity | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| dag_validity | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| redaction | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| uncertainty_handling | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓★ |
| human_gates | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| headless_mode | — | — | — | — | — | — | — | — | — |
| replay | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| golden_regression | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

★ = extra-critical for this fixture (ambiguous-low-context)

Headless mode eval runs against 3 separate headless fixtures:
- `headless-missing-role`
- `headless-missing-task`
- `headless-missing-both`

---

## Running the Eval Suite

### Automated (Python runner)

```bash
cd ~/.copilot/skills/decompose
python3 eval/run_eval.py \
  --fixtures eval/fixtures \
  --output eval_report.md \
  --run-id "$(date +%Y%m%d-%H%M%S)"
```

### Manual (prompt-based)

For each fixture in `eval/fixtures/`:
1. Open `input.md` and simulate the session per user responses
2. Run each eval in `eval/evals/` against the produced artifacts
3. Score rubrics per `eval/rubrics/`
4. Record results in `eval_result.schema.json` format
5. Aggregate into `eval_report.md` using `templates/eval_report.md.tmpl`

---

## Pass / Fail Summary

| Eval | Type | Pass bar |
|---|---|---|
| role_first | binary | 100% of interactive fixtures |
| task_second | binary | 100% of interactive fixtures |
| question_budget | binary | 100% of normal fixtures |
| accessibility | rubric | ≥ 0.85 for non-technical fixtures |
| brief_quality | rubric | ≥ 0.80 for all fixtures |
| agent_readiness | rubric | ≥ 0.80 for all fixtures |
| schema_validity | binary | 100% of all fixtures |
| dag_validity | binary | 100% of all fixtures |
| redaction | binary | 100% removal (zero findings) |
| uncertainty_handling | rubric | ≥ 0.80 for all fixtures |
| human_gates | binary | 100% of gate fixtures |
| headless_mode | binary | 100% of headless error cases |
| replay | binary | 100% of replay fixtures |
| golden_regression | binary | 100% golden match |

**Overall pass:** All 14 evals pass their required bar.

---

## Failure Escalation

Any failure in a binary eval → block delivery. Do not mark delivery complete.
Rubric eval failure below threshold → block delivery. Document in `docs/unresolved.md`.
Redaction finding → immediate escalation. Do not write artifact.

---

## eval_report.md Location

Written to: `eval_report.md` in the skill root directory.
Also archived to: `eval/runs/{run_id}/eval_report.md` for history.
