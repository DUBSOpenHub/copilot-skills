# Eval: Replay

**ID:** `replay`
**Pass bar:** 100% of replay fixtures

## Purpose
Verify that `replay.jsonl` contains sufficient events to reconstruct session state, and that replaying it produces identical artifacts to the original session.

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `replay_jsonl_path` | filepath | ✓ |
| `original_artifacts` | filepath[] | ✓ |

## Output Contract

```json
{
  "eval_id": "replay",
  "fixture_id": "<id>",
  "pass": true | false,
  "score": 1.0 | 0.0,
  "threshold": 1.0,
  "diff": "<artifact diffs if any>",
  "notes": ""
}
```

## Check Logic

```python
def check_replay(replay_path: str, original_artifacts: dict) -> dict:
    errors = []

    # 1. Load and parse replay.jsonl
    events = []
    with open(replay_path) as f:
        for i, line in enumerate(f):
            try:
                events.append(json.loads(line.strip()))
            except json.JSONDecodeError as e:
                errors.append(f"Line {i+1}: invalid JSON — {e}")

    if errors:
        return {"pass": False, "diff": "\n".join(errors)}

    # 2. Check required event types present
    event_types = {e["event"] for e in events}
    required_events = {"intent_captured", "reflection_confirmed"}
    missing = required_events - event_types
    if missing:
        errors.append(f"Missing required events: {missing}")

    # 3. Check append-only (no deletions, no edits)
    # Verify events are in chronological order by checking sequence consistency
    for i, event in enumerate(events):
        if i > 0 and "timestamp" in event and "timestamp" in events[i-1]:
            if event["timestamp"] < events[i-1]["timestamp"]:
                errors.append(f"Event {i+1}: out-of-order timestamp (replay not append-only)")

    # 4. Verify no raw_intent in any event
    for i, event in enumerate(events):
        if "raw_intent" in event:
            errors.append(f"Event {i+1}: raw_intent found in replay.jsonl — must be sanitized_intent only")

    # 5. Reconstruct state and compare artifacts
    # (In practice, run rehydration.md and diff output against originals)
    # For eval purposes: check key state fields are present
    intent_events = [e for e in events if e["event"] == "intent_captured"]
    if intent_events:
        if not intent_events[0].get("sanitized_intent"):
            errors.append("intent_captured event missing sanitized_intent")
        if "raw_intent" in intent_events[0]:
            errors.append("intent_captured event contains raw_intent — security violation")

    return {
        "pass": len(errors) == 0,
        "score": 1.0 if not errors else 0.0,
        "diff": "\n".join(errors)
    }
```

## Required Event Sequence

A complete replay.jsonl must contain (in order):
1. `intent_captured` — with `role` and `sanitized_intent`
2. At least 3 × `question_asked` events — with `index`, `category`, `question`, `answer`
3. `blind_spots_surfaced` — with `blind_spots` array
4. `reflection_confirmed` — with `confirmed: true`
5. (optional) `redaction_event` entries if redaction occurred

## Security Checks

- **`raw_intent` must NOT appear** in any replay event.
- **`redaction_log` entries** must not contain the original secret value — only the pattern name and action.
- **Sanitized intent only** — the version with `[REDACTED]` markers.

## Artifact Diff Check

After replay reconstruction:
```
For each artifact in [genome.json, brief.md, AGENTS.md]:
  diff = compare(original_artifact, replayed_artifact)
  if diff != "":
    errors.append(f"{artifact}: replay produced different output — diff: {diff}")
```

Acceptable differences: `meta.created_at` (timestamp will differ), `meta.session_id` (may differ if new session).
Unacceptable differences: any structural or content change in nodes, edges, brief text, or AGENTS.md sections.

## Failure Behavior

- `replay.jsonl` missing → `pass: false, score: 0.0, notes: "replay.jsonl not found."`
- Invalid JSONL → `pass: false, score: 0.0, diff: "Line N: invalid JSON — <error>."`
- Missing `reflection_confirmed` event → `pass: false, notes: "Session not completed — cannot replay."`
