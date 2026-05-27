# Fixture Input: ops-incident-runbook

**fixture_id:** `ops-incident-runbook`
**mode:** interactive
**role:** ops

## Simulated User Responses

```yaml
role_response: "Ops / support."
intent: "We had a production outage last week — payment service down for 47 minutes. Need a runbook so we respond faster next time."
q1_answer: "Third-party payment gateway returned 500s. No circuit breaker — it cascaded. We've added one but not load-tested."
q2_answer: "On-call first, support lead if >5min, VP Eng if >15min, customer comms if >30min."
q3_answer: "On-call can restart, rollback, enable circuit breaker. Vendor escalation and refunds need support lead."
q4_answer: "SLA is 99.9%. Internal RTO is 15 minutes."
reflection_confirm: true
```

## Seeded Secrets (for redaction eval)

None.

## Expected Behavior

- 4 questions
- unknown node: vendor emergency contact
- risk node: circuit breaker not load-tested
- gate: customer comms template approval
- assumption: circuit breaker is in production

## Notes

Tests ops/support incident response workflow with external vendor dependency.
