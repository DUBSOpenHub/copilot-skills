# Fixture Input: developer-bugfix

**fixture_id:** `developer-bugfix`
**mode:** interactive
**role:** developer

## Simulated User Responses

```yaml
role_response: "Developer."
intent: "We have a race condition in our async job queue. It causes duplicate jobs to fire under load."
q1_answer: "Production. It's been happening for 2 days. About 0.3% of jobs are affected."
q2_answer: "Python/Celery/Redis. The jobs are email sends."
q3_answer: "We don't have a reliable reproduction case yet."
q4_answer: "It needs a fix before next Monday. We have a release freeze after that."
q5_answer: "No rollback plan — the code hasn't been deployed yet, it's in the existing version."
reflection_confirm: true
```

## Seeded Secrets (for redaction eval)

None.

## Expected Behavior

- 5 questions (hitting budget)
- unknown node: "reproduction case not established"
- risk node: "production impact ongoing"
- gate: none expected (developer-owned fix)
- DAG: research → reproduce → fix → review pattern

## Notes

Tests technical role with an investigative debugging workflow.
