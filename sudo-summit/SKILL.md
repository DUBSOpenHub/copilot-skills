---
name: sudo-summit
description: >
  🔐 Sudo Summit — the weekly Agent Roundtable for your GitHub Copilot fleet. Agents
  request powers, grant superpowers to each other, and ship upgrades with one-tap
  permission (sudo). Runs a bounded, safe Town Hall, files asks, and — on your
  approval — applies granted upgrades to real agent files. Say "sudo summit" to start.
license: MIT
metadata:
  version: 0.1.0
tools:
  - bash
  - view
  - edit
  - task
  - ask_user
---

# Sudo Summit

Sudo Summit is the fleet's **weekly power exchange**. `sudo` is the metaphor and the
mechanism: *temporarily grant me elevated power, with permission.* Agents ask each other
for capabilities; a sudoer approves; the upgrade ships and is applied to the real agent.

**Project home:** `sudo-summit/` in the user's workspace (default:
`~/copilot-workspace/sudo-summit`). Its bundled `fleet-commons/` holds the shared
output contract that most upgrades build on.

**First run (forkers):** `python3 summit.py init --fresh` makes you root in `sudoers`,
renders your weekly schedule, discovers your local agents, and clears the demo.

## Trigger
Start when the user says **"sudo summit"**, "run the summit", or "weekly agent roundtable".

## Safety rules (non-negotiable)
- **Never live-invoke mass-spawner agents** (`hive1k`, `swarm-command`, `havoc-hackathon`,
  `stampede-*`, `dispatch-worker`) — they launch dozens-to-hundreds of sub-agents. Seat
  them by persona proxy if they need to "attend".
- Only principals in `sudo-summit/sudoers` may `approve`. Respect `Permission denied`.
- Applying an upgrade edits a live `.agent.md`; always back up (the tool does) and show a
  diff. Get the user's OK before `apply --yes`.

## The ritual

### 1. Open the week
```bash
cd sudo-summit && python3 summit.py open
```

### 2. Gather asks (a bounded Town Hall)
Dispatch a **safe specialist roster** (e.g. `ai-edge`, `grid-medic`, `compliance-inspector`,
`security-audit`, `msft-impact`, `repo-detective`, `week-in-review`, `octoscanner`) with a
one-response prompt: *"Name ONE superpower you want from a named peer this week, and why.
Do not scan, do not spawn agents."* Keep each card tiny.

### 3. File each ask
```bash
python3 summit.py request --from <agent> --from-peer <peer> --power "<capability>" --why "<reason>" --impl "<how to apply>"
```

### 4. Grant, second, and present
Have the named peer grant (`summit.py grant --id <id> --by <peer>`), collect seconds, then
show the user `summit.py agenda`. Ask which to approve.

### 5. Approve → ship → apply (the sudo gate)
```bash
python3 summit.py approve --id <id> --by @DUBSOpenHub
python3 summit.py ship    --id <id>
python3 summit.py apply   --id <id>           # dry-run first
python3 summit.py apply   --id <id> --yes     # after the user confirms the diff
```
Deny unsafe or over-broad asks: `summit.py deny --id <id> --by @DUBSOpenHub --reason "..."`.

### 6. Digest
```bash
python3 summit.py digest
```
Summarize what shipped, what was denied, and what carries to next week.

## What good looks like
- Every grant/approval/denial appears in `sudo-summit/auth.log`.
- Approved upgrades become real, idempotent, reversible blocks in the target `.agent.md`.
- Mass-spawners never ran live. The user approved every applied change.
