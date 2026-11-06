---
name: ai-first-drops
description: Research and publish exactly three verified GitHub and Microsoft AI stories with practical prompts, through the validated weekly runner.
---

# AI-First Drops

The canonical implementation is `~/copilot-workspace/ai-first-drops`.
Read this file and `scripts/drop_quality.py` there for the executable contract.
Do not use the retired `~/weekly-ai-frontier-report` checkout.

## Trigger and publication boundary

For "weekly ai report", "ai-first drops", or "run the drop", execute:

```bash
bash ~/copilot-workspace/ai-first-drops/scripts/weekly-report.sh
```

The runner prepares on Friday from **06:00 America/Los_Angeles**, publishes at
**09:00 Pacific**, retries every five minutes, and catches up through Sunday.
On other days it does nothing. To explicitly prepare a future Friday without
publishing, use `--prepare YYYY-MM-DD`. Never bypass the 09:00 publication gate.
The LaunchAgent uses this same runner. Do not separately create issues or releases.
No GUI apps are opened in scheduled runs.

**Exactly three verified stories are required.** A two-story edition is a failed
draft, not a publishable result. Research more candidates when a story fails.
Never invent, recycle an old launch as new, or pad a weak third item to meet
the quota. If three cannot be verified, record the missing evidence and fail
closed so the runner can retry and alert. Do not claim guaranteed availability
of a Mac, authentication, news sources, or remote services.

## Draft-only mode (invoked by the runner)

When asked to write `draft.json`, research and write only the requested JSON.
Do not recursively invoke the runner, publish, generate images, create releases,
send messages, open apps, or alter the installed skill.

### Research and verify

1. Cover the seven days ending on the requested Friday. Research at least six
   distinct candidates where possible across M365 apps (Word, Excel, PowerPoint,
   Outlook, Teams), Microsoft AI, GitHub Copilot App, GitHub Copilot CLI, and
   GitHub Changelog. Microsoft Copilot's consumer app is **not** GitHub Copilot App.
2. Read official announcements and release notes. Distinguish original ship dates
   from recap publication dates; exclude roadmap promises and inaccessible private
   previews presented as available features. Identify actual availability and limits.
3. Check Work IQ and Slack every run for corroboration and corrections. Respect
   source access policies; do not work around a blocked tool. A missing required
   discovery source is a blocker, not permission to pretend it was checked.
   If the hosted Work IQ connection has a transport or expired-token failure,
   the supported, project-pinned Microsoft client provides a normal sign-in path:
   `~/copilot-workspace/ai-first-drops/node_modules/.bin/workiq ask --json -q "..."`
   Use its authenticated result only when `isError` is false. Do not clear shared
   credentials, bypass policy denials, or claim the hosted connection was repaired.
   Keep references and sensitivity labels local; published claims need public
   evidence regardless of the internal source. Reuse authorized discovery evidence
   already gathered for the same edition, with its original provenance; do not
   claim that cached evidence is a fresh query. Never background-scan Slack or read
   unapproved threads; only use specifically authorized links/evidence.
4. Internal corroboration remains in the local draft only. Every publishable
   claim must also be supported by a public official GitHub/Microsoft URL.
   Never publish private links, internal quotations, unreleased/embargoed material,
   customer data, personal data or confidential facts to the canonical archive.
5. Rank non-developer impact (50%), practical impact (25%), accessibility (15%)
   and threshold crossing (10%). Lead with useful business workflows, not admin
   metrics or coding-model trivia. Explain what actually changed and why it matters.

### Write

- Three distinct, neutral, readable headlines; no hype, "finally", fabricated
  benchmark or pricing claims. Keep each story under 180 words excluding its prompt.
- Plain English paragraphs, not serialized tool output, JSON fragments, escaped
  Unicode, placeholders, raw HTML, markup, broken encodings or missing descriptions.
- One standalone, actionable prompt per story, accessible to a non-developer.
  Exactly one each: **GitHub Copilot CLI**, **GitHub Copilot App**, and
  **M365 Copilot (specific app)**. Do not force a feature onto a surface where it
  does not work. The independent editor checks this against the cited source.
- State access/preview requirements explicitly. Prompts must demonstrate the
  specific new capability, not just ask for a generic summary. Use supplied inputs,
  flag missing evidence, and require approval before consequential actions.
- Always use "GitHub Copilot" in full for GitHub products and "M365 Copilot" for
  Microsoft 365. Preserve the actual identity of other Microsoft products.

### JSON contract

The draft is UTF-8 JSON, with this shape (the example describes fields, not news):

```json
{
  "edition_date": "2026-11-06",
  "research": {
    "workiq": "checked",
    "slack": "checked",
    "candidate_count": 6
  },
  "stories": [
    {
      "headline": "A neutral headline for a verified capability",
      "what_changed": "What shipped, its real date, and what the feature does.",
      "why_it_matters": "The concrete practical change for a non-developer.",
      "access": "Actual availability, licenses, preview status and known limits.",
      "surface": "M365 Copilot (Word)",
      "prompt": "A complete standalone prompt of at least sixty characters that demonstrates this specific capability on this surface.",
      "source_url": "https://learn.microsoft.com/official-source-path",
      "source_date": "2026-11-02",
      "confidence": "High",
      "internal_evidence": {
        "system": "workiq",
        "reference": "A local-only verifiable source reference",
        "public_safe": true
      }
    }
  ],
  "bottom_line": "One memorable, factual sentence connecting all three stories."
}
```

Supply **three** objects in `stories`, with distinct headlines and specific
source URLs; use the other two approved surfaces exactly once. `confidence` is
High or Medium. `internal_evidence.system` is workiq, slack, or internal-docs.
Dates must be in the requested seven-day window; never invent future dates.
If blocked, write `research-blocker.txt` alongside the draft with the exact gap.

## Independent editorial review

The runner starts a fresh, separate CLI invocation after schema validation.
It reads the official sources, verifies dates, product identity, access, prompt
compatibility, public safety, plain-English descriptions and ranking. Its
`review.json` must name the exact SHA-256 of the current draft and pass all six
checks in `drop_quality.REVIEW_CHECKS`. Rejected drafts are retained for diagnosis,
then researched again; stale approvals cannot authorize changed content.
An automated review reduces risk; it is not proof every factual claim is infallible.

## Graphics and output

The runner calls the **official Asset Generator** `create_email_banner` endpoint,
the same tool exposed by the companion. No generative typography or substitute
social graphic. Fixed properties:

- `pillar`: `copilot`
- `heading`: `AI-First Drops`
- `eyebrow`: the actual edition date range
- `description`: `This week's AI updates — explained, with prompts to try.`
- `theme`: rotate through all 12 light, grey and dark email themes using
  `(canonical edition number - 1) % 12`

Download and verify the 1320x568 PNG; macOS Vision OCR must read the title,
date range and exact description. Service, dimensions, or text failures block
publication. The image is checked **before**, not injected after, publishing.
The verified PNG is archived in a **draft edition release**, downloaded again
and byte-checked. It is also uploaded as a GitHub image attachment associated with
the internal distribution repository. Reports use that stable attachment URL,
not a temporary image-service URL or a private release-download URL.
Verify the image through GitHub Markdown rendering in **both repositories**;
private image URLs are signed during rendering, so a raw anonymous URL check is
not the reader's actual path. Do not persist expiring signed URLs.
The draft release is published only at publication time; final notes link to the
edition issue. Never overwrite another edition's release/asset or change repository
visibility to make a retry pass.

The renderer—not the model—writes the title, banner, subtitle, three story
sections with separated **🆕 What changed**, **🎯 Why it matters**,
**🧪 Try it in**, **🔗 Source** blocks, then the final three-column Quick Summary
and bottom line. There is no TL;DR, honorable mention, or fourth story.

Local outputs and private research evidence:
`~/.copilot/ai-first-drops/YYYY-MM-DD/`.
CSV also goes to `~/Desktop/ai-first-drops-YYYY-MM-DD.csv` with columns
Rank, Capability, Model, Developer, Key Breakthrough, Benchmark, Access, Prompt.
Never invent model names or benchmark results for product features.

## Publication and recovery

The deterministic runner owns all writes:

1. Exact-title lookup in **DUBSOpenHub/ai-first-drops** and **github/dmo-ai**.
   API errors are not absence. Never append a new edition to an old issue.
2. Reuse an existing valid issue body unchanged on partial retry. Reject mismatches
   and invalid historical partial editions rather than silently overwrite them.
3. Create only missing copies with identical report bodies. Canonical labels:
   weekly-report, frontier-models, published. Never add those labels internally.
4. Assign the internal issue to DUBSOpenHub and add it to GitHub Project 20236;
   verify both persisted. Do not modify the project's view filters.
5. Cut canonical release `vN.0.0`, target main, mark latest; concise notes link
   to the canonical issue. Verify release and issue parity before recording success.
6. Lock against overlapping runs. Each CLI attempt has a 30-minute process-group
   timeout. Preserve logs, rejected drafts and failure reasons; alert after failure.
   Persist at most four expensive attempts per Pacific day per edition **per phase**;
   preparation failures cannot consume the 09:00 publication budget. A missing
   three-story research set waits an hour before another attempt; five-minute
   polling must not become an unlimited loop of paid research. Cooldown is not success.

Run `--preflight` for live auth/repository/project/banner-service checks and
`--status` for schedule/checkout information. Neither publishes.
