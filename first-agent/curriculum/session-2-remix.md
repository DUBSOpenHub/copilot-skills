# Session 2: Remix It 🔧

## Overview
**Duration**: 30 minutes (10 min anatomy + 15 min remix exercises + 5 min pair share)
**Goal**: Attendees modify a working agent and see behavior change. The identity shift: "I can control this."
**Milestone**: Tinkerer (200 pts)
**Pre-req**: Session 1 complete

## Step 1: Welcome Back (1 min)

Display:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SESSION 2: REMIX IT 🔧
  
  Last time you ran an agent.
  This time you're going to change one.
  Same agent. Your rules.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Step 2: The Anatomy (5 min)

Read and display `curriculum/templates/meeting-summarizer.md` — the same agent from Session 1.

Walk through the four sections, one at a time:

> **Section 1 — Identity** (lines 1-2)
> "This tells the agent WHO it is. Like a job title and job description in two sentences."

> **Section 2 — Rules** (lines 3-8)
> "These are the instructions. Each rule changes behavior. Add a rule, the agent does something new. Remove a rule, it stops doing that thing."

> **Section 3 — Output Format** (lines 9-16)
> "This is what the output looks like. You're designing a template. The agent fills it in."

> **Section 4 — Tone** (lines 17-20)
> "This sets the personality. Professional? Casual? Bullet points or paragraphs? Your call."

After walking through all four, say:

> "That's the whole agent. Four sections. Plain English. Every agent you'll ever see follows this same pattern: Identity, Rules, Output, Tone."

## Step 3: Exercise 1 — Change a Rule (5 min)

Say:
> "Let's change one thing. Right now this agent lists action items but doesn't prioritize them. Let's add a rule that makes it rank action items by urgency."

Guide them:
1. Show the current rules section
2. Add a new rule: `"Rank all action items by urgency: 🔴 High, 🟡 Medium, 🟢 Low"`
3. Re-run the agent on the same meeting notes from Session 1

After the output appears:

> "See the difference? One line changed. The output now has priority markers. That's the fundamental insight: **these instructions are like a recipe. Change an ingredient, change the dish.**"

## Step 4: Exercise 2 — Break It, Fix It (5 min)

Say:
> "Now let's try something fun. Let's delete the output format section entirely and see what happens."

Guide them:
1. Remove the Output Format section
2. Re-run on the same notes
3. Show the degraded output — it'll be unstructured, inconsistent

> "See how messy that got? The output format is what gives the agent structure. Without it, the agent improvises — and improvisation isn't what you want when you need consistent results."

Now restore it:
1. Put the Output Format section back
2. Re-run — clean output returns

> "And it's back. You just learned something that takes some people weeks to figure out: **every section of an agent matters, and you can test that by removing it.**"

## Step 5: Exercise 3 — Make It Yours (5 min)

```
ask_user: "Pick one change to make this agent your own:"
choices: [
  "Change the output to include a 'Decisions Made' section",
  "Make it add emoji to each section header",
  "Add a rule: 'Flag any items that mention deadlines'",
  "Change the tone to be more casual and friendly"
]
```

Guide them through whichever they pick. Re-run. Show the result.

> "You just customized an AI agent. Not by coding — by writing a clear instruction in English. That's all agent-building is."

## Step 6: Knowledge Check (5 min)

Five questions via `ask_user`:

**Q1:**
```
ask_user: "What are the four sections of an agent?"
choices: [
  "Identity, Rules, Output Format, Tone",
  "Header, Body, Footer, Signature",
  "Input, Processing, Output, Logging",
  "Name, Code, Tests, Documentation"
]
correct: "Identity, Rules, Output Format, Tone"
```

**Q2:**
```
ask_user: "What happens when you remove the Output Format section?"
choices: [
  "The agent still works but output is unstructured and inconsistent",
  "The agent crashes",
  "Nothing changes",
  "The agent refuses to run"
]
correct: "The agent still works but output is unstructured and inconsistent"
```

**Q3:**
```
ask_user: "How do you add a new behavior to an agent?"
choices: [
  "Add a new rule in plain English",
  "Write code in Python",
  "Submit a ticket to the AI team",
  "Install a new plugin"
]
correct: "Add a new rule in plain English"
```

**Q4:**
```
ask_user: "What's the best way to test if a rule is working?"
choices: [
  "Remove it, run the agent, see what changes",
  "Read the documentation",
  "Ask someone on the engineering team",
  "There's no way to test it"
]
correct: "Remove it, run the agent, see what changes"
```

**Q5:**
```
ask_user: "An agent is written in:"
choices: [
  "Plain English with light formatting",
  "Python",
  "A proprietary AI language",
  "JSON configuration files"
]
correct: "Plain English with light formatting"
```

Award +15 per correct. +50 bonus for perfect (5/5).

## Step 7: Pair Share (3 min)

> "Turn to the person next to you. Show them the change you made in Exercise 3. What did you change? What happened?"

> ⏱️ [FACILITATOR: Give 2-3 minutes for pair sharing. This is where the energy builds — people get excited seeing each other's changes.]

## Step 8: Bridge to Session 3 (2 min)

Display:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✅ SESSION 2 COMPLETE
  
  🔧 Milestone: Tinkerer
  ⭐ Points: [total]
  
  You can read an agent.
  You can change an agent.
  You can break and fix an agent.
  
  Next up → Session 3: Build It
  You're building your own. From scratch.
  
  🏠 HOMEWORK: Think about one task you
  do repeatedly that feels like it could
  be automated. Bring that to Session 3.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Update SQL:
- Add points (75 base + quiz points)
- Set milestone to "Tinkerer"
- Mark session 2 completed with timestamp
- Increment sessions_completed
