# Session 1: Run It 🧭

## Overview
**Duration**: 30 minutes (10 min demo + 15 min hands-on + 5 min debrief)
**Goal**: Every attendee runs a working AI agent and sees useful output from their own data.
**Milestone**: Explorer (50 pts)

## Step 1: Welcome (1 min)

Display:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SESSION 1: RUN IT 🧭
  
  You're about to run an AI agent.
  It will take about 2 minutes.
  Nothing can break. Let's go.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Step 2: The Agent (3 min)

Explain briefly:
> "An agent is a text file with instructions. You give it a task, it follows the instructions and gives you a result. That's it. No magic, no code. Just clear instructions in plain English."

Then show them the meeting summarizer by reading `curriculum/templates/meeting-summarizer.md` and displaying it. Point out:
- It's about 20 lines
- It's written in plain English
- Anyone could read it and understand what it does

## Step 3: Run It (5 min)

Ask the attendee:

```
ask_user: "Do you have meeting notes you'd like to try? Paste them below, or I can use a sample."
choices: ["Use sample meeting notes", "I'll paste my own"]
```

**If sample**: Use these built-in sample notes:

```
Team sync - March 5

Attendees: Sarah, Mike, Jordan, Priya

- Sarah: Q1 dashboard is almost done. Needs data from Mike's team by Friday.
- Mike: Data export is ready but has a formatting issue. Will fix by Thursday.
- Jordan: Customer feedback survey results are in. NPS dropped 5 points. Wants to schedule a deep-dive.
- Priya: New hire starting Monday. Needs laptop and account access set up.
- Sarah: Can we move the weekly sync to Tuesday? Conflicts with her other meeting.
- Everyone agreed to try Tuesday at 2pm for two weeks.
- Jordan will send the NPS report to the team by end of day.
- Mike will CC Sarah when the data export is fixed.
```

**If pasting their own**: Accept whatever they paste.

Now act as the meeting-summarizer agent. Follow the instructions in `curriculum/templates/meeting-summarizer.md` to process the notes. Produce the structured output.

After showing the output, pause and say:

> "That's it. You just ran an AI agent. It read your notes, identified the key information, and organized it. The whole thing took about 30 seconds."
>
> "⏱️ Typical time to do this manually: ~15 minutes. Agent time: ~30 seconds."

## Step 4: Explore the Output (3 min)

Ask:

```
ask_user: "What do you notice about the output?"
choices: [
  "It pulled out action items I might have missed",
  "It organized things more clearly than my notes",
  "It's pretty good but missed something",
  "I'm surprised it worked on my actual notes"
]
```

Respond warmly to whatever they pick. If they say it missed something, acknowledge it: "Good eye. Agents aren't perfect — but they give you a strong first draft to work from. The cool part? In Session 2, you'll learn how to fix that by editing one line."

## Step 5: Knowledge Check (5 min)

Three questions via `ask_user`:

**Q1:**
```
ask_user: "What is an AI agent, based on what you just experienced?"
choices: [
  "A text file with instructions that processes information",
  "A complex program that requires coding to build",
  "A chatbot that answers questions",
  "A database that stores meeting notes"
]
correct: "A text file with instructions that processes information"
```

Award +15 for correct. If wrong, gently clarify: "Close! An agent is actually just a text file with instructions. That's what makes it so accessible — if you can write clear instructions, you can build an agent."

**Q2:**
```
ask_user: "How long was the agent file you just used?"
choices: [
  "About 20 lines",
  "Hundreds of lines of code",
  "It's a compiled program, no lines to count",
  "About 200 lines"
]
correct: "About 20 lines"
```

Award +15 for correct.

**Q3:**
```
ask_user: "What language is the agent written in?"
choices: [
  "Plain English (with some formatting)",
  "Python",
  "JavaScript",
  "A special AI language"
]
correct: "Plain English (with some formatting)"
```

Award +15 for correct. +50 bonus if all three correct.

## Step 6: Wrap-Up (2 min)

Display progress:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✅ SESSION 1 COMPLETE
  
  🧭 Milestone: Explorer
  ⭐ Points: [total]
  
  You ran your first AI agent.
  It's just a text file. 20 lines.
  Plain English.
  
  Next up → Session 2: Remix It
  You'll open that file and change it.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Update SQL:
- Set points
- Set milestone to "Explorer"
- Mark session 1 completed with timestamp
- Increment sessions_completed

Say: "Show your facilitator your output! And think about this: that agent was just 20 lines. Next session, you're going to change those lines and watch the behavior change."
