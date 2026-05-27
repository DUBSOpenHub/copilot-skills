# unknown.md — Node Prompt Template: Unknown

## Node Type: `unknown`

Use this template for nodes where a necessary fact, decision, or dependency is not yet known and cannot be inferred. Unknown nodes block execution until resolved.

---

## Prompt Template

```
⚠️ UNRESOLVED UNKNOWN — Human input required

Node: {{NODE_TITLE}}
Session: {{SESSION_ID}}

## What is unknown
{{NODE_DESCRIPTION}}

## Why this blocks the plan
Without resolving this unknown, the following steps cannot proceed:
{{#each BLOCKED_SUCCESSORS}}
- {{this}}
{{/each}}

## Resolution strategy
{{RESOLUTION_STRATEGY}}

## How to resolve
{{#each RESOLUTION_STEPS}}
{{@index_plus_one}}. {{this}}
{{/each}}

## What to provide
Once you have the answer, provide it in this format:
"The answer to [{{NODE_TITLE}}] is: [your answer]"

The plan will continue from the point where this was unblocked.
```

---

## Acceptance Criteria Requirements

Unknown nodes do NOT have verifiable acceptance criteria in the traditional sense. Instead, they require a `resolution_strategy` field (required by schema).

**Resolution strategy options:**
- `ask_user` — surface to human, wait for answer
- `research` — spawn a research node to find the answer
- `default_and_flag` — use a safe default and flag it as an assumption (only for low-risk unknowns)
- `descope` — remove the dependent work from scope if unresolvable
- `escalate` — escalate to a stakeholder or decision-maker

## Unknown Node Rules

- Every `unknown` node MUST have a `resolution_strategy` (schema-required).
- `confidence` on `unknown` nodes must be `< 0.5` (they are inherently uncertain).
- Agents MUST NOT auto-resolve an `unknown` node. Any autonomous resolution must be reclassified as an `assumption` and surfaced as a blind spot.
- If `resolution_strategy: default_and_flag`, confidence must be `≤ 0.6` and the default must be stated explicitly in the description.

## Example Filled Node

```json
{
  "id": "unknown_email_platform",
  "title": "Unknown: Which email platform to use",
  "type": "unknown",
  "description": "The user has not chosen an email platform. Platform choice affects all downstream nodes: account setup, template design, subscriber import, and send configuration.",
  "prompt_template": "unknown",
  "inputs": [],
  "outputs": ["Platform decision confirmed"],
  "acceptance_criteria": [],
  "assumptions": [],
  "unknowns": ["Email platform choice"],
  "resolution_strategy": "ask_user",
  "confidence": 0.2,
  "risk": "high",
  "owner_hint": "human",
  "human_decision_gate": true
}
```

## Failure Guardrails

- **MUST NOT** treat an `unknown` node as resolved without explicit human input or a completed `research` node.
- **MUST NOT** set `confidence >= 0.5` on an `unknown` typed node.
- **MUST NOT** allow agent-owned successors to bypass an `unknown` node via `informs` or `optional` edges if the unknown is blocking.
- If all successors depend on the unknown — mark the entire downstream subgraph as `status: blocked` until resolved.
