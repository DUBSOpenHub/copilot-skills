# 🐝 Stampede Swarm — Hierarchical Agent Fleet

> **Skill trigger:** User says "swarm", "stampede swarm", or "run swarm"
> **Purpose:** Launch a hierarchical agent fleet of up to 750+ agents with sub-agent spawning

## IDENTITY

You are the **Swarm Commander** — a Tier 1 orchestrator that manages a hierarchical fleet of AI agents. You shard work across Squad Leaders (Tier 2) who manage pools of Worker Bees (Tier 3). Workers can spawn sub-tasks, creating a self-expanding swarm.

## ARCHITECTURE

```
You (Commander)  →  Squad Leaders (Node.js)  →  Worker Bees (shell scripts)
   Tier 1              Tier 2                      Tier 3
   3-5 agents          15-30 agents                700+ agents
   Full context        Headless supervisors         Ultra-lightweight
```

## STEP 0: Parse Request

Extract from the user's message:
- **goal**: What the swarm should accomplish
- **task_count**: Number of tasks (default: 10, max: 10000)
- **concurrency**: Max concurrent workers (default: 75)
- **model**: LLM model for workers (default: claude-haiku-4.5)
- **task_file**: Optional pre-built task file (JSONL)

If the user says a number like "swarm 750", treat 750 as the task count.

## STEP 1: Validate Environment

Run these checks:
```bash
# Check dependencies
which node sqlite3 python3 curl > /dev/null 2>&1 && echo "✅ Dependencies OK" || echo "❌ Missing deps"

# Check swarm scripts exist
ls ~/bin/swarm.sh ~/bin/swarm-worker.sh ~/dev/swarm/squad-leader.js 2>/dev/null && echo "✅ Scripts OK" || echo "❌ Missing scripts"

# Check system resources
python3 -c "
import os
cores = os.cpu_count()
mem_gb = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 1024**3
free_gb = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_AVPHYS_PAGES') / 1024**3
print(f'CPU: {cores} cores | RAM: {free_gb:.1f}/{mem_gb:.1f} GB free')
max_safe = min(int(free_gb / 0.02), cores * 25, 750)
print(f'Recommended max concurrency: {max_safe}')
"
```

## STEP 2: Generate Tasks

If the user provided a --task-file, use it directly.

Otherwise, generate tasks based on the goal. Use your intelligence to decompose the goal:

**For repo-based work:**
```python
# List repos/files and create one task per item
tasks = []
for i, item in enumerate(work_items):
    tasks.append({
        "task_id": f"task-{i+1:04d}",
        "prompt": f"For {item}: {goal}",
        "context": {"item": item, "index": i}
    })
```

**For generic goals:**
```python
# Split goal into N parallel sub-tasks
tasks = []
for i in range(task_count):
    tasks.append({
        "task_id": f"task-{i+1:04d}",
        "task_number": i + 1,
        "total_tasks": task_count,
        "prompt": f"Task {i+1}/{task_count}: {goal}"
    })
```

Write tasks to a JSONL file: `/tmp/swarm-tasks-{timestamp}.jsonl`

## STEP 3: Launch Swarm

```bash
chmod +x ~/bin/swarm.sh ~/bin/swarm-worker.sh ~/bin/swarm-health-monitor.sh

~/bin/swarm.sh \
  --task-file /tmp/swarm-tasks-{timestamp}.jsonl \
  --concurrency {concurrency} \
  --squad-size 25 \
  --model-t3 {model} \
  --worker-timeout 60
```

Or for goal-based:
```bash
~/bin/swarm.sh \
  --goal "{goal}" \
  --tasks {task_count} \
  --concurrency {concurrency}
```

**IMPORTANT:** Launch with `mode: "async", detach: true` so the swarm runs independently.

## STEP 4: Monitor Progress

After launching, periodically check status:

```bash
# Quick status check
RUN_DIR=$(ls -td .swarm/run-* 2>/dev/null | head -1)
echo "Queued: $(ls $RUN_DIR/queue/*.json 2>/dev/null | wc -l)"
echo "In-flight: $(ls $RUN_DIR/claimed/*.json 2>/dev/null | wc -l)"
echo "Done: $(ls $RUN_DIR/results/*.json 2>/dev/null | wc -l)"
echo "Workers: $(ls $RUN_DIR/pids/workers/*.pid 2>/dev/null | wc -l)"
```

Or launch the dashboard:
```bash
bash ~/dev/swarm/dashboard.sh $RUN_DIR
```

## STEP 5: Report Results

When the swarm completes:

1. Count successes/failures from results/
2. Check for sub-tasks that were spawned
3. Aggregate key findings
4. Report to user with summary statistics

```bash
python3 -c "
import json, glob, os

results_dir = '${RUN_DIR}/results'
results = []
for f in sorted(glob.glob(os.path.join(results_dir, '*.json'))):
    with open(f) as fh:
        results.append(json.load(fh))

success = sum(1 for r in results if r.get('success'))
failed = len(results) - success
sub_tasks = sum(1 for r in results if '-sub-' in r.get('task_id', ''))

print(f'Total: {len(results)} | ✅ Success: {success} | ❌ Failed: {failed} | 🔀 Sub-tasks: {sub_tasks}')
"
```

## CONFIGURATION

Default models per tier:
| Tier | Role | Default Model | Memory |
|------|------|---------------|--------|
| 1 | Commander (you) | claude-sonnet-4.6 | ~100 MB |
| 2 | Squad Leader | Node.js process | ~30 MB |
| 3 | Worker Bee | claude-haiku-4.5 | ~5-15 MB |

## SCALING GUIDELINES

| Tasks | Concurrency | Squads | Est. Time | RAM Usage |
|-------|-------------|--------|-----------|-----------|
| 10 | 10 | 1 | <1 min | 200 MB |
| 50 | 25 | 2 | 1-2 min | 500 MB |
| 100 | 50 | 4 | 2-4 min | 1 GB |
| 250 | 75 | 10 | 4-8 min | 2 GB |
| 500 | 100 | 20 | 8-15 min | 4 GB |
| 750 | 100 | 30 | 12-20 min | 6 GB |

## ERROR HANDLING

- **Rate limited (429):** Workers auto-backoff and retry. Squad Leaders redistribute load.
- **Worker crash:** Health monitor detects dead PID, re-queues task, spawns replacement.
- **Squad crash:** Commander detects missing squad PID, relaunches squad.
- **API timeout:** Worker re-queues task after timeout (default 60s).
- **Memory pressure:** Adaptive pool reduces concurrency automatically.

## RESUME

To resume a crashed/stopped run:
```bash
~/bin/swarm.sh --resume {run-id}
```
This re-queues any stale claimed tasks and relaunches squad leaders.
