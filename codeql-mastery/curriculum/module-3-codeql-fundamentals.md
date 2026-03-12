# Module 3: CodeQL Fundamentals

How CodeQL actually works — the engine behind code scanning.

## The CodeQL Pipeline

```
Source Code → Extractor → CodeQL Database → Queries → SARIF Results → Alerts
    ↓              ↓              ↓              ↓           ↓
 Your repo    Language-    Relational      QL files    Security tab
              specific     representation  (.ql)      on GitHub
              parser       of your code
```

## Step 1: Code Extraction

CodeQL doesn't analyze source code directly. It first **extracts** your code into a structured database.

### How Extraction Works

For each supported language, CodeQL has a specialized **extractor**:

| Language Type | Extraction Method | What's Captured |
|-------------|------------------|----------------|
| **Compiled** (Java, C++, C#, Go) | Intercepts the build process | AST, type info, call graphs, data flow |
| **Interpreted** (Python, JS, Ruby) | Parses source files directly | AST, type inference, module resolution |

The extractor produces:
- **Abstract Syntax Tree (AST)**: Every expression, statement, declaration
- **Type information**: Variable types, function signatures, class hierarchies
- **Control flow**: If/else branches, loops, exception handling
- **Data flow**: How values move between variables and functions
- **Call graph**: Which functions call which other functions

### Database Structure

A CodeQL database is a **relational database** stored on disk. It contains tables like:

| Table (conceptual) | What It Stores | Example Row |
|-------------------|---------------|-------------|
| `functions` | All function definitions | `get_user()` at line 42 in `app.py` |
| `calls` | All function calls | `execute(query)` at line 45 |
| `variables` | All variable declarations | `name` of type `str` at line 43 |
| `expressions` | All expressions | `f"SELECT..."` at line 44 |
| `types` | Type information | `str`, `Cursor`, `Response` |
| `comments` | Code comments | `# TODO: add auth` at line 41 |

## Step 2: Query Execution

Once you have a database, you run **QL queries** against it.

### QL — The Query Language

QL is a **declarative, object-oriented query language**. It's a dialect of **Datalog** (a logic programming language related to Prolog).

Key characteristics:
- **Declarative**: You describe WHAT you're looking for, not HOW to find it
- **Logic-based**: Uses logical predicates and quantifiers
- **Object-oriented**: Has classes, inheritance, and methods
- **Set-based**: Queries return sets of results (like SQL)

### Basic QL Syntax

```ql
import python                          // Import language-specific library

from Function f                        // Declare variable f of type Function
where f.getName() = "eval"             // Filter: function named "eval"
select f, "Dangerous function: eval()" // Output: location + message
```

This query finds all functions named `eval` in a Python codebase.

### QL vs SQL Comparison

| Concept | SQL | QL |
|---------|-----|------|
| Select data | `SELECT name FROM functions` | `from Function f select f.getName()` |
| Filter | `WHERE name = 'eval'` | `where f.getName() = "eval"` |
| Join | `JOIN calls ON ...` | `exists(Call c \| c.getTarget() = f)` |
| Aggregate | `COUNT(*)` | `count(Function f \| ...)` |
| Subquery | `IN (SELECT ...)` | `exists(... \| ...)` |

### A Real Security Query

```ql
/**
 * @name SQL injection
 * @description Building SQL queries from user input enables SQL injection.
 * @kind path-problem
 * @problem.severity error
 * @security-severity 9.8
 * @id py/sql-injection
 */

import python
import semmle.python.security.dataflow.SqlInjectionQuery
import DataFlow::PathGraph

from SqlInjectionConfiguration config, DataFlow::PathNode source, DataFlow::PathNode sink
where config.hasFlowPath(source, sink)
select sink.getNode(), source, sink, "This SQL query depends on $@.", source.getNode(), "user-provided value"
```

Breaking this down:
- **Metadata comments** (`@name`, `@kind`, etc.) control how results appear in GitHub
- **Imports** bring in language libraries and pre-built security models
- **Configuration** defines sources (user input) and sinks (SQL execution)
- **`hasFlowPath`** checks if tainted data can flow from source to sink
- **`select`** outputs the vulnerability location with a message

## Step 3: Results

Query results are formatted as **SARIF** (Static Analysis Results Interchange Format):

```json
{
  "runs": [{
    "tool": { "driver": { "name": "CodeQL" } },
    "results": [{
      "ruleId": "py/sql-injection",
      "message": { "text": "This SQL query depends on user-provided value" },
      "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "app.py" }, "region": { "startLine": 45 } } }],
      "codeFlows": [{ "threadFlows": [{ "locations": [/* source → sink path */] }] }]
    }]
  }]
}
```

GitHub parses this SARIF and creates **code scanning alerts** with:
- The vulnerability type and severity
- The exact file and line number
- The data flow path from source to sink
- Suggested fix information

## Key Concepts Summary

| Concept | What It Is | Why It Matters |
|---------|-----------|---------------|
| Extractor | Parses code into a database | Language-specific, captures full semantics |
| CodeQL Database | Relational representation of code | Enables querying code like data |
| QL | Datalog-based query language | Declarative, powerful pattern matching |
| Source | Where untrusted data enters | Starting point for taint tracking |
| Sink | Where data is used dangerously | End point — where vulnerabilities occur |
| SARIF | Results format | Standard interchange for static analysis |

## Quiz (5+ questions, use ask_user with 4 choices each)

1. "What does the CodeQL extractor produce?" (A relational database of your code / A compiled binary / A test report / A dependency graph only)
2. "QL is a dialect of which programming paradigm?" (Datalog — a logic programming language / JavaScript — a scripting language / SQL — a database language / Python — a general-purpose language)
3. "For compiled languages like Java, how does CodeQL extract code?" (By intercepting the build process / By reading source files directly / By analyzing .class files / By running the tests)
4. "What format are CodeQL results uploaded in?" (SARIF / JSON-LD / GraphQL / Protocol Buffers)
5. "In a CodeQL security query, what does `hasFlowPath(source, sink)` check?" (Whether tainted data can flow from user input to a dangerous operation / Whether the code compiles successfully / Whether tests pass / Whether the function is called)
