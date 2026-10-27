"""A minimal DMI identity tree, independent of the machine running the tests."""
from pathlib import Path


class DmiTree:
    def __init__(self, directory, vendor, board):
        self.root = Path(directory)
        self.root.mkdir(parents=True)
        self.write(vendor, board)

    def write(self, vendor, board):
        (self.root / "board_vendor").write_text(vendor + "\n")
        (self.root / "board_name").write_text(board + "\n")
