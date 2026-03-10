# Copilot Instructions — Agent Company

## What is Agent Company?
A Copilot CLI skill that deploys 15 AI agents as a full Series A/B startup team. Give it any idea, and agents collaborate through a 5-phase pipeline to produce a complete startup operating package.

## File Map

| Path | Purpose |
|------|---------|
| SKILL.md | Main orchestrator — 5-phase pipeline |
| config.yml | Models, timeouts, phase definitions |
| catalog.yml | Skill metadata and registration |
| agents/ceo.md | Vision, strategy, board review synthesis |
| agents/cto.md | Architecture, tech stack |
| agents/cfo.md | Financial model, unit economics |
| agents/vp-product.md | PRD, roadmap, user stories |
| agents/vp-engineering.md | Sprint plan, team structure |
| agents/head-of-design.md | Design system, user flows |
| agents/vp-marketing.md | Marketing plan |
| agents/vp-sales.md | Sales playbook, pricing |
| agents/head-of-growth.md | Growth plan |
| agents/head-of-people.md | Hiring plan, org chart |
| agents/head-of-cs.md | Customer success playbook |
| agents/general-counsel.md | Legal checklist |
| agents/head-of-data.md | Metrics framework, dashboards |
| agents/head-of-devops.md | Infrastructure, monitoring |
| agents/head-of-security.md | Security plan |

## Non-negotiables

1. Agent prompts stay under 200 lines
2. Agents never read other agent prompts — only artifacts passed as input
3. Output file paths must match what SKILL.md expects
4. Gates are mandatory — never skip user review between phases
5. Config is source of truth — never hardcode models or timeouts

## Prohibited actions

- Don't merge agent prompts into a single file
- Don't add phases without updating config.yml
- Don't remove gates from the pipeline
