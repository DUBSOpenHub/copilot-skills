# Copilot CLI Skills

A collection of skills for [GitHub Copilot CLI](https://docs.github.com/copilot/concepts/agents/about-copilot-cli) that extend the agent with specialized workflows.

## Skills

| Skill | Description |
|-------|-------------|
| [agent-company](agent-company/) | — |
| [cli-mastery](cli-mastery/) | Interactive training for the GitHub Copilot CLI. Guided lessons, quizzes, scenario challenges, and a full reference c... |
| [codeql-mastery](codeql-mastery/) | 🛡️ CodeQL Mastery — SOSS Fund expert on GitHub CodeQL and code scanning. Ask any question about CodeQL, code scanning... |
| [copilot-cli-quickstart](copilot-cli-quickstart/) | Use this skill when someone wants to learn GitHub Copilot CLI from scratch. Offers interactive step-by-step tutorials... |
| [copilot-first-light](copilot-first-light/) | ✨ First Light — a warm, friendly guide that helps anyone build their first AI agent in about 10 minutes. No coding ex... |
| [dark-factory](dark-factory/) | 🏭 Dark Factory — agentic build system with sealed-envelope testing. Orchestrates 6 specialist agents through a checkp... |
| [design-auditor](design-auditor/) | 🔍 Design Auditor — paste a URL, get 5 ranked fixes to improve conversions. Analyzes layout, performance, accessibilit... |
| [dispatch](dispatch/) | Cross-terminal multi-agent orchestration. Splits complex tasks into parallel work units dispatched to independent Cop... |
| [evo-forge](evo-forge/) | 🧬 Evo Forge — breeds better agents through evolutionary selection. Mutates agent prompts, tournaments them, selects s... |
| [first-agent](first-agent/) | 🎓 First Agent — live training skill that guides non-developers from zero to building their first AI agent in three se... |
| [gdoc-converter](gdoc-converter/) | Converts Google Docs, Slides, and Sheets to Microsoft Office formats (Word, PowerPoint, Excel). Paste a Google URL an... |
| [havoc-hackathon](havoc-hackathon/) | 🏟️ Havoc Hackathon — a multi-model orchestration skill that turns your terminal into a competitive arena. Dispatches ... |
| [headcount-zero](headcount-zero/) | — |
| [hive1k](hive1k/) | 🐝 Hive1K — recursive multi-model swarm orchestrator. Launches 250-1,000+ AI agents across 16 models with Division Com... |
| [m365-easy-button](m365-easy-button/) | Translate Google Workspace habits into Microsoft 365 steps, app mappings, troubleshooting, and power-user guidance. |
| [octofund](octofund/) | 🐙 OctoFund — data-driven funding allocator for underfunded open source projects. Takes a budget, scores critical proj... |
| [pitch-master](pitch-master/) | 🎤 Pitch Master — transforms ANY concept, repo README, or about section into a world-class Y Combinator / TechStars 60... |
| [reflect](reflect/) | Helps any Hubber write their FY26 performance reflection. Pulls GitHub activity for the review period, reads the org ... |
| [sidecar](sidecar/) | — |
| [slack-context](slack-context/) | Use when the user asks to "fetch context from Slack", "read this Slack thread", "get requirements from Slack", "extra... |
| [soss-skill-template](soss-skill-template/) | 🛡️ SOSS Fund Training — MODULE_TITLE. Interactive trainer with CTA tracking, security validation, and dashboard-ready... |
| [stampede](stampede/) | Cross-terminal multi-agent orchestration. Splits complex tasks into parallel work units dispatched to independent CLI... |
| [swarm](swarm/) | — |
| [swarm-command](swarm-command/) | 🐝 Swarm Command — multi-model consensus swarm orchestrator. Launches 50-250+ AI agents across 15 models with hierarch... |
| [weekly-ai-report](weekly-ai-report/) | 📡 Weekly AI Report — researches frontier model releases from the past week, stack-ranks new capabilities by power/imp... |

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
