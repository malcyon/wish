#!/usr/bin/env python3
"""Open Wish's window on the Windows 11 VM's own desktop.

Runs **inside the guest**, started by `winwishtask.ps1 -Action start`, which
puts it in session 1 through a scheduled task -- a GUI started from an SSH
shell lands in session 0 and is on a window station nobody can see.
`tools/winwish.py` copies it there and drives the rest; it is run in the guest
as `pythonw.exe winwishrun.py`, with no arguments.

The party it opens is `_ordinary_party` from `tests/test_windowslayout.py`,
written to a disk by `winwishmeasure.py`: six characters at a size a player
would actually see, which is the kind of window
`#474 (Raising the UI font grows the window's minimum width with an ordinary
party open, which is the defect #41 removed for the widest one)` is about. An
empty window shows none of what is being decided.

`pythonw.exe` has no console, so anything written to stdout or stderr would go
nowhere and a traceback would be silence. Both are pointed at a log file before
Qt is imported. The argument parser takes no options: it exists so that
`--help` or a stray argument stops here, before a window opens, and is not
something anybody runs by hand.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(r"C:\Wish\wish")
SAVE = pathlib.Path(r"C:\Wish\ORDINARY.D64")
LOG = pathlib.Path(r"C:\Wish\window.log")


def main(argv=None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)

    log = open(LOG, "w", buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = log
    sys.stderr = log
    sys.path.insert(0, str(ROOT))

    print("root:", ROOT)
    print("save:", SAVE, "exists:", SAVE.exists())

    from wish.__main__ import main as wish_main

    print("starting")
    try:
        code = wish_main(["--tab", "editor", str(SAVE)])
    except BaseException:
        import traceback
        traceback.print_exc()
        raise
    print("exit:", code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
