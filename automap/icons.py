"""Small vector icons, as SVG path data. No Qt in here.

**Why paths and not a font.** `work/reports/font-awesome.md` weighed three ways
of getting icons: `qtawesome`, bundling `Font Awesome 7 Free-Solid-900.otf`, and
lifting the path data. The paths win for this program specifically:

* the map draws with `QPainter`, not `QIcon`, so a font's only advantage --
  `qta.icon()` for toolbar buttons -- is the use we have least of;
* a path is drawn into whatever box you give it, where a glyph needs
  `tightBoundingRect` arithmetic because at `setPixelSize(16)` the ink of
  `location-dot` is 14x18 with a 3px descender and the advance varies per icon;
* `render.py`'s `to_svg` gets the notes for free -- the export is already
  emitting exactly this;
* nothing ships that PyInstaller, `pyproject.toml` and the release build have to
  be told about, and the repository grows 12 KB of source rather than a 405 KB
  binary.

The whole `_UNIT` box is 640x640, which is `svgs-full`'s uniform canvas, so
placement is arithmetic-free: scale by `size / 640` and translate.

Only `M`, `L`, `C` and `Z` appear, all absolute -- checked across every icon
lifted here -- so `commands()` is a twenty-line parser rather than a dependency.

---

Icons under `FONT_AWESOME` are **Font Awesome Free 7.3.1 by Fonticons, Inc.**
(https://fontawesome.com), icons licensed **CC BY 4.0**. The path data is
verbatim from `svgs-full/solid/`; the licence text is in
`docs/licences/fontawesome-LICENSE.txt` and the attribution is carried in the
README and the About box. Brands are not used and must not be: the licence
forbids brand-logo use and the set carries `wizards-of-the-coast`.

Icons under `OURS` are this project's own, drawn here because Font Awesome Free
has **no sword** -- `sword` and `swords` are Pro-only, and `khanda` is a Sikh
religious emblem, wrong in meaning and illegible at twelve pixels. A fighter and
an encounter both want one, so both are drawn from straight lines, which is also
what the map's own line art is made of.
"""

from __future__ import annotations

import math
import re

#: Every icon is drawn in this box, matching Font Awesome's `svgs-full` canvas.
BOX = 640

FONT_AWESOME = {
    "location-dot":
        "M128 252.6C128 148.4 214 64 320 64C426 64 512 148.4 512 "
        "252.6C512 371.9 391.8 514.9 341.6 569.4C329.8 582.2 310.1 582.2 "
        "298.3 569.4C248.1 514.9 127.9 371.9 127.9 252.6zM320 320C355.3 "
        "320 384 291.3 384 256C384 220.7 355.3 192 320 192C284.7 192 256 "
        "220.7 256 256C256 291.3 284.7 320 320 320z",
    "hat-wizard":
        "M128 464L213.7 255.8C230.7 214.5 261.5 180.5 300.9 159.5L447.8 "
        "81.2C460.1 74.6 474.3 85.9 470.8 99.4L433.6 241.8C432.5 245.9 "
        "432 250.1 432 254.4C432 260.7 433.2 267 435.6 272.9L512 464L304.9 "
        "464L316.7 428.6L357.1 415.1C363.6 412.9 368 406.8 368 399.9C368 "
        "393 363.6 386.9 357.1 384.7L316.7 371.2L303.2 330.8C301 324.4 "
        "294.9 320 288 320C281.1 320 275 324.4 272.8 330.9L259.3 "
        "371.3L218.9 384.8C212.4 387 208 393.1 208 400C208 406.9 212.4 413 "
        "218.9 415.2L259.3 428.7L271.1 464.1L128 464.1zM343.6 205.5C342.5 "
        "202.2 339.5 200 336 200C332.5 200 329.5 202.2 328.4 205.5L321.7 "
        "225.7L301.5 232.4C298.2 233.5 296 236.5 296 240C296 243.5 298.2 "
        "246.5 301.5 247.6L321.7 254.3L328.4 274.5C329.5 277.8 332.5 280 "
        "336 280C339.5 280 342.5 277.8 343.6 274.5L350.3 254.3L370.5 "
        "247.6C373.8 246.5 376 243.5 376 240C376 236.5 373.8 233.5 370.5 "
        "232.4L350.3 225.7L343.6 205.5zM96 512L544 512C561.7 512 576 526.3 "
        "576 544C576 561.7 561.7 576 544 576L96 576C78.3 576 64 561.7 64 "
        "544C64 526.3 78.3 512 96 512z",
    "cross":
        "M304 64C277.5 64 256 85.5 256 112L256 192L176 192C149.5 192 128 "
        "213.5 128 240L128 272C128 298.5 149.5 320 176 320L256 320L256 "
        "528C256 554.5 277.5 576 304 576L336 576C362.5 576 384 554.5 384 "
        "528L384 320L464 320C490.5 320 512 298.5 512 272L512 240C512 213.5 "
        "490.5 192 464 192L384 192L384 112C384 85.5 362.5 64 336 64L304 "
        "64z",
    "mask":
        "M320 128C96 128 32 224 32 336C32 448 112 512 208 512L216.4 "
        "512C240.6 512 262.8 498.3 273.6 476.6L296.8 430.3C301.2 421.5 "
        "310.1 416 320 416C329.9 416 338.8 421.5 343.2 430.3L366.4 "
        "476.6C377.2 498.3 399.4 512 423.6 512L432 512C528 512 608 448 608 "
        "336C608 224 544 128 320 128zM128 320C128 284.7 156.7 256 192 "
        "256C227.3 256 256 284.7 256 320C256 355.3 227.3 384 192 384C156.7 "
        "384 128 355.3 128 320zM448 256C483.3 256 512 284.7 512 320C512 "
        "355.3 483.3 384 448 384C412.7 384 384 355.3 384 320C384 284.7 "
        "412.7 256 448 256z",
    "user":
        "M320 312C386.3 312 440 258.3 440 192C440 125.7 386.3 72 320 "
        "72C253.7 72 200 125.7 200 192C200 258.3 253.7 312 320 312zM290.3 "
        "368C191.8 368 112 447.8 112 546.3C112 562.7 125.3 576 141.7 "
        "576L498.3 576C514.7 576 528 562.7 528 546.3C528 447.8 448.2 368 "
        "349.7 368L290.3 368z",
    "door-open":
        "M384 128L448 128L448 544C448 561.7 462.3 576 480 576L512 576C529.7 "
        "576 544 561.7 544 544C544 526.3 529.7 512 512 512L512 128C512 92.7 "
        "483.3 64 448 64L352 64L352 64L192 64C156.7 64 128 92.7 128 128L128 "
        "512C110.3 512 96 526.3 96 544C96 561.7 110.3 576 128 576L352 "
        "576C369.7 576 384 561.7 384 544L384 128zM256 320C256 302.3 270.3 "
        "288 288 288C305.7 288 320 302.3 320 320C320 337.7 305.7 352 288 "
        "352C270.3 352 256 337.7 256 320z",
    "lock":
        "M256 160L256 224L384 224L384 160C384 124.7 355.3 96 320 96C284.7 "
        "96 256 124.7 256 160zM192 224L192 160C192 89.3 249.3 32 320 "
        "32C390.7 32 448 89.3 448 160L448 224C483.3 224 512 252.7 512 "
        "288L512 512C512 547.3 483.3 576 448 576L192 576C156.7 576 128 "
        "547.3 128 512L128 288C128 252.7 156.7 224 192 224z",
    "triangle-exclamation":
        "M320 64C334.7 64 348.2 72.1 355.2 85L571.2 485C577.9 497.4 577.6 "
        "512.4 570.4 524.5C563.2 536.6 550.1 544 536 544L104 544C89.9 544 "
        "76.8 536.6 69.6 524.5C62.4 512.4 62.1 497.4 68.8 485L284.8 "
        "85C291.8 72.1 305.3 64 320 64zM320 416C302.3 416 288 430.3 288 "
        "448C288 465.7 302.3 480 320 480C337.7 480 352 465.7 352 448C352 "
        "430.3 337.7 416 320 416zM320 224C301.8 224 287.3 239.5 288.6 "
        "257.7L296 361.7C296.9 374.2 307.4 384 319.9 384C332.5 384 342.9 "
        "374.3 343.8 361.7L351.2 257.7C352.5 239.5 338.1 224 319.8 224z",
    "skull":
        "M480 491.4C538.5 447.4 576 379.8 576 304C576 171.5 461.4 64 320 "
        "64C178.6 64 64 171.5 64 304C64 379.8 101.5 447.4 160 491.4L160 "
        "528C160 554.5 181.5 576 208 576L240 576L240 536C240 522.7 250.7 "
        "512 264 512C277.3 512 288 522.7 288 536L288 576L352 576L352 "
        "536C352 522.7 362.7 512 376 512C389.3 512 400 522.7 400 536L400 "
        "576L432 576C458.5 576 480 554.5 480 528L480 491.4zM160 320C160 "
        "284.7 188.7 256 224 256C259.3 256 288 284.7 288 320C288 355.3 "
        "259.3 384 224 384C188.7 384 160 355.3 160 320zM416 256C451.3 256 "
        "480 284.7 480 320C480 355.3 451.3 384 416 384C380.7 384 352 "
        "355.3 352 320C352 284.7 380.7 256 416 256z",
    "arrow-down-long":
        "M297.4 598.6C309.9 611.1 330.2 611.1 342.7 598.6L470.7 "
        "470.6C483.2 458.1 483.2 437.8 470.7 425.3C458.2 412.8 437.9 "
        "412.8 425.4 425.3L352 498.7L352 64C352 46.3 337.7 32 320 "
        "32C302.3 32 288 46.3 288 64L288 498.7L214.6 425.3C202.1 412.8 "
        "181.8 412.8 169.3 425.3C156.8 437.8 156.8 458.1 169.3 "
        "470.6L297.3 598.6z",
    "trash-can":
        "M232.7 69.9C237.1 56.8 249.3 48 263.1 48L377 48C390.8 48 403 "
        "56.8 407.4 69.9L416 96L512 96C529.7 96 544 110.3 544 128C544 "
        "145.7 529.7 160 512 160L128 160C110.3 160 96 145.7 96 128C96 "
        "110.3 110.3 96 128 96L224 96L232.7 69.9zM128 208L512 208L512 "
        "512C512 547.3 483.3 576 448 576L192 576C156.7 576 128 547.3 128 "
        "512L128 208zM216 272C202.7 272 192 282.7 192 296L192 488C192 "
        "501.3 202.7 512 216 512C229.3 512 240 501.3 240 488L240 296C240 "
        "282.7 229.3 272 216 272zM320 272C306.7 272 296 282.7 296 296L296 "
        "488C296 501.3 306.7 512 320 512C333.3 512 344 501.3 344 488L344 "
        "296C344 282.7 333.3 272 320 272zM424 272C410.7 272 400 282.7 400 "
        "296L400 488C400 501.3 410.7 512 424 512C437.3 512 448 501.3 448 "
        "488L448 296C448 282.7 437.3 272 424 272z",
    "check":
        "M530.8 134.1C545.1 144.5 548.3 164.5 537.9 178.8L281.9 530.8C276.4 "
        "538.4 267.9 543.1 258.5 543.9C249.1 544.7 240 541.2 233.4 "
        "534.6L105.4 406.6C92.9 394.1 92.9 373.8 105.4 361.3C117.9 348.8 "
        "138.2 348.8 150.7 361.3L252.2 462.8L486.2 141.1C496.6 126.8 516.6 "
        "123.6 530.9 134z",
}


def _poly(points, cx: float = 0.0, cy: float = 0.0, turn: float = 0.0) -> str:
    """One closed subpath, optionally turned about `(cx, cy)` by `turn` degrees.

    The rotation is what makes crossed swords one drawing rather than two: the
    blade is written once, upright, and the pair is the same points twice.
    """
    r = math.radians(turn)
    sin, cos = math.sin(r), math.cos(r)
    out = []
    for i, (x, y) in enumerate(points):
        dx, dy = x - cx, y - cy
        px, py = cx + dx * cos - dy * sin, cy + dx * sin + dy * cos
        out.append(f"{'M' if i == 0 else 'L'}{px:.1f} {py:.1f}")
    return "".join(out) + "z"


def _rect(x: float, y: float, w: float, h: float, **kw) -> str:
    return _poly(((x, y), (x + w, y), (x + w, y + h), (x, y + h)), **kw)


# The blade, upright: point, shoulders, crossguard, grip. Drawn thick on
# purpose -- the map is stroked at 3px and a 12px icon beside it that is one
# pixel wide reads as a scratch rather than as a sword.
_BLADE = ((320, 60), (392, 190), (392, 380), (496, 380), (496, 450),
          (376, 450), (376, 552), (264, 552), (264, 450), (144, 450),
          (144, 380), (248, 380), (248, 190))
_POMMEL = (240, 546, 160, 62)          # x, y, w, h

OURS = {
    # One sword, for the fighter: Font Awesome Free has none.
    "sword": _poly(_BLADE) + _rect(*_POMMEL),
    # Crossed swords, for an encounter. Turned 32 degrees either way, which is
    # wide enough that the two guards do not land on each other at 12px.
    "swords": (_poly(_BLADE, 320, 320, -32) + _rect(*_POMMEL, cx=320, cy=320,
                                                    turn=-32)
               + _poly(_BLADE, 320, 320, 32) + _rect(*_POMMEL, cx=320, cy=320,
                                                     turn=32)),
    # A chest, drawn as an outline rather than a solid: on graph paper a filled
    # rectangle reads as terrain, which is the one thing a note must not do.
    # The inner rectangle is wound the other way, so winding fill makes it a
    # hole -- the same trick `location-dot`'s counter uses.
    "chest": (_rect(104, 232, 432, 304)
              + _poly(((144, 272), (144, 496), (496, 496), (496, 272)))
              + _rect(104, 232, 432, 96)
              + _rect(284, 296, 72, 104)),
}

ICONS: dict[str, str] = {**FONT_AWESOME, **OURS}

_NUMBER = re.compile(r"[MLCZmlczHhVvSsQqTtAa]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def path_data(name: str) -> str:
    """The raw SVG `d`, for `to_svg` to write out unchanged."""
    return ICONS[name]


def commands(name: str) -> tuple[tuple, ...]:
    """`d` parsed into `("M", x, y)`, `("L", x, y)`, `("C", *6)` and `("Z",)`.

    Absolute commands only. Everything lifted here uses exactly those four --
    `svgs-full` emits no arcs and no relative form -- so an unexpected letter is
    a mistake in a hand-written icon and is raised rather than guessed at.
    """
    tokens = _NUMBER.findall(ICONS[name])
    out: list[tuple] = []
    i, op = 0, ""
    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            op = token
            i += 1
            if op in "Zz":
                out.append(("Z",))
                op = ""
                continue
        if not op:
            raise ValueError(f"{name}: coordinates before any command")
        if op not in "MLC":
            raise ValueError(f"{name}: unsupported path command {op!r}")
        count = 6 if op == "C" else 2
        numbers = tuple(float(t) for t in tokens[i:i + count])
        if len(numbers) != count:
            raise ValueError(f"{name}: {op} wants {count} numbers")
        out.append((op, *numbers))
        i += count
        if op == "M":
            op = "L"                # a repeated pair after M is a line, per SVG
    return tuple(out)


def extent(name: str) -> tuple[float, float, float, float]:
    """The ink's bounding box, for checking an icon fits where it is put.

    Control points count, so this is at worst an over-estimate -- which is the
    safe direction for "does this note overlap a wall".
    """
    xs, ys = [], []
    for cmd in commands(name):
        if cmd[0] == "Z":
            continue
        coords = cmd[1:]
        xs.extend(coords[0::2])
        ys.extend(coords[1::2])
    return min(xs), min(ys), max(xs), max(ys)
