# Eval: Headless Mode

**ID:** `headless_mode`
**Pass bar:** 100% of headless error fixtures

## Purpose
Verify that headless mode returns clear, specific errors for missing `--role` or `--task` inputs, and never silently infers or partially executes.

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `mode` | `headless` | ✓ |
| `headless_args` | object | ✓ |
| `actual_output` | string | ✓ |

## Output Contract

```json
{
  "eval_id": "headless_mode",
  "fixture_id": "<id>",
  "pass": true | false,
  "score": 1.0 | 0.0,
  "threshold": 1.0,
  "diff": "",
  "notes": ""
}
```

## Test Cases

### Case 1: Missing `--role`
```
Input: { "task": "Add OAuth to API" }
Expected output contains:
  "ERROR: role is required in headless mode. Provide --role <value>."
Expected NOT to contain: any genome.json output, any brief.md content
```

### Case 2: Missing `--task`
```
Input: { "role": "developer" }
Expected output contains:
  "ERROR: task is required in headless mode. Provide --task <value>."
Expected NOT to contain: any synthesis output
```

### Case 3: Missing both
```
Input: {}
Expected output contains BOTH:
  "ERROR: role is required in headless mode. Provide --role <value>."
  "ERROR: task is required in headless mode. Provide --task <value>."
Expected NOT to contain: any synthesis output
```

### Case 4: Valid headless input
```
Input: { "role": "developer", "task": "Add OAuth2 login" }
Expected: genome.json and brief.md are produced
PASS if artifacts are produced and no ERROR lines in output
```

## Check Logic

```python
def check_headless(args: dict, output: str, fixture_type: str) -> dict:
    if fixture_type == "missing_role":
        expected_error = "ERROR: role is required in headless mode"
        passed = expected_error in output and "genome" not in output.lower()
    elif fixture_type == "missing_task":
        expected_error = "ERROR: task is required in headless mode"
        passed = expected_error in output and "genome" not in output.lower()
    elif fixture_type == "missing_both":
        passed = (
            "ERROR: role is required in headless mode" in output and
            "ERROR: task is required in headless mode" in output and
            "genome" not in output.lower()
        )
    elif fixture_type == "valid":
        passed = "ERROR:" not in output
    else:
        passed = False
    return {"pass": passed, "score": 1.0 if passed else 0.0}
```

## Critical Rules

- **No silent inference.** If `--role` is absent, the skill must NOT guess a role from the task text.
- **No partial execution.** If any required input is missing, the skill must NOT proceed to synthesis.
- **Both errors returned together** when both inputs are missing.
- Error message must contain the exact string `"is required in headless mode"`.

## Failure Behavior

- Output contains partial synthesis alongside error → `pass: false, notes: "Partial execution occurred — synthesis must not run with missing inputs."`
- Error message is vague ("missing argument") without specifying which → `pass: false`.
