"""Shared test helpers: a fresh, isolated workspace root per test (never
`/tmp` — a git-ignored directory inside `tests/`), plus small builders for
the most common setup sequences so individual test files stay focused on
what they're actually asserting.
"""
from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TMP_ROOT = Path(__file__).resolve().parent / ".tmp_workspaces"

from engine import (  # noqa: E402
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
    scenario,
    strings,
    workspace as workspace_mod,
)
from engine.errors import EngineError  # noqa: E402
from engine.pptx import notes as notes_mod  # noqa: E402
from engine.pptx import ooxml_engine, reimport  # noqa: E402

DEFAULT_BRIEF = {
    "audience": "Developers", "eventType": "meetup", "durationMinutes": 20,
    "takeaway": "Test takeaway", "proofPoints": ["a stat"], "excludedTopics": [], "tone": "neutral",
}


def new_root() -> Path:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    root = TMP_ROOT / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def cleanup(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def new_store() -> tuple[persistence.Store, Path]:
    root = new_root()
    return persistence.Store(root=root), root


def make_workspace(store: persistence.Store, brief_overrides: dict | None = None, actor: str = "Test Speaker"):
    payload = dict(DEFAULT_BRIEF)
    if brief_overrides:
        payload.update(brief_overrides)
    ws, brief = workspace_mod.create_workspace(store, actor=actor, brief_payload=payload)
    conn = store.connect(ws.id)
    return ws, brief, conn


def ingest_paste(conn, store: persistence.Store, workspace_id: str, text: str, uri: str = "paste:test",
                  actor: str = "Test Speaker", sensitivity_label: str | None = None):
    payload = {
        "origin": "local", "sourceType": "local_paste", "uri": uri, "owner": "owner@example.com",
        "permissionState": "authorized", "aclSnapshot": "owner-only", "version": "v1", "content": text,
        "sensitivityLabel": sensitivity_label,
    }
    staging_dir = store.workspace_dir(workspace_id) / "staging"
    return ingest_mod.ingest_source(conn, workspace_id, payload, actor=actor, staging_dir=staging_dir)


def make_factual_claim(conn, workspace_id: str, atom_id: str, text: str = "Adoption grew 42%.", actor: str = "Test Speaker"):
    created = claims_mod.propose_claims(conn, workspace_id, [
        {"type": "factual", "text": text, "evidenceAtomIds": [atom_id]},
    ], actor=actor)
    return created[0]


def full_happy_path_beats(factual_claim_id: str, aspirational_claim_id: str) -> list[dict]:
    return [
        {"role": "HOOK", "headline": "A stat that changes the room", "timeBudgetSeconds": 60, "spokenTalkTrack": "Open cold."},
        {"role": "STAKES", "headline": "Talks fail without provenance", "timeBudgetSeconds": 90, "spokenTalkTrack": "Stakes.", "visualDescription": "Desk photo"},
        {"role": "TURN", "headline": "What changes the outcome", "timeBudgetSeconds": 90, "spokenTalkTrack": "Turn.", "visualDescription": "Diagram"},
        {"role": "MECHANISM", "headline": "How the ledger works end to end", "timeBudgetSeconds": 120, "spokenTalkTrack": "Mechanism.", "visualDescription": "Live demo", "isDemo": True},
        {"role": "PROOF", "headline": "Adoption grew 42% in one quarter", "timeBudgetSeconds": 90, "spokenTalkTrack": "Proof.", "claimIds": [factual_claim_id], "visualDescription": "Bar chart"},
        {"role": "OBJECTION", "headline": "Is the overhead worth it", "timeBudgetSeconds": 90, "spokenTalkTrack": "Objection.", "visualDescription": "Quote"},
        {"role": "ASK", "headline": "Start your next talk this way", "timeBudgetSeconds": 60, "spokenTalkTrack": "Ask.", "claimIds": [aspirational_claim_id], "visualDescription": "CTA graphic"},
    ]
