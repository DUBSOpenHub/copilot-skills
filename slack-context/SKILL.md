---
name: slack-context
description: >
  Use when the user asks to "fetch context from Slack", "read this Slack thread",
  "get requirements from Slack", "extract Slack conversation", or provides a Slack
  permalink. Uses `gh slack read` — no background scraping, no MCP server.
  Always warn about security and request confirmation before using Slack data.
---

# Slack Context — Read Slack Threads On Demand

Retrieves Slack thread content using `gh slack read` for specific, user-initiated
requests. No background scraping. No persistent MCP connection. Every fetch
requires explicit user consent.

## ⚠️ Security Requirements

**BEFORE fetching any Slack content:**

1. Display this warning:
```
⚠️  SECURITY WARNING
You're about to fetch Slack messages that may contain:
• Personal information (PII)
• Confidential business information
• Private conversations
• Credentials or secrets

Continue? (y/n)
```

2. After fetching, display content and ask for confirmation before using it.
3. Remind the user to redact sensitive data.

## When to Use

**Trigger phrases:**
- "Fetch context from this Slack thread: [url]"
- "Read this Slack conversation and help me with what we discussed"
- "Get the requirements from this Slack chat"
- "Use this Slack thread as context"

**Appropriate:**
- Technical implementation discussions
- Feature requests in team channels
- Bug reports with reproduction steps
- Open design discussions

**Refuse these:**
- Customer support conversations
- Private DMs (unless explicit permission)
- HR or personnel matters
- Security incident details
- Anything marked confidential

## Process

### Step 1: Extract Slack URL
Validate the permalink format:
```
https://[workspace].slack.com/archives/[CHANNEL_ID]/p[TIMESTAMP]
```

### Step 2: Get User Consent
Always show the security warning. Stop if user declines.

### Step 3: Fetch Thread
```bash
gh slack read <slack-permalink>
```

### Step 4: Display and Confirm
Show the full content. Ask the user to review for sensitive info.
Only proceed after explicit confirmation.

### Step 5: Summarize and Use
Extract key technical details. Focus on decisions and requirements,
not opinions about people. Reference the Slack URL for attribution.

## Error Handling

**Extension not installed:**
```bash
gh extension install rneatherway/gh-slack
```

**Not authenticated:**
```bash
eval $(gh slack auth -t github)
```

**Invalid URL:**
Must match `slack.com/archives/C[A-Z0-9]*/p[0-9]*`

## Boundaries

**Will:**
- Fetch specific Slack threads via `gh slack read`
- Always warn and request confirmation
- Summarize technical discussions
- Extract requirements and decisions

**Will not:**
- Scrape or search Slack broadly
- Run as a background MCP server
- Fetch without explicit user consent
- Store or cache Slack content
- Override a user's "no"
