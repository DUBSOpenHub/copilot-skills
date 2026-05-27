# Fixture Input: researcher-market-map

**fixture_id:** `researcher-market-map`
**mode:** interactive
**role:** researcher

## Simulated User Responses

```yaml
role_response: "Researcher."
intent: "I need to map the competitive landscape for AI-powered developer tools. This is for an internal strategy report due in 3 weeks."
q1_answer: "Identify top 10 competitors, their pricing, positioning, and key differentiators."
q2_answer: "Internal only. Audience is our head of product and CEO."
q3_answer: "I have access to Crunchbase, LinkedIn, and public pricing pages. No analyst reports."
q4_answer: "Three weeks. I'm working alone on this."
q5_answer: "PDF or slide deck format."
reflection_confirm: true
```

## Seeded Secrets (for redaction eval)

None.

## Expected Behavior

- 5 questions
- research nodes: competitor identification, pricing analysis, positioning analysis
- review node: executive brief review gate
- milestone node: final report delivery
- DAG: parallel research paths, synthesized into report

## Notes

Tests researcher role with parallel research workflow and output format specification.
