# review.md — Node Prompt Template: Review

## Node Type: `review`

Use this template for nodes that evaluate completed work against defined criteria before the plan continues.

---

## Prompt Template

```
You are reviewing the output of: {{PRIOR_NODE_TITLE}}

## Context
- Role: {{ROLE}}
- Overall goal: {{INTENT}}
- What was produced: {{INPUTS}}

## Review Task
{{NODE_DESCRIPTION}}

## Review Criteria (verify each)
{{#each ACCEPTANCE_CRITERIA}}
- [ ] {{this}}
{{/each}}

## Output Required
For each criterion above, state:
- PASS / FAIL / PARTIAL
- Evidence (what you observed)
- If FAIL or PARTIAL: specific recommended fix

Then provide an overall verdict:
- ✅ APPROVED — all criteria met; proceed to next node
- ⚠️ CONDITIONAL — minor gaps; describe conditions for approval
- ❌ REJECTED — major gaps; describe what must be redone

Do not proceed past a REJECTED verdict without human confirmation.

## Known Unknowns at This Node
{{#each NODE_UNKNOWNS}}
- {{this}}
{{/each}}
```

---

## Acceptance Criteria Requirements

Review nodes must include:
- [ ] The specific artifact or output being reviewed
- [ ] Verifiable pass/fail criteria (not subjective)
- [ ] A clear verdict structure (APPROVED / CONDITIONAL / REJECTED)

## Review Node Rules

- A review node with verdict REJECTED must have a `blocks` edge back to the node being reviewed (create a feedback loop in the DAG).
- If the review gate requires human judgment (e.g., design aesthetics, legal review), set `human_decision_gate: true`.
- Automated reviews (e.g., test pass/fail, schema validation) may be `human_decision_gate: false`.

## Example Filled Node

```json
{
  "id": "review_oauth_implementation",
  "title": "Review OAuth implementation before staging deploy",
  "type": "review",
  "description": "Review the OAuth implementation for correctness, security, and test coverage. Verify all acceptance criteria from implement_oauth_flow are met.",
  "prompt_template": "review",
  "inputs": [
    "implement_oauth_flow outputs",
    "Test results",
    "Code diff"
  ],
  "outputs": [
    "Review verdict: APPROVED / CONDITIONAL / REJECTED",
    "Per-criterion pass/fail with evidence",
    "Recommended fixes if REJECTED"
  ],
  "acceptance_criteria": [
    "/auth/github endpoint redirects to GitHub correctly",
    "/auth/github/callback stores session correctly",
    "No secrets or tokens in committed code",
    "Integration tests pass with 0 failures",
    "No existing endpoint broken (regression check)"
  ],
  "assumptions": [],
  "unknowns": [],
  "confidence": 0.9,
  "risk": "low",
  "owner_hint": "developer",
  "human_decision_gate": false
}
```
