# Copilot CLI Skills

A collection of skills for [GitHub Copilot CLI](https://docs.github.com/copilot/concepts/agents/about-copilot-cli) that extend the agent with specialized workflows.

## Skills

| Skill | Description |
|-------|-------------|
| [cli-mastery](cli-mastery/) | Interactive training for the GitHub Copilot CLI. Guided lessons, quizzes, scenario challenges, and a full reference. Say `cliexpert` to start. |
| [dark-factory](dark-factory/) | 🏭 Agentic build system with sealed-envelope testing. Orchestrates 6 specialist agents through a checkpoint-gated pipeline. Say `dark factory` to start. |
| [dispatch](dispatch/) | Cross-terminal multi-agent orchestration via tmux panes with filesystem IPC, dead worker recovery, and conflict-aware synthesis. |
| [first-agent](first-agent/) | 🎓 Live training skill that guides non-developers from zero to building their first AI agent in three sessions. Say `first-agent` to start. |
| [havoc-hackathon](havoc-hackathon/) | 🏟️ Multi-model tournament that dispatches up to 14 AI models in elimination heats with sealed judge panels. Say `run hackathon` to start. |
| [m365-easy-button](m365-easy-button/) | Translate Google Workspace habits into Microsoft 365 steps, app mappings, and troubleshooting. |
| [pitch-master](pitch-master/) | 🎤 Transforms any concept or repo into a world-class 60-second pitch. Say `pitch me` to start. |
| [stampede](stampede/) | Cross-terminal multi-agent orchestration with parallel task dispatch, dead agent recovery, and conflict-aware synthesis. |

## Install

### Install all skills

```bash
git clone https://github.com/DUBSOpenHub/copilot-skills.git /tmp/copilot-skills
cp -R /tmp/copilot-skills/*/ ~/.copilot/skills/
```

### Install a single skill

```bash
# Example: install pitch-master
git clone --depth 1 https://github.com/DUBSOpenHub/copilot-skills.git /tmp/copilot-skills
cp -R /tmp/copilot-skills/pitch-master ~/.copilot/skills/
```

After installing, restart your Copilot CLI session (`/exit` then `copilot`) to pick up the new skills. Use `/skills` to verify they loaded.

## How skills work

Each skill is a folder containing a `SKILL.md` file with YAML frontmatter (name, description) and markdown prompt instructions. Copilot CLI loads skills from `~/.copilot/skills/` on startup.

```
~/.copilot/skills/
├── dark-factory/
│   └── SKILL.md
├── pitch-master/
│   └── SKILL.md
└── ...
```

## License

MIT
