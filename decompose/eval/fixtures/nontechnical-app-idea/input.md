# Fixture Input: nontechnical-app-idea

**fixture_id:** `nontechnical-app-idea`
**mode:** interactive
**role:** creator

## Simulated User Responses

```yaml
role_response: "I'm not technical — I'm a creator."
intent: "I have an idea for an app that helps people track their water intake. Not sure how to build it."
q1_answer: "Make it easy for people to remember to drink water during the day."
q2_answer: "Something simple on a phone. I don't know what else."
q3_answer: "Probably just me to start. Maybe hire someone eventually."
q4_answer: "I have no budget right now. Would need to find funding."
reflection_confirm: true
```

## Seeded Secrets (for redaction eval)

None.

## Expected Behavior

- Role question first
- Non-technical vocabulary throughout
- budget unknown → unknown node
- "hire someone" → gate or decision node
- brief.md: jargon-free (no "API", "backend", "iOS build pipeline")
- Accessibility score ≥ 0.85

## Notes

Tests non-technical accessibility with an app idea that requires technical execution the user cannot perform themselves.
