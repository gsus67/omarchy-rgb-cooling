"""Readable code is a CI rule: C++ and Python lines stay within 100 columns."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 100


def sources():
    patterns = ("src/*.cpp", "src/*.hpp", "*.py", "bin/*", "tests/*.py", "tests/fakes/*.py")
    return sorted(path for pattern in patterns for path in ROOT.glob(pattern))


class StyleTest(unittest.TestCase):
    def test_sources_found(self):
        self.assertTrue(sources(), "no sources to check")

    def test_line_length(self):
        for path in sources():
            for number, line in enumerate(path.read_text().splitlines(), 1):
                with self.subTest(file=str(path.relative_to(ROOT)), line=number):
                    where = f"{path.relative_to(ROOT)}:{number}"
                    self.assertLessEqual(len(line), LIMIT, f"{where} is over {LIMIT} columns")

    def test_no_trailing_whitespace(self):
        for path in sources():
            for number, line in enumerate(path.read_text().splitlines(), 1):
                with self.subTest(file=str(path.relative_to(ROOT)), line=number):
                    where = f"{path.relative_to(ROOT)}:{number}"
                    self.assertEqual(line, line.rstrip(), f"{where} has trailing whitespace")


if __name__ == "__main__":
    unittest.main()
