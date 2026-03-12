# Module 5: Community Packs

This module covers CodeQL query packs and the community ecosystem.

## 🎯 CTA: Review Community Packs

The learner must explore and review community-contributed CodeQL query packs.

## What Are Query Packs?

CodeQL **query packs** are collections of queries bundled for easy distribution and use. They're published to the GitHub Container Registry and can be used in code scanning configurations.

### Pack Types

| Pack Type | Purpose | Example |
|-----------|---------|---------|
| **Query Pack** | Contains `.ql` query files | `codeql/python-queries` |
| **Library Pack** | Contains reusable `.qll` library files | `codeql/python-all` |
| **Model Pack** | Contains data flow models for frameworks | Custom framework support |

## Official GitHub Query Packs

These are maintained by GitHub's CodeQL team:

| Pack Name | Language | Queries | Focus |
|-----------|----------|---------|-------|
| `codeql/javascript-queries` | JavaScript/TypeScript | 200+ | Security + quality |
| `codeql/python-queries` | Python | 150+ | Security + quality |
| `codeql/java-queries` | Java/Kotlin | 200+ | Security + quality |
| `codeql/cpp-queries` | C/C++ | 150+ | Security + quality |
| `codeql/csharp-queries` | C# | 150+ | Security + quality |
| `codeql/go-queries` | Go | 100+ | Security + quality |
| `codeql/ruby-queries` | Ruby | 80+ | Security + quality |
| `codeql/swift-queries` | Swift | 50+ | Security + quality |

### Query Suites Within Packs

Each language pack includes multiple **query suites** (subsets of queries):

| Suite | What It Includes | Use When |
|-------|-----------------|----------|
| `default` | High-precision security queries | Starting out — lowest false positives |
| `security-extended` | Default + medium-precision security | Want broader coverage |
| `security-and-quality` | All security + code quality queries | Want comprehensive analysis |

## Community Packs

Beyond GitHub's official packs, the community contributes specialized packs:

### Where to Find Community Packs

1. **GitHub Container Registry**: Search `ghcr.io` for CodeQL packs
2. **GitHub Topics**: Search for `codeql` topic on GitHub repositories
3. **CodeQL Community Packs GitHub Org**: [github.com/GitHubSecurityLab](https://github.com/GitHubSecurityLab)
4. **GitHub Security Lab**: Research and advanced queries

### Notable Community Contributions

| Source | Focus | URL |
|--------|-------|-----|
| GitHub Security Lab | Advanced security research queries | `github/securitylab` |
| CodeQL Community Packs | Community-maintained query collections | Various repos |
| Trail of Bits | Custom security queries | `trailofbits/codeql-queries` |
| LGTM Community | Historical queries (pre-GitHub acquisition) | Archived |

### Using Community Packs in Code Scanning

**In Default Setup:** You can add additional query packs to your default setup:
1. Go to Settings → Code security → Code scanning
2. Edit the default setup
3. Add pack references in the format: `owner/pack-name@version`

**In Advanced Setup (workflow YAML):**
```yaml
- name: Initialize CodeQL
  uses: github/codeql-action/init@v3
  with:
    languages: python
    packs: |
      codeql/python-queries:security-extended
      my-org/custom-security-pack
```

## Creating Your Own Query Pack

### Pack Structure

```
my-query-pack/
├── qlpack.yml           # Pack metadata
├── queries/
│   ├── MyQuery1.ql      # Query files
│   └── MyQuery2.ql
├── lib/
│   └── MyLibrary.qll    # Reusable library code
└── test/
    └── MyQuery1/
        ├── test.py      # Test code
        └── MyQuery1.expected  # Expected results
```

### qlpack.yml

```yaml
name: my-org/my-security-pack
version: 1.0.0
description: Custom security queries for my organization
dependencies:
  codeql/python-all: "*"
defaultSuiteFile: suite.qls
```

### Publishing

```bash
# Install CodeQL CLI
gh extension install github/gh-codeql

# Create a pack
codeql pack init my-org/my-pack

# Add queries...

# Test your pack
codeql test run test/

# Publish to GitHub Container Registry
codeql pack publish
```

## CTA Verification

To verify the learner has reviewed community packs, ask them to:
1. Name at least 2 community packs or query suites they explored
2. Explain the difference between `default` and `security-extended` suites
3. Describe one use case where a community pack would be more useful than the default pack

Cross-reference their answers with known packs. If they can name real packs and explain the suite differences, mark CTA as verified.

## Quiz (5+ questions, use ask_user with 4 choices each)

1. "What is a CodeQL query pack?" (A collection of QL queries bundled for distribution / A ZIP file of source code / A GitHub Action / A Docker container)
2. "Which query suite has the lowest false positive rate?" (default / security-extended / security-and-quality / all-queries)
3. "Where are CodeQL packs published?" (GitHub Container Registry / npm / PyPI / Maven Central)
4. "What file defines a CodeQL pack's metadata?" (qlpack.yml / package.json / Dockerfile / setup.py)
5. "What is the difference between a query pack and a library pack?" (Query packs contain .ql files to run; library packs contain reusable .qll code / They are the same thing / Query packs are for JavaScript only / Library packs run faster)
