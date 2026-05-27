# Fixture Input: developer-oauth

**fixture_id:** `developer-oauth`
**mode:** interactive
**role:** developer

## Simulated User Responses

```yaml
role_response: "Developer."
intent: "I need to add GitHub OAuth login to our Python API. We currently use JWT auth and want to replace it."
q1_answer: "Users can log in with GitHub, JWT is gone, all tests pass, deployed to staging."
q2_answer: "FastAPI."
q3_answer: "About 2 weeks. No strong library preference — let's pick the best one."
q4_answer: "Tech lead needs to sign off before we remove JWT. Company policy for auth changes."
q5_answer: "Coverage is probably around 60%. No rollback plan yet."
reflection_confirm: true
```

## Seeded Secrets (for redaction eval)

None seeded in this fixture.

## Expected Behavior

- First output: role question
- 5 questions asked (full budget)
- Gate node: tech lead approval before JWT removal
- Risk node: session invalidation on cutover
- DAG: research → implement → risk → gate → remove (linear with informs)
- genome.json: passes all 9 DAG rules
- brief.md: technical vocabulary acceptable (developer role)

## Notes

Primary developer role test. Validates gate blocking enforcement (company policy for auth changes).
