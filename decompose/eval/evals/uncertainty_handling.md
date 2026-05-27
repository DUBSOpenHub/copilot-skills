# Eval: Uncertainty Handling

**ID:** `uncertainty_handling`
**Pass bar:** Rubric score ≥ 0.80 · Critical for `ambiguous-low-context` fixture

## Purpose
Score how explicitly and accurately the skill surfaces unknowns, assumptions, risks, and gates. Uses `rubrics/uncertainty_handling.md`.

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `genome_json_path` | filepath | ✓ |
| `clarification_state_path` | filepath | ✓ |

## Output Contract

```json
{
  "eval_id": "uncertainty_handling",
  "fixture_id": "<id>",
  "pass": true | false,
  "score": 0.0–1.0,
  "threshold": 0.80,
  "rubric_breakdown": {},
  "diff": "",
  "notes": ""
}
```

## Check Logic

```python
def score_uncertainty(genome: dict, state: dict) -> dict:
    scores = {}

    # Unknown completeness: Q&A log unknowns appear in genome.unknowns
    qa_unknowns = [q for q in state.get("questions_log", []) if not q["answer"].strip()]
    genome_unknowns = genome.get("unknowns", [])
    if qa_unknowns:
        covered = sum(1 for q in qa_unknowns
                      if any(q["category"] in u.lower() for u in genome_unknowns))
        scores["unknown_completeness"] = covered / len(qa_unknowns)
    else:
        scores["unknown_completeness"] = 1.0

    # Assumption accuracy: genome assumptions stated or reasonably inferred
    assumptions = genome.get("assumptions", [])
    blind_spots = genome.get("blind_spots", [])
    assumption_bs = [bs for bs in blind_spots if bs["classification"] == "assumption"]
    scores["assumption_accuracy"] = 1.0 if len(assumption_bs) >= 1 else 0.5

    # Gate accuracy: irreversible decisions are gates, not assumptions
    gate_nodes = [n for n in genome["nodes"] if n.get("human_decision_gate")]
    gate_bs = [bs for bs in blind_spots if bs["classification"] == "gate"]
    scores["gate_accuracy"] = 1.0 if len(gate_nodes) > 0 and len(gate_bs) > 0 else (
        1.0 if len(gate_nodes) == 0 else 0.3
    )

    # Blind spot count: minimum 2
    scores["blind_spot_count"] = 1.0 if len(blind_spots) >= 2 else 0.0

    # No silent assumptions: confidence >= 0.85 only on user-confirmed facts
    high_conf_unconfirmed = [
        n for n in genome["nodes"]
        if n.get("confidence", 0) >= 0.85 and n.get("assumptions")
    ]
    scores["no_silent_assumptions"] = max(0.0, 1.0 - len(high_conf_unconfirmed) * 0.15)

    weights = {
        "unknown_completeness": 0.25,
        "assumption_accuracy": 0.20,
        "gate_accuracy": 0.25,
        "blind_spot_count": 0.15,
        "no_silent_assumptions": 0.15
    }
    total = sum(scores[k] * weights[k] for k in weights)
    return {"scores": scores, "total": total}
```

## Critical Fixture Notes

**`ambiguous-low-context`:** This fixture has intentionally sparse input. Expected behavior:
- `meter_pct < 60` at close
- At least 3 unknowns in genome
- At least 1 unknown-type node
- At least 1 gate classified blind spot

Failure to surface ambiguity in this fixture is an automatic FAIL regardless of score.

## Failure Behavior

- `genome.json` missing → `pass: false, score: 0.0`
- `clarification_state` missing → partial check only; note in report.
