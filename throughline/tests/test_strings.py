"""NFR-1 / FR-INV-2: every user-facing string must say "GitHub Copilot
Throughline" or "GitHub Copilot" in full — never a bare "Copilot"."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from helpers import REPO_ROOT, strings


class NamingComplianceTests(unittest.TestCase):
    def test_is_compliant_detects_bare_copilot(self):
        self.assertFalse(strings.is_compliant("Ask Copilot to help."))
        self.assertTrue(strings.is_compliant("Ask GitHub Copilot to help."))
        self.assertTrue(strings.is_compliant("Ask GitHub Copilot Throughline to help."))

    def test_assert_compliant_raises_on_bare_copilot(self):
        with self.assertRaises(ValueError):
            strings.assert_compliant("Copilot did this.")
        strings.assert_compliant("GitHub Copilot did this.")  # should not raise

    def test_every_template_constant_is_compliant(self):
        for name in dir(strings):
            if name.startswith("_"):
                continue
            value = getattr(strings, name)
            if isinstance(value, str):
                self.assertTrue(strings.is_compliant(value), f"strings.{name} contains a bare 'Copilot'")

    def test_skill_md_is_compliant(self):
        text = (REPO_ROOT / "SKILL.md").read_text()
        # The frontmatter's own `name: throughline` line is fine; scan the
        # rendered body text only for the naming rule.
        self.assertTrue(strings.is_compliant(text), "SKILL.md contains a bare 'Copilot'")

    def test_readme_is_compliant(self):
        text = (REPO_ROOT / "README.md").read_text()
        self.assertTrue(strings.is_compliant(text))

    def test_docs_are_compliant(self):
        for doc in (REPO_ROOT / "docs").glob("*.md"):
            text = doc.read_text()
            self.assertTrue(strings.is_compliant(text), f"{doc} contains a bare 'Copilot'")

    def test_product_name_constants_are_exact(self):
        self.assertEqual(strings.PRODUCT_NAME, "GitHub Copilot Throughline")
        self.assertEqual(strings.PRODUCT_SHORT, "GitHub Copilot")


if __name__ == "__main__":
    unittest.main()
