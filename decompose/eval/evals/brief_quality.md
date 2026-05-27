# Eval: Brief Quality

**ID:** `brief_quality`
**Pass bar:** Rubric score ≥ 0.80 for all fixtures

## Purpose
Score `brief.md` on clarity, completeness, and actionability using `rubrics/brief_quality.md`.

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `brief_md_path` | filepath | ✓ |
| `genome_json_path` | filepath | ✓ |

## Output Contract

```json
{
  "eval_id": "brief_quality",
  "fixture_id": "<id>",
  "pass": true | false,
  "score": 0.0–1.0,
  "threshold": 0.80,
  "diff": "<criterion failures>",
  "rubric_breakdown": {},
  "notes": ""
}
```

## Check Logic

```
1. Load brief.md and genome.json.
2. Check all 9 required sections are present.
3. Score each rubric criterion:
   a. Goal clarity: is ## Goal one sentence, plain language, accurate?
   b. Plan completeness: does ## The Plan cover all genome nodes (non-gate)?
   c. Human gate accuracy: all human_decision_gate:true nodes in ## Decisions?
   d. Unknowns accuracy: genome.unknowns match ## What We Don't Know Yet?
   e. Risk coverage: high/critical risk nodes appear in ## Risks and Watch-Outs?
   f. Next step clarity: ## Next Step is one actionable sentence?
4. Weighted score (see rubric weights).
5. PASS if score >= 0.80.
```

## Section Presence Check

Required sections (checked by header name):
```python
REQUIRED_SECTIONS = [
    "## Goal",
    "## Why This Matters",
    "## What We Know",
    "## What We Don't Know Yet",
    "## The Plan",
    "## Decisions You Need to Make",
    "## Risks and Watch-Outs",
    "## How to Know It Worked",
    "## Next Step"
]
```

Score penalty: -0.05 per missing section (capped at -0.40).

## Gate Accuracy Check

```python
def check_gate_accuracy(brief_text: str, genome: dict) -> float:
    gate_nodes = [n for n in genome["nodes"] if n.get("human_decision_gate")]
    if not gate_nodes:
        return 1.0
    decisions_section = extract_section(brief_text, "## Decisions You Need to Make")
    found = sum(1 for n in gate_nodes if n["title"] in decisions_section
                or n["id"] in decisions_section)
    return found / len(gate_nodes)
```

## Fail Examples

```
Missing section "## Decisions You Need to Make" | Score: -0.05 (section) + -0.20 (gate criterion)
Gate node 'approve_launch' not in Decisions section | Criterion score: 0.5
"Next Step" is 3 sentences | Criterion score: 0.6
```

## Failure Behavior

- `brief.md` missing → `pass: false, score: 0.0, notes: "brief.md not found."`
- `genome.json` missing → use brief.md only; skip genome-cross-checks; note in report.
