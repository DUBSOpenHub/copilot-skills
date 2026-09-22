"""Error catalog and the one exception type the Engine ever raises
deliberately (programming bugs still raise normal Python exceptions, which
`cli.py` converts to an `INTERNAL_ERROR` envelope rather than a stack trace
on stdout).

Every entry mirrors ARCH.md §12 exactly: a stable `code`, a `severity`
(`BLOCKING` | `ADVISORY` | `INFO`), and a human message built from
`strings.py` templates. BLOCKING errors are raised as `EngineError` and
translated by the CLI into `{"ok": false, "error": {...}}`. ADVISORY/INFO
conditions are not exceptions — they are attached to a successful result's
`advisories`/`info` list by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


BLOCKING = "BLOCKING"
ADVISORY = "ADVISORY"
INFO = "INFO"

# Canonical severity for every known code (documented in ARCH §12). Used by
# tests to assert every code in this catalog is exercised at least once.
SEVERITY = {
    "SOURCE_UNAUTHORIZED": BLOCKING,
    "BUNDLE_LIMIT_REACHED": BLOCKING,
    "FILE_TOO_LARGE": BLOCKING,
    "UNSUPPORTED_FILE_TYPE": BLOCKING,
    "LABEL_CONFLICT": BLOCKING,
    "PARSE_FAILED": BLOCKING,
    "CLAIM_UNSUPPORTED": BLOCKING,
    "NARRATIVE_GATE_FAILED": BLOCKING,
    "ACCESS_REVOKED": ADVISORY,
    "SOURCE_STALE": ADVISORY,
    "CONFLICT_UNRESOLVED": BLOCKING,
    "DEMO_FALLBACK_MISSING": BLOCKING,
    "ACCESSIBILITY_CHECK_FAILED": BLOCKING,
    "STAGE_APPROVER_REQUIRED": BLOCKING,
    "UNMATCHED_CONTENT": ADVISORY,
    "WORKSPACE_ALREADY_ACTIVE": BLOCKING,
    "PDF_FALLBACK_USED": ADVISORY,
    "NO_LKG_AVAILABLE": INFO,
    "DEMO_ASSET_MISSING": ADVISORY,
    # Additional structural codes not enumerated in §12's table but implied
    # by other requirements / needed for a complete, honest CLI surface.
    "NOT_FOUND": BLOCKING,
    "VALIDATION_ERROR": BLOCKING,
    "GATE_NOT_PASSED": BLOCKING,
    "RATIONALE_REQUIRED": BLOCKING,
    "APPROVER_REQUIRED": BLOCKING,
    "IMMUTABLE_LOCKED_CLAIM": BLOCKING,
    "NO_ACTIVE_WORKSPACE": BLOCKING,
    "RESTORE_POINT_NOT_FOUND": BLOCKING,
    "INTERNAL_ERROR": BLOCKING,
}


class EngineError(Exception):
    """Raised for every BLOCKING condition. Carries the exact fields the
    CLI's JSON envelope needs (`code`, `message`, `details`)."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        if code not in SEVERITY:
            raise KeyError(f"Unknown error code used: {code}")
        if SEVERITY[code] != BLOCKING:
            raise ValueError(
                f"EngineError may only be raised for BLOCKING codes; "
                f"'{code}' is {SEVERITY[code]}. Use an advisory/info entry instead."
            )
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass
class Advisory:
    """A non-blocking caveat attached to an otherwise-successful result."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.code not in SEVERITY:
            raise KeyError(f"Unknown advisory code: {self.code}")
        if SEVERITY[self.code] not in (ADVISORY, INFO):
            raise ValueError(f"'{self.code}' is BLOCKING; raise EngineError instead.")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}
