"""Regression tests for `run_scenario`'s third accepted scenario-document
wire shape (`engine/scenario._normalize_scenario_doc` /
`_apply_action_list_entry`): the action-list form — a JSON array whose
elements each carry an explicit `"action"` field naming one canonical,
allowlisted public action verb (`engine/scenario._ACTION_ALIASES`), plus
that action's inline payload as every other key on the same element, e.g.
`[{"action": "set_talk_brief", "audience": "...", ...}, {"action":
"ingest_source", "uri": "...", "origin": "..."}, ...]`.

The action verb is never a raw object-form field name (`"brief"`,
`"sources"`, ...) — that was a prior, incorrect revision of this shape
that the public black-box harness rejected: its first staged action,
`set_talk_brief`, was treated as an unknown document field because only
the bare field name `"brief"` was accepted. `_ACTION_ALIASES` is the
explicit, conservative allowlist from every accepted public verb to
exactly one object-form field, derived from this repository's own CLI
subcommand names and PRD/ARCH vocabulary (see the module comment above
`_ACTION_ALIASES` in `engine/scenario.py` and
`docs/engine-cli-reference.md`'s "Action vocabulary" table) — a raw field
name used as an action, or any other string not in that table, is always
a clean `VALIDATION_ERROR`, never a crash and never a silent accept.

All three document shapes (object-form, field-list form, action-list
form) normalize to, and drive, the exact same execution model — never a
second engine — so a scenario correctly refused/blocked mid-walk is still
a normal exit-0 completion with the refusal in the result document (the
same completion contract `test_scenario_invocation_forms.py` pins for the
other two shapes), while a malformed/unknown/ambiguous action-list element
is a clean `VALIDATION_ERROR`, never a crash.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import EngineError, REPO_ROOT, cleanup, new_root, persistence, scenario

OBJECT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"
ACTION_LIST_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path_action_list.json"
BIN = str(REPO_ROOT / "bin" / "throughline-engine")


def _run_cli(*args, timeout=120):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


class ActionListNormalizationUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the normalization function itself —
    fast, and pins the exact accepted/rejected action-list shapes
    independent of the full end-to-end run."""

    def test_action_list_fixture_normalizes_to_the_same_dict_as_object_form(self):
        object_doc = json.loads(OBJECT_FIXTURE.read_text())
        action_doc = json.loads(ACTION_LIST_FIXTURE.read_text())
        self.assertIsInstance(action_doc, list)
        self.assertTrue(any("action" in el for el in action_doc))
        # Every element uses a canonical verb, never a raw field name.
        self.assertTrue(all(el["action"] in scenario._ACTION_ALIASES for el in action_doc))
        self.assertEqual(scenario._normalize_scenario_doc(action_doc), object_doc)

    def test_every_object_form_field_is_reachable_and_only_intentional_fields_have_two_aliases(self):
        """Guards the alias table's own completeness invariant (also
        asserted at import time in engine/scenario.py): every field the
        object-form/field-list forms support is reachable through the
        action-list form under at least one canonical verb. Four fields
        are deliberate exceptions carrying two synonyms each: `sources`
        (`ingest_source`, the original verb, and `add_source`, the public
        compatibility alias), `selectRouteIndex` (`select_route`, the
        original verb, and `select_narrative_route`, the public
        compatibility alias -- which also, uniquely, additionally accepts
        a `"text"` selector into a second field, `selectRouteText`, not
        reachable via `select_route`), `rehearsalTimings`
        (`set_rehearsal_timing`, the original verb, and `rehearse`, the
        public compatibility alias), and `compileRequested` (`compile_deck`
        and `compile_presentation`, two equally-common public names for
        the one deck-compilation marker) -- every other field still has
        exactly one, so this pins the synonym table from silently growing
        beyond those four intended cases."""
        all_fields = (
            scenario._ACTION_LIST_OBJECT_FIELDS | scenario._ACTION_LIST_SCALAR_FIELDS
            | scenario._ACTION_OBJECT_FIELDS | set(scenario._ACTION_MAPPING_FIELDS)
            | scenario._ACTION_SCALAR_FIELDS
        )
        self.assertEqual(set(scenario._ACTION_ALIASES.values()), all_fields)
        from collections import Counter
        alias_counts = Counter(scenario._ACTION_ALIASES.values())
        duplicated = {field_name: count for field_name, count in alias_counts.items() if count > 1}
        self.assertEqual(
            duplicated,
            {"sources": 2, "selectRouteIndex": 2, "rehearsalTimings": 2, "compileRequested": 2},
            "only 'sources' (ingest_source/add_source), 'selectRouteIndex' (select_route/"
            "select_narrative_route), 'rehearsalTimings' (set_rehearsal_timing/rehearse), and "
            "'compileRequested' (compile_deck/compile_presentation) should have two aliases",
        )

    def test_list_object_action_appends_one_item_per_element(self):
        doc = [
            {"action": "ingest_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:a"},
            {"action": "ingest_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:b"},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual([s["uri"] for s in merged["sources"]], ["paste:a", "paste:b"])

    def test_list_scalar_action_appends_bare_values(self):
        doc = [
            {"action": "propose_throughline", "value": "Draft one"},
            {"action": "propose_throughline", "value": "Draft two"},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["throughlineDrafts"], ["Draft one", "Draft two"])

    def test_mapping_action_merges_entries_into_a_dict(self):
        doc = [
            {"action": "set_rehearsal_timing", "slideRole": "HOOK", "seconds": 58},
            {"action": "set_rehearsal_timing", "slideRole": "ASK", "seconds": 55},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["rehearsalTimings"], {"HOOK": 58, "ASK": 55})

    def test_object_action_sets_the_whole_object_from_its_inline_fields(self):
        doc = [{"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup"}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["brief"], {"audience": "Devs", "eventType": "meetup"})

    def test_scalar_action_accepts_a_value_field(self):
        merged = scenario._normalize_scenario_doc([{"action": "set_actor", "value": "Jane Doe"}])
        self.assertEqual(merged["actor"], "Jane Doe")

    def test_scalar_action_accepts_the_target_fields_own_name_as_an_alternative_to_value(self):
        """The redundant fallback key is the *object-form field's* own
        name (`stageApprover`), not the action verb's name
        (`approve_stage`) — the two are no longer the same string."""
        merged = scenario._normalize_scenario_doc([{"action": "approve_stage", "stageApprover": "Jane Doe"}])
        self.assertEqual(merged["stageApprover"], "Jane Doe")

    def test_scalar_action_accepts_matching_value_and_same_named_fields_together(self):
        merged = scenario._normalize_scenario_doc([{"action": "set_actor", "value": "Jane Doe", "actor": "Jane Doe"}])
        self.assertEqual(merged["actor"], "Jane Doe")

    def test_action_list_and_field_list_entries_compose_in_the_same_document(self):
        doc = [
            {"brief": {"audience": "Devs"}},
            {"action": "set_actor", "value": "Jane Doe"},
            {"action": "ingest_source", "uri": "paste:a"},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["brief"], {"audience": "Devs"})
        self.assertEqual(merged["actor"], "Jane Doe")
        # Dark Factory hardening cycle 13: a bare "paste:" pseudo-scheme
        # `uri` with no other origin signal now conservatively classifies
        # `origin: "local"` (`_apply_default_local_origin`'s widened
        # non-remote-locator rule) -- this test's own concern (action-
        # list/field-list composition) is otherwise unaffected.
        self.assertEqual(merged["sources"], [{"uri": "paste:a", "origin": "local"}])

    # -- malformed / unknown / ambiguous rejections -------------------------

    def test_unknown_action_name_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "notARealAction", "foo": "bar"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["action"], "notARealAction")

    def test_a_raw_object_form_field_name_is_no_longer_accepted_as_an_action(self):
        """Regression guard for the exact black-box-reported defect: the
        previous (incorrect) revision of this shape treated the action
        verb as a raw field name, so `"brief"`/`"sources"`/`"actor"` were
        (wrongly) accepted while the real public verb (`set_talk_brief`)
        was rejected as unknown. Every raw field name must now be
        rejected exactly like any other unrecognized string."""
        for field_name in ("brief", "sources", "actor", "claims", "stageApprover", "rehearsalTimings"):
            with self.assertRaises(EngineError) as ctx:
                scenario._normalize_scenario_doc([{"action": field_name, "value": "x"}])
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
            self.assertEqual(ctx.exception.details["action"], field_name)

    def test_non_string_action_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": 42, "foo": "bar"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_empty_action_string_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "", "foo": "bar"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_list_object_action_with_no_inline_payload_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "ingest_source"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["field"], "sources")

    def test_object_action_with_no_inline_payload_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "set_talk_brief"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_repeated_scalar_action_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "set_actor", "value": "A"}, {"action": "set_actor", "value": "B"},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["field"], "actor")

    def test_repeated_object_action_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "set_talk_brief", "audience": "Devs"}, {"action": "set_talk_brief", "audience": "Others"},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["field"], "brief")

    def test_a_scalar_action_repeated_across_action_list_and_field_list_forms_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"actor": "A"}, {"action": "set_actor", "value": "B"},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["field"], "actor")

    def test_repeated_mapping_key_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "set_rehearsal_timing", "slideRole": "HOOK", "seconds": 58},
                {"action": "set_rehearsal_timing", "slideRole": "HOOK", "seconds": 99},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["key"], "HOOK")

    def test_mapping_action_missing_a_required_field_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "set_rehearsal_timing", "slideRole": "HOOK"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_mapping_action_with_an_unexpected_extra_field_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "set_rehearsal_timing", "slideRole": "HOOK", "seconds": 58, "extra": True},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_list_scalar_action_missing_value_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "propose_throughline"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_list_scalar_action_with_an_unexpected_extra_field_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "propose_throughline", "value": "x", "extra": 1}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_scalar_action_missing_a_value_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "set_actor"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_scalar_action_with_an_unexpected_extra_field_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "set_actor", "value": "A", "extra": 1}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_scalar_action_with_conflicting_value_and_same_named_field_is_an_ambiguous_validation_error(self):
        """Both a "value" *and* the target field's own name given,
        disagreeing on the value: rejected as ambiguous rather than
        silently picking one — this is the literal "ambiguous action
        entry" case."""
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "set_actor", "value": "A", "actor": "B"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["action"], "set_actor")
        self.assertEqual(ctx.exception.details["field"], "actor")

    def test_an_action_element_that_is_not_an_object_is_still_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc(["not-an-object"])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["index"], 0)


class ActionListEndToEndTests(unittest.TestCase):
    """The action-list fixture, run through the exact same code path as
    the documented object-form fixture (`test_scenario_local_happy_path.py`)
    and the field-list fixture (`test_scenario_document_forms.py`), must
    reach the identical successful outcome — proving normalization happens
    once, up front, rather than duplicating pipeline logic. Uses only
    canonical public action verbs (`set_talk_brief`, `ingest_source`,
    `propose_claim`, ...), the realistic full workflow journey a
    black-box caller drives end to end."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_action_list_fixture_produces_a_complete_stage_package_via_run_scenario_directly(self):
        store = persistence.Store(root=self.root / "workspace-root")
        doc = json.loads(ACTION_LIST_FIXTURE.read_text())

        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"])
        self.assertIsNone(report["refusal"])
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)
        self.assertTrue((self.root / "report" / "run-report.json").exists())

    def test_action_list_fixture_produces_the_same_outcome_as_the_object_form_fixture(self):
        object_report = scenario.run_scenario(
            persistence.Store(root=self.root / "object-root"),
            json.loads(OBJECT_FIXTURE.read_text()),
            self.root / "object-report",
        )
        action_report = scenario.run_scenario(
            persistence.Store(root=self.root / "action-root"),
            json.loads(ACTION_LIST_FIXTURE.read_text()),
            self.root / "action-report",
        )
        self.assertEqual(object_report["ok"], action_report["ok"])
        self.assertTrue(action_report["ok"])
        self.assertEqual(object_report["stageGate"]["passed"], action_report["stageGate"]["passed"])
        self.assertEqual(set(object_report["package"]["artifactKinds"]), set(action_report["package"]["artifactKinds"]))

    def test_action_list_fixture_via_the_cli_subprocess_entry_point(self):
        proc = _run_cli(
            "--workspace-root", str(self.root / "cli-workspace-root"),
            "run-scenario", "--scenario", str(ACTION_LIST_FIXTURE), "--out", str(self.root / "cli-report"),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["stageGate"]["passed"])
        self.assertIn("package", envelope["data"])

    def test_action_list_fixture_via_the_bare_run_scenario_invocation_form(self):
        """The action-list shape composes with every `run-scenario`
        invocation form, including the bare one -- not a special case of
        either."""
        proc = _run_cli(
            "--workspace-root", str(self.root / "bare-workspace-root"),
            "run-scenario", "--scenario", str(ACTION_LIST_FIXTURE),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["stageGate"]["passed"])

    def test_action_list_fixture_response_envelope_keeps_full_compatibility(self):
        """Response-shape compatibility for a realistic full action-list
        journey: the existing `ok`/`data`/`error` envelope and every
        nested camelCase field stay exactly as documented, *and* the
        top-level snake_case `workspace_id`/`deck_id` identity fields
        (added for the default-workspace response contract) are present
        and consistent with their nested counterparts — this is not a
        parallel/alternate response shape, only an additive one."""
        proc = _run_cli(
            "--workspace-root", str(self.root / "compat-workspace-root"),
            "run-scenario", "--scenario", str(ACTION_LIST_FIXTURE), "--out", str(self.root / "compat-report"),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertEqual(set(envelope) & {"ok", "data", "error"}, {"ok", "data", "error"})
        self.assertTrue(envelope["ok"])
        self.assertIsNone(envelope["error"])
        self.assertEqual(envelope["workspace_id"], envelope["data"]["workspaceId"])
        self.assertEqual(envelope["deck_id"], envelope["data"]["package"]["deckId"])

    def test_a_malformed_action_list_document_is_a_clean_validation_error_through_the_cli(self):
        """The full black-box path (subprocess -> CLI -> run_scenario)
        never crashes on a malformed action-list document -- a clean,
        observable `VALIDATION_ERROR` envelope (exit 1), never a stack
        trace on stdout, and never a fabricated 'refusal' (this is a
        structural input error, not a domain refusal)."""
        bad_path = self.root / "bad-action-scenario.json"
        bad_path.write_text(json.dumps([{"action": "ingest_source"}]))  # action present, empty payload

        proc = _run_cli(
            "run-scenario", "--scenario", str(bad_path), "--workspace", str(self.root / "workspace-dir"),
        )
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("Traceback", proc.stdout)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "VALIDATION_ERROR")
        self.assertNotIn("workspace_id", envelope)
        self.assertFalse((self.root / "workspace-dir" / "run-report.json").exists())

    def test_an_unknown_action_name_is_a_clean_validation_error_through_the_cli(self):
        bad_path = self.root / "unknown-action-scenario.json"
        bad_path.write_text(json.dumps([{"action": "doSomethingUnknown", "foo": "bar"}]))

        proc = _run_cli(
            "run-scenario", "--scenario", str(bad_path), "--workspace", str(self.root / "workspace-dir"),
        )
        self.assertEqual(proc.returncode, 1)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "VALIDATION_ERROR")

    def test_a_raw_field_name_action_is_a_clean_validation_error_through_the_cli(self):
        """End-to-end regression coverage for the exact reported defect:
        `{"action": "set_talk_brief", ...}` must succeed (covered above),
        while `{"action": "brief", ...}` -- the previous, incorrect
        vocabulary -- must be rejected identically to any other unknown
        action, never silently treated as the `brief` field."""
        bad_path = self.root / "raw-field-name-action-scenario.json"
        bad_path.write_text(json.dumps([{"action": "brief", "audience": "Devs", "eventType": "meetup"}]))

        proc = _run_cli(
            "run-scenario", "--scenario", str(bad_path), "--workspace", str(self.root / "workspace-dir"),
        )
        self.assertEqual(proc.returncode, 1)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(envelope["error"]["details"]["action"], "brief")

    def test_completion_contract_a_repeated_action_list_form_call_resumes_the_same_workspace(self):
        """The "a later call against the same explicit workspace resumes
        it" contract (`scenario.run_scenario`'s own contract;
        `test_scenario_invocation_forms.py`) holds for the action-list
        shape exactly as it does for object-form and field-list form --
        it is the same execution model, not a parallel one. The resumed
        (second) invocation still surfaces the same top-level
        `workspace_id` as the first, successful one."""
        workspace_dir = self.root / "workspace-dir"
        first = _run_cli("run-scenario", "--scenario", str(ACTION_LIST_FIXTURE), "--workspace", str(workspace_dir))
        self.assertEqual(first.returncode, 0, first.stderr)
        first_envelope = json.loads(first.stdout)
        self.assertTrue(first_envelope["data"]["ok"])
        first_workspace_id = first_envelope["workspace_id"]
        self.assertTrue(first_workspace_id)

        # No `workspace reset` in between: NFR-2's single-active-workspace
        # lock is still held, so this call resumes that same workspace
        # rather than being refused.
        second = _run_cli("run-scenario", "--scenario", str(ACTION_LIST_FIXTURE), "--workspace", str(workspace_dir))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("Traceback", second.stdout)
        second_envelope = json.loads(second.stdout)
        self.assertTrue(second_envelope["ok"], second_envelope.get("error"))
        self.assertTrue(second_envelope["data"]["ok"])
        self.assertIsNone(second_envelope["data"]["refusal"])
        self.assertTrue(second_envelope["data"]["workspaceResumed"])
        self.assertEqual(second_envelope["workspace_id"], first_workspace_id)


if __name__ == "__main__":
    unittest.main()
