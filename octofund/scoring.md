# OctoFund Scoring Rubric

This file is the single source of truth for how OctoFund scores projects.
**Read-only at runtime — the skill references this but never modifies it.**

---

## Dimensions

### Impact Score (0–100) — Weight: 60%

Measures how widely a project is depended upon.

**Calculation:** Normalize the project's dependents count against the highest in the evaluated set.

```
impact_score = (project_dependents / max_dependents_in_set) × 100
```

| Dependents | Typical Score Range |
|------------|:-------------------:|
| >100K repos | 80–100 |
| 10K–100K repos | 40–80 |
| 1K–10K repos | 10–40 |
| <1K repos | 0–10 |

**Data sources (in priority order):**
1. GitHub Dependency Graph API (`gh api repos/{owner}/{repo}`)
2. `dependents_estimate` field in `critical-projects.json`
3. If neither available: `⚠️ unavailable` — do not estimate

---

### Funding Gap Score (0–100) — Weight: 40%

Measures how underfunded a project is relative to its usage. More absent signals = higher gap = more need.

**Calculation:** Sum points for each absent or weak funding signal.

| Signal | Absent | Present but $0 | <$1K/mo | >$1K/mo |
|--------|:------:|:--------------:|:-------:|:-------:|
| GitHub Sponsors | +20 | — | +10 | +0 |
| OpenCollective | +15 | — | +5 | +0 |
| FUNDING.yml | +15 | +5 | — | — |
| Tidelift | +10 | — | — | +0 |
| Security posture | +10 | +5 | — | +0 |
| Monthly funding est. | +30 ($0) | — | +10 (<$1K) | +0 (>$1K) |

**Maximum possible gap score:** 100
**Minimum possible gap score:** 0 (all signals active, well-funded)

**Data sources:**
- GitHub Sponsors: GraphQL API (`hasSponsorsListing`)
- FUNDING.yml: `gh api repos/{owner}/{repo}/contents/.github/FUNDING.yml`
- OpenCollective: `https://opencollective.com/{project}/members/all.json`
- Tidelift: HTTP status check on listing page
- Security posture: `SECURITY.md` presence + vulnerability alerts enabled

---

## Combined Score

```
combined = (impact_score × 0.6) + (gap_score × 0.4)
```

---

## Hidden Pillar Boost 🔥

Projects with **≤3 active maintainers** receive a +10 bonus to their combined score (capped at 100).

**Rationale:** A project with 1 maintainer and 50K dependents represents a higher funding priority than a project with 20 maintainers and 200K dependents. The maintainer count corrects for single-point-of-failure risk that raw dependency counts miss.

**Active maintainer definition:** Contributors with ≥1 commit in the last 12 months.

**Data source:**
1. `gh api repos/{owner}/{repo}/contributors` — filter by recent activity
2. `maintainers_estimate` field in `critical-projects.json` as fallback

---

## Allocation Algorithm

### Step 1: Exclude
Remove projects scoring below 70.

### Step 2: Apply overrides
If the user pinned any project amounts, allocate those first. Remaining budget = total budget − sum of overrides.

### Step 3: Proportional distribution
Distribute remaining budget across non-pinned, non-excluded projects proportionally to their combined score.

```
project_share = (project_score / sum_of_all_scores) × remaining_budget
```

### Step 4: Enforce floor and ceiling
- **Floor:** $500 minimum per funded project
- **Ceiling:** 30% of total budget maximum per project (including overrides)
- If floor enforcement pushes total above budget, remove the lowest-scoring project and redistribute
- If ceiling enforcement leaves excess, redistribute to remaining projects

### Step 5: Round
Round to nearest $100. Show any unallocated remainder explicitly.

---

## Emoji Legend (Locked)

| Emoji | Meaning |
|:-----:|---------|
| ❌ | Not present / not enrolled |
| 🟡 | Present but inactive ($0) |
| 🟠 | Active, <$1K/mo |
| 🟢 | Active, >$1K/mo |
| 🔥 | Hidden Pillar (≤3 maintainers) |
| ⚠️ | Data unavailable |
