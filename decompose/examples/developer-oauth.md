# Example: Developer — OAuth2 Integration

**Role:** Developer
**Skill:** `decompose` v1.0
**Mode:** Interactive

---

## Session Transcript

### Step 1 — Role Lens

**decompose:** Welcome! Before we dive in, I want to understand your perspective so I can ask the most useful questions.

What's your role on this work? (Developer, PM, designer, creator, ops, researcher, other — or "skip"?)

**User:** Developer.

---

### Step 2 — Intent Capture

**decompose:** What would you like to accomplish? Plain language is fine.

**User:** I need to add GitHub OAuth login to our Python API. We currently use JWT auth and want to replace it.

**decompose:** Got it — you want to replace JWT auth with GitHub OAuth in a Python API. That's a well-scoped change. Let me ask a few questions to nail down the details.

---

### Step 3–4 — Understanding Meter + Q&A

**📊 Understanding Meter: 35%**
✅ I know: Python API, GitHub OAuth login, replace JWT auth
❓ I don't yet know: framework, success criteria, timeline, test coverage, approver for JWT removal
💡 Most useful next question: What does "done" look like for this change?

**Q1:** What does a successful OAuth integration look like for you? For example: users can log in with GitHub, existing sessions still work during a cutover window, all tests pass, deployed to staging?

**User:** Users can log in with GitHub, JWT is gone, all tests pass, and it's deployed to staging. We'll handle production separately.

---

**📊 Understanding Meter: 52%**
✅ I know: GitHub OAuth, JWT replacement, staging deploy, all tests pass as acceptance bar
❓ I don't yet know: framework, timeline, test coverage baseline, who approves JWT removal
💡 Most useful next question: What Python web framework are you using?

**Q2:** Which Python web framework is your API built on — FastAPI, Flask, Django, something else?

**User:** FastAPI.

---

**📊 Understanding Meter: 65%**
✅ I know: FastAPI, GitHub OAuth, JWT replaced, staging target, 2-week ballpark
❓ I don't yet know: test coverage on auth, OAuth library preference, who approves JWT removal
💡 Most useful next question: What's your timeline?

**Q3:** What's your timeline for this? And do you have a preferred OAuth library (e.g., authlib, fastapi-users), or should we evaluate options first?

**User:** ~2 weeks. No strong library preference — let's pick the best one.

---

**📊 Understanding Meter: 75%**
✅ I know: FastAPI, GitHub OAuth, 2-week timeline, library TBD, staging first, JWT replaced
❓ I don't yet know: existing auth test coverage, approver for JWT cutover, rollback plan
💡 Most useful next question: Who needs to approve the JWT removal?

**Q4:** When the time comes to remove the JWT auth system, does that require sign-off from anyone — a tech lead, security team, or is it your call?

**User:** I need my tech lead to sign off before we remove JWT. It's company policy for any auth changes.

---

**📊 Understanding Meter: 83%**
✅ I know: FastAPI, GitHub OAuth, 2-week timeline, library TBD, staging first, JWT replaced, tech lead approves JWT removal
❓ I don't yet know: existing test coverage, rollback plan if staging fails

I feel like I have a solid plan. Want one more question, or should we move forward?

**User:** One more question is fine.

---

**Q5:** Do you know the current test coverage for your auth module? And do you have a rollback plan if OAuth breaks on staging?

**User:** Coverage is probably around 60%. No rollback plan yet — that's a gap I know about.

---

### Step 5 — Blind Spot Engine

🔍 Before I finalize your plan:

1. **ASSUMPTION** — I'm assuming your FastAPI app uses a standard ASGI setup (Starlette-based). If you're using an unusual middleware stack, some OAuth library integrations may need adjustment.

2. **UNKNOWN** — Current test coverage for the auth module is ~60% (self-reported). Missing coverage could hide regressions during the JWT → OAuth migration.
   ↳ Assess and improve auth test coverage before or alongside the OAuth implementation.

3. **RISK** — Removing JWT auth invalidates all active JWT sessions. Users mid-session will be forcibly logged out if there's no migration window.
   ↳ Plan a brief maintenance window or dual-auth period before cutover.

4. **RISK** — No rollback plan defined. If OAuth fails on staging, reverting to JWT may require re-issuing tokens.
   ↳ Create a rollback runbook before the JWT removal gate.

5. **GATE** — JWT removal requires explicit tech lead sign-off per company policy. No agent or automated process may proceed past this point without human approval.

---

### Step 6 — Reflection Mirror

Here's what I'm planning to build from:

**Goal:** Add GitHub OAuth login to your FastAPI Python API, replacing JWT auth, targeting staging deployment within two weeks.

**What I know:**
- FastAPI framework
- GitHub is the OAuth provider
- JWT auth will be replaced (not kept alongside OAuth)
- Target: staging first, then production (separately)
- Two-week timeline
- Library to be selected (research step first)
- Tech lead must approve JWT removal per company policy
- ~60% current test coverage on auth module

**What I'm not sure about:**
- Rollback plan if staging OAuth fails
- Exact test gap in auth module

**Things to watch:**
- ASSUMPTION: Standard FastAPI/ASGI setup
- UNKNOWN: Auth test coverage gaps not fully mapped
- RISK: Active JWT sessions will be invalidated on cutover
- RISK: No rollback plan defined yet
- GATE: Tech lead must approve JWT removal before that step executes

Does this match what you have in mind?

**User:** Yes, confirmed.

---

### Step 7 — Artifacts (genome.json)

```json
{
  "genome_id": "developer-oauth-001",
  "schema_version": "1.0",
  "role": "developer",
  "intent": "Add GitHub OAuth login to a FastAPI Python API, replacing JWT auth, targeting staging deployment within two weeks.",
  "nodes": [
    {
      "id": "research_oauth_library",
      "title": "Research and select OAuth library",
      "type": "research",
      "description": "Evaluate authlib, fastapi-users, and python-social-auth for GitHub OAuth2 support with FastAPI. Recommend one with rationale.",
      "prompt_template": "research",
      "inputs": ["FastAPI framework", "GitHub OAuth2 requirement"],
      "outputs": ["Selected library with rationale", "Compatibility confirmation"],
      "acceptance_criteria": [
        "At least 2 libraries evaluated",
        "GitHub OAuth2 compatibility confirmed for chosen library",
        "Integration complexity with FastAPI documented"
      ],
      "assumptions": ["FastAPI ASGI setup is standard"],
      "unknowns": [],
      "confidence": 0.9,
      "risk": "low",
      "human_decision_gate": false
    },
    {
      "id": "assess_auth_coverage",
      "title": "Assess auth module test coverage",
      "type": "research",
      "description": "Map current test coverage of the auth module. Identify gaps that could hide regressions during JWT → OAuth migration.",
      "prompt_template": "research",
      "inputs": ["Current codebase", "~60% coverage estimate"],
      "outputs": ["Coverage report", "List of untested auth paths"],
      "acceptance_criteria": [
        "Coverage report generated",
        "Untested auth paths identified",
        "Risk assessment of gaps documented"
      ],
      "parallelizable_with": ["research_oauth_library"],
      "assumptions": [],
      "unknowns": [],
      "confidence": 0.85,
      "risk": "medium",
      "human_decision_gate": false
    },
    {
      "id": "implement_oauth_endpoints",
      "title": "Implement GitHub OAuth login endpoints",
      "type": "code_change",
      "description": "Add /auth/github and /auth/github/callback endpoints. Update session management. Do not remove JWT endpoints in this step.",
      "prompt_template": "code_change",
      "inputs": ["Selected OAuth library", "FastAPI app structure", "GitHub OAuth app credentials (runtime)"],
      "outputs": ["/auth/github redirect endpoint", "/auth/github/callback session endpoint", "Updated session model", "Integration tests"],
      "acceptance_criteria": [
        "User can initiate GitHub OAuth via /auth/github",
        "Callback stores GitHub user ID in session",
        "Existing JWT endpoints not broken",
        "Integration tests pass"
      ],
      "assumptions": [],
      "unknowns": ["Whether existing session model can be extended or must be replaced"],
      "confidence": 0.85,
      "risk": "medium",
      "human_decision_gate": false
    },
    {
      "id": "risk_session_invalidation",
      "title": "Risk: JWT session invalidation on cutover",
      "type": "risk",
      "description": "When JWT auth is removed, all active JWT sessions are invalidated. Plan a migration window or dual-auth period.",
      "prompt_template": "risk",
      "inputs": ["Implementation complete", "Estimated active sessions"],
      "outputs": ["Rollback runbook", "Migration window plan"],
      "acceptance_criteria": [
        "Rollback procedure documented",
        "Migration window timing agreed"
      ],
      "assumptions": [],
      "unknowns": ["Number of active sessions at cutover"],
      "confidence": 0.75,
      "risk": "high",
      "human_decision_gate": false
    },
    {
      "id": "approve_jwt_removal",
      "title": "Tech lead approves JWT auth removal",
      "type": "decision",
      "description": "Per company policy, tech lead must explicitly approve removal of the JWT auth system before cutover. OAuth must be verified on staging first.",
      "prompt_template": "decision",
      "inputs": ["OAuth verified on staging", "Rollback runbook ready", "All tests passing"],
      "outputs": ["Approval granted or denied"],
      "acceptance_criteria": [],
      "assumptions": [],
      "unknowns": [],
      "confidence": 0.95,
      "risk": "high",
      "owner_hint": "tech_lead",
      "human_decision_gate": true
    },
    {
      "id": "remove_jwt_auth",
      "title": "Remove JWT auth system",
      "type": "code_change",
      "description": "Remove JWT middleware, token issuance, and validation endpoints after tech lead approval. Update all tests.",
      "prompt_template": "code_change",
      "inputs": ["Tech lead approval confirmed", "Rollback plan ready"],
      "outputs": ["JWT code removed", "Tests updated", "Staging redeployed"],
      "acceptance_criteria": [
        "JWT endpoints return 404 or 401",
        "GitHub OAuth login still functional",
        "All tests pass with 0 failures",
        "Staging deploy successful"
      ],
      "assumptions": [],
      "unknowns": [],
      "confidence": 0.9,
      "risk": "high",
      "human_decision_gate": false
    }
  ],
  "edges": [
    { "from": "research_oauth_library", "to": "implement_oauth_endpoints", "type": "blocks" },
    { "from": "assess_auth_coverage", "to": "implement_oauth_endpoints", "type": "informs" },
    { "from": "implement_oauth_endpoints", "to": "risk_session_invalidation", "type": "informs" },
    { "from": "implement_oauth_endpoints", "to": "approve_jwt_removal", "type": "blocks" },
    { "from": "risk_session_invalidation", "to": "approve_jwt_removal", "type": "informs" },
    { "from": "approve_jwt_removal", "to": "remove_jwt_auth", "type": "blocks" }
  ],
  "assumptions": ["FastAPI ASGI setup is standard", "GitHub OAuth app will be created before implementation"],
  "unknowns": ["Existing session model extensibility", "Active session count at cutover time"],
  "blind_spots": [
    { "text": "Standard FastAPI/ASGI assumed", "classification": "assumption" },
    { "text": "Auth module test coverage has ~40% gap", "classification": "unknown" },
    { "text": "JWT session invalidation on cutover", "classification": "risk" },
    { "text": "No rollback plan defined yet", "classification": "risk" },
    { "text": "JWT removal requires tech lead sign-off", "classification": "gate" }
  ],
  "open_questions": [
    "Does the existing session model need to be replaced or can it be extended?",
    "What is the planned cutover window timing?"
  ],
  "meta": {
    "created_at": "2024-01-15T11:00:00Z",
    "skill_version": "1.0",
    "session_id": "sess-developer-oauth-001",
    "questions_asked": 5,
    "meter_pct_at_close": 83
  },
  "handoff": {
    "start_node_id": "research_oauth_library",
    "human_gates": ["approve_jwt_removal"],
    "do_not_assume": ["Tech lead approval for JWT removal", "Session model replacement vs extension", "Active session count at cutover"]
  }
}
```
