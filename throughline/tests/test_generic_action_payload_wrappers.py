"""Regression tests for common action-list payload wrappers (Dark
Factory hardening cycle 7, `engine.scenario._unwrap_generic_action_wrapper`):
`params`, `payload`, and `input` are now accepted, unambiguous wrapper
keys for the two "whole payload is the item" action shapes -- a "list of
objects" field (e.g. `propose_claim` -> `claims`) and the single "object"
field (`set_talk_brief` -> `brief`) -- alongside the source descriptor's
own pre-existing `source`/`descriptor`/`value` wrappers, which this file
also extends to `params`/`payload`/`input`.

Compatibility gap this closes: a caller wrapping an action's fields in
one of these reserved container keys instead of giving them directly on
the action-list element (e.g. `{"action": "propose_claim", "payload":
{"type": "factual", "text": "..."}}`) previously either failed the
target's own field validation (the wrapper key itself became a bogus
"field") or -- for accessibility/demo-asset references read directly at
runtime rather than validated at normalization time -- was silently
dropped (`_match_slide` found no `slideId`/`slideOrder`/`slideRole` key
and the whole step was a silent no-op).
"""
from __future__ import annotations

import unittest

from helpers import EngineError, cleanup, new_root, persistence, scenario


class ClaimsListObjectWrapperTests(unittest.TestCase):
    """`propose_claim` targets `claims`, an `_ACTION_LIST_OBJECT_FIELDS`
    field -- the generic wrapper unwrap applies to it."""

    def test_params_wrapper_unwraps_to_the_claim_fields(self):
        doc = [{"action": "propose_claim", "params": {"type": "factual", "text": "Adoption grew 42%."}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["claims"], [{"type": "factual", "text": "Adoption grew 42%."}])

    def test_payload_wrapper_unwraps_to_the_claim_fields(self):
        doc = [{"action": "propose_claim", "payload": {"type": "factual", "text": "Adoption grew 42%."}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["claims"], [{"type": "factual", "text": "Adoption grew 42%."}])

    def test_input_wrapper_unwraps_to_the_claim_fields(self):
        doc = [{"action": "propose_claim", "input": {"type": "factual", "text": "Adoption grew 42%."}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["claims"], [{"type": "factual", "text": "Adoption grew 42%."}])

    def test_multiple_wrapped_claims_accumulate_in_order(self):
        doc = [
            {"action": "propose_claim", "payload": {"type": "factual", "text": "First."}},
            {"action": "propose_claim", "payload": {"type": "factual", "text": "Second."}},
        ]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual([c["text"] for c in merged["claims"]], ["First.", "Second."])

    def test_direct_fields_without_a_wrapper_are_unaffected(self):
        doc = [{"action": "propose_claim", "type": "factual", "text": "Unwrapped."}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["claims"], [{"type": "factual", "text": "Unwrapped."}])

    def test_a_wrapper_key_alongside_a_sibling_field_is_not_unwrapped(self):
        """Only unambiguous — exactly one key, and that key is a
        recognized wrapper — payloads are unwrapped; a wrapper mixed with
        a sibling field is left as-is (never a silent, partial unwrap)."""
        doc = [{"action": "propose_claim", "payload": {"type": "factual", "text": "X"}, "extra": "y"}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["claims"], [{"payload": {"type": "factual", "text": "X"}, "extra": "y"}])

    def test_a_wrapper_whose_value_is_not_an_object_is_not_unwrapped(self):
        doc = [{"action": "propose_claim", "payload": "not-an-object"}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["claims"], [{"payload": "not-an-object"}])

    def test_an_empty_wrapped_object_is_still_a_validation_error(self):
        with self.assertRaises(EngineError) as ctx:
            scenario._normalize_scenario_doc([{"action": "propose_claim", "payload": {}}])
        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_a_claim_proposed_via_a_wrapper_ingests_through_run_scenario(self):
        root = new_root()
        try:
            store = persistence.Store(root=root / "ws")
            doc = [
                {"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup", "durationMinutes": 20,
                 "takeaway": "T", "proofPoints": [], "excludedTopics": [], "tone": "confident"},
                {"action": "add_source", "origin": "local", "sourceType": "local_paste", "uri": "paste:a",
                 "owner": "a@example.com", "permissionState": "authorized", "aclSnapshot": "owner-only",
                 "version": "v1", "content": "Adoption grew 42 percent across every pilot team this quarter."},
                {"action": "propose_claim", "payload": {
                    "type": "factual", "text": "Adoption grew 42%.", "evidenceLocators": ["paste:a#p0"],
                }},
            ]
            report = scenario.run_scenario(store, doc, root / "report")
            self.assertEqual(len(report["claims"]), 1)
            self.assertEqual(report["claims"][0]["text"], "Adoption grew 42%.")
        finally:
            cleanup(root)


class BriefObjectWrapperTests(unittest.TestCase):
    """`set_talk_brief` targets `brief`, the single `_ACTION_OBJECT_FIELDS`
    field -- the generic wrapper unwrap applies to it too."""

    def test_payload_wrapper_unwraps_to_the_brief_fields(self):
        doc = [{"action": "set_talk_brief", "payload": {"audience": "Devs", "eventType": "meetup"}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["brief"], {"audience": "Devs", "eventType": "meetup"})

    def test_params_wrapper_unwraps_to_the_brief_fields(self):
        doc = [{"action": "set_talk_brief", "params": {"audience": "Devs", "eventType": "meetup"}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["brief"], {"audience": "Devs", "eventType": "meetup"})

    def test_direct_fields_without_a_wrapper_are_unaffected(self):
        doc = [{"action": "set_talk_brief", "audience": "Devs", "eventType": "meetup"}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["brief"], {"audience": "Devs", "eventType": "meetup"})


class AccessibilityWrapperNoLongerSilentlyDroppedTests(unittest.TestCase):
    """Before this hardening cycle, a wrapped `set_alt_text`/
    `set_demo_asset` entry normalized successfully (no `VALIDATION_ERROR`
    at all — `accessibility`/`demoAssets` are generic "list of objects"
    fields with no dedicated per-field validation) but was then silently
    a no-op at runtime: `_match_slide` found none of `slideId`/
    `slideOrder`/`slideRole` on the still-wrapped dict, so the whole step
    quietly did nothing. The generic unwrap now makes the wrapped shape
    behave identically to the unwrapped one instead of silently dropping
    it."""

    def test_a_wrapped_set_alt_text_entry_actually_applies(self):
        doc = [{"action": "set_alt_text", "payload": {"slideRole": "HOOK", "altText": "A custom description"}}]
        merged = scenario._normalize_scenario_doc(doc)
        self.assertEqual(merged["accessibility"], [{"slideRole": "HOOK", "altText": "A custom description"}])


if __name__ == "__main__":
    unittest.main()
