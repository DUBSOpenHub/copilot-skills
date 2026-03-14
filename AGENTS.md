# Agents

## Overview

This repo is the canonical collection of Copilot CLI skills published by DUBSOpenHub. Each subfolder is a self-contained skill installed by copying it to `~/.copilot/skills/`.

## Available Agents

### cli-mastery
- **Purpose**: Interactive training for the GitHub Copilot CLI — guided lessons, quizzes, scenario challenges, and a full reference covering slash commands, shortcuts, modes, agents, skills, MCP, and configuration
- **Usage**: Say `cliexpert` in Copilot CLI
- **Model**: Default Copilot model

### codeql-mastery
- **Purpose**: SOSS Fund expert on GitHub CodeQL and code scanning; answers questions about QL queries, vulnerability detection, community packs, and database internals
- **Usage**: Say `codeql` in Copilot CLI
- **Model**: Default Copilot model

### dark-factory
- **Purpose**: Agentic build system with sealed-envelope testing; orchestrates 6 specialist agents through a checkpoint-gated pipeline
- **Usage**: Say `dark factory` (full build) or `dark factory express` (quick tasks)
- **Model**: Default Copilot model

### dispatch
- **Purpose**: Cross-terminal multi-agent orchestration via tmux panes with filesystem IPC, atomic operations, dead-worker recovery, and conflict-aware synthesis
- **Usage**: Say `dispatch` in Copilot CLI
- **Model**: Default Copilot model

### first-agent
- **Purpose**: Live training skill guiding non-developers from zero to building their first AI agent in three sessions (Run It → Remix It → Build It)
- **Usage**: Say `first-agent` in Copilot CLI
- **Model**: Default Copilot model

### gdoc-converter
- **Purpose**: Converts Google Docs, Slides, and Sheets to Microsoft Office formats (Word, PowerPoint, Excel)
- **Usage**: Say `convert` with a Google Doc link
- **Model**: Default Copilot model

### havoc-hackathon
- **Purpose**: Multi-model tournament arena; dispatches up to 18 AI models in elimination heats, scores with sealed judge panels, and synthesizes collective-intelligence output
- **Usage**: Say `run hackathon` in Copilot CLI
- **Model**: Up to 18 models in parallel

### m365-easy-button
- **Purpose**: Translates Google Workspace habits into Microsoft 365 steps, app mappings, troubleshooting, and power-user guidance
- **Usage**: Invoke skill or ask M365-related questions
- **Model**: Default Copilot model

### pitch-master
- **Purpose**: Transforms any concept, repo README, or about section into a world-class 60-second YC/TechStars pitch
- **Usage**: Say `pitch me` in Copilot CLI
- **Model**: Default Copilot model

### soss-skill-template
- **Purpose**: SOSS Fund Training interactive trainer with CTA tracking, security validation, and dashboard-ready data export
- **Usage**: Follow skill-specific trigger phrase
- **Model**: Default Copilot model

### stampede
- **Purpose**: Cross-terminal multi-agent orchestration via tmux panes with filesystem IPC, atomic operations, dead-agent recovery, and conflict-aware synthesis
- **Usage**: Say `stampede` in Copilot CLI
- **Model**: Default Copilot model

### agent-company / swarm
- **Purpose**: Experimental multi-agent collaboration skills (in development)
- **Usage**: Refer to each skill's SKILL.md for current trigger
- **Model**: Default Copilot model

## Configuration

Install all skills at once:
```bash
git clone https://github.com/DUBSOpenHub/copilot-skills.git /tmp/copilot-skills
cp -R /tmp/copilot-skills/*/ ~/.copilot/skills/
```

Or install a single skill:
```bash
cp -R /tmp/copilot-skills/pitch-master ~/.copilot/skills/
```

Restart your Copilot CLI session (`/exit` then `copilot`) after installing. Use `/skills` to verify.
