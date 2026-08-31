"""Small vector icons, as SVG path data. No Qt in here.

**Why paths and not a font.** A write-up since lost,
`work/reports/font-awesome.md`, weighed three ways of getting icons: `qtawesome`, bundling `Font Awesome 7 Free-Solid-900.otf`, and
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
verbatim from `svgs-full/`, `solid/` except for `gem`, which Donald chose in
the **regular** weight; the licence text is in
`fontawesome-LICENSE.txt` and the attribution is carried in the
README and the About box. Brands are not used and must not be: the licence
forbids brand-logo use and the set carries `wizards-of-the-coast`.

Icons under `OURS` are this project's own. Three reasons an icon gets drawn
here rather than lifted: Font Awesome Free has **no sword** -- `sword` and
`swords` are Pro-only, and `khanda` is a Sikh religious emblem, wrong in
meaning and illegible at twelve pixels; `hat-wizard`'s brim is a separate
subpath that stops touching the cone at 13px and reads as a shark's fin; and
`mask` stays perfectly legible while reading as goggles.

`TEXT_GLYPHS` are neither: a **character**, drawn from whatever font the
platform resolves it to. There is exactly one, the Encounter note's U+2694
crossed swords, and it is Donald's choice. It is not path data and does not
scale from the 640 box, so `ui/iconpaint.py` fits it to the box by its own ink
-- and it looks like whatever the machine has. Here that is DejaVu Sans and
monochrome; on Windows and macOS the same code point is commonly resolved to
the colour emoji font instead. See `docs/109-icon-choices.md`.

**`hat-wizard` is in the table anyway**, because the *application* icon is
drawn from it -- `ui/appicon.py`, at 16 px and up on a tile, where the sizes
that matter are 32 and above. It is not the magic-user's glyph on the map and
must not be used as one: at 13px the finding above still stands.

**The 13px rule these were drawn to.** One connected silhouette, with at most
one hole and that hole no smaller than about 64 units in the 640 box. Hole
*count* is not what matters -- a large second counter survives -- and the
failure that kills a glyph is separation, not mush.

**That rule now binds in one place only.** The map cell draws a note at
`render.NOTE_SIZE`, which is 26; the note editor's picker is 15. The last 13px
consumer is the notes list in `automap/panel.py`. A new icon still has to pass
the rule to go in that list, and no longer has to pass it to go on the map.
`docs/109-icon-choices.md` carries the sheet and the sizes.
"""

from __future__ import annotations

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
    "hat-wizard":
        "M128 464L213.7 255.8C230.7 214.5 261.5 180.5 300.9 "
        "159.5L447.8 81.2C460.1 74.6 474.3 85.9 470.8 99.4L433.6 "
        "241.8C432.5 245.9 432 250.1 432 254.4C432 260.7 433.2 267 "
        "435.6 272.9L512 464L304.9 464L316.7 428.6L357.1 415.1C363.6 "
        "412.9 368 406.8 368 399.9C368 393 363.6 386.9 357.1 "
        "384.7L316.7 371.2L303.2 330.8C301 324.4 294.9 320 288 "
        "320C281.1 320 275 324.4 272.8 330.9L259.3 371.3L218.9 "
        "384.8C212.4 387 208 393.1 208 400C208 406.9 212.4 413 218.9 "
        "415.2L259.3 428.7L271.1 464.1L128 464.1zM343.6 205.5C342.5 "
        "202.2 339.5 200 336 200C332.5 200 329.5 202.2 328.4 "
        "205.5L321.7 225.7L301.5 232.4C298.2 233.5 296 236.5 296 "
        "240C296 243.5 298.2 246.5 301.5 247.6L321.7 254.3L328.4 "
        "274.5C329.5 277.8 332.5 280 336 280C339.5 280 342.5 277.8 "
        "343.6 274.5L350.3 254.3L370.5 247.6C373.8 246.5 376 243.5 376 "
        "240C376 236.5 373.8 233.5 370.5 232.4L350.3 225.7L343.6 "
        "205.5zM96 512L544 512C561.7 512 576 526.3 576 544C576 561.7 "
        "561.7 576 544 576L96 576C78.3 576 64 561.7 64 544C64 526.3 "
        "78.3 512 96 512z",
    # The Treasure note. **Regular weight, not solid** -- Donald picked
    # the outline, and on graph paper a filled lozenge reads as terrain,
    # which is what the drawn chest it replaces was avoiding. Verbatim
    # from `svgs-full/regular/`, the one icon here not from `solid/`.
    "gem":
        "M232.5 136L320 229L407.5 136L232.5 136zM447.9 163.1L375.6 "
        "240L504.6 240L448 163.1zM497.9 288L142.1 288L320 484.3L497.9 "
        "288zM135.5 240L264.5 240L192.2 163.1L135.6 240zM569.8 "
        "280.1L337.8 536.1C333.3 541.1 326.8 544 320 544C313.2 544 "
        "306.8 541.1 302.2 536.1L70.2 280.1C62.5 271.6 61.9 258.9 "
        "68.7 249.7L180.7 97.7C185.2 91.6 192.4 87.9 200 87.9L440 "
        "87.9C447.6 87.9 454.8 91.5 459.3 97.7L571.3 249.7C578.1 "
        "258.9 577.4 271.6 569.8 280.1z",
    # The quickfight badge on a roster card -- `panel.CharacterCard`, drawn at
    # `ICON_SIZE`. Three subpaths (head, body, trailing arm), which the 13px
    # rule normally rejects; it passes because the separations are the ones a
    # reader of a running figure expects to see, and every limb is wider than
    # the 64-unit floor. Judged on `tools/iconsheet.py`'s magnified column.
    "person-running":
        "M352.5 32C383.4 32 408.5 57.1 408.5 88C408.5 118.9 383.4 144 352.5"
        " 144C321.6 144 296.5 118.9 296.5 88C296.5 57.1 321.6 32 352.5 "
        "32zM219.6 240C216.3 240 213.4 242 212.2 245L190.2 299.9C183.6 "
        "316.3 165 324.3 148.6 317.7C132.2 311.1 124.2 292.5 130.8 "
        "276.1L152.7 221.2C163.7 193.9 190.1 176 219.6 176L316.9 176C345.4 "
        "176 371.7 191.1 386 215.7L418.8 272L480.4 272C498.1 272 512.4 "
        "286.3 512.4 304C512.4 321.7 498.1 336 480.4 336L418.8 336C396 336 "
        "375 323.9 363.5 304.2L353.5 287.1L332.8 357.5L408.2 380.1C435.9 "
        "388.4 450 419.1 438.3 445.6L381.7 573C374.5 589.2 355.6 596.4 "
        "339.5 589.2C323.4 582 316.1 563.1 323.3 547L372.5 436.2L276.6 "
        "407.4C243.9 397.6 224.6 363.7 232.9 330.6L255.6 240L219.7 "
        "240zM211.6 421C224.9 435.9 242.3 447.3 262.8 453.4L267.5 "
        "454.8L260.6 474.1C254.8 490.4 244.6 504.9 231.3 515.9L148.9 "
        "583.8C135.3 595 115.1 593.1 103.9 579.5C92.7 565.9 94.6 545.7 "
        "108.2 534.5L190.6 466.6C195.1 462.9 198.4 458.1 200.4 452.7L211.6 "
        "421z",
}


OURS: dict[str, str] = {}

ICONS: dict[str, str] = {**FONT_AWESOME, **OURS}

#: Icons that are a **character**, not a path. `ui/iconpaint.py` draws these
#: with the system font and fits them to the same box the paths are drawn in.
#:
#: The Encounter note is the only one. `swords`, drawn here, was replaced by
#: Donald's choice of U+2694 -- which buys a real pair of crossed swords in
#: place of the starburst ours read as, and costs the guarantee that every
#: note on the map is drawn by the same hand.
TEXT_GLYPHS: dict[str, str] = {
    "crossed-swords": "⚔",
}

#: Every name a caller may ask for, drawn by either route.
NAMES: frozenset[str] = frozenset(ICONS) | frozenset(TEXT_GLYPHS)


def is_text(name: str) -> bool:
    """Is this icon a font character rather than path data?"""
    return name in TEXT_GLYPHS


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
