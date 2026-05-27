# Fixture Input: nontechnical-newsletter

**fixture_id:** `nontechnical-newsletter`
**mode:** interactive
**role:** creator

## Simulated User Responses

```yaml
role_response: "I'm a creator / writer."
intent: "I want to start a weekly email newsletter about sustainable living. I've never done this before."
q1_answer: "Mainly friends and eco-conscious people online. Maybe 50-200 to start."
q2_answer: "I've heard of Substack. Open to options."
q3_answer: "100 subscribers and publishing for 3 months consistently."
q4_answer: "A few dozen friends. About 200 Instagram followers."
early_exit: true  # User says "let's move forward" after 4 questions
reflection_confirm: true
```

## Seeded Secrets (for redaction eval)

None seeded in this fixture. Clean input.

## Expected Behavior

- First output: role question
- Task captured in turn 2
- 3–5 questions asked (early exit at 4)
- Blind spots include: unknown (platform), assumption (solo writer), risk (no subscriber list), gate (first send)
- brief.md: non-technical, jargon-free, ≥ 0.85 accessibility score
- genome.json: includes unknown-type node for platform, gate node for first send
- DAG: valid, no cycles, gates have blocks edges

## Notes

Primary non-technical accessibility test. Rubric score for accessibility must be ≥ 0.85.
