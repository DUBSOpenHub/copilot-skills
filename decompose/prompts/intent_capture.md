# intent_capture.md — Step 2: Intent Capture

## Purpose
Accept the user's plain-language goal, run the redaction pipeline on all input, sanitize the intent, and confirm it is ready for clarification. Task input is accepted here — not before.

## Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `role` | string | ✓ | Established role from Step 1 (or "unspecified" if deferred) |
| `raw_user_input` | string | ✓ | The user's stated goal, pasted notes, issue text, or rough idea |
| `redaction_patterns` | string[] | internal | Patterns applied by the redaction pipeline |

## Output Contract

**Format:** Plain conversational text + internal state update.

**Required elements:**
1. Brief acknowledgment of the stated goal (1–2 sentences, role-adapted vocabulary).
2. Redaction confirmation: if any redaction occurred, surface a visible notice: `⚠️ I noticed what looks like [type of sensitive data] in your input — I've removed it and marked the location [REDACTED]. Please review before we continue.`
3. Sanitized intent stored in `clarification_state.sanitized_intent`.
4. `replay.jsonl` entry appended with event type `intent_captured` and sanitized intent only.
5. Transition to Understanding Meter (Step 3 / socratic_bandit).

**Internal state written:**
```json
{
  "event": "intent_captured",
  "role": "<role>",
  "sanitized_intent": "<redacted goal text>",
  "redaction_log": []
}
```

## Guardrails

- **MUST** run redaction before storing or surfacing any part of the input.
- **MUST NOT** store `raw_intent` in any written artifact — memory only.
- **MUST NOT** echo raw input back to the user if redaction occurred.
- **MUST NOT** proceed if the sanitized intent is empty after redaction — ask the user to rephrase without sensitive data.
- **MUST NOT** interpret, expand, or infer goals beyond what the user stated — save that for socratic_bandit.
- **MUST NOT** expose internal redaction pattern names or scoring to the user.
- **MUST NOT** include chain-of-thought or classification logic in any output.

## Redaction Pipeline

Apply these patterns in order to `raw_user_input`. Replace matches with `[REDACTED]` or `[REVIEW-REQUIRED]` if uncertain:

| Pattern | Match | Action |
|---|---|---|
| Bearer/API tokens | `sk-[A-Za-z0-9]+`, `ghp_[A-Za-z0-9]+`, `Bearer\s+[^\s]+`, `AIza[A-Za-z0-9_-]+` | `[REDACTED]` |
| Generic secrets | `password\s*[:=]\s*\S+`, `secret\s*[:=]\s*\S+`, `token\s*[:=]\s*\S+` (case-insensitive) | `[REDACTED]` |
| Email in non-comms context | `[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}` | `[REVIEW-REQUIRED]` |
| Phone numbers | `(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}` | `[REDACTED]` |
| SSN / National ID | `\d{3}-\d{2}-\d{4}` | `[REDACTED]` |
| Private keys | `-----BEGIN [A-Z ]+ KEY-----` | `[REDACTED]` |

Log each match to `redaction_log` in `clarification_state`.

## Examples

### Pass — clean input
**Input role:** `developer`
**Input goal:** `I want to add OAuth2 login to our Python API.`
**Output:**
```
Got it — you'd like to add OAuth2 login to a Python API. That's a well-scoped starting point.

Let me ask a few questions to make sure I plan the right work for you.
```
*State: sanitized_intent = "Add OAuth2 login to a Python API", redaction_log = []*

### Pass — input with embedded secret
**Input goal:** `Add OAuth login. My API key is sk-abc123xyz. Use GitHub as the provider.`
**Output:**
```
⚠️ I noticed what looks like an API key in your input — I've removed it and marked the location [REDACTED]. Please review before we continue.

Got it — you'd like to add OAuth login using GitHub as the provider.

Let me ask a few questions to fill in what I don't yet know.
```
*State: sanitized_intent = "Add OAuth login using GitHub as the provider. API key: [REDACTED]", redaction_log: [{pattern_matched: "sk-...", location: "raw_intent:1", action: "REDACTED"}]*

### Failure — empty post-redaction intent
**Input goal:** `sk-abc123 ghp_xyz987`
**Output:**
```
⚠️ I had to remove sensitive-looking content from your input, and after that there wasn't enough left for me to work with.

Could you describe your goal without including any API keys, tokens, or passwords? You can always add those securely later.
```
*State: sanitized_intent = "", flow halted at intent_capture.*

## Failure Behavior

- Empty input after redaction → prompt user to rephrase; do not proceed.
- Input that is purely a question (e.g., "what can you do?") → gently redirect: "I'm here to help you plan your goal. What are you hoping to accomplish?"
- Input with `[REVIEW-REQUIRED]` items → surface them individually and ask user to confirm whether to include or remove.
- If `role` is missing (headless mode without role) → do not proceed; return: `ERROR: role is required in headless mode. Provide --role <value>.`
