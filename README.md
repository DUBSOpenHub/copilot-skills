# Copilot CLI Skills

A collection of skills for [GitHub Copilot CLI](https://docs.github.com/copilot/concepts/agents/about-copilot-cli) that extend the agent with specialized workflows.

## Skills

| Skill | Description |
|-------|-------------|
| [agent-company](agent-company/) | — |
| [cli-mastery](cli-mastery/) | 'Interactive training for the GitHub Copilot CLI. Guided lessons, quizzes, scenario challenges, and a full reference ... |
| [codeql-mastery](codeql-mastery/) | 🛡️ CodeQL Mastery — SOSS Fund expert on GitHub CodeQL and code scanning. Ask any question about CodeQL, code scanning... |
| [copilot-cli-quickstart](copilot-cli-quickstart/) | Use this skill when someone wants to learn GitHub Copilot CLI from scratch. Offers interactive step-by-step tutorials... |
| [dark-factory](dark-factory/) | 🏭 Dark Factory — agentic build system with sealed-envelope testing. Orchestrates 6 specialist agents through a checkp... |
| [dispatch](dispatch/) | Cross-terminal multi-agent orchestration. Splits complex tasks into parallel work units dispatched to independent Cop... |
| [first-agent](first-agent/) | 🎓 First Agent — live training skill that guides non-developers from zero to building their first AI agent in three se... |
| [gdoc-converter](gdoc-converter/) | Converts Google Docs, Slides, and Sheets to Microsoft Office formats (Word, PowerPoint, Excel). Paste a Google URL an... |
| [havoc-hackathon](havoc-hackathon/) | 🏟️ Havoc Hackathon — a multi-model orchestration skill that turns your terminal into a competitive arena. Dispatches ... |
| [m365-easy-button](m365-easy-button/) | Translate Google Workspace habits into Microsoft 365 steps, app mappings, troubleshooting, and power-user guidance. |
| [octofund](octofund/) | 🐙 OctoFund — data-driven funding allocator for underfunded open source projects. Takes a budget, scores critical proj... |
| [pitch-master](pitch-master/) | 🎤 Pitch Master — transforms ANY concept, repo README, or about section into a world-class Y Combinator / TechStars 60... |
| [slack-context](slack-context/) | Use when the user asks to "fetch context from Slack", "read this Slack thread", "get requirements from Slack", "extra... |
| [soss-skill-template](soss-skill-template/) | 🛡️ SOSS Fund Training — MODULE_TITLE. Interactive trainer with CTA tracking, security validation, and dashboard-ready... |
| [stampede](stampede/) | Cross-terminal multi-agent orchestration. Splits complex tasks into parallel work units dispatched to independent Cop... |
| [swarm](swarm/) | — |

## Install

### Install all skills

```bash
git clone https://github.com/DUBSOpenHub/copilot-skills.git /tmp/copilot-skills
cp -R /tmp/copilot-skills/*/ ~/.copilot/skills/
```

### Install a single skill

```bash
git clone --depth 1 https://github.com/DUBSOpenHub/copilot-skills.git /tmp/copilot-skills
cp -R /tmp/copilot-skills/pitch-master ~/.copilot/skills/
```

After installing, restart your Copilot CLI session (`/exit` then `copilot`) to pick up the new skills. Use `/skills` to verify they loaded.

## How skills work

Each skill is a folder containing a `SKILL.md` file with YAML frontmatter (name, description) and markdown prompt instructions. Copilot CLI loads skills from `~/.copilot/skills/` on startup.

## License

MIT
