#!/usr/bin/env python3
"""Regenerate THIRD_PARTY_LICENSES.md from ui/icons.py.

The attribution list is generated rather than hand-written because
game-icons.net's glyphs are CC BY 3.0 and attribution is the whole of what that
licence asks for: a list that has drifted from what ships looks discharged and
is not. `ui.icons.ARTISTS` names who drew each glyph, so the file says exactly
what the program draws. Re-run after adding an icon:

    python3 tools/genlicenses.py

`--check` regenerates into memory and fails if the committed file differs,
which is what `tests/test_licenses.py` runs.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wish import licenses

OUT = pathlib.Path(__file__).resolve().parent.parent / "THIRD_PARTY_LICENSES.md"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    text = licenses.markdown()
    if "--check" in argv:
        if not OUT.exists():
            print(f"{OUT.name} is missing")
            return 1
        if OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.name} is out of date")
            return 1
        return 0
    # `newline=` so a run on Windows does not rewrite every line ending
    # and make the file differ from what Linux generated.
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
