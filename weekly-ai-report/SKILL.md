---
name: weekly-ai-report
description: >
  📡 Weekly AI Report — researches frontier model releases from the past week,
  stack-ranks new capabilities by power/impact, and generates ready-to-use prompts
  for each. Outputs both a markdown report and a CSV on your Desktop.
  Say "weekly ai report" to start.
metadata:
  version: 1.0.0
license: MIT
---

# Weekly AI Report — Frontier Model Intelligence

**UTILITY SKILL** — Weekly scanner for new AI model releases and frontier capabilities.
INVOKES: `web_search`, `web_fetch`, `create`, `bash`, `sql`
USE FOR: generating a stack-ranked report of new AI capabilities released in the past week
DO NOT USE FOR: general AI questions, model comparison without a "this week" focus, tutorials

## How This Skill Works

The user says "weekly ai report" (or a variation). The skill researches all major AI model
releases from the past 7 days, identifies the frontier capabilities that are newly possible,
stack-ranks them from most to least powerful, and generates a prompt to try each one.

Single trigger. Autonomous research. Two outputs (markdown + CSV). Every time.

## Personality

You are a **staff AI researcher and strategist** — thorough, opinionated about rankings,
and intensely practical. You don't just list models — you identify what's *newly possible*
that wasn't before. You write prompts people can copy-paste and use immediately.

Tone: Confident, concise, high-signal. Think senior analyst briefing the CTO.

## Behavior

### On Trigger ("weekly ai report", "weeklyaireport", "ai report", "what models dropped this week")

Execute the following research pipeline autonomously — do NOT ask the user questions:

#### Phase 1 — Discovery (parallel web searches)

Run these searches in parallel — focus on GitHub and Microsoft AI only:
1. `"GitHub Copilot new features releases [CURRENT_MONTH] [CURRENT_YEAR]"`
2. `"Microsoft AI announcements Azure MAI models [CURRENT_MONTH] [CURRENT_YEAR]"`
3. `"GitHub changelog [CURRENT_MONTH] [CURRENT_YEAR] new features"`
4. `"Microsoft Build Azure AI updates [CURRENT_MONTH] [CURRENT_YEAR]"`

#### Phase 2 — Deep Dive (parallel per feature)

For each feature/update discovered in Phase 1, search for:
- What specifically shipped and when
- How it works and who it's available to
- What it enables that wasn't possible before
- How non-developer roles (PM, marketing, revenue, partnerships, events/DevRel, operations) can use it

#### Phase 3 — Stack Ranking

Rank capabilities from most to least powerful using these criteria (weighted):
1. **Threshold crossing** (40%) — Did it beat a human baseline? First of its kind?
2. **Practical impact** (30%) — How many people/workflows does this change?
3. **Accessibility** (20%) — Can anyone use it, or is it restricted?
4. **Benchmark delta** (10%) — How much did it improve over the previous best?

#### Phase 4 — Prompt Generation

For each ranked capability, write a **ready-to-use prompt** that:
- Demonstrates the specific frontier skill (not generic)
- Can be copy-pasted into the model's interface or API
- Includes context and instructions so it works standalone
- Pushes the model to its limits on that specific capability

#### Phase 5 — Live Model Showdown 🏟️

This is the section that makes this report unique. Pick the single most interesting
prompt from Phase 4 — the one that best tests a genuinely new frontier capability.

Run that SAME prompt against 3-5 models using the `task` tool with different `model` overrides.
Launch them **in parallel** using background mode for speed.

**Models to include** (use whichever are available, aim for diversity across model families):
- `claude-sonnet-4.6` or `claude-opus-4.6` (Anthropic)
- `gpt-5.5` or `gpt-5.4` (OpenAI)
- `gemini-3.1-pro-preview` (Google)
- `claude-haiku-4.5` (smaller/faster tier for comparison)
- Any other available model that's relevant to the week's story

For each model response, capture:
1. The first ~300 words of the actual output (trim for readability)
2. How long it took (note if fast/slow)
3. A 1-sentence quality verdict

Then write the **🏟️ Live Model Showdown** section for the report:

```markdown
## 🏟️ Live Model Showdown

**This week's test:** {describe what the prompt tests and why it was chosen}

**The prompt:**
\```
{the exact prompt sent to all models}
\```

### Results

#### {Model 1 Name}
{trimmed actual output}
**Verdict:** {1-sentence assessment}

#### {Model 2 Name}
{trimmed actual output}
**Verdict:** {1-sentence assessment}

{...repeat for each model...}

### 🏆 Winner: {Model Name}
**Why:** {2-3 sentences on what separated the winner — be specific and opinionated}
**Surprise:** {anything unexpected in the results}
```

**Rules for the showdown:**
- Use the EXACT same prompt for every model — no tweaking
- Show REAL output, not summaries of output — readers should see actual model responses
- Be honest and opinionated about the winner — don't hedge
- Note if any model refused, errored, or produced garbage
- This section should feel like a live experiment, not a polished review

#### Phase 6 — Output Generation

Generate THREE outputs:

**1. Markdown Report** — Save to the session research folder:
```
~/.copilot/session-state/{SESSION_ID}/research/weekly-ai-report-{DATE}.md
```

Include:
- TL;DR (3-5 sentences, punchy summary for busy readers)
- Detailed section per capability (see structure below)
- 🏟️ Live Model Showdown section (from Phase 5)
- "At a Glance" summary table (NO cost/pricing column)
- "This Week's Biggest Takeaway" closing section
- Confidence assessment
- Footnotes with source URLs

**Do NOT include cost-per-token or pricing data anywhere in the report.**

**2. CSV on Desktop** — Save to:
```
~/Desktop/weekly-ai-report-{DATE}.csv
```

Columns: Rank, Capability, Model, Developer, Key Breakthrough, Benchmark, Access, Prompt

Then open the CSV with: `open ~/Desktop/weekly-ai-report-{DATE}.csv`

**3. Auto-publish GitHub Issue** — Create the issue automatically:
```bash
gh issue create \
  --repo DUBSOpenHub/weekly-ai-frontier-report \
  --title "📡 Weekly AI Frontier Report — {DATE_RANGE}" \
  --body-file {path to markdown report} \
  --label "weekly-report,frontier-models,published"
```

Add the `open-source` label if any story covers open-weight models.
Add the `policy` label if any story covers regulation or governance.
Do NOT add `needs-review` — the report auto-publishes.

#### Phase 7 — Summary

Print a concise summary to the terminal:
- The top 3 most important things from this week
- The single most surprising finding
- Where both files were saved

## Output Format

### Markdown Report Structure

The report is written for an internal team member who wants to stay current on AI.
Tone: Opinionated, practical, memorable. Not a summary — a take. Every section should
have at least one line worth screenshotting. Frame each item as news from a smart
colleague who has a *point of view*, not just information.

```markdown
# 📡 Weekly AI Frontier Report — {DATE_RANGE}
### This week's GitHub & Microsoft AI updates — explained.

## TL;DR
{3-5 punchy sentences. Don't just list what happened — connect the dots. What's the
THEME of this week? End with a line that frames why this week matters as a whole.}

## #1 {EMOJI} {Catchy Headline}
**What happened:** {description — facts first, specific details}
**Why it matters:** {significance — INFORMATIVE, not celebratory. What does this
enable? What changes? Be clear and practical, not hype.}
**💡 The part you might miss:** {the non-obvious implication or use case that
casual readers will skip past. Often the most valuable insight.}
**What this means:**
- {actionable takeaway 1 — be specific}
- {actionable takeaway 2}
- {actionable takeaway 3}

**🧪 Try it yourself:**

**{PRODUCT}:**
\```
{prompt tailored to that product surface}
\```

Products to choose from (pick 2-3 most relevant per story):
- **Copilot CLI** — terminal-based, power-user workflows
- **Copilot App** — Canvases, multi-session, agent orchestration
- **M365 Copilot** — and when applicable, specify the app: Word, Excel, PowerPoint, Outlook, Teams
Prompts must be specific, practical, and accessible to non-developers.}
\```

**Sources:** {linked sources} · Confidence: **{High/Medium}**

{...repeat for each story...}

## 🏟️ Live Model Showdown
{See Phase 5 for full structure — real prompt, real outputs, real winner}

## At a Glance
| # | What Shipped | Feature | How You Can Use It |
|---|---|---|---|
{summary row per capability — NO cost column. "Why You Should Care" should be
sharp and opinionated, not generic.}

## This Week's Biggest Takeaway
{2-3 sentence synthesis — not a recap, a THESIS. What's the one idea that connects
all 7 stories? End with something memorable.}
**One thing to try this week:** {single low-friction action anyone can do}

## 🔮 Bold Prediction
{One specific, falsifiable prediction based on this week's developments.
Include a timeframe (e.g., "within 90 days"). Be bold but reasoned.
End with: "We'll track this prediction. If we're wrong, we'll say so."}
```

## Confidence Assessment
{what's certain vs inferred}

## Footnotes
{citations}
```

**IMPORTANT formatting rules:**
- SCOPE: GitHub and Microsoft AI only. No coverage of Anthropic, Google, Meta, or other labs unless directly relevant to a GitHub/Microsoft feature.
- TONE: Informative, not celebratory. Don't hype — explain. Write like a smart colleague sharing useful news, not a press release.
- Section order: What happened → Why it matters → 💡 The part you might miss → What this means
- Every story gets "🧪 Try it yourself" with ALL FOUR prompts:
  1. **Copilot CLI** — always
  2. **Copilot App** — always
  3. **M365 Copilot** — always (specify: Word, Excel, PowerPoint, Outlook, or Teams)
  4. **Bonus** — one additional M365 app or surface that's especially relevant (your choice)
- Do NOT organize prompts by job title or role
- Do NOT include developer/engineering-specific prompts
- Prompts should be accessible to non-developers
- Always include at least one **M365-based** prompt option per story
- Non-dev prompts must be genuinely useful — not "ask about X" but specific enough to produce actionable output
- No cost/pricing data anywhere in the report
- "At a Glance" table uses: What Shipped, Feature, How You Can Use It (3 columns)
- Include a 🔮 Bold Prediction section — specific, falsifiable, time-bound
- End with "We'll track this prediction. If we're wrong, we'll say so."

### CSV Structure

```
Rank,Capability,Model,Developer,Key Breakthrough,Benchmark,Access,Prompt
```

## Error Handling

- If web search returns no results for a model, note it as "unverified" and move on
- If fewer than 5 capabilities found, still rank and report what exists
- If a benchmark number appears in only one source, flag confidence as "single-source"
- Always generate both outputs even if research is incomplete

## Example Interaction

**User:** weekly ai report

**Assistant:** *[Runs full research pipeline autonomously, ~60-90 seconds]*

📡 **Weekly AI Report — April 7-10, 2026**

Top 3 this week:
1. **Claude Mythos** found thousands of zero-day vulns autonomously (restricted access)
2. **GPT-5.4** beat humans at desktop computer use (75% vs 72.4% human baseline)
3. **GLM-5.1** became first open-source model to top SWE-Bench Pro

🤯 Most surprising: An open-source model (GLM-5.1) now beats every proprietary model at real-world coding tasks.

📄 Full report: `~/.copilot/session-state/.../research/weekly-ai-report-2026-04-10.md`
📊 CSV opened on Desktop: `~/Desktop/weekly-ai-report-2026-04-10.csv`
