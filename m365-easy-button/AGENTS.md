# AGENTS.md — Working Guide for AI Agents

This file tells any AI agent how to work effectively on the M365 Easy Button codebase.

---

## Architecture

M365 Easy Button is a **single-file Copilot CLI skill**. The entire skill lives in `SKILL.md`. There are no sub-agents, no pipeline, no orchestration — just one comprehensive prompt that turns the Copilot CLI into a Google-to-Microsoft translator.

```
SKILL.md (the entire skill)
  ├── Persona & tone rules
  ├── Answer format (Bridge → Steps → Next → Gotcha → Power Move → If This Fails)
  ├── App Router (30+ product mappings)
  ├── Mental Model Translations
  ├── Behavior Mapping tables (9 product areas)
  ├── Keyboard shortcut comparisons
  ├── Workflow translations (9 end-to-end tasks)
  ├── First Week Survival Guide
  ├── Power User Tips
  ├── AI Features comparison
  ├── Troubleshooting patterns (13)
  ├── CLI engagement elements (achievements, confidence meter, fun facts)
  └── Trigger phrases & activation
```

---

## File Ownership Map

| File | Purpose | Change Rules |
|------|---------|-------------|
| `SKILL.md` | The entire skill | Most critical file. Every edit affects runtime behavior. |
| `README.md` | Repo documentation | Keep in sync with SKILL.md coverage claims. |
| `SECURITY.md` | Vulnerability reporting | Update version table when releasing. |
| `CONTRIBUTING.md` | Contributor guide | Update if answer format or persona rules change. |
| `CHANGELOG.md` | Release history | Add entry for every meaningful SKILL.md change. |
| `.github/copilot-instructions.md` | Repo-specific Copilot rules | Rarely changes. |
| `.github/workflows/validate.yml` | CI validation | Update section checks if SKILL.md headings change. |

---

## Key Rules When Editing SKILL.md

1. **Never break the translator persona.** The skill is a patient coworker, not tech support. Never say "it's easy" or "just do X."
2. **Every mapping starts from Google.** Even if the user didn't mention Google, the Bridge section connects to it.
3. **Be specific.** Menu paths, app names (web vs desktop), keyboard shortcuts. Vague advice helps no one.
4. **Stay neutral.** Never editorialize about Google vs Microsoft. Both have strengths.
5. **Stay in scope.** Day-to-day M365 apps only. No Azure/Intune/Entra admin deep-dives. Refer to IT for those.
6. **Keep tables consistent.** Google concept | Microsoft equivalent | Key difference.
7. **Test after editing.** Install locally, restart the CLI session, and query with real questions.

---

## How to Test Changes

```bash
# Copy your modified SKILL.md to the skill location
cp SKILL.md ~/.copilot/skills/m365-easy-button/SKILL.md

# Restart your Copilot CLI session, then test with:
# "easy button"
# "how do I share a file in OneDrive?"
# "what's the Microsoft version of Google Apps Script?"
# "I can't find my files in Teams"
```

Verify the skill responds with the Bridge → Steps → Next Step → Gotcha format and that the persona feels right.

---

## Common Pitfalls

- **Don't add Azure/Intune/Entra content.** That's out of scope. The skill explicitly refers users to IT for admin infrastructure.
- **Don't remove the Mental Model section.** It's the most innovative part — it explains *why* Microsoft feels different, not just *what* is different.
- **Don't hardcode dates or version numbers in SKILL.md.** The skill uses `web_search` to fetch current info.
- **Don't duplicate product mappings.** Check the App Router table before adding a new one to a behavior mapping section.
- **Menu paths change frequently.** When updating steps, note whether they apply to web, desktop, or both.
