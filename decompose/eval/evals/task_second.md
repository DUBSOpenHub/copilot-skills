# Eval: Task Second

**ID:** `task_second`
**Pass bar:** 100% of interactive fixtures

## Purpose
Verify that task/goal capture occurs in the second user interaction — after role is established but not before.

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `session_transcript` | string | ✓ |
| `mode` | string | ✓ |

## Output Contract

```json
{
  "eval_id": "task_second",
  "fixture_id": "<id>",
  "pass": true | false,
  "score": 1.0 | 0.0,
  "threshold": 1.0,
  "diff": "",
  "notes": ""
}
```

## Check Logic

```
1. Identify Turn 1 (role question) and Turn 2 (task/intent capture).
2. PASS if ALL of:
   a. Turn 1 is a role question (covered by role_first eval).
   b. Turn 2 asks for the user's goal, task, or intent — OR acknowledges a previously stated goal.
   c. Turn 2 does NOT ask another role question.
   d. Turn 2 does NOT begin clarifying questions (Socratic Q&A starts in Turn 3+).
3. SKIP for headless and replay fixtures.
```

## Pass Examples

```
Turn 1: "What's your role?"
Turn 2: "What would you like to accomplish? Plain language is fine."
→ PASS
```

```
Turn 1: "What's your role?"
[User states role + incidentally mentions goal]
Turn 2: "Got it — so you'd like to [restate goal]. Let me ask a few questions."
→ PASS — task captured in Turn 2 acknowledgment.
```

## Fail Examples

```
Turn 1: "What's your role?"
Turn 2: "What's your stack and how large is your team?"
→ FAIL — Clarifying questions in Turn 2, goal never explicitly captured.
```

```
Turn 1: "What's your role?"
Turn 2: "What's your role?" [repeated]
→ FAIL — Role question repeated instead of moving to intent capture.
```

## Guardrails

- Score is binary: 1.0 or 0.0.
- Not applicable to headless/replay fixtures.

## Failure Behavior

- If Turn 2 not found → `pass: false, score: 0.0, notes: "Session transcript has only one turn."`
