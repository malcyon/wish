#!/usr/bin/env python3
"""Photograph the automapper's Messages panel, with a proposed line in it.

`.claude/rules/gui-text.md` asks for two things that are hard to do any other
way: look at a string **in the running window** before proposing it, and put a
picture in front of Donald whenever a decision about the interface is being
asked for. Neither is possible from the source, because the panel puts a
timestamp in front of every line and the combat log puts `round N` in front of
most of them, so a sentence that reads well in a constant can read badly in the
only place anybody sees it.

    .venv/bin/python tools/messageshot.py work/issue425/panel.png
    .venv/bin/python tools/messageshot.py --say "One line." shot.png

So this builds the real window offscreen, drives `tests/gamedata`'s arena
through a short fight so the panel holds the lines a player would actually be
reading, and grabs the panel with whatever candidate sentences were asked for
sitting among them. `--say` may be repeated, and each one is drawn as the
Messages panel would draw it, including its timestamp.

With no `--say` it photographs the panel that
`#425 (The Messages window logs a quarter of a fight when the player turns the
game's combat speed up)` builds: the warning `automap/window.COMBAT_TOO_FAST`
carries, shown by setting the game's combat speed to 0 in the arena's memory
and letting the window notice, which is the path a player takes.

No emulator and no game disks: the arena is generated from the format plus the
player's own saved records. The PNG goes under `work/`, which is gitignored.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile


def _offscreen() -> None:
    """Make it impossible for this process to draw on Donald's desktop.

    Copied from `tools/shotwindow.py`, and forced rather than defaulted for the
    same reason: a desktop that exports `QT_QPA_PLATFORM` for its own
    compositor would otherwise keep its own value. Unsetting `WAYLAND_DISPLAY`
    is the part that is easy to miss -- a Qt child prefers it over whatever is
    set for X, so a private X display is not a sandbox on its own.
    """
    os.environ["QT_QPA_PLATFORM"] = os.environ.get("WISH_SHOT_PLATFORM",
                                                   "offscreen")
    if "WISH_SHOT_PLATFORM" not in os.environ:
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("XDG_SESSION_TYPE", None)
        os.environ["GDK_BACKEND"] = "x11"


_CONFIG = None


def _isolate_config() -> None:
    """No run of this reads or writes the user's real settings."""
    global _CONFIG
    _CONFIG = tempfile.TemporaryDirectory(prefix="messageshot-")
    os.environ["XDG_CONFIG_HOME"] = _CONFIG.name
    os.environ["XDG_DATA_HOME"] = _CONFIG.name


_offscreen()
_isolate_config()

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PyQt6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from automap import combatlog  # noqa: E402
from automap.screen import SCREEN_COLS  # noqa: E402
from automap.state import Automapper  # noqa: E402
from automap.window import AutomapBinding  # noqa: E402
from wish.ui_window import Ui_WishWindow  # noqa: E402

#: The message panel's own geometry, the four bytes `COMBAT $0970` holds.
LEFT, RIGHT, BOTTOM = 23, 39, 23

#: A short fight, in the shape the game paints it: each entry is one repaint of
#: the message window, and the empty ones are the game clearing it, which is
#: what commits the block before it.
FIGHT = (["ORC", "ATTACKS", "BRUTUS AND", "MISSES..."],
         [],
         ["ORC", "ATTACKS", "MAGNUS AND", "HITS FOR 3", "POINTS OF", "DAMAGE"],
         [])


def _paint(target, rows) -> None:
    """Repaint the message window, as the game would between two polls."""
    from test_combatlog import painted  # the tests' own painter
    target.memory[combatlog.WINDOW] = bytes(
        [LEFT, RIGHT, combatlog.MESSAGE_TOP, BOTTOM])
    target.memory[0xCC00 + combatlog.MESSAGE_TOP * SCREEN_COLS] = painted(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("png", type=pathlib.Path)
    parser.add_argument("--say", action="append", default=[],
                        help="a candidate line, drawn as the panel draws it; "
                             "repeatable")
    parser.add_argument("--alarm", action="append", default=[],
                        help="the same, drawn in the panel's alarm colour")
    args = parser.parse_args()

    from gamedata import synthetic_arena
    from test_combatlog import MemoryTarget, machine

    memory = dict(synthetic_arena())
    memory.update(machine([]).memory)
    target = MemoryTarget(memory)

    app = QApplication.instance() or QApplication([])
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    window = AutomapBinding(root, Automapper(target, {}))
    for _ in range(window.LIVE_EVERY):
        window.tick()
    if window.battle is None:
        print("no fight started in the arena; nothing to photograph")
        return 1

    for frame in FIGHT:
        _paint(target, frame)
        window.tick()

    if args.say or args.alarm:
        for line in args.say:
            window.messages.say(line, dedup=False)
        for line in args.alarm:
            window.messages.say(line, dedup=False, alarm=True)
    else:
        # The player's own path: `FASTER` twice on the game's SPEED command.
        target.memory[combatlog.DELAY] = b"\x00"
        window.tick()
        window.tick()

    for frame in FIGHT:
        _paint(target, frame)
        window.tick()

    # The panel at the width the real window gives it, because a line that
    # fits a wide grab and is cut off in the window has not been looked at.
    root.resize(root.sizeHint())
    root.show()
    app.processEvents()
    panel = window.messages.list
    print(f"panel width in the window: {panel.width()}px")
    app.processEvents()
    args.png.parent.mkdir(parents=True, exist_ok=True)
    panel.grab().save(str(args.png))
    print(f"{args.png}  ({panel.width()}x{panel.height()})")
    for line in window.messages.lines():
        print("   ", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
