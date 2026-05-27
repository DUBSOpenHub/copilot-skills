# Rubric: Uncertainty Handling

**Version:** 1.0 · **Threshold:** 0.80 (80%) to pass

## Purpose
Score how explicitly and accurately the skill captures unknowns, assumptions, risks, and gates. Applied to all fixtures, critical for `ambiguous-low-context`.

## Scoring Criteria

| Criterion | Weight | Description |
|---|---|---|
| **Unknown completeness** | 0.25 | All unresolved facts from Q&A appear in genome.unknowns |
| **Assumption accuracy** | 0.20 | Every genome assumption was either stated by the user or is a clearly reasonable inference marked as such |
| **Gate accuracy** | 0.25 | Every irreversible decision in the plan is classified as a gate (not assumption) |
| **Blind spot count** | 0.15 | At least 2 blind spots surfaced per session; all classified correctly |
| **No silent assumptions** | 0.15 | No inferred facts presented as confirmed without user validation |

## Silent Assumption Detection

A silent assumption exists when:
- A genome node has `confidence >= 0.85` on a fact the user did not explicitly confirm
- A `human_decision_gate: true` node is missing from `AGENTS.md ## Human Gates`
- An `unknown` classification that should be a `gate` (irreversible decision treated as information gap)
- The `brief.md` states something as fact that was marked as `unknown` in the genome

## Gate vs Assumption Classification

| Scenario | Correct classification |
|---|---|
| Deleting auth system | `gate` |
| Sending external comms | `gate` |
| Deploying to production | `gate` |
| Framework version not stated by user | `assumption` |
| User's timeline not confirmed | `unknown` |
| Budget not mentioned | `unknown` |
| Whether tests exist | `assumption` (if typical for context) or `unknown` |

## Scoring Guide

**0.9–1.0:** All unknowns listed, all assumptions reasonable, all gates correctly classified, 2+ blind spots.

**0.8–0.89:** One minor classification error or one unknown slightly imprecise — passes.

**0.7–0.79:** Gate classified as assumption, or significant unknown silently dropped — FAIL.

**< 0.7:** Multiple gate/assumption errors, or silent assumptions throughout — FAIL.

## Failure Modes

| Failure | Score impact | Recommended fix |
|---|---|---|
| Unknown missing from genome | -0.10 per item | Add to genome.unknowns |
| Gate misclassified as assumption | -0.15 | Reclassify; add human_decision_gate: true |
| Fewer than 2 blind spots surfaced | -0.15 | Surface at least 2 per session |
| Assumption has no basis in user input | -0.10 | Either ask user to confirm, or mark as unknown |
| Silent assumption in brief.md | -0.10 | Move to "What We Don't Know Yet" section |
