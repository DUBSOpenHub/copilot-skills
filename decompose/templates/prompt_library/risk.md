# risk.md — Node Prompt Template: Risk

## Node Type: `risk`

Use this template for nodes that explicitly analyze, document, or mitigate a known risk before the plan continues.

---

## Prompt Template

```
You are analyzing a risk for: {{NODE_TITLE}}

## Context
- Role: {{ROLE}}
- Overall goal: {{INTENT}}
- Risk identified: {{NODE_DESCRIPTION}}

## Risk Analysis Task
For the identified risk, produce:

1. **Risk description** — What could go wrong, and when?
2. **Likelihood** — How likely is this to occur? (Low / Medium / High)
3. **Impact** — What happens if it occurs? (Low / Medium / High / Critical)
4. **Triggers** — What conditions make this risk active?
5. **Mitigation options** — At least 2 ways to reduce likelihood or impact
6. **Recommended mitigation** — Which option and why
7. **Residual risk** — What remains after mitigation is applied
8. **Owner** — Who is responsible for monitoring/mitigating this risk

## Constraints
- Do not dismiss any risk as "unlikely" without evidence
- Do not recommend an irreversible mitigation without flagging it as a gate
- If the risk requires immediate escalation, surface it prominently

## Known Unknowns at This Node
{{#each NODE_UNKNOWNS}}
- {{this}}
{{/each}}
```

---

## Acceptance Criteria Requirements

Risk nodes must produce at minimum:
- [ ] Likelihood and impact assessment
- [ ] At least one concrete mitigation option
- [ ] Owner/responsible party identified

## Risk Node Rules

- Risk nodes with `risk: critical` at the node level MUST be followed by a `decision` node (human gate).
- Risk nodes may be connected to their parent nodes with `informs` edges (non-blocking) unless the risk is blocking.
- A risk node with no mitigation path must be reclassified as an `unknown` node.

## Example Filled Node

```json
{
  "id": "risk_user_session_loss",
  "title": "Risk: Users logged out during JWT to OAuth cutover",
  "type": "risk",
  "description": "When JWT auth is removed, all active JWT sessions will be invalidated. Users with active sessions will be forcibly logged out. This could cause data loss for users mid-action.",
  "prompt_template": "risk",
  "inputs": [
    "JWT removal approved",
    "Estimated active sessions at cutover time"
  ],
  "outputs": [
    "Risk assessment document",
    "Recommended mitigation plan",
    "Rollback procedure"
  ],
  "acceptance_criteria": [
    "Likelihood and impact scored",
    "At least 2 mitigation options documented",
    "Rollback procedure defined"
  ],
  "assumptions": [],
  "unknowns": ["Number of active sessions at planned cutover time"],
  "confidence": 0.8,
  "risk": "high",
  "owner_hint": "developer",
  "human_decision_gate": false
}
```
