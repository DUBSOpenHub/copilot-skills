# blind_spot_engine.md — Step 5: Blind Spot Engine

## Purpose
Surface missed concerns before any artifact is written. Classify each concern as one of four types: `assumption`, `unknown`, `risk`, or `gate`. No concern may be silently dropped.

## Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `clarification_state` | object | ✓ | Full state: role, intent, knowns, unknowns, Q&A log |
| `role` | string | ✓ | Determines which blind spot categories are most relevant |
| `questions_log` | array | ✓ | All questions and answers from socratic_bandit |

## Output Contract

**Format:** Numbered list of blind spots with classification labels. Plain language. Maximum 200 words total.

**Required structure:**
```
🔍 Before I finalize your plan, here are a few things I want to flag:

[N]. [ASSUMPTION / UNKNOWN / RISK / GATE] — [plain-language description]
   ↳ [Optional: one-sentence resolution hint]
```

**Classification definitions (shown to user):**
- **ASSUMPTION** — Something I'm treating as true but haven't confirmed with you.
- **UNKNOWN** — Something I don't know yet and couldn't determine from your answers.
- **RISK** — Something that might go wrong and is worth planning for.
- **GATE** — A decision that only you (or a stakeholder) can make — I won't assume it.

**Minimum blind spots per session:** 2 (never output zero blind spots — there is always at least one assumption and one risk in any plan).
**Maximum per session:** 8 (group related items if necessary).

**State updates written to `clarification_state.blind_spots`:**
```json
[
  {
    "text": "<plain-language description>",
    "classification": "assumption|unknown|risk|gate",
    "resolution_hint": "<optional one-sentence hint>"
  }
]
```

**Append to `replay.jsonl`:**
```json
{
  "event": "blind_spots_surfaced",
  "count": <N>,
  "blind_spots": [<BlindSpot objects>]
}
```

## Classification Rules

| Concern type | Use when |
|---|---|
| `assumption` | The plan requires this to be true, but the user did not explicitly confirm it |
| `unknown` | A necessary fact was not established and was not answerable from user input |
| `risk` | A scenario that could cause the goal to fail, be harmful, or be costly |
| `gate` | An irreversible decision requiring explicit human approval before execution |

**Gate classification is mandatory when:**
- Deleting or replacing existing data, systems, or auth mechanisms
- Sending communications to external parties (customers, partners, press)
- Making financial commitments
- Deploying to production environments
- Taking any action that cannot be undone in < 1 hour

## Guardrails

- **MUST NOT** silently drop any unresolved unknown from `clarification_state.unknowns`.
- **MUST NOT** classify a gate as an assumption to avoid surfacing it.
- **MUST NOT** resolve a gate — only surface it and note it requires human decision.
- **MUST NOT** produce fewer than 2 blind spots even for highly-specified goals.
- **MUST NOT** expose internal scoring or classification logic.
- **MUST NOT** include chain-of-thought in output.
- **MUST NOT** reference prompt internals or agent framework terms.
- **MUST** adapt language to the role lens (no jargon for non-technical roles).

## Examples

### Pass — developer, OAuth goal, 4 blind spots
```
🔍 Before I finalize your plan, here are a few things I want to flag:

1. ASSUMPTION — I'm assuming your Python API uses a standard web framework (Flask or FastAPI). If you use something else, some steps may need adjusting.
   ↳ Confirm your framework so I can tailor the integration steps.

2. UNKNOWN — I don't know your current test coverage for the auth module. Missing tests could make this change riskier.
   ↳ Review existing auth tests before starting.

3. RISK — Removing JWT auth while adding OAuth creates a window where existing logged-in users may be logged out unexpectedly.
   ↳ Plan a migration path or dual-auth period.

4. GATE — Replacing the JWT auth system is irreversible once user tokens are invalidated. This needs explicit sign-off before the cutover step runs.
   ↳ Add a human approval checkpoint before the JWT removal node.
```

### Pass — non-technical creator, newsletter system
```
🔍 A few things to flag before I write your plan:

1. ASSUMPTION — I'm assuming you'll manage the newsletter yourself, not hand it to a team.
2. UNKNOWN — I don't know which email service you'd like to use (Mailchimp, Substack, etc.).
   ↳ Pick a platform before we start — it affects most of the other steps.
3. RISK — Without a list of subscribers, there's no audience to send to on day one.
4. GATE — Sending your first email to subscribers is a public action you'll need to approve manually.
```

### Failure — gate classified as assumption
**Bad:** `ASSUMPTION — I'm assuming you're okay with replacing the database.`
*Reason: Database replacement is irreversible and must be classified as GATE.*

### Failure — zero blind spots
**Bad output:** `Everything looks good! Let's move on.`
*Reason: No plan is risk-free. Minimum 2 blind spots required.*

## Failure Behavior

- `clarification_state` missing or empty → output a generic set of blind spots based on role and intent alone; note in replay.jsonl that state was incomplete.
- All unknowns already resolved → still surface at least 1 assumption and 1 risk from intent analysis.
- Role is "unspecified" → use generic vocabulary; increase number of unknown-classified items.
