"""Draw every square mark the artist delivered, resized to the sizes Windows
draws, on a light taskbar and a dark one.

    .venv/bin/python tools/taskbaricon.py work/issue351/taskbar-marks.png

For `#351 (The Windows build shows no logo in About and a black square on
the taskbar, because the artist's SVGs are not in the package)`. Donald,
2026-09-06, of the colour mark on a Windows taskbar: *"It is too small for
the color image. I am open to suggestions."* And then: *"please offer me an
image with comparisons."*

**Resize. Nothing else.** The first sheet drawn for this switched off two
`<image>` elements in an in-memory copy of the artist's file, cropped the
lettering out of the combo mark with a viewBox, and drew a pentagram of its
own, and Donald refused it: *"you're editing the artist's image, which is
forbidden. We should only be resizing what the original artist gave us."*
In-memory is still editing. So every cell on this sheet is one of Dustin
Geddy Parker's delivered files, whole, scaled to a square: no element left
out, no viewBox moved, no colour changed, no stroke thickened, nothing drawn
by hand. A choice that cannot be made by scaling a file he delivered is not a
choice this sheet offers.

**What he delivered** is read from `~/Downloads/wish_logo/` (or
`$WISH_LOGO_DELIVERY`) and is not copied into the repository: three
families -- `Marks/`, the pentacle alone; `Combo Marks/`, the pentacle with
lettering; `Logos/`, the wide lockup -- each in Color, Black and White, each
as an SVG and PNGs at 80, 150, 200 and 500 (the logos at 300x100, 600x200 and
1200x400). The two colour SVGs are byte-identical to `assets/logo/mark.svg`
and `assets/logo/combo-mark-color.svg`. The logos are 3:1 and not square, so
they are not taskbar candidates and are not drawn.

**Each row is one file at one size in two ways where the two differ**: the
SVG rendered at the size, and the smallest delivered PNG no smaller than the
size scaled down to it. He exported PNGs at 80 and 150 for a reason, and a
hand-tuned raster can beat a downscaled vector at 24 pixels. Where the two
were measured indistinguishable the PNG row is dropped rather than padding
the sheet -- `PNG_ROWS` says which were kept and the docstring beside it
says what was measured.

**Each row says whether the file has its own ground.** The Color files carry
an opaque near-black square (`#17140e`) under the gold; the Black and White
files are line art on transparency. That is not a detail: an opaque square
looks the same on a light taskbar and a dark one, while transparent line art
is invisible on the taskbar that matches its colour.

**Nothing here decides.** The rows are lettered so Donald can answer with a
letter, and the judgement of which sizes each survives is in
`docs/132-logo.md` §7, not on the sheet.
"""

from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
)
from PyQt6.QtSvg import QSvgRenderer  # noqa: E402

#: Where the artist's delivery sits. Read in place, never copied in: the two
#: files the program uses are already committed under `assets/logo/` and the
#: rest are his to hand over when a choice is made.
DELIVERY = pathlib.Path(
    os.environ.get("WISH_LOGO_DELIVERY", "~/Downloads/wish_logo")).expanduser()

#: The sizes a Windows `.ico` is asked for -- `docs/132-logo.md` §1b -- minus
#: 40 and 64, which are 32 and 48 at a display scaling and add no new
#: judgement. The taskbar button is 24 logical pixels on Windows 10 and 11,
#: 32 at 150 % scaling; 256 is Explorer's big view and nearly decoration.
SIZES = (16, 20, 24, 32, 48, 256)

#: How much each size is blown up beside its true-size cell, chosen so every
#: magnified cell is about 192 pixels; 256 is shown at true size only.
MAGNIFY = {16: 12, 20: 9, 24: 8, 32: 6, 48: 4, 256: 1}

#: The PNG sizes he delivered for the square families.
PNG_SIZES = (80, 150, 200, 500)

#: A Windows 11 taskbar, light theme and dark theme, so each true-size cell
#: sits on what it will actually sit on. Windows 11 follows the system theme,
#: so both are real.
TASKBAR_LIGHT = QColor("#f3f3f3")
TASKBAR_DARK = QColor("#202020")

PAPER = QColor("#fbfcfd")
INK = QColor("#16202b")
MUTED = QColor("#5c6b7a")


# --- the delivered files ---------------------------------------------------


def svg_path(family: str, colourway: str) -> pathlib.Path:
    """`Marks/Color/SVG Color Mark.svg`, `Combo Marks/Black/SVG Black Combo.svg`."""
    word = "Combo" if family == "Combo Marks" else "Mark"
    return DELIVERY / family / colourway / f"SVG {colourway} {word}.svg"


def png_path(family: str, colourway: str, side: int) -> pathlib.Path:
    """`Marks/Color/Color Mark 80x80.png`. One file is named with a lowercase
    `combo`, so the name is matched case-insensitively rather than assumed."""
    folder = DELIVERY / family / colourway
    want = f"{colourway} {family[:-1]} {side}x{side}.png".lower()
    for candidate in folder.iterdir():
        if candidate.name.lower() == want:
            return candidate
    raise FileNotFoundError(f"{folder}/{want}")


def nearest_png(side: int) -> int:
    """The smallest delivered PNG no smaller than `side`, so a raster is only
    ever scaled down: 80 for everything up to 80, 500 for 256."""
    return next(s for s in PNG_SIZES if s >= side)


def render_svg(path: pathlib.Path, size: int) -> QImage:
    """`path` rendered whole into a `size` square, on transparency."""
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        raise RuntimeError(f"{path} did not parse")
    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return out


def scale_png(path: pathlib.Path, size: int) -> QImage:
    """`path` scaled whole to a `size` square, area-averaged."""
    source = QImage(str(path))
    if source.isNull():
        raise RuntimeError(f"{path} did not load")
    return source.convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied).scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)


def ground(image: QImage) -> str:
    """What the file brings with it: read off the pixels rather than asserted."""
    w, h = image.width(), image.height()
    alphas = [image.pixelColor(x, y).alpha() for y in range(h) for x in range(w)]
    if min(alphas) == 255:
        c = image.pixelColor(0, 0)
        return f"opaque, its own ground {c.name()}"
    clear = sum(1 for a in alphas if a == 0)
    return f"transparent ({clear * 100 // len(alphas)} % of the square is empty)"


# --- the rows --------------------------------------------------------------

#: `(family, colourway)` in the order they are drawn: the marks first, since
#: they are the taskbar candidates, then the combo marks so the lettering can
#: be seen failing rather than described failing.
FILES = [
    ("Marks", "Color"),
    ("Marks", "Black"),
    ("Marks", "White"),
    ("Combo Marks", "Color"),
    ("Combo Marks", "Black"),
    ("Combo Marks", "White"),
]

#: Which files get a second row scaled from the delivered PNG. Measured on
#: 2026-09-06 with `difference()` below at 24 and 32: the largest per-channel
#: gap between the SVG render and the scaled PNG was 89 or more of 255 for
#: every family, and the sheet shows why. The Color files' two rings are
#: embedded bitmaps carrying a hairline each, and Qt's renderer loses them
#: below 48 while the artist's PNG export kept them as a faint circle; the
#: Black and White PNGs are a little lighter than Qt's render of the same
#: paths (alpha coverage 89 against 99 at 32). So every file keeps its PNG
#: row. `python tools/taskbaricon.py --measure` reprints the figures; drop a
#: pair here if it falls under `SAME_ENOUGH`.
PNG_ROWS = frozenset(FILES)

#: Below this largest per-channel gap two renders are the same to the eye.
SAME_ENOUGH = 24


def difference(a: QImage, b: QImage) -> int:
    """The largest per-channel gap between two same-sized images, alpha
    included, out of 255."""
    gap = 0
    for y in range(a.height()):
        for x in range(a.width()):
            p, q = a.pixelColor(x, y), b.pixelColor(x, y)
            gap = max(gap, abs(p.red() - q.red()), abs(p.green() - q.green()),
                      abs(p.blue() - q.blue()), abs(p.alpha() - q.alpha()))
    return gap


class Row:
    """One lettered row: one delivered file, scaled one way."""

    def __init__(self, letter: str, family: str, colourway: str,
                 raster: bool) -> None:
        self.letter = letter
        self.family = family
        self.colourway = colourway
        self.raster = raster

    @property
    def name(self) -> str:
        what = "Combo mark" if self.family == "Combo Marks" else "Mark"
        how = "from the PNGs" if self.raster else "from the SVG"
        return f"{self.colourway} {what}, {how}"

    def source(self, size: int) -> pathlib.Path:
        if self.raster:
            return png_path(self.family, self.colourway, nearest_png(size))
        return svg_path(self.family, self.colourway)

    def draw(self, size: int) -> QImage:
        if self.raster:
            return scale_png(self.source(size), size)
        return render_svg(self.source(size), size)

    def what(self) -> str:
        """The row's caption: which file, and what ground it brings."""
        if self.raster:
            files = ", ".join(f"{s}x{s}" for s in PNG_SIZES)
            which = (f"{self.source(24).parent.relative_to(DELIVERY)}/ PNGs "
                     f"({files}), the smallest no smaller than the cell, "
                     "scaled down")
        else:
            which = f"{self.source(24).relative_to(DELIVERY)}, rendered"
        return f"{which}. Ground: {ground(self.draw(48))}."


def rows() -> list[Row]:
    out: list[Row] = []
    letters = iter("ABCDEFGHIJKLMNOP")
    for family, colourway in FILES:
        out.append(Row(next(letters), family, colourway, raster=False))
        if (family, colourway) in PNG_ROWS:
            out.append(Row(next(letters), family, colourway, raster=True))
    return out


# --- the sheet -------------------------------------------------------------

#: The theming question, in words, under the rows. Donald, 2026-09-06: *"If
#: there is something fancy we need to do around theming or dark mode, let me
#: know. His images are transparent. I agree that simple will work better."*
#: Two shapes are possible and the sheet is drawn so both can be judged from
#: the pictures; it names neither.
FOOTER = (
    "Theming. Windows 11 paints the taskbar in the system theme, light or "
    "dark, and a transparent file shows whatever is behind it. Two ways to "
    "ship:\n"
    "1. One icon for both themes: a row whose light cell and dark cell both "
    "read. Nothing to detect, nothing to maintain. The Color rows carry their "
    "own opaque ground, so they are the same picture on both; the Black and "
    "White rows are transparent and each is invisible on the taskbar that "
    "matches it.\n"
    "2. A colourway per theme, swapped at run time from Qt's colorScheme() "
    "and colorSchemeChanged: the White mark on a dark taskbar, the Black on "
    "a light one. More to build and a second thing to go wrong, and Help > "
    "About already chose the colour combo mark on 2026-09-05 because it "
    "carries its own ground and needs no detection.\n"
    "3. Not on this sheet: a version with its own ground drawn for 24 and 32 "
    "pixels, which is a thing to ask the artist for."
)

LABEL_W = 420
GAP = 14
ROW_PAD = 26


def _magnified(image: QImage, factor: int) -> QImage:
    side = image.width() * factor
    return image.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation)


def _on(image: QImage, taskbar: QColor, pad: int = 6) -> QImage:
    """`image` at true size on a patch of `taskbar`."""
    side = image.width() + pad * 2
    out = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(taskbar)
    painter = QPainter(out)
    painter.drawImage(QPointF(pad, pad), image)
    painter.end()
    return out


def sheet(the_rows: list[Row] | None = None) -> QImage:
    the_rows = rows() if the_rows is None else the_rows
    columns = []       # (size, x, true-cell width, magnified width)
    x = LABEL_W
    for size in SIZES:
        true_w = (size + 12) * 2 if size < 256 else 0
        mag_w = size * MAGNIFY[size]
        columns.append((size, x, true_w, mag_w))
        x += true_w + (GAP if true_w else 0) + mag_w + GAP * 2
    width = x
    header_h = 70
    row_h = 256 + ROW_PAD * 2 + 30
    footer_h = 150
    height = header_h + row_h * len(the_rows) + footer_h

    out = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(PAPER)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    title, label, small = QFont(), QFont(), QFont()
    title.setPointSize(14)
    title.setBold(True)
    label.setPointSize(11)
    label.setBold(True)
    small.setPointSize(9)

    painter.setPen(INK)
    painter.setFont(title)
    painter.drawText(QRectF(GAP, 8, width, 30),
                     "Wish taskbar icon: every square mark the artist "
                     "delivered, resized and nothing else")
    painter.setFont(small)
    painter.setPen(MUTED)
    painter.drawText(QRectF(GAP, 36, width, 20),
                     "Each size: true size on a light taskbar and a dark one, "
                     "then magnified. 256 is true size only. The taskbar "
                     "button is 24, or 32 at 150 % scaling.")
    for size, cx, true_w, mag_w in columns:
        painter.drawText(QRectF(cx, 52, true_w + GAP + mag_w, 16),
                         f"{size} px" + ("" if size < 256 else " (true size)"))

    for index, row in enumerate(the_rows):
        top = header_h + index * row_h
        painter.setPen(INK)
        painter.setFont(label)
        painter.drawText(QRectF(GAP, top + ROW_PAD, LABEL_W - GAP, 22),
                         f"{row.letter}.  {row.name}")
        painter.setFont(small)
        painter.setPen(MUTED)
        painter.drawText(QRectF(GAP, top + ROW_PAD + 26, LABEL_W - GAP * 2, 200),
                         int(Qt.TextFlag.TextWordWrap), row.what())
        for size, cx, true_w, mag_w in columns:
            image = row.draw(size)
            y = top + ROW_PAD
            if true_w:
                painter.drawImage(QPointF(cx, y), _on(image, TASKBAR_LIGHT))
                painter.drawImage(QPointF(cx + size + 12, y),
                                  _on(image, TASKBAR_DARK))
                mx = cx + true_w + GAP
            else:
                mx = cx
            big = _magnified(image, MAGNIFY[size])
            # The magnified cell sits on the light taskbar in its left half
            # and the dark one in its right, so a transparent file shows
            # against both without doubling the sheet's width.
            half = big.width() // 2
            painter.fillRect(QRectF(mx, y, half, big.height()), TASKBAR_LIGHT)
            painter.fillRect(QRectF(mx + half, y, big.width() - half,
                                    big.height()), TASKBAR_DARK)
            painter.drawImage(QPointF(mx, y), big)
    painter.setFont(small)
    painter.setPen(INK)
    painter.drawText(QRectF(GAP, height - footer_h + 10, width - GAP * 2,
                            footer_h - 10),
                     int(Qt.TextFlag.TextWordWrap), FOOTER)
    painter.end()
    return out


def measure() -> list[tuple[str, str, int, int]]:
    """Per file, the largest per-channel gap between the SVG render and the
    scaled PNG at 24 and at 32 -- what decided `PNG_ROWS`."""
    out = []
    for family, colourway in FILES:
        gaps = []
        for size in (24, 32):
            vector = render_svg(svg_path(family, colourway), size)
            raster = scale_png(png_path(family, colourway, nearest_png(size)),
                               size)
            gaps.append(difference(vector, raster))
        out.append((family, colourway, gaps[0], gaps[1]))
    return out


def main(argv: list[str]) -> int:
    app = QGuiApplication(["taskbaricon"])
    assert app is not None
    if "--measure" in argv:
        print("family        colourway  gap@24  gap@32   (of 255; same to the "
              f"eye below {SAME_ENOUGH})")
        for family, colourway, g24, g32 in measure():
            print(f"{family:13s} {colourway:10s} {g24:6d}  {g32:6d}")
        return 0
    out = pathlib.Path(argv[1] if len(argv) > 1
                       else "work/issue351/taskbar-marks.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    image = sheet()
    if not image.save(str(out)):
        raise RuntimeError(f"could not write {out}")
    print(f"{out}  {image.width()}x{image.height()}")
    for row in rows():
        print(f"  {row.letter}. {row.name} -- {row.what()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
