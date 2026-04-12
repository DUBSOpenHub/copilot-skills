---
name: agent-pulse
summary: Launch Agent Pulse real-time Copilot CLI dashboard
---

# Agent Pulse Skill

When the user asks for **agent pulse**, **agent dashboard**, or **show agent telemetry**:

1. Ensure setup is complete:
   - Run: `cd ~/.copilot/agent-pulse && chmod +x setup.sh && ./setup.sh`
2. Launch persistently:
   - Run: `cd ~/.copilot/agent-pulse && ./run-agent-pulse.sh`
   - Use async + detach so it keeps running.
3. If already running, report PID and keep existing instance alive.

## What it tracks

- Active Copilot CLI sessions
- Running agents (all task agent types)
- Total sub-agents spawned
- Daily/weekly/monthly/all-time usage
- Real-time activity timeline + event stream

## Data location

- SQLite/history: `~/.copilot/agent-pulse/agent_pulse.db`
