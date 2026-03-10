# AGENTS.md — Working Guide for AI Agents

This file tells any AI agent how to work on the Agent Company skill.

## Architecture

```
SKILL.md (Board of Directors — orchestrator)
    │
    ├── Phase 1: CEO
    ├── Phase 2: CTO + CFO + VP Product (parallel)
    ├── Phase 3: 6 department heads (parallel)
    ├── Phase 4: 5 operations agents (parallel)
    └── Phase 5: CEO (synthesis)
```

User reviews output at each gate before the next phase runs.

## File Ownership Map

| File/Dir | Owner | Change Rules |
|----------|-------|--------------|
| SKILL.md | Orchestrator | Changes affect all phases. Test a full run. |
| config.yml | Settings | Change tunables here, never hardcode in SKILL.md |
| catalog.yml | Metadata | Update version when agents change |
| agents/*.md | Individual agents | Change one at a time. Keep under 200 lines. |

## Agent Prompt Rules

- Frontmatter: name, description, tools
- Sections: Role, Input, Output, Rules
- Max 200 lines per agent
- Be specific about output format (file names, section headers)
- Never reference other agent prompts — agents only see their input artifacts

## Before You Change Anything

1. Read the agent file completely
2. Check which phase it runs in (see SKILL.md)
3. Verify input/output contracts match upstream/downstream agents
4. Make the smallest possible change

## Common Pitfalls

1. **Adding tools agents don't need** — agents only need `create` (and `view` for CEO). Don't add bash, grep, etc.
2. **Breaking output file paths** — SKILL.md expects exact paths like `engineering/architecture.md`. If you rename an output, update SKILL.md too.
3. **Bloating prompts** — the 200-line cap exists because longer prompts produce worse output. Cut, don't add.
4. **Cross-agent coupling** — agents must never reference each other. They only read artifacts passed to them.
