# Module 6: Advanced — CodeQL Database Internals

**Optional Bonus Material**: Deeper understanding of how CodeQL databases are built.

## How CodeQL Databases Are Built

### The Extraction Pipeline (Deep Dive)

```
Source Code
    ↓
┌─────────────────────┐
│   Build Intercept    │  ← For compiled languages, hooks into the compiler
│   (or Direct Parse)  │  ← For interpreted languages, parses source directly
└─────────┬───────────┘
          ↓
┌─────────────────────┐
│   Trap Files (.trap) │  ← Intermediate representation — one per source file
│   Generated          │  ← Contains tuples (rows) for database tables
└─────────┬───────────┘
          ↓
┌─────────────────────┐
│   Database Import    │  ← Trap files imported into relational database
│   (finalize)         │  ← Indexes built, integrity checks run
└─────────┬───────────┘
          ↓
┌─────────────────────┐
│   CodeQL Database    │  ← Final database ready for queries
│   (on-disk format)   │  ← ~10-100x the size of source code
└─────────────────────┘
```

### Trap Files — The Intermediate Layer

**Trap files** are the secret sauce of CodeQL extraction. They're tab-separated files that define tuples (database rows):

```trap
// Example trap file content (simplified)
functions(1, "get_user", 42, 1, 58, 1)     // id, name, start_line, start_col, end_line, end_col
calls(2, 1, "execute", 45, 5)               // id, enclosing_func, target, line, col
variables(3, "name", "str", 43, 5)           // id, name, type, line, col
expressions(4, "string_format", 44, 12)      // id, kind, line, col
```

Each tuple maps to a row in the final database. The extractor generates thousands of these per source file.

### Database Schema (Conceptual)

A CodeQL database has tables organized by language. For Python:

```
┌─────────────────────────────────────────────────────┐
│                   CodeQL Database                     │
├─────────────────────┬───────────────────────────────┤
│ AST Tables          │ Semantic Tables                │
│ ─────────           │ ──────────────                 │
│ • py_exprs          │ • py_flow_nodes               │
│ • py_stmts          │ • py_scopes                   │
│ • py_functions      │ • py_classes                  │
│ • py_arguments      │ • py_imports                  │
│ • py_parameters     │ • py_module_attributes        │
│ • py_variables      │ • py_object_types             │
├─────────────────────┼───────────────────────────────┤
│ Location Tables     │ Metadata Tables               │
│ ────────────        │ ───────────────               │
│ • locations_default │ • compilations                │
│ • files             │ • compilation_args            │
│ • folders           │ • source_location_prefix      │
│ • numlines          │ • extractor_version           │
└─────────────────────┴───────────────────────────────┘
```

### Compiled vs. Interpreted Extraction

#### Compiled Languages (Java, C++, C#, Go)

For compiled languages, CodeQL needs to **observe the build**:

```bash
# Step 1: Create empty database
codeql database create my-db --language=java --command="mvn clean compile"

# What happens:
# 1. CodeQL wraps the Java compiler (javac)
# 2. Every file compiled → trap file generated
# 3. Type resolution uses actual compiler output
# 4. Dependencies resolved via build artifacts
```

Key implications:
- **Build must succeed** for extraction to work
- CodeQL sees the SAME code the compiler sees (including generated code)
- Build system must be compatible (Maven, Gradle, Make, CMake, MSBuild)
- Environment must have all dependencies installed

#### Interpreted Languages (Python, JavaScript, Ruby)

For interpreted languages, CodeQL parses source files directly:

```bash
# Step 1: Create database (no build command needed)
codeql database create my-db --language=python

# What happens:
# 1. CodeQL walks the source tree
# 2. Each .py file is parsed by CodeQL's Python parser
# 3. Type inference runs (without executing the code)
# 4. Import resolution attempts to find referenced modules
```

Key implications:
- **No build required** — just source files
- Type information is inferred, not from a compiler
- Dynamic features (metaprogramming, runtime imports) may be missed
- Virtual environments and installed packages may not be fully resolved

### Database Size and Performance

| Codebase Size | Approx. DB Size | Extraction Time | Query Time |
|-------------|----------------|----------------|------------|
| 10K LOC | 50-100 MB | 30-60 seconds | 10-30 seconds |
| 100K LOC | 500 MB - 1 GB | 2-5 minutes | 1-3 minutes |
| 1M LOC | 5-10 GB | 15-30 minutes | 5-15 minutes |
| 10M LOC | 50-100 GB | 1-3 hours | 15-60 minutes |

### Multi-Language Databases

Since CodeQL databases are per-language, a project using multiple languages gets multiple databases:

```bash
# Create databases for each language
codeql database create --language=python --db-cluster my-project-dbs
codeql database create --language=javascript --db-cluster my-project-dbs

# In GitHub code scanning, this happens automatically
# Default setup detects all languages and creates separate analyses
```

### Database Upgrading

When CodeQL releases new versions, database schemas may change:

```bash
# Upgrade a database to current schema
codeql database upgrade my-db

# Check database info
codeql database info my-db
```

## Hands-On: Exploring a Database

```bash
# Install CodeQL CLI
gh extension install github/gh-codeql

# Create a database from a local project
codeql database create my-db --language=python --source-root=./my-project

# Explore the database
ls my-db/
# → db-python/  log/  src.zip  codeql-database.yml

# Look at the database schema
codeql database info my-db

# Run a simple query
codeql query run --database=my-db my-query.ql
```

## Quiz (5+ questions, use ask_user with 4 choices each)

1. "What are trap files?" (Intermediate tuple files generated during extraction / Configuration files for CodeQL / Test fixtures / Log files)
2. "Why does CodeQL need to observe the build for Java?" (To intercept compiler output and capture type information / Because Java is slower / To run the tests / To generate documentation)
3. "Approximately how large is a CodeQL database for 100K lines of code?" (500 MB to 1 GB / 1 KB / Same size as source / 100 GB)
4. "Can CodeQL create a database for Python without running a build command?" (Yes — it parses source files directly / No — all languages require a build / Only if using GitHub Actions / Only for Python 2)
5. "What happens when a new CodeQL version changes the database schema?" (You run 'codeql database upgrade' to migrate / The database is deleted / Nothing — schemas are permanent / You must re-extract from scratch)
