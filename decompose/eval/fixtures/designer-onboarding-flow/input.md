# Fixture Input: designer-onboarding-flow

**fixture_id:** `designer-onboarding-flow`
**mode:** interactive
**role:** designer

## Simulated User Responses

```yaml
role_response: "Designer."
intent: "I need to redesign our app onboarding flow. Users are dropping off at step 3 of 5."
q1_answer: "Less than 40% of users complete onboarding. We want 70%."
q2_answer: "Mobile app, iOS and Android. We use Figma for design."
q3_answer: "We have session recordings and a drop-off funnel from Mixpanel. No user interviews yet."
q4_answer: "Engineering needs final specs in 3 weeks. We have a design critique next Friday."
reflection_confirm: true
```

## Seeded Secrets (for redaction eval)

None.

## Expected Behavior

- 4 questions (early exit after reaching meter ≥ 75%)
- research node: user interview (currently missing)
- review node: design critique gate
- unknowns: root cause of step 3 drop-off (no interviews yet)
- gate: engineering handoff approval

## Notes

Tests designer role with UX research-first workflow.
