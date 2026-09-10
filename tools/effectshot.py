#!/usr/bin/env python3
"""Photograph the active-effects panel.

`.claude/rules/gui-text.md`: any interface decision Donald is asked to make
comes with a picture of it, and every string on this panel is his to word.
`QWidget.grab()` works offscreen, so this never puts a window on his screen --
run it the way the rule says:

    env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \
        GDK_BACKEND=x11 .venv/bin/python tools/effectshot.py work/issue13

**The effects in the picture are put there by this script**, into the save
image in memory and never onto a disk. Nothing on the player's save disks has
anything running: all 34 were swept on 2026-09-07 and every one of them has 64
free effect slots, which is what a save made outside a fight looks like. So a
picture of the panel with rows in it has to be composed, and this composes it
through the same reader the panel uses -- `goldbox.effects.active_effects`
over `SaveGame0` -- rather than by poking the model.

`#13 (Edit traits and active effects, in two separate panels)`, step S4.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

#: `(effect slot, id, owner, duration)`. The ids are all CONFIRMED names, and
#: the owners are the three shapes the panel has to tell apart: a character in
#: the party, everybody, and something that was in a fight. 253 is an id
#: nobody has named, which is the fourth row a reader has to be able to make
#: sense of. The durations are real bytes and none of them is shown.
COMPOSED = ((0, 1, None, 0x06),     # Bless, on the character named below
            (1, 35, 0xFF, 0x0A),    # under an allied Prayer, on everybody
            (2, 12, 9, 0x8B),       # Enlarge, on a monster
            (3, 253, None, 0x04))   # an id nobody has named


def main(out: pathlib.Path) -> int:
    import gamedata
    from PyQt6.QtWidgets import QApplication, QMainWindow

    from editor.window import EditorBinding
    from goldbox.effects import (
        EFFECT_DURATION_OFFSET,
        EFFECT_ID_OFFSET,
        EFFECT_OWNER_OFFSET,
    )
    from goldbox.savegame import SaveGame0
    from wish.ui_window import Ui_WishWindow

    src = gamedata.disk_path("PORSAVE11")
    if src is None:
        print("Needs the save disks; set POR_DISKS to where they are")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])

    work = pathlib.Path(tempfile.mkdtemp()) / "PORSAVE11.D64"
    shutil.copy(src, work)

    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    window = EditorBinding(root, str(work))
    root.resize(1875, 1030)
    # The Character Editor is the second main tab, and a tab that is not
    # current is never laid out -- a picture taken without this is the
    # automapper with an unarranged editor behind it.
    from PyQt6.QtWidgets import QTabWidget
    tabs = root.findChild(QTabWidget, "tabs")
    tabs.setCurrentIndex(next(i for i in range(tabs.count())
                              if tabs.tabText(i) == "Character Editor"))
    root.show()
    app.processEvents()

    # The case D1 was decided on: one character selected and the effect on a
    # different one. MALCYON is row 5 on this disk and row 0 is somebody else.
    party = window.party
    subject = next(m for m in party.members if m.name.strip() == "MALCYON")
    original = bytes(party.save0.to_bytes())
    payload = bytearray(original)
    for slot, code, owner, duration in COMPOSED:
        payload[EFFECT_ID_OFFSET + slot] = code
        payload[EFFECT_OWNER_OFFSET + slot] = (subject.index if owner is None
                                               else owner)
        payload[EFFECT_DURATION_OFFSET + slot] = duration
    party.save0 = SaveGame0.from_bytes(bytes(payload), party.game)

    window.roster.selectRow(0)
    window._show_active_effects()
    window._size_roster()
    app.processEvents()

    print(f"selected: {party.member(0).name.strip()};  "
          f"effects on: {subject.name.strip()}")
    for running, on in window._child("active_effects").rows():
        print(f"  {running}  |  {on}")

    box = window._child("box_active_effects")
    box.grab().save(str(out / "effects-panel.png"))
    window._child("editor_header").grab().save(str(out / "effects-header.png"))
    root.grab().save(str(out / "effects-window.png"))

    # And the empty state: the two headings over no rows, no sentence.
    party.save0 = SaveGame0.from_bytes(original, party.game)
    window._show_active_effects()
    window._size_roster()
    app.processEvents()
    box.grab().save(str(out / "effects-panel-empty.png"))

    for name in sorted(p.name for p in out.glob("effects-*.png")):
        print(out / name)
    return 0


if __name__ == "__main__":
    # `argparse` before anything imports Qt: `tests/test_toolhelp.py` requires
    # it of every tool that constructs a `QApplication`, because `--help` or a
    # mistyped argument reaching one would put a window on Donald's screen
    # while he is working. `main` does the Qt import itself, so nothing here
    # touches it until the arguments are known good.
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "out", nargs="?", default="work/issue13", type=pathlib.Path,
        help="directory to write the pictures into (default: work/issue13)")
    raise SystemExit(main(parser.parse_args().out))
