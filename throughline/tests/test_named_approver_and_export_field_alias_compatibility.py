"""Table-driven public compatibility suite for named-approver aliases
(gate/stage/claim approval actions) and `export` action field aliases
(Dark Factory hardening cycle 9, acceptance pass 12).

Compatibility gap this closes:
- `run_gate` rejected any approver-shaped field (`approver`, `human`,
  `name`, ...) on its own inline payload as an unexpected field, instead
  of recording the named approval it identified -- so a gate request
  naming its own approver was refused `VALIDATION_ERROR` rather than
  recording that approval.
- `export` accepted only a narrow `target`/`outputDir`/`actor` vocabulary
  -- several field-name aliases/wrappers commonly used by public
  scenario callers (`format`/`kind`/`type`/`mode` for the target concept;
  `output`/`path`/`directory` for the output-directory override;
  `pptx`/`stagePackage`/`stage_package` boolean-ish target wrappers) were
  all rejected as unexpected fields.

Every alias/wrapper here still normalizes to exactly one of the two
existing operations (`export pptx`/`export package`) or the one existing
named-human-approval field -- never a second mechanism, never a way to
supply a missing/automated approver, and a genuine conflict between two
aliases is always an explicit `VALIDATION_ERROR`, never a silent pick.
Gates/readiness/human approval are never bypassed: a blocked export is
still a structured `report["refusal"]` and exit 0.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import EngineError, REPO_ROOT, cleanup, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _as_field_list(doc: dict) -> list[dict]:
    return [{k: v} for k, v in doc.items()]


class RunGateApproverAliasUnitTests(unittest.TestCase):
    """Direct coverage of `_resolve_named_approver_alias` and the
    `run_gate` (`gateRuns`) action's widened allowed-field set."""

    def test_every_approver_alias_field_name_is_now_accepted_on_run_gate(self):
        for field in ("approver", "approver_name", "approverName", "actor", "human", "name"):
            with self.subTest(field=field):
                doc = [{"action": "run_gate", "gate": "narrative", field: "Dr. Ada Lovelace"}]
                merged = scenario._normalize_scenario_doc(doc)
                self.assertEqual(merged["gateRuns"], [{"gate": "narrative", field: "Dr. Ada Lovelace"}])

    def test_a_nested_approval_object_is_accepted(self):
        doc = [{"action": "run_gate", "gate": "narrative", "approval": {"approver": "Dr. Ada Lovelace"}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["gateRuns"], [{"gate": "narrative", "approval": {"approver": "Dr. Ada Lovelace"}}])

    def test_resolve_named_approver_alias_picks_the_agreeing_value(self):
        resolved = scenario._resolve_named_approver_alias(
            {"gate": "narrative", "approver": "Dr. Ada Lovelace", "human": "Dr. Ada Lovelace"},
            action="run_gate", index=0, default="Scenario Runner",
        )
        self.assertEqual(resolved, "Dr. Ada Lovelace")

    def test_resolve_named_approver_alias_falls_back_to_default_when_absent(self):
        resolved = scenario._resolve_named_approver_alias({"gate": "narrative"}, action="run_gate", index=0, default="Scenario Runner")
        self.assertEqual(resolved, "Scenario Runner")

    def test_resolve_named_approver_alias_rejects_conflicting_aliases(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._resolve_named_approver_alias(
                {"approver": "Dr. Ada Lovelace", "human": "Someone Else"},
                action="run_gate", index=0, default="Scenario Runner",
            )
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_nested_object_naming_no_recognized_field_resolves_to_nothing(self):
        resolved = scenario._resolve_named_approver_alias(
            {"gate": "narrative", "approval": {"decision": "approved"}},
            action="run_gate", index=0, default="Scenario Runner",
        )
        self.assertEqual(resolved, "Scenario Runner")

    def test_an_unrelated_extra_field_is_still_a_validation_error(self):
        """The widened field set never becomes a wildcard -- a genuinely
        unrecognized field is still refused exactly as before (checked
        end-to-end since the field-name check itself runs at execution
        time, not at normalization time)."""
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc.append({"action": "run_gate", "gate": "narrative", "notes": "extra"})
        root = new_root()
        try:
            store = persistence.Store(root=root / "ws")
            report = scenario.run_scenario(store, doc, root / "report")
            self.assertFalse(report["ok"])
            self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        finally:
            cleanup(root)


class RunGateApproverAliasEndToEndTests(unittest.TestCase):
    """End-to-end coverage: a `run_gate` request's own named approver is
    actually recorded on the resulting `GateResult`, never silently
    dropped or refused as unexpected.

    Every gate name `run_gate` accepts (`scope`/`evidence`/`narrative`/
    `claims`/`readiness`/`stage`) is also unconditionally re-run, with
    the whole-document default actor, by the mandatory automatic
    pipeline immediately after any explicit walk finishes (pre-existing,
    correct behavior this hardening cycle does not change -- gate
    results are idempotently re-computed, never append-only) -- so the
    *final* persisted `GateResult`/`report["gateResults"]` entry for that
    gate always reflects the default actor, not an earlier explicit
    `run_gate` request's own approver. The append-only audit trail
    (`report["auditEvents"]`) is what actually distinguishes them: it
    keeps one entry per call, in order, so the *first* `"gate.run"` audit
    event for a given gate is the explicit mid-walk request's own,
    genuine snapshot."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _doc_with_gate_run(self, gate_entry: dict) -> list[dict]:
        base = _as_field_list(json.loads(FIXTURE.read_text()))
        return base + [{"action": "run_gate", **gate_entry}]

    @staticmethod
    def _first_gate_run_actor(audit_events: list[dict], gate_name: str) -> str:
        return next(e["actor"] for e in audit_events if e["action"] == "gate.run" and e["subject_id"] == gate_name)

    def test_an_approver_alias_on_run_gate_is_recorded_for_that_explicit_gate_run(self):
        for field in ("approver", "approver_name", "approverName", "actor", "human", "name"):
            with self.subTest(field=field):
                doc = self._doc_with_gate_run({"gate": "narrative", field: "Dr. Ada Lovelace"})
                store = persistence.Store(root=self.root / f"ws-{field}")
                report = scenario.run_scenario(store, doc, self.root / f"report-{field}")
                self.assertTrue(report["ok"], report.get("refusal"))
                self.assertEqual(self._first_gate_run_actor(report["auditEvents"], "NARRATIVE"), "Dr. Ada Lovelace")

    def test_a_nested_approval_object_on_run_gate_is_recorded(self):
        doc = self._doc_with_gate_run({"gate": "narrative", "approval": {"approverName": "Dr. Ada Lovelace"}})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(self._first_gate_run_actor(report["auditEvents"], "NARRATIVE"), "Dr. Ada Lovelace")

    def test_conflicting_approver_aliases_on_run_gate_is_a_clean_refusal(self):
        doc = self._doc_with_gate_run({"gate": "narrative", "approver": "A", "human": "B"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_no_approver_alias_still_defaults_to_the_whole_document_actor(self):
        doc = self._doc_with_gate_run({"gate": "narrative"})
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(self._first_gate_run_actor(report["auditEvents"], "NARRATIVE"), "Dr. Jamie Rivera")

    def test_the_identical_gate_approver_alias_via_the_cli_subprocess_exits_zero(self):
        doc = self._doc_with_gate_run({"gate": "readiness", "human": "Dr. Ada Lovelace"})
        scenario_path = self.root / "gate-approver-alias-scenario.json"
        scenario_path.write_text(json.dumps(doc))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))
        self.assertEqual(self._first_gate_run_actor(envelope["data"]["auditEvents"], "READINESS"), "Dr. Ada Lovelace")


class ApproveStageNestedApproverObjectTests(unittest.TestCase):
    """`approve_stage`'s `stageApprover` scalar field additionally
    accepts `human`/`name`/`approver` aliases and a nested `approval`
    object -- alongside the already-shipped `approverName`/`approver_name`
    aliases."""

    def test_human_alias_on_approve_stage_normalizes_to_stage_approver(self):
        merged = scenario._normalize_scenario_doc([{"action": "approve_stage", "human": "Jane Doe"}])
        self.assertEqual(merged["stageApprover"], "Jane Doe")

    def test_name_alias_on_approve_stage_normalizes_to_stage_approver(self):
        merged = scenario._normalize_scenario_doc([{"action": "approve_stage", "name": "Jane Doe"}])
        self.assertEqual(merged["stageApprover"], "Jane Doe")

    def test_a_nested_approver_object_on_approve_stage_normalizes_to_stage_approver(self):
        merged = scenario._normalize_scenario_doc([{"action": "approve_stage", "approver": {"name": "Jane Doe"}}])
        self.assertEqual(merged["stageApprover"], "Jane Doe")

    def test_a_nested_approval_object_on_approve_stage_normalizes_to_stage_approver(self):
        merged = scenario._normalize_scenario_doc([{"action": "approve_stage", "approval": {"approverName": "Jane Doe"}}])
        self.assertEqual(merged["stageApprover"], "Jane Doe")

    def test_conflicting_new_aliases_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "approve_stage", "human": "Jane Doe", "name": "Someone Else"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_reaches_stage_end_to_end_with_a_nested_approver_object(self):
        base = json.loads(FIXTURE.read_text())
        base.pop("stageApprover", None)
        doc = _as_field_list(base) + [{"action": "approve_stage", "approver": {"name": "Dr. Jamie Rivera"}}]
        root = new_root()
        try:
            store = persistence.Store(root=root / "ws")
            report = scenario.run_scenario(store, doc, root / "report")
            self.assertTrue(report["ok"], report.get("refusal"))
            self.assertEqual(report["workspace"]["stageApprovedBy"], "Dr. Jamie Rivera")
        finally:
            cleanup(root)

    def test_a_raw_field_list_stage_approver_object_with_no_recognized_key_is_a_clean_refusal(self):
        """A nested object naming none of the recognized approver fields
        is an explicit `VALIDATION_ERROR` at the point `stageApprover` is
        finally consumed -- never silently ignored/auto-approved."""
        base = json.loads(FIXTURE.read_text())
        base["stageApprover"] = {"decision": "approved"}
        doc = _as_field_list(base)
        root = new_root()
        try:
            store = persistence.Store(root=root / "ws")
            report = scenario.run_scenario(store, doc, root / "report")
            self.assertFalse(report["ok"])
            self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")
        finally:
            cleanup(root)


class ClaimApproverAliasEndToEndTests(unittest.TestCase):
    """`propose_claim`'s inline `approve` flag accepts the identical
    shared named-approver alias vocabulary, not just its own `approver`
    key."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_an_approver_name_alias_on_a_claim_is_recorded_as_its_approver(self):
        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:note",
             "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "Adoption grew 42% quarter over quarter."},
            {"action": "propose_claim", "type": "factual", "text": "Adoption grew 42% quarter over quarter.",
             "evidenceLocators": ["paste:note"], "approve": True, "approverName": "Dr. Ada Lovelace"},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertEqual(report["claims"][0]["approver"], "Dr. Ada Lovelace")

    def test_conflicting_claim_approver_aliases_is_a_clean_refusal(self):
        doc = [
            {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
             "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
            {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:note",
             "owner": "speaker@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
             "version": "v1", "content": "Adoption grew 42% quarter over quarter."},
            {"action": "propose_claim", "type": "factual", "text": "Adoption grew 42% quarter over quarter.",
             "evidenceLocators": ["paste:note"], "approve": True, "approver": "A", "human": "B"},
        ]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")


class ExportTargetFieldAliasUnitTests(unittest.TestCase):
    """Direct coverage of `_resolve_export_target`: `format`/`kind`/
    `type`/`mode` field-name aliases and `pptx`/`stagePackage`/
    `stage_package` boolean-ish wrapper fields."""

    def test_every_target_field_name_alias_resolves_to_pptx(self):
        for field in ("target", "format", "kind", "type", "mode"):
            with self.subTest(field=field):
                self.assertEqual(scenario._resolve_export_target({field: "pptx"}, 0), "pptx")

    def test_every_target_field_name_alias_resolves_to_package(self):
        for field in ("target", "format", "kind", "type", "mode"):
            with self.subTest(field=field):
                self.assertEqual(scenario._resolve_export_target({field: "stage_package"}, 0), "package")

    def test_wrapper_fields_resolve_without_any_target_field_at_all(self):
        self.assertEqual(scenario._resolve_export_target({"pptx": True}, 0), "pptx")
        self.assertEqual(scenario._resolve_export_target({"stagePackage": True}, 0), "package")
        self.assertEqual(scenario._resolve_export_target({"stage_package": True}, 0), "package")

    def test_a_falsy_wrapper_field_is_treated_as_absent(self):
        self.assertIsNone(scenario._resolve_export_target({"pptx": False}, 0))

    def test_no_target_field_or_wrapper_at_all_resolves_to_none(self):
        self.assertIsNone(scenario._resolve_export_target({}, 0))

    def test_agreeing_target_field_and_wrapper_is_not_a_conflict(self):
        self.assertEqual(scenario._resolve_export_target({"target": "pptx", "pptx": True}, 0), "pptx")

    def test_conflicting_target_field_aliases_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._resolve_export_target({"target": "pptx", "format": "package"}, 0)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_conflicting_wrapper_and_target_field_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._resolve_export_target({"target": "package", "pptx": True}, 0)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_unrecognized_target_value_is_still_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._resolve_export_target({"format": "carrier_pigeon"}, 0)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class ExportOutputDirFieldAliasUnitTests(unittest.TestCase):
    """Direct coverage of `_resolve_export_output_dir`: `output`/`path`/
    `directory`/`out_dir` field-name aliases."""

    def test_every_output_dir_field_name_alias_resolves(self):
        for field in ("outputDir", "output_dir", "exportDir", "export_dir", "output", "path", "directory", "out_dir"):
            with self.subTest(field=field):
                self.assertEqual(scenario._resolve_export_output_dir({field: "/tmp/x"}, 0), "/tmp/x")

    def test_no_output_dir_field_resolves_to_none(self):
        self.assertIsNone(scenario._resolve_export_output_dir({}, 0))

    def test_agreeing_output_dir_aliases_is_not_a_conflict(self):
        self.assertEqual(scenario._resolve_export_output_dir({"path": "/a", "directory": "/a"}, 0), "/a")

    def test_agreeing_out_dir_and_export_dir_is_not_a_conflict(self):
        self.assertEqual(scenario._resolve_export_output_dir({"out_dir": "/a", "exportDir": "/a"}, 0), "/a")

    def test_conflicting_output_dir_aliases_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._resolve_export_output_dir({"path": "/a", "directory": "/b"}, 0)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_out_dir_conflicting_with_another_alias_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._resolve_export_output_dir({"out_dir": "/a", "directory": "/b"}, 0)
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")


class ExportFieldAliasEndToEndTests(unittest.TestCase):
    """End-to-end coverage through `run_scenario`: every alias/wrapper
    still executes the identical, already-existing
    `package.export_pptx_draft`/`package.export_package` calls -- never a
    bypass, never a second export code path."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def _full_doc(self, extra_actions: list[dict]) -> list[dict]:
        base = json.loads(FIXTURE.read_text())
        return _as_field_list(base) + extra_actions

    def test_format_field_alias_produces_a_pptx_draft(self):
        doc = self._full_doc([{"action": "export", "format": "pptx"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["target"], "pptx")

    def test_kind_field_alias_produces_a_package_export(self):
        doc = self._full_doc([{"action": "export", "kind": "stage_package"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["target"], "package")

    def test_pptx_wrapper_field_alone_produces_a_pptx_draft(self):
        doc = self._full_doc([{"action": "export", "pptx": True}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["target"], "pptx")

    def test_stage_package_wrapper_field_alone_produces_a_package_export(self):
        doc = self._full_doc([{"action": "export", "stagePackage": True}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["target"], "package")

    def test_directory_alias_overrides_the_package_export_location(self):
        custom_dir = self.root / "aliased-export-dir"
        doc = self._full_doc([{"action": "export", "target": "package", "directory": str(custom_dir)}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["exportDir"], str(custom_dir))
        self.assertTrue((custom_dir / "manifest.json").exists())

    def test_out_dir_alias_overrides_the_package_export_location(self):
        """Dark Factory hardening cycle 10, acceptance pass 13: `out_dir`
        is an explicit alias for the same package export output-directory
        override every other `_EXPORT_OUTPUT_DIR_FIELD_NAMES` entry
        already accepts."""
        custom_dir = self.root / "out-dir-aliased-export"
        doc = self._full_doc([{"action": "export", "target": "package", "out_dir": str(custom_dir)}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertEqual(report["exports"][0]["exportDir"], str(custom_dir))
        self.assertTrue((custom_dir / "manifest.json").exists())

    def test_out_dir_conflicting_with_export_dir_on_export_is_a_clean_refusal(self):
        doc = self._full_doc([
            {"action": "export", "target": "package", "out_dir": str(self.root / "a"), "exportDir": str(self.root / "b")},
        ])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_a_named_approver_alias_on_export_names_who_performed_it(self):
        doc = self._full_doc([{"action": "export", "target": "package", "human": "Dr. Ada Lovelace"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))
        export_dir = Path(report["exports"][0]["exportDir"])
        manifest = json.loads((export_dir / "manifest.json").read_text())
        self.assertEqual(manifest["exportedBy"], "Dr. Ada Lovelace")

    def test_a_nested_approval_object_on_export_resolves(self):
        doc = self._full_doc([{"action": "export", "target": "pptx", "approval": {"name": "Dr. Ada Lovelace"}}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertTrue(report["ok"], report.get("refusal"))

    def test_conflicting_target_aliases_on_export_is_a_clean_refusal(self):
        doc = self._full_doc([{"action": "export", "target": "pptx", "format": "package"}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_conflicting_output_dir_aliases_on_export_is_a_clean_refusal(self):
        doc = self._full_doc([
            {"action": "export", "target": "package", "path": str(self.root / "a"), "directory": str(self.root / "b")},
        ])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_a_pptx_wrapper_still_rejects_an_output_dir_override(self):
        """`pptx` (via any alias/wrapper) still has no output-directory
        override anywhere in the domain layer."""
        doc = self._full_doc([{"action": "export", "pptx": True, "path": str(self.root / "nowhere")}])
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "VALIDATION_ERROR")

    def test_a_blocked_package_export_via_aliases_is_still_a_structured_refusal_not_a_bypass(self):
        base = json.loads(FIXTURE.read_text())
        for claim in base["claims"]:
            claim.pop("approve", None)
        base.pop("rehearsalTimings", None)
        base.pop("qaPairs", None)
        base.pop("stageApprover", None)
        doc = _as_field_list(base) + [{"action": "export", "stagePackage": True}]
        store = persistence.Store(root=self.root / "ws")
        report = scenario.run_scenario(store, doc, self.root / "report")
        self.assertFalse(report["ok"])
        self.assertEqual(report["refusal"]["code"], "GATE_NOT_PASSED")
        self.assertFalse(report["stageGate"]["passed"])

    def test_the_identical_export_aliases_via_the_cli_subprocess_exit_zero(self):
        doc = self._full_doc([{"action": "export", "kind": "pptx"}, {"action": "export", "stagePackage": True}])
        scenario_path = self.root / "export-alias-scenario.json"
        scenario_path.write_text(json.dumps(doc))
        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"], envelope.get("error"))
        self.assertTrue(envelope["data"]["ok"], envelope["data"].get("refusal"))
        self.assertEqual([e["target"] for e in envelope["data"]["exports"]], ["pptx", "package"])


if __name__ == "__main__":
    unittest.main()
