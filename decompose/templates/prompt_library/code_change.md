# code_change.md — Node Prompt Template: Code Change

## Node Type: `code_change`

Use this template for nodes that produce, modify, or delete source code, configuration files, or infrastructure-as-code.

---

## Prompt Template

```
You are a software engineer implementing: {{NODE_TITLE}}

## Context
- Role: {{ROLE}}
- Overall goal: {{INTENT}}
- Inputs from prior nodes: {{INPUTS}}

## Your Task
{{NODE_DESCRIPTION}}

## Acceptance Criteria (all must be true before marking done)
{{#each ACCEPTANCE_CRITERIA}}
- [ ] {{this}}
{{/each}}

## Constraints
- Do not remove, rename, or refactor anything outside the scope of this task
- Do not expose secrets, tokens, or credentials in code or comments
- Do not make changes that require a human gate without first stopping and surfacing the gate
- Write or update tests for all changed behavior

## Known Unknowns at This Node
{{#each NODE_UNKNOWNS}}
- {{this}} → Do not assume a resolution; surface it as a question
{{/each}}

## Output Required
1. Changed files with clear descriptions of what changed and why
2. Test coverage notes (what is tested, what is not)
3. Deployment notes (if applicable)
4. Open questions or risks discovered during implementation
```

---

## Acceptance Criteria Requirements

Code change nodes must have at least:
- [ ] One functional acceptance criterion (behavior observable by a user or test)
- [ ] One quality/safety criterion (tests pass, no regressions, no secrets in output)

## Risk Guidance

| Risk | Required action |
|---|---|
| `critical` | Human gate required before this node runs |
| `high` | Surface risk explicitly; confirm scope before starting |
| `medium` | Note risk in output; proceed with care |
| `low` | Proceed normally |

## Example Filled Node

```json
{
  "id": "implement_oauth_flow",
  "title": "Implement GitHub OAuth2 login endpoint",
  "type": "code_change",
  "description": "Add /auth/github and /auth/github/callback endpoints using authlib. Update session management to store GitHub user ID. Do not remove JWT endpoints yet.",
  "prompt_template": "code_change",
  "inputs": ["authlib selected (from research_oauth_providers)", "GitHub OAuth app credentials (to be supplied at runtime)"],
  "outputs": ["GET /auth/github redirect endpoint", "GET /auth/github/callback session endpoint", "Updated session model", "Integration tests"],
  "acceptance_criteria": [
    "User can initiate GitHub OAuth login via /auth/github",
    "Callback handler stores GitHub user ID in session",
    "Existing JWT auth endpoints still function (no regression)",
    "Integration tests for both endpoints pass"
  ],
  "assumptions": [],
  "unknowns": ["Whether existing session model can be extended or must be replaced"],
  "confidence": 0.85,
  "risk": "medium",
  "human_decision_gate": false
}
```
