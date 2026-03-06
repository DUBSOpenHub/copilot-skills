# Graduation 🎓

## When to Trigger
Run this flow when an attendee completes Session 3 (built their own agent).

## Step 1: Collect Info

If not already known from Session 3, ask:

```
ask_user: "What's your name? (This goes on your showcase card.)"
allow_freeform: true
```

Gather from the session:
- Agent name (from Step 3 of Session 3)
- Agent description (from the Identity section they wrote)
- Template used (or "original" if starter)
- Build time (track from session start)

## Step 2: Generate Showcase Card

Display this in the terminal:

```
┌─────────────────────────────────────────────────┐
│                                                   │
│   🎓  FIRST AGENT BUILT                          │
│                                                   │
│   Agent:    "[Agent Name]"                        │
│   Builder:  [Employee Name]                       │
│   Role:     [Their role if known]                 │
│                                                   │
│   What it does:                                   │
│   [One-sentence description from Identity]        │
│                                                   │
│   Built in: [X] minutes                           │
│   Session:  [Date]                                │
│                                                   │
│   💬 "[Their reaction or a generated quote]"      │
│                                                   │
│   Built with GitHub Copilot CLI                   │
│   #FirstAgent #AgentBuilder                       │
│                                                   │
└─────────────────────────────────────────────────┘
```

## Step 3: Save Graduate Record

Write a JSON record to `~/.copilot/first-agent-graduates.json`:

```json
{
  "graduates": [
    {
      "name": "[name]",
      "agent_name": "[agent name]",
      "agent_description": "[description]",
      "template_used": "[template]",
      "build_time_minutes": [X],
      "date": "[ISO date]",
      "points": [total],
      "milestone": "Builder"
    }
  ]
}
```

If the file already exists, read it and append to the `graduates` array.

Use `bash` to write the file. Use `jq` if available, otherwise write directly.

## Step 4: Offer Slack-Ready Post

```
ask_user: "Want a Slack-ready post to share what you built?"
choices: [
  "Yes, generate a Slack post!",
  "No thanks, I'm good"
]
```

If yes, generate:

```
🎓 I just built my first AI agent!

It's called "[Agent Name]" — it [one-sentence description].

Took me [X] minutes. No coding. Just plain English instructions.

The whole agent is 20 lines of text. I'm genuinely surprised how simple this was.

Built during [Company]'s First Agent training with GitHub Copilot CLI.

#FirstAgent #AgentBuilder #CopilotCLI
```

Say: "Copy and paste that into Slack! Your team will want to know about this."

## Step 5: Batch Showcase (Facilitator Mode)

When triggered with "showcase" or "gallery", read `~/.copilot/first-agent-graduates.json` and display:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  🏛️ FIRST AGENT GALLERY
  
  Total Builders: [N]
  Average Build Time: [X] minutes
  
  ┌──────────────────────────────────────────────┐
  │ 1. "[Agent Name]" by [Name]                  │
  │    [Description] — built in [X] min          │
  ├──────────────────────────────────────────────┤
  │ 2. "[Agent Name]" by [Name]                  │
  │    [Description] — built in [X] min          │
  ├──────────────────────────────────────────────┤
  │ ...                                           │
  └──────────────────────────────────────────────┘
  
  🏆 Fastest Build: [Name] — [X] minutes
  🎨 Most Creative: [determined by facilitator]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Innovation Spotlight Template

For newsletter or weekly email, generate:

```
⚡ AGENT OF THE WEEK

[Name] from [team] built "[Agent Name]" — an AI agent that
[description]. It took [X] minutes to build and saves roughly
[estimated time] per use.

"[Quote from the builder]"

Want to build your own? Join the next First Agent session.
Sign up: [link placeholder]
```
