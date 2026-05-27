# Rubric: Agent Readiness

**Version:** 1.0 · **Threshold:** 0.80 (80%) to pass

## Purpose
Score the `AGENTS.md` and per-node prompt configuration for executability by a downstream agent without re-asking known context.

## Scoring Criteria

| Criterion | Weight | Description |
|---|---|---|
| **Start node identified** | 0.15 | `## Start Here` section names a specific executable node ID |
| **Prompt coverage** | 0.25 | Every non-milestone node has a non-empty `prompt_template` in genome |
| **Acceptance criteria coverage** | 0.20 | Every non-milestone, non-human-gated node has ≥ 1 verifiable acceptance criterion |
| **Human gates listed** | 0.15 | `## Human Gates` section in AGENTS.md lists all gate node IDs from genome |
| **Do Not Assume populated** | 0.10 | `## Do Not Assume` lists all open unknowns from genome |
| **Goal stated in one sentence** | 0.05 | `## Goal` is present and a single sentence |
| **Nodes section complete** | 0.10 | Each node entry includes type, description, owner_hint, and acceptance criteria |

## Required AGENTS.md Sections

- [ ] `## Role`
- [ ] `## Goal`
- [ ] `## Nodes` (one entry per genome node)
- [ ] `## Human Gates`
- [ ] `## Do Not Assume`
- [ ] `## Start Here`

## Scoring Guide

**0.9–1.0:** All nodes have prompts and acceptance criteria; gates listed; unknowns listed; start node clear.

**0.8–0.89:** One minor gap (e.g., one node's acceptance criteria slightly vague) — still passes.

**0.7–0.79:** Missing gate in AGENTS.md, or node missing prompt_template — FAIL.

**< 0.7:** Multiple prompt gaps, missing start node, or gates not listed — FAIL.

## Failure Modes

| Failure | Score impact | Recommended fix |
|---|---|---|
| No `## Start Here` | -0.15 | Add section; derive from `handoff.start_node_id` |
| Node missing prompt_template (non-milestone) | -0.10 per node | Add prompt_template reference from prompt_library |
| Gate node not in `## Human Gates` | -0.10 per gate | Add all gate node IDs |
| Node missing acceptance_criteria | -0.08 per node | Derive 1–2 verifiable criteria from description |
| `## Do Not Assume` missing unknowns | -0.05 per unknown | Add from genome.unknowns + handoff.do_not_assume |
| `## Goal` is multiple sentences | -0.05 | Condense to one sentence |
