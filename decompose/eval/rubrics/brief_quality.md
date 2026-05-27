# Rubric: Human Brief Quality

**Version:** 1.0 · **Threshold:** 0.80 (80%) to pass

## Purpose
Score the `brief.md` output on clarity, completeness, and actionability. Applied to all fixtures.

## Scoring Criteria

Score each criterion 0.0–1.0. Final score = weighted average.

| Criterion | Weight | Description |
|---|---|---|
| **Goal clarity** | 0.20 | Goal section is one sentence, plain language, and accurately reflects confirmed intent |
| **Plan completeness** | 0.20 | All major work steps are present; none are missing or described so vaguely as to be unactionable |
| **Human gate accuracy** | 0.20 | All human decision gates from genome are listed in "Decisions You Need to Make"; none are omitted or mislabeled |
| **Unknowns accuracy** | 0.15 | "What We Don't Know Yet" matches unknowns in genome; no unknowns silently dropped |
| **Risk coverage** | 0.15 | All high/critical risks from genome appear in "Risks and Watch-Outs" |
| **Next step clarity** | 0.10 | "Next Step" section is a single, actionable sentence pointing to the first executable step |

## Scoring Guide

**0.9–1.0:** Goal is crisp; all steps present and detailed; gates, unknowns, and risks complete; next step unambiguous.

**0.8–0.89:** One minor gap (e.g., one risk slightly vague, next step slightly broad) — still passes.

**0.7–0.79:** Noticeable gap in one major section (missing gate, vague plan step, or incorrect unknown count) — FAIL.

**< 0.7:** Multiple major gaps or fundamental accuracy problems — FAIL.

## Required Checks

- [ ] `## Goal` section exists and is one sentence
- [ ] `## The Plan` section has at least one numbered step
- [ ] `## Decisions You Need to Make` matches gate nodes in genome (count and substance)
- [ ] `## What We Don't Know Yet` is not empty unless all unknowns were resolved
- [ ] `## Risks and Watch-Outs` contains at least one item
- [ ] `## Next Step` exists and is actionable
- [ ] All 9 required sections present

## Failure Modes

| Failure | Score impact | Recommended fix |
|---|---|---|
| Missing `## Goal` section | -0.20 | Regenerate brief from template |
| Gate in genome not in brief | -0.15 per gate | Add gate to "Decisions" section |
| Unknown in genome not in brief | -0.10 per unknown | Add to "What We Don't Know Yet" |
| High/critical risk not in brief | -0.10 per risk | Add to "Risks and Watch-Outs" |
| "Next Step" is missing | -0.10 | Derive from first executable node in genome |
| Brief references genome internals | -0.10 | Remove all internal references |
