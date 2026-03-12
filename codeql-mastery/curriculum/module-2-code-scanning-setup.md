# Module 2: Code Scanning Setup

This module covers **activating GitHub code scanning** — the primary CTA for this training.

## 🎯 CTA: Activate Code Scanning

This is a CRITICAL call-to-action. The learner must activate code scanning on a real repository.

## What is GitHub Code Scanning?

Code scanning is a GitHub feature that uses CodeQL (and optionally third-party tools) to analyze your code for security vulnerabilities and coding errors. It:

- Runs automatically on push and pull request events
- Creates alerts directly in your repository's Security tab
- Shows inline annotations on pull requests
- Supports 9+ programming languages
- Is **free for public repositories**
- Available via **GitHub Advanced Security (GHAS)** for private repos

## Default Setup vs. Advanced Setup

| Feature | Default Setup | Advanced Setup |
|---------|--------------|---------------|
| Configuration | One-click in Settings | Custom workflow YAML |
| Languages | Auto-detected | Manually specified |
| Query packs | Default + extended | Any packs you choose |
| Schedule | Push + PR + weekly | Fully customizable |
| Best for | Getting started quickly | Custom security policies |

## How to Activate Default Setup

### Step-by-step:

1. **Navigate** to your repository on GitHub
2. Go to **Settings** → **Code security and analysis**
3. Find **Code scanning** section
4. Click **Set up** → **Default**
5. Review the detected languages
6. Click **Enable CodeQL**

That's it! GitHub will:
- Detect your repository's languages automatically
- Configure CodeQL to run on push, PR, and weekly schedule
- Start the first scan immediately
- Show results in the **Security** tab → **Code scanning alerts**

### What Happens Behind the Scenes

When you enable default setup, GitHub:
1. Creates an **Actions workflow** that runs CodeQL
2. On each trigger (push/PR), it:
   a. Checks out your code
   b. **Builds a CodeQL database** (extracts code into a relational format)
   c. Runs the **default query suite** against the database
   d. Uploads results in **SARIF format**
   e. Creates alerts for any findings

### Configuring Default Setup — Key Details

From the [official documentation](https://docs.github.com/en/code-security/code-scanning/enabling-code-scanning/configuring-default-setup-for-code-scanning):

| Setting | Default Value | Can Change? |
|---------|-------------|------------|
| Languages | Auto-detected | Yes — toggle languages on/off |
| Query suite | `default` | Yes — switch to `security-extended` or `security-and-quality` |
| Events | push, pull_request, schedule | No (fixed in default setup) |
| Schedule | Weekly | No (fixed in default setup) |
| Runner | GitHub-hosted | Yes — can use self-hosted |

**Query Suite Options:**
- `default`: Core security queries (recommended starting point)
- `security-extended`: Additional security queries with lower precision
- `security-and-quality`: Security + code quality queries

## Verification

### Automated Verification (via `gh` CLI)

To check if code scanning is active on a repository:

```bash
# Check default setup state
gh api repos/{owner}/{repo}/code-scanning/default-setup --jq '.state'
# Expected: "configured"

# Check for recent analyses
gh api repos/{owner}/{repo}/code-scanning/analyses --jq '.[0] | {tool: .tool.name, created: .created_at, status: .results_count}'

# List any alerts
gh api repos/{owner}/{repo}/code-scanning/alerts --jq '.[].rule.description' | head -5
```

### Manual Verification

Ask the learner:
1. "Go to your repo → Security tab → Code scanning. Do you see the CodeQL tool listed?" (Yes/No)
2. "What is the status of your most recent code scanning analysis?" (Completed / In progress / Not started / Error)

### CTA Completion Criteria

Mark `activate-code-scanning` CTA as **verified** when:
- `gh api` returns state = "configured" for the specified repo, OR
- Learner confirms code scanning is visible in their Security tab AND can report the analysis status

## 🎯 CTA: Read Default Setup Instructions

After activating, the learner should read the full documentation. Verify with a quiz:

1. "Which query suites are available in default setup?" (default, security-extended, security-and-quality / basic, advanced, premium / low, medium, high / standard, custom, enterprise)
2. "What events trigger code scanning in default setup?" (Push, PR, and weekly schedule / Only manual triggers / Only on release tags / Only on main branch commits)
3. "What format are code scanning results uploaded in?" (SARIF / JSON / CSV / XML)

Score 2/3+ to verify this CTA.

## Troubleshooting

| Issue | Solution |
|-------|---------|
| "Code scanning not available" | Repo needs GHAS license (private repos) or must be public |
| "No languages detected" | Ensure repo has source code (not just configs/docs) |
| "Analysis failed" | Check Actions tab for workflow errors; common: build failures for compiled languages |
| "Too many alerts" | Start with `default` query suite, address high-severity first |

## Quiz (5+ questions, use ask_user with 4 choices each)

Focus on setup process, configuration options, and what happens when code scanning runs.
