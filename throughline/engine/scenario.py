"""`run-scenario` — the flagship black-box acceptance entry point (ARCH §4).

Runs one complete, declarative, non-interactive pass end-to-end: brief ->
sources (each paired with a `FetchResult`-shaped dict, so `origin:
workiq|github` needs no live MCP call) -> evidence dispositions -> claim
drafts/approvals -> conflict decisions -> narrative choice -> route choice
-> accessibility/demo declarations -> rehearsal timings -> stage-approval
actor -> (if Stage passes) the full 9-artifact package. Emits
`run-report.json` recording every intermediate `GateResult`, state
transition, and generated ID, so one test can assert the entire journey
without knowing every sub-command.

Three wire-compatible document shapes are accepted: the documented
object-form (one JSON object); a field-list form some black-box callers
send instead (a JSON array of single-key objects, one per top-level
field); and an action-list form (a JSON array whose elements each carry an
explicit `"action"` field naming one canonical, allowlisted public action
verb — e.g. `set_talk_brief`, `ingest_source`, `propose_claim` — plus that
action's own inline payload as the entry's other keys; see
`_ACTION_ALIASES` below for the full verb -> field vocabulary). Object-form
and field-list-form documents have no per-element sequence of their own to
preserve (a single JSON object's fields aren't ordered, and field-list
elements are only ever merged into that same object), so both are still
normalized once, up front (`_normalize_scenario_doc`), into a plain `dict`
and executed as one fixed-order batch by `_run_steps` below (unchanged by
Dark Factory hardening cycle 8). A *true* action-list document — every
element names an `"action"` verb — is different: it carries a real,
caller-authored sequence, and repeated verbs (26 `add_source` actions, an
interleaved `run_gate` before *and* after more sources are added, ...)
carry meaning a fixed-order batch can never represent, so it is instead
dispatched by `_run_ordered_action_list` below, straight from the original
document, one element at a time, in original order, immediately against
the same already-existing domain calls `_run_steps` itself uses (never a
second business-logic implementation) — every element's own effect is
durably persisted and visible to every element after it, and
`report["actionResults"]`/`report["action_results"]` carries one entry per
element (see that function's own docstring for the exact ledger shape).
See `_is_action_list_document` for exactly which documents route to which
executor (a mixed field-list/action-list document is not a *true*
action-list document, and keeps using the unchanged batch path).

See `docs/engine-cli-reference.md` for the full scenario JSON schema.

Runs are always non-interactive and always complete: a scenario step that
is correctly refused or blocked by a domain rule (an `EngineError`, e.g.
`WORKSPACE_ALREADY_ACTIVE`, `BUNDLE_LIMIT_REACHED`, `CONFLICT_UNRESOLVED`,
...) is caught here and recorded as `report["refusal"]` /
`report["ok"] = False` rather than raised — the caller (`cli.py`) still
sees a normal, successful invocation (exit code 0) with the refusal
represented in the result document, never in the exit code. A genuine
engine/runtime fault (anything *not* an `EngineError`, i.e. a real bug) is
deliberately left to propagate so `cli.py`'s own safety net still reports
it as a nonzero, explicit `INTERNAL_ERROR` — never silently absorbed here.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from . import (
    audit as audit_mod,
    claims as claims_mod,
    compiler,
    evidence as evidence_mod,
    gates,
    ingest as ingest_mod,
    models,
    narrative,
    package,
    persistence,
    rehearsal,
    restore as restore_mod,
    workspace as workspace_mod,
)
from .errors import EngineError


def _match_slide(ref: dict, slides: list[models.SlideSpec]) -> Optional[models.SlideSpec]:
    if "slideId" in ref or "slide_id" in ref:
        target = ref.get("slideId", ref.get("slide_id"))
        return next((s for s in slides if s.id == target), None)
    if "slideOrder" in ref or "slide_order" in ref:
        target = ref.get("slideOrder", ref.get("slide_order"))
        return next((s for s in slides if s.order == target), None)
    if "slideRole" in ref or "slide_role" in ref:
        role = str(ref.get("slideRole", ref.get("slide_role"))).upper()
        matches = [s for s in slides if s.role == role]
        idx = ref.get("occurrence", 0)
        return matches[idx] if idx < len(matches) else None
    return None


def _resolve_rehearsal_slide(key: Any, slides: list[models.SlideSpec]) -> Optional[models.SlideSpec]:
    """Resolves one `rehearsalTimings` mapping key to a slide -- tried in
    order: an exact `slideId` match (the primary CLI shape: `rehearse
    run`'s own `{"<slideId>": <actualSeconds>}` timings document, and
    `set_rehearsal_timing`/`rehearse`'s new `slideId` action-list alias),
    a `slideRole` match (case-insensitive; the pre-existing scenario-
    runner convenience shape, resolving to the *first* slide with that
    role -- unchanged), or a bare integer-parseable `slideOrder` position
    (the new `slideOrder` action-list alias). Mirrors `_match_slide`'s own
    existing slideId/slideOrder/slideRole precedence used elsewhere for
    accessibility/demo-asset matching. Returns `None` (silently skipped,
    exactly as an already-unmatched `slideRole` key always has been) if
    none match."""
    key_str = str(key)
    direct = next((s for s in slides if s.id == key_str), None)
    if direct is not None:
        return direct
    role_match = _match_slide({"slideRole": key_str}, slides)
    if role_match is not None:
        return role_match
    try:
        order = int(key)
    except (TypeError, ValueError):
        return None
    return _match_slide({"slideOrder": order}, slides)


def _disposition_for(atom: models.EvidenceAtom, source: models.SourceArtifact, overrides: list[dict], default: str) -> str:
    for rule in overrides:
        if "sourceUri" in rule and source.uri == rule["sourceUri"]:
            return rule["disposition"]
        if "locatorContains" in rule and rule["locatorContains"] in atom.locator:
            return rule["disposition"]
    return default


# --- Action-list scenario documents ----------------------------------------
#
# A third accepted `--scenario` document shape (alongside object-form and
# field-list form; see `_normalize_scenario_doc` below): a JSON array whose
# elements each carry an explicit `"action"` field naming exactly one
# canonical, allowlisted public action verb (see `_ACTION_ALIASES` below —
# never a raw object-form field name), plus that action's inline
# payload — every other key on the same element. This lets a black-box
# caller stream an ordered sequence of tagged steps (e.g. `{"action":
# "ingest_source", "uri": ..., "origin": ...}`) instead of pre-building a
# nested object, while still normalizing, deterministically and up front, into
# the identical object-form dict every other shape produces — never a
# second execution path. See `docs/engine-cli-reference.md` for the full,
# documented schema and `tests/test_scenario_action_list_form.py` for the
# exact accepted/rejected shapes.
#
# The `"action"` key itself is never a raw object-form field name (that
# was a prior, incorrect revision of this shape — the public black-box
# vocabulary uses semantic verbs, not internal field names, and rejected
# e.g. `set_talk_brief` as unknown because only bare `brief` was
# accepted). `_ACTION_ALIASES` is the one, explicit, allowlisted mapping
# from every accepted public action verb to exactly one object-form field
# above; an `"action"` value that isn't one of its keys — including a raw
# field name like `"brief"` or `"sources"` — is always a clean
# `VALIDATION_ERROR` naming the accepted vocabulary, never a guess.
#
# Each aliased field accepts exactly one of four payload shapes:
#   - "list object" (`_ACTION_LIST_OBJECT_FIELDS`): the field is a list of
#     objects (e.g. `sources`, `claims`). One action-list element
#     contributes exactly one list item, made up of every field on the
#     element except `"action"` itself (must be non-empty). May repeat
#     any number of times — that is the entire point of this shape.
#   - "list scalar" (`_ACTION_LIST_SCALAR_FIELDS`): the field is a list of
#     bare values (only `throughlineDrafts`). One element contributes one
#     item, carried in a reserved `"value"` field (no other fields
#     allowed). May also repeat freely.
#   - "object" (`_ACTION_OBJECT_FIELDS`): the field is itself a single
#     object (only `brief`). One element's non-`"action"` fields *are*
#     that object outright. May appear at most once (like a scalar field
#     below).
#   - "mapping" (`_ACTION_MAPPING_FIELDS`): the field is a `{key: value}`
#     dict (only `rehearsalTimings`). One element contributes one entry,
#     named by two fixed field names (`slideRole`/`seconds`). A repeated
#     key across elements is rejected as ambiguous (which value would
#     win?).
#   - "scalar" (`_ACTION_SCALAR_FIELDS`): every other field (`actor`,
#     `evidenceDefaultDisposition`, `customThroughline`,
#     `selectThroughlineIndex`, `selectRouteIndex`, `autoAltText`,
#     `skipDemos`, `stageApprover`) is a single primitive. Its value is
#     carried in a reserved `"value"` field, or (redundantly, but also
#     accepted) a field with the *field's own name* (not the action's) —
#     supplying *both* with two different values is rejected as
#     ambiguous. May appear at most once — a repeat (via *either* this
#     form or the field-list form) is the identical `VALIDATION_ERROR`
#     field-list form already raises for a repeated top-level field.

# Named-human-approver alias vocabulary shared by every gate/stage/claim/
# export action that accepts an explicit approver (Dark Factory hardening
# cycle 9, acceptance pass 12): a conservative, explicit allowlist of
# field names a public scenario caller commonly uses in place of this
# repository's own canonical `actor`/`stageApprover`/`approver` fields --
# `approver`, `approver_name`, `approverName`, `actor`, `human`, `name` --
# plus a `approval` wrapper object carrying one of those same keys nested
# one level down (e.g. `{"approval": {"approver": "Jane Doe"}}`), only
# ever consulted when its own value is unambiguously one recognized shape
# (a non-empty string, or a nested object naming one of the same fields).
# Every one of these only ever *fills in* the existing named-human-
# approval field -- never a second approval mechanism, never a way to
# supply a missing/automated approver (a value that resolves to nothing
# still falls through to whatever default/absence this call site already
# enforces), and two aliases naming two genuinely *different* strings is
# always an explicit `VALIDATION_ERROR`, never a silent pick.
_APPROVER_ALIAS_FIELDS = ("approver", "approver_name", "approverName", "actor", "human", "name")
_APPROVER_NESTED_ONLY_FIELDS = ("approval",)


def _extract_named_approver_string(value: Any) -> Optional[str]:
    """Resolves one already-fetched field value to a plain named-approver
    string: a non-empty (stripped) string is returned as-is; a nested
    object is searched, in `_APPROVER_ALIAS_FIELDS` order, for the first
    of those same keys carrying its own non-empty string (one level of
    nesting only -- e.g. `{"approver": {"name": "Jane Doe"}}` or
    `{"approval": {"approverName": "Jane Doe"}}`); anything else
    (missing, blank, a nested object naming none of them, or any other
    type) resolves to `None` -- never a guess."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, dict):
        for key in _APPROVER_ALIAS_FIELDS:
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        return None
    return None


def _resolve_named_approver_alias(payload: dict, *, action: str, index: Any, default: str) -> str:
    """Resolves an explicit named-human approver from any of
    `_APPROVER_ALIAS_FIELDS`/`_APPROVER_NESTED_ONLY_FIELDS` present on one
    action-list element's own inline payload -- several aliases naming
    the identical resolved string is fine (redundant, not ambiguous), but
    two aliases naming two *different* strings is an explicit
    `VALIDATION_ERROR`, never a silent pick. Falls back to `default` (the
    scenario's own whole-document actor/stageApprover) when no alias is
    present at all, or none of the ones present name a recognized shape
    -- never a missing/automated approver of its own invention."""
    found: dict[str, str] = {}
    for field in (*_APPROVER_ALIAS_FIELDS, *_APPROVER_NESTED_ONLY_FIELDS):
        if field not in payload:
            continue
        name = _extract_named_approver_string(payload[field])
        if name:
            found[field] = name
    distinct = set(found.values())
    if len(distinct) > 1:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} gives conflicting named-approver values via "
            f"{sorted(found)} (ambiguous: which one should win?)",
            {"index": index, "action": action, "fields": sorted(found)},
        )
    return next(iter(distinct)) if distinct else default


def _coerce_named_approver_scalar(value: Any, *, field_label: str) -> Any:
    """Resolves a scalar-field approver value (`stageApprover`, ...) that
    may have arrived as a nested object on a raw field-list/object-form
    document (e.g. `{"stageApprover": {"name": "Jane Doe"}}`, which the
    per-field-alias scalar mechanism below only unwraps for the
    `approve_stage` *action* form -- this covers every other document
    shape too) into a plain string. Anything that isn't a `dict` (a
    string, or `default` itself already a string) passes through
    unchanged; a `dict` naming none of `_APPROVER_ALIAS_FIELDS` is an
    explicit `VALIDATION_ERROR` -- never a silently-ignored/auto-approved
    object."""
    if not isinstance(value, dict):
        return value
    nested = _extract_named_approver_string(value)
    if nested is None:
        raise EngineError(
            "VALIDATION_ERROR",
            f"'{field_label}' was given as an object but names none of the recognized approver fields "
            f"({', '.join(_APPROVER_ALIAS_FIELDS)})",
            {"field": field_label},
        )
    return nested


_ACTION_LIST_OBJECT_FIELDS = frozenset({
    "sources", "evidenceOverrides", "claims", "conflictDecisions",
    "routeDrafts", "accessibility", "demoAssets", "qaPairs", "gateRuns", "exportRequests",
    "sourceRevocations", "sourceQuarantines", "sourceHoldResolutions", "sourceRetirements",
})
_ACTION_LIST_SCALAR_FIELDS = frozenset({"throughlineDrafts"})
_ACTION_OBJECT_FIELDS = frozenset({"brief"})
_ACTION_MAPPING_FIELDS: dict[str, tuple[str, str]] = {"rehearsalTimings": ("slideRole", "seconds")}
_ACTION_SCALAR_FIELDS = frozenset({
    "actor", "evidenceDefaultDisposition", "customThroughline", "selectThroughlineIndex",
    "selectRouteIndex", "autoAltText", "skipDemos", "stageApprover", "compileRequested",
})
# Additional, explicit public-vocabulary field-name aliases for specific
# `_ACTION_SCALAR_FIELDS` targets (Dark Factory hardening cycle 7) --
# each one a further redundant synonym for the identical target field,
# alongside the always-accepted `"value"` and the field's own name (see
# the generic scalar handling in `_apply_action_list_entry` below).
# Absent from this table (the default, `()`) for every other scalar
# field -- unchanged, `"value"`/own-name-only, exactly as before.
# `stageApprover` additionally accepts the full shared named-approver
# alias vocabulary (Dark Factory hardening cycle 9, acceptance pass 12)
# -- `approver`/`approver_name`/`approverName`/`actor`/`human`/`name`, or
# a nested `approval` object -- resolved to a plain string by
# `_apply_action_list_entry`'s generic scalar handling below before the
# conflict check runs, and again (for every *other* document shape, e.g.
# a raw field-list `{"stageApprover": {...}}`) by `_coerce_named_approver_
# scalar` wherever `stageApprover` is finally consumed.
_ACTION_SCALAR_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "stageApprover": (*_APPROVER_ALIAS_FIELDS, *_APPROVER_NESTED_ONLY_FIELDS),
}

# The canonical public action vocabulary (docs/engine-cli-reference.md's
# "Action vocabulary" table is the human-facing copy of this same table).
# Each verb is derived conservatively from this repository's own existing
# domain vocabulary — never invented — so the mapping stays auditable:
#   - most verbs mirror an existing CLI subcommand name verbatim, paired
#     with its command group's noun, e.g. `source ingest` -> "ingest_source",
#     `claim propose` -> "propose_claim", `conflict resolve` ->
#     "resolve_conflict", `narrative select-route` -> "select_route";
#   - where the CLI's own group noun is a shorthand for the full PRD/ARCH
#     entity or phrase, the action uses that fuller, unambiguous noun
#     instead, e.g. `brief set` -> "set_talk_brief" (PRD/ARCH's `TalkBrief`
#     entity / "the talk brief" — never bare "brief", ARCH §1 step 1,
#     FR-INV-1); and
#   - a handful of fields with no single owning CLI subcommand (they are
#     cross-cutting run-scenario-only inputs) get a plain verb+noun name
#     built the same way, e.g. "set_actor", "select_custom_throughline".
_ACTION_ALIASES: dict[str, str] = {
    "set_actor": "actor",
    "set_talk_brief": "brief",
    "ingest_source": "sources",
    # `add_source` is the canonical public-interface synonym for
    # `ingest_source` (same target field, same "source ingest" origin) --
    # the one field in this table intentionally reachable via two verbs;
    # `ingest_source` keeps working unchanged for existing callers.
    "add_source": "sources",
    "set_evidence_disposition": "evidenceOverrides",
    "set_default_evidence_disposition": "evidenceDefaultDisposition",
    "propose_claim": "claims",
    "resolve_conflict": "conflictDecisions",
    "propose_throughline": "throughlineDrafts",
    "select_custom_throughline": "customThroughline",
    "select_throughline": "selectThroughlineIndex",
    "propose_route": "routeDrafts",
    "select_route": "selectRouteIndex",
    # `select_narrative_route` is the canonical public-interface synonym
    # for `select_route` (same underlying route-selection field/logic,
    # named after the PRD/ARCH `NarrativeRoute` entity rather than the
    # CLI's shorter `select-route` verb) -- like `select_throughline`, it
    # is special-cased below to also accept an exact route-label `"text"`
    # selector once real routes exist, alongside the pre-existing numeric
    # `selectRouteIndex` contract both verbs already share.
    "select_narrative_route": "selectRouteIndex",
    "set_alt_text": "accessibility",
    "set_auto_alt_text": "autoAltText",
    "set_demo_asset": "demoAssets",
    "set_rehearsal_timing": "rehearsalTimings",
    # `rehearse` is the canonical public-interface synonym for
    # `set_rehearsal_timing` (same target field, same "rehearse run"
    # origin) -- drives the identical, already-existing
    # `rehearsal.run_rehearsal` code path.
    "rehearse": "rehearsalTimings",
    "skip_demos": "skipDemos",
    "record_qa": "qaPairs",
    "approve_stage": "stageApprover",
    # `run_gate` (ARCH's `gate run <name>`) explicitly, additionally
    # invokes one named gate (scope|evidence|narrative|claims|readiness|
    # stage) through the existing `gates.run_gate` logic, recorded as its
    # own report step -- additive only, never a substitute for (or a
    # reordering of) the mandatory automatic gate pipeline every scenario
    # already runs regardless of this action's presence.
    "run_gate": "gateRuns",
    # `compile_deck`/`compile_presentation` (ARCH's `compile`, "Compile"
    # in docs/engine-cli-reference.md) both name the deck-compilation
    # step every scenario already runs automatically and unconditionally
    # once a route is selected (`compiler.compile_deck` in `_run_steps`
    # below) -- neither verb gates or re-triggers that call, which is
    # unconditional regardless of whether either appears at all; they
    # exist only so a public action-list caller may name that step
    # explicitly without an unknown-action `VALIDATION_ERROR`. Two
    # verbs, one field (`compileRequested`, a plain marker -- see
    # `_apply_action_list_entry` below), mirroring the `sources`/
    # `selectRouteIndex`/`rehearsalTimings` two-synonym pattern above.
    "compile_deck": "compileRequested",
    "compile_presentation": "compileRequested",
    # `export` (ARCH's `export pptx`/`export package`, "Export" in
    # docs/engine-cli-reference.md) is the public action-list verb for
    # this repository's existing deck/Stage-package export behavior --
    # each element is one export request (see `_ACTION_LIST_OBJECT_FIELDS`
    # above: "exportRequests" is a plain "list of objects" field, exactly
    # like `gateRuns`), processed by `_run_steps` through the identical,
    # already-existing `package.export_pptx_draft`/`package.export_package`
    # calls `export pptx`/`export package` already use -- never a second
    # export code path, and never a bypass of either function's own
    # existing gate/approval checks (a `target: "package"` request still
    # re-runs the real Stage gate inside `package.export_package` itself;
    # a blocked export still surfaces as this module's normal
    # `EngineError` -> `report["refusal"]` contract, exit 0, never a
    # silent skip). See `_apply_action_list_entry`'s generic "list of
    # objects" handling above and the `exportRequests` processing in
    # `_run_steps` below for the accepted per-request payload shape.
    "export": "exportRequests",
    # `revoke_source`/`quarantine_source`/`resolve_source_hold`/
    # `retire_source` (ARCH's `source revoke`/`source quarantine`/
    # `source resolve-hold`/`source retire`) are the public action-list
    # verbs for this repository's existing source-lifecycle transitions
    # (FR-SRC-5/FR-SRC-6) -- each element is one lifecycle request
    # (plain "list of objects" fields, exactly like `gateRuns`/
    # `exportRequests`), processed by `_run_steps` through the identical,
    # already-existing `ingest.revoke_access`/`ingest.quarantine_source`/
    # `ingest.resolve_hold`/`ingest.retire_source` calls the CLI's own
    # `source revoke`/`source quarantine`/`source resolve-hold`/
    # `source retire` subcommands use -- never a second lifecycle code
    # path. A declarative one-pass scenario cannot know a source's
    # server-generated id ahead of time, so each request may reference the
    # source by its own `sourceId`/`source_id`, or by the `uri`/
    # `sourceUri`/`source_uri` it was ingested under (resolved to that
    # uri's current active source via `ingest.find_active_source_by_uri`)
    # -- see `_resolve_source_lifecycle_target` and the four processing
    # loops in `_run_steps` below.
    "revoke_source": "sourceRevocations",
    "quarantine_source": "sourceQuarantines",
    "resolve_source_hold": "sourceHoldResolutions",
    "retire_source": "sourceRetirements",
}
_KNOWN_ACTIONS = sorted(_ACTION_ALIASES)
assert set(_ACTION_ALIASES.values()) == (
    _ACTION_LIST_OBJECT_FIELDS | _ACTION_LIST_SCALAR_FIELDS | _ACTION_OBJECT_FIELDS
    | set(_ACTION_MAPPING_FIELDS) | _ACTION_SCALAR_FIELDS
), "every object-form field must have at least one canonical action alias"

# `select_throughline` is the one action verb whose inline payload can
# name its selector via any of four keys instead of a single fixed
# "value"/field-name pair (see `_apply_select_throughline_entry` below):
# the pre-existing numeric synonyms `"value"`/`"selectThroughlineIndex"`,
# plus two new public aliases -- `"choice"` (also numeric) and `"text"`
# (the verbatim text of either a proposed candidate or a wholly new
# custom one). Exactly one of these four keys (or several numeric
# synonyms agreeing on the same value) is required.
_SELECT_THROUGHLINE_NUMERIC_KEYS = ("value", "selectThroughlineIndex", "choice")
_SELECT_THROUGHLINE_TEXT_KEY = "text"
_SELECT_THROUGHLINE_ALLOWED_KEYS = frozenset(_SELECT_THROUGHLINE_NUMERIC_KEYS) | {_SELECT_THROUGHLINE_TEXT_KEY}


def _apply_select_throughline_entry(merged: dict[str, Any], payload: dict[str, Any], index: int) -> None:
    """Special-cased `select_throughline` handling (see the constants
    above) -- unlike every other scalar action, this one action's field
    target depends on *which* selector key its payload used:
      - a numeric selector (`"value"`, `"selectThroughlineIndex"`, or the
        new `"choice"` alias -- interchangeable synonyms for the same
        candidate index) is stored into `selectThroughlineIndex`, exactly
        the pre-existing object-form field `_run_steps` already reads.
      - the new `"text"` alias is stored into a second, new object-form
        field, `selectThroughlineText`, that `_run_steps` resolves against
        the actual generated candidates once they exist (matched
        verbatim text selects that candidate by id; anything else becomes
        a brand-new custom throughline) -- never guessed here, since the
        candidates don't exist yet at normalization time.
    Supplying both a numeric selector and `"text"`, several numeric
    synonyms that disagree, a non-integer numeric selector, an unexpected
    extra field, or no selector at all is always a clean
    `VALIDATION_ERROR`, never a guess."""
    extra = sorted(set(payload) - _SELECT_THROUGHLINE_ALLOWED_KEYS)
    if extra:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'select_throughline' at element {index} has unexpected inline payload field(s) "
            f'{extra}; expected one of "value", "selectThroughlineIndex", "choice", or "text"',
            {"index": index, "action": "select_throughline", "unexpectedFields": extra},
        )
    numeric_values = {payload[k] for k in _SELECT_THROUGHLINE_NUMERIC_KEYS if k in payload}
    has_text = bool(str(payload.get(_SELECT_THROUGHLINE_TEXT_KEY, "")).strip())

    if len(numeric_values) > 1:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'select_throughline' at element {index} gives conflicting index values via "
            '"value"/"selectThroughlineIndex"/"choice" (ambiguous: which one should win?)',
            {"index": index, "action": "select_throughline"},
        )
    has_numeric = len(numeric_values) == 1

    if has_numeric and has_text:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'select_throughline' at element {index} gives both a numeric selector and "
            '"text" (ambiguous: which selection should win?)',
            {"index": index, "action": "select_throughline"},
        )
    if not has_numeric and not has_text:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'select_throughline' at element {index} is missing its inline selector; "
            'expected "value", "selectThroughlineIndex", "choice", or "text"',
            {"index": index, "action": "select_throughline"},
        )

    already_used = "selectThroughlineIndex" in merged or "selectThroughlineText" in merged

    if has_numeric:
        (raw_value,) = numeric_values
        try:
            idx = int(raw_value)
        except (TypeError, ValueError):
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'select_throughline' at element {index} has a non-integer index selector "
                f"({raw_value!r})",
                {"index": index, "action": "select_throughline", "value": raw_value},
            ) from None
        if already_used:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'select_throughline' at element {index} repeats an earlier "
                "'select_throughline' selection (ambiguous, even via a different selector key)",
                {"index": index, "field": "selectThroughlineIndex", "action": "select_throughline"},
            )
        merged["selectThroughlineIndex"] = idx
        return

    if already_used:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'select_throughline' at element {index} repeats an earlier "
            "'select_throughline' selection (ambiguous, even via a different selector key)",
            {"index": index, "field": "selectThroughlineText", "action": "select_throughline"},
        )
    merged["selectThroughlineText"] = str(payload[_SELECT_THROUGHLINE_TEXT_KEY]).strip()


# `select_narrative_route` mirrors `select_throughline`'s own numeric/text
# selector shape (see the constants and function above) for the parallel
# route-selection field: the pre-existing numeric synonyms `"value"`/
# `"selectRouteIndex"`, plus the `"choice"` alias, all still resolve into
# `selectRouteIndex` exactly as `select_route` already does; the new
# `"text"` alias resolves into a new field, `selectRouteText`, matched
# once real candidate routes exist. Unlike a throughline, a route is a
# full beat spine, never freeform text, so there is no "custom route"
# fallback -- `"text"` matching none of the candidate routes' own labels
# is a normal, correctly-refused mid-walk step (see
# `_resolve_route_selection` below), never a guessed/synthesized route.
_SELECT_ROUTE_NUMERIC_KEYS = ("value", "selectRouteIndex", "choice")
_SELECT_ROUTE_TEXT_KEY = "text"
_SELECT_ROUTE_ALLOWED_KEYS = frozenset(_SELECT_ROUTE_NUMERIC_KEYS) | {_SELECT_ROUTE_TEXT_KEY}


def _apply_select_narrative_route_entry(merged: dict[str, Any], payload: dict[str, Any], index: int) -> None:
    """Special-cased `select_narrative_route` handling (see the constants
    above) -- structurally identical to `_apply_select_throughline_entry`:
    a numeric selector (`"value"`, `"selectRouteIndex"`, or `"choice"`) is
    stored into `selectRouteIndex`, the pre-existing field `_run_steps`
    already reads (and `select_route` already targets); the new `"text"`
    alias is stored into a new field, `selectRouteText`, resolved by
    `_resolve_route_selection` once the real candidate routes exist.
    Supplying both a numeric selector and `"text"`, several numeric
    synonyms that disagree, a non-integer numeric selector, an unexpected
    extra field, or no selector at all is always a clean
    `VALIDATION_ERROR`, never a guess."""
    extra = sorted(set(payload) - _SELECT_ROUTE_ALLOWED_KEYS)
    if extra:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'select_narrative_route' at element {index} has unexpected inline payload "
            f'field(s) {extra}; expected one of "value", "selectRouteIndex", "choice", or "text"',
            {"index": index, "action": "select_narrative_route", "unexpectedFields": extra},
        )
    numeric_values = {payload[k] for k in _SELECT_ROUTE_NUMERIC_KEYS if k in payload}
    has_text = bool(str(payload.get(_SELECT_ROUTE_TEXT_KEY, "")).strip())

    if len(numeric_values) > 1:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'select_narrative_route' at element {index} gives conflicting index values via "
            '"value"/"selectRouteIndex"/"choice" (ambiguous: which one should win?)',
            {"index": index, "action": "select_narrative_route"},
        )
    has_numeric = len(numeric_values) == 1

    if has_numeric and has_text:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'select_narrative_route' at element {index} gives both a numeric selector and "
            '"text" (ambiguous: which selection should win?)',
            {"index": index, "action": "select_narrative_route"},
        )
    if not has_numeric and not has_text:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'select_narrative_route' at element {index} is missing its inline selector; "
            'expected "value", "selectRouteIndex", "choice", or "text"',
            {"index": index, "action": "select_narrative_route"},
        )

    already_used = "selectRouteIndex" in merged or "selectRouteText" in merged

    if has_numeric:
        (raw_value,) = numeric_values
        try:
            idx = int(raw_value)
        except (TypeError, ValueError):
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'select_narrative_route' at element {index} has a non-integer index "
                f"selector ({raw_value!r})",
                {"index": index, "action": "select_narrative_route", "value": raw_value},
            ) from None
        if already_used:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'select_narrative_route' at element {index} repeats an earlier "
                "route selection (ambiguous, even via a different selector key)",
                {"index": index, "field": "selectRouteIndex", "action": "select_narrative_route"},
            )
        merged["selectRouteIndex"] = idx
        return

    if already_used:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'select_narrative_route' at element {index} repeats an earlier "
            "route selection (ambiguous, even via a different selector key)",
            {"index": index, "field": "selectRouteText", "action": "select_narrative_route"},
        )
    merged["selectRouteText"] = str(payload[_SELECT_ROUTE_TEXT_KEY]).strip()


# `ingest_source`/`add_source`'s inline payload accepts either its
# documented direct-field shape, or that same set of fields nested inside
# an arbitrarily-*named* container, at any depth (Dark Factory hardening
# cycle 11, acceptance pass 14: a structural, conservative descriptor
# extractor replaces the previous fixed six-name wrapper allowlist --
# `source`/`descriptor`/`value`/`params`/`payload`/`input` -- which
# refused a descriptor nested under any *other* wrapper spelling with an
# originless `VALIDATION_ERROR`, even when the real fields were present
# just one layer "too deep").
#
# A key is recognized as a source-descriptor *container* worth peeling
# through -- never by matching its own name against a guessed list --
# purely by what it structurally carries: its value is a non-empty dict
# (or a non-empty list of non-empty dicts) that itself already carries,
# directly or through further such containers, at least one of this
# module's own conservative, allowlisted semantic leaf keys below (the
# same locator/content/type/auth metadata vocabulary a `FetchResult` --
# or any of its already-recognized field-name aliases; see
# `ingest.SOURCE_PAYLOAD_FIELD_ALIASES` -- is built from). A key that is
# itself one of these semantic leaves (`uri`, `owner`, `title`, ...) is
# never treated as a container, even if its own value happens to be
# dict-/list-shaped -- it is always this level's own field value, per
# the caller's own explicit naming.
_SOURCE_DESCRIPTOR_SEMANTIC_KEYS = frozenset({
    # locator
    "uri", "url", "href", "link", "path", "file", "filename",
    # locator, cont'd (Dark Factory hardening cycle 12): further
    # conservative locator/path synonyms -- a scenario-fixture reference,
    # an on-disk artifact/document/upload path, or a generic
    # "reference"/`ref` -- resolved into the canonical `uri` by
    # `ingest.SOURCE_PAYLOAD_FIELD_ALIASES`, never a second vocabulary.
    "locator", "source_locator", "fixture", "fixture_path", "artifact", "artifact_path",
    "document", "document_path", "file_path", "local_file", "input_file", "input_path",
    "content_file", "content_path", "upload", "upload_path", "reference", "ref",
    # naming / inline content
    "name", "title", "content", "text", "body", "transcript",
    # type / format
    "source_type", "type", "kind", "format", "mime", "mime_type",
    "source_kind", "document_type", "artifact_type",
    # origin / connector
    "origin", "connector", "provider",
    # auth / access / ownership
    "access", "authorized", "permission", "label", "owner", "author",
    # already-canonical/aliased spellings not already covered above, so a
    # descriptor made up entirely of these is recognized too
    "source_uri", "local_path", "web_url", "content_base64",
    "permission_state", "access_state", "acl_snapshot", "permission_snapshot",
    "sensitivity_label", "label_state", "retrieved_at", "authorized_at", "version",
})

# Field names that belong to this action-list's own control plane --
# `action` itself, and the same named-human-approver/gate/export
# vocabulary every *other* action verb already uses elsewhere in this
# module (`_APPROVER_ALIAS_FIELDS`/`_APPROVER_NESTED_ONLY_FIELDS`,
# `_GATE_RUN_NAME_FIELDS`, `_EXPORT_RENDER_MODE_FIELD_NAMES`/export result
# fields -- spelled out here as plain literals, never a second vocabulary,
# since those tables are defined later in this module) -- excluded from
# source-descriptor discovery/merging at every depth: never treated as a
# semantic leaf, never counted as a sibling to merge into a resolved
# descriptor, even if such a field were ever found sitting alongside real
# source-descriptor content. Deliberately excludes bare `name` -- unlike
# an approval action's own use of that word, a source descriptor's own
# `name` is a genuine, conservative descriptor signal (see above).
_SOURCE_DESCRIPTOR_CONTROL_KEYS = frozenset({
    "action", "actor", "approver", "approver_name", "human", "approval", "stage_approver",
    "gate", "gate_name", "render_mode", "export_dir", "manifest_id", "deck_id",
})

_DESCRIPTOR_KEY_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _normalize_descriptor_key(key: Any) -> str:
    """`"sourceUri"`/`"source-uri"`/`"Source Uri"`-style spellings all
    collapse to the identical `"source_uri"` snake_case form -- mirrors
    `ingest._camel_to_snake` -- so `_SOURCE_DESCRIPTOR_SEMANTIC_KEYS`/
    `_SOURCE_DESCRIPTOR_CONTROL_KEYS` membership never depends on a
    caller's own casing/punctuation convention. A non-string key (never
    valid JSON, but never trusted to crash this check either) resolves to
    `""`, which matches neither set."""
    if not isinstance(key, str):
        return ""
    snake = _DESCRIPTOR_KEY_BOUNDARY_RE.sub("_", key)
    return snake.strip().replace("-", "_").replace(" ", "_").lower()


def _has_descriptor_signal(value: Any) -> bool:
    """True if `value` is a non-empty dict directly carrying at least one
    `_SOURCE_DESCRIPTOR_SEMANTIC_KEYS` key (control keys are never a
    signal), or -- recursively -- nests, through further non-semantic,
    non-control container keys, to a descendant dict that does; true for
    a non-empty list if any of its dict items independently carries such
    signal. False for a scalar, an empty dict/list, or a dict/list
    carrying only control-keyed and/or signal-free data."""
    if isinstance(value, dict):
        if not value:
            return False
        for k in value:
            nk = _normalize_descriptor_key(k)
            if nk in _SOURCE_DESCRIPTOR_CONTROL_KEYS:
                continue
            if nk in _SOURCE_DESCRIPTOR_SEMANTIC_KEYS:
                return True
        for k, v in value.items():
            nk = _normalize_descriptor_key(k)
            if nk in _SOURCE_DESCRIPTOR_CONTROL_KEYS or nk in _SOURCE_DESCRIPTOR_SEMANTIC_KEYS:
                continue
            if _has_descriptor_signal(v):
                return True
        return False
    if isinstance(value, list):
        return any(_has_descriptor_signal(item) for item in value if isinstance(item, dict))
    return False


def _is_source_descriptor_container(key: Any, value: Any) -> bool:
    """True if `key`/`value` is an eligible container to peel through --
    `key` itself names neither a control field nor one of this module's
    own semantic leaves (see `_SOURCE_DESCRIPTOR_SEMANTIC_KEYS` above),
    and `value` is a non-empty dict, or a non-empty list of non-empty
    dicts, that already carries real descriptor signal
    (`_has_descriptor_signal`). Never true for an empty dict/list (see
    `_check_empty_source_descriptor_candidate` below for that narrower,
    separate check) or for a bare scalar (a lone unrecognized string
    field is instead resolved by `ingest._apply_bare_scalar_field_hint`,
    once this container search bottoms out onto a terminal descriptor)."""
    nk = _normalize_descriptor_key(key)
    if nk in _SOURCE_DESCRIPTOR_CONTROL_KEYS or nk in _SOURCE_DESCRIPTOR_SEMANTIC_KEYS:
        return False
    if isinstance(value, dict):
        return bool(value) and _has_descriptor_signal(value)
    if isinstance(value, list):
        return bool(value) and all(isinstance(item, dict) and item for item in value) and _has_descriptor_signal(value)
    return False


def _meets_source_identity_bar(candidate: dict[str, Any]) -> bool:
    """Dark Factory hardening cycle 11 (acceptance pass 14): the
    deterministic sufficiency score every source-descriptor candidate is
    judged by wherever this module must silently pick among several
    (`_select_source_descriptor_container` below) or decide whether an
    otherwise-empty-looking candidate is truly empty
    (`_check_empty_source_descriptor_candidate` below): a candidate is
    "sufficient" iff, once fully field-alias-normalized (`ingest.
    normalize_source_payload` -- the exact same resolution `ingest_source`
    itself will later apply), it carries a real `uri` -- a locator given
    directly, *or* one `ingest._apply_manual_upload_hint`/
    `ingest._apply_bare_scalar_field_hint` could already, conservatively,
    synthesize from inline content plus a filename/type/title hint. A
    candidate whose own fields outright conflict (e.g. two disagreeing
    `sourceType` aliases) is never "sufficient" on its own -- never
    silently favored over a genuinely valid sibling candidate -- but that
    same conflict still surfaces normally (never swallowed) if this
    candidate is the only one, or is the one actually selected."""
    try:
        resolved = ingest_mod.normalize_source_payload(candidate)
    except EngineError:
        return False
    return bool(resolved.get("uri"))


def _check_empty_source_descriptor_candidate(value: dict[str, Any], action: str, index: int) -> None:
    """Called only once `value` has already been found to carry *no*
    eligible container (`_is_source_descriptor_container` found none) --
    catches the one remaining case a purely content-based container test
    can never see on its own: a key that is clearly meant to carry a
    nested descriptor (an otherwise-eligible name: not a control/semantic
    key) but was left an empty `{}`/`[]`. Raises the same clean
    `VALIDATION_ERROR` an empty wrapper has always raised only when
    exactly one such empty candidate exists *and* `value`'s own remaining
    fields don't already carry sufficient source identity on their own
    (`_meets_source_identity_bar`) -- never for a name that merely
    happens to carry incidental, unrelated empty metadata (e.g. `{"uri":
    "x", "tags": []}`, left completely alone whenever the rest of the
    descriptor already stands on its own), and never a guess when two or
    more empty candidates make "which one did the caller mean" itself
    ambiguous (silently falls through to the normal, unchanged direct-
    descriptor handling, which will fail its own real-field validation
    downstream exactly as it always has)."""
    empty_candidates = [
        k for k, v in value.items()
        if _normalize_descriptor_key(k) not in _SOURCE_DESCRIPTOR_CONTROL_KEYS
        and _normalize_descriptor_key(k) not in _SOURCE_DESCRIPTOR_SEMANTIC_KEYS
        and isinstance(v, (dict, list)) and not v
    ]
    if len(empty_candidates) != 1:
        return
    (empty_key,) = empty_candidates
    remaining = {k: v for k, v in value.items() if k != empty_key}
    if _meets_source_identity_bar(remaining):
        return
    shape = "list" if isinstance(value[empty_key], list) else "object"
    raise EngineError(
        "VALIDATION_ERROR",
        f"action '{action}' at element {index} has a '{empty_key}' field that must be a "
        f"non-empty source descriptor {shape}",
        {"index": index, "action": action, "field": "sources", "wrapperField": empty_key},
    )


def _check_signal_free_source_descriptor_candidate(value: dict[str, Any], action: str, index: int) -> None:
    """Dark Factory hardening cycle 12 (FR-SRC-1, "descriptor presence
    without a known key"): the non-empty sibling of
    `_check_empty_source_descriptor_candidate` above -- called
    immediately alongside it, under the identical "no eligible container
    found" precondition (`_is_source_descriptor_container` found none
    anywhere in `value`). Catches a key that is clearly meant to carry a
    nested descriptor (an otherwise-eligible name: not a control/semantic
    key) and *is* non-empty, but whose own content carries no recognized
    source locator/content/type/auth signal at all
    (`_has_descriptor_signal` is false for it, exactly like every other
    container-eligibility check in this module) -- an opaque, unrelated
    payload shape that merely happens to sit under a plausible-looking
    wrapper name is never silently reinterpreted as "the" source
    descriptor (an arbitrary object/name is never accepted as a source
    merely for having *a* name), and never silently, confusingly left to
    fail downstream with a generic `origin`/`uri` validation error either.

    Raises the identical clean `VALIDATION_ERROR` shape
    `_check_empty_source_descriptor_candidate` already uses only when
    exactly one such candidate exists *and* `value`'s own remaining
    fields don't already carry sufficient source identity on their own
    (`_meets_source_identity_bar`) -- the same safety valve, so a
    genuinely unrelated, incidental object/list sitting alongside a real,
    already-sufficient descriptor (e.g. `{"uri": "notes.md", "tags":
    {"internal": "x"}}`) is still left completely alone. Two or more such
    candidates is equally never a guess (silently falls through to the
    normal, unchanged direct-descriptor handling, which fails its own
    real-field validation downstream exactly as it always has). Never
    applied to a scalar value at all -- that shape is
    `ingest._apply_bare_scalar_field_hint`'s own, separate, and already
    conservative contract (a locator-/content-shaped scalar is accepted
    there; a bare, hint-less, non-locator-shaped one is left unchanged,
    never guessed at here either)."""
    signal_free_candidates = [
        k for k, v in value.items()
        if _normalize_descriptor_key(k) not in _SOURCE_DESCRIPTOR_CONTROL_KEYS
        and _normalize_descriptor_key(k) not in _SOURCE_DESCRIPTOR_SEMANTIC_KEYS
        and isinstance(v, (dict, list)) and v and not _has_descriptor_signal(v)
    ]
    if len(signal_free_candidates) != 1:
        return
    (candidate_key,) = signal_free_candidates
    remaining = {k: v for k, v in value.items() if k != candidate_key}
    if _meets_source_identity_bar(remaining):
        return
    shape = "list" if isinstance(value[candidate_key], list) else "object"
    raise EngineError(
        "VALIDATION_ERROR",
        f"action '{action}' at element {index} has a '{candidate_key}' field that does not carry a "
        f"recognized source locator/content/type/auth field, so this {shape} cannot be treated as a "
        "source descriptor",
        {"index": index, "action": action, "field": "sources", "wrapperField": candidate_key},
    )


def _normalize_source_field_aliases(item: dict[str, Any]) -> dict[str, Any]:
    """Thin delegate to `ingest_mod.normalize_source_payload` -- kept as
    its own named function (rather than inlining the call at each of this
    module's call sites below) so this module's own docstrings/tests can
    keep referring to it by name. Also applies `_apply_default_local_origin`
    (Dark Factory hardening cycle 12, widened in cycle 13) immediately
    afterward, so every one of this module's own call sites gets the
    identical, `add_source`-only conservative default-local
    classification. Returns a plain descriptor dict -- no internal marker
    of any kind -- so every existing unit test comparing a normalized
    descriptor for exact equality is completely unaffected; a scenario
    element's *further* eligibility for `_apply_add_source_local_defaults`
    below (sourceType/owner/permissionState) is instead tracked
    separately, by object identity, in `run_scenario`'s own
    `add_source_scope` set (see `_apply_action_list_entry`)."""
    return _apply_default_local_origin(ingest_mod.normalize_source_payload(item))


# Dark Factory hardening cycle 13: a small, explicit allowlist of
# pseudo-schemes this module treats as unambiguously naming a local/
# manual reference rather than a network locator -- consulted only by
# `_looks_like_non_remote_locator` below, itself consulted only by
# `_apply_default_local_origin`'s own widened fallback. `file` is also
# already recognized generally by `ingest._looks_like_local_filesystem_
# path` (consulted by `infer_origin`, so a `file:` locator never even
# reaches this fallback); `paste`/`manual-upload`/`fixture`/`upload`/
# `local` are this module's own, additional, conservative pseudo-scheme
# vocabulary for a scenario add_source descriptor's own opaque locator --
# distinct from, and never widening, `ingest._ORIGIN_ALIASES`'s own
# general connector-alias table (a scheme here is never treated as a
# `sourceType`/`origin` synonym, only as a locator-shape signal).
_LOCAL_PSEUDO_SCHEMES = frozenset({"file", "paste", "manual-upload", "fixture", "upload", "local"})


def _looks_like_non_remote_locator(uri: Any) -> bool:
    """Dark Factory hardening cycle 13: true for a `uri` that is
    unambiguously *not* a network locator -- consulted only by
    `_apply_default_local_origin` below, once `ingest.infer_origin` has
    already found no confident match at all (no recognized `sourceType`,
    no GitHub/Microsoft/WorkIQ host or `workiq://` scheme hint, no
    recognized local file extension on a schemeless path). True for:

      - One of this module's own conservative local pseudo-scheme
        allowlist above (`_LOCAL_PSEUDO_SCHEMES`) -- an opaque fixture/
        manual locator such as `fixture:widget-42`/`paste:...`/
        `manual-upload:...`/`upload:...` is unambiguously local *because*
        of this explicit scheme, regardless of how opaque the remainder
        of the string is.
      - A Windows drive-letter scheme (`C:\\notes.md`), mirroring
        `ingest._looks_like_local_filesystem_path`'s own identical
        special case.
      - A completely schemeless string that also contains a path
        separator (`/` or `\\`) -- a relative or absolute filesystem
        path/identifier, e.g. `subdir/notes-without-extension` or
        `/Users/x/fixtures/widget`.

    False for empty/non-string input; false for *any* other named scheme
    -- `http`/`https`, or any other, wholly unrecognized network-shaped
    scheme (`ftp://`, `s3://`, `sharepoint://`, a caller's own bespoke
    connector scheme, ...) -- never a guess for a scheme this module
    doesn't already, explicitly, know is local; and false for a
    completely schemeless, separator-less bare token (e.g. a ticket-
    shaped `"PROJ-1234"`) -- FR-SRC-1's own "never a guess" contract, and
    `UnknownRemoteReferenceRejectionTests`' own explicit "a bare
    arbitrary id is never treated as a genuine locator merely for having
    been given through a locator-flavored field name" contract, are both
    completely unaffected by this rule: an opaque *identifier* alone,
    with no scheme and no path shape at all, remains exactly as
    ambiguously refused as before this hardening cycle. (A schemeless
    path's own recognized-extension case is already handled earlier, by
    `infer_origin` itself, before this fallback is ever consulted --
    never duplicated here.)"""
    if not isinstance(uri, str) or not uri.strip():
        return False
    stripped = uri.strip()
    try:
        scheme = urlsplit(stripped).scheme.lower()
    except ValueError:
        return True
    if scheme in _LOCAL_PSEUDO_SCHEMES:
        return True
    if scheme == "":
        return "/" in stripped or "\\" in stripped
    return len(scheme) == 1


def _apply_default_local_origin(resolved: dict[str, Any]) -> dict[str, Any]:
    """Dark Factory hardening cycle 12 (widened in cycle 13): a
    conservative default-local classification for the `add_source`/
    `ingest_source` action-list verb *only* -- this module's own
    scenario-level entry point, never `ingest.ingest_source`'s own
    direct/raw-CLI contract (`source ingest --input ...`), which still
    requires an explicit or contextually-inferable `origin` exactly as
    before this hardening cycle (see `docs/engine-cli-reference.md`).

    Applies only when `origin` is still completely absent from the
    already fully field-alias-resolved `resolved` descriptor *and*
    `ingest.infer_origin`'s own existing, universal inference (from
    `sourceType`'s format word, a `uri`'s github/workiq host/scheme, or
    a recognized local-file extension) already gives no confident match
    at all -- so this rule never overrides, and never duplicates, that
    pre-existing mechanism. An HTTP(S) URL, a GitHub locator, or a
    Microsoft/WorkIQ locator is always already placed by it (or by an
    explicit `origin`/`connector`/`provider` value already resolved
    earlier in `normalize_source_payload`, which this function is always
    called after) long before this rule is ever consulted -- and an
    explicit origin that outright contradicts an inferable connector is
    caught even earlier still, by `ingest_source` itself. Nothing here
    ever second-guesses either of those.

    Classifies the remaining, still-unplaced descriptor as `local` when
    it already, independently, carries any one of three conservative,
    unambiguous "this is a manual/local reference" signals:

      - `ingest.carries_manual_upload_hint` is already true for it --
        `ingest._apply_manual_upload_hint` (part of the same
        `normalize_source_payload` pass) already refuses to fire for a
        descriptor whose `origin`/`sourceType` confidently implies
        `github`/`workiq`, so reaching here with that marker set always
        means a genuine manual/local upload (a `filename`/`file`/`name`
        naming hint, or a `sourceType`/`title` hint, alongside inline
        content), merely not yet classified -- e.g. a `title`-only,
        content-bearing descriptor synthesizes a `manual-upload:<hash>`
        `uri` that (unlike a real filename's own extension) `infer_origin`
        cannot place on its own.
      - The descriptor carries non-empty inline `content`/
        `contentBase64` directly, even without any filename/type/title
        hint of its own -- a bare paste is still local content, never a
        remote one; if no `uri` ends up established for it, it still
        fails afterward for a separate, genuinely specific reason
        (`uri is required`), never silently authorized as anything.
      - (Dark Factory hardening cycle 13) The descriptor's own `uri` is
        `_looks_like_non_remote_locator` -- an opaque fixture/manual
        locator on one of this module's local pseudo-schemes, or a
        filesystem-shaped path -- even with *no* inline content and no
        manual-upload hint at all. This is the narrow gap the two rules
        above never covered: a descriptor that names its own local
        reference directly (rather than via a naming hint alongside
        inline content) but whose `uri` has no extension `infer_origin`'s
        own file-extension tier could already recognize.

    Never applied to a descriptor whose real `uri` is itself network-
    shaped, or is a bare, scheme-less, separator-less opaque identifier
    (an unrecognized scheme/host `infer_origin` didn't already place, and
    `_looks_like_non_remote_locator` doesn't either) -- an ambiguous
    remote reference, or an arbitrary name/id given through one of this
    hardening cycle's own new locator-shaped field names, stays exactly
    as conservatively refused as before (FR-SRC-1's own "never a guess"
    contract)."""
    if resolved.get("origin"):
        return resolved
    if ingest_mod.infer_origin(resolved.get("sourceType"), resolved.get("uri")) is not None:
        return resolved
    has_manual_upload_hint = ingest_mod.carries_manual_upload_hint(resolved)
    has_inline_content = (
        (resolved.get("content") not in (None, ""))
        or (resolved.get("contentBase64") not in (None, ""))
    )
    has_non_remote_locator = _looks_like_non_remote_locator(resolved.get("uri"))
    if not (has_manual_upload_hint or has_inline_content or has_non_remote_locator):
        return resolved
    result = dict(resolved)
    result["origin"] = "local"
    return result


def _apply_add_source_local_defaults(src_payload: dict[str, Any], actor: str) -> dict[str, Any]:
    """Dark Factory hardening cycle 13: three further, narrowly-scoped
    defaults for a scenario `add_source`/`ingest_source` action-list
    element already classified `origin: "local"` (whether by an
    explicit/aliased `origin`, `ingest.infer_origin`'s own general
    inference, or `_apply_default_local_origin`'s conservative fallback
    above). Callers apply this only to a descriptor that actually came
    through this module's own add_source/ingest_source normalization --
    `_run_ordered_action_list`'s own `_dispatch` calls it unconditionally
    (every element of a *true* action-list document names an explicit
    action, so every "sources" contribution it ever sees is already
    add_source-scoped by construction); `_run_steps` calls it only for an
    item whose identity is present in `run_scenario`'s own
    `add_source_scope` set (built during normalization -- see
    `_apply_action_list_entry`), since its own merged `doc["sources"]`
    list may also contain raw, directly-documented `{"sources": [...]}`
    field entries that never ran through this normalization at all, and
    which must keep requiring every field spelled out explicitly, exactly
    as before this hardening cycle. `ingest.ingest_source`'s own direct/
    raw-CLI contract never calls this function either.

    Applied immediately before this element's own contribution is
    actually ingested -- never at normalization time, before this whole
    document's own `actor` (a whole-document, position-independent config
    value, resolved once in `run_scenario` and reused unchanged for every
    element regardless of its own position) is finally known:

      - `sourceType`, if omitted, defaults to the existing canonical
        `local_upload` type -- the identical default `ingest_source`
        itself already applies for a recognized local file extension or
        manual-upload hint; this only widens *when* it is filled in (any
        local add_source with no sourceType of its own at all), never a
        new/different default value.
      - `owner`, if omitted, defaults to this whole document's own
        `actor` -- the person the scenario is already running as, who is
        the one explicitly adding this source; possession/authorship of
        a manually-added local reference is never ambiguous the way a
        remote fetch's own declared owner metadata would be.
      - `permissionState`, if omitted, defaults to `"authorized"` --
        ARCH §7's own `LocalFetcher` contract already documents that
        manually-added local content is always authorized ("permission
        State is always authorized, since it's the user's own local
        content"); this only makes that same rule observable for a
        scenario descriptor that omitted the field entirely, rather than
        one that always spelled it out.

    "Omitted" means completely absent or blank -- an explicit value of
    any kind (including an explicit `permissionState: "denied"`, or any
    other considered value) is always left completely untouched; this
    function only ever fills a genuine gap, never upgrades/overrides a
    considered signal (explicit denial, or any other explicit value,
    always wins). Never applied to anything but a `local`-origin
    descriptor -- a github/workiq add_source is returned unchanged.

    Also never applied while `uri` itself is still completely absent --
    a bare, locator-less descriptor (e.g. inline content with no naming/
    type hint of any kind, `DefaultLocalClassificationSafetyTests.
    test_bare_content_only_no_hint_at_all_classifies_local_but_still_
    needs_a_locator`) must keep failing for its own separate, honest
    `uri is required`-style reason, exactly as before this hardening
    cycle. This also sidesteps a subtle, otherwise-real interaction:
    `ingest_source` re-runs `normalize_source_payload` on whatever it is
    given, and `ingest._apply_manual_upload_hint` treats a *newly*-
    present `sourceType` as its own "type hint" license to synthesize a
    `manual-upload:<hash>` `uri` for bare inline content -- so defaulting
    `sourceType` before a real `uri` already exists could accidentally
    manufacture one where none was ever supplied, silently rescuing a
    descriptor the product has deliberately decided must stay refused."""
    if not src_payload.get("uri"):
        return src_payload
    if ingest_mod.normalize_origin(src_payload.get("origin")) != "local":
        return src_payload
    result = dict(src_payload)
    if not result.get("sourceType"):
        result["sourceType"] = "local_upload"
    if not result.get("owner"):
        result["owner"] = actor
    if not result.get("permissionState"):
        result["permissionState"] = "authorized"
    return result


# A wrapped source descriptor is not always wrapped exactly once -- a
# caller composing its own generic envelope conventions may nest one
# eligible container inside *another*, to any depth, under any name at
# all, e.g. `{"envelope": {"record": {...real fields...}}}`. The single
# top-level container choice `_normalize_source_action_entries` below
# makes (unchanged, including every one of its own existing ambiguity
# rules) only ever peels off *one* layer; `_unwrap_nested_source_
# descriptor` is applied to whatever that first choice already produced
# (the nested value pulled from a container key, or one item out of a
# list) so any *further* nesting underneath it is resolved identically,
# all the way down, before connector/origin inference or field-alias
# normalization ever sees the descriptor.
_MAX_SOURCE_WRAPPER_DEPTH = 12


def _merge_source_descriptor_siblings(
    base: dict[str, Any], siblings: dict[str, Any], action: str, index: int, wrapper_key: str,
) -> dict[str, Any]:
    """Merges `siblings` (a nested level's own remaining fields, control
    keys already excluded by the caller) onto `base` (an already fully
    resolved descriptor) -- a sibling field whose value conflicts with
    `base`'s own value for the *same* field name is a clean
    `VALIDATION_ERROR`, never a silent pick; identical values (or a
    field present on only one side) merge safely. A no-op when `siblings`
    is empty."""
    if not siblings:
        return base
    merged = dict(base)
    for key, sib_value in siblings.items():
        if key in merged and merged[key] != sib_value:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action '{action}' at element {index} gives conflicting values for '{key}' between a "
                f"'{wrapper_key}' container and a sibling field (ambiguous: which should win?)",
                {"index": index, "action": action, "field": key},
            )
        merged[key] = sib_value
    return merged


def _select_source_descriptor_container(
    container_keys: list[str], value: dict[str, Any], action: str, index: int, depth: int,
) -> str:
    """Chooses which of two-or-more eligible container keys found at the
    same nesting level is the real source descriptor. A single candidate
    is returned immediately, unscored (nothing to disambiguate). For
    2+ candidates, each is fully resolved and scored
    (`_meets_source_identity_bar`); a candidate whose own resolution
    itself raises (e.g. a deeper, genuinely ambiguous nested conflict) is
    simply never a viable pick, exactly like one that resolves cleanly
    but carries no usable identity -- never let one broken/incidental
    sibling container abort a resolution some *other*, perfectly good
    sibling container would have produced. Exactly one candidate meeting
    the sufficiency bar is used silently (the others are incidental,
    insufficient noise, never a real competing descriptor); two or more
    meeting the bar is an explicit `VALIDATION_ERROR` (ambiguous: which
    should win?); none meeting the bar is equally an explicit
    `VALIDATION_ERROR` (this level's own container(s) carry no usable
    source identity at all) -- a clear validation message either way,
    never a silent, arbitrary choice."""
    if len(container_keys) == 1:
        return container_keys[0]

    def _try_resolve(key: str) -> Optional[list[dict[str, Any]]]:
        try:
            resolved = _unwrap_nested_source_descriptor(value[key], action, index, depth=depth + 1)
        except EngineError:
            return None
        candidates = resolved if isinstance(resolved, list) else [resolved]
        if not all(isinstance(c, dict) and c for c in candidates):
            return None
        return candidates

    resolved_by_key = {key: _try_resolve(key) for key in container_keys}
    sufficient_keys = [
        key for key, candidates in resolved_by_key.items()
        if candidates is not None and any(_meets_source_identity_bar(c) for c in candidates)
    ]
    if len(sufficient_keys) == 1:
        return sufficient_keys[0]
    if not sufficient_keys:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} nests {len(container_keys)} candidate source "
            f"descriptor container(s) ({sorted(container_keys)}), but none carries sufficient source "
            "identity (a locator, or inline content plus a filename/type/title hint)",
            {"index": index, "action": action, "field": "sources", "wrapperFields": sorted(container_keys)},
        )
    raise EngineError(
        "VALIDATION_ERROR",
        f"action '{action}' at element {index} nests {len(sufficient_keys)} equally plausible source "
        f"descriptor containers ({sorted(sufficient_keys)}) at the same level (ambiguous: which "
        "should win?)",
        {"index": index, "action": action, "field": "sources", "wrapperFields": sorted(sufficient_keys)},
    )


def _unwrap_nested_source_descriptor(value: Any, action: str, index: int, *, depth: int = 0) -> Any:
    """Recursively peels through any nesting of source-descriptor
    *containers* -- any key name at all, discovered structurally
    (`_is_source_descriptor_container`), never by matching a fixed,
    guessed allowlist of wrapper spellings -- plus a list of one or more
    such dicts under any such key (every item independently contributes
    one descriptor, in order). A non-dict value, an empty dict, or a dict
    naming no eligible container (already a terminal descriptor, or a
    plain field value) is returned completely unchanged -- this function
    is always a safe no-op once nesting bottoms out (see
    `_check_empty_source_descriptor_candidate` for the one exception: an
    otherwise-empty, clearly-intended container is still a clean
    refusal, never silently ignored). Control keys (`action`, and this
    action-list's own actor/approver/gate/export field names -- see
    `_SOURCE_DESCRIPTOR_CONTROL_KEYS`) are never treated as descriptor
    content and never copied into the resolved descriptor, at any depth.

    A container key at a *nested* level (never the outermost action-entry
    level, which keeps its own pre-existing strict single-shape rule; see
    `_normalize_source_action_entries` below) may coexist with genuine
    sibling metadata fields: the container's own recursively-resolved
    content and the sibling fields are merged into one flat descriptor
    (or, when the container resolves to a *list*, merged into every one
    of its items uniformly -- shared ancestor metadata applies to each
    contributed descriptor alike). A sibling field whose value conflicts
    with the container's own resolved value for the *same* field name is
    a clean `VALIDATION_ERROR`, never a silent pick.

    More than one eligible container key at the same nesting level is
    resolved via `_select_source_descriptor_container` (scored, silent
    pick only when unambiguous; a clear `VALIDATION_ERROR` otherwise)."""
    if not isinstance(value, dict) or not value:
        return value
    if depth > _MAX_SOURCE_WRAPPER_DEPTH:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} nests source descriptor containers too deeply",
            {"index": index, "action": action},
        )

    container_keys = [k for k in value if _is_source_descriptor_container(k, value[k])]
    if not container_keys:
        _check_empty_source_descriptor_candidate(value, action, index)
        _check_signal_free_source_descriptor_candidate(value, action, index)
        return value

    wrapper_key = _select_source_descriptor_container(container_keys, value, action, index, depth)
    nested_value = value[wrapper_key]
    siblings = {
        k: v for k, v in value.items()
        if k != wrapper_key and _normalize_descriptor_key(k) not in _SOURCE_DESCRIPTOR_CONTROL_KEYS
    }

    if isinstance(nested_value, list):
        resolved_items = []
        for item in nested_value:
            resolved_item = _unwrap_nested_source_descriptor(item, action, index, depth=depth + 1)
            if not isinstance(resolved_item, dict) or not resolved_item:
                raise EngineError(
                    "VALIDATION_ERROR",
                    f"action '{action}' at element {index} has a '{wrapper_key}' list entry that did "
                    "not resolve to a non-empty source descriptor object",
                    {"index": index, "action": action, "field": "sources", "wrapperField": wrapper_key},
                )
            resolved_items.append(_merge_source_descriptor_siblings(resolved_item, siblings, action, index, wrapper_key))
        return resolved_items

    unwrapped = _unwrap_nested_source_descriptor(nested_value, action, index, depth=depth + 1)
    if isinstance(unwrapped, list):
        return [_merge_source_descriptor_siblings(item, siblings, action, index, wrapper_key) for item in unwrapped]
    if not siblings:
        return unwrapped
    if not isinstance(unwrapped, dict):
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} has sibling field(s) {sorted(siblings)} alongside "
            f"a '{wrapper_key}' container that did not itself resolve to an object",
            {"index": index, "action": action, "field": "sources"},
        )
    return _merge_source_descriptor_siblings(unwrapped, siblings, action, index, wrapper_key)


def _normalize_source_action_entries(payload: dict[str, Any], action: str, index: int) -> list[dict[str, Any]]:
    """Normalizes one `ingest_source`/`add_source` action-list element's
    inline payload into the list of plain `FetchResult`-shaped dict(s) it
    contributes to the object-form `sources` list -- almost always
    exactly one item, feeding the existing `sources` model exactly once
    per contributed descriptor.

    `"sources"` (documented, unchanged) remains its own explicit, narrow
    special case -- the one literal, public wire field
    (`docs/engine-cli-reference.md`) naming a list of descriptors
    directly -- so its pre-existing non-empty-list/no-mixing contract is
    preserved exactly, alongside (never instead of) the fully general
    structural mechanism below for every other shape/name: a nested
    `"sources"` list (under some *other* container) is still just another
    eligible container, resolved the identical structural way.

    Absent a `"sources"` field, the payload's own eligible container
    key(s) are found structurally (`_is_source_descriptor_container`) --
    never by matching a fixed, guessed wrapper-name allowlist:

      - zero eligible containers: direct fields (documented, unchanged)
        -- the payload's own keys *are* the `FetchResult` fields, e.g.
        `{"uri": ..., "origin": ...}` -- the entire payload becomes the
        one contributed item (still passed through
        `_unwrap_nested_source_descriptor` so a directly-given field that
        itself nests a further eligible container -- vanishingly rare,
        since a real field's own value is never dict-shaped -- is still
        resolved).
      - exactly one eligible container key, and every other payload field
        is itself an eligible container too (i.e. no *other*, non-
        container sibling field at all): that container (and only it)
        becomes the contributed item(s) -- a container resolving to a
        list contributes one item per entry, in order.
      - 2+ eligible container keys, still with no other sibling field:
        resolved via `_select_source_descriptor_container` (scored;
        silent pick only when unambiguous).

    A container key alongside *any* other (non-container) sibling field
    at this outermost level -- e.g. a wrapper key alongside a sibling
    direct field -- is always a clean `VALIDATION_ERROR`, never a guess
    as to which should win; nesting *underneath* a chosen container
    additionally allows safe sibling-metadata merging (see
    `_unwrap_nested_source_descriptor`'s own docstring)."""
    if "sources" in payload:
        extra = sorted(k for k in payload if k != "sources")
        if extra:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action '{action}' at element {index} mixes the 'sources' list wrapper with other "
                "inline payload field(s) (ambiguous: which should win?)",
                {"index": index, "action": action, "field": "sources"},
            )
        items = payload["sources"]
        if not isinstance(items, list) or not items:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action '{action}' at element {index} has a 'sources' field that must be a "
                "non-empty list of source descriptor objects",
                {"index": index, "action": action, "field": "sources"},
            )
        normalized = []
        for item in items:
            if not isinstance(item, dict) or not item:
                raise EngineError(
                    "VALIDATION_ERROR",
                    f"action '{action}' at element {index} has a 'sources' list entry that is not "
                    f"a non-empty object ({item!r})",
                    {"index": index, "action": action, "field": "sources"},
                )
            normalized.append(_normalize_source_field_aliases(_unwrap_nested_source_descriptor(item, action, index)))
        return normalized

    container_keys = [k for k in payload if _is_source_descriptor_container(k, payload[k])]
    non_container_keys = [k for k in payload if k not in container_keys]

    if container_keys and non_container_keys:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} mixes source descriptor container field(s) "
            f"{sorted(container_keys)} with other inline payload field(s) {sorted(non_container_keys)} "
            "(ambiguous: which should win?)",
            {"index": index, "action": action, "field": "sources", "wrapperFields": sorted(container_keys)},
        )

    if not container_keys:
        if not payload:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action '{action}' at element {index} has no inline payload fields",
                {"index": index, "action": action, "field": "sources"},
            )
        resolved = _unwrap_nested_source_descriptor(payload, action, index)
        items = resolved if isinstance(resolved, list) else [resolved]
        return [_normalize_source_field_aliases(item) for item in items]

    wrapper_key = _select_source_descriptor_container(container_keys, payload, action, index, depth=0)
    resolved = _unwrap_nested_source_descriptor(payload[wrapper_key], action, index, depth=1)
    items = resolved if isinstance(resolved, list) else [resolved]
    for item in items:
        if not isinstance(item, dict) or not item:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action '{action}' at element {index} has a '{wrapper_key}' field that must resolve "
                "to a non-empty source descriptor object",
                {"index": index, "action": action, "field": "sources", "wrapperField": wrapper_key},
            )
    return [_normalize_source_field_aliases(item) for item in items]


_RAW_SOURCE_DESCRIPTOR_REDACT_KEYS = frozenset({"content", "content_base64", "text", "body", "transcript"})


def _redact_raw_source_descriptor(node: Any) -> Any:
    """Returns a deep copy of `node` (the original, un-normalized public
    payload an `add_source`/`ingest_source` action-list element supplied
    -- see `report["steps"]`'s `source.ingest` `rawDescriptor` field and
    `report["actionResults"]`'s `rawPayload` field) with every inline-
    content-shaped leaf value (`content`/`contentBase64`/`text`/`body`/
    `transcript`, at any depth, under any wrapper) replaced by a short,
    non-sensitive placeholder -- preserving every wrapper/field *name*
    (so the structural normalization this action performed stays fully
    auditable) without duplicating potentially large or sensitive pasted
    content into the run report."""
    if isinstance(node, dict):
        return {
            k: (f"<redacted: {len(v)} chars>" if _normalize_descriptor_key(k) in _RAW_SOURCE_DESCRIPTOR_REDACT_KEYS
                and isinstance(v, str) else _redact_raw_source_descriptor(v))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_redact_raw_source_descriptor(item) for item in node]
    return node


# `set_rehearsal_timing`/`rehearse`'s inline payload accepts one of five
# slide-reference field names (mirroring `_match_slide`'s own pre-existing
# slideId/slideOrder/slideRole precedence, used elsewhere for
# accessibility/demo-asset matching, plus the `slide_id`/`slide_order`
# snake_case aliases) paired with one of six duration field names -- see
# `_apply_rehearsal_timing_entry` below. `actualMinutes`/`actual_minutes`
# is the one minutes-denominated value alias (converted `* 60`); every
# other value alias is already seconds-denominated.
_REHEARSAL_TIMING_KEY_FIELDS = ("slideRole", "slideId", "slide_id", "slideOrder", "slide_order")
_REHEARSAL_TIMING_VALUE_FIELDS_SECONDS = (
    "seconds", "duration", "durationSeconds", "duration_seconds", "actualSeconds", "actual_seconds",
)
_REHEARSAL_TIMING_VALUE_FIELDS_MINUTES = ("actualMinutes", "actual_minutes")
_REHEARSAL_TIMING_VALUE_FIELDS = _REHEARSAL_TIMING_VALUE_FIELDS_SECONDS + _REHEARSAL_TIMING_VALUE_FIELDS_MINUTES
_REHEARSAL_TIMING_ALLOWED_FIELDS = frozenset(_REHEARSAL_TIMING_KEY_FIELDS) | frozenset(_REHEARSAL_TIMING_VALUE_FIELDS)


def _validate_rehearsal_duration(
    raw: Any, *, field_name: str, action: str, index: int, allow_zero: bool = True,
) -> float:
    """Shared numeric guard for every rehearsal-duration-shaped value this
    module accepts (a per-slide/bulk timing, an aggregate total, or a
    cuts target) -- rejects a non-numeric value (including `bool`, which
    is otherwise a silently-coercible Python `int` subclass), a
    non-finite one (`NaN`/`inf`), and a negative one explicitly, always as
    a clean `VALIDATION_ERROR` naming the offending field, never a guess
    or a raw `TypeError`. `allow_zero=False` additionally rejects exactly
    zero (used for a cuts target, where "cut down to nothing" is not a
    meaningful request)."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} has a non-numeric '{field_name}' ({raw!r})",
            {"index": index, "action": action, "field": field_name, "value": raw},
        )
    if not math.isfinite(raw):
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} has an impossible '{field_name}' ({raw!r})",
            {"index": index, "action": action, "field": field_name, "value": raw},
        )
    if raw < 0 or (raw == 0 and not allow_zero):
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} has a negative or impossible '{field_name}' ({raw!r})",
            {"index": index, "action": action, "field": field_name, "value": raw},
        )
    return float(raw)


def _apply_rehearsal_timing_entry(merged: dict[str, Any], payload: dict[str, Any], action: str, index: int) -> None:
    """Special-cased `set_rehearsal_timing`/`rehearse` handling -- unlike
    the generic "mapping" shape's one fixed key_field/value_field pair,
    this action accepts any *one* of `_REHEARSAL_TIMING_KEY_FIELDS`
    (`slideRole`, the original/documented one, or the new `slideId`/
    `slideOrder` aliases) paired with any *one* of
    `_REHEARSAL_TIMING_VALUE_FIELDS` (`seconds`, the original/documented
    one, or the new `duration`/`durationSeconds`/`actualSeconds` aliases
    -- `actualSeconds` mirrors `rehearse run`'s own direct CLI timings-
    document field name verbatim). The resolved entry is stored into the
    identical `rehearsalTimings` dict every other shape already produces,
    keyed by whichever raw reference value (a role string, a slide id
    string, or an integer order) the caller gave -- resolved against the
    real slides once they exist, exactly like a bare `slideRole` key
    already is (`scenario._resolve_rehearsal_slide`). An unexpected extra
    field, zero or more than one recognized key-field, zero or more than
    one recognized value-field, or a repeated resolved key across
    elements is always a clean `VALIDATION_ERROR`, never a guess -- the
    exact same validation `set_rehearsal_timing`'s pre-existing
    `slideRole`/`seconds` shape already enforced, only widened."""
    extra = sorted(set(payload) - _REHEARSAL_TIMING_ALLOWED_FIELDS)
    if extra:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} has unexpected inline payload field(s) {extra}; "
            f"expected one of {_REHEARSAL_TIMING_KEY_FIELDS} paired with one of "
            f"{_REHEARSAL_TIMING_VALUE_FIELDS}",
            {"index": index, "action": action, "field": "rehearsalTimings", "unexpectedFields": extra},
        )
    key_fields_present = [k for k in _REHEARSAL_TIMING_KEY_FIELDS if k in payload]
    value_fields_present = [k for k in _REHEARSAL_TIMING_VALUE_FIELDS if k in payload]
    if len(key_fields_present) != 1 or len(value_fields_present) != 1:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} requires exactly one of "
            f"{_REHEARSAL_TIMING_KEY_FIELDS} and exactly one of {_REHEARSAL_TIMING_VALUE_FIELDS} inline "
            "payload fields",
            {
                "index": index, "action": action, "field": "rehearsalTimings",
                "keyFieldsGiven": key_fields_present, "valueFieldsGiven": value_fields_present,
            },
        )
    if "rehearsalTotalActualSeconds" in merged:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} gives a per-slide rehearsal timing, but an "
            "aggregate total rehearsal duration was already given elsewhere in this document "
            "(ambiguous: which should win?)",
            {"index": index, "action": action, "field": "rehearsalTimings"},
        )
    (key_field,), (value_field,) = key_fields_present, value_fields_present
    key_value = payload[key_field]
    seconds = _validate_rehearsal_duration(payload[value_field], field_name=value_field, action=action, index=index)
    if value_field in _REHEARSAL_TIMING_VALUE_FIELDS_MINUTES:
        seconds *= 60
    bucket = merged.setdefault("rehearsalTimings", {})
    if key_value in bucket:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} repeats key '{key_value}' (ambiguous: which value "
            "should win?)",
            {"index": index, "action": action, "field": "rehearsalTimings", "key": key_value},
        )
    bucket[key_value] = seconds


# --- `rehearse`'s widened rehearsal-subfeature vocabulary ------------------
#
# `rehearse` began as a pure synonym for `set_rehearsal_timing` (the exact
# narrow per-slide shape above) -- but it is the *only* action-list verb
# naming ARCH's entire "Rehearse" command group (`rehearse run`/
# `record-qa`/`propose-cuts`, FR-DEL-1/2/3, FR-M365-4) for a black-box
# caller with no reason to know the finer-grained `record_qa` verb exists,
# or that per-slide timing and an aggregate rehearsal total are different
# shapes. `set_rehearsal_timing` itself is completely unaffected by any of
# this -- it still only ever accepts the one narrow shape above, handled
# by `_apply_rehearsal_timing_entry`.
#
# `rehearse`'s own inline payload is classified, once, into exactly one of
# six mutually exclusive sub-shapes (never a guess between them; mixing
# fields from two different sub-shapes on the same element, or an
# unrecognized field set, is always a clean `VALIDATION_ERROR`):
#
#   1. a single per-slide timing -- identical to `set_rehearsal_timing`'s
#      own shape, reusing `_apply_rehearsal_timing_entry` verbatim;
#   2. a bulk timings wrapper -- exactly one of `timings`/`slideTimings`/
#      `rehearsal`/`run`/`value`, holding either a `{slideRef: seconds}`
#      mapping (the exact `rehearse run --input timings.json` document
#      shape) or a list of single-entry-shaped objects -- see
#      `_apply_rehearsal_bulk_entry`;
#   3. an aggregate whole-rehearsal actual-duration alias (`totalSeconds`/
#      `totalActualSeconds`/`actualDurationSeconds`, or a `Minutes`-suffixed
#      variant of any of those, converted `* 60`) -- no per-slide
#      breakdown at all, allocated proportionally to each slide's own
#      configured time budget (`rehearsal.distribute_total_duration`, once
#      real slides exist in `_run_steps`) and then fed into the identical
#      per-slide `run_rehearsal` contract every other shape already
#      produces -- see `_apply_rehearsal_total_entry`;
#   4. a Q&A pair (a `question` field, optionally `answer`/`claimIndices`)
#      or a `qaPairs` wrapper list of such objects -- contributed into the
#      identical `qaPairs` list `record_qa` already targets -- see
#      `_apply_rehearse_qa_entry`;
#   5. a shorter-variant/cut request -- exactly one of `targetSeconds`/
#      `targetMinutes` (optionally alongside a redundant boolean marker,
#      `requestCuts`/`shorterVariant`/`proposeCuts`, which if given must be
#      truthy) -- feeds `compiler.propose_cuts`'s existing `target_seconds`
#      contract -- see `_apply_rehearse_cuts_entry`;
#   6. a bare re-check -- no fields at all, or exactly the boolean marker
#      `reportSourceChanges`/`checkSourceChanges` -- requests a fresh
#      `rehearsal.run_rehearsal` pass (with an empty timings dict, exactly
#      as a `rehearse run` whose document matches no slide already
#      produces) purely so FR-M365-4's `sourceChanges` change-detection
#      against the workspace's own last-rehearsal snapshot is still
#      reported even when no new timing is supplied at all -- "do not
#      require timing when the action only requests a supported
#      rehearsal subfeature."
#
# Every duration value (per-slide, bulk, aggregate, or a cuts target) is
# validated identically (`_validate_rehearsal_duration` above): must be a
# real, finite, non-negative number -- "impossible" timings (a negative,
# `NaN`/`inf`, or non-numeric value) are refused up front, never handed to
# the domain layer.
_REHEARSAL_BULK_WRAPPER_KEYS = ("timings", "slideTimings", "slide_timings", "rehearsal", "run", "value")
_REHEARSAL_TOTAL_FIELDS_SECONDS = (
    "totalSeconds", "total_seconds", "totalActualSeconds", "total_actual_seconds",
    "actualDurationSeconds", "actual_duration_seconds",
)
_REHEARSAL_TOTAL_FIELDS_MINUTES = (
    "totalMinutes", "total_minutes", "totalActualMinutes", "total_actual_minutes",
    "actualDurationMinutes", "actual_duration_minutes",
)
_REHEARSAL_TOTAL_ALLOWED_FIELDS = frozenset(_REHEARSAL_TOTAL_FIELDS_SECONDS) | frozenset(_REHEARSAL_TOTAL_FIELDS_MINUTES)
# `target_seconds`/`target_minutes`: the snake_case aliases closing the
# known `rehearse` adapter mismatch (Dark Factory hardening cycle 7) --
# a `rehearse` cuts request using snake_case `target_minutes` was
# previously rejected with `VALIDATION_ERROR` while `targetMinutes` was
# accepted; both casings now drive the identical
# `compiler.propose_cuts` contract.
_REHEARSAL_CUTS_FIELDS_SECONDS = ("targetSeconds", "target_seconds")
_REHEARSAL_CUTS_FIELDS_MINUTES = ("targetMinutes", "target_minutes")
_REHEARSAL_CUTS_TARGET_FIELDS = frozenset(_REHEARSAL_CUTS_FIELDS_SECONDS) | frozenset(_REHEARSAL_CUTS_FIELDS_MINUTES)
_REHEARSAL_CUTS_MARKER_FIELDS = (
    "requestCuts", "request_cuts", "shorterVariant", "shorter_variant", "proposeCuts", "propose_cuts",
)
_REHEARSAL_CUTS_ALLOWED_FIELDS = _REHEARSAL_CUTS_TARGET_FIELDS | frozenset(_REHEARSAL_CUTS_MARKER_FIELDS)
_REHEARSAL_SOURCE_CHECK_MARKER_FIELDS = frozenset({
    "reportSourceChanges", "report_source_changes", "checkSourceChanges", "check_source_changes",
})
_REHEARSAL_QA_SINGLE_FIELDS = frozenset({"question", "answer", "claimIndices", "claim_indices"})


def _apply_rehearsal_bulk_entry(merged: dict[str, Any], payload: dict[str, Any], index: int) -> None:
    """Family 2 above: exactly one of `_REHEARSAL_BULK_WRAPPER_KEYS`, with
    no sibling fields, holding either a `{slideRef: seconds}` mapping or a
    non-empty list of single-entry-shaped objects (each run back through
    `_apply_rehearsal_timing_entry`, so every alias/ambiguity/repeated-key
    rule above applies identically per item)."""
    action = "rehearse"
    present = [k for k in _REHEARSAL_BULK_WRAPPER_KEYS if k in payload]
    if len(present) != 1 or len(payload) != 1:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'rehearse' at element {index} must use exactly one bulk-timings wrapper field "
            f"{_REHEARSAL_BULK_WRAPPER_KEYS} with no sibling fields",
            {"index": index, "action": action, "field": "rehearsalTimings", "payloadFields": sorted(payload)},
        )
    (wrapper_key,) = present
    value = payload[wrapper_key]
    if isinstance(value, dict):
        if not value:
            raise EngineError(
                "VALIDATION_ERROR", f"action 'rehearse' at element {index} has an empty '{wrapper_key}' mapping",
                {"index": index, "action": action, "field": wrapper_key},
            )
        if "rehearsalTotalActualSeconds" in merged:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'rehearse' at element {index} gives per-slide timings via '{wrapper_key}', but an "
                "aggregate total rehearsal duration was already given elsewhere in this document (ambiguous)",
                {"index": index, "action": action, "field": wrapper_key},
            )
        bucket = merged.setdefault("rehearsalTimings", {})
        for key_value, raw_seconds in value.items():
            seconds = _validate_rehearsal_duration(raw_seconds, field_name=wrapper_key, action=action, index=index)
            if key_value in bucket:
                raise EngineError(
                    "VALIDATION_ERROR",
                    f"action 'rehearse' at element {index} repeats key '{key_value}' via '{wrapper_key}' "
                    "(ambiguous: which value should win?)",
                    {"index": index, "action": action, "field": "rehearsalTimings", "key": key_value},
                )
            bucket[key_value] = seconds
        return
    if isinstance(value, list):
        if not value:
            raise EngineError(
                "VALIDATION_ERROR", f"action 'rehearse' at element {index} has an empty '{wrapper_key}' list",
                {"index": index, "action": action, "field": wrapper_key},
            )
        for item in value:
            if not isinstance(item, dict) or not item:
                raise EngineError(
                    "VALIDATION_ERROR",
                    f"action 'rehearse' at element {index} has a '{wrapper_key}' list entry that is not a "
                    f"non-empty object ({item!r})",
                    {"index": index, "action": action, "field": wrapper_key},
                )
            _apply_rehearsal_timing_entry(merged, item, "rehearse", index)
        return
    raise EngineError(
        "VALIDATION_ERROR",
        f"action 'rehearse' at element {index} has a '{wrapper_key}' field that must be a mapping or a "
        f"non-empty list of timing entries (got {value!r})",
        {"index": index, "action": action, "field": wrapper_key},
    )


def _apply_rehearsal_total_entry(merged: dict[str, Any], payload: dict[str, Any], index: int) -> None:
    """Family 3 above: exactly one aggregate whole-rehearsal actual-
    duration field (a `Seconds`- or `Minutes`-suffixed alias -- the latter
    converted `* 60`), with no sibling fields, and never combined (in this
    or any other element) with a per-slide `rehearsalTimings` entry."""
    action = "rehearse"
    extra = sorted(set(payload) - _REHEARSAL_TOTAL_ALLOWED_FIELDS)
    present = [k for k in _REHEARSAL_TOTAL_ALLOWED_FIELDS if k in payload]
    if len(present) != 1 or extra:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'rehearse' at element {index} requires exactly one aggregate-duration field "
            f"(one of {sorted(_REHEARSAL_TOTAL_ALLOWED_FIELDS)}); unexpected field(s) {extra}",
            {"index": index, "action": action, "unexpectedFields": extra},
        )
    if "rehearsalTotalActualSeconds" in merged:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'rehearse' at element {index} repeats the aggregate total rehearsal duration "
            "(ambiguous: which value should win?)",
            {"index": index, "action": action},
        )
    if "rehearsalTimings" in merged:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'rehearse' at element {index} gives an aggregate total rehearsal duration, but a "
            "per-slide rehearsal timing was already given elsewhere in this document (ambiguous)",
            {"index": index, "action": action},
        )
    (field_name,) = present
    seconds = _validate_rehearsal_duration(payload[field_name], field_name=field_name, action=action, index=index)
    if field_name in _REHEARSAL_TOTAL_FIELDS_MINUTES:
        seconds *= 60
    merged["rehearsalTotalActualSeconds"] = seconds


def _apply_rehearse_qa_entry(merged: dict[str, Any], payload: dict[str, Any], index: int) -> None:
    """Family 4 above: a single `question`(+`answer`/`claimIndices`/
    `claim_indices`) pair, or a `qaPairs`/`qa_pairs` wrapper list of such
    objects -- both contribute into the identical `qaPairs` list the
    dedicated `record_qa` action already targets (`_run_steps` reads
    `doc["qaPairs"]` regardless of which verb populated it)."""
    action = "rehearse"
    wrapper_keys_present = [k for k in ("qaPairs", "qa_pairs") if k in payload]
    if wrapper_keys_present:
        extra = sorted(set(payload) - set(wrapper_keys_present))
        if extra or len(wrapper_keys_present) > 1:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'rehearse' at element {index} mixes a 'qaPairs'/'qa_pairs' wrapper with "
                f"sibling field(s) {extra} (ambiguous)",
                {"index": index, "action": action, "unexpectedFields": extra},
            )
        items = payload[wrapper_keys_present[0]]
        if not isinstance(items, list) or not items:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'rehearse' at element {index} has a 'qaPairs' field that must be a non-empty list",
                {"index": index, "action": action},
            )
    else:
        items = [payload]

    for item in items:
        if not isinstance(item, dict) or not str(item.get("question", "")).strip():
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'rehearse' at element {index} has a Q&A entry missing a non-empty 'question' "
                f"({item!r})",
                {"index": index, "action": action},
            )
        extra_item = sorted(set(item) - _REHEARSAL_QA_SINGLE_FIELDS)
        if extra_item:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'rehearse' at element {index} has a Q&A entry with unexpected field(s) {extra_item}",
                {"index": index, "action": action, "unexpectedFields": extra_item},
            )
        merged.setdefault("qaPairs", []).append(dict(item))


def _apply_rehearse_cuts_entry(merged: dict[str, Any], payload: dict[str, Any], index: int) -> None:
    """Family 5 above: exactly one of `targetSeconds`/`targetMinutes`
    (the latter converted `* 60`), optionally alongside a redundant
    boolean marker (`requestCuts`/`shorterVariant`/`proposeCuts`) that, if
    given, must be truthy -- feeds `compiler.propose_cuts`'s existing
    `target_seconds` contract (`_run_steps` below)."""
    action = "rehearse"
    extra = sorted(set(payload) - _REHEARSAL_CUTS_ALLOWED_FIELDS)
    present = [k for k in _REHEARSAL_CUTS_TARGET_FIELDS if k in payload]
    if len(present) != 1 or extra:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'rehearse' at element {index} requires exactly one cuts-target field "
            f"(one of {sorted(_REHEARSAL_CUTS_TARGET_FIELDS)}); unexpected field(s) {extra}",
            {"index": index, "action": action, "unexpectedFields": extra},
        )
    for marker in _REHEARSAL_CUTS_MARKER_FIELDS:
        if marker in payload and not payload[marker]:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'rehearse' at element {index} has '{marker}' set to a falsy value -- omit it "
                "instead of disabling a cuts request",
                {"index": index, "action": action, "field": marker},
            )
    if "rehearsalCutsTargetSeconds" in merged:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'rehearse' at element {index} repeats the cuts target duration (ambiguous: which "
            "value should win?)",
            {"index": index, "action": action},
        )
    (field_name,) = present
    seconds = _validate_rehearsal_duration(
        payload[field_name], field_name=field_name, action=action, index=index, allow_zero=False,
    )
    if field_name in _REHEARSAL_CUTS_FIELDS_MINUTES:
        seconds *= 60
    merged["rehearsalCutsTargetSeconds"] = seconds


def _apply_rehearse_entry(merged: dict[str, Any], payload: dict[str, Any], index: int) -> None:
    """Dispatches one `rehearse` action-list element to whichever of the
    six sub-shapes (see the module comment above) its inline payload
    matches -- exactly one, or a clean `VALIDATION_ERROR` naming the
    accepted vocabulary, never a guess."""
    if not payload:
        merged["rehearsalRunRequested"] = True
        return

    keys = set(payload)
    is_single = bool(keys & set(_REHEARSAL_TIMING_KEY_FIELDS))
    is_bulk = bool(keys & set(_REHEARSAL_BULK_WRAPPER_KEYS))
    is_total = bool(keys & _REHEARSAL_TOTAL_ALLOWED_FIELDS)
    is_qa = "question" in keys or "qaPairs" in keys or "qa_pairs" in keys
    is_cuts = bool(keys & _REHEARSAL_CUTS_TARGET_FIELDS)
    is_source_check_only = bool(keys) and keys <= _REHEARSAL_SOURCE_CHECK_MARKER_FIELDS

    family_count = sum([is_single, is_bulk, is_total, is_qa, is_cuts, is_source_check_only])
    if family_count > 1:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'rehearse' at element {index} mixes fields from more than one rehearsal "
            f"sub-feature shape ({sorted(keys)}) -- a per-slide timing, a bulk timings wrapper, an "
            "aggregate total duration, a Q&A pair, a cuts target, and a bare source-change check are "
            "mutually exclusive within one element",
            {"index": index, "action": "rehearse", "payloadFields": sorted(keys)},
        )
    if family_count == 0:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action 'rehearse' at element {index} has unrecognized inline payload field(s) "
            f"{sorted(keys)}; expected a per-slide timing, a bulk timings wrapper "
            f"{_REHEARSAL_BULK_WRAPPER_KEYS}, an aggregate total duration, a Q&A pair, a cuts target, "
            f"or {sorted(_REHEARSAL_SOURCE_CHECK_MARKER_FIELDS)}",
            {"index": index, "action": "rehearse", "payloadFields": sorted(keys)},
        )

    if is_single:
        _apply_rehearsal_timing_entry(merged, payload, "rehearse", index)
    elif is_bulk:
        _apply_rehearsal_bulk_entry(merged, payload, index)
    elif is_total:
        _apply_rehearsal_total_entry(merged, payload, index)
    elif is_qa:
        _apply_rehearse_qa_entry(merged, payload, index)
    elif is_cuts:
        _apply_rehearse_cuts_entry(merged, payload, index)
    else:
        for marker in keys:
            if not payload[marker]:
                raise EngineError(
                    "VALIDATION_ERROR",
                    f"action 'rehearse' at element {index} has '{marker}' set to a falsy value -- omit "
                    "it instead of a bare source-change re-check",
                    {"index": index, "action": "rehearse", "field": marker},
                )
        merged["rehearsalRunRequested"] = True


def _apply_compile_requested_entry(merged: dict[str, Any], payload: dict[str, Any], action: str, index: int) -> None:
    """`compile_deck`/`compile_presentation` never carry inline payload
    fields -- deck compilation already runs automatically and
    unconditionally later in `_run_steps` regardless of this action's
    presence or absence, so there is nothing for either verb's payload to
    configure. Any inline field at all is a clean `VALIDATION_ERROR`,
    never silently ignored."""
    if payload:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} does not accept any inline payload field(s) "
            f"(got {sorted(payload)}); deck compilation already runs automatically once a route is "
            "selected -- this action only exists so an action-list caller may name that step "
            "explicitly",
            {"index": index, "action": action, "unexpectedFields": sorted(payload)},
        )
    merged["compileRequested"] = True


# Common action payload wrappers (Dark Factory hardening cycle 7): a
# public caller may wrap an action's entire inline payload in one of
# these reserved container keys instead of giving its fields directly on
# the action-list element itself -- unambiguous only for the two "whole
# payload is the item" shapes (`_ACTION_LIST_OBJECT_FIELDS`/
# `_ACTION_OBJECT_FIELDS`, e.g. `propose_claim`/`set_talk_brief`), where
# there is no pre-existing, narrower meaning for any of these key names to
# collide with. `sources`/`rehearsalTimings`/the scalar fields/the
# select_throughline/select_narrative_route/rehearse verbs already define
# their own, more specific wrapper/alias vocabulary (`source`/
# `descriptor`/`value` for a source descriptor, `value` for a scalar,
# `timings`/`rehearsal`/`run`/`value` for a bulk rehearsal shape, ...) and
# are dispatched to their own handling above this point -- this generic
# unwrap only ever applies to the two shapes below, never overriding a
# more specific, already-tested contract.
_GENERIC_ACTION_WRAPPER_KEYS = ("params", "payload", "input", "source", "descriptor", "value")


def _unwrap_generic_action_wrapper(payload: dict[str, Any]) -> dict[str, Any]:
    """If `payload` consists of exactly one key from
    `_GENERIC_ACTION_WRAPPER_KEYS` whose value is itself an object
    (including an empty one -- unwrapped to `{}` so the field's own
    "no inline payload fields" validation still reports it plainly,
    rather than a wrapper key becoming a bogus field name), returns that
    nested object (the action's real fields) instead -- otherwise returns
    `payload` completely unchanged. Never partially unwraps (a wrapper
    key alongside any sibling field is left alone here, so the field's
    own "no inline payload fields"/unexpected-field validation below
    still reports it plainly)."""
    if len(payload) == 1:
        ((only_key, only_value),) = payload.items()
        if only_key in _GENERIC_ACTION_WRAPPER_KEYS and isinstance(only_value, dict):
            return dict(only_value)
    return payload


def _apply_action_list_entry(
    merged: dict[str, Any], entry: dict[str, Any], index: int,
    add_source_scope: Optional[set[int]] = None,
) -> None:
    """Applies one action-tagged list element (`entry` has an `"action"`
    key) onto `merged`, the in-progress object-form dict — see the
    module-level comment above for the accepted vocabulary and shapes.
    Raises `VALIDATION_ERROR` for an unknown/unaliased action name or a
    payload that doesn't match its action's required shape; never guesses
    at intent.

    `add_source_scope` (Dark Factory hardening cycle 13, optional --
    every existing caller that never passes it behaves identically to
    before) is a caller-owned identity set: when given, every normalized
    item this element's own `add_source`/`ingest_source` "sources"
    contribution produces has its `id()` recorded into it, so a later,
    separate pass (`_run_steps`, via `run_scenario`'s own
    `add_source_scope`) can recognize -- purely by object identity, never
    by mutating the descriptor dict itself, which would otherwise break
    every existing unit test comparing a normalized descriptor for exact
    equality -- that a given item came through this module's own
    add_source normalization, and is therefore eligible for
    `_apply_add_source_local_defaults`'s further sourceType/owner/
    permissionState defaults. A raw, directly-documented
    `{"sources": [...]}` field entry never reaches this branch at all
    (see the module comment above `_normalize_scenario_doc`), so its own
    items are never added to this set."""
    action = entry.get("action")
    if not isinstance(action, str) or not action:
        raise EngineError(
            "VALIDATION_ERROR",
            f'action-list scenario element {index} has a non-string or empty "action" ({action!r}); '
            f"expected one of {_KNOWN_ACTIONS}",
            {"index": index, "action": action},
        )
    field = _ACTION_ALIASES.get(action)
    if field is None:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action-list scenario element {index} names an unknown action '{action}'; "
            f"expected one of {_KNOWN_ACTIONS}",
            {"index": index, "action": action},
        )
    payload = {k: v for k, v in entry.items() if k != "action"}

    if action == "select_throughline":
        # Bypasses the generic single-target-field shapes below entirely
        # -- this one action's payload can resolve into either of two
        # object-form fields depending on which selector key it used (see
        # `_apply_select_throughline_entry`), never a guess between them.
        _apply_select_throughline_entry(merged, payload, index)
        return

    if action == "select_narrative_route":
        # Same bypass, for the parallel route-selection field (see
        # `_apply_select_narrative_route_entry`) -- `select_route` itself
        # is unaffected and still only ever writes `selectRouteIndex`
        # through the generic scalar path below.
        _apply_select_narrative_route_entry(merged, payload, index)
        return

    if action == "rehearse":
        # Bypasses `set_rehearsal_timing`'s own narrow single-shape
        # handling below entirely -- `rehearse` is the wider, public
        # verb naming ARCH's entire "Rehearse" command group and accepts
        # six mutually exclusive sub-shapes (see `_apply_rehearse_entry`
        # and the module comment above it), only one of which
        # (`_apply_rehearsal_timing_entry`, reused verbatim) is shared
        # with `set_rehearsal_timing`.
        _apply_rehearse_entry(merged, payload, index)
        return

    if field == "sources":
        # Bypasses the generic "list of objects" shape below -- accepts
        # direct fields or any structurally-discovered container shape
        # (including a `sources` list contributing several at once); see
        # `_normalize_source_action_entries` above. Both `ingest_source`
        # and `add_source` share this identical handling.
        for item in _normalize_source_action_entries(payload, action, index):
            if add_source_scope is not None:
                add_source_scope.add(id(item))
            merged.setdefault(field, []).append(item)
        return

    if field == "rehearsalTimings":
        # Bypasses the generic "mapping" shape below -- accepts any of
        # several slide-reference/duration field-name aliases; see
        # `_apply_rehearsal_timing_entry` above. Only `set_rehearsal_timing`
        # reaches this branch now (`rehearse` is special-cased above).
        _apply_rehearsal_timing_entry(merged, payload, action, index)
        return

    if field == "compileRequested":
        # Bypasses the generic scalar shape below -- neither
        # `compile_deck` nor `compile_presentation` carries (or accepts)
        # any inline payload at all; see `_apply_compile_requested_entry`
        # above.
        _apply_compile_requested_entry(merged, payload, action, index)
        return

    if field in _ACTION_LIST_OBJECT_FIELDS:
        payload = _unwrap_generic_action_wrapper(payload)
        if not payload:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action '{action}' at element {index} has no inline payload fields",
                {"index": index, "action": action, "field": field},
            )
        merged.setdefault(field, []).append(payload)
        return

    if field in _ACTION_LIST_SCALAR_FIELDS:
        extra = sorted(set(payload) - {"value"})
        if "value" not in payload or extra:
            raise EngineError(
                "VALIDATION_ERROR",
                f'action \'{action}\' at element {index} must carry its item in exactly one "value" '
                f"field (unexpected field(s): {extra})",
                {"index": index, "action": action, "field": field, "unexpectedFields": extra},
            )
        merged.setdefault(field, []).append(payload["value"])
        return

    if field in _ACTION_MAPPING_FIELDS:
        key_field, value_field = _ACTION_MAPPING_FIELDS[field]
        extra = sorted(set(payload) - {key_field, value_field})
        if key_field not in payload or value_field not in payload or extra:
            raise EngineError(
                "VALIDATION_ERROR",
                f'action \'{action}\' at element {index} requires exactly "{key_field}" and '
                f'"{value_field}" inline payload fields (unexpected field(s): {extra})',
                {"index": index, "action": action, "field": field, "unexpectedFields": extra},
            )
        bucket = merged.setdefault(field, {})
        if payload[key_field] in bucket:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action '{action}' at element {index} repeats key '{payload[key_field]}' "
                "(ambiguous: which value should win?)",
                {"index": index, "action": action, "field": field, "key": payload[key_field]},
            )
        bucket[payload[key_field]] = payload[value_field]
        return

    # Remaining kinds ("object" and "scalar") may each appear at most
    # once — exactly the same invariant (and the identical error) a
    # repeated field-list-form field already enforces below.
    if field in merged:
        raise EngineError(
            "VALIDATION_ERROR",
            f"list-form scenario document repeats top-level field '{field}' (action '{action}', element {index})",
            {"index": index, "field": field, "action": action},
        )

    if field in _ACTION_OBJECT_FIELDS:
        payload = _unwrap_generic_action_wrapper(payload)
        if not payload:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action '{action}' at element {index} has no inline payload fields",
                {"index": index, "action": action, "field": field},
            )
        merged[field] = payload
        return

    # field in _ACTION_SCALAR_FIELDS -- `"value"` and the object-form
    # field's own name are always accepted; a handful of fields also
    # accept additional, explicit public-vocabulary aliases
    # (`_ACTION_SCALAR_FIELD_ALIASES`, e.g. `stageApprover`'s
    # `approverName`/`approver_name`) as further redundant synonyms for
    # the identical target field -- never a second field, and a
    # conflicting value across *any* of these keys is the same
    # `VALIDATION_ERROR` a `"value"`/named-field conflict already raised.
    allowed_keys = {"value", field, *_ACTION_SCALAR_FIELD_ALIASES.get(field, ())}
    extra = sorted(set(payload) - allowed_keys)
    if extra:
        raise EngineError(
            "VALIDATION_ERROR",
            f'action \'{action}\' at element {index} has unexpected inline payload field(s) {extra}; '
            f'expected one of {sorted(allowed_keys)}',
            {"index": index, "action": action, "field": field, "unexpectedFields": extra},
        )
    present_keys = [k for k in allowed_keys if k in payload]
    resolved_by_key = {k: payload[k] for k in present_keys}
    if field == "stageApprover":
        # A nested-object approver value (e.g. `{"approver": {"name":
        # "Jane Doe"}}`) is unwrapped to a plain string *before* the
        # conflict/hashability check below -- a dict naming none of the
        # recognized approver fields is left as-is here, surfacing later
        # as `_coerce_named_approver_scalar`'s own explicit
        # `VALIDATION_ERROR` at the point `stageApprover` is consumed.
        for k in present_keys:
            if isinstance(resolved_by_key[k], dict):
                nested = _extract_named_approver_string(resolved_by_key[k])
                if nested is not None:
                    resolved_by_key[k] = nested
    distinct_values = {resolved_by_key[k] for k in present_keys}
    if len(distinct_values) > 1:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} gives conflicting values via {sorted(present_keys)} "
            "(ambiguous: which one should win?)",
            {"index": index, "action": action, "field": field},
        )
    if not present_keys:
        raise EngineError(
            "VALIDATION_ERROR",
            f'action \'{action}\' at element {index} is missing its inline "value" field',
            {"index": index, "action": action, "field": field},
        )
    merged[field] = resolved_by_key[present_keys[0]]


def _normalize_scenario_doc(doc: Any, add_source_scope: Optional[set[int]] = None) -> dict[str, Any]:
    """Accepts any of the three wire-compatible scenario document shapes
    and returns the plain `dict` every step function below expects:

    - Object-form (documented, unchanged): a single JSON object, returned
      as-is.
    - Field-list form (black-box-caller compatibility): a JSON array whose
      every element is a JSON object naming exactly one top-level field,
      e.g. `[{"actor": "..."}, {"sources": [...]}, {"claims": [...]}, ...]`.
      Elements are merged, in list order, into the identical dict the
      object-form would have produced.
    - Action-list form (black-box-caller compatibility): a JSON array
      whose elements each carry an `"action"` field naming one canonical
      public action verb, plus that action's inline payload as the
      entry's other keys, e.g. `[{"action": "ingest_source", "uri":
      "...", "origin": "..."}, ...]` — see `_ACTION_ALIASES` and
      `_apply_action_list_entry` above for the full verb vocabulary and
      per-action contract. Freely composable with field-list elements in
      the same document (each element is dispatched independently, by
      shape).

    All three are a pure wire-format normalization — every shape drives
    the exact same execution model below, never a second code path.

    Anything else — a document that is neither a dict nor a list, a list
    element that isn't a non-empty object, a non-action element that
    doesn't name exactly one top-level field, an action element with an
    unknown/malformed/ambiguous action or payload, or a top-level field
    repeated across elements (via either form) — is a clean
    `VALIDATION_ERROR` (never the `AttributeError` a bare `.get()` call on
    a list would otherwise raise).

    `add_source_scope` (Dark Factory hardening cycle 13, optional --
    every existing caller that never passes it behaves identically to
    before) is forwarded, unchanged, to every `_apply_action_list_entry`
    call this function makes -- see that function's own docstring for
    what it records.
    """
    if isinstance(doc, dict):
        return doc
    if not isinstance(doc, list):
        raise EngineError(
            "VALIDATION_ERROR",
            "scenario document must be a JSON object, or a list-form array of single-key objects "
            f"or action-tagged objects (got {type(doc).__name__})",
            {"type": type(doc).__name__},
        )
    merged: dict[str, Any] = {}
    for index, entry in enumerate(doc):
        if not isinstance(entry, dict) or not entry:
            raise EngineError(
                "VALIDATION_ERROR",
                "each list-form scenario element must be a non-empty JSON object — either exactly "
                f'one top-level field, e.g. {{"sources": [...]}}, or an action-tagged object, e.g. '
                f'{{"action": "ingest_source", ...}} (element {index} is {entry!r})',
                {"index": index, "entry": entry},
            )
        if "action" in entry:
            _apply_action_list_entry(merged, entry, index, add_source_scope)
            continue
        if len(entry) != 1:
            raise EngineError(
                "VALIDATION_ERROR",
                "each list-form scenario element must be a JSON object with exactly one top-level "
                f'field, e.g. {{"sources": [...]}} (element {index} is {entry!r}); add an "action" '
                "field to use a multi-field action-list entry instead",
                {"index": index, "entry": entry},
            )
        (field_name, value), = entry.items()
        if field_name in merged:
            raise EngineError(
                "VALIDATION_ERROR",
                f"list-form scenario document repeats top-level field '{field_name}' (element {index})",
                {"index": index, "field": field_name},
            )
        merged[field_name] = value
    return merged


def run_scenario(
    store: persistence.Store, doc: dict[str, Any] | list[Any], out_dir: Path,
    export_dir: Optional[Path] = None, scenario_path: Optional[Path] = None,
) -> dict:
    """Entry point used by every invocation form of `cli.py`'s
    `cmd_run_scenario` (`--out`, `--workspace`/`--export-dir`, or the bare
    default-root form) and by the open tests directly. `export_dir`, if
    given, overrides where the Stage package (if Stage passes) is
    physically written, instead of the default location nested under the
    workspace root (ARCH §4, §10).

    `scenario_path` (Dark Factory hardening cycle 12, optional, additive
    -- every existing/direct caller that never passes it behaves
    identically to before) is the on-disk path of the scenario document
    itself, when known (`cli.py`'s `--scenario` always provides it). Its
    parent directory is threaded down to `add_source`/`ingest_source`
    handling as the base directory a *relative* local/fixture `uri` is
    resolved against, before falling back to the current working
    directory exactly as before -- see `ingest._resolve_local_path`.

    `doc` may be any accepted scenario-document shape (object-form,
    field-list form, or action-list form; see `_normalize_scenario_doc`
    and `_is_action_list_document`). `_normalize_scenario_doc` always runs
    first, over the whole document, regardless of shape -- so a malformed
    document shape (an unknown action verb, a payload that doesn't match
    its action's own required shape, ...) is always a clean, immediate
    `VALIDATION_ERROR` (propagated, never treated as a mid-run refusal --
    see the `except EngineError` below, which only guards the walk
    *after* this point) before any workspace/connection ever exists, for
    every shape alike. What differs is which *executor* a well-formed
    document then drives: object-form/field-list-form documents (no
    per-element order of their own) execute via `_run_steps`'s
    unchanged, fixed-order batch walk, against the flattened dict
    `_normalize_scenario_doc` already produced; a *true* action-list
    document (every element names an explicit `"action"` verb) instead
    executes via `_run_ordered_action_list`, straight from the original,
    ordered document -- never the flattened dict, which for that shape is
    consulted only for a handful of whole-document scalar/config fields.

    Exit-code/report contract: this function never raises for a correctly
    refused/blocked step (see module docstring) — it always returns a
    report dict and always writes `<out_dir>/run-report.json`, so the CLI
    always exits 0 for a normal completion. Only a genuine bug (a
    non-`EngineError` exception, including a malformed scenario document)
    propagates out of this function.

    Whether the walk completes or is correctly refused/blocked partway,
    the report is always finished off with a fresh read of the workspace's
    own persisted state (`_attach_workspace_state`) before the connection
    closes -- so a caller can always discover exactly what was actually
    durably persisted (sources, evidence, claims, conflicts, throughlines,
    routes, slides, gate results, restore points, audit events, and a
    workspace-status summary), never just whichever steps happened to run
    before a refusal ended the walk early.
    """
    # Dark Factory hardening cycle 8 (root-cause fix): a *true* action-list
    # document -- every element names an explicit `"action"` verb, as
    # opposed to object-form, or the field-list form's single-key
    # elements -- is never flattened into one aggregate object before
    # anything executes. `_normalize_scenario_doc` is still run first
    # (unchanged -- see `_is_action_list_document`'s own docstring), both
    # so every existing shape/alias/ambiguity check it and
    # `_apply_action_list_entry` already enforce still runs, and to
    # resolve the handful of true whole-document scalars (`actor`,
    # `brief`, `evidenceDefaultDisposition`, `evidenceOverrides`,
    # `autoAltText`, `skipDemos`, `stageApprover`) exactly once, up front
    # -- but the *domain-mutating* fields it also computes
    # (`sources`/`claims`/`throughlineDrafts`/... ) are never used to
    # execute a true action-list document; `_run_ordered_action_list`
    # below dispatches straight from the original, ordered `doc` instead,
    # one action at a time, against the identical already-existing domain
    # calls `_run_steps` itself uses -- so a malformed element (unknown
    # action, wrong payload shape, cross-element ambiguity, ...) is still
    # exactly the same clean, immediate `VALIDATION_ERROR` raised before
    # any workspace/connection exists (never a mid-run refusal), while a
    # repeated verb (26 `add_source` actions, interleaved gate/claim/
    # source-lifecycle actions, ...) executes and persists once per
    # occurrence, in original order, immediately visible to every action
    # after it.
    is_action_list = _is_action_list_document(doc)
    # Dark Factory hardening cycle 13: identity set populated during
    # normalization with every "sources" item that came through this
    # module's own add_source/ingest_source normalization (never a raw
    # `{"sources": [...]}` field entry) -- consulted only by `_run_steps`
    # below, so its own further sourceType/owner/permissionState defaults
    # (`_apply_add_source_local_defaults`) apply only to those items.
    # Irrelevant for a *true* action-list document (`_run_ordered_action_
    # list` re-derives "sources" per element, always already add_source-
    # scoped by construction), but harmless to populate regardless.
    add_source_scope: set[int] = set()
    merged = _normalize_scenario_doc(doc, add_source_scope)
    report: dict[str, Any] = {"steps": [], "ok": True, "refusal": None}
    actor = merged.get("actor") or "Scenario Runner"
    scenario_dir = Path(scenario_path).resolve().parent if scenario_path else None

    try:
        ws, brief, resumed = _open_or_resume_workspace(store, actor, merged.get("brief"))
        report["workspaceId"] = ws.id
        report["briefId"] = brief.id
        report["workspaceResumed"] = resumed
        conn = store.connect(ws.id)
        try:
            try:
                if is_action_list:
                    _run_ordered_action_list(conn, store, ws, brief, doc, merged, actor, report, export_dir, scenario_dir)
                else:
                    _run_steps(conn, store, ws, brief, merged, actor, report, export_dir, scenario_dir, add_source_scope=add_source_scope)
            except EngineError as exc:
                # A deliberate, correctly-refused/blocked domain rule
                # (ARCH §12) -- not a bug. Represent it in the result
                # document; still a normal, zero-exit-code completion
                # (see module docstring). Caught *here*, inside the open
                # connection, rather than only by the outer handler below,
                # so `_attach_workspace_state` immediately after can still
                # read back whatever this walk already durably persisted
                # before the refusal.
                report["ok"] = False
                report["refusal"] = exc.to_dict()
            _attach_workspace_state(conn, ws.id, report)
        finally:
            conn.close()
    except EngineError as exc:
        # A refusal raised before a workspace/connection ever existed
        # (e.g. `WORKSPACE_ALREADY_ACTIVE` from `_open_or_resume_workspace`
        # itself) -- there is no persisted state to attach.
        report["ok"] = False
        report["refusal"] = exc.to_dict()

    out_dir.mkdir(parents=True, exist_ok=True)
    _attach_action_results_ledger(report)
    models.add_report_compat_aliases(report)
    (out_dir / "run-report.json").write_text(json.dumps(report, indent=2, default=str))
    return report


def _attach_action_results_ledger(report: dict[str, Any]) -> None:
    """Compatibility action-results ledger (Dark Factory hardening cycle
    7): `report["steps"]` already records one entry per executed step,
    but never a step for a domain-refused attempt that stopped the walk
    before it could append one (e.g. a denied/over-the-cap source -- see
    `run_scenario`'s own module docstring on why that walk-ending
    `EngineError` is deliberately never appended to `steps` itself, which
    keeps every one of its pre-existing shapes/tests exactly as before).
    `actionResults`/`action_results` is an additive, read-only copy of
    `steps` (each entry tagged `"ok": True` -- every recorded step is, by
    construction, one that actually executed) with one trailing entry
    appended for the walk's own final refusal, if any, so a caller
    scanning a single ledger sees every attempted action's outcome,
    success or failure, without separately cross-referencing
    `report["refusal"]`. Never removes or reshapes `report["steps"]`
    itself.

    A no-op whenever `report["actionResults"]` is already present --
    `_run_ordered_action_list` (Dark Factory hardening cycle 8) populates
    both `actionResults` and `action_results` itself, directly, with one
    entry per original action-list element (never derived from `steps`,
    which stays in its own pre-existing, richer/aggregate shape for that
    execution path too -- see that function's own docstring)."""
    if "actionResults" in report:
        return
    results = [dict(step, ok=True) for step in report.get("steps", [])]
    if not report.get("ok", True) and report.get("refusal"):
        results.append({"action": "scenario.refusal", "ok": False, "error": report["refusal"]})
    report["actionResults"] = results
    report["action_results"] = results


def _attach_workspace_state(conn, workspace_id: str, report: dict[str, Any]) -> None:
    """Populates the scenario report with a fresh read of every
    persisted, workspace-scoped collection, regardless of how far
    `_run_steps` reached before a correctly-refused/blocked step ended the
    walk (see `run_scenario`'s own docstring) -- so a caller can always
    discover exactly what the engine actually persisted, never just
    whichever steps happened to run before a refusal. Called with the
    same open connection `_run_steps` itself used, both on a clean
    completion and right after an `EngineError` is caught, so even a
    first-step refusal (e.g. a rejected source) still surfaces whatever
    was durably committed up to that point (and, on a resumed workspace,
    everything accumulated by every earlier call too).

    Never overwrites a key `_run_steps` already populated with a richer,
    walk-specific shape (`throughline`, `route`, `package`, `rehearsal`,
    `qa`, `exports`, `preStageGates`, `stageGate`) -- those keep their own
    existing contract untouched; this only adds the plain, full-ledger
    collections plus `gateResults`/`auditEvents` (previously only ever
    computed unconditionally at the very end of `_run_steps`, so an early
    abort meant neither ever appeared at all)."""
    report["sources"] = [models.to_jsonable(s) for s in persistence.list_all(conn, "source", workspace_id, models.SourceArtifact)]
    report["evidence"] = [models.to_jsonable(a) for a in persistence.list_all(conn, "evidence", workspace_id, models.EvidenceAtom)]
    report["claims"] = [models.to_jsonable(c) for c in persistence.list_all(conn, "claim", workspace_id, models.Claim)]
    report["conflicts"] = [models.to_jsonable(c) for c in persistence.list_all(conn, "conflict", workspace_id, models.ConflictCard)]
    report["throughlines"] = [models.to_jsonable(t) for t in persistence.list_all(conn, "throughline", workspace_id, models.NarrativeThroughline)]
    report["routes"] = [models.to_jsonable(r) for r in persistence.list_all(conn, "route", workspace_id, models.NarrativeRoute)]
    report["slides"] = [models.to_jsonable(s) for s in persistence.list_all(conn, "slide", workspace_id, models.SlideSpec)]
    report["restorePoints"] = [models.to_jsonable(r) for r in restore_mod.list_restore_points(conn, workspace_id)]

    gate_results = gates.gate_status(conn, workspace_id)
    report["gateResults"] = [models.to_jsonable(g) for g in gate_results]
    report["readiness"] = next(
        (models.to_jsonable(g) for g in gate_results if g.gate == models.GateName.READINESS.value), None,
    )
    report["auditEvents"] = [models.to_jsonable(e) for e in audit_mod.tail_audit(conn, workspace_id)]

    ws_now = persistence.get(conn, "workspace", workspace_id, models.Workspace)
    if ws_now is not None:
        report["workspace"] = {
            "id": ws_now.id, "phase": ws_now.phase, "deckId": ws_now.deck_id, "manifestId": ws_now.manifest_id,
            "activeThroughlineId": ws_now.active_throughline_id, "activeRouteId": ws_now.active_route_id,
            "stageApprovedBy": ws_now.stage_approved_by, "stageApprovedAt": ws_now.stage_approved_at,
            "lastRehearsalAt": ws_now.last_rehearsal_at,
        }


def _open_or_resume_workspace(
    store: persistence.Store, actor: str, brief_payload: Optional[dict],
) -> tuple[models.Workspace, models.TalkBrief, bool]:
    """Opens the workspace this `run_scenario` call operates against
    (ARCH §11). `run-scenario`'s own "explicit workspace" identity *is*
    the resolved store root (`--workspace <dir>`, the bare default-root
    form, or legacy `--out` alongside the global `--workspace-root`) —
    there is no separate `--id` the way `workspace resume` has — so a
    later call whose store resolves to the *same* root idempotently
    resumes whatever workspace is already active there, exactly like the
    bare no-subcommand form and `status` already do
    (`cli.cmd_bare_default_workspace`) via the identical
    `workspace_mod.show_workspace` read, rather than trying (and always
    losing the race) to open a brand-new one on top of it. This is what
    lets repeated scenario calls against one explicit workspace accumulate
    sources/claims/etc. into the single curated bundle instead of being
    refused outright.

    A genuinely different workspace is still fully protected: this
    function never bypasses the lock itself, only skips *re-acquiring*
    it when it already points at this same root's own workspace.
    `workspace_mod.create_workspace` — used both by this function's own
    fallback branch (no workspace active yet at this root) and by every
    other caller (`workspace new`) — is completely unchanged and still
    raises `WORKSPACE_ALREADY_ACTIVE` exactly as before whenever a lock
    for a *different* workspace already exists (NFR-2's exclusivity is
    never weakened).

    A resumed call's own `brief_payload` (if given) is applied as a
    partial update onto the resumed workspace's existing brief via
    `workspace_mod.set_brief` — the same partial-update semantics `brief
    set` already has — rather than silently discarded or used to
    fabricate a second brief.

    Returns `(workspace, brief, resumed)`; `resumed` is `True` iff an
    already-active workspace was reused rather than newly created.
    """
    existing = workspace_mod.show_workspace(store)
    if existing is not None:
        ws, brief = existing["workspace"], existing["brief"]
        if brief_payload:
            conn = store.connect(ws.id)
            try:
                ws, brief = workspace_mod.set_brief(conn, ws.id, brief_payload, actor=actor)
            finally:
                conn.close()
        return ws, brief, True
    ws, brief = workspace_mod.create_workspace(store, actor=actor, brief_payload=brief_payload)
    return ws, brief, False


def _resolve_throughline_selection(
    doc: dict[str, Any], throughlines: list[models.NarrativeThroughline], conn, workspace_id: str, actor: str,
) -> models.NarrativeThroughline:
    """Resolves whichever throughline-selection field(s) the normalized
    scenario document carries into exactly one `narrative.select_throughline`
    call, now that the actual candidates exist (FR-NAR-2): `customThroughline`
    (the pre-existing `select_custom_throughline` action / plain object-form
    field) always creates a brand-new custom throughline, unchanged;
    `selectThroughlineText` (new -- fed by `select_throughline`'s `"text"`
    alias) instead first looks for a candidate whose text matches verbatim,
    selecting *that* candidate by id if found (never a redundant duplicate),
    and only falls back to a genuine custom throughline otherwise; bare
    `selectThroughlineIndex` (default 0) selects by position. Ambiguous
    (both text and custom given) or unmatched (a non-integer or out-of-range
    index, or `text` matching more than one candidate) selections are a
    clean `VALIDATION_ERROR`, never a guess or a raw `IndexError`."""
    selection_text = doc.get("selectThroughlineText")
    custom_text = doc.get("customThroughline")
    if selection_text and custom_text:
        raise EngineError(
            "VALIDATION_ERROR",
            "scenario document gives both 'selectThroughlineText' and 'customThroughline' "
            "(ambiguous: which throughline selection should win?)",
            {"selectThroughlineText": selection_text, "customThroughline": custom_text},
        )

    if selection_text:
        matches = [t for t in throughlines if t.text == selection_text]
        if len(matches) > 1:
            raise EngineError(
                "VALIDATION_ERROR",
                f"selectThroughlineText {selection_text!r} matches {len(matches)} candidate "
                "throughlines (ambiguous)",
                {"selectThroughlineText": selection_text, "matchCount": len(matches)},
            )
        if matches:
            return narrative.select_throughline(conn, workspace_id, actor=actor, throughline_id=matches[0].id)
        return narrative.select_throughline(conn, workspace_id, actor=actor, custom_text=selection_text)

    if custom_text:
        return narrative.select_throughline(conn, workspace_id, actor=actor, custom_text=custom_text)

    idx_raw = doc.get("selectThroughlineIndex", 0)
    try:
        idx = int(idx_raw)
    except (TypeError, ValueError):
        raise EngineError(
            "VALIDATION_ERROR", f"selectThroughlineIndex must be an integer (got {idx_raw!r})",
            {"selectThroughlineIndex": idx_raw},
        ) from None
    if not (0 <= idx < len(throughlines)):
        raise EngineError(
            "VALIDATION_ERROR",
            f"selectThroughlineIndex {idx} does not match any of the {len(throughlines)} candidate "
            "throughline(s)",
            {"selectThroughlineIndex": idx, "candidateCount": len(throughlines)},
        )
    return narrative.select_throughline(conn, workspace_id, actor=actor, throughline_id=throughlines[idx].id)


def _resolve_route_selection(
    doc: dict[str, Any], routes: list[models.NarrativeRoute], conn, workspace_id: str, actor: str,
) -> models.NarrativeRoute:
    """Resolves whichever route-selection field(s) the normalized
    scenario document carries into exactly one `narrative.select_route`
    call, now that the actual candidate routes exist: `selectRouteText`
    (new -- fed by `select_narrative_route`'s `"text"` alias) matches a
    candidate route's own `label` verbatim, selecting that route by id.
    Unlike a throughline, a route is a full beat spine, never freeform
    text, so there is no "custom route" fallback: `text` matching none
    (or more than one) of the candidate routes' labels is a clean
    `VALIDATION_ERROR`, never a guessed/synthesized route. Bare
    `selectRouteIndex` (default 0, the pre-existing `select_route` /
    `select_narrative_route` numeric contract) selects by position.
    Supplying both is a clean `VALIDATION_ERROR`, as is a non-integer or
    out-of-range index -- never a raw `IndexError`."""
    selection_text = doc.get("selectRouteText")
    if selection_text and "selectRouteIndex" in doc:
        raise EngineError(
            "VALIDATION_ERROR",
            "scenario document gives both 'selectRouteText' and 'selectRouteIndex' "
            "(ambiguous: which route selection should win?)",
            {"selectRouteText": selection_text, "selectRouteIndex": doc.get("selectRouteIndex")},
        )

    if selection_text:
        matches = [r for r in routes if r.label == selection_text]
        if len(matches) > 1:
            raise EngineError(
                "VALIDATION_ERROR",
                f"selectRouteText {selection_text!r} matches {len(matches)} candidate routes (ambiguous)",
                {"selectRouteText": selection_text, "matchCount": len(matches)},
            )
        if not matches:
            raise EngineError(
                "VALIDATION_ERROR",
                f"selectRouteText {selection_text!r} does not match any of the {len(routes)} candidate "
                "route(s) by label (a route has no freeform custom-text equivalent -- it must name an "
                "already-proposed route's own label)",
                {"selectRouteText": selection_text, "candidateCount": len(routes)},
            )
        return narrative.select_route(conn, workspace_id, matches[0].id, actor=actor)

    idx_raw = doc.get("selectRouteIndex", 0)
    try:
        idx = int(idx_raw)
    except (TypeError, ValueError):
        raise EngineError(
            "VALIDATION_ERROR", f"selectRouteIndex must be an integer (got {idx_raw!r})",
            {"selectRouteIndex": idx_raw},
        ) from None
    if not (0 <= idx < len(routes)):
        raise EngineError(
            "VALIDATION_ERROR",
            f"selectRouteIndex {idx} does not match any of the {len(routes)} candidate route(s)",
            {"selectRouteIndex": idx, "candidateCount": len(routes)},
        )
    return narrative.select_route(conn, workspace_id, routes[idx].id, actor=actor)


# `export`'s public payload accepts a `target` naming which existing
# export path to run (`pptx`/`deck`/`draft` -> `package.export_pptx_draft`,
# the standalone draft render `export pptx` already performs; `package`/
# `stage` -> `package.export_package`, the full 9-artifact Stage package
# `export package` already performs), plus an optional `renderMode`
# (`pptx` target only) and an optional `outputDir`/`exportDir` override
# (`package` target only -- `pptx` has no such override anywhere in the
# domain layer, exactly like the CLI's own `export pptx` subcommand).
_EXPORT_TARGET_ALIASES = {
    "pptx": "pptx", "deck": "pptx", "draft": "pptx", "pptx_draft": "pptx", "deck_export": "pptx",
    "package": "package", "stage": "package", "stage_package": "package", "stagepackage": "package",
}
# (Dark Factory hardening cycle 9, acceptance pass 12) Several public
# scenario callers name the *target* concept itself via a different field
# name entirely, not just a different value spelling -- `format`/`kind`/
# `type`/`mode` are conservative, explicit synonyms for `target`, each
# resolved through the identical `_EXPORT_TARGET_ALIASES` value table
# above (never a second/looser one). A boolean-ish "wrapper" field can
# also name the target directly, with no separate target-field at all --
# `pptx`/`stagePackage`/`stage_package` -- only a truthy value selects
# that target (a falsy one is simply absent, exactly like an omitted
# field). Two of these naming *different* resolved targets (whether two
# field names, or a field plus a wrapper) is an explicit
# `VALIDATION_ERROR`, never a guess; naming the identical resolved target
# more than once is redundant, not ambiguous.
_EXPORT_TARGET_FIELD_NAMES = ("target", "format", "kind", "type", "mode")
_EXPORT_TARGET_WRAPPER_FIELDS = {"pptx": "pptx", "stagePackage": "package", "stage_package": "package"}
_EXPORT_RENDER_MODE_FIELD_NAMES = ("renderMode", "render_mode")
# `output`/`path`/`directory` are further conservative synonyms for the
# existing `outputDir`/`output_dir`/`exportDir`/`export_dir` override
# (`package` target only, exactly as before) -- resolved the identical
# way (an explicit string value, compared verbatim; two of them naming
# *different* paths is an explicit `VALIDATION_ERROR`). `out_dir` (Dark
# Factory hardening cycle 10, acceptance pass 13) is a further such
# synonym -- the same short form `cli.py`'s own `run-scenario --out`
# flag already uses for the unrelated *workspace* root, but here, inline
# on one `export` request, it names this identical output-directory
# override instead.
_EXPORT_OUTPUT_DIR_FIELD_NAMES = (
    "outputDir", "output_dir", "exportDir", "export_dir", "output", "path", "directory", "out_dir",
)
_EXPORT_REQUEST_ALLOWED_FIELDS = frozenset(
    _EXPORT_TARGET_FIELD_NAMES + _EXPORT_RENDER_MODE_FIELD_NAMES + _EXPORT_OUTPUT_DIR_FIELD_NAMES
    + _APPROVER_ALIAS_FIELDS + _APPROVER_NESTED_ONLY_FIELDS + tuple(_EXPORT_TARGET_WRAPPER_FIELDS)
)


def _resolve_export_target(request: dict, index: int) -> Optional[str]:
    """Resolves `export`'s target concept from every accepted field-name/
    wrapper alias (see the module comment above) -- returns the one
    canonical `"pptx"`/`"package"` value every alias/wrapper present
    agrees on, `None` if none are present at all, or raises an explicit
    `VALIDATION_ERROR` for either an unrecognized value or a genuine
    conflict between two aliases naming different targets."""
    contributions: dict[str, str] = {}
    for field in _EXPORT_TARGET_FIELD_NAMES:
        if field not in request or request[field] is None:
            continue
        raw = request[field]
        normalized = str(raw).strip().lower().replace("-", "_").replace(" ", "_") if isinstance(raw, str) else None
        canon = _EXPORT_TARGET_ALIASES.get(normalized) if normalized else None
        if canon is None:
            raise EngineError(
                "VALIDATION_ERROR",
                f"export request {index} has an unrecognized '{field}' ({raw!r}); expected one of "
                f"{sorted(_EXPORT_TARGET_ALIASES)}",
                {"index": index, "field": field, "value": raw},
            )
        contributions[field] = canon
    for field, canon in _EXPORT_TARGET_WRAPPER_FIELDS.items():
        if request.get(field):
            contributions[field] = canon
    distinct = set(contributions.values())
    if len(distinct) > 1:
        raise EngineError(
            "VALIDATION_ERROR",
            f"export request {index} has conflicting target field(s) {sorted(contributions)} implying "
            "different export operations (ambiguous: which one should win?)",
            {"index": index, "fields": sorted(contributions)},
        )
    return next(iter(distinct)) if distinct else None


def _resolve_export_output_dir(request: dict, index: int) -> Optional[str]:
    """Resolves `export`'s output-directory override from every accepted
    field-name alias -- returns the one path every alias present agrees
    on (compared verbatim, not normalized -- these are literal
    filesystem paths), `None` if none are present, or an explicit
    `VALIDATION_ERROR` if two name genuinely different paths."""
    found: dict[str, str] = {}
    for field in _EXPORT_OUTPUT_DIR_FIELD_NAMES:
        if request.get(field):
            found[field] = request[field]
    distinct = set(found.values())
    if len(distinct) > 1:
        raise EngineError(
            "VALIDATION_ERROR",
            f"export request {index} has conflicting output-directory field(s) {sorted(found)} "
            "(ambiguous: which one should win?)",
            {"index": index, "fields": sorted(found)},
        )
    return next(iter(distinct)) if distinct else None


# `run_gate`'s gate-name field accepts the documented canonical `gate`
# name plus `gateName`/`gate_name` aliases (Dark Factory hardening cycle
# 7) -- resolved in `_run_steps` below. It additionally accepts the
# identical shared named-approver alias vocabulary above (Dark Factory
# hardening cycle 9) so one `run_gate` request can name who performs
# *that* gate run, instead of always falling back to the whole-document
# `actor`.
_GATE_RUN_NAME_FIELDS = ("gate", "gateName", "gate_name")
_GATE_RUN_ALLOWED_FIELDS = frozenset(_GATE_RUN_NAME_FIELDS) | frozenset(_APPROVER_ALIAS_FIELDS) | frozenset(_APPROVER_NESTED_ONLY_FIELDS)


def _process_export_request(
    conn, ws, request: Any, stage_actor: str, scenario_export_dir: Optional[Path], index: int,
) -> dict[str, Any]:
    """Normalizes and executes one `export` action-list element's inline
    payload into the identical, already-existing
    `package.export_pptx_draft`/`package.export_package` call the CLI's
    own `export pptx`/`export package` subcommands use -- never a second
    export code path, and never a bypass of either function's own
    existing Stage-gate/named-approval checks. The target concept
    (`target`/`format`/`kind`/`type`/`mode`, or the `pptx`/`stagePackage`/
    `stage_package` boolean-ish wrapper fields -- see
    `_resolve_export_target`) and an optional named approver (`actor`/
    `approver`/`approverName`/`approver_name`/`human`/`name`, or a nested
    `approval`/`approver` object -- see `_resolve_named_approver_alias`)
    each accept a conservative, explicit allowlist of aliases; defaults
    to the scenario's own `stageApprover`/actor (the identical named-
    human-approval actor the automatic end-of-walk Stage export already
    uses) when no approver alias is given. An unrecognized/conflicting
    target, an unexpected field, an invalid `renderMode`, conflicting
    output-directory aliases, or an `outputDir`/`exportDir` (or any of
    its aliases) given for the `pptx` target (which has no such override
    anywhere in the domain layer) is a clean `VALIDATION_ERROR`, never a
    guess. A `package` target whose Stage gate has not passed raises
    `package.export_package`'s own pre-existing `GATE_NOT_PASSED` --
    propagated untouched, so it is caught by `run_scenario`'s existing
    `except EngineError` handler exactly like any other domain refusal (a
    structured `report["refusal"]`, exit 0, never a bypassed gate)."""
    if not isinstance(request, dict) or not request:
        raise EngineError(
            "VALIDATION_ERROR", f"export request {index} must be a non-empty object", {"index": index},
        )
    extra = sorted(set(request) - _EXPORT_REQUEST_ALLOWED_FIELDS)
    if extra:
        raise EngineError(
            "VALIDATION_ERROR",
            f"export request {index} has unexpected field(s) {extra}; expected one of "
            f"{sorted(_EXPORT_REQUEST_ALLOWED_FIELDS)}",
            {"index": index, "unexpectedFields": extra},
        )
    target = _resolve_export_target(request, index)
    if target is None:
        raise EngineError(
            "VALIDATION_ERROR",
            f"export request {index} is missing a recognized target field (one of "
            f"{sorted(_EXPORT_TARGET_FIELD_NAMES)}, or a truthy {sorted(_EXPORT_TARGET_WRAPPER_FIELDS)} "
            "wrapper field) naming which export operation to run",
            {"index": index},
        )
    request_actor = _resolve_named_approver_alias(request, action="export", index=index, default=stage_actor)
    output_dir = _resolve_export_output_dir(request, index)

    if target == "pptx":
        if output_dir:
            raise EngineError(
                "VALIDATION_ERROR",
                f"export request {index} targets 'pptx', which has no output-directory override -- it "
                "always writes to the workspace's own fixed draft location, exactly like 'export pptx' "
                "itself",
                {"index": index, "target": "pptx"},
            )
        render_mode = request.get("renderMode", request.get("render_mode", "normal"))
        if render_mode not in ("normal", "panic"):
            raise EngineError(
                "VALIDATION_ERROR",
                f"export request {index} has renderMode {render_mode!r}; expected 'normal' or 'panic'",
                {"index": index, "renderMode": render_mode},
            )
        result = package.export_pptx_draft(conn, ws.id, actor=request_actor, render_mode=render_mode)
        return {
            "target": "pptx", "renderMode": render_mode, "path": result["path"],
            "deckId": result["deckId"], "regionCount": result["regionCount"],
        }

    override_dir = Path(output_dir) if output_dir else scenario_export_dir
    result = package.export_package(conn, ws.id, actor=request_actor, export_dir_override=override_dir)
    return {
        "target": "package", "exportDir": result["exportDir"], "manifestId": result["manifestId"],
        "deckId": result["deckId"], "advisories": result["advisories"], "artifactKinds": result["artifactKinds"],
    }


# `revoke_source`/`quarantine_source`/`resolve_source_hold`/
# `retire_source`'s shared source-reference vocabulary (Dark Factory
# hardening cycle 7): a declarative one-pass scenario cannot know a
# source's server-generated id ahead of time merely from having staged
# its own `add_source`/`ingest_source` step earlier in the same document,
# so each lifecycle request may instead name the source by the `uri` it
# was ingested under -- resolved to that uri's current active source,
# first against this same walk's own freshly-ingested sources, then (for
# a resumed workspace) against the persisted ledger.
_SOURCE_LIFECYCLE_ID_FIELDS = ("sourceId", "source_id")
_SOURCE_LIFECYCLE_URI_FIELDS = ("uri", "sourceUri", "source_uri")
_SOURCE_LIFECYCLE_REFERENCE_FIELDS = _SOURCE_LIFECYCLE_ID_FIELDS + _SOURCE_LIFECYCLE_URI_FIELDS


def _resolve_source_lifecycle_target(
    conn, workspace_id: str, request: Any, sources_by_uri: dict[str, models.SourceArtifact], action: str, index: int,
) -> str:
    """Resolves one source-lifecycle action-list request's target source
    id from whichever reference field it gives -- `sourceId`/`source_id`
    (the source's own already-known generated id) or `uri`/`sourceUri`/
    `source_uri` (the locator it was ingested under). Conflicting values
    for the same reference kind, both an id and a uri together, neither,
    or a uri matching no active source is always a clean
    `VALIDATION_ERROR`/`NOT_FOUND`, never a guess."""
    if not isinstance(request, dict) or not request:
        raise EngineError(
            "VALIDATION_ERROR", f"action '{action}' at element {index} must be a non-empty object",
            {"index": index, "action": action},
        )
    id_values = {request[k] for k in _SOURCE_LIFECYCLE_ID_FIELDS if k in request}
    uri_values = {request[k] for k in _SOURCE_LIFECYCLE_URI_FIELDS if k in request}
    if len(id_values) > 1 or len(uri_values) > 1:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} gives conflicting values for the same source "
            "reference field (ambiguous: which one should win?)",
            {"index": index, "action": action},
        )
    if id_values and uri_values:
        raise EngineError(
            "VALIDATION_ERROR",
            f"action '{action}' at element {index} gives both a source id and a uri (ambiguous: which "
            "should identify the target source?)",
            {"index": index, "action": action},
        )
    if id_values:
        return next(iter(id_values))
    if uri_values:
        (uri,) = uri_values
        source = sources_by_uri.get(uri) or ingest_mod.find_active_source_by_uri(conn, workspace_id, uri)
        if source is None:
            raise EngineError(
                "NOT_FOUND", f"no active source found for uri '{uri}'", {"uri": uri},
            )
        return source.id
    raise EngineError(
        "VALIDATION_ERROR",
        f"action '{action}' at element {index} requires one of {_SOURCE_LIFECYCLE_REFERENCE_FIELDS} to "
        "identify the target source",
        {"index": index, "action": action},
    )


# ---------------------------------------------------------------------------
# Ordered action-list executor (Dark Factory hardening cycle 8)
# ---------------------------------------------------------------------------
#
# Root cause of acceptance-pass-11's empty sources/evidence/claims/routes/
# slides/gates/exports: every accepted scenario-document shape -- object-
# form, field-list form, *and* action-list form -- was normalized into one
# flattened `dict` (`_normalize_scenario_doc`) before a single domain call
# ever ran, and `_run_steps` then executed that flattened dict as one
# fixed-order batch (all sources, then all source-lifecycle transitions,
# then all claims, then conflicts, then narrative, then routes, then
# compile, then accessibility/demo, then gates, then rehearsal, then
# stage/package). That is still exactly correct for object-form/field-
# list-form documents (there is no per-element order to preserve -- a
# single JSON object's fields have no sequence at all), so that path
# (`_run_steps`, unchanged) remains their batch executor. But a *true*
# action-list document -- one whose every element names an explicit
# `"action"` verb -- has a real, caller-authored sequence, and repeated
# verbs (26 `add_source` actions, an interleaved `run_gate` before *and*
# after more sources are added, a source revoked partway through, ...)
# carry meaning that a fixed-phase batch can never represent: every
# `add_source` still ends up ingested (correctly), but a `run_gate`
# always evaluates the *final* fully-ingested bundle, never the partial
# one that actually existed at that point in the caller's own sequence,
# and a normalization-time failure anywhere in the list (even in a
# trailing, unrelated element) meant *zero* of the domain effects
# before it were ever attempted, let alone persisted or reported.
#
# `_run_ordered_action_list` below is the fix: it dispatches straight
# from the original, ordered `raw_doc` list, one element at a time,
# directly against the identical already-existing domain-module calls
# `_run_steps`/`cli.py`'s own subcommands use -- never a second business-
# logic implementation (`_apply_action_list_entry` itself, and every
# per-action-family helper above it, is reused completely unchanged, just
# invoked once per single element against a fresh, empty accumulator
# instead of the whole document's shared one, so every existing alias/
# wrapper/shape rule still applies identically). Every element's own
# domain effect is committed immediately and is visible to every element
# after it; a correctly-refused/blocked element stops the walk exactly
# like `_run_steps`'s own single fixed-order walk always has (the same
# `except EngineError` contract, one level up, in `run_scenario`), but
# every element *before* it has already been durably persisted and is
# still reported.
#
# Two domain calls -- `narrative.propose_throughlines` (exactly 3 drafts
# at once) and `narrative.propose_routes` (exactly 2 or 3 at once) --
# only ever accept one fixed-size batch, never a single draft at a time;
# this is a pre-existing, unchanged domain invariant (FR-NAR-1/FR-NAR-3),
# not something this executor may loosen. Repeated `propose_throughline`/
# `propose_route` actions therefore accumulate their drafts and are
# submitted together in the one call each already requires, made the
# moment a selection is actually needed (an explicit `select_throughline`/
# `select_route`-family action, or the end-of-walk default exactly like
# `_run_steps` already falls back to) -- still one persistence event per
# distinct proposal batch, just triggered by the caller's own sequence
# instead of a fixed phase position.
_ACTION_LEDGER_REFUSED_CODES = frozenset({
    "SOURCE_UNAUTHORIZED", "WORKSPACE_ALREADY_ACTIVE", "STAGE_APPROVER_REQUIRED", "APPROVER_REQUIRED",
    "ACCESS_REVOKED",
})
_ACTION_LEDGER_BLOCKED_CODES = frozenset({
    "BUNDLE_LIMIT_REACHED", "CONFLICT_UNRESOLVED", "GATE_NOT_PASSED", "NARRATIVE_GATE_FAILED",
    "ACCESSIBILITY_CHECK_FAILED", "DEMO_FALLBACK_MISSING", "CLAIM_UNSUPPORTED", "RATIONALE_REQUIRED",
    "IMMUTABLE_LOCKED_CLAIM", "FILE_TOO_LARGE", "UNSUPPORTED_FILE_TYPE", "LABEL_CONFLICT", "PARSE_FAILED",
})
# Every other `EngineError` code (`VALIDATION_ERROR`, `NOT_FOUND`,
# `RESTORE_POINT_NOT_FOUND`, `NO_ACTIVE_WORKSPACE`, `INTERNAL_ERROR`, ...)
# is `"failed"` -- an input/reference problem, distinct from a considered
# policy refusal or a precondition/capacity block. ARCH §12 itself only
# defines one severity for all of these (`BLOCKING`); this finer
# three-way split is purely an additive, best-effort ledger classification
# layered on top of it for `actionResults`/`action_results`, never a
# change to §12's own severities or to which codes are `EngineError`s.


def _action_ledger_status(code: str) -> str:
    if code in _ACTION_LEDGER_REFUSED_CODES:
        return "refused"
    if code in _ACTION_LEDGER_BLOCKED_CODES:
        return "blocked"
    return "failed"


def _is_action_list_document(doc: Any) -> bool:
    """`True` iff every element of a list-shaped `doc` is a non-empty
    dict naming an explicit `"action"` verb -- a *true* action-list
    document (see the module comment above `_run_ordered_action_list`).
    An empty list, an object-form `dict`, or a list mixing/only using
    field-list-form single-key elements (no `"action"` key at all) is
    `False` -- all three keep using `_run_steps`'s existing batch path
    unchanged, exactly as before this hardening cycle (a mixed document
    composing field-list and action-list elements in the same list --
    already supported and tested via `_normalize_scenario_doc` -- is
    deliberately routed there too, never split across both executors)."""
    return bool(doc) and isinstance(doc, list) and all(isinstance(e, dict) and "action" in e for e in doc)


def _run_ordered_action_list(
    conn, store: persistence.Store, ws, brief, raw_doc: list[Any], merged: dict[str, Any],
    actor: str, report: dict[str, Any], export_dir: Optional[Path], scenario_dir: Optional[Path] = None,
) -> None:
    """The true ordered executor for an action-list scenario document --
    see the module comment above for the root-cause rationale. `merged`
    (already computed by `run_scenario` via the unchanged
    `_normalize_scenario_doc`) is consulted here *only* for the handful of
    whole-document scalar/config fields that were always applied globally
    regardless of position even in `_run_steps`'s own batch walk --
    `evidenceDefaultDisposition`, `evidenceOverrides`, `autoAltText`,
    `skipDemos`, `stageApprover` (`actor`/`brief` are already resolved and
    applied by `run_scenario` itself before this function is even called)
    -- never for a domain-mutating field (`sources`, `claims`, ...): every
    one of those is instead read straight from `raw_doc`, one element at
    a time, in original order.

    Populates `report["actionResults"]`/`report["action_results"]`
    directly: one entry per `raw_doc` element (in order), each carrying
    at least `index` (that element's position), `action` (its own
    `"action"` verb, verbatim), `status`
    (`completed`/`refused`/`blocked`/`failed` -- see
    `_action_ledger_status`), and `ok` (`True` iff `status ==
    "completed"` -- the pre-existing boolean `_attach_action_results_
    ledger` itself always set, kept for full backward compatibility).
    A non-`completed` entry also carries `error` (the identical
    `{"code", "message", "details"}` shape `EngineError.to_dict()` always
    produces); a `completed` one carries whichever created/updated id(s)
    that action's own domain call produced. Also populates
    `report["steps"]`
    -- using the exact same rich, per-domain-effect shapes (`source.
    ingest`, `evidence.extract`, `claim.propose`, `claim.approve`,
    `narrative.select_throughline`, `narrative.select_route`, `compile`,
    `gate.run`, `rehearse.propose_cuts`) `_run_steps` itself already
    produces -- for full backward compatibility with every existing
    consumer of that field (`_attach_action_results_ledger` is a no-op
    once this function has already populated `actionResults` itself).

    A correctly-refused/blocked element raises the identical `EngineError`
    `_run_steps` would have (never a bypass), stopping the walk -- but the
    ledger entry for that one failing element (and, if the failure
    happened after the main per-action loop, a final `"scenario.tail"`
    entry one index past the last real element) is always appended
    first, so a caller reading `actionResults` sees a result for every
    element the walk actually attempted, success or failure, without
    cross-referencing `report["refusal"]` separately."""
    ledger: list[dict[str, Any]] = []
    report["actionResults"] = ledger
    report["action_results"] = ledger

    staging_dir = store.workspace_dir(ws.id) / "staging"
    sources_by_uri: dict[str, models.SourceArtifact] = {}
    atoms_by_locator: dict[str, models.EvidenceAtom] = {}
    atoms_by_uri_prefix: dict[str, list[models.EvidenceAtom]] = {}
    overrides = merged.get("evidenceOverrides", [])
    default_disposition = merged.get("evidenceDefaultDisposition", "KEEP")
    auto_alt_text = merged.get("autoAltText", True)
    skip_demos = merged.get("skipDemos", False)
    stage_approver = _coerce_named_approver_scalar(merged.get("stageApprover", actor), field_label="stageApprover")

    claim_objs: list[models.Claim] = []
    pending_throughline_drafts: list[str] = []
    pending_route_drafts: list[dict[str, Any]] = []
    all_throughlines: list[models.NarrativeThroughline] = []
    all_routes: list[models.NarrativeRoute] = []
    narrative_state: dict[str, Any] = {"throughline": None, "route": None, "slides": [], "compiled": False}
    timings_by_id: dict[str, float] = {}
    rehearsal_state: dict[str, Any] = {"requested": False, "total_seconds": None}

    # -- Narrative/route/compile: lazy, idempotent, "just in time" --------
    # (see the module comment above on why throughline/route proposal is
    # necessarily batched rather than dispatched one draft at a time).

    def _do_compile() -> None:
        if narrative_state["compiled"]:
            return
        narrative_state["slides"] = compiler.compile_deck(conn, ws.id, actor=actor)
        narrative_state["compiled"] = True
        report["steps"].append({"action": "compile", "slideCount": len(narrative_state["slides"])})
        # Unconditional, immediately after compile -- exactly like
        # `_run_steps`'s own fixed position (compile -> explicit
        # accessibility actions -> auto-fill) -- never deferred to
        # end-of-walk, so an explicit `run_gate`/`export`/`approve_stage`
        # action positioned before the *textual* end of the list still
        # sees every slide's alt text already resolved. Never overwrites
        # an already-set region (explicit `set_alt_text` actions, whether
        # they ran earlier via a lazy compile trigger or will run later
        # and simply overwrite this default -- `compiler.set_alt_text`
        # itself has no "already confirmed" guard, so last-write-wins
        # either way).
        if auto_alt_text:
            for s in narrative_state["slides"]:
                region = s.regions.get("visual")
                if region is not None and not region.alt_text:
                    compiler.set_alt_text(
                        conn, ws.id, s.id, "visual", f"Illustration for: {s.regions['headline'].text}",
                        confirmed_by=actor, actor=actor,
                    )

    def _select_throughline_now(request: dict[str, Any]) -> models.NarrativeThroughline:
        if narrative_state["throughline"] is not None:
            raise EngineError(
                "VALIDATION_ERROR",
                "a throughline has already been selected for this run -- propose any further "
                "candidates before selecting one",
                {},
            )
        if not all_throughlines:
            drafts = pending_throughline_drafts or narrative.default_throughline_drafts(brief)
            all_throughlines.extend(narrative.propose_throughlines(conn, ws.id, brief.id, drafts, actor=actor))
        selected = _resolve_throughline_selection(request, all_throughlines, conn, ws.id, actor)
        narrative_state["throughline"] = selected
        report["throughline"] = {
            "candidates": [{"id": t.id, "text": t.text, "origin": t.origin} for t in all_throughlines],
            "active": {"id": selected.id, "text": selected.text, "origin": selected.origin},
        }
        report["steps"].append({"action": "narrative.select_throughline", "throughlineId": selected.id})
        return selected

    def _ensure_throughline_selected() -> models.NarrativeThroughline:
        if narrative_state["throughline"] is None:
            _select_throughline_now({})
        return narrative_state["throughline"]

    def _select_route_now(request: dict[str, Any]) -> models.NarrativeRoute:
        if narrative_state["route"] is not None:
            raise EngineError(
                "VALIDATION_ERROR",
                "a route has already been selected for this run -- propose any further candidates "
                "before selecting one",
                {},
            )
        throughline = _ensure_throughline_selected()
        if not all_routes:
            resolved_route_drafts = pending_route_drafts
            if not resolved_route_drafts and sources_by_uri:
                fresh_claims = [persistence.get(conn, "claim", c.id, models.Claim) or c for c in claim_objs]
                resolved_route_drafts = narrative.default_route_drafts(brief, throughline, fresh_claims)
            all_routes.extend(narrative.propose_routes(conn, ws.id, throughline.id, resolved_route_drafts, actor=actor))
            # Persisted/reported immediately upon proposal -- before
            # selection below is even attempted -- so a later selection
            # failure (a bad `selectRouteIndex`/`selectRouteText`, or any
            # other refusal further down this same walk) never discards
            # these already-durably-persisted candidates from the
            # caller-visible report (Dark Factory hardening cycle 10,
            # acceptance pass 13). Overwritten immediately below on a
            # successful selection with the identical candidates plus the
            # now-active route; never re-proposed a second time (`all_
            # routes` is already non-empty on every subsequent call).
            report["route"] = {
                "candidates": [{"id": r.id, "label": r.label, "beatCount": len(r.beats)} for r in all_routes],
                "active": None,
            }
        selected = _resolve_route_selection(request, all_routes, conn, ws.id, actor)
        narrative_state["route"] = selected
        report["route"] = {
            "candidates": [{"id": r.id, "label": r.label, "beatCount": len(r.beats)} for r in all_routes],
            "active": {"id": selected.id, "label": selected.label},
        }
        report["steps"].append({"action": "narrative.select_route", "routeId": selected.id})
        _do_compile()
        return selected

    def _ensure_route_selected() -> models.NarrativeRoute:
        if narrative_state["route"] is None:
            _select_route_now({})
        return narrative_state["route"]

    def _ensure_compiled() -> list[models.SlideSpec]:
        _ensure_route_selected()
        if not narrative_state["compiled"]:
            _do_compile()
        return narrative_state["slides"]

    def _maybe_finalize_stage() -> None:
        """The mandatory automatic Stage gate + package export
        (unconditional once Stage passes, `_run_steps`'s own fixed final
        phase) -- re-triable, not "run exactly once": `gates.run_gate`
        is always safe to re-evaluate (its own docstring: "there is no
        explicit invalidation step, only re-evaluation"), so this simply
        does nothing further once `report["package"]` already exists.
        Called just before dispatching *any* explicit `export` action
        (whichever `target`) -- so that action's own, separately
        dispatched `package.export_package` call (via
        `_process_export_request`, which never skips or bypasses this
        one) still finds this automatic export as its own last-known-good
        exactly like it would if the automatic phase had run at its old,
        fixed *textual-last* position -- and again, idempotently, at
        end-of-walk for a document that never explicitly triggers it at
        all. `stage_approver` is already-resolved whole-document config
        (`merged`, above), never position-dependent, so calling this
        early is never a premature/guessed approver name."""
        if "package" in report:
            return
        stage_result = gates.run_gate(conn, ws.id, "stage", actor=stage_approver)
        report["stageGate"] = {"passed": stage_result.passed, "failedChecks": [models.to_jsonable(f) for f in stage_result.failed_checks]}
        if stage_result.passed:
            pkg = package.export_package(conn, ws.id, actor=stage_approver, export_dir_override=export_dir)
            report["package"] = {
                "exportDir": pkg["exportDir"], "manifestId": pkg["manifestId"],
                "deckId": pkg["deckId"], "advisories": pkg["advisories"], "artifactKinds": pkg["artifactKinds"],
            }

    # -- One action's own dispatch ----------------------------------------

    def _dispatch(field_name: str, field_value: Any, index: int, raw_payload: dict[str, Any]) -> dict[str, Any]:
        """Executes the single already-normalized contribution one
        action-list element made (`field_name`/`field_value`, from
        `_apply_action_list_entry` run against a fresh, single-element
        accumulator -- see the call site below) against the live
        connection, immediately. `raw_payload` is that same element's own
        original inline payload (its `entry`, minus `"action"`), used only
        to attach an auditable `rawDescriptor` to each `source.ingest`
        step below (Dark Factory hardening cycle 11, acceptance pass 14)
        -- never itself re-normalized or re-validated here. Returns
        whichever extra ledger fields (created/updated ids, ...) are
        relevant for this action; may raise `EngineError` exactly like
        the identical domain call already does."""
        if field_name in ("actor", "brief", "evidenceDefaultDisposition", "evidenceOverrides", "autoAltText", "skipDemos", "stageApprover"):
            # Whole-document config, already resolved once (`merged`,
            # above) and in effect for the entire walk regardless of this
            # element's own position -- nothing left to do but record
            # that this element ran.
            return {}

        if field_name == "sources":
            raw_descriptor = _redact_raw_source_descriptor(raw_payload)
            created_ids = []
            for src_payload in field_value:
                src_payload = _apply_add_source_local_defaults(src_payload, actor)
                source = ingest_mod.ingest_source(
                    conn, ws.id, src_payload, actor=actor, staging_dir=staging_dir, base_dir=scenario_dir,
                )
                sources_by_uri[source.uri] = source
                created_ids.append(source.id)
                ingest_step = {
                    "action": "source.ingest", "sourceId": source.id, "uri": source.uri, "state": source.state,
                    "origin": source.origin, "sourceType": source.source_type, "owner": source.owner,
                    "permissionState": source.permission_state, "sensitivityLabel": source.sensitivity_label,
                }
                if src_payload.get("title"):
                    ingest_step["title"] = src_payload["title"]
                ingest_step["rawDescriptor"] = raw_descriptor
                report["steps"].append(ingest_step)
                if source.state == models.SourceState.AUTHORIZED.value:
                    atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor=actor)
                    for atom in atoms:
                        disposition = _disposition_for(atom, source, overrides, default_disposition)
                        evidence_mod.set_disposition(conn, ws.id, atom.id, disposition, actor=actor)
                        atoms_by_locator[atom.locator] = atom
                        atoms_by_uri_prefix.setdefault(source.uri, []).append(atom)
                    report["steps"].append({"action": "evidence.extract", "sourceUri": source.uri, "atomCount": len(atoms)})
            return {"sourceIds": created_ids}

        if field_name in ("sourceRevocations", "sourceQuarantines", "sourceHoldResolutions", "sourceRetirements"):
            action_name, verb, step_action = {
                "sourceRevocations": ("revoke_source", None, "source.revoke"),
                "sourceQuarantines": ("quarantine_source", None, "source.quarantine"),
                "sourceHoldResolutions": ("resolve_source_hold", None, "source.resolve_hold"),
                "sourceRetirements": ("retire_source", None, "source.retire"),
            }[field_name]
            source_ids = []
            for req in field_value:
                if field_name == "sourceRevocations":
                    extra = sorted(set(req) - set(_SOURCE_LIFECYCLE_REFERENCE_FIELDS)) if isinstance(req, dict) else []
                    if extra:
                        raise EngineError(
                            "VALIDATION_ERROR", f"action 'revoke_source' at element {index} has unexpected field(s) {extra}",
                            {"index": index, "action": "revoke_source", "unexpectedFields": extra},
                        )
                    source_id = _resolve_source_lifecycle_target(conn, ws.id, req, sources_by_uri, "revoke_source", index)
                    source = ingest_mod.revoke_access(conn, ws.id, source_id, actor=actor)
                    report["steps"].append({"action": step_action, "sourceId": source.id, "uri": source.uri, "state": source.state})
                elif field_name == "sourceQuarantines":
                    allowed = set(_SOURCE_LIFECYCLE_REFERENCE_FIELDS) | {"reason"}
                    extra = sorted(set(req) - allowed) if isinstance(req, dict) else []
                    reason = req.get("reason") if isinstance(req, dict) else None
                    if extra or not isinstance(reason, str) or not reason.strip():
                        raise EngineError(
                            "VALIDATION_ERROR",
                            f"action 'quarantine_source' at element {index} requires a non-empty 'reason' "
                            f"field (unexpected field(s): {extra})",
                            {"index": index, "action": "quarantine_source", "unexpectedFields": extra},
                        )
                    source_id = _resolve_source_lifecycle_target(conn, ws.id, req, sources_by_uri, "quarantine_source", index)
                    source = ingest_mod.quarantine_source(conn, ws.id, source_id, actor=actor, reason=reason)
                    report["steps"].append({
                        "action": step_action, "sourceId": source.id, "uri": source.uri, "state": source.state, "reason": reason,
                    })
                elif field_name == "sourceHoldResolutions":
                    allowed = set(_SOURCE_LIFECYCLE_REFERENCE_FIELDS) | {"decision"}
                    extra = sorted(set(req) - allowed) if isinstance(req, dict) else []
                    decision = req.get("decision") if isinstance(req, dict) else None
                    if extra or decision not in ("authorize", "retire"):
                        raise EngineError(
                            "VALIDATION_ERROR",
                            f"action 'resolve_source_hold' at element {index} requires a 'decision' field "
                            f"of 'authorize' or 'retire' (unexpected field(s): {extra})",
                            {"index": index, "action": "resolve_source_hold", "unexpectedFields": extra, "decision": decision},
                        )
                    source_id = _resolve_source_lifecycle_target(conn, ws.id, req, sources_by_uri, "resolve_source_hold", index)
                    source = ingest_mod.resolve_hold(conn, ws.id, source_id, actor=actor, decision=decision)
                    report["steps"].append({
                        "action": step_action, "sourceId": source.id, "uri": source.uri, "state": source.state, "decision": decision,
                    })
                else:
                    extra = sorted(set(req) - set(_SOURCE_LIFECYCLE_REFERENCE_FIELDS)) if isinstance(req, dict) else []
                    if extra:
                        raise EngineError(
                            "VALIDATION_ERROR", f"action 'retire_source' at element {index} has unexpected field(s) {extra}",
                            {"index": index, "action": "retire_source", "unexpectedFields": extra},
                        )
                    source_id = _resolve_source_lifecycle_target(conn, ws.id, req, sources_by_uri, "retire_source", index)
                    source = ingest_mod.retire_source(conn, ws.id, source_id, actor=actor)
                    report["steps"].append({"action": step_action, "sourceId": source.id, "uri": source.uri, "state": source.state})
                sources_by_uri[source.uri] = source
                source_ids.append(source.id)
            return {"sourceIds": source_ids}

        if field_name == "claims":
            (claim_spec,) = field_value
            atom_ids: list[str] = []
            for loc in claim_spec.get("evidenceLocators", []):
                if loc in atoms_by_locator:
                    atom_ids.append(atoms_by_locator[loc].id)
                elif loc in atoms_by_uri_prefix:
                    atom_ids.extend(a.id for a in atoms_by_uri_prefix[loc])
            draft = {
                "type": claim_spec["type"], "text": claim_spec["text"], "evidenceAtomIds": atom_ids,
                "rationale": claim_spec.get("rationale"), "aspirationalLabel": claim_spec.get("aspirationalLabel"),
            }
            created = claims_mod.propose_claims(conn, ws.id, [draft], actor=actor)
            claim = created[0]
            claim_objs.append(claim)
            if claim_spec.get("approve"):
                # Immediate, not deferred: a later action in this same
                # list (an explicit `export`/`run_gate` naming `claims`/
                # `readiness`/`stage`, ...) is entitled to see this
                # claim's approval already in effect, exactly as it would
                # if a human had run `claim approve` right after `claim
                # propose` -- there is no separate "approve later" verb
                # this action-list vocabulary offers (`propose_claim`'s
                # own inline `approve` flag is the only way to request
                # it), so deferring it to end-of-walk could only ever
                # make a later, dependent action see a *less* approved
                # state than the caller's own sequence implies, never a
                # more faithful one.
                approver = _resolve_named_approver_alias(claim_spec, action="propose_claim", index=index, default=actor)
                claims_mod.approve_claim(conn, ws.id, claim.id, actor=approver)
                report["steps"].append({"action": "claim.approve", "claimId": claim.id})
            return {"claimId": claim.id}

        if field_name == "conflictDecisions":
            (cd,) = field_value
            claim = claim_objs[cd["claimIndex"]]
            open_conflicts = [
                c for c in persistence.list_all(conn, "conflict", ws.id, models.ConflictCard)
                if c.claim_id == claim.id and c.status == models.ConflictStatus.OPEN.value
            ]
            conflict_ids = []
            for card in open_conflicts:
                claims_mod.resolve_conflict(conn, ws.id, card.id, cd.get("decision", "resolved by scenario"), actor=actor)
                conflict_ids.append(card.id)
            return {"conflictIds": conflict_ids}

        if field_name == "throughlineDrafts":
            (draft_text,) = field_value
            pending_throughline_drafts.append(draft_text)
            return {}

        if field_name in ("customThroughline", "selectThroughlineIndex", "selectThroughlineText"):
            selected = _select_throughline_now({field_name: field_value})
            return {"throughlineId": selected.id}

        if field_name == "routeDrafts":
            (rd,) = field_value
            beats = []
            for b in rd.get("beats", []):
                b2 = dict(b)
                b2["claimIds"] = [claim_objs[i].id for i in b.get("claimIds", [])]
                beats.append(b2)
            pending_route_drafts.append({"label": rd.get("label", ""), "beats": beats})
            return {}

        if field_name in ("selectRouteIndex", "selectRouteText"):
            selected = _select_route_now({field_name: field_value})
            return {"routeId": selected.id}

        if field_name == "compileRequested":
            slides = _ensure_compiled()
            return {"slideCount": len(slides)}

        if field_name == "accessibility":
            (acc,) = field_value
            slides = _ensure_compiled()
            slide = _match_slide(acc, slides)
            if slide is None:
                return {"matched": False}
            compiler.set_alt_text(
                conn, ws.id, slide.id, acc.get("region", "visual"), acc.get("altText", "Descriptive alt text"),
                confirmed_by=acc.get("confirmedBy", actor), actor=actor,
            )
            return {"slideId": slide.id}

        if field_name == "demoAssets":
            (da,) = field_value
            slides = _ensure_compiled()
            slide = _match_slide(da, slides)
            if slide is None:
                return {"matched": False}
            compiler.set_demo_asset(
                conn, ws.id, slide.id, actor=actor, live_path=da.get("livePath"),
                prerecorded_asset_path=da.get("prerecordedAssetPath"), static_asset_path=da.get("staticAssetPath"),
                verbal_recovery_script=da.get("verbalRecoveryScript"),
            )
            return {"slideId": slide.id}

        if field_name == "rehearsalTimings":
            slides = _ensure_compiled()
            rehearsal_state["requested"] = True
            matched_ids: dict[str, float] = {}
            for key, seconds in field_value.items():
                slide = _resolve_rehearsal_slide(key, slides)
                if slide is not None:
                    timings_by_id[slide.id] = seconds
                    matched_ids[slide.id] = seconds
            return {"timings": matched_ids} if matched_ids else {"matched": False}

        if field_name == "rehearsalRunRequested":
            _ensure_compiled()
            rehearsal_state["requested"] = True
            return {}

        if field_name == "rehearsalTotalActualSeconds":
            _ensure_compiled()
            rehearsal_state["requested"] = True
            rehearsal_state["total_seconds"] = field_value
            return {}

        if field_name == "rehearsalCutsTargetSeconds":
            slides = _ensure_compiled()
            target_seconds = int(round(field_value))
            proposed_cuts = compiler.propose_cuts(conn, ws.id, target_seconds)
            report["rehearsal"] = report.get("rehearsal") or {}
            report["rehearsal"]["cutsTargetSeconds"] = target_seconds
            report["rehearsal"]["proposedCuts"] = proposed_cuts
            report["steps"].append({"action": "rehearse.propose_cuts", "targetSeconds": target_seconds, "cutCount": len(proposed_cuts)})
            return {"cutCount": len(proposed_cuts)}

        if field_name == "qaPairs":
            (qa,) = field_value
            claim_indices = qa.get("claimIndices") or qa.get("claim_indices") or []
            claim_ids = [claim_objs[i].id for i in claim_indices]
            qa_result = rehearsal.record_qa(conn, ws.id, [{"question": qa["question"], "answer": qa.get("answer", ""), "claimIds": claim_ids}], actor=actor)
            report.setdefault("qa", []).extend(qa_result)
            return {"grounded": qa_result[0]["grounding"]["allGrounded"]} if qa_result else {}

        if field_name == "gateRuns":
            (gr_entry,) = field_value
            extra = sorted(set(gr_entry) - _GATE_RUN_ALLOWED_FIELDS)
            name_values = {gr_entry[k] for k in _GATE_RUN_NAME_FIELDS if k in gr_entry}
            gate_name = next(iter(name_values)) if len(name_values) == 1 else None
            if len(name_values) > 1 or not isinstance(gate_name, str) or not gate_name.strip() or extra:
                raise EngineError(
                    "VALIDATION_ERROR",
                    "action 'run_gate' requires exactly one non-empty \"gate\" field (or \"gateName\"/"
                    f"\"gate_name\" alias) naming the gate to run (unexpected field(s): {extra})",
                    {"gate": gate_name, "unexpectedFields": extra},
                )
            gate_actor = _resolve_named_approver_alias(gr_entry, action="run_gate", index=index, default=actor)
            gate_result = gates.run_gate(conn, ws.id, gate_name, actor=gate_actor)
            report["steps"].append({"action": "gate.run", "gate": gate_name, "passed": gate_result.passed})
            return {"gate": gate_name, "passed": gate_result.passed}

        if field_name == "exportRequests":
            (export_request,) = field_value
            _maybe_finalize_stage()
            result = _process_export_request(conn, ws, export_request, stage_approver, export_dir, index)
            report.setdefault("exports", []).append(result)
            return {k: v for k, v in result.items() if k in ("target", "path", "exportDir", "manifestId", "deckId")}

        raise AssertionError(f"unreachable: unhandled action-list field {field_name!r}")  # pragma: no cover

    # -- Main walk: dispatch every element, in original order, immediately -
    for index, entry in enumerate(raw_doc):
        action = entry.get("action")
        raw_payload = {k: v for k, v in entry.items() if k != "action"}
        is_source_action = action in ("add_source", "ingest_source")
        try:
            scratch: dict[str, Any] = {}
            _apply_action_list_entry(scratch, entry, index)
            (field_name, field_value), = scratch.items()
            ids = _dispatch(field_name, field_value, index, raw_payload)
        except EngineError as exc:
            fail_entry = {
                "index": index, "action": action, "status": _action_ledger_status(exc.code),
                "ok": False, "error": exc.to_dict(),
            }
            if is_source_action:
                # Dark Factory hardening cycle 11 (acceptance pass 14):
                # preserved even for a refused/blocked attempt -- a
                # source action's outcome (accepted, held, or blocked)
                # must never silently drop its own original descriptor
                # from the auditable ledger.
                fail_entry["rawPayload"] = _redact_raw_source_descriptor(raw_payload)
            ledger.append(fail_entry)
            raise
        ok_entry = {"index": index, "action": action, "status": "completed", "ok": True, **(ids or {})}
        if is_source_action:
            ok_entry["rawPayload"] = _redact_raw_source_descriptor(raw_payload)
        ledger.append(ok_entry)

    # -- End-of-walk tail: identical to `_run_steps`'s own unconditional --
    # automatic phases, just reached after every explicit action instead
    # of a fixed position -- never skipped, and never re-ordering
    # anything an explicit action already did above.
    try:
        report["steps"].append({"action": "claim.propose", "count": len(claim_objs)})

        _ensure_compiled()

        pre_gates = {}
        for gate_name in ("scope", "evidence", "narrative", "claims", "readiness"):
            gr = gates.run_gate(conn, ws.id, gate_name, actor=actor)
            pre_gates[gate_name] = {"passed": gr.passed, "failedChecks": [models.to_jsonable(f) for f in gr.failed_checks]}
        report["preStageGates"] = pre_gates

        if rehearsal_state["requested"]:
            final_timings = timings_by_id
            if rehearsal_state["total_seconds"] is not None:
                final_timings = rehearsal.distribute_total_duration(narrative_state["slides"], rehearsal_state["total_seconds"])
            rehearsal_report = rehearsal.run_rehearsal(conn, ws.id, final_timings, actor=actor, skip_demos=skip_demos)
            report["rehearsal"] = {**rehearsal_report, **(report.get("rehearsal") or {})}

        _maybe_finalize_stage()
    except EngineError as exc:
        ledger.append({
            "index": len(raw_doc), "action": "scenario.tail", "status": _action_ledger_status(exc.code),
            "ok": False, "error": exc.to_dict(),
        })
        raise


def _run_steps(
    conn, store: persistence.Store, ws, brief, doc: dict[str, Any], actor: str, report: dict[str, Any],
    export_dir: Optional[Path], scenario_dir: Optional[Path] = None,
    add_source_scope: Optional[set[int]] = None,
) -> None:
    """The one-pass, declarative walk (workspace/brief already created) —
    kept separate from `run_scenario` so the whole walk is covered by one
    `try/except EngineError` there without deeply nesting every step.

    `add_source_scope` (Dark Factory hardening cycle 13, optional --
    every existing caller that never passes it behaves identically to
    before) is the identity set `run_scenario` builds during
    normalization (see `_apply_action_list_entry`): `doc["sources"]` may
    mix items that came through this module's own add_source/
    ingest_source normalization with raw, directly-documented
    `{"sources": [...]}` field entries that never did (a mixed field-
    list/action-list document keeps using this exact batch path -- see
    `_is_action_list_document`'s own docstring) -- only the former are
    eligible for `_apply_add_source_local_defaults`'s further
    sourceType/owner/permissionState defaults."""
    staging_dir = store.workspace_dir(ws.id) / "staging"
    atoms_by_locator: dict[str, models.EvidenceAtom] = {}
    atoms_by_uri_prefix: dict[str, list[models.EvidenceAtom]] = {}
    sources_by_uri: dict[str, models.SourceArtifact] = {}
    overrides = doc.get("evidenceOverrides", [])
    default_disposition = doc.get("evidenceDefaultDisposition", "KEEP")

    for src_payload in doc.get("sources", []):
        if add_source_scope is not None and id(src_payload) in add_source_scope:
            src_payload = _apply_add_source_local_defaults(src_payload, actor)
        source = ingest_mod.ingest_source(
            conn, ws.id, src_payload, actor=actor, staging_dir=staging_dir, base_dir=scenario_dir,
        )
        sources_by_uri[source.uri] = source
        # A richer per-source step entry than just uri/state -- the full
        # canonical ledger metadata (id/origin/sourceType/owner/
        # permissionState/sensitivityLabel) plus a passthrough `title`
        # (never a modeled `SourceArtifact` field -- see
        # `docs/data-model.md`'s `SourceArtifact` entity -- but still
        # surfaced here from the caller's own descriptor, never silently
        # dropped) so a scenario's own "source-add results" are directly
        # observable per step, not just discoverable by re-querying the
        # accumulated ledger (`report["sources"]`, attached below by
        # `_attach_workspace_state` regardless of how the walk ends).
        ingest_step = {
            "action": "source.ingest", "sourceId": source.id, "uri": source.uri, "state": source.state,
            "origin": source.origin, "sourceType": source.source_type, "owner": source.owner,
            "permissionState": source.permission_state, "sensitivityLabel": source.sensitivity_label,
        }
        if src_payload.get("title"):
            ingest_step["title"] = src_payload["title"]
        report["steps"].append(ingest_step)
        if source.state == models.SourceState.AUTHORIZED.value:
            atoms = evidence_mod.extract_evidence(conn, ws.id, source.id, actor=actor)
            for atom in atoms:
                disposition = _disposition_for(atom, source, overrides, default_disposition)
                evidence_mod.set_disposition(conn, ws.id, atom.id, disposition, actor=actor)
                atoms_by_locator[atom.locator] = atom
                atoms_by_uri_prefix.setdefault(source.uri, []).append(atom)
            report["steps"].append({"action": "evidence.extract", "sourceUri": source.uri, "atomCount": len(atoms)})

    # `revoke_source`/`quarantine_source`/`resolve_source_hold`/
    # `retire_source` (Dark Factory hardening cycle 7): explicit source-
    # lifecycle transitions (FR-SRC-5/FR-SRC-6), reachable through the
    # scenario/action-list interface through the identical, already-
    # existing `ingest.revoke_access`/`ingest.quarantine_source`/
    # `ingest.resolve_hold`/`ingest.retire_source` calls the CLI's own
    # granular `source` subcommands use -- never a second lifecycle code
    # path, and never a bypass of any of their existing state-machine
    # checks (e.g. `resolve_source_hold` on a source that isn't currently
    # held still raises the identical, pre-existing `VALIDATION_ERROR`).
    # Purely additive: none of these run unless the scenario document
    # explicitly requests them.
    for idx, req in enumerate(doc.get("sourceRevocations", [])):
        extra = sorted(set(req) - set(_SOURCE_LIFECYCLE_REFERENCE_FIELDS)) if isinstance(req, dict) else []
        if extra:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'revoke_source' at element {idx} has unexpected field(s) {extra}",
                {"index": idx, "action": "revoke_source", "unexpectedFields": extra},
            )
        source_id = _resolve_source_lifecycle_target(conn, ws.id, req, sources_by_uri, "revoke_source", idx)
        source = ingest_mod.revoke_access(conn, ws.id, source_id, actor=actor)
        sources_by_uri[source.uri] = source
        report["steps"].append({
            "action": "source.revoke", "sourceId": source.id, "uri": source.uri, "state": source.state,
        })

    for idx, req in enumerate(doc.get("sourceQuarantines", [])):
        allowed = set(_SOURCE_LIFECYCLE_REFERENCE_FIELDS) | {"reason"}
        extra = sorted(set(req) - allowed) if isinstance(req, dict) else []
        reason = req.get("reason") if isinstance(req, dict) else None
        if extra or not isinstance(reason, str) or not reason.strip():
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'quarantine_source' at element {idx} requires a non-empty 'reason' field "
                f"(unexpected field(s): {extra})",
                {"index": idx, "action": "quarantine_source", "unexpectedFields": extra},
            )
        source_id = _resolve_source_lifecycle_target(conn, ws.id, req, sources_by_uri, "quarantine_source", idx)
        source = ingest_mod.quarantine_source(conn, ws.id, source_id, actor=actor, reason=reason)
        sources_by_uri[source.uri] = source
        report["steps"].append({
            "action": "source.quarantine", "sourceId": source.id, "uri": source.uri, "state": source.state,
            "reason": reason,
        })

    for idx, req in enumerate(doc.get("sourceHoldResolutions", [])):
        allowed = set(_SOURCE_LIFECYCLE_REFERENCE_FIELDS) | {"decision"}
        extra = sorted(set(req) - allowed) if isinstance(req, dict) else []
        decision = req.get("decision") if isinstance(req, dict) else None
        if extra or decision not in ("authorize", "retire"):
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'resolve_source_hold' at element {idx} requires a 'decision' field of "
                f"'authorize' or 'retire' (unexpected field(s): {extra})",
                {"index": idx, "action": "resolve_source_hold", "unexpectedFields": extra, "decision": decision},
            )
        source_id = _resolve_source_lifecycle_target(conn, ws.id, req, sources_by_uri, "resolve_source_hold", idx)
        source = ingest_mod.resolve_hold(conn, ws.id, source_id, actor=actor, decision=decision)
        sources_by_uri[source.uri] = source
        report["steps"].append({
            "action": "source.resolve_hold", "sourceId": source.id, "uri": source.uri, "state": source.state,
            "decision": decision,
        })

    for idx, req in enumerate(doc.get("sourceRetirements", [])):
        extra = sorted(set(req) - set(_SOURCE_LIFECYCLE_REFERENCE_FIELDS)) if isinstance(req, dict) else []
        if extra:
            raise EngineError(
                "VALIDATION_ERROR",
                f"action 'retire_source' at element {idx} has unexpected field(s) {extra}",
                {"index": idx, "action": "retire_source", "unexpectedFields": extra},
            )
        source_id = _resolve_source_lifecycle_target(conn, ws.id, req, sources_by_uri, "retire_source", idx)
        source = ingest_mod.retire_source(conn, ws.id, source_id, actor=actor)
        sources_by_uri[source.uri] = source
        report["steps"].append({
            "action": "source.retire", "sourceId": source.id, "uri": source.uri, "state": source.state,
        })

    claim_objs: list[models.Claim] = []
    for claim_spec in doc.get("claims", []):
        atom_ids: list[str] = []
        for loc in claim_spec.get("evidenceLocators", []):
            if loc in atoms_by_locator:
                atom_ids.append(atoms_by_locator[loc].id)
            elif loc in atoms_by_uri_prefix:
                # Fixture convenience: a bare source URI (no "#pN" suffix)
                # pulls in every paragraph-atom extracted from it.
                atom_ids.extend(a.id for a in atoms_by_uri_prefix[loc])
        draft = {
            "type": claim_spec["type"], "text": claim_spec["text"], "evidenceAtomIds": atom_ids,
            "rationale": claim_spec.get("rationale"), "aspirationalLabel": claim_spec.get("aspirationalLabel"),
        }
        created = claims_mod.propose_claims(conn, ws.id, [draft], actor=actor)
        claim_objs.append(created[0])
    report["steps"].append({"action": "claim.propose", "count": len(claim_objs)})

    for cd in doc.get("conflictDecisions", []):
        claim = claim_objs[cd["claimIndex"]]
        open_conflicts = [
            c for c in persistence.list_all(conn, "conflict", ws.id, models.ConflictCard)
            if c.claim_id == claim.id and c.status == models.ConflictStatus.OPEN.value
        ]
        for card in open_conflicts:
            claims_mod.resolve_conflict(conn, ws.id, card.id, cd.get("decision", "resolved by scenario"), actor=actor)

    for claim_index, (claim_spec, claim) in enumerate(zip(doc.get("claims", []), claim_objs)):
        if claim_spec.get("approve"):
            claim_approver = _resolve_named_approver_alias(claim_spec, action="propose_claim", index=claim_index, default=actor)
            claims_mod.approve_claim(conn, ws.id, claim.id, actor=claim_approver)
            report["steps"].append({"action": "claim.approve", "claimId": claim.id})

    # FR-NAR-1: a scenario that doesn't stage its own drafts (no
    # `throughlineDrafts`/`propose_throughline` entries at all -- the
    # normal case for a "just run a valid proposal flow" scenario) still
    # deterministically gets exactly three real, brief-derived candidates
    # via `narrative.default_throughline_drafts`, the same helper
    # `cli.py`'s direct `narrative propose-throughlines` command falls
    # back to -- never an empty list, and never a fixed placeholder.
    throughline_drafts = doc.get("throughlineDrafts") or narrative.default_throughline_drafts(brief)
    throughlines = narrative.propose_throughlines(conn, ws.id, brief.id, throughline_drafts, actor=actor)
    selected_throughline = _resolve_throughline_selection(doc, throughlines, conn, ws.id, actor)
    report["steps"].append({"action": "narrative.select_throughline", "throughlineId": selected_throughline.id})
    # Persisted into the report immediately -- before routes/compile/gates
    # get a chance to refuse further down -- so the three proposed
    # candidates and whichever one is active (including a speaker-authored
    # replacement, `origin: "custom"`) are always discoverable in the
    # result document even when a later step is correctly refused/blocked
    # (`report` is mutated in place, so this survives an `EngineError`
    # raised anywhere after this point; see `run_scenario`'s docstring).
    report["throughline"] = {
        "candidates": [{"id": t.id, "text": t.text, "origin": t.origin} for t in throughlines],
        "active": {"id": selected_throughline.id, "text": selected_throughline.text, "origin": selected_throughline.origin},
    }

    resolved_route_drafts = []
    for rd in doc.get("routeDrafts", []):
        beats = []
        for b in rd.get("beats", []):
            b2 = dict(b)
            b2["claimIds"] = [claim_objs[i].id for i in b.get("claimIds", [])]
            beats.append(b2)
        resolved_route_drafts.append({"label": rd.get("label", ""), "beats": beats})
    if not resolved_route_drafts and sources_by_uri:
        # FR-NAR-3 mirrors the throughline fallback above, but only for a
        # genuinely *source-driven* scenario (see FR-NAR-3, "the skill
        # proposes two or three narrative routes"): at least one source
        # was actually ingested in this same run. A bare brief with no
        # source context at all still gets no default routes here and is
        # correctly refused for missing routes exactly as before --
        # `tests/test_candidate_persistence_on_refusal.py` and
        # `tests/test_default_throughline_generation.py`'s own
        # `ScenarioRunnerDefaultGenerationTests` both pin that pre-existing
        # brief-only behavior, which this never changes. Claim eligibility
        # (for an optional cited PROOF beat) is checked against each
        # claim's *current*, freshly-reloaded state/approver -- `claim_objs`
        # itself still holds each claim's pre-approval snapshot, since
        # `claims_mod.approve_claim` mutates its own freshly-loaded copy,
        # never the caller's list in place.
        fresh_claims = [persistence.get(conn, "claim", c.id, models.Claim) or c for c in claim_objs]
        resolved_route_drafts = narrative.default_route_drafts(brief, selected_throughline, fresh_claims)
    routes = narrative.propose_routes(conn, ws.id, selected_throughline.id, resolved_route_drafts, actor=actor)
    selected_route = _resolve_route_selection(doc, routes, conn, ws.id, actor)
    report["steps"].append({"action": "narrative.select_route", "routeId": selected_route.id})
    # Persisted immediately, exactly like `report["throughline"]` above,
    # so the proposed route candidates and whichever one is active always
    # survive a later compile/gate refusal.
    report["route"] = {
        "candidates": [{"id": r.id, "label": r.label, "beatCount": len(r.beats)} for r in routes],
        "active": {"id": selected_route.id, "label": selected_route.label},
    }

    slides = compiler.compile_deck(conn, ws.id, actor=actor)
    report["steps"].append({"action": "compile", "slideCount": len(slides)})

    for acc in doc.get("accessibility", []):
        slide = _match_slide(acc, slides)
        if slide is not None:
            compiler.set_alt_text(conn, ws.id, slide.id, acc.get("region", "visual"), acc.get("altText", "Descriptive alt text"), confirmed_by=acc.get("confirmedBy", actor), actor=actor)
    if doc.get("autoAltText", True):
        for s in slides:
            region = s.regions.get("visual")
            if region is not None and not region.alt_text:
                compiler.set_alt_text(conn, ws.id, s.id, "visual", f"Illustration for: {s.regions['headline'].text}", confirmed_by=actor, actor=actor)

    for da in doc.get("demoAssets", []):
        slide = _match_slide(da, slides)
        if slide is not None:
            compiler.set_demo_asset(
                conn, ws.id, slide.id, actor=actor, live_path=da.get("livePath"),
                prerecorded_asset_path=da.get("prerecordedAssetPath"), static_asset_path=da.get("staticAssetPath"),
                verbal_recovery_script=da.get("verbalRecoveryScript"),
            )

    # `run_gate` (action-list verb) explicitly, additionally invokes one
    # named gate through the existing `gates.run_gate` logic -- purely
    # additive: it never replaces, skips, or reorders the mandatory
    # automatic gate pipeline immediately below, which always runs
    # regardless of whether any `gateRuns` entries were given (re-running
    # a gate is always safe -- gates.py's own docstring: "there is no
    # explicit invalidation step, only re-evaluation"). Each entry's
    # inline payload must be exactly one non-empty string gate-name field
    # -- `gate` (documented/canonical), or the `gateName`/`gate_name`
    # aliases (one of scope|evidence|narrative|claims|readiness|stage);
    # it may additionally name who performs *that* gate run via the
    # shared named-approver alias vocabulary (Dark Factory hardening
    # cycle 9, acceptance pass 12 -- `_resolve_named_approver_alias`),
    # falling back to the whole-document `actor` exactly as before when
    # none is given. A missing/blank/non-string gate name, conflicting
    # alias values (gate-name *or* approver), or an unexpected extra
    # field is a clean `VALIDATION_ERROR` here, and an unrecognized gate
    # name is the identical `VALIDATION_ERROR` `gates.run_gate` already
    # raises for a direct `gate run <name>` CLI call -- never a
    # duplicated check.
    for gr_index, gr_entry in enumerate(doc.get("gateRuns", [])):
        extra = sorted(set(gr_entry) - _GATE_RUN_ALLOWED_FIELDS)
        name_values = {gr_entry[k] for k in _GATE_RUN_NAME_FIELDS if k in gr_entry}
        gate_name = next(iter(name_values)) if len(name_values) == 1 else None
        if len(name_values) > 1 or not isinstance(gate_name, str) or not gate_name.strip() or extra:
            raise EngineError(
                "VALIDATION_ERROR",
                "action 'run_gate' requires exactly one non-empty \"gate\" field (or \"gateName\"/"
                f"\"gate_name\" alias) naming the gate to run (unexpected field(s): {extra})",
                {"gate": gate_name, "unexpectedFields": extra},
            )
        gate_actor = _resolve_named_approver_alias(gr_entry, action="run_gate", index=gr_index, default=actor)
        gate_result = gates.run_gate(conn, ws.id, gate_name, actor=gate_actor)
        report["steps"].append({"action": "gate.run", "gate": gate_name, "passed": gate_result.passed})

    pre_gates = {}
    for gate_name in ("scope", "evidence", "narrative", "claims", "readiness"):
        gr = gates.run_gate(conn, ws.id, gate_name, actor=actor)
        pre_gates[gate_name] = {"passed": gr.passed, "failedChecks": [models.to_jsonable(f) for f in gr.failed_checks]}
    report["preStageGates"] = pre_gates

    # `rehearse`'s widened vocabulary (see the module comment above
    # `_apply_rehearse_entry`) can request a rehearsal pass via a
    # per-slide/bulk `rehearsalTimings` mapping, an aggregate
    # `rehearsalTotalActualSeconds` (allocated proportionally to each
    # slide's own time budget -- `rehearsal.distribute_total_duration`),
    # or a bare `rehearsalRunRequested` marker (no timing at all -- run
    # anyway, purely so FR-M365-4's `sourceChanges` still reports). Any
    # one of the three is enough to trigger a pass; combining an explicit
    # per-slide/bulk mapping with an aggregate total is already rejected
    # as ambiguous at normalization time (`_apply_rehearsal_total_entry`/
    # `_apply_rehearsal_timing_entry`), so at most one of the first two
    # branches below ever actually contributes timings.
    if doc.get("rehearsalTimings") or doc.get("rehearsalRunRequested") or "rehearsalTotalActualSeconds" in doc:
        timings_by_id = {}
        for key, seconds in doc.get("rehearsalTimings", {}).items():
            slide = _resolve_rehearsal_slide(key, slides)
            if slide is not None:
                timings_by_id[slide.id] = seconds
        if "rehearsalTotalActualSeconds" in doc:
            timings_by_id = rehearsal.distribute_total_duration(slides, doc["rehearsalTotalActualSeconds"])
        rehearsal_report = rehearsal.run_rehearsal(conn, ws.id, timings_by_id, actor=actor, skip_demos=doc.get("skipDemos", False))
        report["rehearsal"] = rehearsal_report

    # `rehearse`'s cuts/shorter-variant sub-shape (FR-DEL-3): feeds the
    # existing `compiler.propose_cuts` contract and records the proposed
    # beat ids alongside whatever rehearsal timing report already exists
    # (or a fresh, timing-less entry if no timing was requested at all --
    # "do not require timing when the action only requests a supported
    # rehearsal subfeature").
    if "rehearsalCutsTargetSeconds" in doc:
        target_seconds = int(round(doc["rehearsalCutsTargetSeconds"]))
        proposed_cuts = compiler.propose_cuts(conn, ws.id, target_seconds)
        report["rehearsal"] = report.get("rehearsal") or {}
        report["rehearsal"]["cutsTargetSeconds"] = target_seconds
        report["rehearsal"]["proposedCuts"] = proposed_cuts
        report["steps"].append({"action": "rehearse.propose_cuts", "targetSeconds": target_seconds, "cutCount": len(proposed_cuts)})

    for qa in doc.get("qaPairs", []):
        claim_indices = qa.get("claimIndices") or qa.get("claim_indices") or []
        claim_ids = [claim_objs[i].id for i in claim_indices]
        qa_result = rehearsal.record_qa(conn, ws.id, [{"question": qa["question"], "answer": qa.get("answer", ""), "claimIds": claim_ids}], actor=actor)
        report.setdefault("qa", []).extend(qa_result)

    stage_actor = _coerce_named_approver_scalar(doc.get("stageApprover", actor), field_label="stageApprover")
    stage_result = gates.run_gate(conn, ws.id, "stage", actor=stage_actor)
    report["stageGate"] = {"passed": stage_result.passed, "failedChecks": [models.to_jsonable(f) for f in stage_result.failed_checks]}

    if stage_result.passed:
        pkg = package.export_package(conn, ws.id, actor=stage_actor, export_dir_override=export_dir)
        report["package"] = {
            "exportDir": pkg["exportDir"], "manifestId": pkg["manifestId"],
            "deckId": pkg["deckId"], "advisories": pkg["advisories"], "artifactKinds": pkg["artifactKinds"],
        }

    # The public `export` action-list verb (ARCH's `export pptx`/`export
    # package`): each `exportRequests` entry is one explicit request,
    # dispatched through the identical, already-existing
    # `package.export_pptx_draft`/`package.export_package` calls the CLI's
    # own `export pptx`/`export package` subcommands use -- never a second
    # export code path. A `target: "package"` request always re-runs the
    # real Stage gate itself (inside `package.export_package`); if Stage
    # has not passed, that call raises its own pre-existing
    # `GATE_NOT_PASSED` `EngineError`, propagating out of `_run_steps` to
    # `run_scenario`'s own `except EngineError` handler exactly like any
    # other domain refusal -- a structured `report["refusal"]`, exit 0,
    # never a bypassed gate and never a silent no-op.
    for idx, export_request in enumerate(doc.get("exportRequests", [])):
        result = _process_export_request(conn, ws, export_request, stage_actor, export_dir, idx)
        report.setdefault("exports", []).append(result)

