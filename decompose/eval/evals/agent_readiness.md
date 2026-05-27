# Eval: Agent Readiness

**ID:** `agent_readiness`
**Pass bar:** Rubric score ≥ 0.80 for all fixtures

## Purpose
Score `AGENTS.md` and genome node prompt configuration for executability by a downstream agent, using `rubrics/agent_readiness.md`.

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `agents_md_path` | filepath | ✓ |
| `genome_json_path` | filepath | ✓ |

## Output Contract

```json
{
  "eval_id": "agent_readiness",
  "fixture_id": "<id>",
  "pass": true | false,
  "score": 0.0–1.0,
  "threshold": 0.80,
  "rubric_breakdown": {
    "start_node": 0.0–1.0,
    "prompt_coverage": 0.0–1.0,
    "acceptance_criteria": 0.0–1.0,
    "human_gates": 0.0–1.0,
    "do_not_assume": 0.0–1.0,
    "goal_sentence": 0.0–1.0,
    "nodes_section": 0.0–1.0
  },
  "diff": "",
  "notes": ""
}
```

## Check Logic

```python
def score_agent_readiness(agents_md: str, genome: dict) -> dict:
    scores = {}

    # Start node
    scores["start_node"] = 1.0 if genome["handoff"]["start_node_id"] in agents_md else 0.0

    # Prompt coverage
    non_milestone = [n for n in genome["nodes"] if n["type"] != "milestone"]
    covered = [n for n in non_milestone if n.get("prompt_template", "").strip()]
    scores["prompt_coverage"] = len(covered) / len(non_milestone) if non_milestone else 1.0

    # Acceptance criteria
    non_gate_exec = [n for n in genome["nodes"]
                     if not n.get("human_decision_gate") and n["type"] not in ("milestone", "unknown")]
    with_criteria = [n for n in non_gate_exec if n.get("acceptance_criteria")]
    scores["acceptance_criteria"] = len(with_criteria) / len(non_gate_exec) if non_gate_exec else 1.0

    # Human gates listed in AGENTS.md
    gate_nodes = [n for n in genome["nodes"] if n.get("human_decision_gate")]
    gates_in_md = sum(1 for n in gate_nodes if n["id"] in agents_md or n["title"] in agents_md)
    scores["human_gates"] = gates_in_md / len(gate_nodes) if gate_nodes else 1.0

    # Do Not Assume
    unknowns = genome.get("handoff", {}).get("do_not_assume", [])
    if not unknowns:
        scores["do_not_assume"] = 1.0
    else:
        found = sum(1 for u in unknowns if u in agents_md)
        scores["do_not_assume"] = found / len(unknowns)

    # Goal sentence
    goal_section = extract_section(agents_md, "## Goal")
    sentences = [s.strip() for s in goal_section.split(".") if s.strip()]
    scores["goal_sentence"] = 1.0 if len(sentences) <= 2 else 0.7

    # Nodes section completeness
    nodes_section = extract_section(agents_md, "## Nodes")
    all_ids_present = all(n["id"] in nodes_section for n in genome["nodes"])
    scores["nodes_section"] = 1.0 if all_ids_present else 0.5

    # Weighted aggregate
    weights = {
        "start_node": 0.15, "prompt_coverage": 0.25, "acceptance_criteria": 0.20,
        "human_gates": 0.15, "do_not_assume": 0.10, "goal_sentence": 0.05, "nodes_section": 0.10
    }
    total = sum(scores[k] * weights[k] for k in weights)
    return {"scores": scores, "total": total}
```

## Failure Behavior

- `AGENTS.md` missing → `pass: false, score: 0.0, notes: "AGENTS.md not found."`
- `genome.json` missing → `pass: false, score: 0.0, notes: "genome.json required for agent readiness check."`
