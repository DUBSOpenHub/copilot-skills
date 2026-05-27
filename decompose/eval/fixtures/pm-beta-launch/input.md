# Fixture Input: pm-beta-launch

**fixture_id:** `pm-beta-launch`
**mode:** interactive
**role:** pm

## Simulated User Responses

```yaml
role_response: "Product manager / team lead."
intent: "Plan a beta launch for our new project management tool. Team wants to ship in 6 weeks. I need to coordinate engineering, marketing, and support."
q1_answer: "500 active beta users by end of week 6, NPS above 30, all P1 bugs resolved."
q2_answer: "We have a waitlist of 800. Invite-only, not open sign-up."
q3_answer: "3 P1 features still in progress. Done by week 3 engineering says."
q4_answer: "Legal must approve beta ToS. VP Product must sign go/no-go before invites."
q5_answer: "No formal rollback plan yet."
reflection_confirm: true
```

## Seeded Secrets (for redaction eval)

None.

## Expected Behavior

- 5 questions
- gate nodes: legal ToS approval, VP go/no-go
- risk node: compressed timeline (P1 features land week 3, invites need to go week 4+)
- unknown: NPS feedback mechanism
- DAG: gates block invite and launch nodes

## Notes

Tests PM/multi-stakeholder workflow with multiple hard gates.
