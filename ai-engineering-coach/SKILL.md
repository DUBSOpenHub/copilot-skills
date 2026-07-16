---
name: ai-engineering-coach
description: >
  AI Engineering Coach - opens a private local dashboard that analyzes AI coding
  sessions, practice patterns, output, and context health. Say "AI engineering
  coach" to start.
tools:
  - bash
triggers:
  - ai engineering coach
  - ai engineer coach
  - open ai engineering coach
  - open my coding coach
  - show my ai coding dashboard
metadata:
  version: 1.0.0
  license: MIT
  source: https://github.com/microsoft/AI-Engineering-Coach
---

# AI Engineering Coach

Open Microsoft's AI Engineer Coach as a canvas in the GitHub Copilot app. The
dashboard reads local AI session logs without modifying them, and its analysis
runs on this machine.

## Canonical installation

- Repository: `~/copilot-workspace/AI-Engineering-Coach`
- Launcher: `~/.copilot/skills/ai-engineering-coach/open.sh`
- Copilot canvas: `.github/extensions/ai-engineer-coach`

Do not clone another copy or substitute a similarly named project.

## On trigger

When the user asks to open or run AI Engineering Coach:

1. Run exactly:

   ```bash
   ~/.copilot/skills/ai-engineering-coach/open.sh
   ```

2. Confirm briefly that the project opened in the GitHub Copilot app.
3. If the app does not select it automatically, tell the user to open the
   **AI Engineer Coach** canvas.

Do not reproduce the dashboard in chat, upload session data, or start a remote
service.

## Status

When the user asks whether the coach is installed or ready, run:

```bash
~/.copilot/skills/ai-engineering-coach/open.sh --check
```

Report any failed check plainly.

## Update

Only when the user explicitly asks to update the coach, run:

```bash
~/.copilot/skills/ai-engineering-coach/open.sh --update
```

The updater refuses to pull over local repository changes. Never discard,
reset, or overwrite those changes.

## Failures

- If the canonical repository is missing, stop and report that it must be
  restored from `https://github.com/microsoft/AI-Engineering-Coach`.
- If GitHub Copilot is missing, stop and report that the desktop app is
  required for the canvas.
- If installation or build commands fail, surface the command output; do not
  claim the dashboard is ready.

