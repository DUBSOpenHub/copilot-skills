# Eval: Golden Regression

**ID:** `golden_regression`
**Pass bar:** 100% golden match (structural + semantic)

## Purpose
Verify that approved golden outputs in `eval/fixtures/*/golden/` remain stable across skill versions. Detects prompt drift or schema changes that silently degrade output quality.

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `golden_dir` | dirpath | ✓ |
| `produced_artifacts` | filepath[] | ✓ |

## Output Contract

```json
{
  "eval_id": "golden_regression",
  "fixture_id": "<id>",
  "pass": true | false,
  "score": 1.0 | 0.0,
  "threshold": 1.0,
  "diff": "<structural or semantic diffs>",
  "notes": ""
}
```

## What "Golden Match" Means

Golden regression does NOT require byte-for-byte identical output. It requires **structural and semantic equivalence**:

### genome.json golden match
- Same number of nodes (±0)
- Same node IDs (exact match)
- Same node types (exact match)
- Same edge structure (exact match on from/to/type)
- `handoff.start_node_id` matches
- `handoff.human_gates` matches (same set of IDs)
- Top-level `assumptions`, `unknowns`, `blind_spots` count matches (±1)
- `meta.created_at` and `meta.session_id` are excluded from comparison

### brief.md golden match
- All 9 required sections present (exact header names)
- `## Goal` content is semantically equivalent (same intent, may differ in wording)
- `## Decisions You Need to Make` lists same gates (±0)
- `## The Plan` has same number of steps (±1)
- No sections present in golden that are absent in produced version

### AGENTS.md golden match
- Same node IDs in `## Nodes` section
- Same gate IDs in `## Human Gates`
- `## Start Here` references same start node

## Diff Algorithm

```python
def golden_regression(golden_dir: str, produced: dict) -> list:
    diffs = []

    # genome.json structural check
    with open(f"{golden_dir}/genome.json") as f:
        golden_genome = json.load(f)
    prod_genome = produced["genome"]

    golden_ids = {n["id"] for n in golden_genome["nodes"]}
    prod_ids = {n["id"] for n in prod_genome["nodes"]}
    if golden_ids != prod_ids:
        diffs.append(f"Node IDs changed: added={prod_ids-golden_ids}, removed={golden_ids-prod_ids}")

    golden_edges = {(e["from"], e["to"], e["type"]) for e in golden_genome["edges"]}
    prod_edges = {(e["from"], e["to"], e["type"]) for e in prod_genome["edges"]}
    if golden_edges != prod_edges:
        diffs.append(f"Edge structure changed: added={prod_edges-golden_edges}, removed={golden_edges-prod_edges}")

    if golden_genome["handoff"]["start_node_id"] != prod_genome["handoff"]["start_node_id"]:
        diffs.append(f"start_node_id changed: {golden_genome['handoff']['start_node_id']} → {prod_genome['handoff']['start_node_id']}")

    golden_gates = set(golden_genome["handoff"]["human_gates"])
    prod_gates = set(prod_genome["handoff"]["human_gates"])
    if golden_gates != prod_gates:
        diffs.append(f"Human gates changed: {golden_gates} → {prod_gates}")

    return diffs
```

## Golden Update Policy

Golden outputs may only be updated by an explicit human decision:
1. A failing golden regression eval is reviewed by the skill maintainer.
2. The new output is confirmed to be an improvement (not a regression).
3. The golden is updated with a commit message: `chore: update golden for <fixture_id> — <reason>`.

Automated golden updates are not permitted.

## Failure Behavior

- Golden directory not found → `pass: false, notes: "Golden directory missing — run golden generation first."`
- Produced artifact missing → `pass: false, notes: "Artifact not produced for this fixture."`
- Structural diff detected → `pass: false, diff: "<list of structural diffs>"`
