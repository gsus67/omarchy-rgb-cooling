"""Every string the panel translates has a Spanish entry, and nothing extra."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class I18nTest(unittest.TestCase):
    def test_catalog_matches_qml(self):
        used = set()
        for path in ROOT.rglob("*.qml"):
            used |= set(re.findall(r'\bt\("((?:[^"\\]|\\.)*)"\)', path.read_text()))
        catalog = json.loads((ROOT / "i18n/messages.json").read_text())
        self.assertEqual(set(catalog), {"es"})
        self.assertEqual(sorted(used - set(catalog["es"])), [], "missing translations")
        self.assertEqual(sorted(set(catalog["es"]) - used), [], "unused translations")


if __name__ == "__main__":
    unittest.main()
