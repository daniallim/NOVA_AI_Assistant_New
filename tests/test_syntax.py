import ast
from pathlib import Path


def test_all_files_parse():
    root = Path(__file__).resolve().parent.parent
    for f in root.glob("*.py"):
        ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
