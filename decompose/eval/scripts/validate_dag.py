#!/usr/bin/env python3
"""
validate_dag.py — DAG Semantic Validator for decompose genome.json

Runs all 9 DAG validation rules defined in eval/evals/dag_validity.md.

Usage:
    python3 eval/scripts/validate_dag.py <genome.json>
    python3 eval/scripts/validate_dag.py eval/fixtures/developer-oauth/golden/genome.json

Exit codes:
    0 = all rules pass
    1 = one or more rules failed
"""

import json
import sys
from collections import defaultdict, deque


def validate_dag(genome: dict) -> list:
    errors = []
    nodes = genome.get("nodes", [])
    edges = genome.get("edges", [])
    node_ids = {n["id"] for n in nodes}

    # DAG-3: No dangling edge references
    for edge in edges:
        if edge.get("from") not in node_ids:
            errors.append(f"DAG-3: Edge from unknown node '{edge.get('from')}'")
        if edge.get("to") not in node_ids:
            errors.append(f"DAG-3: Edge to unknown node '{edge.get('to')}'")

    # DAG-2: No orphaned nodes (skip if single node)
    if len(nodes) > 1:
        connected = set()
        for edge in edges:
            connected.add(edge.get("from"))
            connected.add(edge.get("to"))
        for nid in node_ids:
            if nid not in connected:
                errors.append(f"DAG-2: Node '{nid}' is orphaned (no edges)")

    # DAG-1: No cycles (Kahn's algorithm on blocks edges only)
    in_degree = defaultdict(int)
    adj = defaultdict(list)
    for edge in edges:
        if edge.get("type") == "blocks":
            src = edge.get("from")
            dst = edge.get("to")
            if src in node_ids and dst in node_ids:
                adj[src].append(dst)
                in_degree[dst] += 1

    queue = deque(nid for nid in node_ids if in_degree[nid] == 0)
    visited_count = 0
    while queue:
        nid = queue.popleft()
        visited_count += 1
        for neighbor in adj[nid]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count < len(node_ids):
        errors.append("DAG-1: Cycle detected in 'blocks' edges — topological sort failed")

    # Per-node checks
    for node in nodes:
        nid = node["id"]
        ntype = node.get("type", "")

        # DAG-4: Agent-owned executable nodes must provide a prompt template.
        prompt_template = node.get("prompt_template")
        needs_prompt = (
            node.get("owner_hint") == "agent"
            and ntype in {"research", "code_change", "comms", "review", "risk"}
        )
        if needs_prompt and not (isinstance(prompt_template, str) and prompt_template.strip()):
            errors.append(
                f"DAG-4: Agent node '{nid}' (type={ntype}) has empty prompt_template"
            )

        # DAG-5: Acceptance criteria required for non-milestone executable nodes.
        if ntype != "milestone" and not node.get("acceptance_criteria"):
            errors.append(f"DAG-5: Node '{nid}' missing acceptance_criteria")

        # DAG-6: Gate node must have at least one outgoing 'blocks' edge and human owner.
        if node.get("human_decision_gate", False) and len(nodes) > 1:
            has_blocks_out = any(
                e.get("from") == nid and e.get("type") == "blocks"
                for e in edges
            )
            if not has_blocks_out:
                errors.append(f"DAG-6: Gate node '{nid}' has no outgoing 'blocks' edge")
            if node.get("owner_hint") != "human":
                errors.append(f"DAG-6: Gate node '{nid}' owner_hint must be 'human'")

        # DAG-7: Unknown nodes must make uncertainty explicit in the node or genome.
        if ntype == "unknown" and not node.get("unknowns"):
            errors.append(f"DAG-7: Unknown node '{nid}' missing unknowns")

        # DAG-8: Low-confidence nodes must be typed as unknown.
        confidence = node.get("confidence", 1.0)
        if confidence < 0.4 and ntype != "unknown":
            errors.append(
                f"DAG-8: Node '{nid}' confidence={confidence} < 0.4 but type='{ntype}' (must be 'unknown')"
            )

    # DAG-9: handoff start node must be a valid node ID.
    handoff = genome.get("handoff", {})
    start_node = handoff.get("start_node") or handoff.get("start_node_id") or ""
    if start_node and start_node not in node_ids:
        errors.append(f"DAG-9: handoff start node '{start_node}' not in node list")

    return errors


def validate_schema_basic(genome: dict) -> list:
    """Basic structural checks without jsonschema dependency."""
    errors = []
    required_top = [
        "genome_id", "schema_version", "role", "intent",
        "nodes", "edges", "assumptions", "unknowns",
        "blind_spots", "open_questions", "meta", "handoff"
    ]
    for field in required_top:
        if field not in genome:
            errors.append(f"SCHEMA: Missing required top-level field: '{field}'")

    for i, node in enumerate(genome.get("nodes", [])):
        required_node = [
            "id", "title", "type", "description", "prompt_template",
            "inputs", "outputs", "acceptance_criteria", "confidence",
            "risk", "human_decision_gate"
        ]
        for field in required_node:
            if field not in node:
                nid = node.get("id", f"[node {i}]")
                errors.append(f"SCHEMA: Node '{nid}' missing required field: '{field}'")

        valid_types = {"research", "decision", "code_change", "comms", "review", "risk", "unknown", "milestone"}
        if node.get("type") not in valid_types:
            errors.append(f"SCHEMA: Node '{node.get('id')}' invalid type: '{node.get('type')}'")

        valid_risks = {"low", "medium", "high", "critical"}
        if node.get("risk") not in valid_risks:
            errors.append(f"SCHEMA: Node '{node.get('id')}' invalid risk: '{node.get('risk')}'")

    for i, edge in enumerate(genome.get("edges", [])):
        for field in ["from", "to", "type"]:
            if field not in edge:
                errors.append(f"SCHEMA: Edge {i} missing field: '{field}'")
        valid_edge_types = {"blocks", "informs", "optional"}
        if edge.get("type") not in valid_edge_types:
            errors.append(f"SCHEMA: Edge {i} invalid type: '{edge.get('type')}'")

    return errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 validate_dag.py <genome.json>")
        sys.exit(1)

    genome_path = sys.argv[1]
    try:
        with open(genome_path) as f:
            genome = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: File not found: {genome_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {genome_path}: {e}")
        sys.exit(1)

    print(f"Validating: {genome_path}")
    print(f"Genome ID:  {genome.get('genome_id', '(unknown)')}")
    print(f"Nodes: {len(genome.get('nodes', []))} | Edges: {len(genome.get('edges', []))}")
    print()

    schema_errors = validate_schema_basic(genome)
    dag_errors = validate_dag(genome)
    all_errors = schema_errors + dag_errors

    if not all_errors:
        print("✅ ALL CHECKS PASSED")
        print(f"   Schema: PASS ({len(genome.get('nodes', []))} nodes, {len(genome.get('edges', []))} edges)")
        print("   DAG:    PASS (9/9 rules)")
        sys.exit(0)
    else:
        print(f"❌ VALIDATION FAILED — {len(all_errors)} error(s):")
        for err in all_errors:
            print(f"   • {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
