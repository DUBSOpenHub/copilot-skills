# Engine CLI Reference

Canonical command/JSON contract for `bin/throughline` (wraps `python3 -m engine.cli`) — the
repository's primary CLI entry point. `bin/throughline-engine` is kept installed alongside it
as a backward-compatible alias for the identical entry point; every command and every scenario
behaves identically under either name. This is the source of truth ARCH.md §4 refers to. Every
command is independently invocable by a human, the Skill Prompt Layer agent (via `bash`), or a
test harness (via `subprocess`) — all three drive the identical entry point.

## Wire contract

Every command optionally reads JSON via `--input <file>` (or `--input -` / piped stdin) and
always writes exactly one line of JSON to stdout:

```json
{"ok": true,  "data": <command-specific result>, "error": null}
{"ok": false, "data": null, "error": {"code": "STRING_CODE", "message": "human text", "details": {}}}
```

Exit code is `0` iff `ok: true`. Diagnostics and stack traces (for genuine bugs) go to **stderr
only** — stdout always stays parseable JSON. Global flag `--workspace-root <path>` overrides the
workspace root (else `THROUGHLINE_WORKSPACE_ROOT` env var, else `THROUGHLINE_HOME` env var, else
`~/.copilot/throughline`). `THROUGHLINE_HOME` is an alternate name for the same setting, honored
only when `THROUGHLINE_WORKSPACE_ROOT` is unset — existing deployments that already export
`THROUGHLINE_WORKSPACE_ROOT` are unaffected.

Most mutating commands take `--actor <name>`; if omitted it defaults to
`$THROUGHLINE_ACTOR` or the OS login user (`getpass.getuser()`) — never a silent `"system"` for a
human-initiated action (NFR-8).

### Top-level identity fields (`workspace_id`, `deck_id`)

Whenever a successful command's `data` establishes or reports a workspace and/or deck identity,
the envelope also carries that identity as top-level, snake_case sibling fields of `ok`/`data`/
`error` — additive only; every nested field inside `data` keeps its existing shape and casing
exactly as documented below:

```json
{"ok": true, "data": {"workspaceId": "workspace:...", ...}, "error": null, "workspace_id": "workspace:...", "deck_id": "deck:workspace:..."}
```

- `workspace_id` is present for `workspace new`/`show`/`resume`, the bare no-subcommand form, and
  every `run-scenario` invocation form (including the bare one) — a `run-scenario` call against a
  root that already has an active workspace idempotently *resumes* it (see "Sequential invocation
  / resume" below) rather than opening a second one, so a first and a later invocation against the
  same resolved workspace root always agree on this same id.
- `deck_id` is present wherever a deck identity is available: `run-scenario`'s report once Stage
  passes, `export package`, `export pptx`, and any `workspace` response once a deck has been
  compiled.
- Both fields are simply **absent** — never a fabricated empty string or `null` — whenever the
  underlying identity isn't present in `data` (e.g. `gate status`, or `workspace show` with no
  active workspace). Every error envelope (`data: null`) never carries either field.

Since hardening cycle 7, `workspace_id`/`deck_id` (identical resolution/absence rules) are also
added *inside* `data` itself — not just as these outer envelope siblings — alongside several other
top-level snake_case report aliases; see "Top-level report compatibility aliases" under "Scenario
runner" below. This matters for a caller reading a written `run-report.json` file directly, which
is never wrapped in this outer envelope.

### No subcommand (bare invocation)

`bin/throughline` invoked with **no subcommand at all** is itself a first-class public form, not
an error: it opens the single default talk workspace (exactly like `workspace new` with no brief)
if none is active yet, or reports the identity of whichever one already is (exactly like
`workspace show`'s active branch) if one is — so a bare invocation and every later bare invocation
against the same resolved workspace root converge on, and resume, the identical workspace/brief
identity rather than ever creating a second one or raising `WORKSPACE_ALREADY_ACTIVE`. It uses the
same workspace-root precedence as every other command (`--workspace-root` /
`THROUGHLINE_WORKSPACE_ROOT` / `THROUGHLINE_HOME` / `~/.copilot/throughline`), and returns exactly
the shape `workspace show` returns for its active branch:

```json
{"ok": true, "data": {"active": true, "workspace": {...}, "brief": {...}, "nextAction": "..."}, "error": null}
```

This is distinct from (but composable with) the bare `run-scenario` form below — that one is
"`run-scenario` with no `--workspace`/`--out`"; this one is "no subcommand named at all." Every
other explicit subcommand, and argparse's own error for an unrecognized one or one missing its own
required nested action (e.g. `workspace` alone), is unaffected. See
`tests/test_bare_default_workspace.py`.

### `status` (compatibility alias)

`bin/throughline status` is a discoverable, explicitly-named top-level subcommand that is a
complete alias for the bare no-subcommand form immediately above: same handler
(`cmd_bare_default_workspace`), same shape, same identity, same workspace-root precedence — for
callers/harnesses that specifically probe for a named `status` verb rather than omitting the
subcommand entirely. A `status` call before any workspace exists opens the single default talk
workspace (exactly like a first bare invocation would); a later `status` call — or a bare
invocation, in either order — resumes that identical workspace/brief identity rather than ever
creating a second one. See `tests/test_status_command.py`.

`status` additionally accepts an explicit `--workspace <dir>` flag, registered directly on this
subcommand (so it may follow the `status` token itself, e.g. `bin/throughline status --workspace
<dir>`) — an alias for the global `--workspace-root`, taking precedence over it if both are given,
exactly like `run-scenario`'s own identically-named flag (below). Every other resolution rule
(env vars, default root) and the identity response shape are unaffected. See
`tests/test_status_command.py`'s `StatusExplicitWorkspaceFlagTests`.

## Commands

### Workspace (NFR-2)

| Command | Notes |
|---|---|
| `workspace new [--input brief.json] --actor <name>` | Opens the single active workspace. With a complete brief, lands at phase `SOURCING`; otherwise `BRIEFING`. Fails `WORKSPACE_ALREADY_ACTIVE` if one is already open. |
| `workspace show` | `{"active": false}` or `{"active": true, "workspace", "brief", "nextAction"}`. Never mutates. |
| `workspace reset --actor <name>` | Releases the active-workspace lock. Data is **never** deleted. |
| `workspace resume --id <id> --actor <name>` | Re-acquires the lock on a previously-closed on-disk workspace. |

### Brief

| Command | Notes |
|---|---|
| `brief set --input brief.json --actor <name>` | Partial update; auto-advances `BRIEFING` → `SOURCING` once audience/eventType/takeaway/duration are all set. |

### Source (FR-SRC-1..6, FR-M365-1..6)

| Command | Notes |
|---|---|
| `source ingest --input fetchresult.json --actor <name>` | Body is one `FetchResult` (see below). Enforces the 25-artifact cap, size/type limits (§16.1 below), independent local-file readability re-check, and the source state machine. |
| `source list` | All sources in the bundle. |
| `source resolve-hold <id> --decision authorize\|retire --actor <name>` | Resolves a `PARSE_FAILED`/`LABEL_CONFLICT`/`QUARANTINED` hold. |
| `source revoke <id> --actor <name>` | Marks `ACCESS_REVOKED`; cascades to dependent evidence/claims. |
| `source retire <id> --actor <name>` | Frees the source's bundle slot. |
| `source quarantine <id> --reason <text> --actor <name>` | Manual hold. |

All four lifecycle transitions above are also reachable through `run-scenario`'s action-list
interface (`revoke_source`/`quarantine_source`/`resolve_source_hold`/`retire_source`, referencing
the target source by `uri` since a declarative scenario document has no other way to know its
server-generated id ahead of time) — see "Source lifecycle actions" under "Scenario runner" below.

`FetchResult` body:
```json
{
  "origin": "local | workiq | github",
  "sourceType": "sharepoint_doc | onedrive_doc | pptx_file | teams_message | teams_transcript |
                 outlook_mail | outlook_calendar | loop_page | github_repo | github_issue |
                 github_pr | github_discussion | github_release_notes | local_upload | local_paste",
  "uri": "exact locator the user named (a filesystem path for local_upload)",
  "owner": "string", "permissionState": "authorized | denied",
  "aclSnapshot": "string", "sensitivityLabel": "string | null", "version": "string",
  "retrievedAt": "ISO-8601 (optional, defaults to now)",
  "content": "text (workiq/github origin, or local_paste)",
  "contentBase64": "base64 (optional, binary local_upload content)"
}
```
For `origin: local` and `sourceType != local_paste`, `uri` **must** be a real filesystem path —
the Engine reads and independently re-verifies it itself (FR-SRC-4); any `content`/`contentBase64`
supplied is ignored for that case.

`.eml` (a locally uploaded RFC 822 email export, distinct from a live WorkIQ Outlook message) is
additionally accepted as a local document type (ARCH §16.1's own table predates it; extraction is
Subject/From/To headers plus the best available text body part, via the stdlib `email` module).

#### Source descriptor field-name aliases (Dark Factory hardening cycle 7)

Every `FetchResult` field above also accepts an explicit, conservative allowlist of camelCase
*and* snake_case synonyms, resolved once by `engine.ingest.normalize_source_payload` — shared by
the raw `source ingest` CLI command above, every `run_scenario` document shape, and the
`ingest_source`/`add_source` action-list verbs, so all four entry points normalize identically:

| Canonical field | Accepted aliases |
|---|---|
| `uri` | `path`, `source_uri`, `sourceUri`, `local_path`, `localPath`, `url`, `href`, `web_url`, `link`, `locator`, `source_locator`/`sourceLocator`, `fixture`, `fixture_path`/`fixturePath`, `artifact`, `artifact_path`/`artifactPath`, `document`, `document_path`/`documentPath`, `file_path`/`filePath`, `local_file`/`localFile`, `input_file`/`inputFile`, `input_path`/`inputPath`, `content_file`/`contentFile`, `content_path`/`contentPath`, `upload`, `upload_path`/`uploadPath`, `reference`, `ref` |
| `sourceType` | `type`, `source_type`, `kind`, `format`, `mime`, `mimeType`, `source_kind`/`sourceKind`, `document_type`/`documentType`, `artifact_type`/`artifactType` |
| `owner` | `author` |
| `permissionState` | `access`, `access_state`, `accessState` |
| `aclSnapshot` | `permission_snapshot`, `permissionSnapshot` |
| `sensitivityLabel` | `label`, `label_state`, `labelState` |
| `retrievedAt` | `authorized_at`, `authorizedAt` |
| `content` | `text`, `body`, `transcript` |
| `origin` | `connector`, `provider` |

An explicit canonical field always wins over a differing sibling alias (e.g. `uri` over a
conflicting `path`) — never silently overridden. Absent the canonical field, two or more
*aliases* that disagree with each other is a clean `VALIDATION_ERROR`, never a guess; agreeing
aliases (including just one) resolve normally. Every other, unrecognized key (e.g. a caller's own
`title`) passes through completely untouched — no source metadata is ever silently dropped. See
`tests/test_source_payload_key_compatibility.py`.

`url`/`href`/`web_url`/`link` (Dark Factory hardening cycle 10/11) and `kind`/`format`/`mime`/
`mimeType` (same cycles) are further conservative field-name synonyms — for a plain
web-fetch-shaped descriptor's own location field, and a MIME-ish "format"/"mime type" name in
place of `sourceType`, respectively — carrying the identical existing value space
(`normalize_origin`/`infer_origin` above), never a second alias *value* vocabulary.
`text`/`body`/`transcript` → `content` and `connector`/`provider` → `origin` (Dark Factory
hardening cycle 11, acceptance pass 14) are the parallel synonyms for a descriptor's own inline
prose and its own connector/product name; `connector`/`provider` are resolved through the
identical `origin` allowlist/conflict-detection an explicit `origin` field already uses (so an
unrecognized connector name is refused exactly like an unrecognized `origin`, and a
connector/provider hint that outright contradicts the descriptor's own `sourceType`/`uri` is its
own explicit `VALIDATION_ERROR`, never silently honored or overridden). See
`tests/test_deep_source_descriptor_unwrapping.py` and
`tests/test_structural_source_descriptor_extraction.py`.

`locator`/`source_locator`/`fixture`/`fixture_path`/`artifact`/`artifact_path`/`document`/
`document_path`/`file_path`/`local_file`/`input_file`/`input_path`/`content_file`/`content_path`/
`upload`/`upload_path`/`reference`/`ref` (Dark Factory hardening cycle 12) are a further,
wider synonym family for `uri` — a scenario-fixture reference, an on-disk artifact/document/
upload path, or a generic "reference"/`ref` — and `source_kind`/`document_type`/`artifact_type`
are the parallel synonyms for `sourceType`, carrying the identical existing value space. Every
alias in this table (old and new alike) also accepts a kebab-case or differently-spaced spelling
of an already-listed name (e.g. `"source-locator"`, `"Source Locator"`) via a second,
`engine.ingest._normalize_field_key`-based fallback match — never a new alias *value*, only a
wider spelling match for the identical, already-declared names. See
`tests/test_source_reference_vocabulary_aliases.py`.

A descriptor with no real `uri` at all may still name its own resource via a bare, otherwise-
unrecognized field whose value is a plain string (Dark Factory hardening cycle 11,
`engine.ingest._apply_bare_scalar_field_hint`): one that already looks like a locator (a URI
scheme, a path separator, or a recognized local upload/paste extension) becomes `uri`; otherwise,
only when this same descriptor also carries a `sourceType`/`title`/`filename`/`file`/`name` hint
of its own, it becomes inline `content` instead (so `_apply_manual_upload_hint` below can still
turn that hint into a synthesized `uri`). Never applied when two or more such unrecognized
string-valued fields exist, or when a real `uri`/`content` is already present — never a guess.

#### Authorization boolean/state aliases (Dark Factory hardening cycle 13)

`authorized`, `is_authorized`, and `isAuthorized` are further, boolean-shaped synonyms for
`permissionState`, resolved by `engine.ingest._apply_authorization_aliases` immediately after the
field-alias table above (shared by every entry point — raw CLI, every `run_scenario` document
shape, and the action-list verbs — never scenario-only). A JSON boolean `true`/`false` on any of
these three, or directly on `permissionState`/one of its own existing `access`/`access_state`/
`accessState` aliases, resolves to the identical canonical `"authorized"`/`"denied"` string the
field already models. Unlike every other alias in the field-name table above (where an explicit
canonical field always silently wins over a differing sibling alias), an authorization signal is
security-sensitive: **any** two of these fields disagreeing — including a boolean alias that
disagrees with an already-explicit `permissionState` string — is a clean `VALIDATION_ERROR`, never
a silent pick; agreeing signals (including just one) resolve normally, and `owner`/`aclSnapshot`
metadata given alongside is completely unaffected. See
`tests/test_manual_source_locator_defaults.py`.

#### Origin alias normalization (FR-SRC-1)

`origin` also accepts a number of common staged/connector-shaped synonyms instead of the exact
canonical string, resolved case-/hyphen-/space-insensitively by `engine.ingest.normalize_origin`
before the state machine runs: `manual`, `upload`, `uploaded`, `file`, `filesystem`,
`local_upload`, `local_paste`, `paste` → `local`; `repo`, `repository`, `issue`, `pr`,
`pull_request`, `discussion`, `release`, `release_notes`, `github_file`, `repo_file`,
`repository_file`, and every `github_*` source-type-shaped value → `github`; `sharepoint`,
`sharepoint_doc`, `onedrive`, `onedrive_doc`, `teams`, `teams_message`, `teams_transcript`,
`teams_chat`, `outlook`, `outlook_mail`, `outlook_calendar`, `loop`, `loop_page`, `m365`,
`microsoft365`, `office365`, `pptx_file` → `workiq`. A staged value that doesn't match after that
(case-/hyphen-/space-insensitive) lookup gets two further, progressively looser passes: a
camelCase-collapsed spelling (e.g. `sharepointDoc`/`teamsTranscript`/`githubIssue` resolve exactly
like their snake_case form already does), then a fully punctuation-agnostic squash — every alias
above and the value itself have all non-alphanumeric characters squashed out before comparing, so
e.g. `"Office 365"` still resolves like `"office365"` does. A known MIME-type string (e.g.
`text/markdown`, `application/pdf`, `application/vnd.openxmlformats-officedocument.
wordprocessingml.document`, `application/vnd.openxmlformats-officedocument.presentationml.
presentation`, `message/rfc822`, `application/json`, `image/png`/`jpeg`/`gif`) is first collapsed
to its equivalent short format word before any of the above. An origin that still isn't one of the
three canonical values or a listed alias/MIME-type is a clean `VALIDATION_ERROR`, never a guess.
`sourceType` is completely untouched by this normalization — a source's own source-type metadata
is preserved exactly as supplied, regardless of which origin alias was used. See
`tests/test_source_origin_aliases.py`.

#### Originless source classification (FR-SRC-1, Dark Factory hardening cycle 9)

An `origin` that is **omitted entirely** (as opposed to an explicit, even if wrong, value — which
is never second-guessed) is conservatively inferred by `engine.ingest.infer_origin` from context
already on the same descriptor, before the checks above run, trying — in order:

1. `sourceType`, run back through `normalize_origin` itself (see above) — the *local* family
   additionally recognizes a bare public format word instead of a connector name: `markdown`,
   `md`, `text`, `txt`, `plaintext`, `pdf`, `pptx`, `docx`, `vtt`, `srt`, `transcript`, `eml`,
   `email`, `json`, `image`, `png`, `jpg`, `jpeg`, `gif` (any camelCase/MIME-type spelling too) →
   `local` — distinct from the already-listed, WorkIQ-specific `pptx_file` (a PowerPoint file
   *retrieved via WorkIQ*, ARCH §7).
2. A short allowlist of well-known `uri` hostname substrings for the `github`/`workiq` connector
   surfaces (`github.com`, `githubusercontent.com` — including `api.github.com`/
   `raw.githubusercontent.com` by substring containment; `sharepoint.com`, `onedrive.live.com`,
   `1drv.ms`, `teams.microsoft.com`, `outlook.office.com`, `outlook.office365.com`,
   `loop.microsoft.com`, `loop.cloud.microsoft`).
3. The `uri`'s own explicit scheme — currently just `workiq://...`.
4. The `uri`'s own file extension, but *only* when the `uri` already looks like a genuine local
   filesystem reference (no scheme at all, an explicit `file://` scheme, or a single-letter
   Windows drive-letter scheme — never a network URL whose host/scheme didn't already match step
   2/3 above): a recognized MVP local document/image extension (`.md`, `.txt`, `.pdf`, `.docx`,
   `.pptx`, `.vtt`, `.srt`, `.eml`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.json`) infers `local`.

When `sourceType` is *also* entirely omitted and `origin` ends up `local` via step 4 above,
`sourceType` itself defaults to the existing `local_upload` canonical type (never fabricated
otherwise — a `sourceType` the caller *did* supply, in any recognized spelling, is always
preserved verbatim in the ledger, never rewritten).

Returns `None` (never a guess) when nothing above gives a confident match, so the descriptor's
`origin` stays exactly as omitted and the existing `VALIDATION_ERROR` refusal still fires — an
unknown/ambiguous descriptor (an unrecognized extension, an unrecognized `sourceType` word, or a
network URL with neither a known host nor a recognized extension) is still held/refused, never
silently authorized. An **explicit**, valid `origin` that outright conflicts with the connector
this same descriptor's own `sourceType`/`uri` already, confidently implies (e.g. `origin: "local"`
with `sourceType: "github_issue"`) is its own clean `VALIDATION_ERROR` — never silently honored,
never silently overridden; an explicit origin that merely *agrees* with the inferred connector, or
that gives no confident inference to compare against, ingests normally exactly as before. See
`tests/test_origin_inference_from_context.py` and
`tests/test_originless_source_family_compatibility.py` (a table-driven suite covering every
MVP-supported source family, conflict cases, and unknown/ambiguous refusals).

`sourceType` itself is also recognized in every spelling `normalize_origin`/the format-word table
above resolves (`engine.ingest._is_recognized_source_type`) — including camelCase, kebab-case, and
MIME-type forms — not only the exact, documented canonical enum values; the *stored* `sourceType`
is always the caller's own original string, completely untouched by this recognition check.

#### Manual-upload naming hint: `filename`/`file` (Dark Factory hardening cycle 10)

A descriptor that supplies literal inline content (`content`/`contentBase64`) but claims no real
filesystem location at all — no `uri`, and none of its existing location-claiming aliases
(`path`/`source_uri`/`local_path`/`url`/`href`/`web_url`) — never has to name a real on-disk file.
`engine.ingest._apply_manual_upload_hint` (part of `normalize_source_payload`, so every entry point
above sees it identically) recognizes two such shapes:

- A `filename`/`file` naming hint (e.g. `{"filename": "adoption-notes.md", "content": "..."}`)
  becomes this descriptor's own synthesized `uri` — a bare value, so a recognized extension still
  drives `infer_origin`'s file-extension tier exactly like a genuine local path would — and, when
  no explicit `title` was already given, this descriptor's `title` too (surfaced only in a
  scenario run-report's own `source.ingest` step, never stored on the model itself).
- Content plus an explicit `sourceType`/`origin` and no naming hint at all (e.g.
  `{"sourceType": "markdown", "content": "..."}`) instead gets a stable, content-hash-derived
  synthetic identity, so two byte-identical inline uploads always resolve to the same source while
  two different ones never collide.

Either way, the descriptor is ingested through the exact same in-memory manual/paste path an
explicit `sourceType: "local_paste"` descriptor already uses — the real on-disk file existence
check (FR-SRC-4) never runs for it — while `sourceType` itself stays completely untouched
(preserved verbatim, never forced to `"local_paste"`). A no-op whenever a real `uri` is already
present (a genuine location claim always wins over a same-descriptor naming hint), whenever there
is no inline content at all, or whenever this descriptor's own `origin`/`sourceType` already,
confidently implies a non-local connector (`github`/`workiq`, which always name a real remote
resource, never a bare naming hint) — a github/workiq descriptor with no `uri` is still correctly
refused exactly as before. See `tests/test_deep_source_descriptor_unwrapping.py`.

#### Conservative default-local classification (Dark Factory hardening cycle 12, widened in cycle 13; `add_source`/`ingest_source` action-list verb only)

When `origin` is still completely absent after every mechanism above (an explicit value, the
originless-classification tiers, and every field alias) has already had its chance,
`engine.scenario`'s own `add_source`/`ingest_source` action handling — never `engine.ingest`'s
shared, direct `ingest_source`/raw `source ingest` CLI contract, which still requires an explicit
or contextually-inferable `origin` exactly as before this hardening cycle — classifies the
descriptor `local` when it already, independently, carries any one of three conservative signals:
either the manual-upload-hint marker (`engine.ingest.carries_manual_upload_hint`, e.g. a
`title`-only, content-bearing descriptor whose own synthesized `manual-upload:<hash>` `uri` has no
extension `infer_origin` can place on its own), non-empty inline `content`/`contentBase64`
directly (even with no filename/type/title hint at all), or — Dark Factory hardening cycle 13 —
the descriptor's own `uri` is itself unambiguously non-remote: a recognized local pseudo-scheme
(`file`, `paste`, `manual-upload`, `fixture`, `upload`, `local`, e.g. `fixture:widget-42`), a
Windows drive-letter scheme, or a completely schemeless string that also contains a path separator
(a relative/absolute filesystem-shaped identifier). Never applied to an HTTP(S) URL, a GitHub
locator, a Microsoft/WorkIQ locator, any other unrecognized/ambiguous remote-shaped scheme (`ftp`,
`s3`, a caller's own bespoke connector scheme, ...), or a bare, schemeless, separator-less opaque
identifier (e.g. a ticket-shaped `PROJ-1234`) — these all stay exactly as conservatively refused as
before (a bare name/id is never accepted as a source merely for having been given through the
wider reference vocabulary above, or for lacking a scheme). Classification alone is not a
substitute for a real locator: a bare, content-only descriptor with nothing else still fails
afterward for its own separate, specific reason (`uri is required`) if no `uri` was ever
established for it. See `tests/test_source_reference_vocabulary_aliases.py` and
`tests/test_manual_source_locator_defaults.py`.

Once classified `local` this way, three further fields default for this exact `add_source`/
`ingest_source` element only (never for a raw, directly-documented `sources` field entry, and
never for `engine.ingest.ingest_source`'s own direct/raw-CLI contract) — applied at the moment
this element's contribution is actually ingested, so the third default below always sees this
whole document's own final, position-independent `actor`:

- `sourceType`, if omitted, defaults to the existing canonical `local_upload` type.
- `owner`, if omitted, defaults to this scenario document's own `actor` — the person explicitly
  adding the source.
- `permissionState`, if omitted, defaults to `"authorized"` — ARCH §7's `LocalFetcher` contract
  already documents that manually-supplied local content is always authorized; this only makes
  that rule observable for a descriptor that omitted the field entirely.

"Omitted" means completely absent or blank; an explicit value of any kind — an explicit
`permissionState: "denied"`, a differently-supplied `owner`/`sourceType`, or any other considered
signal — is always left completely untouched, never upgraded. See
`tests/test_manual_source_locator_defaults.py`.

An opaque `uri` that carries no recognized local-upload extension of its own is ingested from its
own inline `content`/`contentBase64` directly when either is present (exactly like an explicit
`local_paste`/manual-upload-hinted descriptor already is), rather than ever trying — and failing —
to read a file that was never meant to exist on disk; without any inline content, the identical
opaque descriptor is instead held (`PARSE_FAILED`, see below) rather than raising a bare
validation failure, so the attempted source is still observable in the ledger. A `uri` with a
*recognized* local-upload extension (e.g. `notes.md`) is unaffected either way — a genuine, typed
file reference always still tries the real filesystem first and is held/refused for that reason,
even when inline content also happens to be present. See `tests/test_manual_source_locator_defaults.py`.

#### Relative fixture/locator resolution and held (never hard-refused) not-yet-found files (Dark Factory hardening cycle 12, widened in cycle 13)

A relative `local`-origin `uri`/locator (`fixture`, `document`, `reference`, ... or any of their
existing aliases) is resolved first against the *scenario document's own directory* — threaded
down from `run-scenario --scenario <path>` (see "Scenario runner" below) — before falling back to
the current working directory exactly as before this hardening cycle; a caller invoking
`engine.scenario.run_scenario`/`engine.ingest.ingest_source` directly without that context behaves
identically to before (`scenario_path`/`base_dir` are both optional, additive parameters). The
persisted `uri` itself is never rewritten to the resolved path — provenance always reflects the
locator the caller actually gave.

A `uri` ending in a recognized local upload extension (§16.1's own supported-extension table), or
carrying no extension at all (Dark Factory hardening cycle 13 — an opaque fixture/manual
identifier that was never meant to look like a typed file), that still doesn't resolve to a real,
readable file after that is held — `PARSE_FAILED`, with a `hold_reason` naming the missing locator
— rather than aborting ingestion before any ledger row ever exists, so the source stays visible
and resolvable (`source resolve-hold`/`resolve_source_hold`) exactly like any other parse failure
(FR-SRC-6). A real but *unrecognized* extension (e.g. `.exe`/`.zip`, with no inline content to fall
back to), or a real file the current user genuinely cannot read (FR-SRC-4's own independent
re-verification), are both still an immediate, explicit refusal exactly as before — this only ever
widens the held/`PARSE_FAILED` outcome, never what counts as a supported local file type. See
`tests/test_source_reference_vocabulary_aliases.py` and `tests/test_manual_source_locator_defaults.py`.


### Evidence (FR-EVD-1/2)

| Command | Notes |
|---|---|
| `evidence extract <sourceId> [--force] --actor <name>` | Source must be `AUTHORIZED` or later. Idempotent unless `--force`. |
| `evidence set-disposition <atomId> KEEP\|QUARANTINE\|REJECT --actor <name>` | Rejecting an atom unlinks it from every claim. |
| `evidence list` | All atoms. |

### Claim + Conflict (FR-EVD-3..8)

| Command | Notes |
|---|---|
| `claim propose --input drafts.json --actor <name>` | `drafts.json` is a list of `{type, text, evidenceAtomIds[], rationale?, aspirationalLabel?}`. `type` is exactly one of `factual\|interpretive\|aspirational` (case-insensitive). |
| `claim link-evidence <claimId> <atomId> [--contradicts <otherAtomId>] --actor <name>` | Only `KEEP` atoms are linkable. `--contradicts` creates a blocking `ConflictCard`. |
| `claim unlink-evidence <claimId> <atomId> --reason <text> --actor <name>` | |
| `claim set-rationale <claimId> --rationale <text> --actor <name>` | Required before an interpretive claim can be approved. |
| `claim set-aspirational-label <claimId> --label GOAL\|INTENT\|RECOMMENDATION --actor <name>` | |
| `claim approve <claimId> --actor <name>` | Refuses `CLAIM_UNSUPPORTED` (factual, no valid evidence, or interpretive with no valid evidence), `RATIONALE_REQUIRED`, or `CONFLICT_UNRESOLVED`. |
| `claim lock <claimId> --actor <name>` | Must already be `APPROVED`. |
| `claim rewrite <claimId> --text <text> --actor <name>` | The **only** way LOCKED (or any) claim wording changes (FR-NAR-6); clears approval. |
| `claim retire <claimId> --actor <name>` | |
| `claim list` | |
| `conflict list` | |
| `conflict resolve <conflictId> --decision <text> --actor <name>` | Records a human decision; never silent. |

### Narrative (FR-NAR-1..6)

| Command | Notes |
|---|---|
| `narrative propose-throughlines --input drafts.json --actor <name>` | `drafts.json` is a list of exactly 3 strings. Omitting `--input` entirely (or supplying `{"drafts": []}`) falls back to `narrative.default_throughline_drafts(brief)`: 3 deterministic, non-empty, brief-derived candidates (FR-NAR-1) rather than a `VALIDATION_ERROR` — see "Default candidate generation" below. |
| `narrative select-throughline [--id <id>] [--text <verbatim>] --actor <name>` | Exactly one of `--id`/`--text`. |
| `narrative propose-routes --throughline-id <id> --input drafts.json --actor <name>` | `drafts.json` is a list of 2–3 `{label, beats:[{role, headline, claimIds?, spokenTalkTrack?, transitionIn?, transitionOut?, timeBudgetSeconds?, fallbackLine?, sourceRefs?, visualDescription?, isDemo?}]}`. `role` ∈ `HOOK\|STAKES\|TURN\|MECHANISM\|PROOF\|OBJECTION\|ASK`. ≤3 `claimIds` per beat. |
| `narrative select-route <routeId> --actor <name>` | |
| `narrative list` | |

#### Default candidate generation (FR-NAR-1)

`propose_throughlines` itself is unchanged — it only validates (exactly 3, non-empty) and
persists whatever drafts it is given; it never generates text (ARCH §8). Both public entry points
that call it, though, now fall back to `narrative.default_throughline_drafts(brief)` — the same
helper in both places — whenever the caller hasn't supplied its own three drafts (normally the
Skill Prompt Layer's job): the direct `narrative propose-throughlines` command with no `--input`
(or `{"drafts": []}`), and `run-scenario` with no `throughlineDrafts` field (or `"throughlineDrafts":
[]`) at all. The fallback is a pure, deterministic function of the talk brief's own fields
(takeaway, audience, proof points, tone) — always exactly 3 distinct, non-empty candidates, never
a static placeholder and never empty. Explicitly supplied drafts always take priority and are
completely unaffected. See `tests/test_default_throughline_generation.py`.

#### Default route generation (FR-NAR-3)

`propose_routes` itself is likewise unchanged — it only validates (2–3 drafts, ≥1 beat each) and
persists whatever it is given; it never generates beats. `run-scenario` falls back to
`narrative.default_route_drafts(brief, throughline, claims)` whenever a scenario supplies no
`routeDrafts`/`propose_route` entries of its own, but — unlike the throughline fallback above —
only when the same scenario has also actually ingested at least one source (i.e. a genuinely
*source-driven* run): a bare brief with no source context at all still supplies no default routes
and is still correctly refused `VALIDATION_ERROR: exactly 2 or 3 narrative routes are required
(got 0)`, exactly as before generation existed at all. This keeps FR-NAR-3's "two or three routes
appear and none auto-selects" intact: the fallback only proposes candidates — selection is a
wholly separate, unaffected step (`selectRouteIndex`/`selectRouteText`, defaulting to index 0 same
as always).

The fallback always returns exactly 2 real, brief/throughline-derived route drafts, each a full
7-beat spine that already satisfies the Narrative gate (one opening HOOK, one closing ASK, no two
adjacent beats sharing a role, low fixed per-beat time budgets that leave the required ≥10% time
buffer for any realistic brief duration, and headlines truncated to stay within the Compiler's own
length limit regardless of how long the brief/throughline text is). A PROOF beat citing the first
already-*approved*, verified-or-better factual claim among the scenario's own claims is included
only when one exists; otherwise that slot is a second STAKES beat instead — never an uncited PROOF
beat. See `tests/test_default_route_generation.py`.

In the true action-list executor (`_run_ordered_action_list`, see "Scenario document shape" below),
the identical fallback is instead triggered *lazily*, exactly once, by whichever of
`select_narrative_route`/`compile_deck`/`rehearse` — or, absent any of those, the automatic
end-of-walk finalization phase — is the first to actually need a route, rather than at any fixed
document position; a caller may still stage its own explicit `propose_route`/`routeDrafts`
action(s) first, in which case those are used instead and the fallback never runs. Proposing never
auto-selects: `report["route"]["candidates"]` is populated (with `"active": null`) the moment
`propose_routes` durably persists the candidates, immediately — *before* the selection step itself
is even attempted — so a later selection failure (an out-of-range `selectRouteIndex`, or any other
refusal further down the same walk) never erases already-persisted route candidates from the
caller-visible report; a successful selection then overwrites `"active"` with the now-selected
route. See `tests/test_ordered_route_persistence_and_finalization.py`.

### Compile (FR-NAR-4/5, FR-PPT-1/2)

| Command | Notes |
|---|---|
| `compile --actor <name>` | Blocked by `NARRATIVE_GATE_FAILED` unless the narrative gate passes. Produces 7–15 `SlideSpec`s, one per beat. Re-running after edits preserves accessibility metadata already set on unchanged slides. |

`run-scenario`'s action-list form also accepts `compile_deck`/`compile_presentation` (see "Action
vocabulary" below) — both are pure markers naming the identical `compile` step every scenario
already runs automatically and unconditionally once a route is selected; neither accepts any
inline payload, and neither gates, re-triggers, or reorders that automatic call.

### Slide (accessibility/demo, FR-DEL-4/5)

| Command | Notes |
|---|---|
| `slide list` | |
| `slide set-alt-text <slideId> <region> --text <t> --confirmed-by <name> --actor <name>` | Human-confirmed alt text; `region` is usually `visual`. |
| `slide set-reading-order <slideId> --order r1,r2,... --actor <name>` | Must be a total order over exactly the slide's regions. |
| `slide set-color-signal <slideId> <region> --uses true\|false [--indicator <t>] --actor <name>` | |
| `slide set-demo-asset <slideId> [--live][--prerecorded][--static][--verbal] --actor <name>` | All four required before Readiness passes for a demo slide. |

### Gate (FR-GATE-1..5)

| Command | Notes |
|---|---|
| `gate run scope\|evidence\|narrative\|claims\|readiness\|stage --actor <name>` | Fixed order enforced by `stage`, which re-runs every prior gate fresh. `stage` requires a non-empty `--actor`. |
| `gate status` | Latest cached `GateResult` per gate. |

### Export (FR-PPT-4/5, FR-DEL-6)

| Command | Notes |
|---|---|
| `export pptx [--render-mode normal\|panic] --actor <name>` | Standalone draft render to `exports/draft/`. Self-validates the zip before returning. |
| `export package --actor <name>` | Requires Stage to pass. Writes the full 9-artifact package + `manifest.json` under `exports/<timestamp>/`. |

`run-scenario`'s action-list `export` verb dispatches through these identical two calls — see
"Action vocabulary" below for the full `exportRequests` payload contract
(`tests/test_export_action.py`).

### Re-import (FR-PPT-6/7)

| Command | Notes |
|---|---|
| `reimport pptx --path <file> --actor <name>` | Diffs the file against the workspace's canonical regions; creates `PendingEdit`/`UnmatchedContentItem` rows. |
| `reimport list-pending [--status PENDING\|ACCEPTED\|DISCARDED]` | |
| `reimport accept <pendingEditId> --actor <name>` | Merges the edit; a single-claim `body` region reopens that claim via `rewrite`. |
| `reimport discard <pendingEditId> --reason <text> --actor <name>` | |
| `reimport list-unmatched` | |
| `reimport link-unmatched <unmatchedId> --slide-id <id> --region <role> --actor <name>` | Manual linking (FR-PPT-7). |

### Rehearse (FR-DEL-1..3, FR-M365-4)

| Command | Notes |
|---|---|
| `rehearse run --input timings.json [--skip-demos] --actor <name>` | `timings.json`: `{"<slideId>": <actualSeconds>}`. Result also carries `sourceChanges` (see below). |
| `rehearse record-qa --input qa.json --actor <name>` | `qa.json`: list of `{question, answer, claimIds[]}`; grounding is verified per-answer. |
| `rehearse propose-cuts --target-seconds <n>` | HOOK/ASK beats are never proposed for a cut. |

`run-scenario`'s action-list `set_rehearsal_timing`/`rehearse` entries accept one of three
slide-reference field names — `slideRole` (the original), or the new `slideId`/`slideOrder`
aliases (mirroring the same slideId/slideOrder/slideRole precedence accessibility/demo-asset
matching already uses) — paired with one of four duration field names — `seconds` (the original),
or the new `duration`/`durationSeconds`/`actualSeconds` aliases (`actualSeconds` mirrors `rehearse
run`'s own direct CLI timings-document field name verbatim). Exactly one of each is required; an
unexpected extra field, zero or two-plus recognized fields on either side, or a repeated resolved
key (in any alias combination) is a clean `VALIDATION_ERROR`. See
`tests/test_rehearsal_timing_aliases.py`.

#### `rehearse`'s widened rehearsal-subfeature vocabulary

`rehearse` is the one action-list verb naming ARCH's entire "Rehearse" command group (`rehearse
run`/`record-qa`/`propose-cuts`, FR-DEL-1/2/3, FR-M365-4), not just a `set_rehearsal_timing`
synonym — `set_rehearsal_timing` itself still only ever accepts the single narrow shape above.
`rehearse`'s own inline payload is classified, once, into exactly one of six mutually exclusive
sub-shapes (mixing fields from two different ones on the same element is a clean
`VALIDATION_ERROR`):

| Shape | Payload | Effect |
|---|---|---|
| Single per-slide timing | identical to `set_rehearsal_timing`'s shape above | one `rehearsalTimings` entry |
| Bulk timings wrapper | exactly one of `timings`/`slideTimings`/`rehearsal`/`run`/`value`, holding either a `{slideRef: seconds}` mapping (the exact `rehearse run --input timings.json` document shape) or a list of single-entry-shaped objects | every entry contributed into the identical `rehearsalTimings` dict |
| Aggregate total duration | exactly one of `totalSeconds`/`totalActualSeconds`/`actualDurationSeconds` (or a `Minutes`-suffixed variant of any of those, converted `* 60`) | allocated proportionally to each slide's own configured time budget (`rehearsal.distribute_total_duration`; an even split if every budget is zero) and fed into the identical per-slide `run_rehearsal` contract |
| Q&A pair | a `question` field (optionally `answer`/`claimIndices`), or a `qaPairs` wrapper list of such objects | contributed into the identical `qaPairs` list `record_qa` already targets |
| Cuts/shorter-variant request | exactly one of `targetSeconds`/`targetMinutes` (optionally alongside a redundant, must-be-truthy boolean marker: `requestCuts`/`shorterVariant`/`proposeCuts`) | feeds `compiler.propose_cuts`'s existing `target_seconds` contract; `report["rehearsal"]["proposedCuts"]`/`["cutsTargetSeconds"]` |
| Bare re-check | no fields at all, or exactly `reportSourceChanges`/`checkSourceChanges` (must be truthy) | triggers a `rehearsal.run_rehearsal` pass with an empty timings dict, purely so `sourceChanges` (below) still reports — timing is never required just to check for source drift |

An aggregate total duration may never be combined (anywhere else in the same document) with a
per-slide/bulk timing entry — ambiguous, which should win. Every duration value (per-slide, bulk,
aggregate, or a cuts target) is validated identically: a negative, non-finite (`NaN`/`inf`), or
non-numeric (including a bare `bool`) value is a clean `VALIDATION_ERROR`, never silently coerced
or handed to the domain layer. See `tests/test_rehearse_action_subfeatures.py`.

#### Source changes since rehearsal (FR-M365-4)

Every `run_rehearsal` result (both `rehearse run` and `run-scenario`'s own `report["rehearsal"]`)
also carries `sourceChanges`: a diff, by source `uri`, of the workspace's current active bundle
against the snapshot captured at the end of this same workspace's own most recent prior rehearsal.
A `uri` present now but not in that snapshot is `{"uri", "sourceId", "status": "added"}`; one
present in both with a different `contentHash` (re-ingested content — this mints a new source id
superseding the old one, per FR-SRC-5, so the diff is by `uri`, never the unstable id) is
`"changed"`; one in the prior snapshot but no longer active (retired, nothing superseding it) is
`"removed"`. A workspace's *first* rehearsal ever always reports `[]` — there is no prior snapshot
yet, so that call only establishes the baseline. See `tests/test_rehearsal_source_changes.py`.

### Restore (FR-DEL-7)

| Command | Notes |
|---|---|
| `restore list` | |
| `restore apply <restoreId> --actor <name>` | Snapshots current state first (itself reversible), then swaps in the target. |

### Audit (NFR-8)

| Command | Notes |
|---|---|
| `audit tail [--since <ISO-8601>]` | Append-only; no update/delete exists anywhere in this CLI. |

### Scenario runner (flagship black-box entry point)

Three accepted invocation forms — all call the exact same engine code path (`engine/scenario.py`),
so each is a first-class, fully-supported public interface:

```
run-scenario --scenario <scenario.json> --workspace <dir> [--export-dir <dir>]   # primary form
run-scenario --scenario <scenario.json> --out <dir>                              # legacy form
run-scenario --scenario <scenario.json>                                          # bare form
```

One complete, declarative, non-interactive pass end-to-end. See `tests/fixtures/scenarios/` for
working examples, `tests/test_scenario_local_happy_path.py` for the schema in use,
`tests/test_scenario_invocation_forms.py` for all three invocation forms and the refusal contract
below, and `tests/test_scenario_bare_invocation.py` for the bare form's default-root precedence
in full.

| Flag | Effect |
|---|---|
| `--workspace <dir>` | Uses `<dir>` as the workspace root (like `--workspace-root`, and takes precedence over it if both are given) **and** writes `<dir>/run-report.json`, unless `--out` is also given. |
| `--export-dir <dir>` | Optional. If Stage passes, the 9-artifact package is written directly into `<dir>` instead of the default location nested under the workspace root (`<workspace-root>/workspace/<workspaceId>/exports/<stamp>/`). Composable with any of the three forms. |
| `--out <dir>` | Legacy form. Writes `<dir>/run-report.json`; the workspace root is still whatever the global `--workspace-root` flag (or its defaults) resolves to. Still fully supported for backward compatibility. |

`--scenario <scenario.json>` (Dark Factory hardening cycle 12) also supplies `run_scenario`'s own
optional `scenario_path` — every invocation form's identical base context for resolving a
*relative* `local`-origin locator (`fixture`, `document`, `reference`, ...) against the scenario
document's own directory before falling back to the current working directory; see "Relative
fixture/locator resolution" under "Source" above.

**Bare form:** supplying neither `--workspace` nor `--out` is not an error — the workspace root
resolves via the exact same default-root precedence every other command uses (`--workspace-root`
/ `THROUGHLINE_WORKSPACE_ROOT` / `THROUGHLINE_HOME` / `~/.copilot/throughline`; see "Wire
contract" above), and `run-report.json` is written at that resolved root — a deterministic,
discoverable location derived purely from the same flags/env a caller already controls, with no
scenario-specific flag involved at all.

**Sequential invocation / resume:** a workspace's identity, for every `run-scenario` invocation
form, *is* its resolved store root (there is no separate `--id` the way `workspace resume` has).
A later call whose resolved root already has an active workspace (no `workspace reset` in
between) idempotently **resumes** that same workspace — reusing its `workspaceId`/`briefId` — and
continues the walk (accumulating sources/claims/etc. into the same curated bundle) rather than
trying, and always losing the race, to open a brand-new one. The report's own top-level
`workspaceResumed` boolean records which happened (`false` for the first call against a root,
`true` for every later one that resumes it). This is scoped only to `run_scenario`'s own opening
step: `workspace_mod.create_workspace` — used directly by `workspace new`, and by this same
opening step's own fallback when no workspace is active yet — is unaffected, and still refuses
`WORKSPACE_ALREADY_ACTIVE` for a genuinely new open attempt against an already-locked root
(NFR-2's exclusivity is never weakened). See `tests/test_sequential_scenario_resume.py`.

**Exit code / result document contract:** `run-scenario` exits `0` for every normal completion —
**including** a run in which a scenario step is correctly refused or blocked by a domain rule
(any `EngineError`, e.g. `BUNDLE_LIMIT_REACHED`, `CONFLICT_UNRESOLVED`, `CLAIM_UNSUPPORTED`, ...).
That refusal is never encoded as a nonzero exit code; it is always encoded in `run-report.json`
(and the `data` the CLI envelope emits) as:

```json
{"ok": false, "refusal": {"code": "BUNDLE_LIMIT_REACHED", "message": "...", "details": {}}, "steps": [ ... up to the point of refusal ... ]}
```

`report["ok"]` is `true` and `report["refusal"]` is `null` for a normal (non-refused) run — the
rest of the report (`preStageGates`, `stageGate`, `package`, etc., all documented by the fixtures
above) is populated exactly as it always has been, and is never rolled back by a *later* step's
refusal — every step already recorded up to that point (including, notably,
`report["throughline"]`'s three proposed candidates and whichever one is active, and
`report["route"]`'s own candidates/active selection once a route has been selected — see "Narrative
throughline reporting"/"Narrative route reporting" below) stays exactly as it was. Only a genuine
engine/runtime fault (anything that is *not* an `EngineError` — i.e. a real bug) still exits
nonzero, as `INTERNAL_ERROR`. A malformed `--scenario` document (see below) is likewise a clean
`VALIDATION_ERROR`, never a crash.

#### Narrative throughline reporting (FR-NAR-1/2)

As soon as a throughline is selected (whether by index, by text matching a proposed candidate, or
via a wholly new speaker-authored replacement), the report gains a `throughline` field:

```json
{"throughline": {
  "candidates": [{"id": "throughline:...", "text": "...", "origin": "proposed"}, ...],
  "active": {"id": "throughline:...", "text": "...", "origin": "proposed | custom"}
}}
```

`candidates` always lists the exact three proposed throughlines (FR-NAR-1); `active` is whichever
one was actually selected — `origin: "custom"` for a speaker-authored replacement (`"text"`/
`customThroughline` matching none of the three), `"proposed"` otherwise. Because this is recorded
immediately (before routes/compile/gates run), it survives — is never rolled back by — a later
step's refusal (e.g. missing narrative routes), exactly like the rest of the report. See
`tests/test_candidate_persistence_on_refusal.py`.

#### Narrative route reporting (FR-NAR-3)

As soon as a route is selected, the report likewise gains a `route` field, populated immediately
(before compile/gates run) so it survives a later step's refusal exactly like `throughline` above:

```json
{"route": {
  "candidates": [{"id": "route:...", "label": "...", "beatCount": 7}, ...],
  "active": {"id": "route:...", "label": "..."}
}}
```

`candidates` lists every proposed route (2 or 3, whether explicitly supplied or the source-driven
default — see "Default route generation" above); `active` is whichever one was actually selected.

#### Full persisted-workspace-state reporting (`_attach_workspace_state`)

Regardless of whether the walk completes cleanly or is correctly refused/blocked partway (see the
"Runs are always non-interactive and always complete" note in `engine/scenario.py`'s own module
docstring), the report always ends with a fresh read of every persisted, workspace-scoped
collection — attached right before the connection closes, so even a first-step refusal (e.g. a
rejected source) still surfaces whatever was durably committed up to that point, and a *resumed*
call's refusal still shows everything accumulated by every earlier call too:

```json
{
  "sources": [{"id": "source:...", "origin": "local", "source_type": "local_paste", "state": "AUTHORIZED", ...}, ...],
  "evidence": [{"id": "evidence:...", "locator": "...", "disposition": "KEEP", ...}, ...],
  "claims": [{"id": "claim:...", "type": "FACTUAL", "state": "APPROVED", "approver": "...", ...}, ...],
  "conflicts": [{"id": "conflict:...", "status": "OPEN | RESOLVED", ...}, ...],
  "throughlines": [{"id": "throughline:...", "text": "...", "origin": "proposed | custom"}, ...],
  "routes": [{"id": "route:...", "label": "...", "beats": [{"id": "beat:...", "role": "HOOK", ...}, ...]}, ...],
  "slides": [{"id": "slide:...", "role": "HOOK", "regions": {...}, ...}, ...],
  "restorePoints": [{"id": "restore:...", "trigger": "compile | export | gate:<name> | pre_revert", ...}, ...],
  "gateResults": [{"gate": "SCOPE", "passed": true, ...}, ...],
  "readiness": {"gate": "READINESS", "passed": true, ...},
  "auditEvents": [{"action": "source.ingest", ...}, ...],
  "workspace": {
    "id": "workspace:...", "phase": "PACKAGED", "deckId": "deck:...", "manifestId": "manifest:...",
    "activeThroughlineId": "throughline:...", "activeRouteId": "route:...",
    "stageApprovedBy": "...", "stageApprovedAt": "...", "lastRehearsalAt": "..."
  }
}
```

Notes:

- `sources`/`evidence`/`claims`/`conflicts`/`throughlines`/`routes`/`slides`/`restorePoints` are
  `models.to_jsonable` dumps of the underlying dataclasses, so their own nested field names are
  the model's own `snake_case` attribute names (e.g. `source_type`, `permission_state`,
  `is_demo`, `time_budget_seconds`) — distinct from the rest of this report's own hand-built
  camelCase step/summary fields (`sourceId`, `slideId`, ...).
  `sources` reflects the workspace's *entire* accumulated bundle, reloaded fresh on every call —
  not just whichever sources this particular call itself ingested — so it never needs a second
  query to discover what earlier sequential calls already persisted (`tests/test_sequential_
  scenario_resume.py`, `tests/test_multi_origin_source_accumulation.py`).
- `gateResults`/`auditEvents` existed before this hardening cycle but were previously only ever
  populated once, unconditionally, at the very end of a *clean* walk — so any refusal partway
  through left both silently empty even though real gate/audit history already existed. They are
  now attached the same way as every other collection here, and always reflect the true, current
  persisted history.
- `readiness` is the READINESS gate's own latest `GateResultRecord`, `None` if it has never run —
  a convenience top-level mirror of the identical entry already nested under `run_gate`'s/the
  automatic pipeline's own `preStageGates`/`gateResults`.
- `workspace` is a durable status summary (phase, deck/manifest/throughline/route ids, Stage
  approval, last rehearsal time) that always reflects the workspace's *current* persisted state —
  useful for discovering what a **prior** call already reached even when the current one's own
  walk never gets that far (e.g. a `pptx`-only export request on a scenario that never reaches
  Stage still reports `phase: "COMPILED"`, not silently omitted).
- A refusal raised before any workspace/connection ever existed (e.g. `WORKSPACE_ALREADY_ACTIVE`)
  has nothing to attach — none of these keys appear at all in that case, never a crash trying to
  read state that was never created.

See `tests/test_partial_state_report.py` for the full contract and
`tests/test_full_manual_journey.py` for a complete, real journey exercising every field above at
once.

#### Top-level report compatibility aliases (Dark Factory hardening cycle 7)

`engine.models.add_report_compat_aliases` additionally adds top-level snake_case aliases for
public callers that expect a snake_case name instead of (or alongside) an established camelCase
report field — applied to every `run_scenario` report (both the returned/envelope-wrapped `data`
and the written `run-report.json` file on disk) and, generically, to every other command's own
`data` too (`cli.main`'s `emit()`):

| Established field | Snake_case alias/aliases |
|---|---|
| `sources` | `source_ledger` |
| `evidence` | `evidence_atoms` |
| `conflicts` | `conflict_cards` |
| `gateResults` | `gate_results`, `gates` |
| `auditEvents` | `audit_trail`, `audit_events` |
| `throughlines` | `candidate_throughlines` |
| `routes` | `narrative_routes` |
| `restorePoints` | `restore_points` |
| `package` | `export` |
| `workspaceId` / `workspace.id` | `workspace_id` |
| `deckId` / `package.deckId` / `workspace.deck_id` / `workspace.deckId` | `deck_id` |

Every alias is a direct reference to the identical, already-computed value already sitting under
its established name — never a duplicate computation or a fabricated value — and is added only
when that established name is actually present, so a report that never reached far enough to
populate a given collection (e.g. a refusal before any workspace/connection existed) carries
neither the established name nor its alias, exactly as before. `slides`, `claims`, `readiness`,
`rehearsal`, and `qa` already read as snake_case-compatible and need no separate alias. See
`tests/test_report_top_level_compat_aliases.py`.

#### Compatibility action-results ledger: `actionResults` / `action_results`

Every `run_scenario` report also gains an `actionResults`/`action_results` list so a caller can
scan a single ledger for every attempted action's outcome, success or failure, without separately
cross-referencing `report["refusal"]`. Its exact shape depends on which document shape drove the
walk (see "Scenario document shape" below):

- **Object-form/field-list-form** (`_run_steps`'s pre-existing batch path, unchanged by Dark
  Factory hardening cycle 8): a read-only copy of `report["steps"]` (each entry additionally
  tagged `"ok": true`), with one trailing entry appended for the walk's own final refusal, if any
  (`{"action": "scenario.refusal", "ok": false, "error": {...}}`). `report["steps"]` itself is
  completely unchanged.
- **True action-list form** (every element names an explicit `"action"` verb — the ordered
  executor, hardening cycle 8): one entry *per original document element*, in the caller's own
  order, each carrying at least `index` (that element's position in the document), `action` (its
  own `"action"` verb, verbatim), `status` (`"completed"`, `"refused"`, `"blocked"`, or `"failed"`
  — a finer, additive classification of ARCH §12's single `BLOCKING` severity), and `ok` (`true`
  iff `status == "completed"`, kept for the identical backward-compatible shape the other path
  uses). A non-`"completed"` entry also carries `error` (`{"code", "message", "details"}`, the
  identical shape `EngineError.to_dict()` always produces); a `"completed"` one carries whichever
  created/updated id(s) that action's own domain call produced (`sourceIds`, `claimId`,
  `throughlineId`, `routeId`, `gate`/`passed`, ...). A domain refusal/block stops the walk (the
  same "normal, zero-exit-code completion" contract as every other shape — see below), but every
  element before the failing one keeps its own `"completed"` entry, and the failing element itself
  still gets exactly one entry (`status` reflecting *why* it stopped) — an element never reached at
  all (the walk already stopped before it) has no entry. `report["steps"]` is *also* populated for
  this path, using the exact same rich, per-domain-effect shapes (`source.ingest`,
  `evidence.extract`, `claim.propose`, ...) the batch path already produces, for full backward
  compatibility with every existing consumer of that field. If no explicit action ever fails but
  the mandatory automatic end-of-walk phase (pending default-route generation, compile, pre-Stage
  gates, rehearsal, or the Stage gate/package export) is the one that is refused/blocked instead,
  exactly one further entry is appended one index past the last real element, `action:
  "scenario.tail"` — built from this run's own authoritative, already-persisted state (never a
  second, independently re-derived object-form batch), and never both that entry *and* an earlier
  explicit action's own failing entry for the identical run: a domain refusal anywhere in the main
  per-action walk stops it immediately, so the tail phase below is only ever reached when every
  explicit action already completed. See
  `tests/test_ordered_action_list_execution.py` and `tests/test_report_top_level_compat_aliases.py`,
  and `tests/test_ordered_route_persistence_and_finalization.py` for `scenario.tail`'s own
  no-duplicate-refusal coverage.

#### Scenario document shape: object-form, field-list form, or action-list form

`--scenario <scenario.json>` accepts any of three wire-compatible shapes:

- **Object-form** (documented shape used throughout this reference and the fixtures): a single
  JSON object, e.g. `{"actor": "...", "sources": [...], "claims": [...], ...}`.
- **Field-list form** (accepted for black-box callers that emit an ordered sequence instead of a
  keyed object): a JSON array whose every element is an object naming exactly one top-level field,
  e.g. `[{"actor": "..."}, {"sources": [...]}, {"claims": [...]}, ...]`. Elements are merged, in
  list order, into the identical object-form dict (`engine.scenario._normalize_scenario_doc`). See
  `tests/fixtures/scenarios/local_happy_path_list_form.json` for the field-list-form equivalent of
  the canonical `local_happy_path.json` fixture.
- **Action-list form** (accepted for black-box callers that tag each element with an explicit,
  canonical action verb instead of using a field name as the element's only key): a JSON array
  whose elements each carry an `"action"` field naming exactly one of the allowlisted public verbs
  in the "Action vocabulary" table below, plus that action's own payload inlined as the element's
  *other* keys, e.g. `{"action": "ingest_source", "uri": "...", "origin": "..."}`. **The action
  verb is never a raw object-form field name** — `{"action": "brief", ...}` is a `VALIDATION_ERROR`
  (unknown action); the field it targets is set via `{"action": "set_talk_brief", ...}` instead.
  See `tests/fixtures/scenarios/local_happy_path_action_list.json` for the action-list-form
  equivalent of the same canonical fixture, and `tests/test_scenario_action_list_form.py` for the
  full contract.

  **Execution order (Dark Factory hardening cycle 8).** Object-form and field-list-form documents
  have no per-element sequence to preserve (a single JSON object's fields aren't ordered, and
  field-list elements are only ever merged into that same object) — both keep driving
  `_run_steps`'s own pre-existing, unchanged batch walk (brief/sources, then source-lifecycle
  transitions, then claims, then conflicts, then narrative, then routes, then compile, then
  accessibility/demo, then gates, then rehearsal, then stage/package). A **true action-list
  document** — every element names an explicit `"action"` verb — is different: it *does* carry a
  real, caller-authored sequence, and is executed exactly that way, by
  `engine.scenario._run_ordered_action_list`. Every element is dispatched, one at a time, straight
  from the original document, in original order, directly against the identical already-existing
  domain calls the batch path and the granular CLI subcommands both use (never a second
  business-logic implementation) — so a repeated verb (26 `add_source` actions, an interleaved
  `run_gate` before *and* after more sources are added, a source revoked partway through, a claim
  proposed after some evidence and before more, ...) executes and durably persists once per
  occurrence, immediately visible to every action after it, and a gate/export/claim check reflects
  the caller's own *true, partial* state at that exact point in the sequence — not only the fully-
  processed final state a fixed-order batch can ever see. A correctly-refused/blocked element stops
  the walk (the same "normal, zero-exit-code completion, refusal recorded in the result document"
  contract every shape shares — see the module docstring in `engine/scenario.py`), but every
  element before it is already durably persisted and is still reported. Two narrative
  domain calls (`propose_throughline`'s exactly-3-drafts and `propose_route`'s exactly-2-or-3
  routes, FR-NAR-1/FR-NAR-3) only ever accept one fixed-size batch, not a single item at a time —
  repeated `propose_throughline`/`propose_route` actions accumulate their drafts and submit them
  together in the one call each already requires, made the moment a selection is actually needed
  (an explicit `select_throughline`/`select_route`-family action, or the end-of-walk default
  exactly like the batch path already falls back to). See
  `tests/test_ordered_action_list_execution.py` for 26 repeated source additions, interleaved
  source-lifecycle transitions, repeated claim proposals, gate order, partial-refusal persistence,
  and a complete manual journey exercising this ordered executor end to end.

  Field-list and action-list elements may still be freely mixed in the same document (each element
  is dispatched independently by shape, does it have an `"action"` key or not) — such a mixed
  document is not a *true* action-list document (not every element names an `"action"` verb), so it
  keeps using the unchanged batch path above, exactly as before this hardening cycle.

  #### Action vocabulary

  Every accepted verb is derived conservatively from this repository's own existing domain
  vocabulary (`engine/scenario._ACTION_ALIASES` is the authoritative, allowlisted source) — most
  mirror an existing CLI subcommand name verbatim (paired with its command group's noun), and the
  rest use the fuller PRD/ARCH entity or phrase where the CLI's own group noun is a shorthand for
  it (e.g. `brief set` → `set_talk_brief`, never bare `"brief"`, since the PRD/ARCH entity is
  `TalkBrief` / "the talk brief" — FR-INV-1, ARCH §1 step 1). Every field has exactly one verb
  except four deliberate compatibility synonyms: `sources` (`ingest_source`, the original verb,
  and `add_source`, the public alias), `selectRouteIndex` (`select_route`, the original verb, and
  `select_narrative_route`, the public alias — see below, it also uniquely accepts a `"text"`
  selector), `rehearsalTimings` (`set_rehearsal_timing`, the original verb, and `rehearse`, the
  public alias), and `compileRequested` (`compile_deck` and `compile_presentation`, two equally
  common public names for the one deck-compilation marker) — each group drives the identical
  underlying code path, never a second one:

  | Action verb | Target field | Derived from |
  |---|---|---|
  | `set_actor` | `actor` | cross-cutting run-scenario input (every command's own `--actor`) |
  | `set_talk_brief` | `brief` | `brief set` + the `TalkBrief` entity/"the talk brief" phrase |
  | `ingest_source` | `sources` | `source ingest` |
  | `add_source` | `sources` | `source ingest` (public alias/synonym for `ingest_source` above) |
  | `set_evidence_disposition` | `evidenceOverrides` | `evidence set-disposition` |
  | `set_default_evidence_disposition` | `evidenceDefaultDisposition` | default policy for the above |
  | `propose_claim` | `claims` | `claim propose` |
  | `resolve_conflict` | `conflictDecisions` | `conflict resolve` |
  | `propose_throughline` | `throughlineDrafts` | `narrative propose-throughlines` |
  | `select_custom_throughline` | `customThroughline` | `narrative select-throughline --text` |
  | `select_throughline` | `selectThroughlineIndex` / `selectThroughlineText` (see below) | `narrative select-throughline --id`/`--text` |
  | `propose_route` | `routeDrafts` | `narrative propose-routes` |
  | `select_route` | `selectRouteIndex` | `narrative select-route` |
  | `select_narrative_route` | `selectRouteIndex` / `selectRouteText` (see below) | `narrative select-route` (public alias/synonym for `select_route`, named after the `NarrativeRoute` entity) |
  | `set_alt_text` | `accessibility` | `slide set-alt-text` |
  | `set_auto_alt_text` | `autoAltText` | automatic alt-text toggle for the above |
  | `set_demo_asset` | `demoAssets` | `slide set-demo-asset` |
  | `set_rehearsal_timing` | `rehearsalTimings` | `rehearse run`'s per-slide timings input |
  | `rehearse` | `rehearsalTimings` | `rehearse run` (public alias/synonym for `set_rehearsal_timing` above) |
  | `skip_demos` | `skipDemos` | `rehearse run --skip-demos` |
  | `record_qa` | `qaPairs` | `rehearse record-qa` |
  | `approve_stage` | `stageApprover` | `gate run stage --actor <name>` (ARCH §1 step 13) |
  | `run_gate` | `gateRuns` | `gate run <name>` — explicitly, additionally invokes one named gate through the existing `gates.run_gate` logic (see below); purely additive, never a substitute for the mandatory automatic gate pipeline every scenario already runs |
  | `compile_deck` | `compileRequested` | `compile` — a pure marker naming the identical automatic compile step every scenario already runs; never a substitute for, or a re-trigger of, that unconditional call |
  | `compile_presentation` | `compileRequested` | `compile` (public alias/synonym for `compile_deck` above) |
  | `export` | `exportRequests` | `export pptx`/`export package` — each element is one explicit export request, dispatched through the identical, already-existing `package.export_pptx_draft`/`package.export_package` calls; see its own paragraph below |
  | `revoke_source` | `sourceRevocations` | `source revoke` |
  | `quarantine_source` | `sourceQuarantines` | `source quarantine` |
  | `resolve_source_hold` | `sourceHoldResolutions` | `source resolve-hold` |
  | `retire_source` | `sourceRetirements` | `source retire` |

  Every target field accepts exactly one action-list payload shape, with four exceptions —
  `select_throughline`, `select_narrative_route`, `ingest_source`/`add_source`'s own `sources`
  field, and `rehearse`'s own widened vocabulary (see "`rehearse`'s widened rehearsal-subfeature
  vocabulary" under "Rehearse" above), each described in their own paragraph:

  | Field(s) | Shape | One action-list element looks like |
  |---|---|---|
  | `evidenceOverrides`, `claims`, `conflictDecisions`, `routeDrafts`, `accessibility`, `demoAssets`, `qaPairs`, `gateRuns`, `exportRequests` | list of objects | `{"action": "propose_claim", "type": "factual", "text": "...", ...}` — every non-`action` key becomes one appended list item (also accepts a `params`/`payload`/`input`/`source`/`descriptor`/`value` wrapper — see below). May repeat any number of times. `run_gate`'s own item is exactly one non-empty gate-name field — `"gate"` (documented), or the `gateName`/`gate_name` aliases (one of `scope`\|`evidence`\|`narrative`\|`claims`\|`readiness`\|`stage`) — an unrecognized name is the identical `VALIDATION_ERROR` a direct `gate run <name>` CLI call already raises; it additionally accepts the shared named-approver alias vocabulary (`approver`/`approver_name`/`approverName`/`actor`/`human`/`name`, or a nested `approval`/`approver` object — Dark Factory hardening cycle 9) to name who performs *that* gate run, defaulting to the whole-document actor when none is given. `propose_claim`'s own `approve: true` flag accepts the identical vocabulary (not just its documented `approver` key) to name that claim's approver. `export`'s own item accepts a wide alias/wrapper vocabulary — see its own paragraph below. |
  | `sourceRevocations`, `sourceQuarantines`, `sourceHoldResolutions`, `sourceRetirements` | list of objects | `{"action": "revoke_source", "uri": "..."}` (or `sourceId`/`source_id`/`sourceUri`/`source_uri`) — see "Source lifecycle actions" below. |
  | `sources` | list of objects (widened — see below) | `{"action": "ingest_source", "uri": "...", "origin": "...", ...}` — every non-`action` key becomes one appended source descriptor. `add_source`/`ingest_source` may be freely mixed across elements — both append into the same `sources` list. `origin` may be omitted entirely — see "Originless source classification" above. |
  | `throughlineDrafts` | list of bare strings | `{"action": "propose_throughline", "value": "..."}` — the item goes in a reserved `"value"` field (no other fields allowed). May repeat. Omitting `propose_throughline` entirely falls back to 3 deterministic, brief-derived candidates rather than an empty list — see "Default candidate generation" above. |
  | `brief` | single object | `{"action": "set_talk_brief", "audience": "...", "eventType": "...", ...}` — every non-`action` key *is* the brief object outright (also accepts a `params`/`payload`/`input`/`source`/`descriptor`/`value` wrapper — see below). At most once. |
  | `rehearsalTimings` | key/value pair for `set_rehearsal_timing`; six mutually exclusive sub-shapes for `rehearse` (see "Rehearse" above) | `{"action": "set_rehearsal_timing", "slideRole": "HOOK", "seconds": 58}` (or, identically, `{"action": "rehearse", "slideRole": "HOOK", "seconds": 58}`, or any of the widened `slideId`/`slide_id`/`slideOrder`/`slide_order`/`duration`/`durationSeconds`/`duration_seconds`/`actualSeconds`/`actual_seconds`/`actualMinutes`/`actual_minutes` alias combinations — the `Minutes`-suffixed value alias is converted `* 60` — a bulk `timings`/`slideTimings`/`slide_timings`/`rehearsal`/`run`/`value` wrapper, an aggregate `totalSeconds`/`totalMinutes`-style total (each with a `total_seconds`/`total_minutes`-style snake_case sibling), a Q&A pair (`claimIndices`/`claim_indices`, a `qaPairs`/`qa_pairs` wrapper), a cuts target (`targetSeconds`/`target_seconds`/`targetMinutes`/`target_minutes`), or a bare re-check) — a repeated resolved key (via any alias combination, either verb) is a `VALIDATION_ERROR` (ambiguous). |
  | `actor`, `evidenceDefaultDisposition`, `customThroughline`, `selectRouteIndex`, `autoAltText`, `skipDemos`, `stageApprover` | single primitive | `{"action": "set_actor", "value": "Jane Doe"}`, or (redundantly, also accepted) a field with the *target field's own name*, e.g. `{"action": "approve_stage", "stageApprover": "Jane Doe"}` — `stageApprover` additionally accepts the full shared named-approver alias vocabulary (`approverName`/`approver_name`/`approver`/`actor`/`human`/`name`, or a nested `approval`/`approver` object, e.g. `{"action": "approve_stage", "approver": {"name": "Jane Doe"}}` — Dark Factory hardening cycle 9). Supplying more than one of these keys with *different* values is a `VALIDATION_ERROR` (ambiguous); a nested object naming none of the recognized fields is also a `VALIDATION_ERROR`. At most once — a repeat via *either* form is the same `VALIDATION_ERROR` a repeated field-list field already raises. |
  | `compileRequested` | no payload at all | `{"action": "compile_deck"}` (or, identically, `{"action": "compile_presentation"}`) — neither verb accepts any inline field; any field at all is a `VALIDATION_ERROR`, since there is nothing for either to configure. |

  #### Common action payload wrappers: `params`/`payload`/`input`/`source`/`descriptor`/`value`

  Any "list of objects" or single-"object" action-list element above (`propose_claim`,
  `set_talk_brief`, `set_alt_text`, ...) may also wrap its entire inline payload in one of these
  reserved container keys instead of giving its fields directly on the element itself, e.g.
  `{"action": "propose_claim", "payload": {"type": "factual", "text": "..."}}` — unwrapped only
  when the element has *exactly* that one key and its value is itself an object (an empty object
  unwraps to `{}`, so the field's own "no inline payload fields" validation still reports it
  plainly); a wrapper key alongside any sibling field is left completely alone (never a partial/
  ambiguous unwrap). `ingest_source`/`add_source` instead uses a fully general, structural
  discovery mechanism of its own (see below) rather than this fixed six-key list. See
  `tests/test_generic_action_payload_wrappers.py`.

  #### `ingest_source`/`add_source`'s payload: direct fields, or fields nested inside *any* container (Dark Factory hardening cycle 11)

  Unlike every other "list of objects" field above (which only ever unwraps the fixed
  `params`/`payload`/`input`/`source`/`descriptor`/`value` container keys — see above), one
  `ingest_source`/`add_source` action-list element accepts its contributed source descriptor(s)
  nested inside a container of **any name at all** — discovered structurally, never by matching a
  fixed/guessed wrapper-key allowlist. A key is an eligible container purely by what it carries: a
  non-empty object (or a non-empty list of non-empty objects) that itself carries — directly, or
  through further such containers — at least one recognized locator/content/type/auth metadata
  leaf key (`uri`/`url`/`href`/`link`/`path`/`file`/`filename`/`name`/`title`/`content`/`text`/
  `body`/`transcript`/`sourceType`/`source_type`/`type`/`kind`/`format`/`mime`/`mimeType`/
  `origin`/`connector`/`provider`/`access`/`authorized`/`permission`/`label`/`owner`/`author`, or
  any of their already-recognized field-name aliases below — including this hardening cycle's own
  wider `locator`/`fixture`/`artifact`/`document`/`upload`/`reference`/`ref`/`source_kind`/
  `document_type`/`artifact_type` family; see "Source descriptor field-name aliases" above). A key
  that is itself one of these leaves is never treated as a container. Never more than one shape
  combined on the same element (a container key alongside a sibling direct field, two-or-more
  competing container keys, or `"sources"` alongside anything else, is a clean `VALIDATION_ERROR`,
  ambiguous):

  - **Direct fields** (documented, unchanged): the payload's own keys *are* the `FetchResult`
    fields, e.g. `{"action": "ingest_source", "uri": "...", "origin": "..."}`.
  - **A container of any name** (e.g. `{"source": {...}}`, `{"descriptor": {...}}`, or an
    arbitrary `{"envelope": {...}}`/`{"thirdPartyRecord": {...}}`): whose value is itself the
    nested `FetchResult`-shaped object, e.g.
    `{"action": "add_source", "envelope": {"uri": "...", "origin": "...", ...}}`.
  - **A list under any name** (e.g. `{"sources": [...]}`, or an arbitrary `{"batch": [...]}`):
    every item is contributed, in order, so one action-list element can add several sources at
    once, e.g. `{"action": "add_source", "batch": [{"uri": "a", ...}, {"uri": "b", ...}]}`.
    `"sources"` (documented, unchanged) is the one literal wire field name with its own explicit
    non-empty-list contract; any *other* name works identically once it structurally qualifies.
  - **A bare scalar** (no container at all): a lone, otherwise-unrecognized field whose value is a
    plain string is itself resolved as a locator (already URI-/path-/filename-shaped, e.g.
    `{"action": "add_source", "reference": "notes.md", ...}`) or, only when accompanied by a
    `sourceType`/`title`/`filename`/`file`/`name` sibling hint, as inline `content` (see
    `engine.ingest._apply_bare_scalar_field_hint`).
  - **Two-or-more eligible containers at the same level**: each is fully resolved and scored (a
    real locator, or inline content plus a filename/type/title hint) — exactly one meeting that
    bar is used silently (an incidental, signal-free sibling is never a real competitor); two or
    more meeting it, or none at all, is a clean `VALIDATION_ERROR` naming the candidates, never a
    silent pick.
  - **A lone, otherwise-eligible-looking key whose own object/list value carries no recognized
    signal at all** (Dark Factory hardening cycle 12, e.g. `{"action": "add_source",
    "myWeirdField": {"blob": "xyz"}}` with nothing else): a clean, dedicated `VALIDATION_ERROR`
    naming that field — never silently reinterpreted as a source (an arbitrary object/name is
    never accepted merely for having *a* name), and never left to fail downstream with a generic,
    confusing `origin`/`uri` error either — unless this same element's *other* fields already
    stand on their own, in which case the unrelated, incidental field is left completely alone
    (see `engine.scenario._check_signal_free_source_descriptor_candidate`).

  Whichever shape is used, each contributed descriptor also accepts the full "Source descriptor
  field-name aliases" table under "Source" above (`path`/`source_uri`/`sourceUri`/`local_path`/
  `localPath`/`url`/`href`/`web_url`/`link` → `uri`, `type`/`source_type`/`kind`/`format`/`mime`/
  `mimeType` → `sourceType`, `author` → `owner`, `access`/`access_state`/`accessState` →
  `permissionState`, `permission_snapshot`/`permissionSnapshot` → `aclSnapshot`,
  `label`/`label_state`/`labelState` → `sensitivityLabel`, `authorized_at`/`authorizedAt` →
  `retrievedAt`, `text`/`body`/`transcript` → `content`, `connector`/`provider` → `origin`) — an
  alias only ever *fills in* a field that is otherwise absent, never overrides an explicit
  canonical-named value already present; `connector`/`provider` are resolved through the identical
  `origin` allowlist/conflict-detection an explicit `origin` field already uses, so a
  connector/provider hint that outright contradicts the descriptor's own `sourceType`/`uri` is
  refused exactly like a contradictory explicit `origin` already is. Every other key (e.g. a
  caller-supplied `title`, which has no dedicated engine field) passes through completely
  untouched — no source metadata is ever silently dropped. See
  `tests/test_source_action_list_payload_wrappers.py`,
  `tests/test_source_payload_key_compatibility.py`, and
  `tests/test_structural_source_descriptor_extraction.py`.

  #### Nested container depth (Dark Factory hardening cycle 10/11)

  Any of the container/list shapes above may itself nest arbitrarily deeper, under any further
  container name — e.g. `{"action": "add_source", "thirdPartyEnvelope": {"attachment":
  {...real fields...}}}`, or a `sources`/arbitrary-named list entry that is itself another
  container — `engine.scenario._unwrap_nested_source_descriptor` peels through every layer, all the
  way down, before connector/origin inference or field-alias normalization ever sees the
  descriptor. Only the *outermost* shape choice (the element's own top-level payload) follows the
  strict single-shape rule above (a container key alongside a sibling field, or two-or-more
  competing container keys, is always ambiguous there); a container key at a level *underneath*
  that first choice may additionally coexist with genuine sibling metadata — the two merge into
  one flat descriptor (or, for a container resolving to a list, into every one of its items alike),
  and a sibling value that conflicts with the container's own resolved value for the same field
  name is a clean `VALIDATION_ERROR`. The original public descriptor (with any inline
  `content`/`text`/`body`/`transcript` redacted) is preserved under `rawPayload`
  (`report["actionResults"]`) / `rawDescriptor` (`report["steps"]`'s `source.ingest` entry) so this
  normalization stays auditable, for both an accepted and a refused/held attempt alike. See
  `tests/test_deep_source_descriptor_unwrapping.py` and
  `tests/test_structural_source_descriptor_extraction.py`.

  #### Source lifecycle actions: `revoke_source`, `quarantine_source`, `resolve_source_hold`, `retire_source`

  Four action-list verbs invoke the identical, already-existing `ingest.revoke_access`/
  `ingest.quarantine_source`/`ingest.resolve_hold`/`ingest.retire_source` calls the CLI's own
  granular `source revoke`/`source quarantine`/`source resolve-hold`/`source retire` subcommands
  use — never a second lifecycle code path, and never a bypass of any of their existing
  state-machine checks. Since a declarative one-pass scenario cannot know a source's
  server-generated id ahead of time merely from staging its own `add_source`/`ingest_source` step
  earlier in the same document, each request may instead name its target source by the `uri` it
  was ingested under (resolved to that uri's current active source, first against sources ingested
  earlier in the same walk, then — for a resumed workspace — against the persisted ledger):

  - `revoke_source`: `{"action": "revoke_source", "uri": "..."}` (or `sourceId`/`source_id`/
    `sourceUri`/`source_uri`) — marks `ACCESS_REVOKED`; cascades to dependent evidence/claims
    exactly like `source revoke` already does.
  - `quarantine_source`: `{"action": "quarantine_source", "uri": "...", "reason": "..."}` —
    `reason` is required and non-empty.
  - `resolve_source_hold`: `{"action": "resolve_source_hold", "uri": "...", "decision":
    "authorize"|"retire"}` — resolves a `PARSE_FAILED`/`LABEL_CONFLICT`/`QUARANTINED` hold; a
    source not currently held is the identical `VALIDATION_ERROR` a direct `source resolve-hold`
    CLI call already raises.
  - `retire_source`: `{"action": "retire_source", "uri": "..."}` — frees the source's bundle slot.

  Supplying both an id and a uri, conflicting values for the same reference kind, neither, or a
  uri matching no active source is always a clean `VALIDATION_ERROR`/`NOT_FOUND`, never a guess.
  Each successful request is recorded as its own `report["steps"]` entry (`source.revoke`/
  `source.quarantine`/`source.resolve_hold`/`source.retire`). See
  `tests/test_source_lifecycle_scenario_actions.py`.

  #### `export`'s payload: `target` (`pptx` vs `package`) and its widened alias/wrapper vocabulary (Dark Factory hardening cycle 9)

  One `export` action-list element is one explicit export request, executed through the identical,
  already-existing `package.export_pptx_draft`/`package.export_package` calls the CLI's own
  `export pptx`/`export package` subcommands use — never a second export code path, and never a
  bypass of either function's own existing gate/named-approval checks:

  - `target` (required, or a field-name alias — see below) names which existing export path to
    run: `"pptx"` (or the `"deck"`/`"draft"`/`"pptx_draft"`/`"deck_export"` aliases, any
    case/hyphen spelling) runs the standalone draft render (`export pptx`) — usable any time after
    compile, independent of Stage; `"package"` (or the `"stage"`/`"stage_package"`/`"stagepackage"`
    aliases) runs the full 9-artifact Stage package (`export package`) — this always re-runs the
    real Stage gate itself, so a `package` request when Stage has not passed is refused with the
    identical, pre-existing `GATE_NOT_PASSED` `EngineError` (a structured `report["refusal"]`, exit
    0, never a bypassed gate or a crash). The target concept itself may be named via `target`,
    `format`, `kind`, `type`, or `mode` (conservative field-name synonyms, each resolved through
    the identical value table above) — or, with no such field at all, a truthy boolean-ish
    *wrapper* field naming the target directly: `pptx: true` (target `pptx`) or
    `stagePackage: true`/`stage_package: true` (target `package`). Two of these naming genuinely
    *different* targets (whether two field names, or a field plus a wrapper) is an explicit
    `VALIDATION_ERROR`; naming the identical resolved target more than once is redundant, not
    ambiguous.
  - `renderMode`/`render_mode` (optional, `pptx` target only) is `"normal"` (default) or `"panic"`.
  - `outputDir`/`output_dir`/`exportDir`/`export_dir`/`output`/`path`/`directory`/`out_dir`
    (optional, `package` target only — `pptx` has no such override anywhere in the domain layer
    and rejects one as a `VALIDATION_ERROR`, exactly like the CLI's own `export pptx` subcommand)
    overrides the directory the package's files are written into, exactly like `run-scenario`'s
    own top-level `--export-dir` flag. Two aliases naming genuinely different paths is a
    `VALIDATION_ERROR`.
  - `actor`/`approver`/`approverName`/`approver_name`/`human`/`name` (optional; or a nested
    `approval`/`approver` object, e.g. `{"approval": {"approver": "Jane Doe"}}`) names who
    performs *this* export — defaults to the scenario's own `stageApprover`/actor, the identical
    named-human-approval actor the automatic end-of-walk Stage export (below) already uses.

  Every successful request is appended to a new `report["exports"]` list (in element order),
  alongside the existing `report["package"]` field (still populated, unchanged, by the mandatory
  automatic Stage-package export whenever Stage passes — `export` requests are purely additive,
  never a substitute for it). An unrecognized target value, a genuine conflict between two
  target/output-directory aliases, an unexpected field, or an invalid
  `renderMode` is a clean `VALIDATION_ERROR`. See `tests/test_export_action.py`,
  `tests/test_rehearsal_export_gate_snake_case_aliases.py`, and
  `tests/test_named_approver_and_export_field_alias_compatibility.py`.

  #### `select_throughline`'s payload: `value` / `selectThroughlineIndex` / `choice` / `text`

  Unlike every other action above, `select_throughline`'s inline payload may name its selector via
  any of **four** keys, resolving into one of *two* different object-form fields depending on
  which kind of key was used — never a single fixed field:

  - A **numeric** selector — `"value"`, `"selectThroughlineIndex"` (the two original, still fully
    supported synonyms), or the new `"choice"` alias — is stored into `selectThroughlineIndex`
    exactly as before: `{"action": "select_throughline", "choice": 1}`. Several of these keys may
    be given together only if they agree; disagreeing values, or a non-integer value, are a
    `VALIDATION_ERROR`.
  - The new `"text"` alias — `{"action": "select_throughline", "text": "Draft two"}` — is instead
    stored into a new field, `selectThroughlineText`, resolved once the real candidates exist
    (`run_scenario`'s `_resolve_throughline_selection`): text matching a proposed candidate's own
    text verbatim selects *that* candidate by id (never a redundant duplicate); text matching none
    becomes a brand-new custom throughline, identical to `select_custom_throughline`.
  - Supplying both a numeric selector and `"text"` together, an unexpected extra field, no
    selector at all, or using the action twice (in any combination of selector kinds) is a clean
    `VALIDATION_ERROR`. An out-of-range numeric index, or `"text"` matching more than one
    candidate, is only detectable once the real candidates exist, so it surfaces as a normal,
    correctly-refused mid-walk step instead (result document + exit 0), exactly like any other
    domain refusal — never a raw crash.

  See `tests/test_throughline_selector_aliases.py` for the full contract. Selecting the
  throughline also always populates the report's own `throughline` field (candidates + active
  selection) — see "Narrative throughline reporting" above.

  #### `select_narrative_route`'s payload: `value` / `selectRouteIndex` / `choice` / `text`

  Mirrors `select_throughline`'s own numeric/text contract, for the parallel route-selection
  field — with one deliberate difference: a route is a full beat spine, never freeform text, so
  there is no "custom route" fallback.

  - A **numeric** selector — `"value"`, `"selectRouteIndex"`, or `"choice"` — is stored into
    `selectRouteIndex`, exactly the pre-existing field `select_route` already targets:
    `{"action": "select_narrative_route", "choice": 1}`.
  - `"text"` — `{"action": "select_narrative_route", "text": "Primary route"}` — is stored into a
    new field, `selectRouteText`, resolved once the real candidate routes exist
    (`run_scenario`'s `_resolve_route_selection`): text matching a candidate route's own `label`
    verbatim selects that route by id. Text matching none (or more than one) of the candidate
    routes' labels is a clean, correctly-refused `VALIDATION_ERROR` — never a guessed/synthesized
    route, since (unlike a throughline) there is nothing to fall back to.
  - Supplying both a numeric selector and `"text"` together, an unexpected extra field, no
    selector at all, a non-integer numeric value, or repeating the selection (via either
    `select_route` or `select_narrative_route`, in any combination) is a clean `VALIDATION_ERROR`.
    An out-of-range numeric index is only detectable once the real routes exist, so it surfaces as
    a normal, correctly-refused mid-walk step instead (result document + exit 0) — never a raw
    crash.

  See `tests/test_narrative_route_selector_aliases.py` for the full contract.

Any other document shape — neither a JSON object nor a list of non-empty objects, a list element
that names neither exactly one top-level field nor a recognized `"action"`, an action element
naming an unknown action (including any raw object-form field name — that vocabulary is not
accepted) or a payload that doesn't match its action's required shape (missing fields, unexpected
extra fields, or an empty payload where one is required), or a top-level field repeated across
elements (via either form) — is a clean `VALIDATION_ERROR` (never the `AttributeError` a bare
`.get()` call on a list would otherwise raise). See `tests/test_scenario_document_forms.py`,
`tests/test_scenario_action_list_form.py`, `tests/test_source_action_alias.py` (`add_source`/
`ingest_source`), `tests/test_source_origin_aliases.py` (`origin`/`sourceType` alias
normalization), `tests/test_origin_inference_from_context.py` (origin inference from context when
omitted), `tests/test_source_action_list_payload_wrappers.py` (`source`/`descriptor`/`value`/
`sources`-list payload wrappers and field-name aliases),
`tests/test_structural_source_descriptor_extraction.py` (arbitrary-named containers, scalar
payloads, ambiguous-candidate scoring, and control-field exclusion),
`tests/test_throughline_selector_aliases.py`
(`select_throughline`'s `choice`/`text` aliases), `tests/test_narrative_route_selector_aliases.py`
(`select_narrative_route`'s `choice`/`text` aliases),
`tests/test_operational_gate_and_rehearse_actions.py` (`run_gate`/`rehearse`),
`tests/test_rehearsal_timing_aliases.py` (rehearsal timing field-name aliases),
`tests/test_rehearsal_source_changes.py` (FR-M365-4 source-change reporting),
`tests/test_compile_action_aliases.py` (`compile_deck`/`compile_presentation`),
`tests/test_sequential_scenario_resume.py` (resume/accumulation),
`tests/test_candidate_persistence_on_refusal.py` (throughline reporting across a later refusal),
`tests/test_default_throughline_generation.py` (default candidate generation),
`tests/test_default_route_generation.py` (default route generation),
`tests/test_action_list_integration_regression.py` (a full talk-brief-and-representative-sources
journey through evidence/claims/routes/compile/rehearsal/readiness/package, plus targeted
malformed/blocked cases), `tests/test_rehearse_action_subfeatures.py` (`rehearse`'s widened
bulk-timings/aggregate-total/Q&A/cuts/bare-recheck sub-feature vocabulary),
`tests/test_export_action.py` (`export`'s `pptx`/`package` targets and blocked-outcome contract),
`tests/test_multi_origin_source_accumulation.py` (sequential local/GitHub/WorkIQ source
accumulation and ledger-metadata exposure), `tests/test_partial_state_report.py` (full
persisted-workspace-state exposure across a correctly-refused/blocked walk), and
`tests/test_full_manual_journey.py` (one complete, manual-only public action-list journey through
Stage package and restore, verifying all nine artifacts and a genuinely editable `.pptx`),
`tests/test_originless_source_family_compatibility.py` (a table-driven suite of originless
descriptors across every MVP-supported source family, origin-vs-inferred-connector conflicts,
unknown/ambiguous refusals, and an integrated originless manual-only journey reaching Stage
package), and `tests/test_named_approver_and_export_field_alias_compatibility.py` (`run_gate`/
`approve_stage`/`propose_claim`'s shared named-approver alias vocabulary, and `export`'s widened
target/output-directory alias and wrapper-field vocabulary).


## Error codes

See `engine/errors.py` for the authoritative catalog (mirrors ARCH.md §12 exactly) and severity
(`BLOCKING` refuses the command; `ADVISORY` attaches a caveat to a success; `INFO` is a pure
notification).

## Testing

Open tests (`tests/`) drive this exact CLI/`run-scenario` surface via `subprocess`, plus direct
unit tests against engine modules for fast, fine-grained coverage. `python-pptx` and `pypdf`
(already present in this environment) are used only to *validate* generated `.pptx`/`.pdf` bytes
in tests — never imported by the Engine itself.
