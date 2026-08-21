#!/usr/bin/env python3
"""Compile editor/character.ui to editor/ui_character.py.

    tools/genui.py [--check]

`--check` regenerates into memory and fails if the committed file differs,
which is what CI wants. The editor calls `ensure_current()` at startup, so in
normal use this never has to be run by hand -- edit the .ui in Qt Designer,
restart the editor, done.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ROOT / "editor" / "character.ui"
PY = ROOT / "editor" / "ui_character.py"


def compile_ui(ui: pathlib.Path = UI) -> str:
    """Run pyuic6 and return the generated source."""
    out = subprocess.run([sys.executable, "-m", "PyQt6.uic.pyuic", str(ui)],
                         capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr.strip() or "pyuic6 failed")
    return out.stdout


def ensure_current(ui: pathlib.Path = UI, py: pathlib.Path = PY) -> bool:
    """Regenerate if the .ui is newer. Returns True if it wrote.

    This is why there is no build step to forget: rearrange the form in
    Designer, restart, and the running editor is already the new layout.
    """
    if not ui.exists():
        return False
    if py.exists() and py.stat().st_mtime >= ui.stat().st_mtime:
        return False
    py.write_text(compile_ui(ui))
    return True


def body(source: str) -> str:
    """The generated code without pyuic6's header.

    The header carries the absolute path of the `.ui` and the PyQt6 version, so
    a byte comparison fails on any machine but the one that last generated the
    file. CI is exactly that machine, and the drift worth catching is in the
    widgets, not in the banner.
    """
    lines = source.splitlines(keepends=True)
    while lines and (lines[0].startswith("#") or not lines[0].strip()):
        lines.pop(0)
    return "".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    source = compile_ui()
    if "--check" in argv:
        if not PY.exists() or body(PY.read_text()) != body(source):
            print(f"{PY.name} is stale; run tools/genui.py", file=sys.stderr)
            return 1
        print(f"{PY.name} is up to date")
        return 0
    PY.write_text(source)
    print(f"{UI.name} -> {PY.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
