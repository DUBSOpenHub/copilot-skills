"""Gate Runner: contrast math against known color pairs, and each gate's
positive-pass path."""
from __future__ import annotations

import unittest

from helpers import cleanup, gates, make_workspace, new_store


class ContrastMathTests(unittest.TestCase):
    def test_black_on_white_is_max_contrast(self):
        ratio = gates.contrast_ratio("#000000", "#FFFFFF")
        self.assertAlmostEqual(ratio, 21.0, places=1)

    def test_white_on_white_is_minimum_contrast(self):
        ratio = gates.contrast_ratio("#FFFFFF", "#FFFFFF")
        self.assertAlmostEqual(ratio, 1.0, places=2)

    def test_known_wcag_pair_matches_published_ratio(self):
        # #767676 on #FFFFFF is WCAG's own canonical "just barely passes
        # 4.5:1" reference pair.
        ratio = gates.contrast_ratio("#767676", "#FFFFFF")
        self.assertGreaterEqual(ratio, 4.5)
        self.assertLess(ratio, 4.6)

    def test_template_theme_colors_pass_readiness_thresholds(self):
        body_ratio = gates.contrast_ratio(gates.FOREGROUND_HEX, gates.BACKGROUND_HEX)
        headline_ratio = gates.contrast_ratio(gates.ACCENT_HEX, gates.BACKGROUND_HEX)
        self.assertGreaterEqual(body_ratio, 4.5)
        self.assertGreaterEqual(headline_ratio, 3.0)

    def test_contrast_ratio_is_symmetric(self):
        self.assertAlmostEqual(
            gates.contrast_ratio("#123456", "#FEDCBA"),
            gates.contrast_ratio("#FEDCBA", "#123456"),
        )


class GateStatusTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_scope_gate_passes_with_no_sources(self):
        ws, brief, conn = make_workspace(self.store)
        result = gates.run_gate(conn, ws.id, "scope", actor="T")
        self.assertTrue(result.passed)
        conn.close()

    def test_gate_status_reflects_latest_run(self):
        ws, brief, conn = make_workspace(self.store)
        gates.run_gate(conn, ws.id, "scope", actor="T")
        statuses = gates.gate_status(conn, ws.id)
        self.assertTrue(any(g.gate == "SCOPE" and g.passed for g in statuses))
        conn.close()

    def test_unknown_gate_name_rejected(self):
        from engine.errors import EngineError
        ws, brief, conn = make_workspace(self.store)
        with self.assertRaises(EngineError):
            gates.run_gate(conn, ws.id, "not-a-real-gate", actor="T")
        conn.close()


if __name__ == "__main__":
    unittest.main()
