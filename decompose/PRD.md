# PRD: `decompose` — Copilot CLI Skill
**Version:** 1.0 · **Status:** Approved for Dark Factory Build

---

## Overview
`decompose` converts any fuzzy human goal into a role-aware, agent-readable execution plan. It is an intent compiler: `Role Lens → Intent Capture → Socratic Q&A → Reflection Mirror → Task Genome → Human Brief → Agent Pack`.

---

## Problem Statement
Users hand vague goals to AI agents and receive poorly-scoped, jargon-heavy outputs. Agents assume missing facts, skip approval gates, and expose secrets in artifacts. No existing skill bridges human intent and agent execution with role awareness, uncertainty transparency, and safety guarantees.

---

## Goals & Non-Goals

**Goals:** Ask role before task (always). Accept plain-language goals. Ask 3–7 adaptive clarifying questions. Surface assumptions, unknowns, risks, blind spots, and human gates explicitly. Emit a human brief readable by non-technical users. Emit a Task Genome executable by downstream agents. Validate all artifacts before delivery. Pass a sealed full eval suite.

**Non-Goals (MVP):** Does not execute work units. Does not track projects. Does not require users to understand JSON. Does not support multi-user conflict resolution. Does not sync to cloud. Does not expose internal scoring or chain-of-thought.

---

## Personas & User Stories

| Persona | Story |
|---|---|
| Non-technical creator | Describe an idea in plain language; receive a plan I can hand to an agent without understanding prompts or JSON. |
| Developer | Break a feature or bug into executable units with stack context, acceptance criteria, and per-node prompts. |
| PM / team lead | Convert an outcome into scoped work with stakeholders, success metrics, dependencies, risks, and gates. |
| Designer | Turn a design goal into ordered research/prototype/build tasks with review criteria and asset references. |
| Ops / support | Plan incident or process work with urgency, approvals, rollback, and runbook needs captured. |
| Downstream agent | Read `AGENTS.md` and `genome.json` to begin execution without re-asking known context. |

---

## Interaction Flow

**Step 1 · Role Lens** — First output is always a role question. No task is accepted before role is established or explicitly deferred. Role adapts all subsequent vocabulary, depth, and question selection.

**Step 2 · Intent Capture** — Accepts plain English, pasted notes, issue text, or rough ideas. Redaction guidance runs before any input is persisted.

**Step 3 · Understanding Meter** — Displays percent understood, known items, unknown items, and the next highest-value question. Must be interpretable by non-technical users.

**Step 4 · Socratic Bandit Q&A** — One question at a time, selected by expected information gain across: success criteria, scope, constraints, stakeholders, dependencies, risks, assets, acceptance criteria, approval gates, output format. Terminates at sufficient confidence or question budget (3–7).

**Step 5 · Blind Spot Engine** — Surfaces missed concerns before final output, each classified as: assumption, unknown, risk, or human decision gate.

**Step 6 · Reflection Mirror** — Restates captured intent in plain language. User confirms or corrects before any artifact is written.

**Step 7 · Dual Output** — Emits `brief.md`, `genome.json`, `AGENTS.md`, `eval_report.md` (eval runs), and `replay.jsonl`.

---

## Functional Requirements

| ID | Requirement |
|---|---|
| FR-1 | First user-facing output of every interactive session is a role question. |
| FR-2 | Task input is blocked until role is established or explicitly deferred. |
| FR-3 | Clarifying questions number 3–7 per normal interactive session. |
| FR-4 | Understanding Meter shows knowns, unknowns, and plain-language gap explanation. |
| FR-5 | Blind Spot Engine classifies every concern as assumption, unknown, risk, or gate. |
| FR-6 | Reflection Mirror requires user confirmation before artifacts are written. |
| FR-7 | `brief.md` is readable and actionable without technical knowledge. |
| FR-8 | `AGENTS.md` allows a downstream agent to begin without re-asking captured context. |
| FR-9 | `genome.json` conforms to `genome.schema.json` and passes DAG semantic validation. |
| FR-10 | Redaction removes secrets, tokens, keys, and sensitive personal data from all artifacts. |
| FR-11 | Human decision gates block agent-owned successor nodes from being marked ready. |
| FR-12 | Headless mode requires role and task; missing either returns a clear error, not a silent guess. |
| FR-13 | `replay.jsonl` is append-only and sufficient to reconstruct session state. |
| FR-14 | Eval suite produces `eval_report.md` with all required sections on every run. |

---

## Non-Functional & Safety Requirements

**NF-1** User-facing text is jargon-free when role lens is non-technical. **NF-2** All primary outputs are valid Markdown before JSON is inspected. **NF-3** Skill is self-contained under `~/.copilot/skills/decompose/`. **NF-4** No artifact references internal prompts, scoring models, or chain-of-thought. **NF-5** Skill degrades gracefully when optional context is absent.

**SP-1** No secret, credential, token, or sensitive personal data in any written artifact. **SP-2** Unresolved ambiguity is an explicit unknown or gate — never silently assumed. **SP-3** Agent nodes must not bypass or auto-resolve human decision gates. **SP-4** Irreversible decisions are not inferred from insufficient input. **SP-5** Redaction runs before any artifact is written.

---

## Artifact & File Requirements

`SKILL.md` · `PRD.md` · `prompts/role_lens.md` · `prompts/intent_capture.md` · `prompts/socratic_bandit.md` · `prompts/reflection_mirror.md` · `prompts/blind_spot_engine.md` · `prompts/task_genome_synthesis.md` · `prompts/markdown_brief.md` · `prompts/rehydration.md` · `schemas/genome.schema.json` · `schemas/clarification.schema.json` · `schemas/eval_result.schema.json` · `templates/brief.md.tmpl` · `templates/AGENTS.md.tmpl` · `templates/eval_report.md.tmpl` · `templates/prompt_library/{research,code_change,decision,comms,review,risk,unknown}.md` · `examples/{nontechnical-newsletter,developer-oauth,pm-beta-launch,ops-incident-runbook}.md`

Each prompt file must contain: Purpose · Inputs · Output contract · Guardrails · Examples · Failure behavior.

---

## Task Genome Requirements

**Top-level fields:** `genome_id`, `schema_version`, `role`, `intent`, `nodes`, `edges`, `assumptions`, `unknowns`, `blind_spots`, `open_questions`, `meta`, `handoff`

**Per-node fields:** `id`, `title`, `type`, `description`, `prompt_template`, `inputs`, `outputs`, `acceptance_criteria`, `assumptions`, `unknowns`, `confidence`, `risk`, `parallelizable_with`, `owner_hint`, `human_decision_gate`

**Node types:** `research` · `decision` · `code_change` · `comms` · `review` · `risk` · `unknown` · `milestone`  
**Edge types:** `blocks` · `informs` · `optional`

**DAG validation must reject:** cycles · orphaned nodes · edges to missing IDs · executable nodes without acceptance criteria · agent-owned nodes without prompt templates · human-gated nodes marked ready · unknowns with no resolution strategy · low-confidence inferred tasks treated as facts.

---

## Full Eval Suite Requirements

| Eval | Validates | Pass bar |
|---|---|---|
| Role-first | First question is role-oriented | 100% of interactive fixtures |
| Task-second | Task capture follows role | 100% of interactive fixtures |
| Question budget | 3–7 questions asked | 100% of normal fixtures |
| Non-technical accessibility | Brief avoids jargon, explains value | All non-technical fixtures pass rubric |
| Human brief quality | Brief is clear, complete, actionable | Rubric score ≥ threshold |
| Agent pack readiness | AGENTS.md and node prompts are executable | Rubric score ≥ threshold |
| Schema validity | genome.json validates | 100% of fixtures |
| DAG validity | No cycles, orphans, or invalid edges | 100% of fixtures |
| Redaction | Seeded secrets absent from all artifacts | 100% removal |
| Uncertainty handling | Unknowns and assumptions are explicit | All ambiguous fixtures pass |
| Human gates | Irreversible choices block agent nodes | All gate fixtures pass |
| Headless mode | Missing role/task returns clear error | All negative headless cases pass |
| Replay | Replay reconstructs identical state | All replay fixtures pass |
| Golden regression | Approved golden outputs remain stable | 100% golden match |

**Required fixtures (minimum 9):** `nontechnical-newsletter` · `nontechnical-app-idea` · `developer-oauth` · `developer-bugfix` · `pm-beta-launch` · `designer-onboarding-flow` · `ops-incident-runbook` · `researcher-market-map` · `ambiguous-low-context`

**`eval_report.md` must include:** summary table · fixture-level results · failures and diffs · schema validation · redaction findings · agent-readiness score · accessibility score · recommended fixes.

---

## Acceptance Criteria

- [ ] `PRD.md` exists, is complete Markdown, and is self-contained as a build spec.
- [ ] `SKILL.md` references PRD, flow, output contract, and eval suite.
- [ ] Every interactive session's first output is a role question — zero exceptions across all fixtures.
- [ ] Task question appears second in every interactive fixture.
- [ ] Clarifying loop produces 3–7 questions for all normal interactive fixtures.
- [ ] Understanding Meter is interpretable by a non-technical user in all fixtures.
- [ ] Reflection Mirror appears before artifact emission in all interactive fixtures.
- [ ] `brief.md` passes non-technical accessibility rubric for all non-technical fixtures.
- [ ] `AGENTS.md` passes agent pack readiness rubric for all fixtures.
- [ ] `genome.json` validates against `genome.schema.json` for all fixtures.
- [ ] DAG validator rejects all seeded cycle, orphan, missing-edge, and gate violations.
- [ ] Redaction eval confirms zero seeded secrets in any written artifact.
- [ ] Full eval suite produces `eval_report.md` on every run.
- [ ] Headless mode returns a clear error for all negative test cases.
- [ ] Dark Factory returns sealed eval results before delivery is declared complete.

---

## Out of Scope
Executing work units · persistent task tracking · multi-user conflict resolution · cloud sync · exposing internal scoring · auto-resolving human gates.

---

## Dark Factory Delivery Expectations
1. Treat this document as the product source of truth.
2. Build Markdown prompts and templates before adding JSON schemas.
3. Build and run the full eval suite before any delivery claim.
4. Return implementation notes, `eval_report.md`, and unresolved product questions.
5. **Delivery is not complete until `eval_report.md` exists, all acceptance criteria are checked, and a sealed build summary is returned.**
