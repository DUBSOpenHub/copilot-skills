# SKILL.md — `decompose` Copilot CLI Skill

**Version:** 1.0 · **PRD:** `PRD.md` · **Architecture:** see `ARCH.md` in build directory

---

## What This Skill Does

`decompose` converts any fuzzy human goal into a role-aware, agent-readable execution plan.

It acts as an **intent compiler**: it asks who you are, what you want, and what you don't know — then produces two artifacts:

- **`brief.md`** — a plain-language plan readable by anyone
- **`genome.json`** — a structured execution plan for downstream agents

Say "decompose" to start.

---

## Pipeline (Step by Step)

```
1. Role Lens         → First output: who are you? (adapts everything)
2. Intent Capture    → What do you want? (redaction runs here)
3. Understanding Meter → How much do I know? (displayed every turn)
4. Socratic Bandit   → 3–7 adaptive clarifying questions
5. Blind Spot Engine → Surfaces assumptions, unknowns, risks, and gates
6. Reflection Mirror → Restates intent; you confirm before artifacts are written
7. Synthesis         → Emits brief.md + genome.json + AGENTS.md + replay.jsonl
```

---

## How to Start

### Interactive mode
```
> decompose
```

### Headless mode
```
> decompose --role developer --task "Add GitHub OAuth to my API"
```

### Replay a previous session
```
> decompose --replay ./replay.jsonl
```

---

## Output Files

| File | Audience | Description |
|---|---|---|
| `brief.md` | You / your team | Plain-language plan with goal, steps, decisions, risks |
| `genome.json` | Downstream agents | Structured DAG with nodes, edges, prompts, acceptance criteria |
| `AGENTS.md` | Downstream agents | Execution pack: start here, gates, do-not-assume list |
| `replay.jsonl` | Replay / audit | Append-only session log; enables headless rehydration |
| `eval_report.md` | Evaluators | Full eval suite results (produced on eval runs only) |

---

## Output Contract

**brief.md:** Must be valid Markdown. Must contain all 9 required sections. Must be readable by a non-technical user in all non-technical role fixtures. Must not reference internal tooling (genome.json, AGENTS.md, nodes, prompts).

**genome.json:** Must validate against `schemas/genome.schema.json` (Draft 7). Must pass all 9 DAG semantic rules. Must be emitted only after Validation Gate passes. Must never contain secrets or chain-of-thought.

**AGENTS.md:** Must expose Role, Goal, Nodes, Human Gates, Do Not Assume, and Start Here sections. Must match genome gate nodes exactly.

**replay.jsonl:** Append-only. Must not contain `raw_intent`. Must contain at least: `intent_captured`, `question_asked` ×3–7, `blind_spots_surfaced`, `reflection_confirmed`.

---

## Safety Invariants

| Invariant | Enforced by |
|---|---|
| First output is always a role question | `prompts/role_lens.md` |
| Task blocked until role established | `prompts/role_lens.md` guardrails |
| Redaction at input and output | `prompts/intent_capture.md` + Validation Gate |
| No artifact written before user confirms | `prompts/reflection_mirror.md` |
| Human gates not auto-resolved | DAG validator + `prompts/task_genome_synthesis.md` |
| No secrets in any artifact | Redaction pipeline + `eval/evals/redaction.md` |
| No chain-of-thought in output | Guardrails in every prompt file |
| Headless missing inputs → clear error | `prompts/rehydration.md` (FR-12) |

---

## Eval Suite

**14 evals × 9+ fixtures = 126+ eval records per run.**

| Eval | Type | Pass bar |
|---|---|---|
| role_first | binary | 100% |
| task_second | binary | 100% |
| question_budget | binary | 100% |
| schema_validity | binary | 100% |
| dag_validity | binary | 100% |
| redaction | binary | 100% |
| headless_mode | binary | 100% |
| replay | binary | 100% |
| golden_regression | binary | 100% |
| human_gates | binary | 100% |
| accessibility | rubric | ≥ 85% |
| brief_quality | rubric | ≥ 80% |
| agent_readiness | rubric | ≥ 80% |
| uncertainty_handling | rubric | ≥ 80% |

Run the eval suite: see `eval/README.md` and `eval/runner.md`.

Validate a genome: `python3 eval/scripts/validate_dag.py <genome.json>`

---

## File Structure

```
~/.copilot/skills/decompose/
├── SKILL.md
├── PRD.md
├── prompts/
│   ├── role_lens.md
│   ├── intent_capture.md
│   ├── socratic_bandit.md
│   ├── blind_spot_engine.md
│   ├── reflection_mirror.md
│   ├── task_genome_synthesis.md
│   ├── markdown_brief.md
│   └── rehydration.md
├── schemas/
│   ├── genome.schema.json
│   ├── clarification.schema.json
│   └── eval_result.schema.json
├── templates/
│   ├── brief.md.tmpl
│   ├── AGENTS.md.tmpl
│   ├── eval_report.md.tmpl
│   └── prompt_library/
│       ├── research.md
│       ├── code_change.md
│       ├── decision.md
│       ├── comms.md
│       ├── review.md
│       ├── risk.md
│       └── unknown.md
├── examples/
│   ├── nontechnical-newsletter.md
│   ├── developer-oauth.md
│   ├── pm-beta-launch.md
│   └── ops-incident-runbook.md
├── eval/
│   ├── README.md
│   ├── runner.md
│   ├── rubrics/ (4 rubrics)
│   ├── evals/ (14 evals)
│   ├── fixtures/ (9 fixtures)
│   └── scripts/validate_dag.py
└── docs/
    ├── delivery.md
    └── unresolved.md
```

---

## Key Constraints (Non-Goals)

- Does NOT execute work units
- Does NOT track projects over time
- Does NOT expose internal scoring or chain-of-thought
- Does NOT require users to understand JSON
- Does NOT auto-resolve human decision gates

---

## PRD Reference

See `PRD.md` for the complete product spec including all functional requirements (FR-1 through FR-14), safety requirements (SP-1 through SP-5), and acceptance criteria.

---

*Built by Dark Factory · Skill version 1.0 · `decompose` intent compiler*
