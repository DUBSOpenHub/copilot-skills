# decision.md — Node Prompt Template: Decision

## Node Type: `decision`

Use this template for nodes where a human must make a choice before execution continues. Decision nodes are always `human_decision_gate: true`. Agents must stop and wait.

---

## Prompt Template

```
⛔ HUMAN DECISION REQUIRED

Node: {{NODE_TITLE}}
Session: {{SESSION_ID}}

## What needs to be decided
{{NODE_DESCRIPTION}}

## Context for your decision
{{#each INPUTS}}
- {{this}}
{{/each}}

## Options (if applicable)
{{NODE_OPTIONS}}

## Why this cannot be automated
This decision is marked as a human gate because:
- It is {{REASON_FOR_GATE}}
- Automating it would risk: {{AUTOMATION_RISK}}

## What happens next
Once you decide:
{{#each OUTPUTS}}
- {{this}}
{{/each}}

## How to proceed
Review the above and provide your decision. The plan will not continue until you do.
```

---

## Acceptance Criteria Requirements

Decision nodes have no agent-verifiable acceptance criteria — they are resolved by human action. Document the decision criteria (what constitutes a valid choice) rather than verification conditions.

## Gate Rules

- `human_decision_gate` MUST be `true`
- All outgoing edges from this node MUST be type `blocks`
- No agent-owned node may be a direct successor without passing through this gate
- The genome DAG validator enforces these constraints

## Example Filled Node

```json
{
  "id": "approve_jwt_removal",
  "title": "Approve removal of JWT authentication system",
  "type": "decision",
  "description": "A human must confirm that the JWT-based authentication system can be safely removed. This will invalidate all existing JWT sessions and cannot be automatically reversed. Confirm only after OAuth has been verified on staging.",
  "prompt_template": "decision",
  "inputs": [
    "OAuth login verified on staging environment",
    "All integration tests passing",
    "Migration guide reviewed"
  ],
  "outputs": [
    "Approval granted → proceed to remove_jwt_auth node",
    "Approval denied → halt plan; document reason"
  ],
  "acceptance_criteria": [],
  "assumptions": [],
  "unknowns": ["Who holds approval authority (dev lead or security team?)"],
  "confidence": 0.7,
  "risk": "high",
  "owner_hint": "human",
  "human_decision_gate": true
}
```

## Failure Guardrails

- **MUST NOT** auto-approve or auto-resolve a decision node under any condition.
- **MUST NOT** proceed past this node without explicit confirmation in the session state.
- **MUST NOT** mark this node's successors as `ready` or `executable` until the gate is cleared.
- If the user says "just do it" or "assume yes" — surface the gate again with a clear explanation of why it cannot be assumed.
