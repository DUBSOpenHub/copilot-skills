# Final Exam

Comprehensive assessment covering all CodeQL Mastery modules. 20 questions total.

## Instructions for the Skill

Present the final exam as a formal assessment:
- Show "🛡️ CodeQL Mastery — Final Exam" header
- 20 questions via `ask_user` with 4 choices each
- Track correct/incorrect in `codeql_quiz_results` with module='final-exam'
- Show running score after every 5 questions
- Final score out of 20 with percentage
- Passing: 14/20 (70%) = XP +200, level bump
- Perfect: 20/20 = XP +300, special badge

## Questions

### Module 0 — Pre-Work (2 questions)

1. "What does GHAS stand for?"
   a) GitHub Advanced Security ✅
   b) GitHub Automated Scanning
   c) General Host Application Security
   d) GitHub Alert and Security

2. "CodeQL is free for which type of repository?"
   a) Public repositories ✅
   b) Only enterprise repositories
   c) All repositories regardless of visibility
   d) Only repositories with fewer than 100 contributors

### Module 1 — Vulnerability Fundamentals (3 questions)

3. "In CodeQL's taint tracking, what is a 'sink'?"
   a) Where data is used in a security-sensitive operation ✅
   b) Where data enters the program
   c) A function that validates input
   d) A log statement

4. "Which OWASP category includes SQL injection, XSS, and command injection?"
   a) A03:2021 Injection ✅
   b) A01:2021 Broken Access Control
   c) A07:2021 Authentication Failures
   d) A09:2021 Security Logging

5. "What makes CodeQL different from regex-based linters?"
   a) CodeQL builds a semantic database and tracks data flow through code ✅
   b) CodeQL is faster
   c) CodeQL only works with JavaScript
   d) CodeQL doesn't require any configuration

### Module 2 — Code Scanning Setup (3 questions)

6. "Which query suite has the highest precision (fewest false positives)?"
   a) default ✅
   b) security-extended
   c) security-and-quality
   d) all-queries

7. "What events trigger code scanning in default setup?"
   a) Push, pull request, and weekly schedule ✅
   b) Only manual triggers
   c) Only on release tags
   d) Only nightly builds

8. "What format are code scanning results uploaded in?"
   a) SARIF ✅
   b) JUnit XML
   c) Plain text
   d) Binary protocol buffers

### Module 3 — CodeQL Fundamentals (3 questions)

9. "What does the CodeQL extractor produce?"
   a) A relational database representing the source code ✅
   b) A compiled binary for testing
   c) A PDF report
   d) A Docker container

10. "For compiled languages, how does CodeQL extract code?"
    a) By intercepting the build/compilation process ✅
    b) By reading source files directly like Python
    c) By decompiling binaries
    d) By analyzing git diffs

11. "QL is a dialect of which type of language?"
    a) Datalog — a logic programming language ✅
    b) SQL — a database query language
    c) JavaScript — a scripting language
    d) Assembly — a low-level language

### Module 4 — Writing Queries (3 questions)

12. "In QL, what is a 'predicate'?"
    a) A function that defines a logical relationship ✅
    b) A variable declaration
    c) A database table
    d) An import statement

13. "What `@kind` metadata value enables taint-tracking path visualization?"
    a) path-problem ✅
    b) taint-flow
    c) security-alert
    d) problem

14. "What does the `exists` quantifier check?"
    a) Whether at least one element satisfies a condition ✅
    b) Whether a file exists on disk
    c) Whether the database has been created
    d) Whether a variable is non-null

### Module 5 — Community Packs (2 questions)

15. "Where are CodeQL query packs published?"
    a) GitHub Container Registry (ghcr.io) ✅
    b) npm registry
    c) PyPI
    d) Docker Hub

16. "What file defines a CodeQL pack's metadata?"
    a) qlpack.yml ✅
    b) package.json
    c) Makefile
    d) .codeql-config

### Module 6 — Database Internals (2 questions)

17. "What are 'trap files' in CodeQL?"
    a) Intermediate tuple files generated during code extraction ✅
    b) Files that catch errors in queries
    c) Test fixture files
    d) Configuration files for the extractor

18. "Why must the build succeed for CodeQL to analyze Java code?"
    a) CodeQL intercepts the compiler to capture type information and resolved dependencies ✅
    b) CodeQL runs the compiled program to find runtime errors
    c) Java cannot be parsed without compilation
    d) CodeQL needs the JAR files to run queries

### Module 7 — QL Datalog Deep Dive (2 questions)

19. "What does 'fixpoint computation' mean?"
    a) Rules are applied repeatedly until no new facts are derived ✅
    b) A computation that fixes bugs automatically
    c) A method for debugging queries
    d) A way to optimize database storage

20. "Why does QL enforce 'stratified negation'?"
    a) To prevent circular dependencies that would make queries non-terminating ✅
    b) To make queries run faster
    c) To support multiple programming languages
    d) To enable parallel execution

## Scoring

```
20/20: 🏆 PERFECT SCORE — "CodeQL Master" badge + 300 XP
18-19: 🥇 EXCELLENT — 250 XP
14-17: 🥈 PASSED — 200 XP
10-13: 🥉 CLOSE — 100 XP + "Review modules X, Y, Z"
< 10:  📚 NEEDS REVIEW — 50 XP + "Start from Module 1"
```

Log all answers to `codeql_quiz_results` and emit `exam_passed` or `exam_failed` event to `codeql_dashboard`.
