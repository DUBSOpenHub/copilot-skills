# Eval: Question Budget

**ID:** `question_budget`
**Pass bar:** 100% of normal interactive fixtures

## Purpose
Verify that the Socratic Q&A loop asks between 3 and 7 clarifying questions (inclusive) in every normal interactive session.

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `clarification_state` | object | ✓ |
| `session_transcript` | string | ✓ |

## Output Contract

```json
{
  "eval_id": "question_budget",
  "fixture_id": "<id>",
  "pass": true | false,
  "score": 1.0 | 0.0,
  "threshold": 1.0,
  "diff": "",
  "notes": "questions_asked: N"
}
```

## Check Logic

```
1. Extract `questions_asked` from clarification_state.
2. Verify questions_asked is in [3, 7].
   PASS: 3 ≤ questions_asked ≤ 7
   FAIL: questions_asked < 3 OR questions_asked > 7
3. Cross-check: count distinct Socratic question turns in the transcript (exclude role and task turns).
4. Both counts must agree within ±1 (counting ambiguity for early-termination offers).
```

## Pass Examples

```
questions_asked: 4 → PASS
questions_asked: 7 → PASS
questions_asked: 3 → PASS
```

## Fail Examples

```
questions_asked: 2 → FAIL (too few — critical unknowns likely unaddressed)
questions_asked: 8 → FAIL (too many — violates budget constraint)
questions_asked: 0 → FAIL (no Q&A ran)
```

## Guardrails

- Score is binary: 1.0 or 0.0.
- Early termination at 3+ questions when meter ≥ 75% is allowed — score remains 1.0 as long as count is ≥ 3.
- User-initiated early exit ("let's continue") counts as valid termination if questions_asked ≥ 3.

## Failure Behavior

- `clarification_state` missing → `pass: false, score: 0.0, notes: "clarification_state not found — cannot verify question count."`
- Transcript question count and state count disagree by > 1 → `pass: false, notes: "Question count mismatch: state says N, transcript shows M."`
