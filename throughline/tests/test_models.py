"""State-machine transition tables (ARCH §15 open-test requirement) and
pure model/serialization behavior."""
from __future__ import annotations

import unittest

from helpers import models


class SourceStateMachineTests(unittest.TestCase):
    def test_main_path_is_fully_reachable_in_order(self):
        path = models.SOURCE_MAIN_PATH
        for i in range(len(path) - 1):
            self.assertIn(path[i + 1], models.SOURCE_TRANSITIONS[path[i]], f"{path[i]} should reach {path[i + 1]}")

    def test_every_main_path_state_can_reach_every_exception_state(self):
        for state in models.SOURCE_MAIN_PATH:
            for exc in models.SOURCE_EXCEPTION_STATES:
                self.assertTrue(
                    models.is_reachable(models.SOURCE_TRANSITIONS, state, exc),
                    f"{state} should be able to reach exception state {exc}",
                )

    def test_retired_is_terminal(self):
        self.assertEqual(models.SOURCE_TRANSITIONS[models.SourceState.RETIRED], set())

    def test_cannot_skip_permission_checked(self):
        # PROPOSED can only go forward one step (to PERMISSION_CHECKED) or to an exception state.
        allowed = models.SOURCE_TRANSITIONS[models.SourceState.PROPOSED]
        self.assertNotIn(models.SourceState.CURATED, allowed)
        self.assertNotIn(models.SourceState.APPROVED, allowed)

    def test_quarantined_and_stale_can_return_to_authorized(self):
        self.assertIn(models.SourceState.AUTHORIZED, models.SOURCE_TRANSITIONS[models.SourceState.QUARANTINED])
        self.assertIn(models.SourceState.AUTHORIZED, models.SOURCE_TRANSITIONS[models.SourceState.STALE])


class ClaimStateMachineTests(unittest.TestCase):
    def test_main_path_is_fully_reachable_in_order(self):
        path = models.CLAIM_MAIN_PATH
        for i in range(len(path) - 1):
            self.assertIn(path[i + 1], models.CLAIM_TRANSITIONS[path[i]])

    def test_locked_is_immutable_except_explicit_rewrite(self):
        self.assertEqual(models.CLAIM_TRANSITIONS[models.ClaimState.LOCKED], {models.ClaimState.REWRITE_REQUIRED})

    def test_retired_is_terminal(self):
        self.assertEqual(models.CLAIM_TRANSITIONS[models.ClaimState.RETIRED], set())

    def test_unsupported_can_recover_via_evidence_linked(self):
        self.assertIn(models.ClaimState.EVIDENCE_LINKED, models.CLAIM_TRANSITIONS[models.ClaimState.UNSUPPORTED])

    def test_every_pre_locked_main_state_can_reach_every_exception(self):
        for state in models.CLAIM_MAIN_PATH:
            if state == models.ClaimState.LOCKED:
                continue
            for exc in models.CLAIM_EXCEPTION_STATES:
                self.assertTrue(models.is_reachable(models.CLAIM_TRANSITIONS, state, exc), f"{state} -> {exc}")


class SerializationRoundTripTests(unittest.TestCase):
    def test_dataclass_from_dict_round_trips_nested_structures(self):
        beat = models.Beat(id="beat:1", route_id="route:1", order=0, role="HOOK", headline="Hi", claim_ids=["claim:1"])
        route = models.NarrativeRoute(id="route:1", workspace_id="workspace:1", throughline_id="t:1", label="R", beats=[beat])
        data = models.to_jsonable(route)
        rebuilt = models.dataclass_from_dict(models.NarrativeRoute, data)
        self.assertEqual(rebuilt.label, "R")
        self.assertEqual(len(rebuilt.beats), 1)
        self.assertIsInstance(rebuilt.beats[0], models.Beat)
        self.assertEqual(rebuilt.beats[0].claim_ids, ["claim:1"])

    def test_to_jsonable_handles_optional_nested_dataclass(self):
        asset = models.DemoAsset(slide_id="slide:1", live_path="p")
        slide = models.SlideSpec(
            id="slide:1", workspace_id="w:1", deck_id="deck:1", beat_id="beat:1", order=0,
            role="MECHANISM", layout="standard", is_demo=True, demo_asset=asset,
        )
        data = models.to_jsonable(slide)
        self.assertEqual(data["demo_asset"]["live_path"], "p")
        rebuilt = models.dataclass_from_dict(models.SlideSpec, data)
        self.assertIsInstance(rebuilt.demo_asset, models.DemoAsset)
        self.assertEqual(rebuilt.demo_asset.live_path, "p")

    def test_ids_are_structurally_deterministic(self):
        deck_id = models.deck_id("workspace:abc")
        slide_id = models.slide_id(deck_id, 3)
        region_id = models.region_id(slide_id, "headline")
        self.assertEqual(deck_id, "deck:workspace:abc")
        self.assertEqual(slide_id, "deck:workspace:abc:3")
        self.assertEqual(region_id, "deck:workspace:abc:3:headline")


if __name__ == "__main__":
    unittest.main()
