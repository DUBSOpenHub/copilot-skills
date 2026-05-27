# Example: Ops / Support — Incident Runbook

**Role:** Ops / Support
**Skill:** `decompose` v1.0
**Mode:** Interactive

---

## Session Transcript

### Step 1 — Role Lens

**decompose:** Welcome! What's your role on this work? (Ops/support, developer, PM, creator, designer, researcher, other — or "skip"?)

**User:** Ops / support.

---

### Step 2 — Intent Capture

**decompose:** What are you hoping to accomplish?

**User:** We had a production outage last week — the payment service went down for 47 minutes. I need to write an incident runbook so if it happens again we respond faster and don't improvise.

**decompose:** Got it — you want to document a runbook for payment service outages so your team has a clear response playbook for next time. Let me ask a few questions to build the right structure.

---

### Step 3–4 — Q&A (4 questions)

**Q1:** What triggered last week's outage, and do you know if the same root cause could happen again?

**User:** A third-party payment gateway API started returning 500s. Our service has no circuit breaker, so it cascaded. We've added a circuit breaker but not yet tested it under load.

---

**Q2:** Who needs to be notified during an incident, and in what order? (On-call engineer, support lead, executives, customers?)

**User:** On-call engineer first, then support lead if it's > 5 minutes, then VP Engineering if it's > 15 minutes, then customer comms if it's > 30 minutes.

---

**Q3:** What actions can the on-call engineer take on their own versus what requires additional approval?

**User:** They can restart services, roll back deployments, and enable the circuit breaker. Anything involving external vendor escalation or customer refunds needs approval from the support lead.

---

**Q4:** Is there a defined SLA or recovery time objective (RTO) for the payment service?

**User:** Our SLA with customers is 99.9% uptime per month. Our internal RTO target is 15 minutes.

---

### Step 5 — Blind Spot Engine

1. **ASSUMPTION** — I'm assuming the circuit breaker added post-incident is in production. If it's only in staging, it won't protect the next incident.
   ↳ Confirm circuit breaker is deployed and enabled before finalizing the runbook.
2. **UNKNOWN** — The circuit breaker has not been load-tested. Its behavior under real traffic spikes is unknown.
3. **RISK** — The escalation chain (on-call → support lead → VP) has no documented handoff criteria. Responders may delay escalation or escalate prematurely.
4. **GATE** — Customer comms (>30 min outages) must be approved by the support lead before sending. This is an irreversible external action.
5. **RISK** — If the third-party payment gateway is unresponsive, vendor escalation may require a contract contact not documented anywhere.
   ↳ Add vendor emergency contact to the runbook.

---

### Step 6 — Reflection Mirror (confirmed)

**Goal:** Create a payment service incident response runbook with detection, escalation, mitigation steps, and post-incident review requirements.

Confirmed by user.

---

### Step 7 — genome.json (excerpt)

```json
{
  "genome_id": "ops-incident-runbook-001",
  "schema_version": "1.0",
  "role": "ops",
  "intent": "Create a payment service incident response runbook covering detection, escalation, mitigation, and post-incident review.",
  "nodes": [
    {
      "id": "confirm_circuit_breaker_status",
      "title": "Confirm circuit breaker is deployed and enabled",
      "type": "research",
      "description": "Verify the circuit breaker added post-incident is live in production, not just staging. Document its configuration.",
      "prompt_template": "research",
      "inputs": ["Post-incident change log", "Deployment records"],
      "outputs": ["Circuit breaker status confirmed", "Configuration documented"],
      "acceptance_criteria": [
        "Circuit breaker confirmed live in production",
        "Configuration parameters documented",
        "Load-test plan created or scheduled"
      ],
      "confidence": 0.7,
      "risk": "high",
      "human_decision_gate": false
    },
    {
      "id": "document_escalation_chain",
      "title": "Document escalation criteria and contacts",
      "type": "comms",
      "description": "Write the escalation runbook section: who to contact, when, and via what channel. Include decision criteria for each escalation level.",
      "prompt_template": "comms",
      "inputs": ["Escalation chain confirmed by user", "Vendor emergency contact (TBD)"],
      "outputs": ["Escalation section of runbook"],
      "acceptance_criteria": [
        "All 4 escalation levels documented",
        "Timing thresholds explicit (5/15/30 min)",
        "Contact info verified current"
      ],
      "confidence": 0.85,
      "risk": "medium",
      "human_decision_gate": false
    },
    {
      "id": "unknown_vendor_contact",
      "title": "Unknown: Vendor emergency contact",
      "type": "unknown",
      "description": "The third-party payment gateway vendor emergency escalation contact is not documented. This is required for runbook completeness.",
      "prompt_template": "unknown",
      "inputs": [],
      "outputs": ["Vendor emergency contact added to runbook"],
      "resolution_strategy": "ask_user",
      "confidence": 0.2,
      "risk": "high",
      "human_decision_gate": true
    },
    {
      "id": "draft_runbook",
      "title": "Write complete incident runbook",
      "type": "comms",
      "description": "Assemble all sections into a single incident runbook document: detection signals, initial response, escalation chain, mitigation steps, rollback procedure, customer comms template, post-incident review checklist.",
      "prompt_template": "comms",
      "inputs": [
        "Circuit breaker status confirmed",
        "Escalation chain documented",
        "Vendor contact resolved"
      ],
      "outputs": ["Complete incident runbook document"],
      "acceptance_criteria": [
        "All 7 sections present and complete",
        "Runbook reviewed by on-call engineer and support lead",
        "Stored in team wiki and linked from on-call schedule"
      ],
      "confidence": 0.9,
      "risk": "medium",
      "human_decision_gate": false
    },
    {
      "id": "approve_customer_comms_template",
      "title": "Approve customer-facing comms template",
      "type": "decision",
      "description": "Support lead must approve the customer communication template before it is included in the runbook. Sending to customers is an irreversible external action.",
      "prompt_template": "decision",
      "inputs": ["Draft customer comms template"],
      "outputs": ["Approved template added to runbook"],
      "acceptance_criteria": [],
      "confidence": 0.9,
      "risk": "medium",
      "owner_hint": "support_lead",
      "human_decision_gate": true
    }
  ],
  "edges": [
    { "from": "confirm_circuit_breaker_status", "to": "draft_runbook", "type": "informs" },
    { "from": "document_escalation_chain", "to": "draft_runbook", "type": "blocks" },
    { "from": "unknown_vendor_contact", "to": "document_escalation_chain", "type": "blocks" },
    { "from": "approve_customer_comms_template", "to": "draft_runbook", "type": "blocks" }
  ],
  "handoff": {
    "start_node_id": "unknown_vendor_contact",
    "human_gates": ["unknown_vendor_contact", "approve_customer_comms_template"],
    "do_not_assume": ["Vendor emergency contact is known", "Circuit breaker is production-ready", "Customer comms template is approved"]
  }
}
```
