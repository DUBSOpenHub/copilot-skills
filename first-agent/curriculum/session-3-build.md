# Session 3: Build It 🏗️

## Overview
**Duration**: 45 minutes (5 min setup + 25 min guided build + 15 min live showcase)
**Goal**: Every attendee builds a custom agent from scratch and demos it to the room.
**Milestone**: Builder (500 pts)
**Pre-req**: Sessions 1 and 2 complete

## Step 1: Frame It (2 min)

Display:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SESSION 3: BUILD IT 🏗️
  
  This is it.
  You're building your own agent.
  Not modifying someone else's.
  Yours. From scratch.
  
  It takes about 20 minutes.
  You'll have a working agent at the end.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Step 2: Find the Problem (3 min)

```
ask_user: "What repetitive task wastes your time? Pick the closest match, or describe your own."
choices: [
  "Summarizing meetings or calls",
  "Writing status updates or reports",
  "Drafting emails from bullet points",
  "Organizing or formatting documents",
  "Reviewing and extracting info from long documents"
]
allow_freeform: true
```

Based on their answer, select the closest template:
- Meetings/calls → `meeting-summarizer.md`
- Status/reports → `report-generator.md`
- Emails → `email-drafter.md`
- Anything else → `starter-agent.md`

Say:
> "Great choice. I'm going to give you a starter template and we'll customize it together. Think of it like a recipe — we'll swap out ingredients to match your taste."

## Step 3: Name Your Agent (1 min)

```
ask_user: "What should we call your agent? Pick a name that describes what it does."
allow_freeform: true
```

Store the name. This appears on the showcase card.

## Step 4: Build — Identity (3 min)

Show the Identity section of the selected template. Explain:
> "This is your agent's job description. Two sentences: who it is and what it does."

```
ask_user: "Here's the default identity. Want to customize it or keep it as-is?"
choices: [
  "Keep the default — it's close enough",
  "I want to customize it"
]
```

If customize: ask them to describe what the agent should be in 1-2 sentences. Help them refine it into a clean identity statement.

## Step 5: Build — Rules (5 min)

Show the Rules section. Explain:
> "Rules are the instructions your agent follows. Each rule is one behavior. Be specific — 'always include dates' is better than 'be detailed.'"

Show the template's default rules, then:

```
ask_user: "Let's customize the rules. What should your agent ALWAYS do?"
choices: [
  "Keep the default rules",
  "I want to add a rule",
  "I want to change a rule",
  "I want to start fresh with my own rules"
]
```

Guide them through adding/changing 1-2 rules. Keep it simple. If they want to start fresh, help them write 3-4 clear rules.

Remind them: "Remember Session 2 — every rule changes behavior. Keep them short and specific."

## Step 6: Build — Output Format (3 min)

Show the Output Format section. Explain:
> "This is the template for your agent's output. You're designing what the result looks like."

```
ask_user: "How should your agent's output be structured?"
choices: [
  "Keep the default format",
  "Use bullet points with headers",
  "Use a numbered list",
  "Use a table format",
  "I'll describe what I want"
]
```

Help them set up their output format. Keep it clean and practical.

## Step 7: Build — Tone (2 min)

```
ask_user: "What tone should your agent use?"
choices: [
  "Professional and concise",
  "Friendly and conversational",
  "Direct and no-nonsense",
  "Warm but structured"
]
```

Add the tone instruction to the agent.

## Step 8: Assemble and Review (2 min)

Combine all four sections into a complete agent. Display the full agent file:

> "Here's your complete agent. [X] lines of plain English. This is the whole thing."

```
ask_user: "How does this look?"
choices: [
  "Looks great — let's test it!",
  "I want to tweak something first"
]
```

If tweak: help them adjust, then show again.

## Step 9: Test Run (3 min)

```
ask_user: "Ready to test your agent? Paste some real data for it to work on, or I'll generate a sample."
choices: [
  "Generate a sample for me",
  "I'll paste my own data"
]
```

If sample: generate realistic sample data appropriate to their agent type.

Run the agent on the data. Display the output.

> "⏱️ That task typically takes about [estimate] minutes manually. Your agent just did it in seconds."

```
ask_user: "How did it do?"
choices: [
  "That's really good!",
  "Pretty good but I'd change something",
  "It needs work — let me adjust"
]
```

If they want to change: help them iterate. One or two tweaks max to stay on time.

If they're happy:
> "You just built a working AI agent. From scratch. In about 20 minutes. This agent is yours — you can use it every day, share it with your team, or keep customizing it."

## Step 10: Save the Agent (2 min)

Use the `create` tool to save their agent as a file:
- Path: `~/.copilot/agents/[agent-name-slugified].agent.md`
- Confirm the save

> "Your agent is saved. You can run it anytime."

## Step 11: Graduation (3 min)

Read `curriculum/graduation.md` and follow the graduation flow to generate their showcase card.

Update SQL:
- Add points (100 base + 200 for original agent)
- Set milestone to "Builder"
- Mark session 3 completed with timestamp
- Increment sessions_completed
- Insert into first_agent_builds

## Step 12: Live Showcase Prep (2 min)

> "The facilitator is about to ask for volunteers to demo their agent to the room. Here's your 60-second script:"

Generate a brief showcase script:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  🎤 YOUR SHOWCASE SCRIPT (60 sec)
  
  "My agent is called [name]."
  "It [what it does in one sentence]."
  "I built it because [the problem it solves]."
  "Let me show you..." [run the agent]
  
  Total build time: ~[X] minutes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

> ⏱️ [FACILITATOR: Now run the live showcase. Ask for 4-5 volunteers. Each gets 60 seconds. Encourage applause. This is the moment people remember.]

Display final:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✅ SESSION 3 COMPLETE
  
  🏗️ Milestone: Builder
  ⭐ Points: [total]
  
  You built an AI agent.
  From scratch. In plain English.
  It's saved and ready to use.
  
  🎓 You are now an Agent Builder.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
