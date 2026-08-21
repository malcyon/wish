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

Icons under `CANDIDATES` are neither yet: they are the menu of
`docs/109-icon-choices.md`, kept here so `tools/iconsheet.py` renders them
through the code the map really paints with. They go when the pick is made.

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

# --- the menu of docs/109-icon-choices.md -----------------------------------
#
# **These are candidates, not choices.** They exist so that
# `tools/iconsheet.py` renders every option through the same code the map and
# the roster use -- the mistake the first time was choosing from names, and a
# path rendered anywhere but here is not evidence about this program.
#
# `work/reports/icon-sheet.png` is the sheet. When Donald picks, the winners
# move up into `FONT_AWESOME` or `OURS` and **the rest of this block goes**.
#
# Font Awesome entries are verbatim from `svgs-full/solid/`, same as above,
# same licence, same attribution. Nothing here comes from `brands/`.

CANDIDATES_FONT_AWESOME = {
    "wand-sparkles":
        "M528 70.1C537.5 61.6 552 62 561 71L569 79C578 88 578.4 102.5 "
        "569.9 112L484.1 207.9C481.5 210.8 480 214.6 480 218.6L480 "
        "240C480 248.8 472.8 256 464 256L448.2 256C443.6 256 439.3 257.9 "
        "436.3 261.3L164.7 564.9C158.4 572 149.4 576 139.9 576C131.1 576 "
        "122.6 572.5 116.4 566.2L73.7 523.7C67.5 517.5 64 509 64 500.2C64 "
        "490.7 68 481.7 75.1 475.4L186.7 375.6C190.1 372.6 192 368.2 192 "
        "363.7L192 336.1C192 327.3 199.2 320.1 208 320.1L242.6 "
        "320.1C246.5 320.1 250.3 318.6 253.3 316L528 70.1zM496 352C499.6 "
        "352 502.7 354.4 503.7 357.8L518.5 409.5L570.2 424.3C573.6 425.3 "
        "576 428.4 576 432C576 435.6 573.6 438.7 570.2 439.7L518.5 "
        "454.5L503.7 506.2C502.7 509.6 499.6 512 496 512C492.4 512 489.3 "
        "509.6 488.3 506.2L473.5 454.5L421.8 439.7C418.4 438.7 416 435.6 "
        "416 432C416 428.4 418.4 425.3 421.8 424.3L473.5 409.5L488.3 "
        "357.8C489.3 354.4 492.4 352 496 352zM151.7 133.8L166.5 "
        "185.5L218.2 200.3C221.6 201.3 224 204.4 224 208C224 211.6 221.6 "
        "214.7 218.2 215.7L166.5 230.5L151.7 282.2C150.7 285.6 147.6 288 "
        "144 288C140.4 288 137.3 285.6 136.3 282.2L121.5 230.5L69.8 "
        "215.7C66.4 214.7 64 211.6 64 208C64 204.4 66.4 201.3 69.8 "
        "200.3L121.5 185.5L136.3 133.8C137.3 130.4 140.4 128 144 "
        "128C147.6 128 150.7 130.4 151.7 133.8zM272 64C275.7 64 278.9 "
        "66.5 279.8 70.1L286.6 97.4L313.9 104.2C317.5 105.1 320 108.3 320 "
        "112C320 115.7 317.5 118.9 313.9 119.8L286.6 126.6L279.8 "
        "153.9C278.9 157.5 275.7 160 272 160C268.3 160 265.1 157.5 264.2 "
        "153.9L257.4 126.6L230.1 119.8C226.5 118.9 224 115.7 224 112C224 "
        "108.3 226.5 105.1 230.1 104.2L257.4 97.4L264.2 70.1C265.1 66.5 "
        "268.3 64 272 64z",
    "wand-magic":
        "M462.5 76.2L374.3 164.4L475.6 265.7L563.8 177.5C571.6 169.6 576 "
        "159 576 148C576 137 571.6 126.4 563.8 118.5L521.5 76.2C513.6 "
        "68.4 503 64 492 64C481 64 470.4 68.4 462.5 76.2zM340.4 "
        "198.3L76.2 462.5C68.4 470.4 64 481 64 492C64 503 68.4 513.6 76.2 "
        "521.5L118.5 563.8C126.4 571.6 137 576 148 576C159 576 169.6 "
        "571.6 177.5 563.8L441.7 299.6L340.4 198.3z",
    "scroll":
        "M32 176C32 134.5 63.6 100.4 104 96.4L104 96L384 96C437 96 480 "
        "139 480 192L480 368L304 368C264.2 368 232 400.2 232 440L232 "
        "500C232 524.3 212.3 544 188 544C163.7 544 144 524.3 144 500L144 "
        "272L80 272C53.5 272 32 250.5 32 224L32 176zM268.8 544C275.9 "
        "530.9 280 515.9 280 500L280 440C280 426.7 290.7 416 304 416L552 "
        "416C565.3 416 576 426.7 576 440L576 464C576 508.2 540.2 544 496 "
        "544L268.8 544zM112 144C94.3 144 80 158.3 80 176L80 224L144 "
        "224L144 176C144 158.3 129.7 144 112 144z",
    "book-bible":
        "M192 576C139 576 96 533 96 480L96 160C96 107 139 64 192 64L496 "
        "64C522.5 64 544 85.5 544 112L544 400C544 420.9 530.6 438.7 512 "
        "445.3L512 512C529.7 512 544 526.3 544 544C544 561.7 529.7 576 "
        "512 576L192 576zM192 448C174.3 448 160 462.3 160 480C160 497.7 "
        "174.3 512 192 512L448 512L448 448L192 448zM288 144L288 192L240 "
        "192C231.2 192 224 199.2 224 208L224 240C224 248.8 231.2 256 240 "
        "256L288 256L288 368C288 376.8 295.2 384 304 384L336 384C344.8 "
        "384 352 376.8 352 368L352 256L400 256C408.8 256 416 248.8 416 "
        "240L416 208C416 199.2 408.8 192 400 192L352 192L352 144C352 "
        "135.2 344.8 128 336 128L304 128C295.2 128 288 135.2 288 144z",
    "user-ninja":
        "M448 192C448 262.7 390.7 320 320 320C262.8 320 214.4 282.5 198 "
        "230.7C196.9 232 195.8 233.3 194.5 234.5C178.7 250.3 155.7 255.2 "
        "140.9 256.6C132.8 257.4 126.3 250.9 127.1 242.8C128.5 228.1 "
        "133.4 205 149.2 189.2C155 183.4 161.8 179.1 168.8 175.8C161.8 "
        "172.6 155 168.2 149.2 162.4C133.4 146.6 128.5 123.6 127.1 "
        "108.8C126.3 100.7 132.8 94.2 140.9 95C155.6 96.4 178.7 101.3 "
        "194.5 117.1C199.3 121.9 203.2 127.5 206.2 133.2C227.5 92 270.5 "
        "63.8 320 63.8C390.7 63.8 448 121.1 448 191.8zM240 176C240 184.8 "
        "247.2 192 256 192L384 192C392.8 192 400 184.8 400 176C400 167.2 "
        "392.8 160 384 160L256 160C247.2 160 240 167.2 240 176zM238.6 "
        "387L305.6 437.2C314.1 443.6 325.9 443.6 334.4 437.2L401.4 "
        "387C407.9 382.1 416.6 380.8 424 384.2C485.4 412.4 528.1 474.4 "
        "528.1 546.3C528.1 562.7 514.8 576 498.4 576L141.7 576C125.3 576 "
        "112 562.7 112 546.3C112 474.3 154.7 412.3 216.1 384.2C223.5 "
        "380.8 232.2 382.1 238.7 387z",
    "user-secret":
        "M267 48C230.6 48 209.2 106.3 198.7 160L168 160C154.7 160 144 "
        "170.7 144 184C144 197.3 154.7 208 168 208L192 208L192 240C192 "
        "257 195.3 273.2 201.3 288L192 288L192 288L171.5 288C156.3 288 "
        "144 300.3 144 315.5C144 318.5 144.5 321.4 145.4 324.2L174.3 "
        "410.8C136.2 443.6 112 492.1 112 546.3C112 562.7 125.3 576 141.7 "
        "576L498.3 576C514.7 576 528 562.7 528 546.3C528 492.1 503.8 "
        "443.6 465.7 410.9L494.6 324.3C495.5 321.5 496 318.6 496 "
        "315.6C496 300.4 483.7 288.1 468.5 288.1L448 288.1L448 "
        "288.1L438.7 288.1C444.7 273.3 448 257.1 448 240.1L448 208.1L472 "
        "208.1C485.3 208.1 496 197.4 496 184.1C496 170.8 485.3 160.1 472 "
        "160.1L441.3 160.1C430.9 106.4 409.4 48.1 373 48.1C363.4 48.1 354 "
        "52 345.5 56.3C337.3 60.4 327.1 64.1 320 64.1C312.9 64.1 302.7 "
        "60.4 294.5 56.3C286 51.9 276.6 48 267 48zM360.7 532.4L335.9 "
        "461.5L363.8 429C366.5 425.8 368 421.8 368 417.6C368 407.9 360.2 "
        "400.1 350.5 400.1L289.5 400.1C279.8 400.1 272 407.9 272 "
        "417.6C272 421.8 273.5 425.8 276.2 429L304.1 461.5L279.3 "
        "532.4L222.3 352L258 352C276.4 362.2 297.5 368 320 368C342.5 368 "
        "363.6 362.2 382 352L417.7 352L360.7 532.4zM320 320C285.3 320 "
        "255.8 297.9 244.7 267C250.4 270.2 257 272 264 272L276.4 "
        "272C292.9 272 307.5 261.4 312.7 245.8C315 238.8 324.9 238.8 "
        "327.2 245.8C332.4 261.4 347.1 272 363.5 272L375.9 272C382.9 272 "
        "389.5 270.2 395.2 267C384.1 297.9 354.6 320 319.9 320z",
    "key":
        "M400 416C497.2 416 576 337.2 576 240C576 142.8 497.2 64 400 "
        "64C302.8 64 224 142.8 224 240C224 258.7 226.9 276.8 232.3 "
        "293.7L71 455C66.5 459.5 64 465.6 64 472L64 552C64 565.3 74.7 576 "
        "88 576L168 576C181.3 576 192 565.3 192 552L192 512L232 512C245.3 "
        "512 256 501.3 256 488L256 448L296 448C302.4 448 308.5 445.5 313 "
        "441L346.3 407.7C363.2 413.1 381.3 416 400 416zM440 160C462.1 160 "
        "480 177.9 480 200C480 222.1 462.1 240 440 240C417.9 240 400 "
        "222.1 400 200C400 177.9 417.9 160 440 160z",
    "hands-praying":
        "M224 360C224 373.3 213.3 384 200 384C186.7 384 176 373.3 176 "
        "360L176 247.4L264.2 127.7C277.3 109.9 273.5 84.9 255.7 "
        "71.8C237.9 58.7 212.9 62.5 199.8 80.3L106.5 206.9C89.3 230.2 80 "
        "258.5 80 287.6L80 398.3L21.9 417.7C8.8 422 0 434.2 0 448L0 544C0 "
        "554 4.7 563.5 12.7 569.5C20.7 575.5 31.1 577.5 40.8 574.7L195.2 "
        "530.6C250.2 514.9 288 464.7 288 407.5L288 288C288 270.3 273.7 "
        "256 256 256C238.3 256 224 270.3 224 288L224 360zM416 360L416 "
        "288C416 270.3 401.7 256 384 256C366.3 256 352 270.3 352 288L352 "
        "407.6C352 464.8 389.9 515 444.8 530.7L599.2 574.8C608.9 577.6 "
        "619.2 575.6 627.3 569.6C635.4 563.6 640 554 640 544L640 448C640 "
        "434.2 631.2 422 618.1 417.6L560 398.2L560 287.5C560 258.5 550.7 "
        "230.2 533.5 206.8L440.2 80.3C427.1 62.5 402.1 58.7 384.3 "
        "71.8C366.5 84.9 362.7 109.9 375.8 127.7L464 247.4L464 360C464 "
        "373.3 453.3 384 440 384C426.7 384 416 373.3 416 360z",
    "shield":
        "M320 64C324.6 64 329.2 65 333.4 66.9L521.8 146.8C543.8 156.1 "
        "560.2 177.8 560.1 204C559.6 303.2 518.8 484.7 346.5 567.2C329.8 "
        "575.2 310.4 575.2 293.7 567.2C121.3 484.7 80.6 303.2 80.1 204C80 "
        "177.8 96.4 156.1 118.4 146.8L306.7 66.9C310.9 65 315.4 64 320 "
        "64z",
    "shield-halved":
        "M320 64C324.6 64 329.2 65 333.4 66.9L521.8 146.8C543.8 156.1 "
        "560.2 177.8 560.1 204C559.6 303.2 518.8 484.7 346.5 567.2C329.8 "
        "575.2 310.4 575.2 293.7 567.2C121.3 484.7 80.6 303.2 80.1 204C80 "
        "177.8 96.4 156.1 118.4 146.8L306.7 66.9C310.9 65 315.4 64 320 "
        "64zM320 130.8L320 508.9C458 442.1 495.1 294.1 496 205.5L320 "
        "130.9L320 130.9z",
    "stairs":
        "M416 128C416 110.3 430.3 96 448 96L576 96C593.7 96 608 110.3 608 "
        "128C608 145.7 593.7 160 576 160L480 160L480 256C480 273.7 465.7 "
        "288 448 288L352 288L352 384C352 401.7 337.7 416 320 416L224 "
        "416L224 512C224 529.7 209.7 544 192 544L64 544C46.3 544 32 529.7 "
        "32 512C32 494.3 46.3 480 64 480L160 480L160 384C160 366.3 174.3 "
        "352 192 352L288 352L288 256C288 238.3 302.3 224 320 224L416 "
        "224L416 128z",
    "folder-open":
        "M88 289.6L64.4 360.2L64.4 160C64.4 124.7 93.1 96 128.4 96L267.1 "
        "96C280.9 96 294.4 100.5 305.5 108.8L343.9 137.6C349.4 141.8 "
        "356.2 144 363.1 144L480.4 144C515.7 144 544.4 172.7 544.4 "
        "208L544.4 224L179 224C137.7 224 101 250.4 87.9 289.6zM509.8 "
        "512L131 512C98.2 512 75.1 479.9 85.5 448.8L133.5 304.8C140 285.2 "
        "158.4 272 179 272L557.8 272C590.6 272 613.7 304.1 603.3 "
        "335.2L555.3 479.2C548.8 498.8 530.4 512 509.8 512z",
    "floppy-disk":
        "M160 96C124.7 96 96 124.7 96 160L96 480C96 515.3 124.7 544 160 "
        "544L480 544C515.3 544 544 515.3 544 480L544 237.3C544 220.3 "
        "537.3 204 525.3 192L448 114.7C436 102.7 419.7 96 402.7 96L160 "
        "96zM192 192C192 174.3 206.3 160 224 160L384 160C401.7 160 416 "
        "174.3 416 192L416 256C416 273.7 401.7 288 384 288L224 288C206.3 "
        "288 192 273.7 192 256L192 192zM320 352C355.3 352 384 380.7 384 "
        "416C384 451.3 355.3 480 320 480C284.7 480 256 451.3 256 416C256 "
        "380.7 284.7 352 320 352z",
    "file-export":
        "M128.5 64C93.2 64 64.5 92.7 64.5 128L64.5 512C64.5 547.3 93.2 "
        "576 128.5 576L384.5 576C419.8 576 448.5 547.3 448.5 512L448.5 "
        "416L526.6 416L495.6 447C486.2 456.4 486.2 471.6 495.6 480.9C505 "
        "490.2 520.2 490.3 529.5 480.9L601.5 408.9C610.9 399.5 610.9 "
        "384.3 601.5 375L529.5 303C520.1 293.6 504.9 293.6 495.6 "
        "303C486.3 312.4 486.2 327.6 495.6 336.9L526.6 367.9L448.5 "
        "367.9L448.5 234.4C448.5 217.4 441.8 201.1 429.8 189.1L323.2 "
        "82.7C311.2 70.7 295 64 278 64L128.5 64zM390 240L296.5 240C283.2 "
        "240 272.5 229.3 272.5 216L272.5 122.5L390 240zM256.5 392C256.5 "
        "378.7 267.2 368 280.5 368L384.5 368L384.5 416L280.5 416C267.2 "
        "416 256.5 405.3 256.5 392z",
    "file-pen":
        "M128.1 64C92.8 64 64.1 92.7 64.1 128L64.1 512C64.1 547.3 92.8 "
        "576 128.1 576L274.3 576L285.2 521.5C289.5 499.8 300.2 479.9 "
        "315.8 464.3L448 332.1L448 234.6C448 217.6 441.3 201.3 429.3 "
        "189.3L322.8 82.7C310.8 70.7 294.5 64 277.6 64L128.1 64zM389.6 "
        "240L296.1 240C282.8 240 272.1 229.3 272.1 216L272.1 122.5L389.6 "
        "240zM332.3 530.9L320.4 590.5C320.2 591.4 320.1 592.4 320.1 "
        "593.4C320.1 601.4 326.6 608 334.7 608C335.7 608 336.6 607.9 "
        "337.6 607.7L397.2 595.8C409.6 593.3 421 587.2 429.9 578.3L548.8 "
        "459.4L468.8 379.4L349.9 498.3C341 507.2 334.9 518.6 332.4 "
        "531zM600.1 407.9C622.2 385.8 622.2 350 600.1 327.9C578 305.8 "
        "542.2 305.8 520.1 327.9L491.3 356.7L571.3 436.7L600.1 407.9z",
    "eye":
        "M320 96C239.2 96 174.5 132.8 127.4 176.6C80.6 220.1 49.3 272 "
        "34.4 307.7C31.1 315.6 31.1 324.4 34.4 332.3C49.3 368 80.6 420 "
        "127.4 463.4C174.5 507.1 239.2 544 320 544C400.8 544 465.5 507.2 "
        "512.6 463.4C559.4 419.9 590.7 368 605.6 332.3C608.9 324.4 608.9 "
        "315.6 605.6 307.7C590.7 272 559.4 220 512.6 176.6C465.5 132.9 "
        "400.8 96 320 96zM176 320C176 240.5 240.5 176 320 176C399.5 176 "
        "464 240.5 464 320C464 399.5 399.5 464 320 464C240.5 464 176 "
        "399.5 176 320zM320 256C320 291.3 291.3 320 256 320C244.5 320 "
        "233.7 317 224.3 311.6C223.3 322.5 224.2 333.7 227.2 344.8C240.9 "
        "396 293.6 426.4 344.8 412.7C396 399 426.4 346.3 412.7 "
        "295.1C400.5 249.4 357.2 220.3 311.6 224.3C316.9 233.6 320 244.4 "
        "320 256z",
    "magnifying-glass":
        "M480 272C480 317.9 465.1 360.3 440 394.7L566.6 521.4C579.1 533.9 "
        "579.1 554.2 566.6 566.7C554.1 579.2 533.8 579.2 521.3 "
        "566.7L394.7 440C360.3 465.1 317.9 480 272 480C157.1 480 64 386.9 "
        "64 272C64 157.1 157.1 64 272 64C386.9 64 480 157.1 480 272zM272 "
        "416C351.5 416 416 351.5 416 272C416 192.5 351.5 128 272 "
        "128C192.5 128 128 192.5 128 272C128 351.5 192.5 416 272 416z",
    "code-compare":
        "M262.8 65.8C271.8 62.1 282.1 64.1 289 71L345 127C354.4 136.4 "
        "354.4 151.6 345 160.9L289 216.9C282.1 223.8 271.8 225.8 262.8 "
        "222.1C253.8 218.4 248 209.7 248 200L248 176L224 176C206.3 176 "
        "192 190.3 192 208L192 422.7C220.3 435 240 463.2 240 496C240 "
        "540.2 204.2 576 160 576C115.8 576 80 540.2 80 496C80 463.2 99.7 "
        "435 128 422.7L128 208C128 155 171 112 224 112L248 112L248 88C248 "
        "78.3 253.8 69.5 262.8 65.8zM456 144C456 157.3 466.7 168 480 "
        "168C493.3 168 504 157.3 504 144C504 130.7 493.3 120 480 "
        "120C466.7 120 456 130.7 456 144zM448 217.3C419.7 205 400 176.8 "
        "400 144C400 99.8 435.8 64 480 64C524.2 64 560 99.8 560 144C560 "
        "176.8 540.3 205 512 217.3L512 432C512 485 469 528 416 528L392 "
        "528L392 552C392 561.7 386.2 570.5 377.2 574.2C368.2 577.9 357.9 "
        "575.9 351 569L295 513C285.6 503.6 285.6 488.4 295 479.1L351 "
        "423.1C357.9 416.2 368.2 414.2 377.2 417.9C386.2 421.6 392 430.3 "
        "392 440L392 464L416 464C433.7 464 448 449.7 448 432L448 "
        "217.3zM136 496C136 509.3 146.7 520 160 520C173.3 520 184 509.3 "
        "184 496C184 482.7 173.3 472 160 472C146.7 472 136 482.7 136 496z",
}


def _ellipse(cx: float, cy: float, rx: float, ry: float,
             reverse: bool = False) -> str:
    """One closed ellipse, as four cubics.

    `reverse` winds it the other way, which is how a hole is made: winding fill
    cancels a subpath drawn against the one containing it. `location-dot`'s
    counter is the same trick, done by Font Awesome's exporter.
    """
    k = 0.5523                                  # the circle's magic constant
    ax, ay = rx * k, ry * k
    pts = [((cx + rx, cy), (cx + rx, cy + ay), (cx + ax, cy + ry),
            (cx, cy + ry)),
           ((cx, cy + ry), (cx - ax, cy + ry), (cx - rx, cy + ay),
            (cx - rx, cy)),
           ((cx - rx, cy), (cx - rx, cy - ay), (cx - ax, cy - ry),
            (cx, cy - ry)),
           ((cx, cy - ry), (cx + ax, cy - ry), (cx + rx, cy - ay),
            (cx + rx, cy))]
    if reverse:
        pts = [tuple(reversed(seg)) for seg in reversed(pts)]
    out = [f"M{pts[0][0][0]:.1f} {pts[0][0][1]:.1f}"]
    for seg in pts:
        out.append("C" + " ".join(f"{x:.1f} {y:.1f}" for x, y in seg[1:]))
    return "".join(out) + "z"


def _star(cx: float, cy: float, points: int, outer: float, inner: float,
          turn: float = -90.0) -> str:
    """A `points`-pointed star, first point at `turn` degrees.

    Two of these: the wand's tip and the mace's head. Written as one function
    because a hand-typed sixteen-vertex polygon is where the typo lives.
    """
    verts = []
    for i in range(points * 2):
        r = outer if i % 2 == 0 else inner
        a = math.radians(turn + i * 180.0 / points)
        verts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return _poly(verts)


# A dagger for the thief: the sword's shape, two thirds the blade and a guard
# that is wide for its length. Whether that difference survives 13px is the
# question the sheet is for.
_DAGGER = ((320, 70), (376, 210), (376, 330), (452, 330), (452, 390),
           (360, 390), (360, 520), (280, 520), (280, 390), (188, 390),
           (188, 330), (264, 330), (264, 210))
_DAGGER_POMMEL = (252, 514, 136, 58)

CANDIDATES_OURS = {
    # A wizard's hat whose brim is part of the cone rather than a bar under it.
    # That is the whole fix for `hat-wizard`'s shark's fin: one silhouette
    # cannot come apart into two, and the brim is what says "hat".
    "wizard-hat": _poly(((372, 50), (440, 460), (560, 460), (560, 560),
                         (80, 560), (80, 460), (185, 460))),
    # A wand: one thick diagonal bar with the star grown onto its tip, so the
    # star cannot float away as a separate mark at 13px. It can lose its points
    # and still read as a bar with a bulb.
    "wand": (_poly(((56, 516), (124, 584), (434, 274), (366, 206)))
             + _star(450, 190, 4, 155, 58)),
    # A scroll: a sheet with a curl top and bottom, the curls drawn as ellipses
    # wider than the sheet so the silhouette bulges where a roll would. The
    # first version made them plain bars and it read as a cotton reel.
    "parchment": (_rect(205, 150, 230, 340) + _ellipse(320, 150, 200, 62)
                  + _ellipse(320, 490, 200, 62)),
    "dagger": _poly(_DAGGER) + _rect(*_DAGGER_POMMEL),
    # A hooded figure: cowl, shoulders, and the face as the one hole -- the
    # `location-dot` rule applied deliberately rather than inherited. The
    # shoulders are what stop it reading as an archway.
    "hood": ("M320 45C405 115 445 205 445 300C445 340 600 385 600 565"
             "L40 565C40 385 195 340 195 300C195 205 235 115 320 45z"
             + _ellipse(320, 275, 78, 100, reverse=True)),
    # A mace: a flanged head on a haft, the head an eight-lobed mass rather
    # than four spikes -- four spikes at 13px is a cross, which is the cleric
    # icon it is meant to be an alternative to.
    "mace": _star(320, 185, 8, 158, 118) + _rect(282, 230, 76, 340),
}

CANDIDATES: dict[str, str] = {**CANDIDATES_FONT_AWESOME, **CANDIDATES_OURS}

ICONS: dict[str, str] = {**FONT_AWESOME, **OURS, **CANDIDATES}

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
