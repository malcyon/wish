#!/usr/bin/env python3
"""Compile every .ui file in the project to its ui_*.py companion.

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

#: Every directory that may contain .ui files. The search is explicit rather
#: than a recursive glob so that `.venv/`, `build/` and friends are never
#: touched, and so a new directory is a deliberate decision.
UI_DIRS = [
    ROOT / "editor",
    ROOT / "automap",
    ROOT / "wish",
]


def _py_for(ui: pathlib.Path) -> pathlib.Path:
    """The generated file that belongs to a .ui: ``<dir>/ui_<stem>.py``."""
    return ui.with_name(f"ui_{ui.stem}.py")


def discover() -> list[tuple[pathlib.Path, pathlib.Path]]:
    """Every (.ui, ui_*.py) pair in the project, in a stable order."""
    pairs = []
    for d in UI_DIRS:
        if not d.is_dir():
            continue
        for ui in sorted(d.glob("*.ui")):
            pairs.append((ui, _py_for(ui)))
    return pairs


def compile_ui(ui: pathlib.Path) -> str:
    """Run pyuic6 and return the generated source."""
    out = subprocess.run([sys.executable, "-m", "PyQt6.uic.pyuic", str(ui)],
                         capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr.strip() or "pyuic6 failed")
    return out.stdout


def ensure_current(ui: pathlib.Path | None = None,
                   py: pathlib.Path | None = None) -> bool:
    """Regenerate stale pairs. Returns True if anything was written.

    Called with no arguments, checks every pair in the project. Called with
    a specific (ui, py), checks only that one -- which is what
    `editor/__main__.py` still does.
    """
    if ui is not None and py is not None:
        pairs = [(ui, py)]
    else:
        pairs = discover()
    wrote = False
    for ui_path, py_path in pairs:
        if not ui_path.exists():
            continue
        if py_path.exists() and py_path.stat().st_mtime >= ui_path.stat().st_mtime:
            continue
        py_path.write_text(encoding="utf-8", data=compile_ui(ui_path))
        wrote = True
    return wrote


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
    pairs = discover()
    if not pairs:
        print("no .ui files found", file=sys.stderr)
        return 1
    failed = False
    for ui, py in pairs:
        source = compile_ui(ui)
        if "--check" in argv:
            if not py.exists() or body(py.read_text(encoding="utf-8")) != body(source):
                print(f"{py.name} is stale; run tools/genui.py",
                      file=sys.stderr)
                failed = True
            else:
                print(f"{py.name} is up to date")
        else:
            py.write_text(encoding="utf-8", data=source)
            print(f"{ui.name} -> {py.name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
