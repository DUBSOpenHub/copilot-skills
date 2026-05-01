---
name: agent-conductor
description: >
  Multi-agent fleet conductor with real-time TUI observability. Launches
  multiple Terminal Stampede commander groups, keeps them coordinated through
  live collaboration ledgers, and applies sealed Shadow Score evaluation.
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

# Agent Conductor

Agent Conductor coordinates multiple commander-led agent groups so they can
propose, review, improve, converge, and broadcast learnings while the run is
active. It uses Terminal Stampede for visible tmux panes and process lifecycle,
bounded sub-agent fan-out semantics, Agent Pulse or Stampede monitor for
real-time observability, and Shadow Score for sealed post-run quality gates.

Use user-facing terminology **sub-agents**. The compatibility ledger filename
`child-agents.jsonl` may appear in paths, but responses should use
**sub-agents**.

## Command Grammar

| Pattern | Action |
|---|---|
| `agent conductor` | Ask for repo, mission, model tier, and scale |
| `agent conductor on REPO : MISSION` | Launch with questions for missing tier/scale |
| `agent conductor premium max on REPO : MISSION` | Launch 5 premium commander groups |
| `agent conductor standard small on REPO : MISSION` | Launch smaller standard-tier run |
| `agent conductor status [RUN_ID]` | Show concise run stats and insights |
| `agent conductor teardown RUN_ID` | Stop the underlying Stampede tmux session |

Default repo is the current working directory. Mission text after `:` is
required for a launch.

## Launch Questions

If absent, ask exactly one question at a time.

1. Model tier:
   - `Premium` - frontier/premium models for commanders and sub-agents.
   - `Standard` - standard capable models; no mini/cheap silent downgrade.
2. Scale:
   - `Small` - 2 commander groups.
   - `Standard` - 3 commander groups.
   - `Max` - 5 commander groups.
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

Never silently use these models for Agent Conductor sub-agents:

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

## Prerequisites and Preflight

Before launch, verify the local runtime exists:

```bash
command -v copilot
command -v tmux
command -v python3
command -v git
test -x ~/bin/stampede.sh
test -x ~/bin/stampede-monitor.sh
```

If `~/bin/stampede.sh` or `~/bin/stampede-monitor.sh` is missing, stop and
tell the user to run the Agent Conductor quick installer or install Terminal
Stampede first. Do not start an Agent Conductor run without the Stampede
launcher and monitor because the dashboard and recovery contracts depend on
their run files.

## Run Layout

Agent Conductor reuses Stampede's repo-local runtime so Agent Pulse and tmux
monitors work without another service:

```text
REPO/.stampede/RUN_ID/
  state.json
  fleet.json
  queue/
  claimed/
  results/
  commanders/commander-###/
    manifest.json
    context-capsule.json
    assignments.json
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

Structured schema:

```json
{
  "ts": "ISO-8601",
  "run_id": "run-...",
  "profile": "metaswarm",
  "queue": 0,
  "claimed": 0,
  "results": 5,
  "total_tasks": 5,
  "lines": [
    "cmd 0/5 active · sub-agents 0 running / 1250 done / 1250 seen · q 0 · claimed 0 · results 5/5",
    "collab p5 r18 i11 c8 b7"
  ],
  "agents": [
    {
      "id": "commander-001",
      "status": "success",
      "phase": "complete",
      "active": false,
      "model": "claude-opus-4.7",
      "heartbeat_age_s": 4,
      "squad_leads": 50,
      "squad_target": 50,
      "workers": 250,
      "worker_target": 250,
      "sub_agents_seen": 300,
      "sub_agents_running": 0,
      "sub_agents_done": 300,
      "sub_agents_failed": 0
    }
  ]
}
```

## Step 0 - SQL Tracking

Create tables if needed:

```sql
CREATE TABLE IF NOT EXISTS agent_conductor_runs (
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

CREATE TABLE IF NOT EXISTS agent_conductor_events (
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
  "product": "agent-conductor",
  "runtime_profile": "metaswarm",
  "repo_path": "/abs/repo",
  "mission": "user mission",
  "model_tier": "premium | standard",
  "scale": "small | standard | max",
  "commander_count": 5,
  "collab": {"path": "BASE/collab"},
  "shadow_score": {"sealed": true, "seal_hash": "sha256:..."},
  "phase": "preparing",
  "status": "running"
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

Create `collab/protocol.json` with Python `json.dump` before commanders start:

```json
{
  "version": 1,
  "workflow": ["propose", "peer_review", "improve", "consensus", "broadcast", "adopt"],
  "ledgers": {
    "proposals": "proposals.jsonl",
    "reviews": "reviews.jsonl",
    "improvements": "improvements.jsonl",
    "consensus": "consensus.jsonl",
    "broadcasts": "broadcasts.jsonl"
  },
  "record_required_fields": ["ts", "run_id", "commander_id", "event", "item_id", "summary", "evidence", "confidence", "source_refs"],
  "append_only": true
}
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

`adopt` is not a separate ledger. It is represented by a commander writing an
`improvement` or `consensus` record that cites the `broadcasts.jsonl` item it
adopted in `source_refs`.

## Depth Guard

Every commander and worker prompt MUST carry `depth_config` with `can_launch`, `current_depth`, and `max_depth`.

A commander MUST NOT spawn or launch sub-agents when `can_launch` is false or `current_depth >= max_depth`.

Before spawning sub-agents, increment `current_depth` by 1 and set `can_launch` for the next depth from the same rule.

## Step 5 - Commander Manifests

Write one queue manifest per commander. Use different domains so commander
groups overlap enough to collaborate but still bring distinct views.

Recommended domain rotation:

```text
architecture, implementation, telemetry-dashboard, model-depth-recovery, synthesis-shadow-score
```

Each manifest must include:

```json
{
  "task_id": "commander-001",
  "commander_id": "commander-001",
  "run_id": "run-...",
  "kind": "commander",
  "role": "commander",
  "profile": "metaswarm",
  "product": "agent-conductor",
  "runtime_profile": "metaswarm",
  "swarm_scale": "ss-250",
  "per_commander_full_swarm": true,
  "objective": "original mission",
  "mission": "original mission",
  "domain": "architecture",
  "repo_path": "/abs/repo",
  "branch": "havoc-swarm/run-.../commander-001",
  "model_tier": "premium",
  "model_policy": "premium",
  "premium_model_pool": ["claude-opus-4.7", "gpt-5.5", "claude-opus-4.6", "gpt-5.4"],
  "banned_child_models": ["claude-haiku-4.5", "gpt-5.4-mini", "gpt-5-mini", "gpt-4.1"],
  "shadow_score": {"sealed": true, "seal_hash": "sha256:..."},
  "collab": {"path": "BASE/collab", "protocol": "BASE/collab/protocol.json"},
  "constraints": {
    "max_workers": 250,
    "squad_leads_per_commander": 50,
    "workers_per_squad_lead": 5,
    "workers_per_commander": 250,
    "required_status_values": ["success", "partial", "failed"]
  },
  "depth_budget": {"squads_allocated": 50, "squads_max": 50},
  "depth_config": {"can_launch": true, "current_depth": 0, "max_depth": 2},
  "launch_proof": {
    "required": true,
    "state_file": "BASE/commanders/commander-001/swarm-state.json",
    "child_ledger": "BASE/commanders/commander-001/child-agents.jsonl",
    "sub_agent_ledger": "BASE/commanders/commander-001/child-agents.jsonl"
  },
  "telemetry_contract": {
    "state_file": "BASE/commanders/commander-001/swarm-state.json",
    "child_ledger": "BASE/commanders/commander-001/child-agents.jsonl",
    "sub_agent_ledger": "BASE/commanders/commander-001/child-agents.jsonl",
    "launch_proof_required": true
  }
}
```

Runtime note: Stampede may use `profile: metaswarm` internally so existing
monitor and Agent Pulse parsers work. `product: agent-conductor` preserves the
user-facing product identity.

### `swarm-state.json` schema

Each commander must keep this state fresh with Python `json.dump`:

```json
{
  "commander_id": "commander-001",
  "run_id": "run-...",
  "status": "running | success | partial | failed",
  "phase": "launching_workers | collecting | complete",
  "model_policy": "premium",
  "squads_target": 50,
  "workers_target": 250,
  "squad_leads_launched": 50,
  "squad_leads_running": 0,
  "squad_leads_completed": 50,
  "squad_leads_failed": 0,
  "workers_launched": 250,
  "workers_running": 0,
  "workers_completed": 250,
  "workers_failed": 0,
  "launch_proof": {
    "state_file": "BASE/commanders/commander-001/swarm-state.json",
    "child_ledger": "BASE/commanders/commander-001/child-agents.jsonl",
    "sub_agent_ledger": "BASE/commanders/commander-001/child-agents.jsonl"
  },
  "updated_at": "ISO-8601"
}
```

Partial runs are explicitly labeled with launch counts. Never call a partial
run a success.

## Commander Prompt Template

Commander prompts must tell the commander to read `manifest.json`, enforce
`depth_config.can_launch`, launch only within `constraints.max_workers`, write
launch proof to `swarm-state.json`, append compatibility telemetry to
`child-agents.jsonl`, and write JSON only with Python `json.dump`. The commander
must publish at least one collaboration record when it has useful evidence and
must write `bundle.json` with status `success`, `partial`, or `failed`.

## Worker Prompt Template

Worker prompts must receive `context-capsule.json`, `assignments.json`, and
`depth_config` with `can_launch` false unless a future explicit depth budget
allows deeper work. Workers write atomic findings under `atoms/`, cite evidence,
and use Python `json.dump` for every JSON file.

## Step 6 - Launch Terminal Stampede

Invoke the installed Stampede launcher. `--metaswarm` gives each commander its
own visible pane and nested sub-agent proof contract.

```bash
STAMPEDE_OBJECTIVE="$MISSION" \
STAMPEDE_METASWARM_NO_GATES=1 \
STAMPEDE_MODEL_POLICY="$MODEL_TIER" \
STAMPEDE_PREMIUM_MODEL_POOL="$PREMIUM_MODEL_POOL" \
STAMPEDE_BANNED_CHILD_MODELS="claude-haiku-4.5,gpt-5.4-mini,gpt-5-mini,gpt-4.1" \
STAMPEDE_SQUAD_LEADS_PER_COMMANDER=50 \
STAMPEDE_WORKERS_PER_SQUAD_LEAD=5 \
STAMPEDE_WORKERS_PER_COMMANDER=250 \
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
- `commanders/*/child-agents.jsonl` for compatibility sub-agent telemetry.
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
   Agent Conductor run a full success.
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
3. Recompute the hash for `shadow-score/sealed/criteria.json` and compare it to
   `shadow-score/seal.sha256`. If it differs, stop and mark the scorecard as
   failed due to seal mismatch.
4. Open the sealed Shadow Score criteria only in the orchestrator context.
5. Score each commander and the final synthesis on:
    - requirement coverage
    - collaboration quality
    - evidence quality
    - test/validation impact
    - synthesis usefulness
6. Write `shadow-score/scorecard.json`.
7. Produce a final answer with:
    - commander status table
    - concise collaboration stats
    - Shadow Score summary
   - best findings and consensus
    - partial/failure caveats
    - next action

`scorecard.json` schema:

```json
{
  "run_id": "run-...",
  "seal_verified": true,
  "criteria_hash": "sha256:...",
  "overall_score": 0.0,
  "status": "success | partial | failed",
  "dimensions": {
    "requirement_coverage": 0.0,
    "collaboration_quality": 0.0,
    "evidence_quality": 0.0,
    "test_validation_impact": 0.0,
    "synthesis_usefulness": 0.0
  },
  "commander_scores": [
    {"commander_id": "commander-001", "status": "success", "score": 0.0, "evidence_refs": []}
  ],
  "partial_caveats": []
}
```

## Completion Criteria

- Run directory exists with state, collab bus, sealed Shadow Score hash, queue,
  commander telemetry, and concise stats feed.
- Stampede launched with `--metaswarm`.
- Agent Pulse or Stampede monitor can show concise stats and insights.
- Every commander has `success`, `partial`, or `failed`.
- Final synthesis includes Shadow Score results without exposing sealed criteria.
