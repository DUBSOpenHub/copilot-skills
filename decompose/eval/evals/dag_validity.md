# Eval: DAG Validity

**ID:** `dag_validity`
**Pass bar:** 100% of all fixtures

## Purpose
Apply all 9 DAG semantic validation rules to `genome.json`. Reject any genome that violates structural or safety rules — regardless of JSON Schema validity.

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `genome_json` | object | ✓ |

## Output Contract

```json
{
  "eval_id": "dag_validity",
  "fixture_id": "<id>",
  "pass": true | false,
  "score": 1.0 | 0.0,
  "threshold": 1.0,
  "diff": "<list of violated rules>",
  "notes": ""
}
```

## Rules Checked

| Rule ID | Name | Reject condition |
|---|---|---|
| DAG-1 | No cycles | Topological sort fails on node/edge graph |
| DAG-2 | No orphans | Non-sole node has no edges (in or out) |
| DAG-3 | No dangling refs | Edge `from` or `to` not in node ID list |
| DAG-4 | Prompt required | `type != milestone` and `prompt_template` is empty |
| DAG-5 | Acceptance required | Non-human-gated executable node has empty `acceptance_criteria` |
| DAG-6 | Gate blocks agent | `human_decision_gate: true` node has no outgoing `blocks` edge |
| DAG-7 | Unknown strategy | `type: unknown` node missing `resolution_strategy` field |
| DAG-8 | Confidence floor | `confidence < 0.4` on inferred node not typed as `unknown` |
| DAG-9 | Start node valid | `handoff.start_node_id` exists in node ID list |

## Check Algorithm

```python
def validate_dag(genome: dict) -> list[str]:
    errors = []
    node_ids = {n["id"] for n in genome["nodes"]}
    nodes_by_id = {n["id"]: n for n in genome["nodes"]}

    # DAG-3: dangling refs
    for edge in genome["edges"]:
        if edge["from"] not in node_ids:
            errors.append(f"DAG-3: Edge from unknown node '{edge['from']}'")
        if edge["to"] not in node_ids:
            errors.append(f"DAG-3: Edge to unknown node '{edge['to']}'")

    # DAG-2: orphans (skip if single node)
    if len(genome["nodes"]) > 1:
        connected = set()
        for edge in genome["edges"]:
            connected.add(edge["from"])
            connected.add(edge["to"])
        for nid in node_ids:
            if nid not in connected:
                errors.append(f"DAG-2: Node '{nid}' is orphaned (no edges)")

    # DAG-1: cycles (Kahn's algorithm)
    from collections import defaultdict, deque
    in_degree = defaultdict(int)
    adj = defaultdict(list)
    for edge in genome["edges"]:
        if edge["type"] in ("blocks",):
            adj[edge["from"]].append(edge["to"])
            in_degree[edge["to"]] += 1
    queue = deque(n for n in node_ids if in_degree[n] == 0)
    visited = 0
    while queue:
        n = queue.popleft()
        visited += 1
        for neighbor in adj[n]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    if visited < len(node_ids):
        errors.append("DAG-1: Cycle detected in blocks edges")

    # Per-node checks
    for node in genome["nodes"]:
        nid = node["id"]
        ntype = node["type"]

        # DAG-4: prompt required
        if ntype != "milestone" and not node.get("prompt_template", "").strip():
            errors.append(f"DAG-4: Node '{nid}' (type={ntype}) has empty prompt_template")

        # DAG-5: acceptance criteria
        if not node.get("human_decision_gate", False) and ntype not in ("milestone", "unknown"):
            if not node.get("acceptance_criteria"):
                errors.append(f"DAG-5: Node '{nid}' missing acceptance_criteria")

        # DAG-6: gate must have blocks outgoing edge
        if node.get("human_decision_gate", False):
            has_blocks_out = any(
                e["from"] == nid and e["type"] == "blocks"
                for e in genome["edges"]
            )
            if not has_blocks_out and len(genome["nodes"]) > 1:
                errors.append(f"DAG-6: Gate node '{nid}' has no outgoing 'blocks' edge")

        # DAG-7: unknown strategy
        if ntype == "unknown" and not node.get("resolution_strategy", "").strip():
            errors.append(f"DAG-7: Unknown node '{nid}' missing resolution_strategy")

        # DAG-8: confidence floor
        if node.get("confidence", 1.0) < 0.4 and ntype != "unknown":
            errors.append(f"DAG-8: Node '{nid}' confidence={node['confidence']} < 0.4 but not typed as 'unknown'")

    # DAG-9: start node valid
    start = genome.get("handoff", {}).get("start_node_id", "")
    if start and start not in node_ids:
        errors.append(f"DAG-9: start_node_id '{start}' not in node list")

    return errors
```

## Pass Criteria

`validate_dag(genome)` returns an empty list.

## Fail Examples

```
["DAG-1: Cycle detected in blocks edges"]
["DAG-3: Edge to unknown node 'missing_node_id'"]
["DAG-6: Gate node 'approve_jwt_removal' has no outgoing 'blocks' edge"]
["DAG-7: Unknown node 'unknown_platform' missing resolution_strategy"]
```

## Guardrails

- Score is binary.
- All 9 rules are checked; all violations listed in `diff`.
- `informs` and `optional` edges do NOT count for cycle detection or gate-blocking requirements (only `blocks` edges are subject to those rules).
