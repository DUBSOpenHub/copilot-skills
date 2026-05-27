# Rubric: Non-Technical Accessibility

**Version:** 1.0 · **Threshold:** 0.85 (85%) to pass · **Applied to:** Non-technical role fixtures only

## Purpose
Score `brief.md` on jargon-free language, plain vocabulary, and readability by a non-technical user. Applied only to fixtures with `role` in: `creator`, `writer`, `non-technical`, `unspecified`.

## Scoring Criteria

| Criterion | Weight | Description |
|---|---|---|
| **No unexplained jargon** | 0.30 | Technical terms either absent or explained in plain language in parentheses |
| **Sentence length** | 0.15 | ≥ 80% of sentences are 25 words or fewer |
| **Active voice** | 0.15 | ≥ 80% of sentences use active voice (subject does the action) |
| **Self-explanatory headers** | 0.20 | All section headers are understandable to a 10-year-old reading level |
| **No internal references** | 0.20 | No mention of `genome.json`, `nodes`, `edges`, `prompts`, `AGENTS.md`, or any technical infrastructure |

## Jargon Detection List

Flag if any of the following appear without an inline plain-language explanation:

`API`, `SDK`, `JSON`, `schema`, `DAG`, `OAuth`, `JWT`, `CI/CD`, `cron`, `SMTP`, `ASGI`, `endpoint`, `middleware`, `migration`, `payload`, `webhook`, `token` (in technical context), `genome`, `node`, `edge`, `prompt_template`, `acceptance_criteria`, `genome.json`, `AGENTS.md`.

**Exception:** Terms are allowed if they appear with an immediate explanation, e.g.: "OAuth (a standard way to log in with an existing account like GitHub)".

## Header Self-Explanatory Check

The following headers are always acceptable:
- `## Goal`, `## Why This Matters`, `## What We Know`, `## What We Don't Know Yet`, `## The Plan`, `## Decisions You Need to Make`, `## Risks and Watch-Outs`, `## How to Know It Worked`, `## Next Step`

Flag any custom headers that use jargon or require technical knowledge to understand.

## Scoring Guide

**0.9–1.0:** Zero unexplained jargon; short sentences; active voice; clean headers; no internal refs.

**0.85–0.89:** One minor jargon slip or one passive sentence cluster — still passes.

**0.75–0.84:** A technical term used without explanation, or internal reference leaked — FAIL.

**< 0.75:** Multiple jargon instances or internal infrastructure references in user-facing content — FAIL.

## Failure Modes

| Failure | Score impact | Recommended fix |
|---|---|---|
| Unexplained technical term | -0.10 per instance | Add inline explanation or rephrase |
| Internal artifact reference (genome.json, etc.) | -0.15 | Remove from brief; these are internal only |
| Passive voice sentence cluster (3+ in a section) | -0.05 | Rewrite in active voice |
| Header not self-explanatory | -0.10 per header | Replace with plain-language equivalent |
| Sentence > 40 words | -0.03 per instance | Break into two sentences |
