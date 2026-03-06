---
name: cli-mastery
description: >
  Interactive training for the GitHub Copilot CLI. Guided lessons, quizzes,
  scenario challenges, and a full reference covering slash commands, shortcuts,
  modes, agents, skills, MCP, and configuration. Say "cliexpert" to start.
metadata:
  version: 1.1.0
license: MIT
---

# Copilot CLI Mastery

**UTILITY SKILL** — interactive Copilot CLI trainer.
INVOKES: `ask_user`, `sql`, `view`
USE FOR: "cliexpert", "teach me the Copilot CLI", "quiz me on slash commands", "CLI cheat sheet", "copilot CLI final exam"
DO NOT USE FOR: general coding, non-CLI questions, IDE-only features

## Routing and Content

| Trigger | Action |
|---------|--------|
| "cliexpert", "teach me" | Read next `curriculum/module-N-*.md`, teach |
| "quiz me", "test me" | Read current module, 5+ questions via `ask_user` |
| "scenario", "challenge" | Read `curriculum/scenarios.md` |
| "reference" | Read relevant module, summarize |
| "final exam" | Read `curriculum/final-exam.md` |

Specific CLI questions get direct answers without curriculum.
Curriculum in `curriculum/` dir. Read on demand with `view`.

## Behavior

On first interaction, initialize progress tracking:
```sql
CREATE TABLE IF NOT EXISTS mastery_progress (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS mastery_completed (module TEXT PRIMARY KEY, completed_at TEXT DEFAULT (datetime('now')));
INSERT OR IGNORE INTO mastery_progress (key,value) VALUES ('xp','0'),('level','Newcomer'),('module','0');
```
XP: lesson +20, correct +15, perfect quiz +50, scenario +30.
Levels: 0=Newcomer 100=Apprentice 300=Navigator 600=Practitioner 1000=Specialist 1500=Expert 2200=Virtuoso 3000=Architect 4000=Grandmaster 5000=Wizard.

Rules: `ask_user` with `choices` for ALL quizzes/scenarios. Show XP after correct answers. One concept at a time; offer quiz or review after each lesson.
