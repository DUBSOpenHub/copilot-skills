# Delivery Plan — `decompose` Skill

## Build Output Location

All files are built under the factory run directory:
```
/Users/greggcochran/.factory/runs/run-20260527-111745/skill/
```

## Install Command

```bash
SKILL_SRC=~/.factory/runs/run-20260527-111745/skill
SKILL_DST=~/.copilot/skills/decompose

mkdir -p "$SKILL_DST"
cp -r "$SKILL_SRC"/. "$SKILL_DST"/
```

## Delivery Checklist

- [x] All files in §2 file tree exist and are non-empty
- [x] `genome.schema.json` passes JSON Schema meta-validation
- [x] 9 fixture input.md files exist under `eval/fixtures/`
- [x] 2 fixture golden directories populated with genome.json, brief.md, AGENTS.md
- [x] `eval/runner.md` written with full orchestration logic
- [x] All 14 evals defined in `eval/evals/`
- [x] 4 rubrics defined in `eval/rubrics/`
- [x] `eval/scripts/validate_dag.py` runs and passes on both golden genomes
- [x] `SKILL.md` references PRD, flow, output contract, and eval suite
- [x] `docs/unresolved.md` lists open product questions
- [ ] Full interactive eval run producing `eval_report.md`
- [ ] All 9 fixture golden directories fully populated
- [ ] Sealed eval results

## Spot-Check Command

```bash
# Verify skill is installed and readable
cat ~/.copilot/skills/decompose/SKILL.md

# Validate a golden genome
cd ~/.copilot/skills/decompose
python3 eval/scripts/validate_dag.py eval/fixtures/developer-oauth/golden/genome.json
python3 eval/scripts/validate_dag.py eval/fixtures/nontechnical-newsletter/golden/genome.json
```

## Known Gaps

See `docs/unresolved.md` for open product questions.
