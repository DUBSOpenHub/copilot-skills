# Eval: Schema Validity

**ID:** `schema_validity`
**Pass bar:** 100% of all fixtures

## Purpose
Verify that `genome.json` for each fixture validates against `genome.schema.json` (JSON Schema Draft 7).

## Inputs

| Input | Type | Required |
|---|---|---|
| `fixture_id` | string | ✓ |
| `genome_json_path` | filepath | ✓ |
| `schema_path` | filepath | ✓ (`schemas/genome.schema.json`) |

## Output Contract

```json
{
  "eval_id": "schema_validity",
  "fixture_id": "<id>",
  "pass": true | false,
  "score": 1.0 | 0.0,
  "threshold": 1.0,
  "diff": "<validation errors if any>",
  "notes": ""
}
```

## Check Logic

```
1. Load genome.json from fixture output directory.
2. Load genome.schema.json from schemas/.
3. Run JSON Schema Draft 7 validation.
4. PASS if zero validation errors.
5. FAIL if any validation error; list all errors in `diff`.
```

## Validation Command (Python)

```python
import json
import jsonschema

with open("schemas/genome.schema.json") as f:
    schema = json.load(f)

with open(f"eval/fixtures/{fixture_id}/golden/genome.json") as f:
    genome = json.load(f)

try:
    jsonschema.validate(instance=genome, schema=schema,
                        cls=jsonschema.Draft7Validator)
    result = {"pass": True, "score": 1.0, "diff": ""}
except jsonschema.ValidationError as e:
    result = {"pass": False, "score": 0.0, "diff": str(e.message)}
```

## Pass Criteria

- Zero validation errors from JSON Schema Draft 7 validator.
- All required top-level fields present.
- All node objects conform to Node schema.
- All edge objects conform to Edge schema.
- All enum values are valid.

## Fail Examples

```
{"pass": false, "diff": "'research' is not of type 'array' (nodes[0].inputs)"}
{"pass": false, "diff": "'unknown_node_type' is not one of ['research', 'decision', ...]"}
{"pass": false, "diff": "'handoff' is a required property"}
```

## Guardrails

- Score is binary.
- Do not apply DAG semantic checks here — those are in `dag_validity.md`.
- If `genome.json` file does not exist for a fixture → `pass: false, score: 0.0, notes: "genome.json not found at expected path."`
