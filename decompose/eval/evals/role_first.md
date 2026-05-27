# Eval: Role First

**ID:** `role_first`
**Pass bar:** 100% of interactive fixtures

## Purpose
Verify that the first user-facing output of every interactive session is a role question — no exceptions.

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `session_transcript` | string | ✓ |
| `mode` | `interactive` \| `headless` \| `replay` | ✓ |

## Output Contract

```json
{
  "eval_id": "role_first",
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
1. Extract the first assistant-turn text from the session transcript.
2. Check: does it contain a role question?
   PASS criteria (ALL must be true):
   a. The first turn does NOT accept a task or goal.
   b. The first turn asks about the user's role (look for: "role", "perspective", "who are you", or equivalent).
   c. The first turn does NOT ask about the goal or task.
   d. The first turn does NOT produce any artifact (brief.md, genome, etc.).
3. SKIP this eval for headless and replay mode fixtures.
```

## Pass Examples

```
First turn: "Welcome! What's your role on this work? (Developer, PM, creator, etc. or 'skip'?)"
→ PASS
```

```
First turn: "Hi! Before we start, what's your perspective on this work — creator, developer, PM, ops, or other?"
→ PASS
```

## Fail Examples

```
First turn: "What would you like to build today?"
→ FAIL — Task accepted before role established.
```

```
First turn: "Tell me your goal and your role."
→ FAIL — Task question included in first turn.
```

```
First turn: "Welcome! What's your role and what are you trying to accomplish?"
→ FAIL — Two questions in one turn; task question present.
```

## Guardrails

- **Score is binary:** 1.0 (pass) or 0.0 (fail). No partial credit.
- **Not applicable** to headless mode or replay mode fixtures. Set `pass: true, score: 1.0, notes: "N/A — not interactive"` for those.

## Failure Behavior

- If transcript is empty → `pass: false, score: 0.0, notes: "Empty transcript — no first turn found."`
- If first turn cannot be parsed → `pass: false, score: 0.0, notes: "Could not parse first assistant turn."`
