"""Sole source of user-facing product-name text (FR-INV-2, NFR-1).

Every user-facing string emitted anywhere in the Engine — CLI help text,
error messages, generated slide/notes content, exported documents — must
route through this module's constants/templates rather than spelling the
product name inline. This gives the whole codebase exactly one place to
audit for the "GitHub Copilot Throughline" / "GitHub Copilot" naming rule:
a bare "Copilot" not preceded by "GitHub" is never acceptable output.

Tests assert this mechanically (see tests/test_strings.py and the
NFR-1 scan test) by grepping all engine-emitted text for the forbidden
pattern.
"""
from __future__ import annotations

import re

# The two and only two acceptable renderings of the product name.
PRODUCT_NAME = "GitHub Copilot Throughline"
PRODUCT_SHORT = "GitHub Copilot"

# Regex used by tests (and importable by the CLI itself for self-checks) to
# detect a bare "Copilot" that is NOT part of "GitHub Copilot...".
_BARE_COPILOT_RE = re.compile(r"(?<!GitHub )Copilot")


def assert_compliant(text: str) -> None:
    """Raise ValueError if `text` contains a bare 'Copilot' reference.

    This is a defensive, structural guard: any new message added to the
    engine that forgets to route through this module will fail loudly in
    tests rather than silently shipping a bare "Copilot" reference.
    """
    for match in _BARE_COPILOT_RE.finditer(text):
        start = max(0, match.start() - 12)
        end = min(len(text), match.end() + 12)
        raise ValueError(
            f"Bare 'Copilot' reference detected near: ...{text[start:end]}..."
        )


def is_compliant(text: str) -> bool:
    return _BARE_COPILOT_RE.search(text) is None


# ---------------------------------------------------------------------------
# Message templates. Every engine-emitted human-readable string should be
# built from one of these, so a naming-policy audit is a single grep away.
# ---------------------------------------------------------------------------

WELCOME_NEW_WORKSPACE = (
    f"{PRODUCT_NAME} opened a new talk workspace. "
    "Let's capture your talk brief: audience, event/session type, duration, "
    "takeaway, required proof points, excluded topics, and tone."
)

WELCOME_RESUMED_WORKSPACE = (
    f"{PRODUCT_NAME} resumed your open talk workspace at phase '{{phase}}'. "
    "Next required action: {next_action}"
)

SOURCE_UNAUTHORIZED = (
    "Source '{source_ref}' is not authorized for the current user. "
    f"{PRODUCT_NAME} only ever retrieves sources you can already open with "
    "your own permissions."
)

BUNDLE_LIMIT_REACHED = (
    "The curated source bundle already holds 25 artifacts, the maximum "
    f"{PRODUCT_NAME} supports per talk. Remove a source before adding another."
)

FILE_TOO_LARGE = (
    "'{filename}' exceeds the {max_size} limit for {category} files and was "
    "not added to the bundle."
)

UNSUPPORTED_FILE_TYPE = (
    "'{filename}' has an unsupported file type for {category}. "
    "Accepted extensions: {accepted}."
)

LABEL_CONFLICT = (
    "Source '{source_ref}' carries conflicting sensitivity labels "
    "({labels}) and is held until you resolve the conflict. It will not "
    "produce evidence atoms until then."
)

PARSE_FAILED = (
    "Source '{source_ref}' could not be parsed ({reason}) and is held "
    "until resolved. It will not produce evidence atoms until then."
)

CLAIM_UNSUPPORTED = (
    "Stage-ready export was refused: {count} factual claim(s) are "
    "UNSUPPORTED. Add verified evidence or revise: {claim_ids}."
)

NARRATIVE_GATE_FAILED = (
    "Slide compilation is blocked: the narrative gate failed rule "
    "'{rule}'. {detail}"
)

ACCESS_REVOKED = (
    "Evidence atom '{atom_id}' lost access to its source and is now "
    "ACCESS_REVOKED. Slides citing it are reopened for review."
)

SOURCE_STALE = (
    "Source '{source_ref}' is now STALE ({reason}). Dependent evidence and "
    "claims are flagged for revalidation."
)

CONFLICT_UNRESOLVED = (
    "Claim '{claim_id}' has contradictory evidence from '{source_a}' and "
    "'{source_b}'. A conflict card was created and the claim stays "
    "blocked until you record a decision."
)

DEMO_FALLBACK_MISSING = (
    "Readiness failed for slide '{slide_id}': the demo is missing its "
    "'{missing_path}' fallback path."
)

ACCESSIBILITY_CHECK_FAILED = (
    "Readiness failed for slide '{slide_id}': the '{check}' accessibility "
    "check did not pass."
)

STAGE_APPROVER_REQUIRED = (
    "Stage approval requires a named human approver. The workspace remains "
    "at the Readiness gate."
)

UNMATCHED_CONTENT = (
    "Re-imported text did not match any known region and was placed in "
    "the unmatched-content list for manual linking."
)

WORKSPACE_ALREADY_ACTIVE = (
    f"Another {PRODUCT_NAME} workspace is already active (id={{workspace_id}}). "
    "Close or export it, or run 'workspace reset', before starting a new one."
)

PDF_FALLBACK_USED = (
    "The accessible PDF was produced with the built-in stdlib composer "
    "because LibreOffice ('soffice') was not available on this machine. "
    "Visual fidelity is lower; reading order and text content are preserved."
)

NO_LKG_AVAILABLE = (
    "No last-known-good deck is available yet: this workspace has not "
    "reached Stage approval before. The package omits that artifact rather "
    "than fabricating one."
)

DEMO_ASSET_MISSING = (
    "Demo asset path '{path}' referenced by slide '{slide_id}' no longer "
    "exists on disk. The rest of the package still exported."
)

REIMPORT_EDIT_ACCEPTED = (
    "Re-imported edit to region '{region_id}' was recorded as a pending "
    "edit. {claim_note}"
)

RESTORE_POINT_CREATED = (
    "Restore point '{restore_id}' captured at {trigger}."
)

RESTORE_APPLIED = (
    "Workspace state reverted to restore point '{restore_id}'. The prior "
    "state was itself snapshotted first as '{pre_revert_id}'."
)
