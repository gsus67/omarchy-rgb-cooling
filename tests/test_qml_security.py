"""Static guards for the panel QML.

Sensor labels, device names and error messages come from hardware and engines.
Rich text would let such a string load remote images or links, so every text
element must render plain text, the QML must not reach the network on its own,
and the only process it may start is the plugin's own bootstrap.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_COMMAND = ('["python3", root.pluginDirectory + "/bootstrap.py", '
                     'root.pluginDirectory]')
ENGINES_COMMAND = '[root.enginesHelper, root.engineAction, "openrgb"]'
QML_FILES = sorted(path for path in ROOT.rglob("*.qml") if ".git" not in path.parts)
# Elements that interpret markup unless told otherwise.
TEXT_ELEMENTS = ("Text", "TextEdit", "Label", "Controls.Label", "Controls.TextArea", "TextArea")
OPENING = re.compile(r"^(\s*)(%s)\s*\{" % "|".join(re.escape(name) for name in TEXT_ELEMENTS))


def text_blocks(source):
    """Yield (line number, element, block text) for each text element."""
    lines = source.splitlines()
    for index, line in enumerate(lines):
        match = OPENING.match(line)
        if not match:
            continue
        depth, block = 0, []
        for current in lines[index:]:
            block.append(current)
            depth += current.count("{") - current.count("}")
            if depth <= 0:
                break
        yield index + 1, match.group(2), "\n".join(block)


class QmlSecurityTest(unittest.TestCase):
    def test_qml_files_found(self):
        self.assertTrue(QML_FILES, "no QML files to check")

    def test_text_elements_are_plain_text(self):
        for path in QML_FILES:
            for line, element, block in text_blocks(path.read_text()):
                with self.subTest(file=path.name, line=line):
                    self.assertIn("textFormat: Text.PlainText", block,
                                  f"{path.name}:{line} {element} must set "
                                  "textFormat: Text.PlainText")

    def test_no_rich_text_formats(self):
        for path in QML_FILES:
            for number, line in enumerate(path.read_text().splitlines(), 1):
                with self.subTest(file=path.name, line=number):
                    markup = r"\b(RichText|StyledText|AutoText|MarkdownText)\b"
                    self.assertIsNone(re.search(markup, line),
                                      f"{path.name}:{number} uses a markup text format")

    def test_no_remote_urls(self):
        for path in QML_FILES:
            for number, line in enumerate(path.read_text().splitlines(), 1):
                with self.subTest(file=path.name, line=number):
                    self.assertNotRegex(line, r"https?://",
                                        f"{path.name}:{number} references a remote URL")

    def test_only_known_processes(self):
        """The panel runs only bootstrap and the engines helper, with fixed arguments."""
        allowed = {BOOTSTRAP_COMMAND, ENGINES_COMMAND}
        for path in QML_FILES:
            source = path.read_text()
            with self.subTest(file=path.name):
                self.assertNotRegex(source, r"\bexecDetached\b",
                                    f"{path.name} must not detach processes")
                self.assertNotRegex(source, r"\.command\s*=",
                                    f"{path.name} must not build commands at runtime")
                commands = re.findall(r"^\s*command:\s*(.+)$", source, re.MULTILINE)
                for command in commands:
                    self.assertIn(command.strip(), allowed,
                                  f"{path.name} starts an unexpected process: {command.strip()}")

    def test_engine_actions_are_a_closed_list(self):
        source = (ROOT / "RgbCooling.qml").read_text()
        self.assertIn('readonly property var engineActions: ["status", "install", "uninstall"]',
                      source)
        self.assertIn("if (engineProc.running || engineActions.indexOf(action) < 0) return",
                      source)
        self.assertIn('readonly property string enginesHelper: pluginDirectory '
                      '+ "/bin/omarchy-rgb-engines"', source)

    def test_core_lines_are_bounded(self):
        source = (ROOT / "RgbCooling.qml").read_text()
        self.assertIn("if (line.length > maxLine)", source, "reject over-long lines from rgbcd")
        self.assertIn("readonly property int maxLine: 65536", source)

    def test_socket_lives_in_the_runtime_dir(self):
        source = (ROOT / "RgbCooling.qml").read_text()
        self.assertIn('Quickshell.env("XDG_RUNTIME_DIR") || "") + "/omarchy-rgb-cooling.sock"',
                      source)


if __name__ == "__main__":
    unittest.main()
