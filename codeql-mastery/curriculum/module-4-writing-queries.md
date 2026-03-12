# Module 4: Writing Your First CodeQL Query

Hands-on module — the learner writes and understands QL queries.

## QL Language Basics

### Predicates (Functions in QL)

In QL, functions are called **predicates**. They define logical relationships:

```ql
// A predicate that checks if a number is small
predicate isSmall(int n) {
  n in [1 .. 9]
}

// Using it
from int x
where isSmall(x)
select x
// Returns: 1, 2, 3, 4, 5, 6, 7, 8, 9
```

### Classes

QL has classes with **characteristic predicates** (think of them as constructor-filters):

```ql
class SmallNumber extends int {
  SmallNumber() {    // Characteristic predicate — defines membership
    this in [1 .. 9]
  }

  string describe() {
    if this < 5 then result = "low"
    else result = "high"
  }
}

from SmallNumber n
select n, n.describe()
```

### Quantifiers

QL uses logical quantifiers to express complex conditions:

| Quantifier | Meaning | Example |
|-----------|---------|---------|
| `exists` | There is at least one | `exists(Call c \| c.getTarget() = f)` |
| `forall` | For every element | `forall(Parameter p \| p.hasDefault())` |
| `not exists` | There is none | `not exists(Comment c \| c.getLocation() = f.getLocation())` |
| `forex` | For all that exist (and at least one must exist) | `forex(Test t \| t.covers(f) \| t.passes())` |

### Aggregates

| Aggregate | Purpose | Example |
|-----------|---------|---------|
| `count` | Count elements | `count(Function f)` |
| `sum` | Sum values | `sum(int i \| i in [1..10] \| i)` |
| `min` / `max` | Find extremes | `max(Function f \| \| f.getNumberOfParameters())` |
| `avg` | Average | `avg(Function f \| \| f.getNumberOfLines())` |
| `any` | Pick any element | `any(Function f \| f.getName() = "main")` |

## Writing Security Queries

### Pattern 1: Find Dangerous Functions

```ql
import python

from Call c
where c.getFunc().(Name).getId() in ["eval", "exec", "compile"]
select c, "Potentially dangerous function call: " + c.getFunc().(Name).getId()
```

This finds all calls to `eval()`, `exec()`, or `compile()` in Python code.

### Pattern 2: Find Missing Input Validation

```ql
import python
import semmle.python.dataflow.new.DataFlow

from DataFlow::Node source, DataFlow::Node sink
where
  source instanceof RemoteFlowSource and
  sink.asExpr() instanceof Call and
  DataFlow::localFlow(source, sink) and
  not exists(DataFlow::Node sanitizer |
    DataFlow::localFlow(source, sanitizer) and
    DataFlow::localFlow(sanitizer, sink) and
    sanitizer.asExpr() instanceof Call  // Some validation function
  )
select sink, "User input flows to this call without validation"
```

### Pattern 3: Find Hardcoded Secrets

```ql
import python

from Assignment a, StringLiteral s
where
  a.getValue() = s and
  a.getTarget().(Name).getId().regexpMatch("(?i).*(password|secret|token|api_key|apikey).*") and
  s.getText().length() > 5
select a, "Possible hardcoded secret in variable: " + a.getTarget().(Name).getId()
```

## Query Metadata

Every CodeQL query needs metadata comments that control how it appears in GitHub:

```ql
/**
 * @name My custom security query
 * @description Finds X vulnerability pattern
 * @kind problem          // or path-problem for taint tracking
 * @problem.severity error  // error, warning, recommendation
 * @security-severity 8.0   // CVSS-like score (0-10)
 * @precision high           // high, medium, low
 * @id custom/my-query       // unique identifier
 * @tags security            // categorization
 *       external/cwe/cwe-089  // CWE mapping
 */
```

| Metadata | Purpose | Values |
|----------|---------|--------|
| `@kind` | Result type | `problem` (single location), `path-problem` (source-to-sink flow) |
| `@problem.severity` | Alert severity | `error`, `warning`, `recommendation` |
| `@security-severity` | CVSS-like score | 0.0 to 10.0 |
| `@precision` | False positive rate | `high` (few FPs), `medium`, `low` (more FPs) |
| `@tags` | Categories | `security`, `correctness`, `maintainability` |

## Hands-On Exercise

Walk the learner through writing a query step by step:

1. **Start simple**: Find all functions in a Python project
   ```ql
   import python
   from Function f
   select f, f.getName()
   ```

2. **Add a filter**: Find functions with more than 50 lines
   ```ql
   import python
   from Function f
   where f.getMetrics().getNumberOfLines() > 50
   select f, "Long function: " + f.getName() + " (" + f.getMetrics().getNumberOfLines().toString() + " lines)"
   ```

3. **Find a security issue**: Find functions that take user input and call exec
   ```ql
   import python
   from Function f, Call c
   where
     c.getEnclosingFunction() = f and
     c.getFunc().(Name).getId() = "exec"
   select c, "exec() called inside " + f.getName()
   ```

4. **Full taint tracking**: Use the library for complete source-to-sink analysis (shown in Module 3)

## Quiz (5+ questions, use ask_user with 4 choices each)

1. "In QL, what is a 'predicate'?" (A function that defines a logical relationship / A variable type / A database table / A comment annotation)
2. "What does the `exists` quantifier do?" (Checks if at least one element satisfies a condition / Checks if a file exists / Creates a new variable / Imports a library)
3. "What metadata tag controls the severity of a CodeQL alert?" (@problem.severity / @alert-level / @priority / @risk)
4. "Which `@kind` value would you use for a taint-tracking query?" (path-problem / taint-flow / security-alert / data-trace)
5. "What does this QL query find? `from Call c where c.getFunc().(Name).getId() = 'eval' select c`" (All calls to the eval() function / All function definitions / All eval variables / All string literals containing 'eval')
