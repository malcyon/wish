#!/usr/bin/env python3
"""Draw the combat canvas with candidate labels in the squares, at three cell sizes.

Kept from `#345 (Draw a letter in each combat-map square saying what is standing
there, instead of the index the backend counts with)`. It builds
`tests/gamedata`'s synthetic arena with ten fighters, swaps `Combatant.hp_text`
for a label table (`F/MU`, `C/F/MU`, `7LDF`, ...) in this process only, and
draws the canvas offscreen at its minimum size, at its size hint and at
1400x900, writing each PNG and a crop of the occupied rows beside it. It prints
the cell size and the font point size the drawing used, which is how a label
too wide for its square shows up.

    tools/gui/combatlabelroomshot.py OUTDIR

No emulator and no game disk: the arena is synthetic. The pictures go under the
directory named; `tools/scratch.py`'s `scratch_dir` is the place for it.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from automap import combat  # noqa: E402
from automap.target import MemoryTarget  # noqa: E402

LABELS = {0: "F/MU", 1: "C/F/MU", 2: "MU", 3: "F", 8: "G", 9: "GL", 10: "7LDF",
          11: "O", 12: "OL", 13: "DB"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=pathlib.Path,
                        help="directory the PNGs are written to")
    args = parser.parse_args(argv)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from gamedata import synthetic_arena
    from PyQt6.QtCore import QSize
    from PyQt6.QtWidgets import QApplication

    from automap.window import CombatCanvas

    app = QApplication([])  # noqa: F841  (has to outlive the widgets)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    fighters = tuple((i, 24 + (k % 5) * 2, 12 + (k // 5) * 2)
                     for k, i in enumerate(LABELS))
    battle = combat.read_battle(MemoryTarget(synthetic_arena(fighters)))
    orig = combat.Combatant.hp_text
    combat.Combatant.hp_text = property(
        lambda self: LABELS.get(self.index, orig.fget(self)))
    shots = []
    try:
        for name, size in (("min", None), ("hint", "hint"),
                           ("big", QSize(1400, 900))):
            c = CombatCanvas()
            c.show_battle(battle)
            c.resize(c.minimumSize() if size is None
                     else c.sizeHint() if size == "hint" else size)
            img = c.grab().toImage()
            shots.append((name, c.drawn_cell, c.cell, img))
            img.save(str(out / f"room-{name}.png"))
            print(name, "drawn_cell", c.drawn_cell, "self.cell", c.cell,
                  "font pt", max(7, int(c.cell * 0.36)), img.size())
        # crop the occupied rows so they can be looked at side by side
        for name, cell, _, img in shots:
            w, h = img.width(), img.height()
            crop = img.copy(0, 0, min(w, 24 * cell + 40), min(h, 8 * cell + 40))
            crop.save(str(out / f"room-{name}-crop.png"))
    finally:
        combat.Combatant.hp_text = orig
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
