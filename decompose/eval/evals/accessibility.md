# Eval: Accessibility

**ID:** `accessibility`
**Pass bar:** Rubric score ≥ 0.85 for non-technical fixtures

## Purpose
Verify that `brief.md` is jargon-free and readable by non-technical users for fixtures with non-technical roles. Score using `rubrics/accessibility.md`.

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `brief_md_path` | filepath | ✓ |
| `role` | string | ✓ |

## Output Contract

```json
{
  "eval_id": "accessibility",
  "fixture_id": "<id>",
  "pass": true | false,
  "score": 0.0–1.0,
  "threshold": 0.85,
  "diff": "<criterion-level failures>",
  "notes": ""
}
```

## Check Logic

```
1. If role is NOT in [creator, writer, non-technical, unspecified]:
   → Skip: score: 1.0, pass: true, notes: "N/A — technical role fixture"

2. For non-technical fixtures:
   a. Scan brief.md for jargon terms (see rubrics/accessibility.md jargon list).
   b. Count sentences > 25 words.
   c. Check for passive voice sentence clusters.
   d. Verify all headers are from approved list or jargon-free custom headers.
   e. Scan for internal references (genome.json, nodes, AGENTS.md, etc.).

3. Score per rubric criteria weights.
4. PASS if score >= 0.85.
```

## Jargon Detection (automated)

```python
JARGON_TERMS = [
    "API", "SDK", "JSON", "schema", "DAG", "OAuth", "JWT", "CI/CD",
    "cron", "SMTP", "ASGI", "endpoint", "middleware", "migration",
    "payload", "webhook", "genome", "node", "edge", "prompt_template",
    "acceptance_criteria", "genome.json", "AGENTS.md"
]
INTERNAL_REFS = ["genome.json", "AGENTS.md", "replay.jsonl", "nodes", "edges", "prompt_template"]

def scan_jargon(text: str) -> list:
    findings = []
    for term in JARGON_TERMS:
        # Check for term not followed by an explanation in parens
        pattern = rf"\b{re.escape(term)}\b(?!\s*\()"
        if re.search(pattern, text, re.IGNORECASE):
            findings.append(term)
    return findings

def scan_internal_refs(text: str) -> list:
    return [ref for ref in INTERNAL_REFS if ref in text]
```

## Score Calculation

```
score = 1.0
jargon_count = len(scan_jargon(brief_text))
internal_ref_count = len(scan_internal_refs(brief_text))

score -= min(jargon_count * 0.10, 0.30)   # cap jargon penalty at 0.30
score -= internal_ref_count * 0.15         # internal refs are serious
score -= passive_clusters * 0.05           # per sentence cluster
score -= bad_headers * 0.10               # per non-self-explanatory header
score = max(0.0, score)
```

## Pass Examples

```
Role: creator | Jargon: 0 | Internal refs: 0 | Score: 1.0 → PASS
Role: creator | Jargon: 1 (explained) | Score: 0.95 → PASS
Role: developer | Score: 1.0 (skipped) → PASS (N/A)
```

## Fail Examples

```
Role: creator | Jargon: ["OAuth", "JWT", "ASGI"] unexplained | Score: 0.70 → FAIL
Role: creator | Internal refs: ["genome.json", "AGENTS.md"] | Score: 0.70 → FAIL
```

## Failure Behavior

- `brief.md` not found → `pass: false, score: 0.0, notes: "brief.md missing."`
- Role field absent → default to non-technical scan.
