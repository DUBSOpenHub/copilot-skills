"""Regression tests for `set_rehearsal_timing`/`rehearse` action-list
inline-payload aliases (`engine/scenario._apply_rehearsal_timing_entry` /
`_resolve_rehearsal_slide`): a public rehearsal timing entry accepts any
one of three slide-reference field names (`slideRole`, the original; or
`slideId`/`slideOrder`, mirroring `_match_slide`'s own pre-existing
precedence used elsewhere for accessibility/demo-asset matching) paired
with any one of four duration field names (`seconds`, the original; or
`duration`/`durationSeconds`/`actualSeconds`, the latter mirroring
`rehearse run`'s own direct CLI timings-document field name verbatim).

Compatibility gap this closes: the rehearsal action's inline payload
previously required *exactly* `slideRole`+`seconds` -- any other shape
(e.g. `slideId`+`actualSeconds`, matching the direct CLI's own
`{"<slideId>": <actualSeconds>}` timings-document convention) was
rejected with `VALIDATION_ERROR: requires exactly "slideRole" and
"seconds" ...`, even though the underlying `rehearsal.run_rehearsal` call
and its timing-validation rules are otherwise unaffected.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import EngineError, REPO_ROOT, cleanup, new_root, persistence, scenario

BIN = str(REPO_ROOT / "bin" / "throughline")
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenarios" / "local_happy_path.json"


def _run_cli(*args, timeout=60):
    return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, timeout=timeout)


def _as_field_list(doc: dict) -> list[dict]:
    return [{k: v} for k, v in doc.items()]


class RehearsalTimingAliasNormalizationUnitTests(unittest.TestCase):
    """Direct, in-process coverage of the normalization function itself."""

    def test_the_original_slide_role_seconds_shape_is_unaffected(self):
        doc = [{"action": "rehearse", "slideRole": "HOOK", "seconds": 58}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["rehearsalTimings"], {"HOOK": 58})

    def test_duration_is_accepted_as_a_synonym_for_seconds(self):
        doc = [{"action": "rehearse", "slideRole": "HOOK", "duration": 58}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["rehearsalTimings"], {"HOOK": 58})

    def test_duration_seconds_is_accepted_as_a_synonym_for_seconds(self):
        doc = [{"action": "set_rehearsal_timing", "slideRole": "ASK", "durationSeconds": 55}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["rehearsalTimings"], {"ASK": 55})

    def test_actual_seconds_is_accepted_as_a_synonym_for_seconds(self):
        """Mirrors `rehearse run`'s own direct CLI timings-document field
        name verbatim (`{"<slideId>": <actualSeconds>}`)."""
        doc = [{"action": "rehearse", "slideRole": "HOOK", "actualSeconds": 58}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["rehearsalTimings"], {"HOOK": 58})

    def test_slide_id_is_accepted_as_a_slide_reference_alias(self):
        doc = [{"action": "rehearse", "slideId": "slide:abc123", "actualSeconds": 42}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["rehearsalTimings"], {"slide:abc123": 42})

    def test_slide_order_is_accepted_as_a_slide_reference_alias(self):
        doc = [{"action": "rehearse", "slideOrder": 0, "actualSeconds": 30}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["rehearsalTimings"], {0: 30})

    def test_key_and_value_aliases_compose_freely_across_entries(self):
        doc = [
            {"action": "rehearse", "slideId": "slide:one", "actualSeconds": 30},
            {"action": "set_rehearsal_timing", "slideRole": "ASK", "seconds": 55},
            {"action": "rehearse", "slideOrder": 2, "duration": 90},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["rehearsalTimings"], {"slide:one": 30, "ASK": 55, 2: 90})

    def test_two_key_fields_at_once_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "rehearse", "slideRole": "HOOK", "slideId": "slide:x", "seconds": 58},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_two_value_fields_at_once_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "rehearse", "slideRole": "HOOK", "seconds": 58, "duration": 60},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_no_key_field_at_all_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "seconds": 58}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_no_value_field_at_all_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "rehearse", "slideRole": "HOOK"}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_an_unexpected_extra_field_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "rehearse", "slideRole": "HOOK", "seconds": 58, "notes": "extra"},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_repeated_resolved_key_via_different_alias_spellings_is_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([
                {"action": "set_rehearsal_timing", "slideRole": "HOOK", "seconds": 58},
                {"action": "rehearse", "slideRole": "HOOK", "actualSeconds": 60},
            ])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(ctx.exception.details["key"], "HOOK")


class RehearsalSlideResolutionUnitTests(unittest.TestCase):
    """Direct coverage of `_resolve_rehearsal_slide`'s three-way
    precedence (slideId, then slideRole, then slideOrder)."""

    def _slide(self, id_, role, order):
        from helpers import models
        return models.SlideSpec(id=id_, workspace_id="ws:x", deck_id="deck:x", beat_id=f"beat:{order}", order=order, role=role, layout="standard")

    def test_resolves_by_exact_slide_id_first(self):
        slides = [self._slide("slide:a", "HOOK", 0), self._slide("slide:b", "ASK", 1)]
        self.assertIs(scenario._resolve_rehearsal_slide("slide:b", slides), slides[1])

    def test_resolves_by_role_when_not_a_known_id(self):
        slides = [self._slide("slide:a", "HOOK", 0), self._slide("slide:b", "ASK", 1)]
        self.assertIs(scenario._resolve_rehearsal_slide("ask", slides), slides[1])

    def test_resolves_by_integer_order_as_a_last_resort(self):
        slides = [self._slide("slide:a", "HOOK", 0), self._slide("slide:b", "ASK", 1)]
        self.assertIs(scenario._resolve_rehearsal_slide(1, slides), slides[1])
        self.assertIs(scenario._resolve_rehearsal_slide("1", slides), slides[1])

    def test_returns_none_for_a_key_matching_nothing(self):
        slides = [self._slide("slide:a", "HOOK", 0)]
        self.assertIsNone(scenario._resolve_rehearsal_slide("NOT_A_ROLE", slides))


class RehearsalActionAliasEndToEndTests(unittest.TestCase):
    """End-to-end coverage through `run_scenario`: alias-shaped rehearsal
    timing entries drive the identical `rehearsal.run_rehearsal` call and
    still reach Stage exactly like the canonical `slideRole`/`seconds`
    shape already does."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_slide_id_and_actual_seconds_aliases_reach_stage_and_package(self):
        """`slideId` mirrors `rehearse run`'s own direct CLI timings-
        document convention (`{"<slideId>": <actualSeconds>}`) -- since a
        slide's own id is only known once compiled, the workspace is
        pre-created directly here (with the fixture's own brief) so its
        deterministic slide ids (`deck:<workspaceId>:<beatOrder>`, ARCH's
        own documented ID-stability scheme) can be computed *before*
        constructing the one-shot scenario document, entirely within a
        single `run_scenario` call (resuming that same pre-created
        workspace) -- never a second, separate run to compare against."""
        from helpers import workspace_mod

        base = json.loads(FIXTURE.read_text())
        timings = base.pop("rehearsalTimings")
        # "Primary route" (index 0, the one `selectRouteIndex: 0` picks)
        # is the fixture's own selected route -- beat order is its own
        # beats list position.
        beat_order_by_role = {b["role"]: i for i, b in enumerate(base["routeDrafts"][0]["beats"])}

        store = persistence.Store(root=self.root / "ws")
        ws, _ = workspace_mod.create_workspace(store, actor="Dr. Jamie Rivera", brief_payload=base["brief"])
        deck_id = f"deck:{ws.id}"

        doc = _as_field_list(base)
        for role, seconds in timings.items():
            slide_id = f"{deck_id}:{beat_order_by_role[role]}"
            doc.append({"action": "rehearse", "slideId": slide_id, "actualSeconds": seconds})

        report = scenario.run_scenario(store, doc, self.root / "report")

        self.assertTrue(report["ok"], report.get("refusal"))
        self.assertTrue(report["stageGate"]["passed"], report["stageGate"]["failedChecks"])
        self.assertIn("package", report)
        self.assertEqual(report["rehearsal"]["totalActualSeconds"], sum(timings.values()))
        self.assertEqual(len(report["rehearsal"]["perSlide"]), len(timings))

    def test_duration_alias_produces_the_identical_rehearsal_report(self):
        base = json.loads(FIXTURE.read_text())
        timings = base.pop("rehearsalTimings")
        doc = _as_field_list(base)

        seconds_report = scenario.run_scenario(
            persistence.Store(root=self.root / "seconds-root"),
            doc + [{"action": "rehearse", "slideRole": role, "seconds": s} for role, s in timings.items()],
            self.root / "seconds-report",
        )
        duration_report = scenario.run_scenario(
            persistence.Store(root=self.root / "duration-root"),
            doc + [{"action": "rehearse", "slideRole": role, "duration": s} for role, s in timings.items()],
            self.root / "duration-report",
        )
        self.assertEqual(
            seconds_report["rehearsal"]["totalActualSeconds"], duration_report["rehearsal"]["totalActualSeconds"],
        )

    def test_validation_for_impossible_values_is_preserved(self):
        """Widening the accepted field names never weakens validation --
        an unrecognized/ambiguous rehearsal entry is still a clean
        `VALIDATION_ERROR` through the full public CLI path."""
        doc = _as_field_list(json.loads(FIXTURE.read_text()))
        doc = [d for d in doc if "rehearsalTimings" not in d]
        doc.append({"action": "rehearse", "slideRole": "HOOK", "seconds": 58, "duration": 60})
        scenario_path = self.root / "impossible-rehearsal-scenario.json"
        scenario_path.write_text(json.dumps(doc))

        proc = _run_cli("run-scenario", "--scenario", str(scenario_path), "--workspace", str(self.root / "ws"))
        self.assertEqual(proc.returncode, 1)
        envelope = json.loads(proc.stdout)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
