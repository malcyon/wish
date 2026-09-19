#!/usr/bin/env python3
"""The harness the `rostercard*` and `levelupstub*` scripts share: one
character, the same in every picture, built through the program's own
widgets, plus the helpers that stack captioned pictures into one PNG.

Written for `#161 (A roster card loses a character's classes and its Level up
button once four condition badges are lit)`, and reused for `#168 (A character
ready to level loses the Level up button, even with nothing running)`. It
renders through the real `WishWindow`, poking geometry and layout per variant;
no repository file is touched. `tools/gui/rostercard.py` was built from this
harness and is the one to run today -- these scripts are the ones that
produced the pictures and tables the two issues were settled by.

Not run on its own: every script that needs it does `from tools import
rostercardvariants as O`, and `O.application()` is the one call that points Qt
offscreen and the program's config at a scratch directory before a window is
built. Nothing happens at import.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QRectF, Qt  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QHBoxLayout,
    QVBoxLayout,
)

from automap import live, paths  # noqa: E402
from tools.registry import scratch  # noqa: E402
from wish.session import Session  # noqa: E402
from wish.window import MAP_TAB, WishWindow  # noqa: E402

OUT = scratch.scratch_dir("rostercardvariants")
NAME = "LADY KATHERINE"
CLASSES = tuple(live.ClassProgress(n, 8, 100_000, 0.5, 90_000)
                for n in ("magic-user", "cleric", "thief"))
READIED = ("BANDED MAIL +1", "SHIELD +2", "LONG SWORD +3")
#: The five a living character can show at once: hasted, blessed, warded,
#: invisible, strengthened. `live.CONDITION_BADGES` is the order a card draws.
BADGES = ("death-skull", "oppression") + tuple(g for g, _ in live.CONDITION_BADGES)
#: The five a *living* character can show; the two above are dead and drained.
LIVING = tuple(g for g, _ in live.CONDITION_BADGES)

CAP = 30
INK = QColor("#f2f4f7")
BG = QColor("#16202b")

QUICKFIGHT = [True]

#: The scratch config directory `application()` makes, kept alive for the run.
_CONFIG: tempfile.TemporaryDirectory | None = None


def parser(description: str) -> argparse.ArgumentParser:
    """The argument parser every script here starts from.

    `--help` on a script must not build a window, and building one is what
    every script does next, so each one parses before it asks for
    `application()`.
    """
    return argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter)


def application() -> QApplication:
    """Point Qt offscreen, the config at a scratch directory, and return the
    application.

    Offscreen and with Wayland unset, so nothing reaches Donald's screen;
    the config directories are a fresh temporary one so the program never
    reads or writes his own settings.
    """
    global _CONFIG
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("XDG_SESSION_TYPE", None)
    os.environ["GDK_BACKEND"] = "x11"
    if _CONFIG is None:
        _CONFIG = tempfile.TemporaryDirectory(prefix="wish-161-")
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        os.environ[name] = _CONFIG.name
    return QApplication.instance() or QApplication(["x"])


def character(slot: int, readied=READIED) -> live.Character:
    return live.Character(slot=slot, name=NAME, classes=CLASSES, level=8,
                          armour_class=-3, thac0=5, hp=41, hp_max=99,
                          experience=100_000, readied=readied,
                          quickfight=QUICKFIGHT[0])


def snapshot(party: int = 8, readied=READIED) -> live.Snapshot:
    return live.Snapshot(
        characters=tuple(character(i, readied) for i in range(party)),
        effects=(), x=1, y=1, facing=0, clock_text="10:15", area_file="GEO04")


def settle(app, win, times=3):
    for _ in range(times):
        app.processEvents()


def build(app, *, party=8, readied=READIED, badges=len(LIVING), width=None,
          quickfight=True, levelling=True,
          height=1100):
    home = pathlib.Path(_CONFIG.name) / "home"
    home.mkdir(exist_ok=True)
    paths._home = lambda: home
    win = WishWindow(None, maps={}, tab=MAP_TAB,
                     session=Session(find=lambda pref=None: None))
    win.show()
    settle(app, win)
    roster = win.map.roster
    QUICKFIGHT[0] = quickfight
    for card in roster.cards:
        card.levelling = levelling
    roster.show_snapshot(snapshot(party, readied))
    for card in roster.cards[:party]:
        card.conditions.set_icons((LIVING + BADGES[:2])[:badges])
    if width is not None:
        # `RosterPanel.ask_for_room` reads the column's own maximum and makes
        # it the scroll area's minimum, so raising the cap and asking again is
        # the whole of "widen the column".
        win.ui.automap_roster.setMaximumWidth(width)
        roster.ask_for_room(party)
    w = roster.cards[0].frame
    while w is not None:
        w.updateGeometry()
        w = w.parentWidget()
    floor = win.minimumSizeHint()
    win.resize(max(floor.width(), 900), max(floor.height(), height))
    settle(app, win)
    return win, roster


def close(app, win):
    win.session.close()
    win.hide()
    win.deleteLater()
    app.processEvents()


def crop(image: QImage, height: int, scale=2) -> QImage:
    """The top `height` logical pixels of a rendered image."""
    return image.copy(0, 0, image.width(), min(height * scale, image.height()))


def shot(widget, scale=2) -> QImage:
    """The widget, drawn at `scale` device pixels per logical pixel."""
    size = widget.size()
    pm = QPixmap(size.width() * scale, size.height() * scale)
    pm.setDevicePixelRatio(scale)
    pm.fill(QColor("#0d141c"))
    widget.render(pm)
    image = pm.toImage()
    # The pixmap carries a device pixel ratio of 2, so `drawImage` would draw
    # it back at half size and every height sum below would be double what is
    # painted. Flatten it: from here on one pixel is one pixel.
    image.setDevicePixelRatio(1)
    return image


WRAP = 940


def _font():
    f = QFont()
    f.setPointSize(9)
    return f


def _caption_height(text, width):
    fm = QFontMetrics(_font())
    r = fm.boundingRect(0, 0, width, 10_000,
                        int(Qt.AlignmentFlag.AlignLeft
                            | Qt.TextFlag.TextWordWrap), text)
    return r.height() + 12


def captioned(images, lines, out, gap=14):
    """Stack captioned images vertically into one PNG."""
    width = max(WRAP, max(i.width() for i in images) + 2 * gap)
    text_w = width - 2 * gap
    heads = [_caption_height(t, text_w) for t in lines]
    height = sum(i.height() + h for i, h in zip(images, heads)) \
        + gap * (len(images) + 1)
    canvas = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(BG)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(_font())
    y = gap
    for image, line, head in zip(images, lines, heads):
        p.setPen(QPen(INK))
        p.drawText(QRectF(gap, y, text_w, head),
                   int(Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                   line)
        y += head
        p.drawImage(gap, y, image)
        y += image.height() + gap
    p.end()
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    assert canvas.save(str(out)), out
    print(out)


def side_by_side(images, lines, out, gap=14):
    cols = len(images)
    col_w = max(max(i.width() for i in images),
                (WRAP - gap * (cols + 1)) // cols)
    head = max(_caption_height(t, col_w) for t in lines)
    width = col_w * cols + gap * (cols + 1)
    height = max(i.height() for i in images) + head + 2 * gap
    canvas = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(BG)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(_font())
    x = gap
    for image, line in zip(images, lines):
        p.setPen(QPen(INK))
        p.drawText(QRectF(x, gap, col_w, head),
                   int(Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                   line)
        p.drawImage(x, gap + head, image)
        x += col_w + gap
    p.end()
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    assert canvas.save(str(out)), out
    print(out)


# --------------------------------------------------------------- variants


def move_badges_to_own_row(roster, party=8):
    for card in roster.cards[:party]:
        lay: QVBoxLayout = card.frame.layout()
        top = card.frame.findChild(QHBoxLayout, f"card_{card.index}_top")
        top.removeWidget(card.conditions)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(card.conditions)
        row.addStretch(1)
        lay.insertLayout(1, row)


def move_badges_to_readied_row(roster, party=8):
    for card in roster.cards[:party]:
        lay: QVBoxLayout = card.frame.layout()
        top = card.frame.findChild(QHBoxLayout, f"card_{card.index}_top")
        top.removeWidget(card.conditions)
        idx = lay.indexOf(card.readied)
        lay.removeWidget(card.readied)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(card.readied, 1)
        row.addWidget(card.conditions, 0,
                      Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.insertLayout(idx, row)


def shorten_class(app, roster, party=8):
    for card in roster.cards[:party]:
        lab = card.klass
        lab.setText(lab.fontMetrics().elidedText(
            lab.text(), Qt.TextElideMode.ElideRight,
            lab.contentsRect().width()))
    app.processEvents()
