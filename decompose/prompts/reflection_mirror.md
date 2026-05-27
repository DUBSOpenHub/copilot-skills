# reflection_mirror.md — Step 6: Reflection Mirror

## Purpose
Restate the captured intent, knowns, unknowns, and blind spots in plain language so the user can confirm or correct before any artifact is written. No artifact is emitted until `confirmed: true` is set.

## Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `clarification_state` | object | ✓ | Complete state including blind_spots, knowns, unknowns, meter_pct |
| `role` | string | ✓ | Adapts vocabulary and framing |
| `sanitized_intent` | string | ✓ | Redacted goal text |

## Output Contract

**Format:** Structured plain-language summary + confirmation prompt. No JSON, no headers. Maximum 300 words.

**Required sections (in order):**

1. **Mirror header:** `"Here's what I'm planning to build from, [role-appropriate address]:"` (or friendly equivalent)
2. **Goal restatement:** One sentence restating the confirmed intent in the user's own words.
3. **What I know:** Bullet list of `knowns` in plain language (≤ 8 items; group if more).
4. **What I'm not sure about:** Bullet list of `unknowns` in plain language.
5. **Things to watch:** Brief list of blind spots (1-line each, classification label in plain English).
6. **Confirmation prompt:** `"Does this match what you have in mind? If anything looks off, tell me now and I'll update it before writing your plan."`

**On user confirmation:**
- Set `clarification_state.confirmed = true`
- Append to `replay.jsonl`:
```json
{ "event": "reflection_confirmed", "meter_pct": <N>, "confirmed": true }
```
- Proceed to Synthesis (task_genome_synthesis + markdown_brief in parallel).

**On user correction:**
- Accept the correction, update relevant knowns/unknowns/blind_spots.
- Re-issue the mirror with updated content.
- Do not restart Q&A — apply corrections directly.
- `questions_asked` counter is not incremented for corrections.
- Append to `replay.jsonl`:
```json
{ "event": "reflection_corrected", "correction": "<user's correction>", "field_updated": "<knowns|unknowns|blind_spots>" }
```

## Guardrails

- **MUST NOT** write any artifact (brief.md, genome.json, AGENTS.md) before `confirmed: true`.
- **MUST NOT** introduce new information not established during Q&A.
- **MUST NOT** interpret or expand the user's goal beyond what was stated.
- **MUST NOT** use technical jargon with non-technical roles.
- **MUST NOT** ask new clarifying questions — this step is confirmation only.
- **MUST NOT** silently drop any blind spot from the summary.
- **MUST NOT** expose internal field names (e.g., `genome_id`, `clarification_state`).
- **MUST NOT** include chain-of-thought, scoring, or classification internals.

## Examples

### Pass — developer, OAuth goal confirmed
```
Here's what I'm planning to build from:

Goal: Add GitHub OAuth login to your Python API, replacing JWT auth, targeting staging deployment within two weeks.

What I know:
• Python API using FastAPI
• GitHub is the OAuth provider
• JWT auth will be replaced (not kept alongside OAuth)
• Target: staging first, then production
• Two-week timeline
• You'll handle the implementation yourself

What I'm not sure about:
• Your current test coverage for auth
• Whether rollback is required if staging fails
• Who needs to approve the JWT removal

Things to watch:
• ASSUMPTION: I'm assuming FastAPI — let me know if that's wrong.
• RISK: Logged-in users may be logged out during the JWT → OAuth cutover.
• GATE: JWT removal needs your explicit approval before that step runs.

Does this match what you have in mind? If anything looks off, tell me now and I'll update it before writing your plan.
```

### Pass — non-technical creator, newsletter, confirmed
```
Here's what I'm planning for you:

Goal: Launch a weekly email newsletter about sustainable living, targeting a small starting audience.

What I know:
• Weekly sending cadence
• Topic: sustainable living
• Starting small (under 500 subscribers)
• You'll write the content yourself

What I'm not sure about:
• Which email platform you'd like to use
• Whether you have a subscriber list yet

Things to watch:
• ASSUMPTION: You're managing this solo.
• UNKNOWN: No email platform chosen yet — this affects most steps.
• GATE: Sending your first email is a public action you'll approve manually.

Does this match what you have in mind?
```

### Failure — artifact emitted before confirmation
**Bad behavior:** Emitting `genome.json` in the same turn as the mirror summary.
*Reason: `confirmed` is not yet set. Violates FR-6 and safety invariant.*

### Failure — new question asked
**Bad behavior:** "Does this look right? Also, what's your deployment environment?"
*Reason: No new questions allowed in Reflection Mirror step. Correction only.*

## Failure Behavior

- `clarification_state` incomplete → issue mirror with available data; note missing fields as unknowns.
- User confirms but immediately adds a correction → accept correction, update state, re-issue updated mirror before proceeding.
- User says "start over" → reset `clarification_state` to initial values, return to intent_capture.
- Three consecutive failed confirmations → surface a summary of discrepancies and ask user to provide a written correction rather than verbal back-and-forth.
