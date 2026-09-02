#!/usr/bin/env python3
"""Draw one automapper roster card in a state no save can produce, and say
what the column cuts off.

A card carries a name, a class and level, the quickfight badge and the Level
up button on its top row, and its readied items with the condition badges at
the right-hand end of the line under it. Which of those survive the 220px
column depends on how many badges are lit, how much is readied and whether the
character has earned a level -- and **no saved game on this machine has a
character with every condition running**, so the states that decide it cannot
be photographed from one. This writes the state by hand, the same way
`tools/shotstrip.py` writes an effect table by hand.

    tools/rostercard.py                       today's worst case, as numbers
    tools/rostercard.py --badges 0 --no-readied
    tools/rostercard.py --width 300 --out work/card.png
    tools/rostercard.py --font +6             about Windows' base font

What it prints is where each part of the card ends up: **whole**, **cut (N of
Mpx)**, or **gone** past the column's right edge -- the sentence a person can
act on, rather than a width they have to interpret.
`#161 (Five condition badges push the class, the level and the Level up
button off the roster card)` and `#168 (A character who has earned a level
shows 32px of the Level up button)` were both settled by reading this at
several badge counts, and both are closed; what it is for now is asking
whether they have come back. `#77`'s cap means the answer is not the same at
every interface font, so `--font` is the second question and not an
afterthought.

Offscreen, against a throwaway config, and with no game disks needed: the
party is made up, so this runs anywhere.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))
sys.path.insert(0, str(TOOLS))

# Importing this is what forces the process offscreen and gives it a throwaway
# config directory: both run at its import time, and they have to happen
# before Qt is imported at all.
import shotwindow  # noqa: E402
from PyQt6.QtCore import QPoint  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from automap import live, paths  # noqa: E402
from wish.session import Session  # noqa: E402
from wish.window import MAP_TAB, WishWindow  # noqa: E402

NAME = "LADY KATHERINE"
#: A triple-class character, which is what makes the class label long.
CLASSES = tuple(live.ClassProgress(n, 8, 100_000, 0.5, 90_000)
                for n in ("magic-user", "cleric", "thief"))
READIED = ("BANDED MAIL +1", "SHIELD +2", "LONG SWORD +3")
#: The badges a *living* character can show, in the order a card draws them;
#: the two after are dead and drained, so the pair only a corpse carries is
#: reached by asking for every one of them.
LIVING = tuple(glyph for glyph, _ in live.CONDITION_BADGES)
BADGES = LIVING + ("death-skull", "oppression")


def character(slot: int, readied, quickfight: bool) -> live.Character:
    return live.Character(slot=slot, name=NAME, classes=CLASSES, level=8,
                          armour_class=-3, thac0=5, hp=41, hp_max=99,
                          experience=100_000, readied=readied,
                          quickfight=quickfight)


def build(app, *, party=8, readied=READIED, badges=len(LIVING), width=None,
          quickfight=True, levelling=True, height=1100):
    """A window whose roster column is in the state asked for."""
    home = pathlib.Path(shotwindow._CONFIG.name) / "home"
    home.mkdir(exist_ok=True)
    paths._home = lambda: home
    win = WishWindow(None, maps={}, tab=MAP_TAB,
                     session=Session(find=lambda pref=None: None))
    win.show()
    for _ in range(3):
        app.processEvents()
    roster = win.map.roster
    for card in roster.cards:
        card.levelling = levelling
    roster.show_snapshot(live.Snapshot(
        characters=tuple(character(i, readied, quickfight)
                         for i in range(party)),
        effects=(), x=1, y=1, facing=0, clock_text="10:15",
        area_file="GEO04"))
    for card in roster.cards[:party]:
        card.conditions.set_icons(BADGES[:badges])
    if width is not None:
        # `#162` made the three columns a draggable splitter, so widening the
        # roster is what a user's drag does: give the splitter the sizes,
        # rather than raising a maximum the column no longer has.
        splitter = win.map.columns.splitter
        sizes = splitter.sizes()
        sizes[win.map.columns.ROSTER_AT] = width
        splitter.setSizes(sizes)
    widget = roster.cards[0].frame
    while widget is not None:
        widget.updateGeometry()
        widget = widget.parentWidget()
    floor = shotwindow.floor_of(win)
    win.resize(max(floor.width(), 900), max(floor.height(), height))
    for _ in range(3):
        app.processEvents()
    return win, roster


def close(app, win) -> None:
    # Not `close()`: that asks about unsaved changes, and an offscreen message
    # box is a run that never ends.
    win.session.close()
    win.hide()
    win.deleteLater()
    app.processEvents()


def state(win, roster) -> tuple[int, list[str]]:
    """The column's width, and where each part of the card's row ends up."""
    card = roster.cards[0]
    viewport = win.ui.automap_roster_scroll.viewport()
    edge = viewport.width()

    def where(widget, label: str) -> str:
        if not widget.isVisible() or widget.width() == 0:
            return f"{label}: not shown"
        left = widget.mapTo(viewport, QPoint(0, 0)).x()
        if left + widget.width() <= edge:
            return f"{label}: whole"
        if left >= edge:
            return f"{label}: gone"
        return f"{label}: cut ({edge - left} of {widget.width()}px)"

    return edge, [where(card.name, "Name"),
                  where(card.klass, "Class and level"),
                  where(card.conditions, "Condition badges"),
                  where(card.quickfight, "Quickfight"),
                  where(card.level_up, "Level up")]


def strip(win, roster, cards: int) -> QImage:
    """The roster column as a picture, cropped under the `cards`th card."""
    column = win.ui.automap_roster
    last = roster.cards[cards - 1].frame
    bottom = last.mapTo(column, QPoint(0, last.height())).y() + 6
    scale = 2
    pixmap = QPixmap(column.width() * scale, column.height() * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(QColor("#0d141c"))
    column.render(pixmap)
    image = pixmap.toImage()
    # The pixmap carries a device pixel ratio of 2, so anything drawing it
    # back would halve it. Flatten it: from here one pixel is one pixel.
    image.setDevicePixelRatio(1)
    return image.copy(0, 0, image.width(),
                      min(bottom * scale, image.height()))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Draw a roster card in a chosen state and say what the "
                    "column cuts off.")
    ap.add_argument("--badges", type=int, default=len(LIVING), metavar="N",
                    help=f"condition badges lit, 0 to {len(BADGES)} "
                         f"(default: %(default)s, every one a living "
                         f"character can show; above that is a corpse)")
    ap.add_argument("--no-readied", action="store_true",
                    help="nothing in the character's hands")
    ap.add_argument("--no-quickfight", action="store_true",
                    help="drop the quickfight badge")
    ap.add_argument("--no-levelling", action="store_true",
                    help="a character who has not earned a level, so no "
                         "Level up button")
    ap.add_argument("--party", type=int, default=8, metavar="N",
                    help="characters in the party (default: %(default)s)")
    ap.add_argument("--width", type=int, default=None, metavar="PX",
                    help="widen the roster column to this, in place of its "
                         "220px cap")
    ap.add_argument("--font", type=float, default=0.0, metavar="PT",
                    help="points added to the interface font; +6 measures "
                         "here about like Windows' base font")
    ap.add_argument("--out", default=None, metavar="PNG",
                    help="also write a picture of the column here")
    ap.add_argument("--cards", type=int, default=1, metavar="N",
                    help="cards to keep in that picture (default: "
                         "%(default)s)")
    args = ap.parse_args(argv[1:])

    if not 0 <= args.badges <= len(BADGES):
        print(f"There are {len(BADGES)} badges, so --badges is 0 to "
              f"{len(BADGES)}.", file=sys.stderr)
        return 2

    app = QApplication.instance() or QApplication(["rostercard"])
    base = app.font()
    bigger = QFont(base)
    bigger.setPointSizeF(base.pointSizeF() + args.font)
    app.setFont(bigger)
    try:
        win, roster = build(app, party=args.party,
                            readied=() if args.no_readied else READIED,
                            badges=args.badges, width=args.width,
                            quickfight=not args.no_quickfight,
                            levelling=not args.no_levelling)
        try:
            edge, rows = state(win, roster)
            card = roster.cards[0].frame
            floor = win.minimumSizeHint()
            print(f"Interface font {bigger.pointSizeF():g}pt, "
                  f"{args.badges} badge{'' if args.badges == 1 else 's'}, "
                  f"{'nothing' if args.no_readied else 'a full hand'} readied")
            print(f"Column {edge}px, card asks for "
                  f"{card.minimumSizeHint().width()}x"
                  f"{card.minimumSizeHint().height()}, window floor "
                  f"{floor.width()}x{floor.height()}")
            for row in rows:
                print(f"    {row}")
            if args.out:
                image = strip(win, roster, min(args.cards, args.party))
                out = pathlib.Path(args.out)
                out.parent.mkdir(parents=True, exist_ok=True)
                if not image.save(str(out)):
                    print(f"Could not write {out}.", file=sys.stderr)
                    return 1
                print(f"Wrote {out}  ({image.width()}x{image.height()})")
        finally:
            close(app, win)
    finally:
        app.setFont(base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
