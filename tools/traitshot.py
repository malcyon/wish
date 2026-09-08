#!/usr/bin/env python3
"""Photograph the Character Traits box and its picker, with the flag on.

`.claude/rules/gui-text.md`: any interface decision Donald is asked to make
comes with a picture of it, and every string on both of these is his to word.
`QWidget.grab()` works offscreen, so this never puts a window on his screen --
run it the way the rule says:

    env -u WAYLAND_DISPLAY -u XDG_SESSION_TYPE QT_QPA_PLATFORM=offscreen \
        GDK_BACKEND=x11 .venv/bin/python tools/traitshot.py work/issue13

`#13 (Edit traits and active effects, in two separate panels)`, step S3.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["WISH_EXPERIMENTAL_TRAITS"] = "1"

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def main(out: pathlib.Path) -> int:
    import gamedata
    from PyQt6.QtWidgets import QApplication, QMainWindow

    from editor.traitpicker import TraitPicker
    from editor.window import EditorBinding
    from wish.ui_window import Ui_WishWindow

    src = gamedata.disk_path("PORSAVE11")
    if src is None:
        print("needs the save disks; set POR_DISKS to where they are")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])

    work = pathlib.Path(tempfile.mkdtemp()) / "PORSAVE11.D64"
    shutil.copy(src, work)

    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    window = EditorBinding(root, str(work))
    root.resize(1875, 1030)
    root.show()
    app.processEvents()
    window.roster.selectRow(5)               # MALCYON, an elf: 107 in slot 0
    view = window._widgets["item_effects"]
    view.add(20)                             # Resist Fire, so Remove lights up
    view.selectRow(1)
    app.processEvents()

    box = window._child("box_effects")
    box.grab().save(str(out / "traits-box.png"))
    root.grab().save(str(out / "traits-window.png"))

    picker = TraitPicker(window.party.game, tuple(view.codes()), root)
    picker.resize(560, 620)
    picker.show()
    app.processEvents()
    picker.grab().save(str(out / "traits-picker.png"))

    picker.filter_line.setText("poison")
    app.processEvents()
    picker.grab().save(str(out / "traits-picker-filtered.png"))

    # A monster's attack form, coloured, with its reason in the tooltip.
    picker.filter_line.setText("")
    app.processEvents()
    view.add(83)                             # petrifying gaze
    view.selectRow(2)
    app.processEvents()
    box.grab().save(str(out / "traits-box-warned.png"))

    for name in sorted(p.name for p in out.glob("*.png")):
        print(out / name)
    return 0


if __name__ == "__main__":
    where = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "work/issue13")
    raise SystemExit(main(where))
