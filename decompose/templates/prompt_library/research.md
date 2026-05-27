# research.md — Node Prompt Template: Research

## Node Type: `research`

Use this template for nodes where the primary work is gathering, evaluating, or synthesizing information before a decision or implementation step.

---

## Prompt Template

```
You are a researcher helping with: {{NODE_DESCRIPTION}}

## Context
- Role: {{ROLE}}
- Overall goal: {{INTENT}}
- Inputs available: {{INPUTS}}

## Your Task
Research and evaluate options for: {{NODE_TITLE}}

Specifically:
{{#each ACCEPTANCE_CRITERIA}}
- {{this}}
{{/each}}

## Output Required
Provide a structured research summary with:
1. Options evaluated (minimum 2, maximum 5)
2. Pros and cons of each option
3. Recommendation with rationale
4. Assumptions made during research
5. What remains unknown after this research

## Constraints
- Do not make irreversible decisions — surface them as recommendations requiring human sign-off
- Flag any option with significant cost, risk, or compliance implications
- Note if any required information was unavailable

## Known Unknowns at This Node
{{#each NODE_UNKNOWNS}}
- {{this}}
{{/each}}
```

---

## Acceptance Criteria Requirements

Research nodes must produce:
- [ ] At least 2 options evaluated
- [ ] Clear recommendation with rationale
- [ ] List of assumptions made
- [ ] List of remaining unknowns post-research

## Risk Guidance

| Confidence | Risk | Guidance |
|---|---|---|
| ≥ 0.85 | any | Proceed normally |
| 0.60–0.84 | low/medium | Note assumptions; proceed |
| 0.40–0.59 | any | Surface unknowns; get confirmation before next node |
| < 0.40 | any | Reclassify as `unknown` node |

## Example Filled Node

```json
{
  "id": "research_oauth_providers",
  "title": "Research OAuth library options for FastAPI",
  "type": "research",
  "description": "Evaluate Python OAuth2 libraries compatible with FastAPI. Compare authlib, python-social-auth, and fastapi-users. Recommend one with rationale.",
  "prompt_template": "research",
  "inputs": ["FastAPI framework confirmed", "GitHub as OAuth provider"],
  "outputs": ["Recommended library", "Comparison table", "Integration complexity estimate"],
  "acceptance_criteria": [
    "At least 2 libraries evaluated",
    "GitHub OAuth2 compatibility confirmed for recommended library",
    "Integration complexity documented"
  ],
  "assumptions": ["FastAPI is the web framework in use"],
  "unknowns": [],
  "confidence": 0.9,
  "risk": "low",
  "human_decision_gate": false
}
```
