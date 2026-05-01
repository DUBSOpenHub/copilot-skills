---
name: swarmmesh
description: >
  Multi-swarm collaboration orchestrator with real-time TUI observability.
  Launches multiple Terminal Stampede commander swarms, connects them through
  a live collaboration mesh, and applies sealed Shadow Score evaluation.
tools:
  - bash
  - glob
  - view
  - sql
  - ask_user
  - task
  - read_agent
  - list_agents
---

# SwarmMesh

SwarmMesh connects multiple commander-led swarms so they can propose, review,
improve, converge, and broadcast learnings while the run is active. It uses
Terminal Stampede for visible tmux panes and process lifecycle, Swarm Command
semantics for bounded sub-agent fan-out, Agent Pulse or Stampede monitor for
real-time observability, and Shadow Score for sealed post-run quality gates.

Use user-facing terminology **sub-agents**. The compatibility ledger filename
`child-agents.jsonl` may appear in paths, but responses should use
**sub-agents**.

## Command Grammar

| Pattern | Action |
|---|---|
| `swarmmesh` | Ask for repo, mission, model tier, and scale |
| `swarmmesh on REPO : MISSION` | Launch with questions for missing tier/scale |
| `swarmmesh premium max on REPO : MISSION` | Launch 5 premium commander swarms |
| `swarmmesh standard small on REPO : MISSION` | Launch smaller standard-tier run |
| `swarmmesh status [RUN_ID]` | Show concise run stats and insights |
| `swarmmesh teardown RUN_ID` | Stop the underlying Stampede tmux session |

Default repo is the current working directory. Mission text after `:` is
required for a launch.

## Launch Questions

If absent, ask exactly one question at a time.

1. Model tier:
   - `Premium` - frontier/premium models for commanders and sub-agents.
   - `Standard` - standard capable models; no mini/cheap silent downgrade.
2. Scale:
   - `Small` - 2 commander swarms.
   - `Standard` - 3 commander swarms.
   - `Max` - 5 commander swarms.
3. Dashboard:
   - `Agent Pulse + Stampede monitor` recommended.
   - `Stampede monitor only`.

## Model Tiers

Premium model rotation:

```text
claude-opus-4.7,gpt-5.5,claude-opus-4.6,gpt-5.4,claude-opus-4.5,gpt-5.2,claude-sonnet-4.6,gpt-5.3-codex,claude-sonnet-4.5,gpt-5.2-codex
```

Standard model rotation:

```text
claude-sonnet-4.6,gpt-5.4,claude-sonnet-4.5,gpt-5.3-codex,gpt-5.2-codex,gpt-5.2
```

Never silently use these models for SwarmMesh sub-agents:

```text
claude-haiku-4.5,gpt-5.4-mini,gpt-5-mini,gpt-4.1
```

Pass the chosen tier through the run state, commander manifests, and Stampede
environment. Stampede exposes the active policy as:

```text
STAMPEDE_MODEL_POLICY
STAMPEDE_PREMIUM_MODEL_POOL
STAMPEDE_BANNED_CHILD_MODELS
STAMPEDE_SQUAD_LEADS_PER_COMMANDER
STAMPEDE_WORKERS_PER_SQUAD_LEAD
STAMPEDE_WORKERS_PER_COMMANDER
```

## Run Layout

SwarmMesh reuses Stampede's repo-local runtime so Agent Pulse and tmux monitors
work without another service:

```text
REPO/.stampede/RUN_ID/
  state.json
  fleet.json
  queue/
  claimed/
  results/
  commanders/commander-###/
    swarm-state.json
    child-agents.jsonl
    bundle.json
    atoms/
    logs/
  collab/
    protocol.json
    proposals.jsonl
    reviews.jsonl
    improvements.jsonl
    consensus.jsonl
    broadcasts.jsonl
  shadow-score/
    sealed/
      criteria.json
    seal.sha256
    scorecard.json
  orchestrator-commentary.json
  orchestrator-commentary.jsonl
```

`orchestrator-commentary.json` must stay concise: stats and insights only. Good
shape:

```text
cmd 3/5 active · sub-agents 112 running / 480 done / 620 seen · q 0 · claimed 3 · results 2/5
collab p5 r18 i11 c8 b7
commander-004 launching_workers · squads 32/50 · sub-agents 160/250 · run 42 done 118 fail 0
```

## Step 0 - SQL Tracking

Create tables if needed:

```sql
CREATE TABLE IF NOT EXISTS swarmmesh_runs (
    run_id TEXT PRIMARY KEY,
    repo_path TEXT NOT NULL,
    mission TEXT NOT NULL,
    model_tier TEXT NOT NULL,
    scale TEXT NOT NULL,
    commander_count INTEGER NOT NULL,
    status TEXT DEFAULT 'running',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS swarmmesh_events (
    run_id TEXT NOT NULL,
    ts TEXT DEFAULT (datetime('now')),
    event TEXT NOT NULL,
    detail TEXT
);
```

## Step 1 - Parse and Normalize

Extract:

| Field | Source | Default |
|---|---|---|
| `repo_path` | `on REPO` | current working directory |
| `mission` | text after `:` | ask if missing |
| `model_tier` | premium/standard | ask |
| `scale` | small/standard/max | ask |
| `dashboard` | requested dashboard | Agent Pulse + Stampede monitor |

Map scale to commander count:

| Scale | Commanders |
|---|---:|
| Small | 2 |
| Standard | 3 |
| Max | 5 |

## Step 2 - Create Run Directory

Use `run-YYYYMMDD-HHMMSS`.

```bash
RUN_ID="$(python3 - <<'PY'
import datetime
print("run-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
PY
)"
BASE="$REPO_PATH/.stampede/$RUN_ID"
mkdir -p "$BASE"/{queue,claimed,results,logs,pids,scripts,commanders,collab,shadow-score/sealed}
```

Write `state.json` with Python. Include:

```json
{
  "run_id": "run-YYYYMMDD-HHMMSS",
  "profile": "metaswarm",
  "product": "swarmmesh",
  "repo_path": "/abs/repo",
  "mission": "user mission",
  "model_tier": "premium | standard",
  "scale": "small | standard | max",
  "commander_count": 5,
  "collab": {"path": "BASE/collab"},
  "shadow_score": {"sealed": true, "seal_hash": "sha256:..."},
  "phase": "preparing"
}
```

## Step 3 - Create Sealed Shadow Score Envelope

Generate hidden acceptance criteria before any commander starts. Do not include
criteria contents in commander prompts, manifests, collaboration ledgers, or
responses while the run is active.

Create `shadow-score/sealed/criteria.json`:

```json
{
  "mission": "original mission",
  "generated_at": "ISO-8601",
  "dimensions": [
    "requirement_coverage",
    "collaboration_quality",
    "evidence_quality",
    "test_validation_impact",
    "synthesis_usefulness"
  ],
  "acceptance_checks": [
    "Final synthesis answers the mission directly.",
    "At least two commanders review another commander's proposal.",
    "Consensus items cite source refs from commander bundles or collab ledgers.",
    "Partial runs are explicitly labeled partial with launch counts."
  ]
}
```

Hash it:

```bash
shasum -a 256 "$BASE/shadow-score/sealed/criteria.json" > "$BASE/shadow-score/seal.sha256"
```

Only expose the hash in `state.json` and commander manifests.

## Step 4 - Collaboration Bus

Create append-only ledgers:

```text
collab/proposals.jsonl
collab/reviews.jsonl
collab/improvements.jsonl
collab/consensus.jsonl
collab/broadcasts.jsonl
```

Protocol sequence:

```text
propose -> peer_review -> improve -> consensus -> broadcast -> adopt
```

Every record should include:

```json
{
  "ts": "ISO-8601",
  "run_id": "run-...",
  "commander_id": "commander-001",
  "event": "proposal | peer_review | improvement | consensus | broadcast",
  "item_id": "stable-id",
  "summary": "short",
  "evidence": [],
  "confidence": 0.0,
  "source_refs": []
}
```

## Step 5 - Commander Manifests

Write one queue manifest per commander. Use different domains so swarms overlap
enough to collaborate but still bring distinct views.

Recommended domain rotation:

```text
architecture, implementation, telemetry-dashboard, model-depth-recovery, synthesis-shadow-score
```

Each manifest must include:

```json
{
  "task_id": "commander-001",
  "run_id": "run-...",
  "kind": "commander",
  "profile": "swarmmesh",
  "runtime_profile": "metaswarm",
  "mission": "original mission",
  "domain": "architecture",
  "repo_path": "/abs/repo",
  "model_tier": "premium",
  "model_policy": "premium",
  "shadow_score": {"sealed": true, "seal_hash": "sha256:..."},
  "collab": {"path": "BASE/collab", "protocol": "BASE/collab/protocol.json"},
  "constraints": {
    "max_workers": 250,
    "squad_leads_per_commander": 50,
    "workers_per_squad_lead": 5,
    "workers_per_commander": 250,
    "required_status_values": ["success", "partial", "failed"]
  },
  "depth_budget": {"squads_allocated": 50, "squads_max": 50}
}
```

## Step 6 - Launch Terminal Stampede

Invoke the installed Stampede launcher. `--metaswarm` gives each commander its
own visible pane and nested sub-agent proof contract.

```bash
STAMPEDE_OBJECTIVE="$MISSION" \
STAMPEDE_METASWARM_NO_GATES=1 \
~/bin/stampede.sh \
  --metaswarm \
  --run-id "$RUN_ID" \
  --count "$COMMANDER_COUNT" \
  --repo "$REPO_PATH" \
  --models "$MODEL_POOL" \
  --no-attach
```

If Agent Pulse is requested, launch or refresh it with the repo scan root:

```bash
osascript -e 'tell application "Terminal" to do script "cd ~/copilot-cli-agent-pulse && AGENT_PULSE_SCAN_ROOTS='"$REPO_PATH"' python3 agent_pulse.py --no-splash"' \
  -e 'tell application "Terminal" to activate'
```

## Step 7 - Status and Live Insights

For status, read:

- `orchestrator-commentary.json` for concise stats and insights.
- `fleet.json` for commander models.
- `commanders/*/swarm-state.json` for launch proof.
- `collab/*.jsonl` for collaboration counts.
- `results/commander-*.json` for terminal bundles.

Do not provide heavy narration. Report compactly:

```text
RUN run-... | cmd 3/5 active | sub-agents 112 running / 480 done / 620 seen | results 2/5
collab p5 r18 i11 c8 b7
active: commander-004 launching_workers, commander-005 collecting
```

## Step 8 - Recovery

If a commander dies before a terminal bundle:

1. Check Agent Pulse `commander_alerts` or PID/tmux state.
2. If the commander heartbeat is stale and no tmux process exists, requeue the
   claimed manifest unless generation is exhausted.
3. Mark unrecoverable commanders `partial` or `failed`; never call a partial
   SwarmMesh run a full success.
4. Keep existing collab ledgers and Shadow Score envelope immutable.

For teardown:

```bash
~/bin/stampede.sh --teardown --run-id "$RUN_ID" --repo "$REPO_PATH"
```

## Step 9 - Final Synthesis and Shadow Score

After `results/commander-*.json` count equals commander count:

1. Load all commander bundles.
2. Load `collab/proposals.jsonl`, `reviews.jsonl`, `improvements.jsonl`,
   `consensus.jsonl`, and `broadcasts.jsonl`.
3. Open the sealed Shadow Score criteria only in the orchestrator context.
4. Score each commander and the final synthesis on:
   - requirement coverage
   - collaboration quality
   - evidence quality
   - test/validation impact
   - synthesis usefulness
5. Write `shadow-score/scorecard.json`.
6. Produce a final answer with:
   - commander status table
   - concise collaboration stats
   - Shadow Score summary
   - best findings and consensus
   - partial/failure caveats
   - next action

## Completion Criteria

- Run directory exists with state, collab bus, sealed Shadow Score hash, queue,
  commander telemetry, and concise stats feed.
- Stampede launched with `--metaswarm`.
- Agent Pulse or Stampede monitor can show concise stats and insights.
- Every commander has `success`, `partial`, or `failed`.
- Final synthesis includes Shadow Score results without exposing sealed criteria.
