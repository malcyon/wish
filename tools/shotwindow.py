"""Photograph the editor's window offscreen, at a chosen UI font and width.

Issue #71 was decided by looking at three of these. Donald could not tell from
`minimumSizeHint()` whether a header squeezed to its floor was acceptable --
the numbers said 1447 and the picture said the Character box was drawing on top
of itself -- and the script that made the pictures lived in `/tmp` and is gone.
This is that script, kept.

Like `tools/iconsheet.py` it renders what the program ships, through the
program's own painting code: a real `WishWindow`, grabbed offscreen. What comes
out is what the program would do.

Three things it can answer that a test cannot:

* **what another machine's font does.** `--font +6` measures here about like
  Windows' base font -- CI answered 1447 where this machine answered 1451 at
  +6pt -- so a Windows-sized layout can be looked at without a Windows machine.
* **what the layout does at a width.** `--width` draws it there; where the
  floor is wider than the width asked for, Qt clamps and the report says what
  it was actually drawn at.
* **where the screen ends.** `--target` marks a line, so a window wider than a
  1280px laptop says so in the picture rather than in a number.

The caption strip carries the same numbers as the report, because a picture
pasted into an issue arrives without its terminal.

    .venv/bin/python tools/shotwindow.py                    # synthetic party
    .venv/bin/python tools/shotwindow.py --font +6
    .venv/bin/python tools/shotwindow.py --save work/PORSAVE11.D64 --tab map

The default party is `tests/gamedata.synthetic_party` -- six characters of the
widest shape the record allows -- so this runs on a machine with no game disks,
and the picture is the worst case rather than a plausible one.

**Output goes under `work/`, which is `.gitignore`d.** A synthetic party is
ours; a screenshot of Donald's own save is his data and neither belongs in the
repository.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile


def _offscreen() -> None:
    """Make it impossible for this process to draw on the user's desktop.

    Set before Qt is imported, and *forced* rather than defaulted: a desktop
    session that exports `QT_QPA_PLATFORM` for its own compositor -- COSMIC and
    KDE both do -- would otherwise keep its own value and get the real window
    this exists to prevent. `tests/conftest.py` learned that the hard way.

    Unsetting `WAYLAND_DISPLAY` is the part that is easy to miss: a Qt child
    prefers it over whatever is set for X, so a private X display is not a
    sandbox on its own.

    `WISH_SHOT_PLATFORM` is the way to mean it -- set it to `wayland` or `xcb`
    and that is used instead, so watching the window go by is one variable
    away.
    """
    os.environ["QT_QPA_PLATFORM"] = os.environ.get("WISH_SHOT_PLATFORM",
                                                   "offscreen")
    if "WISH_SHOT_PLATFORM" not in os.environ:
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("XDG_SESSION_TYPE", None)
        os.environ["GDK_BACKEND"] = "x11"


#: Held for the life of the process, so the throwaway config below is removed
#: at exit rather than left in `/tmp` once per run.
_CONFIG = None


def _isolate_config() -> None:
    """No run of this reads or writes the user's real settings.

    `automap/paths.py` reads the XDG pair on Linux and `APPDATA` on Windows.
    Pointing all four at a throwaway directory keeps a remembered window
    geometry out of the picture -- the size asked for is the size drawn -- and
    keeps anything this window writes on the way out away from his config.

    The game disks are found from `$HOME` and not from these, so a real save
    still gets its item names and its icons.
    """
    global _CONFIG
    _CONFIG = tempfile.TemporaryDirectory(prefix="wish-shotwindow-")
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        os.environ[name] = _CONFIG.name


_offscreen()
_isolate_config()

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))          # `gamedata.synthetic_party`

from PyQt6.QtCore import QRectF, Qt  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from wish.session import Session  # noqa: E402
from wish.window import EDITOR_TAB, MAP_TAB, WishWindow  # noqa: E402

TABS = {"editor": EDITOR_TAB, "map": MAP_TAB}

#: The screen the window has to fit, and what the marked line defaults to: the
#: 1280x720 laptop `tests/test_mapscale.py` calls SMALL.
TARGET = 1280

CAPTION_H = 34
MARK = QColor("#d02020")
CAPTION_BG = QColor("#16202b")
CAPTION_INK = QColor("#f2f4f7")


def floor_of(win) -> "QSize":  # noqa: F821
    """The window's `minimumSizeHint()`, asked so that it answers today's.

    `QLayout.activate()` pins a top-level window's `minimumSize` from the
    layout and does not un-pin it, so after anything that shrinks a child's
    minimum the hint keeps answering the old, larger number. Un-pin, invalidate
    and re-activate, and it answers the layout in front of it. This trap cost a
    prototype run during #71 and is written up in `tests/test_mapscale.py`'s
    `_floor`.
    """
    win.setMinimumSize(0, 0)
    layout = win.layout()
    if layout is not None:
        layout.invalidate()
        layout.activate()
    return win.minimumSizeHint()


def shoot(app, save: str | None, extra: float = 0.0, width: int | None = None,
          height: int | None = None, tab: int = EDITOR_TAB) -> tuple:
    """Draw the window and return `(image, floor, drawn)`.

    `extra` is points added to the UI font, `width` and `height` the size to
    draw at -- either defaulting to the window's own floor. `image` is the
    grab, without the caption strip.

    The font is set on the application *before* the window is built, because
    half of what the floor is made of is measured at construction.
    """
    base = app.font()
    bigger = QFont(base)
    bigger.setPointSizeF(base.pointSizeF() + extra)
    app.setFont(bigger)
    modals = _no_modals()
    try:
        # `maps={}` is not `maps=None`, and `WishWindow` only loads the maps
        # for the second: `{}` gave `--tab map` an empty automapper every
        # time, which is not what its own usage example shows. The editor tab
        # draws no map, so it keeps the empty dict and the load it saves.
        win = WishWindow(save, maps=None if tab == MAP_TAB else {}, tab=tab,
                         session=Session(find=lambda pref=None: None))
        try:
            # `EditorWindow.showEvent` calls `_size_roster` once, *after* the
            # window is shown -- so the roster's real column widths only exist
            # on the far side of this, and anything measured before it is a
            # different window's answer. The other #71 trap.
            win.show()
            app.processEvents()

            floor = floor_of(win)
            win.resize(width or floor.width(), height or floor.height())
            app.processEvents()

            pixmap: QPixmap = win.grab()
            drawn = (win.width(), win.height())
            return pixmap.toImage(), floor, drawn
        finally:
            # Not `close()`: that asks about unsaved changes, and an offscreen
            # message box is a run that never ends. But `closeEvent` is also
            # the only thing that stops the session, so do that by hand --
            # otherwise every call leaves a 1000ms `QTimer` ticking for the
            # life of the process, and under `--tab map` each one goes on
            # calling `attach()` once a second forever.
            win.session.close()
            win.hide()
            win.deleteLater()
            app.processEvents()
    finally:
        _restore_modals(modals)
        app.setFont(base)


#: What was asked and answered for us during the last `shoot`. A dialog the
#: program wanted to raise means something went wrong that a person would have
#: been told about, so the tool exits non-zero rather than leaving a picture
#: that looks like a successful run. An unreadable `--save` drew an empty
#: window and exited 0 before this.
SUPPRESSED: list[str] = []


def _no_modals():
    """Turn every blocking dialog into a line on stderr, for the whole run.

    `win.hide()` below avoids the one modal this tool was known to raise. It is
    not the only one: `EditorWindow.load` reports an unreadable save with
    `QMessageBox.critical`, which is a blocking `exec()` with nobody offscreen
    to dismiss it, so `--save` pointed at a file that is not a save hung until
    it was killed -- eight seconds of nothing, then exit 124.

    A dialog is how the *program* asks a person something. A tool with no
    person has to answer for itself, and the honest answer is to say what was
    asked and carry on.
    """
    saved = {}
    SUPPRESSED.clear()

    def refuse(name):
        def answer(*args, **kwargs):
            said = next((a for a in args if isinstance(a, str)), "")
            SUPPRESSED.append(f"{name}: {said}")
            print(f"shotwindow: suppressed {name} dialog: {said}",
                  file=sys.stderr)
            return QMessageBox.StandardButton.No
        return answer

    for name in ("critical", "warning", "information", "question", "about"):
        saved[name] = getattr(QMessageBox, name)
        setattr(QMessageBox, name, staticmethod(refuse(name)))
    return saved


def _restore_modals(saved) -> None:
    for name, was in saved.items():
        setattr(QMessageBox, name, was)


def caption(image: QImage, text: str, target: int | None) -> QImage:
    """The picture with its numbers along the top and the target line marked.

    The line is drawn only where the window is wider than the target: at 1280
    on a 1447px window it is the whole of what #71 was about, and on a window
    that fits it would be a mark on nothing.
    """
    out = QImage(image.width(), image.height() + CAPTION_H,
                 QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(CAPTION_BG)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    font = QFont()
    font.setPointSize(9)
    p.setFont(font)
    p.setPen(QPen(CAPTION_INK))
    p.drawText(QRectF(8, 0, image.width() - 16, CAPTION_H),
               int(Qt.AlignmentFlag.AlignVCenter), text)
    p.drawImage(0, CAPTION_H, image)

    if target is not None and image.width() > target:
        p.setPen(QPen(MARK, 2))
        p.drawLine(target, 0, target, out.height())
        p.setFont(font)
        p.setPen(QPen(MARK))
        p.drawText(QRectF(target + 4, CAPTION_H, 200, 18),
                   int(Qt.AlignmentFlag.AlignVCenter), f"{target}")
    p.end()
    return out


def _font_offset(text: str) -> float:
    return float(text.lstrip("+"))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Render the editor's window offscreen and write a PNG.")
    ap.add_argument("out", nargs="?", default="work/reports/window.png",
                    help="where to write the PNG (default: %(default)s, "
                         "which is gitignored)")
    ap.add_argument("--save", help="a saved game to open (default: the "
                                   "synthetic widest party, so this runs "
                                   "with no game disks)")
    ap.add_argument("--font", default="+0", type=_font_offset, metavar="+N",
                    help="points added to the UI font. +6 measures here about "
                         "like Windows' base font (default: +0)")
    ap.add_argument("--width", type=int,
                    help="the width to draw at (default: the window's floor). "
                         "A width under the floor is clamped by Qt, and the "
                         "report says what was drawn")
    ap.add_argument("--height", type=int,
                    help="the height to draw at (default: the window's floor)")
    ap.add_argument("--target", type=int, default=TARGET, metavar="N",
                    help="mark a line here when the window is wider "
                         "(default: %(default)s; 0 for none)")
    ap.add_argument("--tab", choices=sorted(TABS), default="editor",
                    help="which tab to show. The window opens on the "
                         "automapper, and the layout questions are all in the "
                         "editor (default: %(default)s)")
    args = ap.parse_args(argv[1:])

    app = QApplication.instance() or QApplication(["shotwindow"])

    save = args.save
    tmp = None
    if save is None:
        from gamedata import synthetic_save
        tmp = tempfile.TemporaryDirectory(prefix="wish-shotwindow-save-")
        save = str(synthetic_save(tmp.name))

    try:
        image, floor, drawn = shoot(app, save, extra=args.font,
                                    width=args.width, height=args.height,
                                    tab=TABS[args.tab])
    finally:
        if tmp is not None:
            tmp.cleanup()

    what = pathlib.Path(args.save).name if args.save else "synthetic party"
    line = (f"{what}  |  {args.tab}  |  UI font +{args.font:g}pt  |  "
            f"floor {floor.width()}x{floor.height()}  |  "
            f"drawn {drawn[0]}x{drawn[1]}")
    target = args.target or None
    if target and drawn[0] > target:
        line += f"  |  {drawn[0] - target}px past {target}"

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not caption(image, line, target).save(str(out)):
        print(f"could not write {out}", file=sys.stderr)
        return 1
    print(f"{out}  {line}")
    if SUPPRESSED:
        # The picture was still written -- it is evidence of what the window
        # did -- but the run is not a success. `--save` on a file that is not
        # a save drew an empty window and exited 0 before this.
        for said in SUPPRESSED:
            print(f"the program asked and nobody could answer -- {said}",
                  file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
