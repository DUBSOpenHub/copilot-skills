# role_lens.md — Step 1: Role Lens

## Purpose
Emit the first user-facing output of every interactive session: a role question that establishes the lens through which all subsequent vocabulary, depth, and question selection will be adapted.

## Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `session_start` | boolean | ✓ | True when this is the first turn of a session |
| `previous_role` | string | optional | Role from a prior session or replay (skips question if provided) |

## Output Contract

**Format:** Plain conversational text. No JSON. No markdown headers. Maximum 120 words.

**Required elements:**
1. Warm greeting that does not mention AI, prompts, or technical internals.
2. A clear, open-ended role question with 5–7 concrete example roles listed (non-technical creator, developer, PM/team lead, designer, ops/support, researcher, other).
3. A single follow-up note: user may say "skip" or "other" if their role is not listed.
4. No task question yet — task is blocked until role is established or deferred.

**Example output:**
```
Welcome! Before we dive in, I'd like to understand your perspective so I can ask the most useful questions for you.

What's your role on this work? For example: creator/writer, developer, product manager, designer, ops/support, researcher, or something else entirely? (Just type your role, or say "skip" if you'd prefer not to say.)
```

## Guardrails

- **MUST NOT** accept a task or goal in this turn — redirect if the user volunteers one.
- **MUST NOT** mention JSON, prompts, schemas, agents, or any technical internals.
- **MUST NOT** make assumptions about the user's role from any prior context.
- **MUST NOT** ask two questions at once.
- **MUST NOT** produce output longer than 150 words.
- **MUST NOT** expose chain-of-thought, scoring, or internal classification logic.

## Examples

### Pass — role question issued correctly
**Input:** `session_start: true`
**Output:**
```
Welcome! Before we dive into your goal, I want to make sure I ask the questions that matter most to you.

What's your role on this work? For example: creator or writer, developer, product manager, designer, ops or support, researcher — or something else? You can also say "skip" if you'd rather not specify.
```

### Pass — user volunteers task, redirect issued
**Input:** User says "I want to build a newsletter system"
**Output:**
```
Great — I'd love to help you plan that! First, a quick question so I can tailor things to you:

What's your role on this work? (Creator/writer, developer, PM, designer, ops, researcher, other, or "skip"?)
```

### Failure — task accepted before role
**Input:** `session_start: true`
**Bad output (rejected):**
```
Tell me about your goal. What would you like to build?
```
*Reason: Skips role question entirely. Violates FR-1 and FR-2.*

### Failure — two questions in one output
**Bad output (rejected):**
```
What's your role, and what are you trying to accomplish today?
```
*Reason: Task question must not appear before role is established. Violates FR-2.*

## Failure Behavior

- If `session_start` is false and `previous_role` is present → skip role question, carry role forward, proceed to intent capture.
- If `session_start` is false and `previous_role` is absent → still issue role question; do not guess.
- If user says "skip" or "doesn't matter" → set `role_deferred: true`, set `role: "unspecified"`, proceed to intent capture with generic vocabulary.
- If user provides an unrecognized role → accept it as-is, store in `role` field, proceed.
