"""Engine CLI: argparse dispatch, one JSON envelope in/out per command
(ARCH §3, §4). This is the *only* state-mutation surface — the Skill
Prompt Layer, a human at a shell, and a test harness all drive this exact
entry point identically (`python3 -m engine.cli <command>` /
`bin/throughline-engine <command>`).

Wire contract: every command reads optional JSON on stdin or `--input
file.json` and writes one envelope to stdout:
    {"ok": bool, "data": <result>, "error": null | {"code","message","details"}}
Exit code 0 iff ok. Diagnostics/logs go to stderr only, so stdout stays
parseable — no stack trace ever reaches stdout.

No subcommand at all (ARCH §4/§11) is itself a supported form, not an
argparse error: see `cmd_bare_default_workspace` and `main()` below — it
opens/resumes the single default talk workspace and returns the same
identity shape `workspace show` does.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

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
    scenario,
    strings,
    workspace as workspace_mod,
)
from .errors import EngineError
from .pptx import reimport as reimport_mod


def _j(obj: Any) -> Any:
    return models.to_jsonable(obj)


def default_actor() -> str:
    return os.environ.get("THROUGHLINE_ACTOR") or getpass.getuser() or "unknown"


def emit(ok: bool, data: Any = None, error: Optional[dict] = None, **top_level: Any) -> None:
    """Writes the one JSON envelope every command emits. `**top_level`
    carries additive, snake_case identity fields (`workspace_id`,
    `deck_id` — see `_identity_fields`) as siblings of `ok`/`data`/`error`;
    it never replaces or renames them, and every nested field already
    inside `data` (`workspaceId`, `workspace.id`, `deckId`, ...) stays
    exactly as it always has, in whichever casing that field already
    used."""
    envelope = {"ok": ok, "data": data, "error": error}
    envelope.update(top_level)
    print(json.dumps(envelope, default=str))


def _identity_fields(data: Any) -> dict[str, str]:
    """Promotes a workspace/deck identity already present somewhere in a
    successful command's `data` payload to top-level, snake_case envelope
    fields (`workspace_id`, `deck_id`) — additive only, alongside (never
    instead of) the existing `ok`/`data`/`error` envelope and every nested
    field exactly as before, in whichever casing it already used (hand-
    built result dicts such as `run-scenario`'s report and
    `package.export_package` use camelCase, e.g. `workspaceId`/`deckId`;
    `models.to_jsonable`-serialized dataclasses such as `workspace`/
    `brief` use each field's own snake_case Python name, e.g.
    `workspace.deck_id`). This is the single place that normalizes
    whichever shape a given command happens to nest its identity in, so a
    black-box caller never has to know each command's own nested shape
    just to read the identity it just established:

    - `workspace_id`: `data["workspaceId"]` (the `run-scenario` report —
      including its bare/default-workspace form), or `data["workspace"]
      ["id"]` (`workspace new`/`show`/`resume`, and the bare
      no-subcommand form — `cmd_bare_default_workspace`), or, for a
      `run-scenario` invocation correctly refused before it could open
      one (e.g. a repeated bare invocation refused
      `WORKSPACE_ALREADY_ACTIVE`), `data["refusal"]["details"]
      ["workspaceId"]` — the *already-active* workspace's own id
      (`engine/workspace.py`'s `create_workspace`), so a first
      (successful) and a later (correctly refused) invocation against the
      same resolved workspace root still surface the identical
      `workspace_id`.
    - `deck_id`: `data["deckId"]` (`export package`/`export pptx`), or
      `data["package"]["deckId"]` (the `run-scenario` report, once Stage
      passes), or `data["workspace"]["deck_id"]` (once a deck has been
      compiled — the raw dataclass field name, unlike the two camelCase
      shapes above).

    Absent whenever neither shape is present (e.g. `gate status`) — never
    a fabricated value.
    """
    if not isinstance(data, dict):
        return {}
    refusal = data.get("refusal") or {}
    workspace_id = (
        data.get("workspaceId")
        or (data.get("workspace") or {}).get("id")
        or (refusal.get("details") or {}).get("workspaceId")
    )
    deck_id = (
        data.get("deckId")
        or (data.get("package") or {}).get("deckId")
        or (data.get("workspace") or {}).get("deck_id")
    )
    fields: dict[str, str] = {}
    if isinstance(workspace_id, str) and workspace_id:
        fields["workspace_id"] = workspace_id
    if isinstance(deck_id, str) and deck_id:
        fields["deck_id"] = deck_id
    return fields


def read_input(args: argparse.Namespace) -> dict:
    input_path = getattr(args, "input", None)
    if input_path:
        if input_path == "-":
            return json.loads(sys.stdin.read() or "{}")
        return json.loads(Path(input_path).read_text())
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read()
        except Exception:
            raw = ""
        if raw.strip():
            return json.loads(raw)
    return {}


def _store(args: argparse.Namespace) -> persistence.Store:
    # A local `--workspace` (currently only `status` and `run-scenario`
    # register it) is the caller's explicit workspace-root target,
    # taking precedence over the global `--workspace-root` if both happen
    # to be given -- exactly the same precedence `cmd_run_scenario`
    # already applies inline for its own `--workspace` flag. Every other
    # command has no `workspace` attribute at all, so `getattr` falls
    # through to `None` and this is a no-op for them.
    root = getattr(args, "workspace", None) or getattr(args, "workspace_root", None)
    return persistence.Store(root=root)


def _active_conn(args: argparse.Namespace) -> tuple[persistence.Store, Any, str]:
    store = _store(args)
    workspace_id = workspace_mod.require_active_workspace(store)
    conn = store.connect(workspace_id)
    return store, conn, workspace_id


# ---------------------------------------------------------------------------
# Handlers — one function per subcommand, returning the JSON-safe `data`
# payload. Any EngineError raised propagates to `main()`'s envelope.
# ---------------------------------------------------------------------------

def cmd_workspace_new(args):
    store = _store(args)
    brief_payload = read_input(args) if (not sys.stdin.isatty() or args.input) else None
    ws, brief = workspace_mod.create_workspace(store, actor=args.actor, brief_payload=brief_payload or None)
    return {"workspace": _j(ws), "brief": _j(brief), "nextAction": workspace_mod.next_action_for(ws)}


def cmd_workspace_show(args):
    store = _store(args)
    result = workspace_mod.show_workspace(store)
    if result is None:
        return {"active": False, "message": strings.WELCOME_NEW_WORKSPACE}
    return {
        "active": True, "workspace": _j(result["workspace"]), "brief": _j(result["brief"]),
        "nextAction": result["nextAction"],
    }


def cmd_workspace_reset(args):
    store = _store(args)
    closed_id = workspace_mod.reset_active_workspace(store, actor=args.actor)
    return {"closedWorkspaceId": closed_id}


def cmd_workspace_resume(args):
    store = _store(args)
    result = workspace_mod.resume_workspace(store, args.id, actor=args.actor)
    return {"workspace": _j(result["workspace"]), "brief": _j(result["brief"]), "nextAction": result["nextAction"]}


def cmd_bare_default_workspace(args):
    """Handler for the no-subcommand invocation (`bin/throughline` alone,
    ARCH §4/§11) *and* the explicit top-level `status` subcommand (a
    discoverable, named alias for callers that specifically probe for a
    `status` verb): opens the single default talk workspace exactly like
    `workspace new` would if none is active yet, or reports the identity
    of whichever one is already active (mirroring `workspace show`'s
    active branch) if one is -- so a bare invocation and any later bare
    invocation (or `status` call) converge on, and resume, the exact same
    workspace/brief identity rather than a fresh one each time. Uses the same
    `--workspace-root` / env-var / default-root precedence as every other
    command (`_store`) -- this is not a parallel code path, only the
    default-workspace convenience of having no subcommand at all to name
    one explicitly. Returns the identical shape `workspace show` returns
    for its active branch, so identity is directly comparable/consistent
    with that command's own output.
    """
    store = _store(args)
    existing = workspace_mod.show_workspace(store)
    if existing is None:
        ws, brief = workspace_mod.create_workspace(store, actor=default_actor(), brief_payload=None)
        next_action = workspace_mod.next_action_for(ws)
    else:
        ws, brief, next_action = existing["workspace"], existing["brief"], existing["nextAction"]
    return {"active": True, "workspace": _j(ws), "brief": _j(brief), "nextAction": next_action}


def cmd_brief_set(args):
    store, conn, wid = _active_conn(args)
    try:
        payload = read_input(args)
        ws, brief = workspace_mod.set_brief(conn, wid, payload, actor=args.actor)
        return {"workspace": _j(ws), "brief": _j(brief)}
    finally:
        conn.close()


def cmd_source_ingest(args):
    store, conn, wid = _active_conn(args)
    try:
        payload = read_input(args)
        staging_dir = store.workspace_dir(wid) / "staging"
        source = ingest_mod.ingest_source(conn, wid, payload, actor=args.actor, staging_dir=staging_dir)
        return {"source": _j(source)}
    finally:
        conn.close()


def cmd_source_list(args):
    store, conn, wid = _active_conn(args)
    try:
        sources = persistence.list_all(conn, "source", wid, models.SourceArtifact)
        return {"sources": [_j(s) for s in sources]}
    finally:
        conn.close()


def cmd_source_resolve_hold(args):
    store, conn, wid = _active_conn(args)
    try:
        source = ingest_mod.resolve_hold(conn, wid, args.source_id, actor=args.actor, decision=args.decision)
        return {"source": _j(source)}
    finally:
        conn.close()


def cmd_source_revoke(args):
    store, conn, wid = _active_conn(args)
    try:
        source = ingest_mod.revoke_access(conn, wid, args.source_id, actor=args.actor)
        return {"source": _j(source)}
    finally:
        conn.close()


def cmd_source_retire(args):
    store, conn, wid = _active_conn(args)
    try:
        source = ingest_mod.retire_source(conn, wid, args.source_id, actor=args.actor)
        return {"source": _j(source)}
    finally:
        conn.close()


def cmd_source_quarantine(args):
    store, conn, wid = _active_conn(args)
    try:
        source = ingest_mod.quarantine_source(conn, wid, args.source_id, actor=args.actor, reason=args.reason)
        return {"source": _j(source)}
    finally:
        conn.close()


def cmd_evidence_extract(args):
    store, conn, wid = _active_conn(args)
    try:
        atoms = evidence_mod.extract_evidence(conn, wid, args.source_id, actor=args.actor, force=args.force)
        return {"evidenceAtoms": [_j(a) for a in atoms]}
    finally:
        conn.close()


def cmd_evidence_set_disposition(args):
    store, conn, wid = _active_conn(args)
    try:
        atom = evidence_mod.set_disposition(conn, wid, args.atom_id, args.disposition, actor=args.actor)
        return {"evidenceAtom": _j(atom)}
    finally:
        conn.close()


def cmd_evidence_list(args):
    store, conn, wid = _active_conn(args)
    try:
        atoms = persistence.list_all(conn, "evidence", wid, models.EvidenceAtom)
        return {"evidenceAtoms": [_j(a) for a in atoms]}
    finally:
        conn.close()


def cmd_claim_propose(args):
    store, conn, wid = _active_conn(args)
    try:
        payload = read_input(args)
        drafts = payload if isinstance(payload, list) else payload.get("drafts", [])
        created = claims_mod.propose_claims(conn, wid, drafts, actor=args.actor)
        return {"claims": [_j(c) for c in created]}
    finally:
        conn.close()


def cmd_claim_link_evidence(args):
    store, conn, wid = _active_conn(args)
    try:
        claim = claims_mod.link_evidence(conn, wid, args.claim_id, args.atom_id, actor=args.actor, contradicts_atom_id=args.contradicts)
        return {"claim": _j(claim)}
    finally:
        conn.close()


def cmd_claim_unlink_evidence(args):
    store, conn, wid = _active_conn(args)
    try:
        claim = claims_mod.unlink_evidence(conn, wid, args.claim_id, args.atom_id, actor=args.actor, reason=args.reason)
        return {"claim": _j(claim)}
    finally:
        conn.close()


def cmd_claim_set_rationale(args):
    store, conn, wid = _active_conn(args)
    try:
        claim = claims_mod.set_rationale(conn, wid, args.claim_id, args.rationale, actor=args.actor)
        return {"claim": _j(claim)}
    finally:
        conn.close()


def cmd_claim_set_aspirational_label(args):
    store, conn, wid = _active_conn(args)
    try:
        claim = claims_mod.set_aspirational_label(conn, wid, args.claim_id, args.label, actor=args.actor)
        return {"claim": _j(claim)}
    finally:
        conn.close()


def cmd_claim_approve(args):
    store, conn, wid = _active_conn(args)
    try:
        approval = claims_mod.approve_claim(conn, wid, args.claim_id, actor=args.actor)
        return {"approval": _j(approval)}
    finally:
        conn.close()


def cmd_claim_lock(args):
    store, conn, wid = _active_conn(args)
    try:
        claim = claims_mod.lock_claim(conn, wid, args.claim_id, actor=args.actor)
        return {"claim": _j(claim)}
    finally:
        conn.close()


def cmd_claim_rewrite(args):
    store, conn, wid = _active_conn(args)
    try:
        claim = claims_mod.rewrite_claim(conn, wid, args.claim_id, args.text, actor=args.actor)
        return {"claim": _j(claim)}
    finally:
        conn.close()


def cmd_claim_retire(args):
    store, conn, wid = _active_conn(args)
    try:
        claim = claims_mod.retire_claim(conn, wid, args.claim_id, actor=args.actor)
        return {"claim": _j(claim)}
    finally:
        conn.close()


def cmd_claim_list(args):
    store, conn, wid = _active_conn(args)
    try:
        items = persistence.list_all(conn, "claim", wid, models.Claim)
        return {"claims": [_j(c) for c in items]}
    finally:
        conn.close()


def cmd_conflict_list(args):
    store, conn, wid = _active_conn(args)
    try:
        items = persistence.list_all(conn, "conflict", wid, models.ConflictCard)
        return {"conflicts": [_j(c) for c in items]}
    finally:
        conn.close()


def cmd_conflict_resolve(args):
    store, conn, wid = _active_conn(args)
    try:
        card = claims_mod.resolve_conflict(conn, wid, args.conflict_id, args.decision, actor=args.actor)
        return {"conflict": _j(card)}
    finally:
        conn.close()


def cmd_narrative_propose_throughlines(args):
    store, conn, wid = _active_conn(args)
    try:
        payload = read_input(args)
        drafts = payload if isinstance(payload, list) else payload.get("drafts", [])
        ws = persistence.get(conn, "workspace", wid, models.Workspace)
        if not drafts:
            # FR-NAR-1: a call with no explicit drafts (no `--input` at
            # all, or `{"drafts": []}`) still deterministically produces
            # exactly 3 real, brief-derived candidates -- never an empty
            # list -- via the same helper `run-scenario` falls back to.
            brief = persistence.get(conn, "brief", ws.brief_id, models.TalkBrief) if ws.brief_id else None
            drafts = narrative.default_throughline_drafts(brief)
        created = narrative.propose_throughlines(conn, wid, ws.brief_id, drafts, actor=args.actor)
        return {"throughlines": [_j(t) for t in created]}
    finally:
        conn.close()


def cmd_narrative_select_throughline(args):
    store, conn, wid = _active_conn(args)
    try:
        selected = narrative.select_throughline(conn, wid, actor=args.actor, throughline_id=args.id, custom_text=args.text)
        return {"throughline": _j(selected)}
    finally:
        conn.close()


def cmd_narrative_propose_routes(args):
    store, conn, wid = _active_conn(args)
    try:
        payload = read_input(args)
        drafts = payload if isinstance(payload, list) else payload.get("drafts", [])
        created = narrative.propose_routes(conn, wid, args.throughline_id, drafts, actor=args.actor)
        return {"routes": [_j(r) for r in created]}
    finally:
        conn.close()


def cmd_narrative_select_route(args):
    store, conn, wid = _active_conn(args)
    try:
        route = narrative.select_route(conn, wid, args.route_id, actor=args.actor)
        return {"route": _j(route)}
    finally:
        conn.close()


def cmd_narrative_list(args):
    store, conn, wid = _active_conn(args)
    try:
        throughlines = persistence.list_all(conn, "throughline", wid, models.NarrativeThroughline)
        routes = persistence.list_all(conn, "route", wid, models.NarrativeRoute)
        return {"throughlines": [_j(t) for t in throughlines], "routes": [_j(r) for r in routes]}
    finally:
        conn.close()


def cmd_compile(args):
    store, conn, wid = _active_conn(args)
    try:
        slides = compiler.compile_deck(conn, wid, actor=args.actor)
        return {"slides": [_j(s) for s in slides]}
    finally:
        conn.close()


def cmd_slide_list(args):
    store, conn, wid = _active_conn(args)
    try:
        slides = persistence.list_all(conn, "slide", wid, models.SlideSpec)
        return {"slides": [_j(s) for s in slides]}
    finally:
        conn.close()


def cmd_slide_set_alt_text(args):
    store, conn, wid = _active_conn(args)
    try:
        slide = compiler.set_alt_text(conn, wid, args.slide_id, args.region, args.text, confirmed_by=args.confirmed_by, actor=args.actor)
        return {"slide": _j(slide)}
    finally:
        conn.close()


def cmd_slide_set_reading_order(args):
    store, conn, wid = _active_conn(args)
    try:
        order = args.order.split(",")
        slide = compiler.set_reading_order(conn, wid, args.slide_id, order, actor=args.actor)
        return {"slide": _j(slide)}
    finally:
        conn.close()


def cmd_slide_set_color_signal(args):
    store, conn, wid = _active_conn(args)
    try:
        uses = args.uses.lower() == "true"
        slide = compiler.set_color_signal(conn, wid, args.slide_id, args.region, uses, args.indicator, actor=args.actor)
        return {"slide": _j(slide)}
    finally:
        conn.close()


def cmd_slide_set_demo_asset(args):
    store, conn, wid = _active_conn(args)
    try:
        slide = compiler.set_demo_asset(
            conn, wid, args.slide_id, actor=args.actor, live_path=args.live,
            prerecorded_asset_path=args.prerecorded, static_asset_path=args.static, verbal_recovery_script=args.verbal,
        )
        return {"slide": _j(slide)}
    finally:
        conn.close()


def cmd_gate_run(args):
    store, conn, wid = _active_conn(args)
    try:
        result = gates.run_gate(conn, wid, args.gate, actor=args.actor)
        return {"gateResult": _j(result)}
    finally:
        conn.close()


def cmd_gate_status(args):
    store, conn, wid = _active_conn(args)
    try:
        results = gates.gate_status(conn, wid)
        return {"gateResults": [_j(r) for r in results]}
    finally:
        conn.close()


def cmd_export_pptx(args):
    store, conn, wid = _active_conn(args)
    try:
        result = package.export_pptx_draft(conn, wid, actor=args.actor, render_mode=args.render_mode)
        return result
    finally:
        conn.close()


def cmd_export_package(args):
    store, conn, wid = _active_conn(args)
    try:
        result = package.export_package(conn, wid, actor=args.actor)
        return result
    finally:
        conn.close()


def cmd_reimport_pptx(args):
    store, conn, wid = _active_conn(args)
    try:
        pptx_bytes = Path(args.path).read_bytes()
        result = reimport_mod.run_reimport(conn, wid, pptx_bytes, actor=args.actor, source_path=args.path)
        advisories = []
        if result["unmatched"]:
            from .errors import Advisory
            advisories.append(Advisory(
                "UNMATCHED_CONTENT", strings.UNMATCHED_CONTENT, {"count": len(result["unmatched"])},
            ).to_dict())
        return {
            "unchangedCount": len(result["unchanged"]),
            "pendingEdits": [_j(pe) for pe in result["pendingEdits"]],
            "unmatched": [_j(u) for u in result["unmatched"]],
            "advisories": advisories,
        }
    finally:
        conn.close()


def cmd_reimport_list_pending(args):
    store, conn, wid = _active_conn(args)
    try:
        items = reimport_mod.list_pending_edits(conn, wid, status=args.status)
        return {"pendingEdits": [_j(i) for i in items]}
    finally:
        conn.close()


def cmd_reimport_accept(args):
    store, conn, wid = _active_conn(args)
    try:
        result = reimport_mod.accept_pending_edit(conn, wid, args.pending_edit_id, actor=args.actor)
        return {"slide": _j(result["slide"]), "claim": _j(result["claim"]) if result["claim"] else None}
    finally:
        conn.close()


def cmd_reimport_discard(args):
    store, conn, wid = _active_conn(args)
    try:
        pe = reimport_mod.discard_pending_edit(conn, wid, args.pending_edit_id, actor=args.actor, reason=args.reason)
        return {"pendingEdit": _j(pe)}
    finally:
        conn.close()


def cmd_reimport_list_unmatched(args):
    store, conn, wid = _active_conn(args)
    try:
        items = reimport_mod.list_unmatched(conn, wid)
        return {"unmatched": [_j(i) for i in items]}
    finally:
        conn.close()


def cmd_reimport_link_unmatched(args):
    store, conn, wid = _active_conn(args)
    try:
        pe = reimport_mod.link_unmatched(conn, wid, args.unmatched_id, args.slide_id, args.region, actor=args.actor)
        return {"pendingEdit": _j(pe)}
    finally:
        conn.close()


def cmd_rehearse_run(args):
    store, conn, wid = _active_conn(args)
    try:
        payload = read_input(args)
        timings = payload if not isinstance(payload, dict) or "timings" not in payload else payload["timings"]
        result = rehearsal.run_rehearsal(conn, wid, timings, actor=args.actor, skip_demos=args.skip_demos)
        return result
    finally:
        conn.close()


def cmd_rehearse_record_qa(args):
    store, conn, wid = _active_conn(args)
    try:
        payload = read_input(args)
        qa_pairs = payload if isinstance(payload, list) else payload.get("qaPairs", [])
        result = rehearsal.record_qa(conn, wid, qa_pairs, actor=args.actor)
        return {"qa": result}
    finally:
        conn.close()


def cmd_rehearse_propose_cuts(args):
    store, conn, wid = _active_conn(args)
    try:
        cuts = compiler.propose_cuts(conn, wid, args.target_seconds)
        return {"beatIdsToCut": cuts}
    finally:
        conn.close()


def cmd_restore_list(args):
    store, conn, wid = _active_conn(args)
    try:
        items = restore_mod.list_restore_points(conn, wid)
        return {"restorePoints": [_j(r) for r in items]}
    finally:
        conn.close()


def cmd_restore_apply(args):
    store, conn, wid = _active_conn(args)
    rp, pre = restore_mod.apply_restore_point(conn, wid, args.restore_id, actor=args.actor)
    # conn is closed by apply_restore_point (file swapped underneath it).
    return {"restoredTo": _j(rp), "preRevertSnapshot": _j(pre)}


def cmd_audit_tail(args):
    store, conn, wid = _active_conn(args)
    try:
        events = audit_mod.tail_audit(conn, wid, since=args.since)
        return {"events": [_j(e) for e in events]}
    finally:
        conn.close()


def cmd_run_scenario(args):
    # A local `--workspace` is the black-box contract's own workspace root
    # (ARCH §11), taking precedence over the global `--workspace-root` if
    # both happen to be given; it also doubles as the report directory
    # when `--out` is omitted, so `run-report.json` lands in the exact
    # directory the caller named. When *neither* `--workspace` nor `--out`
    # is given (the bare invocation form), `root` stays `None` and
    # `persistence.Store` falls through to its own default-root precedence
    # (`--workspace-root` / `THROUGHLINE_WORKSPACE_ROOT` /
    # `THROUGHLINE_HOME` / `~/.copilot/throughline`) exactly like every
    # other command — bare invocation is not a separate code path, it is
    # just every existing default applying with no scenario-specific flag
    # involved at all.
    root = args.workspace or getattr(args, "workspace_root", None)
    store = persistence.Store(root=root)
    scenario_file = Path(args.scenario)
    scenario_doc = json.loads(scenario_file.read_text())
    if args.out:
        out_dir = Path(args.out)
    elif args.workspace:
        out_dir = Path(args.workspace)
    else:
        # Bare invocation: the report location is deterministic because it
        # is a pure function of the same resolved workspace root above —
        # discoverable by anyone who resolves that same precedence chain.
        out_dir = store.root
    export_dir = Path(args.export_dir) if args.export_dir else None
    # `scenario_path` (Dark Factory hardening cycle 12) gives `run_scenario`
    # this scenario document's own directory, so a relative local/fixture
    # `uri` an `add_source`/`ingest_source` action names resolves against
    # it first -- see `engine.ingest._resolve_local_path`.
    return scenario.run_scenario(store, scenario_doc, out_dir, export_dir=export_dir, scenario_path=scenario_file)


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="throughline-engine", description=f"{strings.PRODUCT_NAME} deterministic Engine CLI")
    parser.add_argument("--workspace-root", default=None, help="Override the workspace root directory (else THROUGHLINE_WORKSPACE_ROOT env var, else THROUGHLINE_HOME env var, or ~/.copilot/throughline)")
    # `required=False`: a bare invocation (no subcommand at all) is itself
    # a fully supported public form -- see `cmd_bare_default_workspace`
    # and `main()` below -- not an error. Every existing subcommand (and
    # its own required nested sub-subcommand, where applicable) is
    # unaffected: this only changes what happens when *no* top-level
    # command token is given at all.
    sub = parser.add_subparsers(dest="command", required=False, help="Omit entirely to open/resume the default talk workspace (same identity 'workspace show' reports).")

    def add(name, **kwargs):
        return sub.add_parser(name, **kwargs)

    def with_actor(p):
        p.add_argument("--actor", default=None)
        return p

    def with_input(p):
        p.add_argument("--input", default=None, help="Path to a JSON file (or '-' for stdin); omit to read stdin automatically when piped")
        return p

    # Top-level `status`: a compatibility alias for the bare no-subcommand
    # form (`cmd_bare_default_workspace`) -- opens/resumes the single
    # default talk workspace and reports its identity, so a caller that
    # specifically probes for a named `status` verb (rather than omitting
    # the subcommand entirely) can still verify current/default workspace
    # identity and resume behavior. Not a parallel implementation: same
    # handler, same shape as the bare form and `workspace show`'s active
    # branch (docs/engine-cli-reference.md).
    #
    # `--workspace <dir>`: an explicit-target alias for the global
    # `--workspace-root` (registered on this subparser so it may follow
    # the `status` token itself, e.g. `bin/throughline status --workspace
    # <dir>`, exactly like `run-scenario`'s own identically-named flag) --
    # takes precedence over `--workspace-root` if both are given (`_store`
    # above), but every other resolution rule (env vars, default root) and
    # the identity response shape are completely unaffected.
    status_p = add("status")
    status_p.add_argument("--workspace", default=None, help="Explicit workspace root directory (alias for --workspace-root; takes precedence if both are given)")
    status_p.set_defaults(_handler=cmd_bare_default_workspace)

    ws = add("workspace")
    ws_sub = ws.add_subparsers(dest="workspace_cmd", required=True)
    with_actor(with_input(ws_sub.add_parser("new"))).set_defaults(_handler=cmd_workspace_new)
    ws_sub.add_parser("show").set_defaults(_handler=cmd_workspace_show)
    with_actor(ws_sub.add_parser("reset")).set_defaults(_handler=cmd_workspace_reset)
    p = with_actor(ws_sub.add_parser("resume"))
    p.add_argument("--id", required=True)
    p.set_defaults(_handler=cmd_workspace_resume)

    br = add("brief")
    br_sub = br.add_subparsers(dest="brief_cmd", required=True)
    with_actor(with_input(br_sub.add_parser("set"))).set_defaults(_handler=cmd_brief_set)

    src = add("source")
    src_sub = src.add_subparsers(dest="source_cmd", required=True)
    with_actor(with_input(src_sub.add_parser("ingest"))).set_defaults(_handler=cmd_source_ingest)
    src_sub.add_parser("list").set_defaults(_handler=cmd_source_list)
    p = with_actor(src_sub.add_parser("resolve-hold"))
    p.add_argument("source_id")
    p.add_argument("--decision", required=True, choices=["authorize", "retire"])
    p.set_defaults(_handler=cmd_source_resolve_hold)
    p = with_actor(src_sub.add_parser("revoke"))
    p.add_argument("source_id")
    p.set_defaults(_handler=cmd_source_revoke)
    p = with_actor(src_sub.add_parser("retire"))
    p.add_argument("source_id")
    p.set_defaults(_handler=cmd_source_retire)
    p = with_actor(src_sub.add_parser("quarantine"))
    p.add_argument("source_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(_handler=cmd_source_quarantine)

    ev = add("evidence")
    ev_sub = ev.add_subparsers(dest="evidence_cmd", required=True)
    p = with_actor(ev_sub.add_parser("extract"))
    p.add_argument("source_id")
    p.add_argument("--force", action="store_true")
    p.set_defaults(_handler=cmd_evidence_extract)
    p = with_actor(ev_sub.add_parser("set-disposition"))
    p.add_argument("atom_id")
    p.add_argument("disposition")
    p.set_defaults(_handler=cmd_evidence_set_disposition)
    ev_sub.add_parser("list").set_defaults(_handler=cmd_evidence_list)

    cl = add("claim")
    cl_sub = cl.add_subparsers(dest="claim_cmd", required=True)
    with_actor(with_input(cl_sub.add_parser("propose"))).set_defaults(_handler=cmd_claim_propose)
    p = with_actor(cl_sub.add_parser("link-evidence"))
    p.add_argument("claim_id")
    p.add_argument("atom_id")
    p.add_argument("--contradicts", default=None)
    p.set_defaults(_handler=cmd_claim_link_evidence)
    p = with_actor(cl_sub.add_parser("unlink-evidence"))
    p.add_argument("claim_id")
    p.add_argument("atom_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(_handler=cmd_claim_unlink_evidence)
    p = with_actor(cl_sub.add_parser("set-rationale"))
    p.add_argument("claim_id")
    p.add_argument("--rationale", required=True)
    p.set_defaults(_handler=cmd_claim_set_rationale)
    p = with_actor(cl_sub.add_parser("set-aspirational-label"))
    p.add_argument("claim_id")
    p.add_argument("--label", required=True, choices=list(models.ASPIRATIONAL_LABELS))
    p.set_defaults(_handler=cmd_claim_set_aspirational_label)
    p = with_actor(cl_sub.add_parser("approve"))
    p.add_argument("claim_id")
    p.set_defaults(_handler=cmd_claim_approve)
    p = with_actor(cl_sub.add_parser("lock"))
    p.add_argument("claim_id")
    p.set_defaults(_handler=cmd_claim_lock)
    p = with_actor(cl_sub.add_parser("rewrite"))
    p.add_argument("claim_id")
    p.add_argument("--text", required=True)
    p.set_defaults(_handler=cmd_claim_rewrite)
    p = with_actor(cl_sub.add_parser("retire"))
    p.add_argument("claim_id")
    p.set_defaults(_handler=cmd_claim_retire)
    cl_sub.add_parser("list").set_defaults(_handler=cmd_claim_list)

    cf = add("conflict")
    cf_sub = cf.add_subparsers(dest="conflict_cmd", required=True)
    cf_sub.add_parser("list").set_defaults(_handler=cmd_conflict_list)
    p = with_actor(cf_sub.add_parser("resolve"))
    p.add_argument("conflict_id")
    p.add_argument("--decision", required=True)
    p.set_defaults(_handler=cmd_conflict_resolve)

    nr = add("narrative")
    nr_sub = nr.add_subparsers(dest="narrative_cmd", required=True)
    with_actor(with_input(nr_sub.add_parser("propose-throughlines"))).set_defaults(_handler=cmd_narrative_propose_throughlines)
    p = with_actor(nr_sub.add_parser("select-throughline"))
    p.add_argument("--id", default=None)
    p.add_argument("--text", default=None)
    p.set_defaults(_handler=cmd_narrative_select_throughline)
    p = with_actor(with_input(nr_sub.add_parser("propose-routes")))
    p.add_argument("--throughline-id", required=True)
    p.set_defaults(_handler=cmd_narrative_propose_routes)
    p = with_actor(nr_sub.add_parser("select-route"))
    p.add_argument("route_id")
    p.set_defaults(_handler=cmd_narrative_select_route)
    nr_sub.add_parser("list").set_defaults(_handler=cmd_narrative_list)

    with_actor(add("compile")).set_defaults(_handler=cmd_compile)

    sl = add("slide")
    sl_sub = sl.add_subparsers(dest="slide_cmd", required=True)
    sl_sub.add_parser("list").set_defaults(_handler=cmd_slide_list)
    p = with_actor(sl_sub.add_parser("set-alt-text"))
    p.add_argument("slide_id")
    p.add_argument("region")
    p.add_argument("--text", required=True)
    p.add_argument("--confirmed-by", required=True)
    p.set_defaults(_handler=cmd_slide_set_alt_text)
    p = with_actor(sl_sub.add_parser("set-reading-order"))
    p.add_argument("slide_id")
    p.add_argument("--order", required=True, help="Comma-separated region roles")
    p.set_defaults(_handler=cmd_slide_set_reading_order)
    p = with_actor(sl_sub.add_parser("set-color-signal"))
    p.add_argument("slide_id")
    p.add_argument("region")
    p.add_argument("--uses", required=True, choices=["true", "false"])
    p.add_argument("--indicator", default=None)
    p.set_defaults(_handler=cmd_slide_set_color_signal)
    p = with_actor(sl_sub.add_parser("set-demo-asset"))
    p.add_argument("slide_id")
    p.add_argument("--live", default=None)
    p.add_argument("--prerecorded", default=None)
    p.add_argument("--static", default=None)
    p.add_argument("--verbal", default=None)
    p.set_defaults(_handler=cmd_slide_set_demo_asset)

    gt = add("gate")
    gt_sub = gt.add_subparsers(dest="gate_cmd", required=True)
    p = with_actor(gt_sub.add_parser("run"))
    p.add_argument("gate", choices=["scope", "evidence", "narrative", "claims", "readiness", "stage"])
    p.set_defaults(_handler=cmd_gate_run)
    gt_sub.add_parser("status").set_defaults(_handler=cmd_gate_status)

    ex = add("export")
    ex_sub = ex.add_subparsers(dest="export_cmd", required=True)
    p = with_actor(ex_sub.add_parser("pptx"))
    p.add_argument("--render-mode", default="normal", choices=["normal", "panic"])
    p.set_defaults(_handler=cmd_export_pptx)
    with_actor(ex_sub.add_parser("package")).set_defaults(_handler=cmd_export_package)

    ri = add("reimport")
    ri_sub = ri.add_subparsers(dest="reimport_cmd", required=True)
    p = with_actor(ri_sub.add_parser("pptx"))
    p.add_argument("--path", required=True)
    p.set_defaults(_handler=cmd_reimport_pptx)
    p = ri_sub.add_parser("list-pending")
    p.add_argument("--status", default="PENDING")
    p.set_defaults(_handler=cmd_reimport_list_pending)
    p = with_actor(ri_sub.add_parser("accept"))
    p.add_argument("pending_edit_id")
    p.set_defaults(_handler=cmd_reimport_accept)
    p = with_actor(ri_sub.add_parser("discard"))
    p.add_argument("pending_edit_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(_handler=cmd_reimport_discard)
    ri_sub.add_parser("list-unmatched").set_defaults(_handler=cmd_reimport_list_unmatched)
    p = with_actor(ri_sub.add_parser("link-unmatched"))
    p.add_argument("unmatched_id")
    p.add_argument("--slide-id", required=True)
    p.add_argument("--region", required=True)
    p.set_defaults(_handler=cmd_reimport_link_unmatched)

    rh = add("rehearse")
    rh_sub = rh.add_subparsers(dest="rehearse_cmd", required=True)
    p = with_actor(with_input(rh_sub.add_parser("run")))
    p.add_argument("--skip-demos", action="store_true")
    p.set_defaults(_handler=cmd_rehearse_run)
    with_actor(with_input(rh_sub.add_parser("record-qa"))).set_defaults(_handler=cmd_rehearse_record_qa)
    p = rh_sub.add_parser("propose-cuts")
    p.add_argument("--target-seconds", required=True, type=int)
    p.set_defaults(_handler=cmd_rehearse_propose_cuts)

    rs = add("restore")
    rs_sub = rs.add_subparsers(dest="restore_cmd", required=True)
    rs_sub.add_parser("list").set_defaults(_handler=cmd_restore_list)
    p = with_actor(rs_sub.add_parser("apply"))
    p.add_argument("restore_id")
    p.set_defaults(_handler=cmd_restore_apply)

    au = add("audit")
    au_sub = au.add_subparsers(dest="audit_cmd", required=True)
    p = au_sub.add_parser("tail")
    p.add_argument("--since", default=None)
    p.set_defaults(_handler=cmd_audit_tail)

    p = add("run-scenario")
    p.add_argument("--scenario", required=True)
    p.add_argument("--out", default=None, help="Legacy form: directory to write run-report.json into (workspace root stays governed by the global --workspace-root)")
    p.add_argument("--workspace", default=None, help="Public black-box form: directory used as both the workspace root and (unless --out is also given) the run-report.json location")
    p.add_argument("--export-dir", default=None, help="Optional: directory the Stage package artifacts are written into, overriding the default location nested under the workspace root")
    p.set_defaults(_handler=cmd_run_scenario)
    # Bare invocation (neither --workspace nor --out): the workspace root
    # falls through to --workspace-root / THROUGHLINE_WORKSPACE_ROOT /
    # THROUGHLINE_HOME / ~/.copilot/throughline, and run-report.json is
    # written at that same resolved root — see cmd_run_scenario above and
    # docs/engine-cli-reference.md.

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "actor") and getattr(args, "actor", None) is None:
        args.actor = default_actor()
    handler = getattr(args, "_handler", None)
    if handler is None and getattr(args, "command", None) is None:
        # Bare invocation (ARCH §4/§11): no top-level command token was
        # given at all -- not a missing/invalid command (argparse itself
        # still rejects those with its own usage error, unchanged, since
        # `command` would be set to whatever unrecognized-but-parsed
        # value in that case). This is the one and only place the bare
        # form is special-cased; every explicit subcommand above is
        # untouched.
        handler = cmd_bare_default_workspace
    if handler is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        data = handler(args)
        models.add_report_compat_aliases(data)
        emit(True, data=data, error=None, **_identity_fields(data))
        return 0
    except EngineError as exc:
        emit(False, data=None, error=exc.to_dict())
        return 1
    except Exception as exc:  # noqa: BLE001 - last-resort safety net, never a bare stdout traceback
        print(traceback.format_exc(), file=sys.stderr)
        emit(False, data=None, error={"code": "INTERNAL_ERROR", "message": str(exc), "details": {}})
        return 1


if __name__ == "__main__":
    sys.exit(main())
