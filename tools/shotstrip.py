#!/usr/bin/env python3
"""Photograph the automapper's roster column with a chosen set of spells up.

`tools/shotwindow.py` draws the whole window, and it draws it with no
emulator -- so the party effects row along the bottom of the roster column is
always empty in it, which is the one thing this exists to look at. This builds
the same form, feeds `BottomStrip` an effect table it makes up, and grabs the
column.

Why a tool and not a throwaway: `CLAUDE.md` says a string has to be judged in
the running window rather than in the diff, and the party effects row is
icons and tooltips -- so every future change to a badge, a grouping or the
row's placement wants exactly this picture again.

    .venv/bin/python tools/shotstrip.py                     # every badge lit
    .venv/bin/python tools/shotstrip.py --effects 1 49      # Bless and Prayer
    .venv/bin/python tools/shotstrip.py --effects none      # nothing running
    .venv/bin/python tools/shotstrip.py --monsters 2        # and on monsters

The effect ids are `goldbox/traits.py`'s. Each one is written into the party
row -- owner `$FF` -- because **no save this project holds carries a
party-wide effect**: checked 2026-08-31, the only effect in any fixture is id
73 with owner `0x00`, which is a character. Making the table up here is what
lets the row be looked at at all.

**Output goes under `work/`, which is `.gitignore`d**, and the tooltip text is
printed to the terminal, because a `grab()` does not draw one.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile


def _offscreen() -> None:
    """Make it impossible for this process to draw on the user's desktop.

    Forced rather than defaulted, and `WAYLAND_DISPLAY` unset: a Qt child
    prefers Wayland over whatever is set for X, so a private X display is not
    a sandbox on its own. `tools/shotwindow.py` has the long version.
    """
    os.environ["QT_QPA_PLATFORM"] = os.environ.get("WISH_SHOT_PLATFORM",
                                                   "offscreen")
    if "WISH_SHOT_PLATFORM" not in os.environ:
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("XDG_SESSION_TYPE", None)
        os.environ["GDK_BACKEND"] = "x11"


_CONFIG = None


def _isolate_config() -> None:
    """Nothing this runs reads or writes the user's real settings."""
    global _CONFIG
    _CONFIG = tempfile.TemporaryDirectory(prefix="wish-shotstrip-")
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        os.environ[name] = _CONFIG.name


_offscreen()
_isolate_config()

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from automap import live  # noqa: E402
from automap.panel import BottomStrip  # noqa: E402
from automap.state import AutomapState  # noqa: E402
from wish.ui_window import Ui_WishWindow  # noqa: E402

#: One id out of each badge group, so the default picture is every glyph the
#: row can draw at once -- the widest it will ever be.
EVERY_BADGE = tuple(ids[0] for _glyph, ids in live.CONDITION_BADGES)


def snapshot(party, monsters: int):
    """A `Snapshot` carrying `party` as party-wide effects and `monsters` more.

    Only the effect table matters here; everything else is what an empty
    machine would answer, because the row reads nothing else.
    """
    effects = [live.Effect(slot=i, id=n, owner=live.PARTY_WIDE, duration=8,
                           magnitude=0)
               for i, n in enumerate(party)]
    effects += [live.Effect(slot=len(effects) + i, id=39,
                            owner=live.FIRST_MONSTER + i, duration=8,
                            magnitude=0)
                for i in range(monsters)]
    return live.Snapshot(characters=(), effects=tuple(effects), x=3, y=14,
                         facing=0, clock_text="", area_file="GEO00")


def shoot(app, party, monsters: int, zoom: int, full: bool):
    """Draw the roster column and return `(image, tooltip, icon names)`.

    Cropped to the strip by default -- the icon row, the square, the area name
    and the party strength line -- because the eight empty cards above it are
    nine tenths of the column and none of what is being judged. `--full` keeps
    them, for a question about where the row sits rather than what it says.
    """
    root = QMainWindow()
    ui = Ui_WishWindow()
    ui.setupUi(root)
    strip = BottomStrip(root)

    state = AutomapState()
    state.area = "GEO00"
    state.source, state.x, state.y = "status", 3, 14
    strip.show_state(state, snapshot(party, monsters))

    column = ui.automap_roster
    column.resize(column.sizeHint().width() or 260,
                  column.sizeHint().height())
    app.processEvents()
    image = column.grab().toImage()
    if not full:
        # From the top of the icon row to the bottom of the column. The row is
        # zero-high when nothing is running, so the crop starts from the
        # square instead and the picture still shows the gap it leaves.
        top = min(w.geometry().top()
                  for w in (ui.strip_effects, ui.strip_where) if w.height())
        image = image.copy(0, max(0, top - 4), image.width(),
                           image.height() - max(0, top - 4))
    if zoom > 1:
        image = image.scaled(image.width() * zoom, image.height() * zoom,
                             Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.FastTransformation)
    return image, strip.effects.toolTip(), strip.effects.names


def _ids(words) -> tuple[int, ...]:
    if len(words) == 1 and words[0].lower() == "none":
        return ()
    return tuple(int(w) for w in words)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Render the automapper's roster column offscreen, with a "
                    "made-up set of party-wide effects running.")
    ap.add_argument("out", nargs="?", default="work/strip.png",
                    help="where to write the PNG (default: %(default)s, "
                         "which is gitignored)")
    ap.add_argument("--effects", nargs="+", default=None, metavar="ID",
                    help="effect ids to run on the whole party, or the word "
                         "'none' (default: one from every badge group)")
    ap.add_argument("--monsters", type=int, default=0, metavar="N",
                    help="how many effects to put on monsters as well "
                         "(default: %(default)s)")
    ap.add_argument("--zoom", type=int, default=4, metavar="N",
                    help="scale the picture up by this, since the icons are "
                         "13px (default: %(default)s)")
    ap.add_argument("--full", action="store_true",
                    help="keep the whole roster column rather than cropping "
                         "to the strip")
    args = ap.parse_args(argv[1:])

    party = EVERY_BADGE if args.effects is None else _ids(args.effects)
    app = QApplication.instance() or QApplication(["shotstrip"])
    image, tip, names = shoot(app, party, args.monsters, args.zoom,
                              args.full)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(out))
    print(f"wrote {out}  ({image.width()}x{image.height()}, "
          f"zoom {args.zoom}x)")
    print(f"icons: {', '.join(names) or 'none'}")
    print("tooltip:")
    for line in (tip.splitlines() or ["(none)"]):
        print(f"    {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
