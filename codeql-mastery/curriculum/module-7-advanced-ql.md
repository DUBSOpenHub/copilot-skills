# Module 7: Advanced — QL as a Datalog Dialect

**Optional Bonus Material**: Deep dive into the datalog foundations of QL.

## What is Datalog?

**Datalog** is a declarative query language rooted in logic programming. It's a subset of Prolog, designed for querying relational data. CodeQL's QL language is a **modern dialect of Datalog** with object-oriented extensions.

### Datalog Fundamentals

| Concept | Datalog | QL Equivalent |
|---------|---------|--------------|
| **Fact** | `parent("Alice", "Bob").` | Extracted data in the database (tuples) |
| **Rule** | `ancestor(X, Y) :- parent(X, Y).` | Predicate definition |
| **Query** | `?- ancestor("Alice", Z).` | `from ... where ... select ...` |
| **Variable** | Upper-case: `X`, `Y` | Declared: `Function f`, `int x` |
| **Negation** | `not member(X, "admins").` | `not exists(... \| ...)` |

### Why Datalog for Code Analysis?

Datalog's properties make it ideal for analyzing code:

1. **Termination guarantee**: Unlike Prolog, Datalog queries always terminate (no infinite loops)
2. **Monotonic reasoning**: Adding facts never invalidates existing conclusions
3. **Efficient fixpoint computation**: Recursive queries (like transitive closure) are computed efficiently
4. **Set semantics**: Results are sets, not sequences — no duplicates, order-independent

## QL's Datalog Heritage

### Predicates as Rules

In Datalog, a **rule** derives new facts from existing ones. In QL, **predicates** serve the same purpose:

```
// Datalog
ancestor(X, Y) :- parent(X, Y).
ancestor(X, Z) :- parent(X, Y), ancestor(Y, Z).

// QL equivalent
predicate isAncestor(Person x, Person y) {
  isParent(x, y)
  or
  exists(Person mid | isParent(x, mid) and isAncestor(mid, y))
}
```

Both express: "X is an ancestor of Y if X is a parent of Y, OR X is a parent of someone who is an ancestor of Y." This is **recursive** — the rule refers to itself.

### Fixpoint Semantics

Datalog evaluates recursive rules using **fixpoint computation**:

1. Start with known facts (the database)
2. Apply all rules to derive new facts
3. Repeat until no new facts are derived (the **fixpoint**)

QL does the same thing. When you write a recursive predicate:

```ql
// Find all functions reachable from main()
predicate isReachable(Function f) {
  f.getName() = "main"
  or
  exists(Function caller |
    isReachable(caller) and
    caller.calls(f)
  )
}
```

QL evaluates this by:
1. `main()` is reachable (base case)
2. Anything `main()` calls is reachable
3. Anything called by those functions is also reachable
4. Continue until no new reachable functions are found

### Stratified Negation

Datalog restricts negation to be **stratified** — you can't negate something that depends on the thing being defined. QL enforces this too:

```ql
// VALID: negation doesn't create circular dependency
predicate isDead(Function f) {
  not exists(Call c | c.getTarget() = f)  // No one calls this function
}

// CONCEPTUALLY INVALID (QL prevents this pattern):
// predicate isAlive(Function f) { not isDead(f) }
// predicate isDead(Function f) { not isAlive(f) }  // Circular!
```

## QL Extensions Beyond Datalog

QL goes beyond classical Datalog with several powerful extensions:

### 1. Object-Oriented Types

```ql
class SecuritySink extends DataFlow::Node {
  SecuritySink() {
    this = any(SqlExecution e).getAnArgument()
    or
    this = any(FileWrite w).getAnArgument()
  }
}
```

Classes in QL define **sets of values** (not mutable objects). A `SecuritySink` is any data flow node that matches the characteristic predicate.

### 2. Aggregates

Classical Datalog has no aggregates. QL adds:

```ql
// Count functions per module
from Module m
select m, count(Function f | f.getEnclosingModule() = m | f) as numFunctions
order by numFunctions desc
```

### 3. String Operations

```ql
from Function f
where f.getName().regexpMatch("(?i).*password.*")
select f, "Function name contains 'password'"
```

### 4. Range Types and Arithmetic

```ql
from int x
where x in [1 .. 100] and x % 7 = 0
select x  // Multiples of 7 up to 100
```

## Taint Tracking as Datalog

CodeQL's taint tracking is fundamentally a Datalog computation:

```
// Pseudocode — what taint tracking looks like as Datalog rules

// Base case: sources are tainted
tainted(X) :- isSource(X).

// Inductive case: taint propagates through data flow
tainted(Y) :- tainted(X), flowsTo(X, Y), not isSanitizer(Y).

// Alert: tainted data reaches a sink
alert(Y) :- tainted(Y), isSink(Y).
```

The entire taint tracking framework is a fixpoint computation:
1. Mark all sources as tainted
2. Propagate taint through data flow edges
3. Stop at sanitizers
4. Report where taint reaches sinks
5. Repeat until fixpoint (no new tainted nodes)

## Performance Implications

Understanding the Datalog foundation helps you write better queries:

| Pattern | Performance | Why |
|---------|-----------|-----|
| Simple predicates | Fast | Small intermediate tables |
| Recursive predicates | Medium | Fixpoint computation, but bounded |
| Cross-product joins | Slow | Cartesian product explosion |
| Unbound variables | Very slow | Must enumerate all possible values |
| Tight constraints first | Fast | Reduces intermediate result size |

### Query Optimization Tips

```ql
// SLOW: unbound join
from Function f, Call c
where c.getTarget().getName() = f.getName()
select f, c

// FAST: direct relationship
from Function f, Call c
where c.getTarget() = f
select f, c
```

```ql
// SLOW: filter late
from Variable v
where v.getAnAccess().getEnclosingFunction().getName() = "main"
select v

// FAST: filter early
from Function main, Variable v
where
  main.getName() = "main" and
  v.getAnAccess().getEnclosingFunction() = main
select v
```

## Key Takeaways

| QL Feature | Datalog Origin | Benefit for Code Analysis |
|-----------|---------------|--------------------------|
| Declarative queries | Core Datalog | Describe WHAT to find, not HOW |
| Recursive predicates | Datalog rules | Transitive closure (call graphs, data flow) |
| Fixpoint computation | Datalog semantics | Guaranteed termination |
| Stratified negation | Datalog restriction | Sound logical reasoning |
| Classes (QL extension) | Not in Datalog | Organize code patterns as types |
| Aggregates (QL extension) | Not in Datalog | Counting, statistics, metrics |
| Taint tracking | Datalog fixpoint | Source-to-sink vulnerability detection |

## Quiz (5+ questions, use ask_user with 4 choices each)

1. "What does 'fixpoint computation' mean in Datalog?" (Rules are applied repeatedly until no new facts are derived / A computation that runs exactly once / A way to fix bugs in queries / A method for optimizing database storage)
2. "Why is Datalog ideal for code analysis?" (Guaranteed termination, efficient recursion, and set semantics / It's the fastest query language / It was designed specifically for CodeQL / It supports mutable state)
3. "In QL, what does a class's characteristic predicate define?" (The set of values that belong to that class / The constructor arguments / The return type / The class name)
4. "What is 'stratified negation'?" (Negation that doesn't create circular dependencies / Negation applied in layers / A way to negate multiple conditions / Database sharding strategy)
5. "How is CodeQL's taint tracking related to Datalog?" (It's a fixpoint computation that propagates tainted facts through data flow rules / It uses SQL under the hood / It's a separate system not related to Datalog / It only works with JavaScript)
