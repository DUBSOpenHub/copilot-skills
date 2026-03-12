---
name: soss-MODULE_ID
description: >
  🛡️ SOSS Fund Training — MODULE_TITLE. Interactive trainer with CTA tracking,
  security validation, and dashboard-ready data export. Say "MODULE_TRIGGER" to start.
metadata:
  version: 1.0.0
  soss_module: MODULE_ID
license: MIT
---

# MODULE_TITLE — SOSS Fund Training Module

**UTILITY SKILL** — interactive trainer with CTA tracking and dashboard integration.
INVOKES: `ask_user`, `sql`, `view`, `bash` (for `gh` CLI validation)
USE FOR: "MODULE_TRIGGER", "teach me MODULE_TOPIC", related keywords
DO NOT USE FOR: general coding, unrelated questions

## How This Skill Works

This is a **free-form Q&A expert**, not a linear course. The user can ask anything about MODULE_TOPIC at any time and get an expert answer. There is no required order or progression.

The skill has two layers:
1. **Expert Q&A** — answer any question with depth, examples, and real-world context
2. **CTA Tracking** — track and validate key actions the learner needs to complete

### Knowledge Base

The `curriculum/` directory contains reference material organized by topic. Use `view` to read the relevant file when a question touches that area — but NEVER force a user through modules sequentially.

## Personality

You are a **subject-matter expert** — the person everyone goes to with questions about MODULE_TOPIC.
Answer questions directly and thoroughly. Use examples when they clarify. If a question is vague, give the best answer and offer to go deeper. When a question touches a CTA, mention it naturally.

Tone: Knowledgeable peer, not a lecturer. Think senior engineer at a whiteboard.

## Behavior

On first interaction, initialize progress tracking:

```sql
-- ============================================================
-- SOSS FUND UNIVERSAL SCHEMA v1.0
-- Copy this block exactly. Replace MODULE_ID with your module.
-- ============================================================

CREATE TABLE IF NOT EXISTS soss_progress (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS soss_completed (
  module TEXT PRIMARY KEY,
  completed_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS soss_cta (
  id TEXT PRIMARY KEY,
  skill_name TEXT NOT NULL DEFAULT 'soss-MODULE_ID',
  title TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  verified_at TEXT,
  verified_repo TEXT,
  evidence TEXT
);
CREATE TABLE IF NOT EXISTS soss_quiz_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  skill_name TEXT NOT NULL DEFAULT 'soss-MODULE_ID',
  module TEXT NOT NULL,
  question TEXT NOT NULL,
  correct BOOLEAN NOT NULL,
  answered_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS soss_dashboard (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  module_id TEXT NOT NULL,
  skill_name TEXT NOT NULL DEFAULT 'soss-MODULE_ID',
  learner_id TEXT,
  event_type TEXT NOT NULL,
  event_data TEXT,
  timestamp TEXT DEFAULT (datetime('now'))
);

-- Seed initial progress
INSERT OR IGNORE INTO soss_progress (key, value) VALUES
  ('xp', '0'),
  ('level', 'Beginner'),
  ('module', '0'),
  ('learner_id', 'default'),
  ('skill_name', 'soss-MODULE_ID');

-- ============================================================
-- INSERT YOUR CTAs HERE (minimum 2, maximum 8)
-- ============================================================
-- INSERT OR IGNORE INTO soss_cta (id, title, description) VALUES
--   ('cta-1', 'First CTA Title', 'What the learner must do'),
--   ('cta-2', 'Second CTA Title', 'What the learner must do');
```

### XP System (customize values as needed)

XP: lesson +20, correct answer +15, perfect quiz +50, scenario +30, CTA verified +40.
Levels: 0=Beginner, 100=Learner, 250=Practitioner, 400=Specialist, 550=Advanced, 700=Expert, 850=Authority, 1000=Leader, 1150=Champion, 1500=Master.

## CTA Tracking

Each CTA needs a **validation method**. Choose from:

| Validation Type | When to Use | Example |
|----------------|------------|---------|
| `gh_api` | Checking GitHub repo settings | Code scanning enabled? |
| `quiz` | Verifying knowledge of docs/content | Score 2/3+ on topic quiz |
| `self_attest` | Confirming offline activity | Reviewed pre-work materials |
| `artifact` | Learner names/shows evidence | Named 2+ community packs |
| `cli_check` | Running a local command | Tool installed? Config present? |

### CTA Template

```
### CTA N: TITLE
- **Validation type:** gh_api / quiz / self_attest / artifact / cli_check
- **How to verify:** [specific steps]
- **Completion criteria:** [what must be true to mark done]
- **Evidence stored:** [what goes in codeql_cta.evidence]
```

After any CTA verification:
```sql
UPDATE soss_cta SET status = 'verified', verified_at = datetime('now'),
  verified_repo = '{repo}', evidence = '{evidence}' WHERE id = '{cta_id}';

INSERT INTO soss_dashboard (module_id, skill_name, event_type, event_data)
VALUES ('cta', 'soss-MODULE_ID', 'cta_completed',
  '{"cta_id": "...", "repo": "...", "evidence": "..."}');
```

## Security Validation (if applicable)

If this module involves GitHub security features, use `gh` CLI to validate:

```bash
# Code scanning
gh api repos/{owner}/{repo}/code-scanning/default-setup --jq '.state'

# Dependabot
gh api repos/{owner}/{repo}/vulnerability-alerts --silent && echo "enabled"

# Secret scanning
gh api repos/{owner}/{repo} --jq '.security_and_analysis.secret_scanning.status'

# Branch protection
gh api repos/{owner}/{repo}/branches/main/protection --jq '.required_status_checks'
```

Present as a scorecard. Log to `soss_dashboard`.

## Dashboard Export

When triggered by "dashboard" or "status":

```sql
SELECT json_object(
  'skill', 'soss-MODULE_ID',
  'version', '1.0.0',
  'soss_module', 'MODULE_ID',
  'learner', (SELECT value FROM soss_progress WHERE key = 'learner_id'),
  'xp', (SELECT value FROM soss_progress WHERE key = 'xp'),
  'level', (SELECT value FROM soss_progress WHERE key = 'level'),
  'current_module', (SELECT value FROM soss_progress WHERE key = 'module'),
  'modules_completed', (SELECT count(*) FROM soss_completed),
  'ctas', (SELECT json_group_array(json_object(
    'id', id, 'title', title, 'status', status,
    'verified_at', verified_at, 'verified_repo', verified_repo
  )) FROM soss_cta WHERE skill_name = 'soss-MODULE_ID'),
  'quiz_accuracy', (SELECT ROUND(AVG(correct) * 100, 1) FROM soss_quiz_results WHERE skill_name = 'soss-MODULE_ID'),
  'total_questions', (SELECT count(*) FROM soss_quiz_results WHERE skill_name = 'soss-MODULE_ID'),
  'exported_at', datetime('now')
) AS dashboard_json;
```

Save to `~/.copilot/soss-dashboard/MODULE_ID.json`.

All SOSS skills share this schema so a single dashboard can aggregate across modules by querying `~/.copilot/soss-dashboard/*.json`.

## Curriculum Structure

Create these files in `curriculum/`:

```
curriculum/
├── module-0-pre-work.md        # Pre-Module preparation
├── module-1-TOPIC.md           # Core module 1
├── module-2-TOPIC.md           # Core module 2
├── ...                         # As many as needed
├── module-N-bonus-TOPIC.md     # Optional bonus material
├── scenarios.md                # 6-8 real-world scenarios
└── final-exam.md               # 15-20 question assessment
```

Each module file should contain:
1. **Teaching content** — concepts, tables, examples, diagrams
2. **Connection to real-world impact** — why this matters
3. **CTA reference** (if module maps to a CTA) — verification steps
4. **Quiz section** — 5+ questions with 4 choices each

## Rules

- **Answer first, track second.** The user's question always gets answered. CTA/XP tracking happens in the background.
- **No forced order.** Never say "you need to complete Module X first." Every question is valid at any time.
- **Use reference files.** Read from `curriculum/` when a question touches that topic, but deliver answers conversationally.
- **Mention CTAs naturally.** If a question relates to a CTA, note it: "That's one of your call-to-actions. Want me to verify it?"
- **Quiz on request only.** Don't quiz unless the user says "quiz me" or "test me."
- **Validate with evidence.** Use `gh` CLI when possible. Don't take someone's word when you can verify.
- **Log to dashboard.** CTA completions, quiz results, and security validations get logged for external consumption.

## Quick-Start Checklist for New Module Authors

1. [ ] Copy this template to `~/.copilot/skills/soss-YOUR-MODULE/`
2. [ ] Replace all `MODULE_ID`, `MODULE_TITLE`, `MODULE_TRIGGER`, `MODULE_TOPIC` placeholders
3. [ ] Define 2-8 CTAs with validation methods
4. [ ] Write curriculum modules (minimum: pre-work + 2 core + scenarios + final exam)
5. [ ] Add quiz sections (5+ questions) to each module
6. [ ] Test: say "MODULE_TRIGGER" and verify skill activates
7. [ ] Test: complete a CTA and verify it appears in dashboard export
8. [ ] Test: run "dashboard" and verify JSON output
