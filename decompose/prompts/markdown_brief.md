# markdown_brief.md — Step 7b: Human Brief Generation

## Purpose
Emit a plain-language `brief.md` that a non-technical user can read, understand, and hand to another person or agent without understanding JSON, prompts, or schemas. Runs in parallel with `task_genome_synthesis`.

## Inputs

| Input | Type | Required | Description |
|---|---|---|---|
| `clarification_state` | object | ✓ | Confirmed state with knowns, unknowns, blind_spots |
| `role` | string | ✓ | Adapts vocabulary and depth |
| `sanitized_intent` | string | ✓ | Confirmed goal |
| `genome.json` | object | optional | If available, use node list; otherwise synthesize from state |
| `brief.md.tmpl` | template | ✓ | Output scaffold |

## Output Contract

**Format:** Valid Markdown written to `brief.md`. Uses `brief.md.tmpl` as scaffold. All sections required.

**Required sections:**
1. `## Goal` — One sentence. Plain language. No jargon.
2. `## Why This Matters` — 2–3 sentences: what problem this solves, who benefits.
3. `## What We Know` — Bullet list of confirmed facts.
4. `## What We Don't Know Yet` — Bullet list of open unknowns. Never empty — at minimum note "All key facts were confirmed."
5. `## The Plan` — Numbered list of steps in plain language. Each step: what happens + why.
6. `## Decisions You Need to Make` — Numbered list of human gates. If none: "No decisions are blocked — the plan can run as-is."
7. `## Risks and Watch-Outs` — Bullet list of risks and assumptions, plain language.
8. `## How to Know It Worked` — Bullet list of success indicators, plain language.
9. `## Next Step` — One sentence: "To begin, [action]."

**Accessibility rules (enforced for all roles, critical for non-technical):**
- No unexplained acronyms.
- No technical jargon without inline explanation in parentheses.
- Sentences ≤ 25 words preferred.
- Active voice preferred.
- Section headers must be self-explanatory to a non-technical reader.
- No reference to `genome.json`, `nodes`, `edges`, `prompts`, or internal tooling.

## Guardrails

- **MUST NOT** reference JSON, schemas, genome, nodes, edges, prompts, or any technical infrastructure.
- **MUST NOT** include any secret, token, credential, or `[REDACTED]` item.
- **MUST NOT** include `[REVIEW-REQUIRED]` items — surface them as unknowns instead.
- **MUST NOT** resolve a human gate — list it under "Decisions You Need to Make."
- **MUST NOT** expose chain-of-thought or internal classifications.
- **MUST NOT** use passive voice constructions that obscure ownership ("it will be done" → "you will do X").
- **MUST** produce valid Markdown before genome.json validation is checked (NF-2).

## Examples

### Pass — developer, OAuth (brief excerpt)
```markdown
## Goal
Add GitHub login to our Python API, replacing the current login system, and get it working on our test environment within two weeks.

## Why This Matters
Right now, users log in with a username and password managed by our own system. Switching to GitHub login means users don't need a separate password, and we reduce the risk of storing credentials ourselves.

## What We Know
- We're using the FastAPI web framework
- GitHub will be the login provider
- The current login system (JWT-based) will be replaced, not kept alongside
- Target: test environment first, then live environment
- Two-week timeline

## What We Don't Know Yet
- How much of the current login code is covered by tests
- Who needs to sign off on removing the old login system

## The Plan
1. **Research options** — Find the best Python library for GitHub login (takes ~half a day)
2. **Build the GitHub login flow** — Write the code for users to log in with GitHub (~3 days)
3. **Approve the switch** — You review and confirm the old login system can be removed (human decision required)
4. **Remove the old login system** — Clean up the old code and redeploy (~1 day)

## Decisions You Need to Make
1. **Remove old login system** — Before step 4 runs, you (or your team lead) must confirm it's safe to delete the current login code. This can't be undone automatically.

## Risks and Watch-Outs
- Current users may be logged out during the switch — plan for a brief maintenance window
- If we assumed FastAPI is your framework and it isn't, some steps may need adjusting

## How to Know It Worked
- A user can click "Log in with GitHub" and reach their account
- The old login endpoints no longer work
- All tests pass

## Next Step
To begin, start with the research step: find and evaluate Python OAuth libraries for FastAPI.
```

### Pass — non-technical creator, newsletter
```markdown
## Goal
Launch a weekly email newsletter about sustainable living for a small starting audience.

## Why This Matters
You want to share ideas about sustainable living regularly. A newsletter lets you build a loyal audience who chose to hear from you — on a schedule you control.

## What We Know
- Weekly sending cadence
- Topic: sustainable living
- Starting small (fewer than 500 readers)
- You'll write the content yourself

## What We Don't Know Yet
- Which email tool you'll use (Mailchimp, Substack, Beehiiv, etc.)
- Whether you have a list of people to invite

## The Plan
1. **Choose your email tool** — Pick a platform that fits your budget and comfort level
2. **Set up your newsletter** — Create your account, brand it, and write your welcome email
3. **Build your first audience** — Invite people you know, share a sign-up link
4. **Write and send issue #1** — Your first real issue goes out to real readers
5. **Approve your first send** — You personally review and hit "send" (this is a decision only you make)

## Decisions You Need to Make
1. **Send first email** — Sending your first newsletter is a public action. You'll review it and press send yourself.

## Risks and Watch-Outs
- Without an email platform chosen, we can't complete step 2
- Sending without a subscriber list means no readers on day one

## How to Know It Worked
- Your newsletter is live and accepting sign-ups
- At least one person (ideally more) receives issue #1

## Next Step
To begin, choose your email platform — this unlocks all the steps that follow.
```

### Failure — jargon in non-technical brief
**Bad:** "Configure the SMTP relay and set up a cron job for batch delivery."
*Reason: SMTP relay and cron job are unexplained technical terms. Non-technical accessibility rubric fails.*

### Failure — internal reference leaked
**Bad:** "See node `send_email_batch` in genome.json for the prompt template."
*Reason: Internal artifact reference in user-facing brief. Violates NF-4.*

## Failure Behavior

- `clarification_state.confirmed = false` → do not write brief; return to reflection_mirror.
- Template slot cannot be filled → use `[TBD — to be confirmed]` and list as unknown.
- Genome not yet available → synthesize plan steps from `knowns` and Q&A log.
- Markdown validation fails (malformed headers, broken lists) → self-correct and re-validate before writing.
