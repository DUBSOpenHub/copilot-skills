# First Agent: Facilitator Guide

You are the most important part of this program. The skill guides the technical exercises, but you bring the energy, the pacing, and the human moments that make people remember this training.

---

## Before the Session

### Room Setup
- [ ] Projector connected to YOUR laptop (you demo from your terminal)
- [ ] Attendees have laptops open with terminal access
- [ ] Copilot CLI installed on all machines (coordinate with IT in advance)
- [ ] Wi-Fi confirmed working
- [ ] The skill installed: `~/.copilot/skills/first-agent/` on all machines

### Pre-Install Script (share with IT)
```bash
# Verify Copilot CLI is working
copilot --version

# Install the First Agent skill
mkdir -p ~/.copilot/skills/first-agent
# [Copy skill files to the directory]
```

### Your Prep (10 min)
1. Run through Session 1 yourself. Know what the output looks like.
2. Build your own agent using Session 3. Have it ready as your opening demo.
3. Prepare YOUR meeting notes (or status report, or email draft) for the live demo. Real data from your actual work hits harder than samples.

### The Opening Hook Script (your first 2 minutes)

This script was battle-tested across 8 AI models and refined through two elimination rounds, then fused from the 4 finalists' strongest DNA. Use it as-is or adapt it to your own voice. The structure works — the specific details should be yours.

> Six back-to-back meetings last Tuesday. You know that feeling — not like you forgot a detail. Like it *passed through you*. You were there. You nodded. You retained absolutely nothing.
>
> So Wednesday, out of pure frustration, I wrote something. Not code — I can't write code. Twenty lines of plain English. Took maybe fifteen minutes.
>
> I'm going to run it right now on a real transcript from yesterday. Watch.
>
> *[run your agent]*
>
> Three decisions I didn't remember being made. Two action items I'd already lost. And one line that stopped me cold: someone had volunteered me for a Friday deadline I never agreed to. Just sitting in paragraph six, waiting to become my problem Thursday night.
>
> Four seconds. The meeting drained an hour of my life, and this got it back in four seconds.
>
> Here's the instruction file. Read line five with me. It says: "Find the decisions. Flag anything with my name on it by Thursday." That's it. Not Python. Not code. English. Like writing a really good email to a really fast assistant who never sleeps and has no ego.
>
> I call it Brief. Because that's all I ever wanted from a meeting. And I built it two weeks ago knowing nothing. If you can write a grocery list, you can build one of these.
>
> Here's what today is. Everyone in this room has a version of this problem. The status report you dread. The survey data you never look at. The job description that takes three drafts. In ninety minutes, you're going to build your own. You'll run one first, just to feel it move. Then you'll crack it open and change what it does. Then you build from scratch — and you show the room.
>
> Open your laptops. What's the task that quietly drains your time? Let's go.

**Adaptation tips:**
- Replace "six back-to-back meetings" with your actual pain point
- The demo surprise ("flagged a deadline I didn't agree to") is the money moment — find your own version of this
- Name your agent. "Notes to Nobody," "Monday Morning Me," "Brief" — a name makes it real
- The line "closer to writing a really good email to a really fast assistant" is the best demystification line. Keep it.

---

## Session 1: Run It (30 minutes)

### Pacing Guide

| Time | What's Happening | Your Role |
|------|-------------------|-----------|
| 0:00-0:02 | Opening | Hook them. Show YOUR agent on the projector. "I built this in 8 minutes. By the end of today, you'll build one too." |
| 0:02-0:10 | Live demo | Run the meeting summarizer on YOUR real notes. Narrate: "Watch what it does with the action items." Let the room react. |
| 0:10-0:25 | Hands-on | Attendees invoke `first-agent session 1`. Walk the room. Help anyone stuck on setup. Common issue: terminal not finding the skill — check the path. |
| 0:25-0:30 | Debrief | "Raise your hand if that just worked." Ask 2-3 people: "What surprised you?" Plant the seed: "That agent? 20 lines. Text file. Next session, you change it." |

### Talking Points
- **Don't say**: "AI agent" without grounding it. Instead: "A text file with instructions that processes your data."
- **Don't say**: "It's easy." Instead: "It's simpler than you'd expect."
- **Do say**: "Nothing here can break anything. The worst that happens is a weird answer."
- **Do say**: "This isn't a demo. This is your agent, running on your data, right now."

### Common Questions
| Question | Answer |
|----------|--------|
| "Is this connected to the internet?" | "The CLI talks to GitHub's AI models. Your data stays in your session." |
| "Can I use this on confidential data?" | "Check with your IT/security team on data policies. For training, use the sample data or non-sensitive notes." |
| "What if it gets something wrong?" | "It will sometimes. That's why it's a first draft, not a final product. You review and edit. The value is the 90% it gets right in 30 seconds." |
| "Do I need to code?" | "Not a single line. Agents are plain English instructions." |

---

## Session 2: Remix It (30 minutes)

### Pacing Guide

| Time | What's Happening | Your Role |
|------|-------------------|-----------|
| 0:00-0:05 | The reveal | Open the agent file on the projector. "This is the entire agent. 20 lines." Pause. Let them absorb that. Walk through the 4 sections slowly. |
| 0:05-0:10 | Exercise 1 demo | Change a rule live on the projector. Re-run. Show the behavior change. "One line. That's all I changed." |
| 0:10-0:25 | Hands-on exercises | Attendees invoke `first-agent session 2`. Walk the room. The "break it" exercise is where the magic happens — watch for the "oh!" reactions. |
| 0:25-0:28 | Pair share | "Turn to the person next to you. Show them what you changed." This 3 minutes is where energy builds. Let it run if it's flowing. |
| 0:28-0:30 | Bridge | "Next session: you're building from scratch. Homework: think about one repetitive task you'd automate. Bring it with you." |

### Talking Points
- **The key insight**: "Prompts are code. Tiny edits, big behavioral shifts." Say this at least twice.
- **After the break exercise**: "See how it fell apart? That's why structure matters. And now you know how to test any rule — remove it and see what happens."
- **The identity shift moment**: After Exercise 3 (Make It Yours): "You just customized an AI agent. Not by coding — by writing a clear instruction in English. You're already an agent builder. You just don't have your own agent yet. That's next time."

### Common Issues
| Issue | Fix |
|-------|-----|
| Attendee can't see the agent file | Show them the template path in the skill directory |
| "My change didn't do anything" | The change was too subtle. Suggest a more dramatic rule: "Only use 3 words per bullet point" — the change will be obvious |
| Attendee gets ambitious and wants to build | Great sign! Channel it: "Hold that energy for Session 3. That's exactly what we're doing next." |

---

## Session 3: Build It (45 minutes)

### Pacing Guide

| Time | What's Happening | Your Role |
|------|-------------------|-----------|
| 0:00-0:05 | Frame it | "This is it. You're building your own agent today. Not modifying. Yours." Brief show of templates on projector. |
| 0:05-0:30 | Guided build | Attendees invoke `first-agent session 3`. **This is your most active phase.** Walk the room constantly. Help people name their agent. Help them write rules. Unblock anyone stuck on "what should I build?" |
| 0:30-0:45 | Live showcase | **The most important 15 minutes of the entire program.** See showcase guide below. |

### Helping People Pick a Problem

If someone says "I don't know what to build," try these prompts:
- "What did you do last week that felt repetitive?"
- "What task do you dread every Monday morning?"
- "If you could have an assistant handle one thing, what would it be?"
- "What report takes you the longest to write?"

Common answers and templates to suggest:
| Their Problem | Suggest |
|---------------|---------|
| "Meetings take forever to summarize" | Meeting Summarizer |
| "I spend ages writing status updates" | Report Generator |
| "Emails take me too long to draft" | Email Drafter |
| Anything else | Starter template |

### Running the Live Showcase 🎤

This is the moment that makes the program work. Do it well.

**Setup (1 min):**
> "We've got 15 minutes. I want to hear from 4-5 of you. You get 60 seconds each: what's your agent called, what does it do, and show us it running. Who wants to go first?"

**If nobody volunteers:**
Pick someone you saw building something interesting during the guided build. Say: "I saw you building something cool — want to show us?"

**During each demo:**
- Let them talk. Don't interrupt.
- React genuinely. "That's really clever." / "I would use that."
- After each demo, lead the applause. This sounds small. It's not.
- Ask the room: "Who else could use an agent like that?"

**After all demos:**
> "You just watched [N] people build AI agents from scratch. None of them wrote code. All of them solved a real problem. That's what this program is about."

### After Session 3

1. **Immediately**: Share the showcase in your team's Slack/Teams channel. Use the Slack-ready posts the skill generated.
2. **Within 24 hours**: Send a follow-up message: "If you want to build more agents, the skill is still on your machine. Just type `first-agent` to start."
3. **Within 1 week**: Ask attendees: "Are you still using your agent?" Collect testimonials.
4. **Within 2 weeks**: Ask 2-3 enthusiastic attendees if they'd facilitate the next cohort. Give them this guide.

---

## Running the Innovation Spotlight

### After Each Cohort

1. **Collect showcase cards**: The skill generates these automatically during graduation
2. **Pick "Agent of the Week"**: Choose the most creative or impactful agent
3. **Post to Slack/Teams**:

```
⚡ AGENT OF THE WEEK

[Name] from [team] built "[Agent Name]" — an AI agent that
[description]. It took [X] minutes to build and saves roughly
[estimated time] per use.

"[Quote from the builder]"

Want to build your own? Join the next First Agent session.
Sign up: [link]
```

4. **Aggregate gallery**: Run `first-agent showcase` to generate a gallery of all graduates

### Monthly Newsletter Blurb

```
🎓 FIRST AGENT PROGRAM UPDATE

[N] employees have built their first AI agent this month.

Top agents:
• "[Name]" by [Builder] — [description]
• "[Name]" by [Builder] — [description]  
• "[Name]" by [Builder] — [description]

Average build time: [X] minutes
Most popular category: [category]

Next session: [date] — [sign-up link]
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Copilot CLI not installed | Have IT run the pre-install script. This must be done BEFORE the session. |
| Skill not found | Check `~/.copilot/skills/first-agent/SKILL.md` exists. Copy from shared drive if needed. |
| "Model not responding" | Check internet connection. The CLI needs to reach GitHub's API. |
| Attendee way ahead of the group | Great problem. Give them the starter template and let them build a second agent. |
| Attendee stuck and frustrated | Pair them with someone nearby who's doing well. Peer support > facilitator support. |
| Output looks wrong | Check if the agent file has formatting issues. Common: missing line breaks between sections. |
| Someone wants to leave early | The showcase is the anchor. "Stay for the demos — they're the best part." |

---

## The Facilitator Mindset

You're not teaching a tool. You're giving people a new capability. The difference:

- **Teaching a tool**: "Here's how to use the CLI. Here are the commands."
- **Giving a capability**: "You just built something that saves you 20 minutes a week. And you can build more."

The energy you bring is the energy the room will have. If you're excited about what's possible, they will be too. If you treat this like checkbox training, they'll treat it that way too.

The showcase at the end of Session 3 is everything. Protect that time. Don't let exercises run over. The demos are what people remember, what they tell their colleagues about, and what generates demand for the next cohort.

---

*You've got this. The program works. Trust the skill, bring the energy, and let people surprise themselves.*
