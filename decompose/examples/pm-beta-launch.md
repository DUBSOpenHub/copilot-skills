# Example: PM — Beta Launch

**Role:** Product Manager / Team Lead
**Skill:** `decompose` v1.0
**Mode:** Interactive

---

## Session Transcript

### Step 1 — Role Lens

**decompose:** Welcome! What's your role on this work? (PM/team lead, developer, designer, creator, ops, researcher, other — or "skip"?)

**User:** Product manager / team lead.

---

### Step 2 — Intent Capture

**decompose:** What are you hoping to accomplish? Rough ideas are fine.

**User:** We need to plan a beta launch for our new project management tool. The team wants to go out in 6 weeks. I need to coordinate engineering, marketing, and support.

**decompose:** Got it — you're planning a 6-week coordinated beta launch across engineering, marketing, and support. Let me ask a few questions to scope the work properly.

---

### Step 3–4 — Q&A (5 questions)

**Q1:** What does a successful beta launch look like for you? For example: 500 active beta users, a specific NPS target, feature coverage milestone, or something else?

**User:** 500 active beta users by end of week 6, NPS above 30, and all P1 bugs resolved.

---

**Q2:** Who is your beta audience — existing customers, a waitlist, invited partners, or open sign-up?

**User:** We have a waitlist of about 800 people. We'll invite from there, not open sign-up.

---

**Q3:** What's the current state of the product — is it feature-complete for beta, or are there known gaps engineering needs to close in these 6 weeks?

**User:** 3 P1 features are still in progress. Engineering says they'll be done in week 3. The rest is feature-complete.

---

**Q4:** What approvals or sign-offs are required before you can invite the waitlist? (Legal review, security audit, executive approval, etc.)

**User:** We need legal to approve the beta terms of service, and our VP of Product has to sign off on the go/no-go decision before invites go out.

---

**Q5:** Is there a rollback or "pause launch" plan if critical issues emerge during beta?

**User:** Not formally. We know we need one but haven't built it yet.

---

### Step 5 — Blind Spot Engine

1. **ASSUMPTION** — I'm assuming the waitlist is deduplicated and segmented (e.g., by use case or company size). If not, invite targeting may be suboptimal.
2. **UNKNOWN** — No formal rollback / pause plan exists. This is a risk for a live product with 500+ beta users.
   ↳ Create an incident response and pause-launch runbook before week 1.
3. **RISK** — 3 P1 features completing in week 3 compresses testing, QA, and onboarding prep into 3 weeks.
4. **RISK** — Beta NPS target of 30 requires active feedback collection. Without a feedback mechanism (surveys, in-app), NPS cannot be measured.
5. **GATE** — VP of Product go/no-go decision must happen before invites go out. This cannot be automated.
6. **GATE** — Legal approval of beta terms of service is required before any user can access the product.

---

### Step 6 — Reflection Mirror (confirmed)

**Goal:** Launch a beta of a new project management tool to 500 waitlist users in 6 weeks, hitting NPS ≥ 30 and P1 bug-free by end of beta.

**Confirmed** by user.

---

### Step 7 — AGENTS.md (excerpt)

```markdown
# AGENTS.md — Beta Launch Execution Pack

## Role
Product Manager / Team Lead

## Goal
Launch a beta of a new project management tool to 500 waitlist users in 6 weeks, with NPS ≥ 30 and all P1 bugs resolved.

## Human Gates
- `legal_tos_approval` — Legal must approve beta terms of service before any user access
- `vp_go_nogo` — VP of Product must approve go/no-go before invites are sent

## Do Not Assume
- Waitlist is properly segmented
- A rollback plan exists (it does not — must be created)
- NPS feedback mechanism is in place

## Start Here
Begin at node `create_rollback_plan` — this is an unresolved risk that must be addressed in week 1.
```
