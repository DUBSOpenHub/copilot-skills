# Module 0: Pre-Work Review

This is the **Pre-Module** — cover these preparation steps BEFORE starting the CodeQL workshop.

## 🎯 CTA: Review Pre-Work Instructions

Before diving into CodeQL, the learner should confirm they've completed these preparation steps:

### Pre-Work Checklist

| Step | What to Do | Why It Matters |
|------|-----------|---------------|
| GitHub Account | Ensure you have an active GitHub account with access to a repository | CodeQL runs on GitHub repos |
| Repository Access | Have a repo ready (public or private with GHAS) | You'll activate code scanning on it |
| Codespace or Local Setup | Access to GitHub Codespaces or local dev environment | For running CodeQL queries |
| Basic Git Knowledge | Comfortable with clone, commit, push, pull | CodeQL integrates with Git workflows |
| Security Awareness | Read about OWASP Top 10 at a high level | Context for what CodeQL detects |

### What is CodeQL?

CodeQL is GitHub's **semantic code analysis engine**. Unlike regex-based linters, CodeQL:
- Builds a **database** from your source code (an abstract representation of the code's structure)
- Lets you write **queries** against that database using a purpose-built language called QL
- Finds vulnerabilities by modeling how data flows through your code
- Powers GitHub's **code scanning** feature — the same engine behind thousands of security alerts

### Why This Matters for Your Organization

- CodeQL catches vulnerabilities **before** they reach production
- It's free for public repositories and included with GitHub Advanced Security (GHAS) for private repos
- The SOSS Fund (Securing Open Source Software) initiative drives adoption of tools like CodeQL across critical open-source projects
- Learning CodeQL means you can write **custom queries** for your organization's specific security needs

### Key Vocabulary

| Term | Definition |
|------|-----------|
| **CodeQL** | GitHub's semantic code analysis engine |
| **Code Scanning** | GitHub feature that runs CodeQL (and other tools) on your code |
| **GHAS** | GitHub Advanced Security — enterprise security features |
| **QL** | The query language used to write CodeQL queries (a datalog dialect) |
| **CodeQL Database** | A relational representation of your source code |
| **Query Pack** | A collection of CodeQL queries bundled for distribution |
| **SARIF** | Static Analysis Results Interchange Format — how results are reported |
| **Default Setup** | GitHub's one-click CodeQL configuration |

## Verification

To verify pre-work completion, ask the learner:
1. "Do you have a GitHub repository ready for code scanning?" (Yes/No)
2. "Have you reviewed the OWASP Top 10 categories?" (Yes/No)
3. Quick quiz: "What does CodeQL stand for?" (Choices: Code Query Language, a query language for code analysis / A code linter like ESLint / A GitHub Actions workflow / A type of database)

If they answer the quiz correctly + confirm at least 1 of the 2 prep questions, mark CTA `pre-work-review` as done.

## Quiz (5 questions, use ask_user with 4 choices each)

Focus on: "What is the purpose of [pre-work step]?" and "Which of these best describes CodeQL?"
