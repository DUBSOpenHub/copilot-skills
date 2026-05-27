# Decompose Skill — Eval Report

**Generated:** 2026-05-27T21:35:24Z  
**Script:** materialize_outputs.py  
**Open Eval Suite:** 21 checks × 9 fixtures = 189 total

## Summary

| Metric | Count |
|---|---:|
| Fixtures evaluated | 9 |
| Checks per fixture | 21 |
| Total checks | 189 |
| Passed | 189 |
| Failed | 0 |
| Pass rate | 100% |

## Per-Fixture Results

| Fixture | Schema | DAG | Brief | AGENTS | Replay | Status |
|---|---|---|---|---|---|---|
| nontechnical-newsletter | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| nontechnical-app-idea | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| developer-oauth | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| developer-bugfix | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| pm-beta-launch | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| designer-onboarding-flow | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| ops-incident-runbook | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| researcher-market-map | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| ambiguous-low-context | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |

## Headless Negative Cases

| Case | Error Present | Required Flag Mentioned | Status |
|---|---|---|---|
| headless-missing-role | ✅ | ✅ | PASS |
| headless-missing-task | ✅ | ✅ | PASS |
| headless-missing-both | ✅ | ✅ | PASS |

## Artifact Inventory

| Artifact | Count | Path Pattern |
|---|---|---|
| transcript.md | 9 | eval/fixtures/*/output/transcript.md |
| replay.jsonl | 9 | eval/fixtures/*/output/replay.jsonl |
| genome.json | 9 | eval/fixtures/*/output/genome.json |
| brief.md | 9 | eval/fixtures/*/output/brief.md |
| AGENTS.md | 9 | eval/fixtures/*/output/AGENTS.md |
| headless_result.json | 3 | eval/fixtures/headless-*/output/headless_result.json |

---
*All checks pass. Run `python3 eval/scripts/run_open_eval.py` for detailed rubric scores.*
