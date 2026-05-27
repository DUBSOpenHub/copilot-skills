# rehydration.md — Headless / Replay Mode Entry Point

## Purpose
Enable two entry modes that bypass the interactive pipeline: (1) **Headless mode** — accepts `role` and `task` directly and proceeds to Synthesis; (2) **Replay mode** — reads `replay.jsonl` and reconstructs session state, then re-enters at Synthesis.

## Inputs

### Headless Mode

| Input | Type | Required | Description |
|---|---|---|---|
| `--role` | string | ✓ | Role lens (e.g., `developer`, `pm`, `ops`) |
| `--task` | string | ✓ | Plain-language goal |
| `--questions` | string[] | optional | Pre-answered clarifying questions as `category:answer` pairs |
| `--blind-spots` | string | optional | JSON array of BlindSpot objects |

### Replay Mode

| Input | Type | Required | Description |
|---|---|---|---|
| `--replay` | filepath | ✓ | Path to `replay.jsonl` file |
| `--from-event` | string | optional | Resume from specific event type (default: `reflection_confirmed`) |

## Output Contract

### Headless Mode — Success
Proceeds directly to `task_genome_synthesis` + `markdown_brief` with supplied inputs.
Emits all standard artifacts: `genome.json`, `brief.md`, `AGENTS.md`, `replay.jsonl`.

### Headless Mode — Errors (FR-12)

**Missing role:**
```
ERROR: role is required in headless mode. Provide --role <value>.
Accepted values: developer, pm, designer, ops, researcher, creator, unspecified
```

**Missing task:**
```
ERROR: task is required in headless mode. Provide --task <value>.
```

**Both missing:**
```
ERROR: role is required in headless mode. Provide --role <value>.
ERROR: task is required in headless mode. Provide --task <value>.
```

**Rules for headless errors:**
- Return all applicable errors in one response.
- No silent inference of missing values.
- No partial execution — stop immediately on missing required inputs.
- Return code / status: non-zero (error).

### Replay Mode — Success
Reads `replay.jsonl` events in order, reconstructs `clarification_state`, and verifies that `reflection_confirmed` event exists.
Then re-runs `task_genome_synthesis` + `markdown_brief`.
Emits: `genome.json`, `brief.md`, `AGENTS.md` (same as original session).

### Replay Mode — Errors

**File not found:**
```
ERROR: replay file not found at <path>. Provide a valid --replay path.
```

**Missing confirmation event:**
```
ERROR: replay.jsonl does not contain a reflection_confirmed event. Session was not completed. Cannot synthesize artifacts.
```

**Corrupted / invalid JSONL:**
```
ERROR: replay.jsonl is malformed at line <N>: <error detail>. Cannot reconstruct session state.
```

## Replay State Reconstruction

Read `replay.jsonl` events in sequence and apply:

| Event type | State operation |
|---|---|
| `intent_captured` | Set `role`, `sanitized_intent`, `redaction_log` |
| `question_asked` | Append to `questions_log`, update `knowns`, `unknowns`, `meter_pct` |
| `blind_spots_surfaced` | Set `blind_spots` |
| `reflection_confirmed` | Set `confirmed: true`, `meter_pct` |
| `reflection_corrected` | Apply correction to named field |
| `redaction_event` | Append to `redaction_log` |

After reconstruction, verify: `confirmed == true`. If not, return error.

## Guardrails

- **MUST NOT** silently infer a missing `--role` or `--task` from any context.
- **MUST NOT** execute any synthesis step if required inputs are missing.
- **MUST NOT** expose replay.jsonl contents to the user as raw JSON.
- **MUST NOT** write artifacts if replay reconstruction fails.
- **MUST NOT** re-run redaction on already-sanitized replay events.
- **MUST NOT** include chain-of-thought or internal state dumps in error messages.

## Examples

### Pass — headless success
```
Input: --role developer --task "Add GitHub OAuth to FastAPI API"
Output: genome.json + brief.md + AGENTS.md written successfully.
```

### Pass — headless error (missing role)
```
Input: --task "Add GitHub OAuth to FastAPI API"
Output:
ERROR: role is required in headless mode. Provide --role <value>.
```

### Pass — headless error (both missing)
```
Input: (no arguments)
Output:
ERROR: role is required in headless mode. Provide --role <value>.
ERROR: task is required in headless mode. Provide --task <value>.
```

### Pass — replay success
```
Input: --replay ./replay.jsonl
Output: Session reconstructed from 8 events. Artifacts regenerated.
```

### Failure — silent inference
**Bad behavior:** Missing `--role`, but infers "developer" from task text.
*Reason: Violates FR-12 and SP-2. Always return error for missing required headless inputs.*

## Failure Behavior

- Missing `--role` only → return role error, stop.
- Missing `--task` only → return task error, stop.
- Missing both → return both errors, stop.
- Replay file missing → return file-not-found error, stop.
- Replay missing confirmation → return missing-event error, stop.
- Replay corrupted → return line-specific error, stop.
