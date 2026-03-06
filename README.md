# Copilot CLI Skills

A collection of skills for [GitHub Copilot CLI](https://docs.github.com/copilot/concepts/agents/about-copilot-cli) that extend the agent with specialized workflows.

## Skills

| Skill | Description |
|-------|-------------|
| [cli-mastery](cli-mastery/) | Interactive training for the GitHub Copilot CLI. Guided lessons, quizzes, scenario challenges, and a full reference c... |
| [dark-factory](dark-factory/) | 🏭 Dark Factory — agentic build system with sealed-envelope testing. Orchestrates 6 specialist agents through a c... |
| [dispatch](dispatch/) | Cross-terminal multi-agent orchestration. Splits complex tasks into parallel work units dispatched to independent Cop... |
| [first-agent](first-agent/) | 🎓 First Agent — live training skill that guides non-developers from zero to building their first AI agent in thr... |
| [havoc-hackathon](havoc-hackathon/) | 🏟️ Havoc Hackathon — a multi-model orchestration skill that turns your terminal into a competitive arena. Disp... |
| [m365-easy-button](m365-easy-button/) | Translate Google Workspace habits into Microsoft 365 steps, app mappings, troubleshooting, and power-user guidance. |
| [m365-expert](m365-expert/) | — |
| [pitch-master](pitch-master/) | 🎤 Pitch Master — transforms ANY concept, repo README, or about section into a world-class Y Combinator / TechSta... |
| [stampede](stampede/) | Cross-terminal multi-agent orchestration. Splits complex tasks into parallel work units dispatched to independent Cop... |

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
