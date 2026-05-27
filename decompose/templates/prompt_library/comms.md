# comms.md — Node Prompt Template: Communications

## Node Type: `comms`

Use this template for nodes that produce, send, or coordinate communications: announcements, emails, release notes, customer messages, press statements, or stakeholder updates.

---

## Prompt Template

```
You are drafting a communication for: {{NODE_TITLE}}

## Context
- Role: {{ROLE}}
- Overall goal: {{INTENT}}
- Audience: {{COMMS_AUDIENCE}}
- Channel: {{COMMS_CHANNEL}}
- Tone: {{COMMS_TONE}}

## Your Task
{{NODE_DESCRIPTION}}

## Required elements in this communication
{{#each ACCEPTANCE_CRITERIA}}
- {{this}}
{{/each}}

## Constraints
- Do not include names, emails, phone numbers, or personal data unless explicitly provided and approved
- Do not make commitments beyond what was confirmed during planning
- Flag any claim that requires fact-checking before sending
- Do not send — draft only. Sending requires human gate approval.

## Known Unknowns at This Node
{{#each NODE_UNKNOWNS}}
- {{this}}
{{/each}}

## Output Required
1. Draft communication (complete, ready-to-review)
2. List of facts that should be verified before sending
3. Recommended reviewer(s)
4. Sending instructions (timing, channel, list)
```

---

## Acceptance Criteria Requirements

Communications nodes must include at least:
- [ ] One content criterion (what must be included)
- [ ] One approval criterion (who reviews before sending)
- [ ] One delivery criterion (how and when it is sent)

## Safety Rules

- All comms nodes that reach external parties (customers, press, partners) are ALWAYS `human_decision_gate: true`.
- Internal-only drafts (e.g., to a team) may be `human_decision_gate: false` if scope is confirmed.
- Redaction pipeline runs on all comms outputs before they are written.

## Example Filled Node

```json
{
  "id": "draft_beta_launch_email",
  "title": "Draft beta launch announcement email",
  "type": "comms",
  "description": "Write the announcement email to the beta waitlist. Announce the launch date, highlight 3 key features, include a call-to-action link, and provide an unsubscribe note.",
  "prompt_template": "comms",
  "inputs": [
    "Launch date confirmed: March 15",
    "Beta waitlist: managed in Mailchimp",
    "Top 3 features confirmed by PM"
  ],
  "outputs": [
    "Draft email (subject line + body)",
    "Review checklist",
    "Sending instructions"
  ],
  "acceptance_criteria": [
    "Email includes launch date",
    "Three features described in plain language",
    "CTA link placeholder included",
    "Unsubscribe note included",
    "Reviewed and approved by PM before sending"
  ],
  "assumptions": ["Mailchimp is the delivery platform"],
  "unknowns": ["Final CTA link URL"],
  "confidence": 0.85,
  "risk": "medium",
  "owner_hint": "pm",
  "human_decision_gate": true
}
```
