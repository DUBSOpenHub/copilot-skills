"""Source Ingest Port (ARCH §3 Engine diagram, §7 connector boundary).

`ingest_source` is the single entry point through which a `FetchResult`
envelope (already retrieved by the agent-side Fetcher — see ARCH §7)
becomes a `SourceArtifact` in the ledger. The Engine performs no network or
MCP I/O itself; it only validates, hashes, stages, and state-machines what
it is handed, and for `origin: local` it independently re-verifies
filesystem readability rather than trusting the caller (FR-SRC-4).
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from . import models, parsers, persistence, strings
from .errors import EngineError

BUNDLE_LIMIT = 25
PASTE_MAX_CHARS = 200_000

CATEGORY_LIMITS = {
    "documents": {
        "extensions": {".pdf", ".docx", ".pptx", ".txt", ".md", ".vtt", ".srt", ".eml"},
        "max_bytes": 20 * 1024 * 1024,
    },
    "images": {
        "extensions": {".png", ".jpg", ".jpeg", ".gif"},
        "max_bytes": 10 * 1024 * 1024,
    },
    "data": {
        "extensions": {".csv", ".json", ".xlsx"},
        "max_bytes": 15 * 1024 * 1024,
    },
    "demo_video": {
        "extensions": {".mp4", ".mov"},
        "max_bytes": 250 * 1024 * 1024,
    },
}

_EXT_TO_CATEGORY = {
    ext: cat for cat, spec in CATEGORY_LIMITS.items() for ext in spec["extensions"]
}

VALID_ORIGINS = {"local", "workiq", "github"}
VALID_SOURCE_TYPES = {
    "sharepoint_doc", "onedrive_doc", "pptx_file", "teams_message",
    "teams_transcript", "outlook_mail", "outlook_calendar", "loop_page",
    "github_repo", "github_issue", "github_pr", "github_discussion",
    "github_release_notes", "local_upload", "local_paste",
}

# FR-SRC-1/ARCH §7: some staged/black-box callers describe a source's
# `origin` using a connector- or source-type-shaped synonym instead of one
# of the three canonical origins the rest of the Engine models (`local`,
# `github`, `workiq`) -- e.g. "manual"/"upload" for a locally-supplied
# artifact, a bare "issue"/"repo" for a GitHub-hosted one, or
# "sharepoint"/"teams"/"outlook"/"loop" for any Microsoft 365 connector
# surface WorkIQ already fronts. This is a conservative, explicit
# allowlist of such aliases -- inferred only from this module's own
# existing `VALID_SOURCE_TYPES` connector vocabulary above, never
# invented -- resolved case-/punctuation-insensitively by `_normalize_origin`
# below before the `VALID_ORIGINS` membership check. It only ever maps
# *into* one of the three already-modeled canonical origins; an alias
# that isn't listed here is returned unchanged, so the existing check
# still rejects a truly unknown origin exactly as before (never a
# guess). `sourceType` is completely untouched by this table -- a
# source's own source-type metadata is preserved exactly as the caller
# supplied it, regardless of which origin spelling was used.
_ORIGIN_ALIASES: dict[str, str] = {
    # local: on-disk or manually supplied content.
    "manual": "local", "upload": "local", "uploaded": "local", "file": "local",
    "filesystem": "local", "local_upload": "local", "local_paste": "local", "paste": "local",
    # local, cont'd (Dark Factory hardening cycle 9, acceptance pass 12):
    # a bare *format* word -- the MVP-supported local upload/paste
    # families (markdown/text, PDF, PPTX, DOCX, VTT/transcript,
    # EML/email, JSON, image) -- is just as conservative a "known source
    # type" signal as the connector-shaped words above: nothing else in
    # this table claims any of these words, so there is no ambiguity.
    # Deliberately distinct from the already-listed, WorkIQ-specific
    # `pptx_file` (ARCH's "a PowerPoint file retrieved via WorkIQ") --
    # bare `pptx` instead means a plain uploaded/pasted PowerPoint file.
    "markdown": "local", "md": "local", "text": "local", "txt": "local", "plaintext": "local",
    "plain_text": "local", "pdf": "local", "pptx": "local", "docx": "local", "word_doc": "local",
    "vtt": "local", "srt": "local", "transcript": "local", "eml": "local", "email": "local",
    "json": "local", "image": "local", "png": "local", "jpg": "local", "jpeg": "local", "gif": "local",
    # github: repo-hosted artifacts.
    "repo": "github", "repository": "github", "issue": "github", "pr": "github",
    "pull_request": "github", "discussion": "github", "release": "github",
    "release_notes": "github", "github_repo": "github", "github_issue": "github",
    "github_pr": "github", "github_discussion": "github", "github_release_notes": "github",
    # github, cont'd: a specific file within a repo ("repository/file"
    # form) -- distinct from the already-listed bare `file` (local upload)
    # above, so always given as one of these unambiguous compound words.
    "github_file": "github", "repo_file": "github", "repository_file": "github",
    # workiq: every Microsoft 365 connector surface WorkIQ fronts.
    "sharepoint": "workiq", "sharepoint_doc": "workiq", "onedrive": "workiq",
    "onedrive_doc": "workiq", "teams": "workiq", "teams_message": "workiq",
    "teams_transcript": "workiq", "teams_chat": "workiq", "outlook": "workiq", "outlook_mail": "workiq",
    "outlook_calendar": "workiq", "loop": "workiq", "loop_page": "workiq",
    "m365": "workiq", "microsoft365": "workiq", "office365": "workiq", "pptx_file": "workiq",
}

# Second-tier, punctuation-agnostic lookup over the same conservative
# table above (never a separately-maintained/expanded vocabulary): keyed
# by every alias/canonical value with every non-alphanumeric character
# removed, so a caller's own separator style (space/hyphen/underscore, or
# none at all -- e.g. "Office 365", "office-365", "OFFICE365") all
# resolve identically. Consulted only as a fallback, after the exact
# (space/hyphen/underscore-normalized) lookup above has already failed --
# it can only ever *widen* which already-listed alias spellings resolve,
# never introduce a new canonical mapping. Also includes each canonical
# origin mapped to itself (e.g. "workiq" -> "workiq") -- the exact-value
# check above (`key in VALID_ORIGINS`) only ever matches a canonical
# spelling with *no* internal hyphen/space (since those are already
# normalized to an underscore first), so a canonical word written with
# internal punctuation ("Work IQ", "work-iq") would otherwise squash to
# "workiq" and still fail that exact check -- this closes that gap
# without introducing any new *alias* mapping (a canonical origin
# resolving to itself is never a guess).
_ORIGIN_ALIASES_SQUASHED: dict[str, str] = {
    "".join(ch for ch in k if ch.isalnum()): v for k, v in _ORIGIN_ALIASES.items()
} | {origin: origin for origin in VALID_ORIGINS}

# MIME-style spellings a public caller may use in place of the short
# format word already listed in `_ORIGIN_ALIASES` above (Dark Factory
# hardening cycle 9) -- keyed by the exact, lowercased MIME string (these
# have their own internal "/"/"."/"-" structure, so the generic
# space/hyphen/punctuation normalization below can't reach them); each
# value is one of `_ORIGIN_ALIASES`'s own existing keys, never a second,
# separately-maintained origin mapping.
_MIME_TYPE_ALIASES: dict[str, str] = {
    "text/markdown": "markdown", "text/plain": "text", "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/vtt": "vtt", "application/x-subrip": "srt", "message/rfc822": "eml",
    "application/json": "json", "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
}

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _camel_to_snake(value: str) -> str:
    """`"sharepointDoc"`/`"teamsTranscript"`-style camelCase collapsed to
    the identical snake_case spelling (`"sharepoint_doc"`/
    `"teams_transcript"`) already listed in `_ORIGIN_ALIASES`/
    `VALID_SOURCE_TYPES` -- a no-op for a value with no internal
    lower-to-upper boundary (already snake_case/kebab-case/lowercase)."""
    return _CAMEL_BOUNDARY_RE.sub("_", value).lower()


def normalize_origin(raw_origin: Any) -> Any:
    """Resolves a staged `origin` value to one of the three canonical
    origins (`local`/`github`/`workiq`): an exact canonical value (in any
    case/hyphen/space spelling) passes through normalized; a listed alias
    (`_ORIGIN_ALIASES`, matched first with normal space/hyphen/underscore
    spelling, then a camelCase-collapsed spelling, then -- only if both
    fail -- with all punctuation squashed out via
    `_ORIGIN_ALIASES_SQUASHED`, so e.g. "Office 365" still resolves like
    "office365" does) resolves to its canonical origin; a known MIME-type
    string (`_MIME_TYPE_ALIASES`) is first collapsed to its equivalent
    short format word before any of the above; anything else -- including
    a non-string value -- is returned completely unchanged so the
    caller's own `VALID_ORIGINS` membership check still rejects a truly
    unknown origin exactly as before (never a silent guess)."""
    if not isinstance(raw_origin, str):
        return raw_origin
    resolved = _MIME_TYPE_ALIASES.get(raw_origin.strip().lower(), raw_origin)
    spaced = resolved.strip().replace("-", "_").replace(" ", "_")
    key = spaced.lower()
    if key in VALID_ORIGINS:
        return key
    if key in _ORIGIN_ALIASES:
        return _ORIGIN_ALIASES[key]
    snake = _camel_to_snake(spaced)
    if snake != key:
        if snake in VALID_ORIGINS:
            return snake
        if snake in _ORIGIN_ALIASES:
            return _ORIGIN_ALIASES[snake]
    squashed = "".join(ch for ch in key if ch.isalnum())
    return _ORIGIN_ALIASES_SQUASHED.get(squashed, raw_origin)


def _is_recognized_source_type(source_type: Any) -> bool:
    """FR-SRC-1 (Dark Factory hardening cycle 9): a `sourceType` is
    recognized either as an exact `VALID_SOURCE_TYPES` member (any case/
    punctuation spelling -- resolved the identical camelCase/squash way
    `normalize_origin` already does) or as one of the same conservative,
    allowlisted connector/format words `_ORIGIN_ALIASES` already maps to
    a canonical origin (every one of those is itself a genuine, named
    source-type synonym, e.g. `"markdown"`/`"github_issue"`/
    `"sharepoint"` -- never a guess). The *stored* `sourceType` is always
    the caller's own original string, completely untouched by this
    recognition check -- see `ingest_source` below."""
    if not isinstance(source_type, str) or not source_type.strip():
        return False
    if source_type in VALID_SOURCE_TYPES:
        return True
    return normalize_origin(source_type) in VALID_ORIGINS


# FR-SRC-1: well-known `uri` hostname/path substrings that conservatively
# imply a canonical origin when a source descriptor omits `origin`
# entirely -- consulted only by `infer_origin` below, and only after
# `sourceType` itself gave no match.
_URI_ORIGIN_HINTS: dict[str, str] = {
    "github.com": "github",
    "githubusercontent.com": "github",
    "sharepoint.com": "workiq",
    "onedrive.live.com": "workiq",
    "1drv.ms": "workiq",
    "teams.microsoft.com": "workiq",
    "outlook.office.com": "workiq",
    "outlook.office365.com": "workiq",
    "loop.microsoft.com": "workiq",
    "loop.cloud.microsoft": "workiq",
}

# A `uri`'s own explicit *scheme* (as opposed to a hostname substring
# above) that unambiguously names a connector on its own -- e.g.
# `workiq://sharepoint/doc/123`, `workiq://mail/thread/1` -- consulted
# immediately after the hostname-substring hints above and before the
# file-extension tier below.
_URI_SCHEME_ORIGIN_HINTS: dict[str, str] = {"workiq": "workiq"}

# FR-SRC-1 (Dark Factory hardening cycle 9): the MVP-supported local
# upload/paste document and image formats -- reusing the identical
# extension sets `CATEGORY_LIMITS` already enforces size/type limits for
# (documents + images), plus `.json` specifically (the `data` category
# also includes `.csv`/`.xlsx`, which are not part of the documented
# local source-family vocabulary and are deliberately excluded here) --
# consulted only by `infer_origin`'s file-extension tier below, and only
# for a `uri` that already looks like a genuine filesystem path (see
# `_looks_like_local_filesystem_path`), never for a network URL whose
# host/scheme didn't already match one of the allowlists above.
_LOCAL_FILE_EXTENSION_HINTS: dict[str, str] = {
    ext: "local" for ext in (CATEGORY_LIMITS["documents"]["extensions"] | CATEGORY_LIMITS["images"]["extensions"])
} | {".json": "local"}


def _looks_like_local_filesystem_path(uri: str) -> bool:
    """True for a bare path (no scheme at all, e.g. `/Users/x/notes.md`
    or a relative `notes.md`), an explicit `file://` scheme, or a
    single-letter scheme (a Windows drive letter, e.g. `C:\\notes.md`,
    which `urlsplit` would otherwise misparse as a scheme named `"c"`) --
    false for any genuine network URL (`https://...`, `sharepoint://...`,
    ...), which is never eligible for extension-based inference (a
    remote resource's own host/scheme is the only signal trusted for
    it, via the allowlists above)."""
    try:
        scheme = urlsplit(uri).scheme.lower()
    except ValueError:
        return True
    return scheme in ("", "file") or len(scheme) == 1


def infer_origin(source_type: Any, uri: Any) -> Optional[str]:
    """FR-SRC-1: conservatively infers the canonical `origin` a source
    descriptor omitted entirely, using only context already present on
    the same descriptor -- never invoked when `origin` was explicitly
    given (even a wrong/unrecognized one; see `ingest_source` below,
    which only calls this when `origin` is missing/blank). Tries, in
    order:

      1. `sourceType`, run back through `normalize_origin` itself -- every
         value in `VALID_SOURCE_TYPES` is already one of `_ORIGIN_ALIASES`'s
         own keys (e.g. `sourceType: "github_issue"` already means
         `origin: "github"`), so this is the exact same conservative,
         allowlisted table, never a second one.
      2. A short allowlist of well-known `uri` hostname substrings for the
         `github`/`workiq` connector surfaces (`_URI_ORIGIN_HINTS` above).
      3. The `uri`'s own explicit scheme (`_URI_SCHEME_ORIGIN_HINTS`,
         e.g. `workiq://...`).
      4. (Dark Factory hardening cycle 9) The `uri`'s own file extension,
         but *only* when it already looks like a genuine local filesystem
         reference (`_looks_like_local_filesystem_path`) -- a recognized
         MVP local document/image extension (`_LOCAL_FILE_EXTENSION_HINTS`)
         is a conservative, allowlisted signal exactly like the others
         above, never a guess for an arbitrary/unrecognized extension or
         a network URL whose host/scheme already failed to match.

    Returns `None` (never a guess) when nothing above gives a confident
    match, so the descriptor's `origin` stays exactly as omitted and the
    existing `VALID_ORIGINS` check still refuses it precisely as before
    -- an unknown/unsafe descriptor is still held/refused, never silently
    authorized."""
    if isinstance(source_type, str):
        by_type = normalize_origin(source_type)
        if by_type in VALID_ORIGINS:
            return by_type
    if isinstance(uri, str):
        lowered = uri.lower()
        for needle, origin in _URI_ORIGIN_HINTS.items():
            if needle in lowered:
                return origin
        try:
            scheme = urlsplit(uri).scheme.lower()
        except ValueError:
            scheme = ""
        if scheme in _URI_SCHEME_ORIGIN_HINTS:
            return _URI_SCHEME_ORIGIN_HINTS[scheme]
        if _looks_like_local_filesystem_path(uri):
            ext = _extension_of(uri)
            hint = _LOCAL_FILE_EXTENSION_HINTS.get(ext)
            if hint:
                return hint
    return None


# FR-M365-4 / §16.2 staleness windows, in days, by source_type category.
STALE_WINDOW_DAYS = {
    "teams_message": 7, "teams_transcript": 7, "outlook_mail": 7, "outlook_calendar": 7,
    "sharepoint_doc": 14, "onedrive_doc": 14, "pptx_file": 14, "loop_page": 14,
    "github_repo": 14, "github_issue": 14, "github_pr": 14, "github_discussion": 14,
    "github_release_notes": 14,
    # local_upload / local_paste: no elapsed-time rule (content-hash only).
}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _active_source_count(conn, workspace_id: str) -> int:
    sources = persistence.list_all(conn, "source", workspace_id, models.SourceArtifact)
    return sum(1 for s in sources if s.state != models.SourceState.RETIRED.value and not s.superseded_by)


def _find_active_by_uri(conn, workspace_id: str, uri: str) -> Optional[models.SourceArtifact]:
    sources = persistence.list_all(conn, "source", workspace_id, models.SourceArtifact)
    candidates = [s for s in sources if s.uri == uri and not s.superseded_by]
    return candidates[-1] if candidates else None


def find_active_source_by_uri(conn, workspace_id: str, uri: str) -> Optional[models.SourceArtifact]:
    """Public counterpart to `_find_active_by_uri` -- lets a caller that
    only knows a source's own `uri` (e.g. `engine.scenario`'s
    `revoke_source`/`quarantine_source`/`resolve_source_hold`/
    `retire_source` action-list verbs, which have no other way to
    reference a source generated earlier in the same declarative walk)
    resolve it to its current, active `SourceArtifact` without reaching
    into this module's own private helper."""
    return _find_active_by_uri(conn, workspace_id, uri)


def _extension_of(uri: str) -> str:
    return Path(uri).suffix.lower()


def _resolve_local_path(uri: str, base_dir: Optional[Path]) -> Path:
    """Resolves a `local`-origin source's own `uri` -- its unmodified
    provenance locator, never rewritten on the `SourceArtifact` itself --
    to the real filesystem `Path` the Engine actually reads/re-verifies
    (FR-SRC-4). A *relative* `uri` (Dark Factory hardening cycle 12) is
    tried first against `base_dir` -- the directory of the scenario
    document that named it, when known -- and only falls back to the
    current working directory (`Path(uri).expanduser()`, exactly the
    pre-existing resolution, since a relative `Path` is implicitly
    interpreted against the CWD by every filesystem operation) when
    `base_dir` is absent or that first candidate doesn't actually exist.
    An absolute `uri` (or a `~`-prefixed one) is completely unaffected by
    `base_dir` either way -- `expanduser()` alone already resolves it
    identically to before this hardening cycle."""
    expanded = Path(uri).expanduser()
    if base_dir is not None and not expanded.is_absolute():
        candidate = base_dir / expanded
        if candidate.exists():
            return candidate
    return expanded


def validate_file_limits(uri: str, byte_size: int) -> tuple[str, str]:
    """Returns (category, extension) or raises FILE_TOO_LARGE / UNSUPPORTED_FILE_TYPE."""
    ext = _extension_of(uri)
    category = _EXT_TO_CATEGORY.get(ext)
    if category is None:
        accepted = ", ".join(sorted({e for spec in CATEGORY_LIMITS.values() for e in spec["extensions"]}))
        raise EngineError(
            "UNSUPPORTED_FILE_TYPE",
            strings.UNSUPPORTED_FILE_TYPE.format(filename=uri, category="uploaded", accepted=accepted),
            {"uri": uri, "extension": ext},
        )
    max_bytes = CATEGORY_LIMITS[category]["max_bytes"]
    if byte_size > max_bytes:
        raise EngineError(
            "FILE_TOO_LARGE",
            strings.FILE_TOO_LARGE.format(
                filename=uri, max_size=f"{max_bytes // (1024 * 1024)}MB", category=category
            ),
            {"uri": uri, "byteSize": byte_size, "maxBytes": max_bytes},
        )
    return category, ext


def _decode_payload_bytes(payload: dict) -> bytes:
    if "contentBase64" in payload and payload["contentBase64"] is not None:
        return base64.b64decode(payload["contentBase64"])
    content = payload.get("content", "")
    if content is None:
        content = ""
    return content.encode("utf-8")


def _stage_bytes(staging_dir: Path, source_id: str, ext: str, data: bytes) -> Path:
    staging_dir.mkdir(parents=True, exist_ok=True)
    suffix = ext if ext else ".txt"
    path = staging_dir / f"{source_id}{suffix}"
    path.write_bytes(data)
    return path


def normalize_text(origin: str, ext: str, raw: bytes) -> tuple[str, Optional[str]]:
    """Returns (normalized_text, parse_failure_reason_or_None)."""
    if origin != "local":
        # workiq/github Fetchers hand the Engine already-normalized text.
        return raw.decode("utf-8", errors="replace"), None
    try:
        text = parsers.extract_text(ext, raw)
    except parsers.ParseError as exc:
        return "", str(exc.reason)
    if ext == ".pdf" and not text.strip():
        return "", "no extractable text found in PDF content stream"
    return text, None


# Public payload key compatibility (Dark Factory hardening cycle 7): a
# `FetchResult` descriptor's own field names accept a conservative,
# explicit allowlist of camelCase/snake_case synonyms in place of the
# documented canonical name -- resolved once, centrally, here, so every
# entry point (the raw `source ingest` CLI command, every `run_scenario`
# document shape -- object-form, field-list form, *and* action-list form
# -- and any future caller) shares the identical resolution instead of a
# separately-maintained table per call site. `engine.scenario`'s own
# action-list normalization (`_normalize_source_field_aliases`) delegates
# to this exact function rather than keeping its own copy.
#
# Precedence: an explicit canonical field always wins over a differing
# sibling alias (pre-existing behavior for `path` -> `uri`, unchanged);
# absent the canonical field, two or more *aliases* that disagree with
# each other is a conflict -- a clean `VALIDATION_ERROR`, never a silent
# guess. Every alias only ever *fills in* the canonical field -- the
# alias key itself, and any other unrecognized field (e.g. a caller's own
# `title`), is left completely untouched on the returned dict, so no
# source metadata is ever silently dropped.
#
# `url`/`href`/`web_url` (Dark Factory hardening cycle 10, acceptance
# pass 13) are further conservative synonyms for `uri` -- the exact same
# generic field names a plain web-fetch-shaped descriptor commonly uses
# in place of the documented `uri`. `kind`/`format` are the parallel
# generic synonyms for `sourceType` (alongside the pre-existing `type`/
# `source_type`) -- e.g. a descriptor naming its own MIME-ish `format`
# instead of a `sourceType`. Neither group is a new alias *value*
# vocabulary (that already lives in `_ORIGIN_ALIASES`/`_MIME_TYPE_ALIASES`
# above); these are only new *field names* carrying the identical
# existing value space.
#
# `link` (Dark Factory hardening cycle 11, acceptance pass 14) is one
# further conservative `uri` synonym, alongside `url`/`href`/`web_url`
# above. `mime`/`mimeType` are the parallel synonyms for `sourceType`'s
# own already-recognized MIME-string spelling (`_MIME_TYPE_ALIASES`
# above already collapses a MIME string to its equivalent short format
# word regardless of which field name carried it in). `text`/`body`/
# `transcript` are conservative synonyms for a descriptor's own inline
# `content` -- the same generic "the actual bytes/prose live here" field
# a caller's own envelope conventions commonly spell differently.
# `connector`/`provider` are conservative synonyms for `origin` itself --
# a descriptor naming which connector/product retrieved it (e.g.
# `"connector": "SharePoint"`) rather than the documented `origin` field
# -- resolved by the exact same conservative `normalize_origin`/
# `_ORIGIN_ALIASES` allowlist every explicit `origin` value already goes
# through in `ingest_source` below (never a second, separately-maintained
# vocabulary), so an unrecognized connector name is refused exactly like
# an unrecognized `origin` already is, and a connector/provider hint that
# outright conflicts with the descriptor's own `sourceType`/`uri` is
# caught by that same existing conflict check.
#
# `locator`/`source_locator`/`fixture`/`fixture_path`/`artifact`/
# `artifact_path`/`document`/`document_path`/`file_path`/`local_file`/
# `input_file`/`input_path`/`content_file`/`content_path`/`upload`/
# `upload_path`/`reference`/`ref` (Dark Factory hardening cycle 12) are a
# further, wider conservative synonym family for `uri` -- every one of
# them names a concrete locator/path a caller's own vocabulary commonly
# uses in place of the documented `uri` (a scenario-fixture reference, an
# on-disk artifact/document/upload path, a generic "reference"/`ref`),
# never a second, looser mechanism -- an alias here still only ever
# *fills in* `uri` when no canonical value (or an already-agreeing alias)
# is already present, exactly like every other alias in this table.
# `source_kind`/`document_type`/`artifact_type` are the parallel synonyms
# for `sourceType`, carrying the identical existing value space
# (`normalize_origin`/`infer_origin`/`_is_recognized_source_type` above),
# never a second alias *value* vocabulary. See `normalize_source_payload`
# below for the additional camelCase/kebab-case *key*-spelling
# normalization every alias here (old and new alike) also benefits from.
SOURCE_PAYLOAD_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "uri": (
        "path", "source_uri", "sourceUri", "local_path", "localPath", "url", "href", "web_url", "link",
        "locator", "source_locator", "sourceLocator", "fixture", "fixture_path", "fixturePath",
        "artifact", "artifact_path", "artifactPath", "document", "document_path", "documentPath",
        "file_path", "filePath", "local_file", "localFile", "input_file", "inputFile",
        "input_path", "inputPath", "content_file", "contentFile", "content_path", "contentPath",
        "upload", "upload_path", "uploadPath", "reference", "ref",
    ),
    "sourceType": (
        "type", "source_type", "kind", "format", "mime", "mimeType",
        "source_kind", "sourceKind", "document_type", "documentType", "artifact_type", "artifactType",
    ),
    "owner": ("author",),
    "permissionState": ("access", "access_state", "accessState"),
    "aclSnapshot": ("permission_snapshot", "permissionSnapshot"),
    "sensitivityLabel": ("label", "label_state", "labelState"),
    "retrievedAt": ("authorized_at", "authorizedAt"),
    "content": ("text", "body", "transcript"),
    "origin": ("connector", "provider"),
}


def _normalize_field_key(key: Any) -> str:
    """`"sourceLocator"`/`"source-locator"`/`"Source Locator"`-style
    spellings of a source-descriptor field name all collapse to the
    identical `"source_locator"` snake_case form -- the same
    normalization `engine.scenario._normalize_descriptor_key` already
    applies for structural container discovery, mirrored here so the
    *field-alias* resolution below stays consistent with it. A
    non-string key resolves to `""`, matching nothing."""
    if not isinstance(key, str):
        return ""
    snake = _camel_to_snake(key)
    return snake.strip().replace("-", "_").replace(" ", "_").lower()


# Reverse lookup, keyed by every alias above collapsed through
# `_normalize_field_key` -- built once, at import time, purely so
# `normalize_source_payload` below can also recognize a kebab-case
# (`"source-locator"`) or differently-spaced spelling of an
# *already-listed* alias without this table having to separately
# enumerate every punctuation variant of every alias by hand. Never
# introduces a new alias *value* -- every entry still maps to one of
# this module's own already-declared canonical fields above.
_ALIAS_KEY_NORMALIZED_LOOKUP: dict[str, str] = {
    _normalize_field_key(alias): canonical
    for canonical, aliases in SOURCE_PAYLOAD_FIELD_ALIASES.items()
    for alias in aliases
}

# `filename`/`file`/`name` (Dark Factory hardening cycle 10/11,
# acceptance pass 13/14): conservative naming-only hints, deliberately
# *not* part of the `uri` alias group above -- unlike every one of those
# (`path`/`local_path`/`url`/...), none of these three claims a real
# location the Engine must independently re-verify for `origin: local`
# (FR-SRC-4). See `_apply_manual_upload_hint` below for the one, narrow
# way this trio is actually used: only ever together with literal inline
# content, and only when no real location field is present at all.
# `name` is the same kind of bare display-name hint as `filename`/`file`
# (e.g. a descriptor naming its own resource `"adoption-notes.md"` via a
# generic `name` field rather than `filename`) -- never a second,
# looser mechanism.
_MANUAL_UPLOAD_HINT_FIELDS = ("filename", "file", "name")
# Internal-only marker key `_apply_manual_upload_hint` stamps onto its own
# output -- read (and popped, never persisted onto the `SourceArtifact`
# model or surfaced in any report) by `ingest_source`'s own byte-
# acquisition step below, so a hinted descriptor is always ingested
# in-memory even when its own `sourceType` (preserved completely
# untouched, exactly like any other explicit `sourceType`) isn't the
# literal string `"local_paste"`.
_MANUAL_UPLOAD_HINT_MARKER = "_manualUploadHint"


def _apply_manual_upload_hint(payload: dict[str, Any]) -> dict[str, Any]:
    """FR-SRC-1 (Dark Factory hardening cycle 10, acceptance pass 13): a
    descriptor that supplies literal inline content (`content`/
    `contentBase64`) but claims no real filesystem location at all (no
    `uri`, and none of the alias table's own location-claiming aliases --
    `path`/`source_uri`/`local_path`/`url`/`href`/`web_url` -- already
    resolved it) never has to name a real on-disk file: it is always
    ingested through the exact same in-memory manual/paste path an
    explicit `sourceType: "local_paste"` descriptor already uses, exactly
    as if the caller had supplied that `sourceType` themselves. A no-op
    whenever a real `uri` is already present (however much other
    metadata this same descriptor also carries), whenever there is no
    inline content to ingest at all, or whenever this descriptor's own
    `origin`/`sourceType` already, confidently implies a non-local
    connector (`github`/`workiq`, which always name a real remote
    resource, never a bare naming hint) -- so a github/workiq
    `FetchResult` that happens to omit `uri` is still correctly refused
    exactly as before, never silently reinterpreted as a manual upload.

    A `filename`/`file`/`name` naming hint becomes this descriptor's own
    synthesized `uri` -- a bare value (no `scheme:` prefix), so a
    recognized extension still drives `infer_origin`'s existing file-
    extension tier exactly like a genuine local path would -- and, when
    no explicit `title` was already given, this same descriptor's
    `title` too (surfaced only in a scenario run-report's own
    `source.ingest` step, never stored on the `SourceArtifact` model
    itself). Absent any naming hint at all, a still content-bearing
    descriptor that is either explicitly typed (`sourceType`/`origin`
    given directly, e.g. `{"sourceType": "markdown", "content": "..."}`)
    *or* explicitly titled (Dark Factory hardening cycle 11, acceptance
    pass 14 -- `{"title": "Adoption Notes", "content": "..."}`, no
    `sourceType` at all) instead gets a stable, content-derived synthetic
    identity, so two byte-identical inline uploads always resolve to the
    very same source (consistent with a real file's own path-based
    identity) while two different ones never collide. A descriptor with
    *none* of a naming hint, an explicit `sourceType`, or an explicit
    `title` is left completely untouched -- the pre-existing "uri is
    required" refusal still applies exactly as before.

    Marks its result with the internal `_MANUAL_UPLOAD_HINT_MARKER` flag
    (consumed, and never persisted or reported, by `ingest_source`'s own
    byte-acquisition step) so that step always reads this descriptor's
    own inline content -- regardless of whatever `sourceType` string the
    caller did or didn't supply -- rather than ever trying to read this
    synthesized, non-existent path from a real filesystem. Idempotent:
    re-applying it to its own already-processed output (which now has a
    real `uri`) is always a no-op."""
    if payload.get("uri"):
        return payload
    has_content = (
        ("content" in payload and payload["content"] is not None)
        or ("contentBase64" in payload and payload["contentBase64"] is not None)
    )
    if not has_content:
        return payload
    raw_origin = payload.get("origin")
    implied_origin = None
    if isinstance(raw_origin, str) and raw_origin.strip():
        implied_origin = normalize_origin(raw_origin)
    if implied_origin not in VALID_ORIGINS:
        implied_origin = infer_origin(payload.get("sourceType"), None)
    if implied_origin in ("github", "workiq"):
        return payload
    hint = next(
        (payload[f].strip() for f in _MANUAL_UPLOAD_HINT_FIELDS if isinstance(payload.get(f), str) and payload[f].strip()),
        None,
    )
    has_type_or_title_hint = (
        (isinstance(payload.get("sourceType"), str) and payload["sourceType"].strip())
        or (isinstance(payload.get("title"), str) and payload["title"].strip())
    )
    if hint is None and not has_type_or_title_hint:
        return payload
    result = dict(payload)
    if hint is not None:
        result["uri"] = hint
        result.setdefault("title", hint)
    else:
        result["uri"] = f"manual-upload:{sha256_hex(_decode_payload_bytes(payload))[:16]}"
    result[_MANUAL_UPLOAD_HINT_MARKER] = True
    return result


# Dark Factory hardening cycle 13 (FR-SRC-1, authorization boolean/state
# aliases): `authorized`/`is_authorized`/`isAuthorized` are boolean-
# shaped synonyms for `permissionState` -- resolved by their own
# dedicated step below (`_apply_authorization_aliases`), run immediately
# after `normalize_source_payload`'s own generic `SOURCE_PAYLOAD_FIELD_
# ALIASES` pass (which already resolves the pre-existing, string-valued
# `access`/`access_state`/`accessState` aliases into `permissionState`,
# using that pass's own "an explicit canonical field always wins over a
# differing sibling alias" precedent), rather than folded into that same
# generic table -- because authorization, unlike a locator/type/label
# alias, is a security-sensitive signal: two of these fields disagreeing
# is always a clean, explicit `VALIDATION_ERROR`, even when one of them
# is the already-resolved canonical `permissionState` field itself
# (which the generic pass never even compares against a sibling alias
# once the canonical field is already present). Every alias name here is
# matched regardless of camelCase/snake_case/kebab-case spelling, via the
# identical `_normalize_field_key` every other alias in this module
# already uses.
_AUTHORIZATION_BOOLEAN_ALIASES = ("authorized", "is_authorized", "isAuthorized")
_AUTHORIZATION_BOOLEAN_ALIAS_KEYS = frozenset(
    _normalize_field_key(alias) for alias in _AUTHORIZATION_BOOLEAN_ALIASES
)


def _normalize_permission_state_value(value: Any) -> Any:
    """A JSON boolean `True`/`False` becomes the identical canonical
    `"authorized"`/`"denied"` string `permissionState` already models --
    every other value (an already-canonical string, `None`, or anything
    else) is returned completely unchanged, so the existing
    `ingest_source` "must be 'authorized'" check still refuses an
    unrecognized/misspelled value exactly as before (never a guess)."""
    if value is True:
        return "authorized"
    if value is False:
        return "denied"
    return value


def _apply_authorization_aliases(payload: dict[str, Any]) -> dict[str, Any]:
    """Collects every authorization-shaped signal already present on
    `payload` -- the canonical `permissionState` itself (however it got
    there: given directly, or already alias-resolved from `access`/
    `access_state`/`accessState` by the generic pass above), plus this
    step's own `authorized`/`is_authorized`/`isAuthorized` boolean
    aliases, found by normalized key regardless of spelling -- and
    resolves them to a single `permissionState` value. Zero signals is a
    no-op (nothing to resolve; the pre-existing "must be authorized"
    refusal still applies downstream exactly as before). One signal
    (after normalizing a boolean to its canonical string) resolves
    `permissionState` to it. Two or more that, once normalized, disagree
    -- including a boolean alias that disagrees with an already-explicit
    `permissionState` -- is a clean `VALIDATION_ERROR`, never a silent
    pick; two or more that agree is a safe no-op past the first. Returns
    a new dict; never mutates the caller's own, and never removes the
    original alias field(s) (consistent with every other alias in this
    module -- source metadata is never silently dropped)."""
    result = dict(payload)
    signals: dict[str, Any] = {}
    if "permissionState" in result:
        signals["permissionState"] = result["permissionState"]
    for key, value in payload.items():
        if key != "permissionState" and _normalize_field_key(key) in _AUTHORIZATION_BOOLEAN_ALIAS_KEYS:
            signals[key] = value
    if not signals:
        return result
    resolved_values = {k: _normalize_permission_state_value(v) for k, v in signals.items()}
    distinct = set(resolved_values.values())
    if len(distinct) > 1:
        raise EngineError(
            "VALIDATION_ERROR",
            f"conflicting values for 'permissionState' given via field(s) {sorted(resolved_values)} "
            "(ambiguous: which one should win?)",
            {"field": "permissionState", "aliasFields": sorted(resolved_values)},
        )
    (only_value,) = distinct
    result["permissionState"] = only_value
    return result


# Every field name this module already recognizes on a source descriptor
# -- every canonical `SOURCE_PAYLOAD_FIELD_ALIASES` key and every one of
# its own aliases, the manual-upload naming hints, the authorization
# boolean aliases above, and the always-passthrough `title` -- consulted
# only by `_apply_bare_scalar_field_hint` below to find the one remaining
# field name it does *not* already know (never a second, looser
# recognition vocabulary).
_RECOGNIZED_SOURCE_FIELD_NAMES = (
    frozenset(SOURCE_PAYLOAD_FIELD_ALIASES)
    | frozenset(a for aliases in SOURCE_PAYLOAD_FIELD_ALIASES.values() for a in aliases)
    | frozenset(_MANUAL_UPLOAD_HINT_FIELDS)
    | frozenset(_AUTHORIZATION_BOOLEAN_ALIASES)
    | frozenset({"title", "contentBase64", "version"})
)


def _looks_like_uri_or_path(value: str) -> bool:
    """Dark Factory hardening cycle 11 (acceptance pass 14): true for a
    bare string that already looks like a locator on its own -- an
    explicit URI scheme (`https://...`, or one of this codebase's own
    pseudo-schemes already used throughout its tests/fixtures, e.g.
    `paste:...`/`manual-upload:...`), a path separator (`/`/`\\`), or a
    recognized MVP local upload/paste extension (the identical
    `_EXT_TO_CATEGORY`/`_LOCAL_FILE_EXTENSION_HINTS` allowlists every
    other extension-based signal in this module already uses) -- false
    for ordinary prose content. Never a guess for anything else (a
    multi-line string, or one with none of these signals, is never
    locator-shaped)."""
    stripped = value.strip()
    if not stripped or "\n" in stripped:
        return False
    try:
        scheme = urlsplit(stripped).scheme
    except ValueError:
        scheme = ""
    if scheme and len(scheme) > 1:
        return True
    if "/" in stripped or "\\" in stripped:
        return True
    ext = Path(stripped).suffix.lower()
    return ext in _EXT_TO_CATEGORY or ext in _LOCAL_FILE_EXTENSION_HINTS


def _apply_bare_scalar_field_hint(payload: dict[str, Any]) -> dict[str, Any]:
    """Dark Factory hardening cycle 11 (acceptance pass 14): a
    descriptor that already has neither a real `uri` nor any inline
    `content`/`contentBase64`, but carries exactly one field this module
    doesn't otherwise recognize at all (`_RECOGNIZED_SOURCE_FIELD_NAMES`)
    whose own value is a plain, non-empty string, is a public caller's
    own unrecognized spelling for that one missing descriptor field --
    resolved, conservatively, from the string's own shape: one that
    already looks like a URI/filesystem path/filename
    (`_looks_like_uri_or_path`) becomes this descriptor's own `uri`;
    otherwise -- only when this same payload already also carries a real
    naming/type hint of its own (`sourceType`, `title`, or a
    `filename`/`file`/`name` hint -- every one of them already a
    recognized field on its own) -- it becomes this descriptor's inline
    `content` instead, so `_apply_manual_upload_hint` below can still
    turn that hint into a synthesized `uri` exactly as if the caller had
    named the canonical `content` field themselves.

    A no-op whenever `payload` already has a `uri` or inline content
    (nothing missing to infer), whenever zero or more than one
    unrecognized string-valued field exists (never a guess as to which
    one is 'the' field), or whenever the sole candidate isn't itself a
    plain string. Every other field is left completely untouched."""
    if payload.get("uri"):
        return payload
    has_content = (
        ("content" in payload and payload["content"] is not None)
        or ("contentBase64" in payload and payload["contentBase64"] is not None)
    )
    if has_content:
        return payload
    unrecognized = [
        k for k, v in payload.items()
        if k not in _RECOGNIZED_SOURCE_FIELD_NAMES and isinstance(v, str) and v.strip()
    ]
    if len(unrecognized) != 1:
        return payload
    (key,) = unrecognized
    value = payload[key].strip()
    result = dict(payload)
    if _looks_like_uri_or_path(value):
        result["uri"] = value
        return result
    has_naming_hint = (
        (isinstance(payload.get("sourceType"), str) and payload["sourceType"].strip())
        or (isinstance(payload.get("title"), str) and payload["title"].strip())
        or any(isinstance(payload.get(f), str) and payload[f].strip() for f in _MANUAL_UPLOAD_HINT_FIELDS)
    )
    if has_naming_hint:
        result["content"] = value
    return result


def normalize_source_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolves every `SOURCE_PAYLOAD_FIELD_ALIASES` canonical field from
    whichever accepted alias(es) are present on `payload` -- see the
    table comment above for the exact precedence/conflict rules -- then,
    for any canonical field still unresolved, a second (Dark Factory
    hardening cycle 12) fallback pass matches any *differently-spelled*
    -- kebab-case, extra spacing, unconventional casing -- variant of an
    already-listed alias via `_normalize_field_key`/
    `_ALIAS_KEY_NORMALIZED_LOOKUP` (never a new alias *value*, only a
    wider spelling match for the identical, already-declared ones); then
    `_apply_authorization_aliases` (Dark Factory hardening cycle 13) so a
    boolean `authorized`/`is_authorized`/`isAuthorized` -- or an
    already-resolved `permissionState`/`access`/`access_state` boolean --
    resolves to the canonical `"authorized"`/`"denied"` string, rejecting
    outright if two such signals disagree; then applies
    `_apply_bare_scalar_field_hint` (above) so a lone remaining
    unrecognized field name still resolves to `uri`/`content`, then
    `_apply_manual_upload_hint` (above) so a `filename`/`file`/`name`-
    named, content-bearing descriptor with no real location field at all
    resolves a synthesized `uri` too. Returns a new dict (never mutates
    the caller's own); idempotent, so calling it more than once on an
    already-normalized descriptor (e.g. once at action-list/structural-
    descriptor-extraction normalization time, again inside
    `ingest_source` itself) is always a safe no-op."""
    result = dict(payload)
    for canonical, aliases in SOURCE_PAYLOAD_FIELD_ALIASES.items():
        if canonical in result:
            continue
        present = [a for a in aliases if a in result]
        if not present:
            continue
        values = [result[a] for a in present]
        if any(v != values[0] for v in values[1:]):
            raise EngineError(
                "VALIDATION_ERROR",
                f"conflicting values for '{canonical}' given via alias field(s) {present} "
                "(ambiguous: which one should win?)",
                {"field": canonical, "aliasFields": present},
            )
        result[canonical] = values[0]

    unresolved = {c for c in SOURCE_PAYLOAD_FIELD_ALIASES if c not in result}
    if unresolved:
        candidates_by_canonical: dict[str, list[str]] = {}
        for key in payload:
            canonical = _ALIAS_KEY_NORMALIZED_LOOKUP.get(_normalize_field_key(key))
            if canonical in unresolved:
                candidates_by_canonical.setdefault(canonical, []).append(key)
        for canonical, keys in candidates_by_canonical.items():
            values = [result[k] for k in keys]
            if any(v != values[0] for v in values[1:]):
                raise EngineError(
                    "VALIDATION_ERROR",
                    f"conflicting values for '{canonical}' given via alias field(s) {sorted(keys)} "
                    "(ambiguous: which one should win?)",
                    {"field": canonical, "aliasFields": sorted(keys)},
                )
            result[canonical] = values[0]

    result = _apply_authorization_aliases(result)
    result = _apply_bare_scalar_field_hint(result)
    return _apply_manual_upload_hint(result)


def carries_manual_upload_hint(resolved_payload: dict[str, Any]) -> bool:
    """Public accessor for `_apply_manual_upload_hint`'s own internal
    `_MANUAL_UPLOAD_HINT_MARKER` (never persisted/reported anywhere else
    -- see that function's own docstring) -- lets a caller that already
    holds a `normalize_source_payload`-resolved descriptor (e.g.
    `engine.scenario`'s own conservative, `add_source`-only default-local
    origin classification, Dark Factory hardening cycle 12) ask whether
    this module's own manual/local-upload-hint logic already,
    conservatively, recognized it as one -- without reaching into this
    module's own private marker constant directly."""
    return bool(resolved_payload.get(_MANUAL_UPLOAD_HINT_MARKER))


def ingest_source(
    conn,
    workspace_id: str,
    payload: dict[str, Any],
    actor: str,
    staging_dir: Path,
    base_dir: Optional[Path] = None,
) -> models.SourceArtifact:
    """`base_dir` (Dark Factory hardening cycle 12, optional, additive --
    every existing caller that never passed it behaves identically to
    before) is consulted only when acquiring a `local`-origin, on-disk
    file: a *relative* `uri` is tried against it first (the scenario
    document's own directory, when the caller is `engine.scenario`'s
    `run_scenario`), before falling back to the current working
    directory exactly as before. Never affects an absolute/`~`-prefixed
    `uri`, and never rewrites the persisted `uri` itself -- see
    `_resolve_local_path` above."""
    payload = normalize_source_payload(payload)
    # Read (never persisted/reported further -- see `_apply_manual_upload_hint`
    # above) before any other payload field access below, purely a local
    # byte-acquisition-routing flag.
    manual_upload_hint = bool(payload.get(_MANUAL_UPLOAD_HINT_MARKER))
    # (Dark Factory hardening cycle 13) Read once, also purely a byte-
    # acquisition-routing flag -- consulted below so an opaque `uri` that
    # doesn't resolve to a real on-disk file, but that nonetheless
    # carries its own literal inline content, still ingests from that
    # content directly instead of being treated as a missing file.
    has_inline_content = (
        (payload.get("content") not in (None, ""))
        or (payload.get("contentBase64") not in (None, ""))
    )
    raw_origin = payload.get("origin")
    source_type = payload.get("sourceType")
    uri = payload.get("uri")
    # FR-SRC-1: conservatively infer the connector this descriptor
    # implies (from its own `sourceType`/`uri`) unconditionally -- used
    # below to fill in a wholly *omitted* `origin`, and also to catch an
    # *explicit* `origin` that outright conflicts with it.
    inferred = infer_origin(source_type, uri)
    if not raw_origin:
        # `origin` was omitted entirely (as opposed to given but wrong/
        # unrecognized, which is never second-guessed here) -- fall back
        # to the inferred connector before falling through to the same
        # "must be one of ..." refusal an omitted origin has always
        # produced.
        if inferred is not None:
            raw_origin = inferred
    else:
        # (Dark Factory hardening cycle 9) An explicit, valid `origin`
        # that outright conflicts with the connector this same
        # descriptor's own `sourceType`/`uri` already, confidently implies
        # is refused explicitly -- never silently honored (which one
        # would be "right"?) and never silently overridden either.
        normalized_explicit = normalize_origin(raw_origin)
        if normalized_explicit in VALID_ORIGINS and inferred is not None and inferred != normalized_explicit:
            raise EngineError(
                "VALIDATION_ERROR",
                f"origin '{raw_origin}' conflicts with the connector already implied by this source's "
                f"own sourceType/uri (would infer '{inferred}')",
                {"origin": raw_origin, "inferredOrigin": inferred},
            )
    origin = normalize_origin(raw_origin)
    if not source_type and origin == "local" and (
        (isinstance(uri, str) and _extension_of(uri) in _LOCAL_FILE_EXTENSION_HINTS) or manual_upload_hint
    ):
        # (Dark Factory hardening cycle 9) `sourceType` was omitted
        # entirely too, but the `uri`'s own recognized local document/
        # image extension already unambiguously identified this as a
        # local upload (the exact same signal `infer_origin` just used,
        # if that is how `origin` itself got here) -- default to the
        # existing `local_upload` canonical type rather than refusing a
        # descriptor that already gave every signal it safely could.
        # Never applied when a `sourceType` *was* supplied (however
        # spelled) -- that original value is always preserved verbatim.
        #
        # (Dark Factory hardening cycle 12) `manual_upload_hint` widens
        # this identical default to also cover a descriptor whose `uri`
        # was itself *synthesized* by `_apply_manual_upload_hint` (a
        # `filename`/`file`/`name` hint with an unrecognized/absent
        # extension, or a bare content-hash identity, e.g. a `title`-only
        # paste) -- already conservatively established as a genuine
        # manual/local upload, regardless of its own synthetic `uri`'s
        # shape.
        source_type = "local_upload"
    owner = payload.get("owner")
    permission_state = payload.get("permissionState")
    acl_snapshot = payload.get("aclSnapshot", "")
    sensitivity_label = payload.get("sensitivityLabel")
    version = payload.get("version") or models.now_iso()
    retrieved_at = payload.get("retrievedAt") or models.now_iso()

    if origin not in VALID_ORIGINS:
        raise EngineError("VALIDATION_ERROR", f"origin must be one of {sorted(VALID_ORIGINS)}", {"origin": origin})
    if not _is_recognized_source_type(source_type):
        raise EngineError("VALIDATION_ERROR", f"sourceType '{source_type}' is not recognized", {"sourceType": source_type})
    if not uri:
        raise EngineError("VALIDATION_ERROR", "uri is required", {})
    if not owner:
        raise EngineError("VALIDATION_ERROR", "owner is required", {})

    # FR-M365-1/FR-SRC-4: a denied fetch never becomes a source at all.
    if permission_state != "authorized":
        raise EngineError(
            "SOURCE_UNAUTHORIZED", strings.SOURCE_UNAUTHORIZED.format(source_ref=uri), {"uri": uri}
        )

    existing = _find_active_by_uri(conn, workspace_id, uri)
    if existing is None and _active_source_count(conn, workspace_id) >= BUNDLE_LIMIT:
        raise EngineError("BUNDLE_LIMIT_REACHED", strings.BUNDLE_LIMIT_REACHED, {"limit": BUNDLE_LIMIT})

    # -- Acquire bytes, independently for `local` origin (FR-SRC-4) --------
    # `manual_upload_hint` (Dark Factory hardening cycle 10) widens this
    # branch's own "in-memory content, no real file required" condition
    # to also cover a `filename`/`file`-hinted or content-plus-type-only
    # descriptor `_apply_manual_upload_hint` already recognized as never
    # claiming a real filesystem location -- `sourceType` itself stays
    # exactly whatever the caller supplied (or omitted), never forced to
    # the literal string `"local_paste"`.
    forced_hold_reason: Optional[str] = None
    if origin == "local" and source_type != "local_paste" and not manual_upload_hint:
        local_path = _resolve_local_path(uri, base_dir)
        if not local_path.exists():
            if has_inline_content and _extension_of(uri) not in _EXT_TO_CATEGORY:
                # (Dark Factory hardening cycle 13) A `uri` with no
                # recognized local-upload extension of its own (an
                # opaque fixture/manual pseudo-scheme reference, or a
                # bare identifier with no extension at all) was never
                # meant to name a real, typed on-disk file: it still
                # carries its own literal inline content, so it is
                # ingested from that content directly, exactly like an
                # explicit `local_paste`/manual-upload-hinted descriptor
                # already is, rather than ever being held or refused for
                # a file that was never going to exist. Never applies to
                # a `uri` with a recognized extension (e.g. `notes.md`)
                # -- a genuine, typed file reference always still tries
                # the real filesystem first, and is held/refused exactly
                # as before, even if inline content also happens to be
                # present (a real, explicit locator is never silently
                # second-guessed by sibling content -- see
                # `test_a_real_uri_is_never_overridden_by_a_sibling_
                # filename_hint`).
                raw = _decode_payload_bytes(payload)
                if len(raw) > PASTE_MAX_CHARS:
                    raise EngineError(
                        "FILE_TOO_LARGE",
                        strings.FILE_TOO_LARGE.format(
                            filename=uri, max_size=f"{PASTE_MAX_CHARS} characters", category="pasted text"
                        ),
                        {"uri": uri, "chars": len(raw), "maxChars": PASTE_MAX_CHARS},
                    )
                byte_size = len(raw)
                ext = ".txt"
            elif _extension_of(uri) in _EXT_TO_CATEGORY or _extension_of(uri) == "":
                # (Dark Factory hardening cycle 12, widened in cycle 13)
                # A recognized local upload extension -- or no extension
                # at all, an opaque fixture/manual identifier that was
                # never meant to look like a typed file -- that doesn't
                # (yet) resolve to a real, readable file on disk is still
                # a genuine, MVP-supported local source -- held for user
                # resolution (FR-SRC-6 already holds a source whose
                # *content* can't be parsed; a source whose content can't
                # even be found yet is the identical kind of "not yet
                # resolved" condition), never a hard abort dropped from
                # the ledger before it can even be seen/resolved. A file
                # with a real but *unrecognized* extension (e.g.
                # `.exe`/`.zip`) is still refused exactly as before
                # (never held) -- this only ever widens the held/
                # PARSE_FAILED outcome, never what counts as a supported
                # local file type.
                raw = b""
                byte_size = 0
                forced_hold_reason = f"local file not found: {uri}"
                ext = _extension_of(uri)
            else:
                raise EngineError(
                    "VALIDATION_ERROR", f"local file not found: {uri}", {"uri": uri}
                )
        elif not os.access(local_path, os.R_OK):
            raise EngineError(
                "SOURCE_UNAUTHORIZED", strings.SOURCE_UNAUTHORIZED.format(source_ref=uri), {"uri": uri}
            )
        else:
            raw = local_path.read_bytes()
            byte_size = len(raw)
            category, ext = validate_file_limits(uri, byte_size)
    elif origin == "local" and (source_type == "local_paste" or manual_upload_hint):
        text = payload.get("content", "")
        if len(text) > PASTE_MAX_CHARS:
            raise EngineError(
                "FILE_TOO_LARGE",
                strings.FILE_TOO_LARGE.format(filename=uri, max_size=f"{PASTE_MAX_CHARS} characters", category="pasted text"),
                {"uri": uri, "chars": len(text), "maxChars": PASTE_MAX_CHARS},
            )
        raw = text.encode("utf-8")
        byte_size = len(raw)
        ext = ".txt"
    else:
        raw = _decode_payload_bytes(payload)
        byte_size = len(raw)
        ext = ""

    content_hash = sha256_hex(raw)

    source_id = models.new_id("source")
    if forced_hold_reason is not None:
        # (Dark Factory hardening cycle 12) The file itself was never
        # found, so there is nothing for `normalize_text`/the format
        # parsers to even attempt -- the hold reason is this branch's
        # own, already-explicit "not found" message, never whatever an
        # empty-bytes parse of a format-specific extractor happens to
        # produce (which, for some formats, would misleadingly *not*
        # look like a failure at all, e.g. an empty `.md`/`.txt`).
        normalized_text, parse_failure = "", forced_hold_reason
    else:
        normalized_text, parse_failure = normalize_text(origin, ext, raw)

    state = models.SourceState.AUTHORIZED.value
    hold_reason = None

    # FR-SRC-6: source's own label changed vs. its immediately prior
    # snapshot -> LABEL_CONFLICT, held until resolved.
    if existing is not None and existing.sensitivity_label is not None \
            and sensitivity_label is not None and existing.sensitivity_label != sensitivity_label:
        state = models.SourceState.LABEL_CONFLICT.value
        hold_reason = (
            f"sensitivity label changed from '{existing.sensitivity_label}' to '{sensitivity_label}'"
        )
    elif parse_failure is not None:
        state = models.SourceState.PARSE_FAILED.value
        hold_reason = parse_failure

    assert models.is_reachable(models.SOURCE_TRANSITIONS, models.SourceState.PROPOSED, models.SourceState(state)), (
        f"unreachable source state computed: {state}"
    )

    staged_path = _stage_bytes(staging_dir, source_id, ext or ".txt", normalized_text.encode("utf-8") if normalized_text else raw)

    source = models.SourceArtifact(
        id=source_id,
        workspace_id=workspace_id,
        origin=origin,
        source_type=source_type,
        uri=uri,
        owner=owner,
        permission_state=permission_state,
        acl_snapshot=acl_snapshot,
        sensitivity_label=sensitivity_label,
        version=str(version),
        retrieved_at=retrieved_at,
        content_hash=content_hash,
        state=state,
        byte_size=byte_size,
        local_path=str(staged_path),
        captured_at=models.now_iso(),
        hold_reason=hold_reason,
        supersedes=existing.id if existing else None,
    )

    audit_details = {"origin": origin, "sourceType": source_type, "uri": uri, "state": state}
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="source.ingest", subject_type="source", subject_id=source.id, details=audit_details,
    )

    writes = [("source", source)]
    if existing is not None:
        existing.state = models.SourceState.STALE.value
        existing.superseded_by = source.id
        existing.updated_at = models.now_iso()
        writes.append(("source", existing))

    persistence.commit_many(conn, writes, [audit])
    if existing is not None:
        _cascade_supersession(conn, workspace_id, existing, actor)
    return source


def _cascade_supersession(conn, workspace_id: str, old_source: models.SourceArtifact, actor: str) -> None:
    """FR-SRC-5/FR-M365-4: a changed/re-ingested source invalidates
    dependent evidence atoms and reopens citing claims/slides rather than
    silently continuing to trust stale content."""
    from . import evidence as evidence_mod  # local import avoids a cycle

    atoms = persistence.list_all(conn, "evidence", workspace_id, models.EvidenceAtom)
    for atom in atoms:
        if atom.source_id != old_source.id:
            continue
        atom.freshness_state = models.FreshnessState.STALE.value
        atom.updated_at = models.now_iso()
        audit = models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="evidence.mark_stale", subject_type="evidence", subject_id=atom.id,
            details={"reason": "source_reingested", "sourceId": old_source.id},
        )
        persistence.commit(conn, "evidence", atom, audit)
        evidence_mod.demote_dependent_claims(conn, workspace_id, atom.id, actor, reason="source_reingested")


def revoke_access(conn, workspace_id: str, source_id: str, actor: str) -> models.SourceArtifact:
    """Explicit access-revocation entry point (FR-SRC-5), e.g. invoked by
    the agent when a WorkIQ/GitHub recheck reports the user can no longer
    open a previously authorized source."""
    source = persistence.get(conn, "source", source_id, models.SourceArtifact)
    if source is None or source.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"source '{source_id}' not found", {"sourceId": source_id})
    source.state = models.SourceState.ACCESS_REVOKED.value
    source.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="source.access_revoked", subject_type="source", subject_id=source.id, details={},
    )
    persistence.commit(conn, "source", source, audit)

    from . import evidence as evidence_mod
    atoms = persistence.list_all(conn, "evidence", workspace_id, models.EvidenceAtom)
    for atom in atoms:
        if atom.source_id != source_id:
            continue
        atom.access_state = models.AccessState.ACCESS_REVOKED.value
        atom.updated_at = models.now_iso()
        audit2 = models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="evidence.access_revoked", subject_type="evidence", subject_id=atom.id, details={},
        )
        persistence.commit(conn, "evidence", atom, audit2)
        evidence_mod.demote_dependent_claims(conn, workspace_id, atom.id, actor, reason="access_revoked")
    return source


def retire_source(conn, workspace_id: str, source_id: str, actor: str) -> models.SourceArtifact:
    source = persistence.get(conn, "source", source_id, models.SourceArtifact)
    if source is None or source.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"source '{source_id}' not found", {"sourceId": source_id})
    source.state = models.SourceState.RETIRED.value
    source.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="source.retire", subject_type="source", subject_id=source.id, details={},
    )
    persistence.commit(conn, "source", source, audit)
    return source


def resolve_hold(conn, workspace_id: str, source_id: str, actor: str, decision: str) -> models.SourceArtifact:
    """Resolve a PARSE_FAILED/LABEL_CONFLICT/QUARANTINED hold. decision is
    'authorize' (accept and proceed) or 'retire' (drop from bundle)."""
    source = persistence.get(conn, "source", source_id, models.SourceArtifact)
    if source is None or source.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"source '{source_id}' not found", {"sourceId": source_id})
    held_states = {
        models.SourceState.PARSE_FAILED.value,
        models.SourceState.LABEL_CONFLICT.value,
        models.SourceState.QUARANTINED.value,
    }
    if source.state not in held_states:
        raise EngineError(
            "VALIDATION_ERROR", f"source '{source_id}' is not in a held state ({source.state})", {"state": source.state}
        )
    if decision not in ("authorize", "retire"):
        raise EngineError("VALIDATION_ERROR", "decision must be 'authorize' or 'retire'", {"decision": decision})
    source.state = models.SourceState.AUTHORIZED.value if decision == "authorize" else models.SourceState.RETIRED.value
    source.hold_reason = None if decision == "authorize" else source.hold_reason
    source.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="source.resolve_hold", subject_type="source", subject_id=source.id, details={"decision": decision},
    )
    persistence.commit(conn, "source", source, audit)
    return source


def quarantine_source(conn, workspace_id: str, source_id: str, actor: str, reason: str) -> models.SourceArtifact:
    source = persistence.get(conn, "source", source_id, models.SourceArtifact)
    if source is None or source.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"source '{source_id}' not found", {"sourceId": source_id})
    source.state = models.SourceState.QUARANTINED.value
    source.hold_reason = reason
    source.updated_at = models.now_iso()
    audit = models.AuditEvent(
        id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
        action="source.quarantine", subject_type="source", subject_id=source.id, details={"reason": reason},
    )
    persistence.commit(conn, "source", source, audit)
    return source


def staleness_window_days(source_type: str) -> Optional[int]:
    return STALE_WINDOW_DAYS.get(source_type)


def revalidate_staleness(conn, workspace_id: str, source_id: str, actor: str, now_override: Optional[str] = None) -> models.SourceArtifact:
    """§16.2 staleness rule, re-evaluated on workspace reopen and before
    every EVIDENCE gate run. Content/version-change staleness is applied at
    ingest time already (via supersession); this covers the elapsed-time
    leg for sources whose type has a window and haven't been re-ingested."""
    import datetime

    source = persistence.get(conn, "source", source_id, models.SourceArtifact)
    if source is None or source.workspace_id != workspace_id:
        raise EngineError("NOT_FOUND", f"source '{source_id}' not found", {"sourceId": source_id})
    window = staleness_window_days(source.source_type)
    if window is None or source.state in (
        models.SourceState.RETIRED.value, models.SourceState.STALE.value,
        models.SourceState.ACCESS_REVOKED.value,
    ):
        return source
    now = datetime.datetime.strptime(now_override, "%Y-%m-%dT%H:%M:%SZ") if now_override else datetime.datetime.utcnow()
    captured = datetime.datetime.strptime(source.captured_at, "%Y-%m-%dT%H:%M:%SZ")
    if (now - captured).days >= window:
        source.state = models.SourceState.STALE.value
        source.updated_at = models.now_iso()
        audit = models.AuditEvent(
            id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
            action="source.stale", subject_type="source", subject_id=source.id,
            details={"reason": "elapsed_time", "windowDays": window},
        )
        persistence.commit(conn, "source", source, audit)
        from . import evidence as evidence_mod
        atoms = persistence.list_all(conn, "evidence", workspace_id, models.EvidenceAtom)
        for atom in atoms:
            if atom.source_id != source_id:
                continue
            atom.freshness_state = models.FreshnessState.STALE.value
            atom.updated_at = models.now_iso()
            audit2 = models.AuditEvent(
                id=models.new_id("audit"), workspace_id=workspace_id, actor=actor,
                action="evidence.mark_stale", subject_type="evidence", subject_id=atom.id,
                details={"reason": "elapsed_time"},
            )
            persistence.commit(conn, "evidence", atom, audit2)
            evidence_mod.demote_dependent_claims(conn, workspace_id, atom.id, actor, reason="elapsed_time")
    return source
