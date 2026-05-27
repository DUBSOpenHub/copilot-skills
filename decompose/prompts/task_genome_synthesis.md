# task_genome_synthesis.md — Step 7a: Task Genome Synthesis

## Purpose
Synthesize the confirmed `clarification_state` into a valid `genome.json` that passes both JSON Schema validation and DAG semantic checks. Every node must be executable by a downstream agent without re-asking known context.

## Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `clarification_state` | object | ✓ | Fully confirmed state (confirmed: true) |
| `role` | string | ✓ | Role lens |
| `sanitized_intent` | string | ✓ | Confirmed goal |
| `genome.schema.json` | schema | ✓ | Validation target |

## Output Contract

**Format:** Valid JSON conforming to `genome.schema.json` (Draft 7). Written to `genome.json` only after passing all validation checks at the Validation Gate.

**Required top-level fields:** `genome_id`, `schema_version`, `role`, `intent`, `nodes`, `edges`, `assumptions`, `unknowns`, `blind_spots`, `open_questions`, `meta`, `handoff`

**Minimum nodes:** 3 for any non-trivial goal. Maximum: 20 (split into sub-genomes if larger).

**Per-node synthesis rules:**
1. `id` — lowercase slug, unique within genome (e.g., `research_providers`, `implement_oauth_flow`).
2. `type` — choose the best-fit type; `unknown` nodes require `resolution_strategy`.
3. `prompt_template` — must reference a valid prompt_library template name (e.g., `research`, `code_change`). Empty string only for `milestone` type nodes.
4. `confidence` — derive from: explicit user confirmation → 0.85–1.0; inferred from context → 0.50–0.84; guessed → 0.30–0.49 (flag as `unknown` node if < 0.4).
5. `human_decision_gate` — set `true` for every node classified as `gate` in blind_spots.
6. `acceptance_criteria` — required for all non-milestone, non-human-gated nodes; must be verifiable.

**DAG construction rules:**
- All nodes must be reachable from `handoff.start_node_id`.
- No cycles allowed.
- No orphaned nodes (every node except the first must have at least one incoming edge).
- `human_decision_gate: true` nodes must appear as the `from` in at least one `blocks` edge.
- Agent-owned nodes must not be successors of a gated node without first passing through the gate.

**Validation Gate checks (run before writing):**
1. JSON Schema validation against `genome.schema.json`.
2. Topological sort — reject if cycle detected.
3. Orphan check — reject if node has no edges and is not the sole node.
4. Dangling reference check — reject if any edge `from`/`to` is not in node ID list.
5. Prompt template check — reject if `type != milestone` and `prompt_template` is empty.
6. Acceptance criteria check — reject if non-human-gated executable node has empty `acceptance_criteria`.
7. Gate blocking check — reject if `human_decision_gate: true` node is not upstream of its successors via `blocks` edges.
8. Unknown strategy check — reject if `type: unknown` node has no `resolution_strategy`.
9. Confidence floor check — reject if `confidence < 0.4` on inferred node not typed as `unknown`.

**On validation failure:** Do not write artifact. Surface error to user: `"I found an issue in the plan structure: [error description]. Let me fix it before writing."` Then self-correct and re-validate.

## Guardrails

- **MUST NOT** write `genome.json` before validation passes.
- **MUST NOT** silently drop any unknown or blind spot from genome top-level arrays.
- **MUST NOT** include any secret, token, or sensitive personal data.
- **MUST NOT** auto-resolve a human gate — leave it as a gate node.
- **MUST NOT** expose internal chain-of-thought, scoring, or prompt names other than those in `prompt_library/`.
- **MUST NOT** produce a genome where `confirmed: false` in clarification_state.
- **MUST NOT** include internal redaction log in the genome output.
- **MUST NOT** set `confidence >= 0.85` on any item not explicitly confirmed by the user.

## Examples

### Pass — minimal valid genome (developer, OAuth)
```json
{
  "genome_id": "developer-oauth-2024",
  "schema_version": "1.0",
  "role": "developer",
  "intent": "Add GitHub OAuth login to a FastAPI Python API, replacing JWT auth, targeting staging within two weeks.",
  "nodes": [
    {
      "id": "research_oauth_providers",
      "title": "Research OAuth library options",
      "type": "research",
      "description": "Evaluate Python OAuth libraries compatible with FastAPI (authlib, python-social-auth, etc.).",
      "prompt_template": "research",
      "inputs": ["FastAPI stack", "GitHub OAuth requirements"],
      "outputs": ["Recommended library with rationale"],
      "acceptance_criteria": ["Library chosen and documented", "Compatibility with FastAPI confirmed"],
      "assumptions": ["FastAPI framework in use"],
      "unknowns": [],
      "confidence": 0.9,
      "risk": "low",
      "parallelizable_with": [],
      "owner_hint": "developer",
      "human_decision_gate": false
    },
    {
      "id": "implement_oauth_flow",
      "title": "Implement GitHub OAuth flow",
      "type": "code_change",
      "description": "Implement the OAuth2 authorization code flow with GitHub as provider.",
      "prompt_template": "code_change",
      "inputs": ["Chosen OAuth library", "GitHub app credentials"],
      "outputs": ["Working OAuth login endpoint", "Session management updated"],
      "acceptance_criteria": ["User can log in with GitHub", "Auth token stored securely", "Tests pass"],
      "assumptions": [],
      "unknowns": ["Test coverage baseline"],
      "confidence": 0.85,
      "risk": "medium",
      "parallelizable_with": [],
      "owner_hint": "developer",
      "human_decision_gate": false
    },
    {
      "id": "approve_jwt_removal",
      "title": "Approve JWT auth removal",
      "type": "decision",
      "description": "Human gate: confirm that JWT auth can be removed and existing sessions invalidated.",
      "prompt_template": "decision",
      "inputs": ["OAuth implementation verified on staging"],
      "outputs": ["Signed-off removal approval"],
      "acceptance_criteria": [],
      "assumptions": [],
      "unknowns": ["Who must approve (dev lead, security team?)"],
      "confidence": 0.7,
      "risk": "high",
      "parallelizable_with": [],
      "owner_hint": "human",
      "human_decision_gate": true
    },
    {
      "id": "remove_jwt_auth",
      "title": "Remove JWT auth system",
      "type": "code_change",
      "description": "Remove JWT middleware, token issuance, and validation after human gate approval.",
      "prompt_template": "code_change",
      "inputs": ["Approval from approve_jwt_removal gate"],
      "outputs": ["JWT code removed", "Tests updated", "Staging re-deployed"],
      "acceptance_criteria": ["JWT endpoints return 404 or 401", "OAuth login still functional", "All tests pass"],
      "assumptions": [],
      "unknowns": [],
      "confidence": 0.9,
      "risk": "high",
      "parallelizable_with": [],
      "owner_hint": "developer",
      "human_decision_gate": false
    }
  ],
  "edges": [
    { "from": "research_oauth_providers", "to": "implement_oauth_flow", "type": "blocks" },
    { "from": "implement_oauth_flow", "to": "approve_jwt_removal", "type": "blocks" },
    { "from": "approve_jwt_removal", "to": "remove_jwt_auth", "type": "blocks" }
  ],
  "assumptions": ["FastAPI framework in use", "GitHub as OAuth provider is confirmed"],
  "unknowns": ["Existing test coverage for auth module", "Who must approve JWT removal"],
  "blind_spots": [
    { "text": "FastAPI framework assumed — not explicitly confirmed", "classification": "assumption" },
    { "text": "Rollback plan if staging OAuth fails is undefined", "classification": "risk" },
    { "text": "JWT removal requires explicit human approval", "classification": "gate" }
  ],
  "open_questions": ["Who is the approver for JWT removal?", "Is rollback to JWT required if OAuth fails?"],
  "meta": {
    "created_at": "2024-01-15T10:30:00Z",
    "skill_version": "1.0",
    "session_id": "sess-developer-oauth-001",
    "questions_asked": 5,
    "meter_pct_at_close": 82
  },
  "handoff": {
    "start_node_id": "research_oauth_providers",
    "human_gates": ["approve_jwt_removal"],
    "do_not_assume": ["Who approves JWT removal", "Whether rollback to JWT is acceptable"]
  }
}
```

### Failure — cycle in DAG
**Bad:** Node A blocks B, B blocks C, C blocks A.
*Reason: Topological sort fails. Reject and self-correct.*

### Failure — agent node succeeds gate without blocks edge
**Bad:** Gate node `approve_jwt_removal` has no outgoing `blocks` edge to `remove_jwt_auth`.
*Reason: Gate bypass violation. Reject and add the edge.*

## Failure Behavior

- Schema validation failure → self-correct and re-validate; surface error if uncorrectable.
- Cycle detected → identify the cycle, break it by reclassifying one edge as `informs`, re-validate.
- Orphaned node → add a minimal `informs` edge to connect it, or merge into another node.
- Empty `acceptance_criteria` on non-gate node → derive 1–2 verifiable criteria from `description`; flag confidence as 0.7.
- `confirmed: false` → abort synthesis, return to reflection_mirror.
