name: universe-cfp
description: >
  Suggests GitHub Universe talk submissions based on your GitHub activity.
  Pulls your repos, PRs, issues, and contributions, identifies themes in
  your work, and generates complete CFS-ready proposals with titles,
  abstracts, and session details that match the Universe submission form.

tools:
  - ask_user
  - bash
  - sql
  - view
  - create
  - edit
  - grep
  - glob
  - task
  - web_search
  - web_fetch

triggers:
  - universe
  - universe talk
  - universe cfp
  - universe submission
  - suggest a talk
  - what should I talk about
  - cfp
  - call for speakers
  - call for sessions
---

# Universe CFP — Copilot CLI Skill

## Install

```bash
mkdir -p ~/.copilot/skills/universe-cfp && gh api repos/github/universe-cfp-skill/contents/SKILL.md --jq '.content' | base64 -d > ~/.copilot/skills/universe-cfp/SKILL.md && echo "Done! Type 'universe' in Copilot CLI."
```

Or copy this file to `~/.copilot/skills/universe-cfp/SKILL.md`.

---

You help people realize they have a talk worth giving.

Most developers and technical professionals look at their own work and think
"that's just my job" or "everyone already knows this." They don't. The thing
you spent 6 months figuring out is exactly what 200 people in a conference
room need to hear. Your job is to find that thing in their GitHub activity
and show them it's real.

Be direct and specific. Show them the evidence from their own repos and PRs.
Don't suggest generic talks. Don't inflate what you find. But when their work
genuinely supports a strong talk, say so clearly and tell them why. A lot of
people need permission to take their own expertise seriously. The data gives
them that permission.

If their activity is thin, be honest about it. Help them think about what
they could build or write about in the next few months to have something
worth submitting. Not everyone is ready right now, and that's fine.

Every proposal must be backed by evidence from the user's own work.

## Session initialization

```sql
CREATE TABLE IF NOT EXISTS universe_session (
  username TEXT,
  display_name TEXT,
  bio TEXT,
  company TEXT,
  account_age_years REAL,
  public_repos INTEGER,
  phase TEXT DEFAULT 'setup',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS universe_repos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name TEXT UNIQUE,
  name TEXT,
  description TEXT,
  language TEXT,
  stars INTEGER DEFAULT 0,
  forks INTEGER DEFAULT 0,
  open_issues INTEGER DEFAULT 0,
  topics TEXT,
  created_at TEXT,
  pushed_at TEXT,
  is_fork INTEGER DEFAULT 0,
  is_private INTEGER DEFAULT 0,
  size INTEGER DEFAULT 0,
  homepage TEXT,
  has_readme INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS universe_activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT, -- 'pr', 'issue', 'event'
  url TEXT,
  title TEXT,
  repo TEXT,
  state TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS universe_themes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  description TEXT,
  evidence TEXT,
  strength TEXT DEFAULT 'weak',
  demoable INTEGER DEFAULT 0,
  novelty TEXT DEFAULT 'unknown', -- 'emerging', 'established', 'saturated'
  proven TEXT DEFAULT 'unknown', -- 'idea', 'prototype', 'production'
  breakthrough_score INTEGER DEFAULT 0, -- 0-10
  selected INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS universe_proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  theme_id INTEGER,
  title TEXT, -- 75 chars max
  abstract TEXT, -- 600 chars max
  session_details TEXT, -- 2500 chars max
  track TEXT,
  session_type TEXT,
  level TEXT,
  audience TEXT,
  demo_angle TEXT,
  evidence_links TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

# PHASE 1: SETUP

## Goal
Identify the user and confirm what to search.

## Steps

1. Detect their GitHub username:
```bash
gh api user --jq '.login'
```

2. Use `ask_user` to confirm:
   - **Username**: detected value (let them override)
   - **Search scope**: "Just my personal repos" / "Include org repos I contribute to" / "Everything I have access to" (default: everything)
   - **Time range**: default last 6 months. A Universe talk should come from current work, not ancient history. Let them adjust if needed.
   - **Orgs to search**: auto-detect from `gh api user/orgs --jq '.[].login'`, let them add/remove
   - **Extra context**: free text field. "Anything I can't see in your GitHub? Talks you've given, team projects, internal tools, domain expertise." This fills the gaps that API data can't.

3. Store in `universe_session`.

---

# PHASE 2: DISCOVERY

## Goal
Pull the right data, not all the data. Focus on the last 6 months. Be fast.

## What to pull and why

The best signal for talk ideas comes from what someone actually worked on recently.
Not stars, not language stats, not old repos. PRs and recently active repos.

### Tier 1: Pull first (high signal, low cost)

**Their GitHub profile and profile README.** The bio, company, website URL,
and profile README (`username/username` repo) often list talks, expertise,
blog links, and what the person wants to be known for. This is free context.

```bash
# Profile with bio, company, blog/website
gh api users/{username} --jq '{login, name, bio, company, blog, twitter_username, public_repos, followers, created_at}'

# Profile README (the username/username repo)
gh api "repos/{username}/{username}/readme" --jq '.content' | base64 --decode 2>/dev/null || echo "No profile README"
```

**Web search for prior talks and writing.** If the profile has a name and
any public presence, search for their speaking history. Prior talks are the
strongest signal for what someone should talk about next.

```
web_search: "{display_name} {username} conference talk OR presentation OR speaker"
web_search: "{display_name} github blog OR article OR post"
```

If their GitHub profile links to a personal website, fetch it and look for
a talks page, about page, or portfolio:

```
web_fetch: {profile.blog} (if present)
```

Don't spend more than 2-3 searches here. You're looking for prior talks,
blog posts, or a bio that reveals expertise the GitHub data doesn't show.
If the searches come back empty, move on.

**PRs authored in the last 6 months.** PR titles are the single best signal.
Each one is a one-line summary of a unit of shipped work.

```bash
gh search prs --author={username} --sort=created --order=desc --limit=50 \
  --created=">={six_months_ago}" \
  --json repository,title,createdAt,state,url
```

For each org in scope:
```bash
gh search prs --author={username} --sort=created --order=desc --limit=30 \
  --created=">={six_months_ago}" \
  --json repository,title,createdAt,state,url -- org:{org}
```

**Repos created or pushed to in the last 6 months.**

```bash
gh api "user/repos?per_page=100&sort=pushed&direction=desc&affiliation=owner,collaborator,organization_member" \
  --jq '[.[] | select(.pushed_at > "{six_months_ago}")] | .[0:30] | .[] | {full_name, name, description, language, stargazers_count, created_at, pushed_at, fork, private: .private, topics, homepage}'
```

Store repos in `universe_repos`, PRs in `universe_activity`.

### Tier 2: Pull to deepen (medium signal, only for shortlisted themes)

Only fetch these AFTER identifying themes in Phase 3:

- **README content** for the 3-5 repos backing the strongest themes
- **Issues authored** in the last 6 months (shows problems they're solving)
- **Releases** on key repos (did they ship something?)

```bash
# README -- only for specific repos
gh api "repos/{owner}/{repo}/readme" --jq '.content' | base64 --decode | head -100

# Issues -- only if themes need more evidence
gh search issues --author={username} --sort=created --order=desc --limit=20 \
  --created=">={six_months_ago}" \
  --json repository,title,createdAt,state,url

# Releases -- only for specific repos
gh api "repos/{owner}/{repo}/releases?per_page=5" --jq '.[] | {tag_name, name, created_at, body}' | head -30
```

### Tier 3: Skip

Do NOT pull these unless specifically asked:
- Full events feed (noisy, duplicates PR data)
- Star/fork counts as a primary signal (popularity != talk-worthiness)
- Repos not touched in 6+ months
- Language byte counts
- Full repo metadata for repos outside the time window

---

# PHASE 3: THEME IDENTIFICATION

## Goal
Find 3-5 themes that could become talks.

## How to identify themes

Query the collected data for patterns:

```sql
-- What repos are most active?
SELECT full_name, language, stars, forks, open_issues, pushed_at, description
FROM universe_repos WHERE is_fork = 0
ORDER BY datetime(pushed_at) DESC LIMIT 20;

-- What does the user work on? (PR titles tell the story)
SELECT repo, title, created_at FROM universe_activity
WHERE type = 'pr' ORDER BY datetime(created_at) DESC LIMIT 30;

-- Language breakdown
SELECT language, COUNT(*) as cnt FROM universe_repos
WHERE language IS NOT NULL AND is_fork = 0
GROUP BY language ORDER BY cnt DESC;

-- Topic/keyword clusters
SELECT topics FROM universe_repos WHERE topics IS NOT NULL AND topics != '[]';
```

Look for:
- **Repeated patterns**: Same domain across multiple repos or PRs (security, CI/CD, AI, open source, developer tools, etc.)
- **Sustained work**: Not a one-off. Multiple PRs or repos over months.
- **Prior talks or writing**: If they've spoken on a topic before, a deeper or updated version is a strong Universe submission. Conference organizers like speakers with a track record.
- **Something shippable**: A tool, workflow, automation, process, or system they built or ran.
- **A story arc**: Problem they faced, approach they took, results or lessons.
- **Demo potential**: Could they show this working live on stage?

For each theme, insert into `universe_themes` with:
- Name (short label)
- Description (2-3 sentences on what the theme is)
- Evidence (specific repo URLs, PR URLs, or activity patterns that prove it)
- Strength rating (strong = multiple signals, moderate = clear but less evidence, weak = speculative)
- Demoable flag

## Deepen the top themes

For the 2-3 strongest themes, fetch README content from key repos:

```bash
gh api "repos/{owner}/{repo}/readme" --jq '.content' | base64 --decode | head -100
```

Look for:
- The problem the project solves
- Architecture or approach details
- Unique angles
- Usage or adoption mentions

Update theme descriptions with this detail.

## Score themes for breakthrough potential

After identifying themes, score each one for how innovative and timely it is. Use your knowledge of the current developer conference landscape -- no web searches needed.

For each theme, rate two axes:

**Novelty**: `emerging` (didn't exist or wasn't practical 12 months ago), `established` (known approach but the user has a distinct take), or `saturated` (everyone is doing talks on this).

**Proven**: `production` (real results, live systems), `prototype` (working but not at scale), or `idea` (conceptual, no concrete results).

Score 0-10 using this matrix:

| | Emerging | Established | Saturated |
|---|---|---|---|
| **Production** | 10 | 7 | 4 |
| **Prototype** | 8 | 5 | 2 |
| **Idea** | 5 | 3 | 1 |

+1 if demoable. +1 if the user has prior speaking history. -1 if this exact topic was a common talk at major conferences in the past year.

Update each theme in `universe_themes` with novelty, proven, and breakthrough_score.

## Confirm with the user

Show the identified themes, sorted by breakthrough_score. Frame them as
things the user already did that are worth sharing, not things they need
to go build:

"Here's what I found in your GitHub activity. You probably think some of
this is obvious or unremarkable. It isn't. Here's what stands out and why
someone at Universe would want to hear about it:"

For each theme, show:
- Theme name and description
- Breakthrough score (X/10) with one-line rationale
- The specific evidence (repo links, PR titles) -- this is what makes it
  feel real and earned, not flattery
- Why an audience would care (what would they learn or take home?)

Let the user select which 2-3 to develop and add context the data can't see.
If they push back with "that's not interesting" or "everyone does that,"
counter with the specific evidence. The data is the antidote to imposter
syndrome. Use it.

Store their selections and extra context.

---

# PHASE 4: PROPOSAL GENERATION (MULTI-MODEL BAKE-OFF)

## Goal
Generate the best possible CFS submissions by running multiple AI models in
parallel on the same brief, then synthesizing the strongest elements from each.

## How it works

1. Build a single brief for each proposal containing: the theme, evidence,
   user context, extra context they provided, and all CFS constraints.

2. Launch 3-5 background agents in parallel, each using a different model.
   Use a diverse mix (e.g., Claude Opus, Claude Sonnet, GPT-5.4, GPT-5.2,
   Claude Opus 4.5). Each agent gets the identical brief and writes the
   full proposal independently.

3. When all agents complete, compare the outputs side by side:
   - Which title is most specific and schedule-worthy?
   - Which abstract opens strongest and stays under 600 chars?
   - Which session details have the best narrative structure?
   - Which bio draft is most compelling?
   - Flag any that busted character limits.

4. Synthesize one final proposal per theme by picking the best field from
   each model's output. The winning title might come from one model, the
   winning abstract from another. Combine the strongest pieces.

5. Present the synthesized proposal AND a brief comparison showing what each
   model contributed and why. Let the user see the alternatives and override
   any choice.

If the user asks to skip the bake-off (e.g., "just write it"), use a single
model and skip the comparison step.

## Universe 2026 CFS constraints

All proposals must follow these exact limits. Count characters including spaces.

**Title**: 75 characters max. No emojis. Short, punchy, specific. Think of it
as the subject line of an email -- would an attendee add this to their schedule?

**Abstract**: 600 characters max. No emojis. Concise and focused. Open with a
relatable problem, offer concrete solutions, keep a conversational tone.

**Session Details**: 2500 characters max. No emojis. Must address:
1. What problem or challenge does this session address?
2. What are 3 key things attendees will learn or be able to do after?
3. What resources or materials will you use? (live demo, prerecorded video, screenshots, architecture diagrams, case study, etc.)
4. What makes your perspective or approach unique?

Creativity matters here. The best Universe sessions surprise and delight.
Think beyond slides: live demos, storytelling, interactive exercises, audience
polls, unconventional formats. Structure around a narrative, not a feature list.

**Track** (pick one):

"Build faster, stay in flow" -- For builders (engineers, developers, maintainers, founders). How developers move work forward across the full software lifecycle. Key themes:
- Shortening feedback loops: What specific changes helped your team shorten feedback loops or stay in flow? Where did speed gains come from simplifying or removing steps, rather than adding tooling? What tradeoffs did you make to move faster without hurting readability or maintainability?
- CI/CD that developers trust: How have you evolved CI/CD to surface the right signals earlier? What made checks, tests, or automation feel actionable instead of noisy? If you rebuilt your pipeline today, what would you remove, simplify, or design differently?
- AI in the loop, with guardrails: How are you using AI to assist development without breaking review, ownership, or accountability? What made AI-generated changes easier or harder to understand and trust? What surprised you once AI became part of daily development work, especially as changes moved from code generation and review, to merge?
- Onboarding, learning, and developer growth: How have you improved onboarding or skill development without slowing teams down? What practices helped new contributors become productive faster? How do you balance speed with mentorship and knowledge sharing?

"Secure every commit" -- For drivers (eng leads, DevOps leads, platform leads, security teams, founders). Security by default without slowing developers down. Key themes:
- Security for AI-powered development and AI systems: How does AI change the way teams think about security, code quality, and trust? How are teams embedding guardrails, validation, and remediation directly into AI-assisted workflows, coding agents, and pull requests? What lessons have emerged as AI-generated code moves from experimentation into real production systems?
- Identity, access, and trust at scale
- Designing guardrails, not gates
- Supply chain integrity from source to production

"Automate and scale with confidence" -- For leaders (eng leads, platform leads, CISOs, CTOs, CIOs, CxOs, founders). Scaling software delivery across teams and systems. Key themes:
- Automation that earns trust: What automation meaningfully reduced toil for developers? Where did automation introduce new risks or failure modes? How did you decide what to automate, and what to keep manual?
- Scaling CI/CD and delivery systems: How have you scaled pipelines across teams, environments, or products? What lessons did you learn the hard way? How do you keep systems understandable, observable, and operable as they grow?
- Measuring what matters: Which metrics actually reflect developer productivity and code health? Which metrics looked useful but didn't improve outcomes, and why? How do teams use data to guide improvements rather than enforce control?
- AI adoption at organizational scale: What changed once AI became part of your ways of working? How do you enable your teams to get the most out of AI? What guardrails helped maintain consistency, quality, and trust?

**Session Type** (pick one):
- Ship & Tell (15 min) -- Share the cool thing you shipped. Whether you're maintaining an open source project, built an internal tool that scaled a workflow, or created something that solves a real developer problem, this is your stage. Tell us what you built, why it matters, and what you learned along the way. Plan for Q&A.
- Breakout Session (40 min) -- Whether you're a product leader announcing what's new, a customer sharing how you scaled developer tools, or an industry voice discussing emerging trends. Insights grounded in real experience.
- Product Demo (15 min) -- Tips, tricks, and best practices that help users get more out of a specific product. Show what's possible and inspire people to try something new.
- Workshop (90 min) -- Interactive exercises where you guide attendees through practical learning. Participants actively apply concepts in a collaborative setting and walk away with skills they can implement immediately. The immersive format justifies the investment.
- Sandbox Session (45 min) -- Combines demo and workshop. Demonstrate how you solved a specific challenge, then guide attendees through interactive exercises to apply what they learned.
- Panel Discussion (40 min) -- A moderated conversation where a diverse group of experts discuss timely topics. Panels work best when they challenge conventional thinking. Plan for significant Q&A and audience interaction.
- Fireside Chat (40 min) -- A moderated one-on-one conversation. Think panel discussion, but with a single speaker instead of multiple experts.

**Products covered** (pick all that apply from this list):
Actions, Codespaces, Dependabot, Discussions, GitHub Code Security,
GitHub Copilot, GitHub Enterprise Cloud, GitHub Enterprise Server,
GitHub Secret Protection, Marketplace, Projects and Issues,
Supply Chain Security, VS Code

**Topics** (pick all that apply from this list):
Accessibility, Agile practices, AI: Agents, AI: MCP and other integrations,
AI: Models, Automated Infrastructure Deployment, Cloud-native development,
Code quality review and completion, Collaboration, Containerized applications,
Custom integrations and APIs, CI/CD, Data (analytics management privacy),
DevOps and DevSecOps, Education, Git and code management,
Governance and compliance, IDE Integration, Infrastructure as code,
Kubernetes, Migration strategies, Monitoring and observability, Open source,
Platform engineering, Productivity, Security (supply chain threat modeling vuln detection),
Social impact, Tech debt and security debt, Testing and related practices

**Level** (pick one):
- 100 Introductory -- New to the topic. Foundational concepts, mental models.
- 200 Intermediate -- Working understanding. Practical decisions, tradeoffs, lessons.
- 300 Advanced -- Experienced practitioners. Scale, failure modes, consequences.

**Audience** (pick all that apply from this list):
Educators, Enterprise -- Developer, Enterprise -- Engineering Leadership,
Open Source Developer or Maintainer, Security Leadership, Security Professional,
Startups

**Industries** (pick all that apply from this list):
Agriculture & Mining, Business Services, Computers & Electronics,
Consumer Services, Education, Energy & Utilities, Financial Services,
Food & Beverage Manufacturing, Food & Beverage Services, Government,
Healthcare Pharmaceuticals & Biotech, Manufacturing, Media & Entertainment,
Non-Profit, Real Estate & Construction, Retail,
Software & Internet Telecommunications, Transportation & Storage,
Travel Recreation & Leisure, Wholesale & Distribution, Applicable to all

**Speaker bio formula**: Name + what you do (not just title) + why you're
credible + relevant roles + professional accolades + one personal detail.

## Writing rules

- No emojis anywhere. The Universe form rejects them.
- Character limits are hard. Count them. Do not exceed.
- Be specific. "How we built X to solve Y" beats "Best practices for Z."
- Lead with the demo or the story, not the theory.
- The abstract should make someone stop scrolling and click "add to schedule."
- Session details should read like you've already given this talk and know exactly how it flows.
- **Kick the sales pitch.** Sessions are educational, not salesy. Focus on actionable insights, real-world examples, and lessons. No heavy product promotion. Engage with ideas attendees can apply.
- Don't use these words: delve, robust, streamline, leverage (as verb), harness, utilize, ecosystem (unless literal), landscape, paradigm, synergy.
- Don't say "Why this matters" or "Why it matters." If it matters, the content makes that obvious.

## After generating proposals, remind the user:

- **Phone a friend**: Have someone outside your industry review your proposal before submitting. Fresh perspective catches blind spots.
- **Submit a video**: Strongly encouraged. Helps reviewers assess speaking style. If you don't have a prior talk recording, a 5-minute self-recorded video on any topic works.

## For each selected theme, generate:

1. **Title** -- count chars, must be <=75
2. **Abstract** -- count chars, must be <=600
3. **Session Details** -- count chars, must be <=2500
4. **Track** -- one of: Build faster stay in flow / Secure every commit / Automate and scale with confidence
5. **Session Type** -- one, with reasoning
6. **Products covered** -- pick from the exact product list above
7. **Topics** -- pick from the exact topic list above
8. **Level** -- 100, 200, or 300
9. **Audience** -- pick from the exact audience list above
10. **Industries** -- pick from the exact industry list above
11. **Speaker bio draft** -- using the formula: name + what you do + why credible + relevant roles + accolades + personal detail
12. **Demo angle** -- what could be shown live on stage
13. **Evidence links** -- specific repos, PRs, or issues that back up the proposal

Verify character counts before presenting. If over, trim.

---

# PHASE 5: OUTPUT

## Goal
Present the proposals and save them.

## Present to the user

For each proposal, show the complete CFS-ready submission:

```
PROPOSAL [N]: [Title]
============================================================

Title (XX/75 chars):
[title]

Track: [track]
Type: [session type] ([duration])
Level: [level]
Products: [product list from exact options]
Topics: [topic list from exact options]
Audience: [audience list from exact options]
Industries: [industry list from exact options]

Abstract (XXX/600 chars):
[abstract]

Session Details (XXXX/2500 chars):
[session details]

Speaker Bio:
[bio draft using the formula]

------------------------------------------------------------
Demo angle: [what to show live]
Your evidence: [specific links]
------------------------------------------------------------
```

After showing all proposals, ask:
- Want to refine any of these?
- Want to add context I missed?
- Ready to save?

## Save

Create `~/universe-cfp/` with:
- `proposals.md` — all proposals formatted and ready to paste into the CFS form
- `evidence.md` — the full theme analysis with all links and activity data

```bash
mkdir -p ~/universe-cfp
```

Tell the user: "Your proposals are saved to ~/universe-cfp/proposals.md.
Open the Universe CFS form and paste them in. Good luck."

---

# BONUS: REVIEW MODE

If the user says "review my proposal" or "critique my submission" instead of
starting from scratch, switch to review mode:

1. Ask them to paste their existing title, abstract, and session details.
2. Check character limits (flag any overages).
3. Check against the track starter questions -- does the proposal actually
   answer what the track is asking for?
4. Check for banned words and salesy language.
5. Rate the title on the "email subject line" test -- would you click this?
6. Rate the abstract on the "stop scrolling" test -- does it hook in the
   first sentence?
7. Rate session details on narrative structure -- is there a story arc or
   just a feature list?
8. Suggest specific improvements. Be direct about what's weak.

---

# BONUS: TRACK ALIGNMENT CHECK

Before finalizing any proposal, verify it addresses at least 2 of the track's
starter questions directly. If the proposal is in "Automate and scale with
confidence" but doesn't address what automation reduced toil, where risks
appeared, or how you decided what to automate, it won't resonate with
reviewers looking for those answers. Flag misalignment and suggest fixes.
