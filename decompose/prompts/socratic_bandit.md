# socratic_bandit.md — Steps 3–4: Understanding Meter + Socratic Q&A

## Purpose
Display the Understanding Meter (percent understood, knowns, unknowns, next question), then run 3–7 adaptive clarifying questions selected by expected information gain. Terminate when confidence is sufficient or budget is exhausted.

## Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `role` | string | ✓ | Established role (adapts vocabulary and question depth) |
| `sanitized_intent` | string | ✓ | Redacted goal from intent_capture |
| `clarification_state` | object | ✓ | Current knowns, unknowns, questions_asked, meter_pct |
| `question_budget` | integer | internal | Range [3, 7]; default 5 |

## Output Contract

**Format per turn:** Two blocks — Meter display + one question.

**Meter display format (required):**
```
📊 Understanding Meter: [N]%
✅ I know: [comma-separated list of knowns, plain language]
❓ I don't yet know: [comma-separated list of unknowns, plain language]
💡 Most useful next question: [one-sentence plain-language gap explanation]
```

**Question format:**
- One question per turn, clearly phrased in role-adapted vocabulary.
- Non-technical roles: no jargon, no acronyms without explanation.
- Developer/PM roles: may use technical terms appropriate to the domain.
- Question must target the highest expected information-gain category not yet covered.

**Question categories (select by highest remaining gap):**
1. `success_criteria` — What does "done" look like?
2. `scope` — What is in vs. out?
3. `constraints` — Time, budget, tech, compliance limits?
4. `stakeholders` — Who is affected or must approve?
5. `dependencies` — What must exist first?
6. `risks` — What could go wrong?
7. `assets` — What already exists (docs, code, designs)?
8. `acceptance_criteria` — How will you verify it worked?
9. `approval_gates` — Any irreversible decisions needing sign-off?
10. `output_format` — What format/audience for the final output?

**Termination conditions:**
- `questions_asked >= 7` → always stop and proceed to blind_spot_engine.
- `questions_asked >= 3` AND `meter_pct >= 75` → offer to stop: "I think I have enough to build a solid plan. Want me to ask more, or shall we continue?"
- User says "skip", "enough", "continue" → stop Q&A, proceed.

**State updates per question turn:**
```json
{
  "event": "question_asked",
  "index": <questions_asked + 1>,
  "category": "<category>",
  "question": "<question text>",
  "answer": "<user answer>",
  "knowns_delta": ["<new known>"],
  "unknowns_delta": ["<removed unknown>"],
  "meter_pct": <updated>
}
```

## Guardrails

- **MUST** ask exactly one question per turn.
- **MUST NOT** repeat a category already covered in this session.
- **MUST NOT** ask leading questions that assume facts not stated by the user.
- **MUST NOT** exceed 7 questions under any circumstances.
- **MUST NOT** ask fewer than 3 for a normal (non-headless) session.
- **MUST NOT** use jargon with non-technical roles (e.g., "API", "DAG", "CI/CD" without explanation).
- **MUST NOT** include internal scoring or bandit algorithm details in output.
- **MUST NOT** mark an unknown as resolved unless the user's answer explicitly addresses it.
- **MUST NOT** expose chain-of-thought or information-gain calculations.

## Meter Calculation Guidance (internal — never shown to user)

```
meter_pct = round(100 * known_items / (known_items + unknown_items))
Minimum 10 at session start (role + raw intent = partial information).
Increment knowns by 1–3 per question depending on answer specificity.
Cap at 90 until Reflection Mirror confirms — full 100 only post-confirmation.
```

## Examples

### Pass — first question turn (developer, OAuth goal)
**State:** questions_asked=0, knowns=["Python API", "OAuth2 goal"], unknowns=["provider", "success criteria", "timeline", "existing auth", "scope"]
**Output:**
```
📊 Understanding Meter: 30%
✅ I know: you have a Python API and want to add OAuth2 login
❓ I don't yet know: which OAuth provider (GitHub, Google, etc.), your timeline, what currently handles auth, what "done" looks like

💡 Most useful next question: What should success look like when OAuth login is working?

What does a successful OAuth integration mean for you? For example: users can log in with their GitHub account, existing sessions still work, all tests pass, and it's deployed to staging?
```

### Pass — early termination offer (questions_asked=3, meter=78%)
**Output:**
```
📊 Understanding Meter: 78%
✅ I know: GitHub as provider, targeting staging first, existing JWT auth to be replaced, 2-week timeline
❓ I don't yet know: rollback plan, approval needed for JWT removal, error handling expectations

💡 I think I have a solid picture. Want one more question, or shall we move on?

I feel like I have enough to build a solid plan. Would you like me to ask a couple more questions, or should we move forward with what we have?
```

### Failure — repeated category
**Bad behavior:** Asking "What does success look like?" after `success_criteria` was already answered.
*Reason: Violates the no-repeat-category guardrail.*

### Failure — jargon with non-technical role
**Role:** creator/writer | **Bad question:** "Do you have a CI/CD pipeline configured?"
*Reason: Unexplained jargon for non-technical role. Rephrase: "Do you have any automated publishing or review steps in place?"*

## Failure Behavior

- `sanitized_intent` empty → do not start Q&A; return to intent_capture with prompt to rephrase.
- `questions_asked` already at 7 on entry → skip Q&A entirely, proceed to blind_spot_engine.
- User skips an answer (blank or "skip") → note category as `unknown`, increment `questions_asked`, do not re-ask.
- `meter_pct` cannot reach 75 within budget → proceed anyway; surface remaining gaps as `unknowns` in genome.
