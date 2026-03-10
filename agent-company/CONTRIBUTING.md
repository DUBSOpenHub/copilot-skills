# Contributing to Headcount Zero

Thanks for your interest in improving Headcount Zero! Here's how to help.

## Quick Ways to Help

- 🐛 **Report a bug** — [Open an issue](https://github.com/DUBSOpenHub/headcount-zero/issues) with what you expected vs what happened
- 💡 **Suggest a feature** — New agent roles, output formats, or pipeline changes
- 🎨 **Improve a prompt** — Submit a PR to any `agents/*.md` file
- 📝 **Test it out** — Run it on a startup idea and share the results

## Making Changes

### Agent Prompts (`agents/*.md`)

Each agent follows this format:

```markdown
---
name: agent-id
description: One-line description
tools:
  - create
---

# Role
# Input
# Output
# Rules
```

**Rules when editing agents:**
1. Keep under 200 lines
2. Be specific about output format (file names, section headers)
3. Don't reference other agent prompts — agents only see artifacts passed to them
4. Test by running a full pipeline after your change

### SKILL.md (Orchestrator)

Changes here affect all phases. Be careful and test a full run.

### config.yml

Add new tunables here. Never hardcode values in SKILL.md or agent prompts.

## Pull Request Process

1. Fork the repo
2. Make your change on a feature branch
3. Test with at least one full pipeline run
4. Submit a PR with a clear description of what changed and why

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
