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

Each set has its own square canvas -- 640 for Font Awesome's `svgs-full`, 512
for game-icons.net -- so placement is scale by `size / box(name)` and
translate. Nothing is rescaled into a common box on the way in: the path data
is the artist's file byte for byte, which is what makes it diffable against the
archive it came from.

`commands()` reads the whole of the path grammar those two sets use -- absolute
and relative moves, lines, `H`/`V`, cubics, smooth cubics and elliptical arcs
-- and hands back moves, lines, cubics and closes. It grew from twenty lines
when the game-icons set arrived, and it grew rather than the icons being
redrawn into a simpler `d`, because redrawing somebody's art is the one thing
this file must not do.

---

Icons under `FONT_AWESOME` are **Font Awesome Free 7.3.1 by Fonticons, Inc.**
(https://fontawesome.com), icons licensed **CC BY 4.0**. The path data is
verbatim from `svgs-full/`, `solid/` except for `gem`, which Donald chose in
the **regular** weight; the licence text is in
`fontawesome-LICENSE.txt` and the attribution is carried in the
README and the About box. Brands are not used and must not be: the licence
forbids brand-logo use and the set carries `wizards-of-the-coast`.

---

Icons under `GAME_ICONS` are from **game-icons.net**, licensed **CC BY 3.0**,
each verbatim from the artist's own SVG. `ARTISTS` says who drew which, so an
attribution file can be generated from what actually ships rather than retyped.
Donald chose all eight by name; nothing here was picked by an assistant.

**Wish ships both sets, deliberately.** The instruction to replace every Font
Awesome icon was withdrawn on 2026-08-31 -- nine of them have no counterpart in
the chosen list -- so `door-open`, `lock`, `stairs`, `check`,
`triangle-exclamation`, `trash-can`, `folder-open`, `floppy-disk`, `eye` and
`hat-wizard` stay as they are. Font Awesome's are line-weight glyphs and
game-icons.net's are solid silhouettes, and a roster card now draws both.

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

import math
import re

#: Every Font Awesome icon is drawn in this box, matching `svgs-full`'s canvas.
#: It is also the box a caller gets for an icon it does not ask `box()` about.
BOX = 640

#: game-icons.net draws on 512. Its SVGs are kept verbatim rather than rescaled
#: into 640, so the committed path data can be diffed against the artist's file
#: -- and `box()` is what stops a 512 glyph being drawn at four-fifths size.
GAME_ICONS_BOX = 512

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


#: Icons from **game-icons.net**, licensed **CC BY 3.0**
#: (https://creativecommons.org/licenses/by/3.0/). Each one is verbatim from
#: the artist's own SVG in the archive Donald keeps, drawn on that site's
#: uniform **512** box rather than Font Awesome's 640 -- see `box()`.
#:
#: Donald chose every one of these by name and by artist; nothing here was
#: picked, redrawn or nudged to fit. `ARTISTS` below records who drew what,
#: because attribution is the whole of what CC BY asks for and a licence file
#: is worth more generated from the table that ships than retyped beside it.
GAME_ICONS = {
    "death-skull":
        "M255.997 16.004c-120 0-239.997 60-239.997 149.998C16 226.002 61 "
        "256 61 316c0 45-15 45-15 75 0 14.998 48.01 32.002 89.998 "
        "44.998v60h239.997v-60s90.567-27.957 "
        "90-45c-.933-27.947-15-30-15-74.998 0-30 45.642-91.42 "
        "44.998-149.998 0-90-119.998-149.998-239.996-149.998zm-90 "
        "179.997c33.137 0 60 26.864 60 60 0 33.136-26.863 60-60 60C132.863 "
        "316 106 289.136 106 256c0-33.136 26.862-60 59.998-60zm179.998 "
        "0c33.136 0 60 26.864 60 60 0 33.136-26.864 60-60 60-33.136 "
        "0-60-26.864-60-60 0-33.136 26.864-60 60-60zm-89.998 105c15 0 45 "
        "60 45 75 0 29.998 0 29.998-15 29.998h-60c-15 0-15 0-15-30 0-15 "
        "30-74.998 45-74.998z",
    "oppression":
        "M19.188 16.406V123.28l153.593 "
        "81.75-70.655-188.624H19.187zm109.812 0L248.125 "
        "161.22l5.25-144.814H129zm165.25 0 40.906 133.156 "
        "60.72-133.156H294.25zm140.188 0-14.594 155.938 "
        "74.75-69.5V16.406h-60.156zM19.188 167.062v97.532l99.874 "
        "9.937L19.19 167.064zm409.406 40.313c-17.884-.094-38.853 "
        "9.07-55.938 26.156a100.137 100.137 0 0 0-13.562 "
        "16.845c-93.737-56.476-329.936 76.333-179 189.78H60.78l-26.468 "
        "47.72H291.5L203 384.625c24.27-26.708 67.458-43.704 97-45.063 "
        "13.793 45.098 36.265 113.497 71.75 "
        "148.313h60.844c-43.07-46.547-76.538-109.09-81.938-179.844a33.574 "
        "33.574 0 0 0 6.313 8.783c18.662 18.663 55.944 11.648 "
        "83.28-15.688s34.35-64.618 "
        "15.688-83.28c-7-7-16.614-10.413-27.344-10.47zM19.188 "
        "323v59.563l77.687-23.938L19.187 323z",
    "running-ninja":
        "M378.321 58.818c-3.95 6.585-5.374 14.345-2.228 20.761 8.425 5.494 "
        "50.968 15.802 47.286 29.773-.784 2.301-1.087 3.54-1.515 "
        "5.224-7.4-6.764-22.462-10.05-27.902-9.049-4.832.843-9.721 "
        "3.05-14.44 3.248-5.986-.032-11.34-1.516-15.925-4.254 3.24 8.943 "
        "14.85 15.537 22.049 14.412 11.318-2.258 23.535 3.723 31.779 "
        "6.67-5.055 13.86-22.014 7.334-22.014 7.334l-121.937-28.02L253.44 "
        "90.45l-17.34 17.72 88.945 29.131-120.023 "
        "2.676-29.907-12.486-40.77 23.617 182.99 13.291-56.212 "
        "59.426h99.22c19.341-15.746 63.009-51.2 63.645-50.793 12.867 "
        "29.973 33.256 19.023 48.815 1.55 4.515-5.069 9.47 12.362 "
        "12.021-16.015.64-1 1.217-2.011 1.772-3.03-18.028-7.661-48.58 "
        "5.732-31.817-17.992 5.135-7.262 20.776-5.296 36.871 "
        "3.97.582-15.262-1.056-42.396-15.484-48.39-14.85-6.169-34.024-5.48-41.316 "
        "2.682-9.946-16.88-39.574-19.07-51.307-20.764-3.453-5.429-4.558-10.479-5.223-16.226zm-188.328 "
        "59.236-4.558 4.034 16.138 6.853 10.852-10.887zm276.578 "
        "24.354c6.542 4.808 7.01 5.943 11.393 6.1 1.597-1.021 5.12-4.613 "
        "1.857-5.37l-11.04-2.203c-1.14-.204-2.02.646-2.21 1.473zM148.167 "
        "160.44l-5.95 5.264h22.43l5.952-5.264zm-39.285 13.598-12 "
        "15.357h15.855l5.461-6.414h42.592l-7.937 "
        "6.94h15.953l16-15.356zm15.664 15.933L20.251 309.592l23.027-4.516 "
        "98.618-115.104zM251.3 234.216 119.878 373.16l-16.697 "
        "4.265s-12.898 29.813-18.834 65.059c7.659 4.113 17.39-8.02 "
        "17.39-8.02s-1.1 13.09 6.64 9.743c14.097-28.569 29.864-58.248 "
        "29.864-58.248l159.721-121.877 20.994 5.584 27.758 7.386-62.557 "
        "58.727-11.238-12.15s-34.319 38.069-47.305 66.224c4.13 4.74 "
        "20.33-7.64 20.33-7.64s-5.369 9.615 1.932 9.31c17.808-16.694 "
        "29.682-29.826 29.682-29.826l132.82-98.543-48.23-28.938z",
    "healing-shield":
        "M256 21.98c-64 48-128 68-224.03 100.02C31.97 234 112 394 256 "
        "490c144-96 224-250 224-362-96-32.02-160-58.02-224-106.02zM229 "
        "128h54v101h101v54H283v101h-54V283H128v-54h101V128z",
    "embrassed-energy":
        "M179.813 20.72v81.25L135.78 75.624l17.564 46.938-115.656-20.938 "
        "84.718 49.906H20v27.345l110.47 14.875 "
        "96.593-29.188c-11.303-11.87-18.594-30.743-18.594-52 0-35.926 "
        "20.87-65.062 46.624-65.062 25.753 0 46.625 29.136 46.625 65.063 0 "
        "20.847-7.038 39.375-17.97 51.28l99.03 29.907 "
        "112.5-15.156V151.53H394.19l84.718-49.905-120.437 21.78 "
        "17.874-47.718-48.656 29.126V20.72H179.813zM495.28 223.343l-112.5 "
        "22.437-55.405-13.124-28.03 118.313 16.592 145h51.688L329.25 "
        "351.22l46.53 27.842-21.31-56.937 124.436 "
        "22.5-91.125-53.688h107.5v-67.593zM20 "
        "223.75v67.188h108.813l-91.125 53.687L157.31 322.97 136.345 "
        "379l38.47-23-28.595 "
        "139.97h48.155l12.905-144.41-21.685-118.84-55.125 13.06L20 223.75z",
    # Replaces `invisible`, which was drawn in dashes -- 55 ink pixels of a
    # 640-box glyph at 13px, against 5,000-9,500 for the rest of the set, and
    # a pale smudge on the card rather than a badge. `docs/136-condition-badges.md`
    # has the measurement. Donald chose this one; 81 ink pixels at 13px, and
    # it reads as a closed eye.
    "eyelashes":
        "M211.3 80.89C122.5 81.18 56.21 109.7 18.89 145l12.36 13C93.43 "
        "99.36 258.4 54.4 485.6 176.8l8.6-15.8c-108.8-58.6-204.6-80.37-282.9-80.11zm-96.9 "
        "84.81c-55.98 21.9-81.16 65.6-96.64 94.4l15.86 8.6c15.24-28.5 "
        "37.13-66.6 87.38-86.2 50.2-19.6 130.5-20.9 263.1 30.7l6.6-16.8c-91.7-32.6-187-64.8-276.3-30.7zm260.4 "
        "76c-177.5 91.5-260 65.2-352.46 41.4l-4.48 17.5c15.96 4.1 31.94 "
        "8.3 48.39 11.9-19.36 13.6-28.82 17.2-40.19 24.6 25.65-1.1 "
        "42.18-9.2 59.71-16.6-12.58 15.5-23.55 31-46 47.4 27.02-7.2 "
        "53.04-15.2 72.63-28.8-12.47 20-27.72 39.5-44.89 58.6 29.43-9.2 "
        "51.69-31.4 74.79-53.4-.3 19.1-9.2 38.2-15.5 57.3 21-19.3 30-33.2 "
        "42.7-52.5-1.2 29.2 7 52.8 14.2 82 4.5-27.9 9.5-55.9 9.5-82.9 15 "
        "25 35.1 47.8 60.4 68.1-13.5-23.5-27-46.9-34.1-71.3 25.8 24.5 "
        "52.7 48.3 85 68.2-21.5-23.5-41.9-47.3-55.1-72.7 23.2 21.8 46.5 "
        "43.6 85.3 56.2-28.1-19.3-46.1-41.2-59.3-64.3 26.7 22.4 56.6 "
        "42.3 92.7 57.2-31.9-22-49.9-44-62.2-66 26.4 21.8 56.6 36.2 "
        "82.9 50.6-20.8-19.2-43.5-37.6-54.4-60.4 21.5 18.7 46.9 26.8 72 "
        "35.5-23.3-15.5-36.7-26-50.6-44.3 22.2 11.2 40.7 15.6 67.4 "
        "22.2-17.4-9.7-35.9-23-47.8-34.5 26.7 6.7 56 7.8 83.6 "
        "7.4-25.3-6.6-52.8-12.4-67.4-22.5 58.4.5 62-4.6 86.5-16.8-51.8 "
        "3.8-84.7 2.9-103.3-19.1z",
    "strong":
        "M257.375 20.313c-13.418 0-26.07 7.685-35.938 21.75-9.868 "
        "14.064-16.343 34.268-16.343 56.75 0 22.48 6.475 42.654 16.344 "
        "56.718 9.868 14.066 22.52 21.75 35.937 21.75 13.418 0 "
        "26.038-7.684 35.906-21.75 9.87-14.063 16.376-34.236 16.376-56.718 "
        "0-22.48-6.506-42.685-16.375-56.75-9.867-14.064-22.487-21.75-35.905-21.75zm-150.25 "
        "43.062c-20.305.574-23.996 13.892-31.78 29.03-23.298 45.304-55.564 "
        "164.75-55.564 164.75l160.47-5.436 29.125 137.593-22.78 "
        "106.03h149.093l-22.282-106 24.25-137.5 157.53 5.313c.002 "
        "0-32.264-119.447-55.56-164.75-7.787-15.14-11.477-28.457-31.782-29.03-17.898 "
        "0-32.406 15.552-32.406 34.718 0 19.166 14.508 34.72 32.406 34.72 "
        "3.728 0 7.258-.884 10.594-2.126l7.937 74.406L309.437 "
        "165c-.285.42-.552.867-.843 1.28-12.436 17.724-30.604 29.69-51.22 "
        "29.69-20.614 "
        "0-38.782-11.966-51.218-29.69-.277-.395-.54-.816-.812-1.218l-116.75 "
        "40.032 7.937-74.406c3.337 1.242 6.867 2.125 10.595 2.125 17.898 0 "
        "32.406-15.553 32.406-34.72 0-19.165-14.507-34.718-32.405-34.718z",
    "sparkling-sabre":
        "M403.563 16.875c-34.11 33.744-53.907 25.412-89.094 4.844 31.052 "
        "27.848 44.703 40.722 9.25 76.124 32.57-26.112 44.422-29.22 "
        "85.342-15-23.523-25.805-21.323-36.88-5.5-65.97zm90.312 "
        "24.406C463.23 68.004 425.365 93.7 386.687 113c1.152 61.455-37.802 "
        "117.82-99.125 165.406C221 330.06 127.345 372.848 24.344 "
        "404.28v41.22A1179.51 1179.51 0 0 0 73 434.47c-2.655 14.497-11.253 "
        "27.387-28.938 39.81 43.158-14.862 52.446-1.325 76.188 "
        "18.814-7.644-26.835-5.256-36.344 34.625-58.438-32.328 "
        "9.304-48.716 5.836-63.03-5.094 74.51-20.002 153.373-49.706 "
        "221.25-93.625 6.362 31.056 5.325 56.495-36.19 94.282 "
        "67.325-35.667 96.207-34.27 130.97 "
        "7.155-34.905-53.113-30.953-75.32 14.063-123.97-42.665 33.767-70.8 "
        "30.987-94.063 12.626.615-.427 1.23-.85 1.844-1.28 90.41-63.473 "
        "157.526-153.397 164.155-283.47zM240.75 70.97c4.865 36.552-4.39 "
        "56.492-23.938 78.53 31.65-24.863 39.97-22.61 "
        "71.157-23-28.584-13.45-36.21-20.397-47.22-55.53zm-110.78 "
        "40.686c-27.298 60.18-58.556 70.662-107.626 70.125 59.78 20.1 "
        "64.886 52.96 69.906 106.25 19.34-58.957 36.19-76.01 "
        "78.72-58.217-41.78-31.838-45.743-48.97-41-118.157zm237.936 "
        "10.188c-30.864 13.607-61.587 22.598-88.937 24.28-2.278 "
        "16.52-11.623 32.867-25.19 49-15.767 18.755-37.557 37.463-62.78 "
        "55.69-49.014 35.414-110.962 68.736-166.656 "
        "94.28v39.625c99.33-30.83 189.144-72.456 251.78-121.064 "
        "55.735-43.25 89.362-90.922 91.782-141.812zm99.53 98.97c-7.594 "
        "35.52-13.903 44.526-46.655 65.31 35.874-8.104 51.316-1.513 74.533 "
        "15.032-22.447-30.02-28.5-41.96-27.875-80.344zM259.75 400.78c-30 "
        "43.11-55.372 48.865-98.656 52.22 51.72 7.82 65.302 14.218 95.875 "
        "41.094-12.9-35.393-15.344-48.14 2.78-93.313z",
}

#: Who drew each game-icons.net glyph, spelled as the site spells it.
ARTISTS = {
    "death-skull": "sbed",
    "oppression": "Lorc",
    "running-ninja": "Darkzaitzev",
    "healing-shield": "Delapouite",
    "embrassed-energy": "Lorc",
    "eyelashes": "Delapouite",
    "strong": "Lorc",
    "sparkling-sabre": "Lorc",
}


OURS: dict[str, str] = {}

ICONS: dict[str, str] = {**FONT_AWESOME, **GAME_ICONS, **OURS}

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


_TOKEN = re.compile(r"[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")

#: How many numbers each command takes.
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "A": 7, "Z": 0}

#: A repeated coordinate group after `M` is a line, per SVG; every other
#: command repeats itself.
_AFTER = {"M": "L", "m": "l"}


def box(name: str) -> float:
    """The side of the square this icon is drawn in.

    Two sets, two canvases: Font Awesome's `svgs-full` is 640 and
    game-icons.net's is 512. Everything that paints an icon scales by
    `size / box(name)`, so the two sets come out the same size beside each
    other on a roster card.
    """
    return GAME_ICONS_BOX if name in GAME_ICONS else BOX


def path_data(name: str) -> str:
    """The raw SVG `d`, for `to_svg` to write out unchanged."""
    return ICONS[name]


def _arc(x0: float, y0: float, rx: float, ry: float, rotation: float,
         large: int, sweep: int, x: float, y: float) -> list[tuple]:
    """One SVG elliptical arc as cubic segments, at most a quarter turn each.

    Every renderer does this; Qt's `QPainterPath` cannot take an arc with a
    rotated axis at all. The maths is the endpoint-to-centre conversion in
    SVG 1.1 appendix F.6, and the 4/3*tan(step/4) tangent scale is the
    standard circular-arc approximation.

    Three arcs reach here, all in game-icons.net glyphs Donald chose:
    `oppression` has two and `sparkling-sabre` one, and all three are circles
    with no rotation.
    """
    if rx == 0 or ry == 0 or (x0, y0) == (x, y):
        return [("L", x, y)]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(rotation)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx, dy = (x0 - x) / 2, (y0 - y) / 2
    x1 = cos_p * dx + sin_p * dy
    y1 = -sin_p * dx + cos_p * dy
    # F.6.6: radii too small to span the chord are grown until they fit.
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx *= math.sqrt(lam)
        ry *= math.sqrt(lam)
    numerator = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    denominator = rx * rx * y1 * y1 + ry * ry * x1 * x1
    coefficient = math.sqrt(max(0.0, numerator / denominator))
    if large == sweep:
        coefficient = -coefficient
    cx1 = coefficient * rx * y1 / ry
    cy1 = -coefficient * ry * x1 / rx
    cx = cos_p * cx1 - sin_p * cy1 + (x0 + x) / 2
    cy = sin_p * cx1 + cos_p * cy1 + (y0 + y) / 2

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        size = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, dot / size)))
        return -a if ux * vy - uy * vx < 0 else a

    ux, uy = (x1 - cx1) / rx, (y1 - cy1) / ry
    vx, vy = (-x1 - cx1) / rx, (-y1 - cy1) / ry
    theta = angle(1, 0, ux, uy)
    sweep_angle = angle(ux, uy, vx, vy)
    if not sweep and sweep_angle > 0:
        sweep_angle -= 2 * math.pi
    elif sweep and sweep_angle < 0:
        sweep_angle += 2 * math.pi

    pieces = max(1, math.ceil(abs(sweep_angle) / (math.pi / 2)))
    step = sweep_angle / pieces
    tangent = 4 / 3 * math.tan(step / 4)
    out = []
    for i in range(pieces):
        a0 = theta + i * step
        a1 = a0 + step
        c0, s0 = math.cos(a0), math.sin(a0)
        c1, s1 = math.cos(a1), math.sin(a1)
        p0x = cx + rx * c0 * cos_p - ry * s0 * sin_p
        p0y = cy + rx * c0 * sin_p + ry * s0 * cos_p
        p1x = cx + rx * c1 * cos_p - ry * s1 * sin_p
        p1y = cy + rx * c1 * sin_p + ry * s1 * cos_p
        d0x = -rx * s0 * cos_p - ry * c0 * sin_p
        d0y = -rx * s0 * sin_p + ry * c0 * cos_p
        d1x = -rx * s1 * cos_p - ry * c1 * sin_p
        d1y = -rx * s1 * sin_p + ry * c1 * cos_p
        out.append(("C", p0x + tangent * d0x, p0y + tangent * d0y,
                    p1x - tangent * d1x, p1y - tangent * d1y, p1x, p1y))
    return out


def commands(name: str) -> tuple[tuple, ...]:
    """`d` parsed into `("M", x, y)`, `("L", x, y)`, `("C", *6)` and `("Z",)`.

    Absolute moves, lines, cubics and closes come out; everything else in the
    two sets is turned into one of those four. Font Awesome's `svgs-full`
    writes nothing else to begin with, and game-icons.net's artists write the
    lot -- relative forms, `H`/`V`, smooth cubics and elliptical arcs -- so the
    parser grew rather than the icons being redrawn into a simpler `d`. The
    art is the artist's; the reading of it is ours.

    Quadratics (`Q`, `T`) are raised rather than guessed at: no icon that ships
    uses one, and a silently mis-drawn glyph is worse than a failing import.
    """
    tokens = _TOKEN.findall(ICONS[name])
    out: list[tuple] = []
    i, op = 0, ""
    x = y = start_x = start_y = 0.0
    control: tuple[float, float] | None = None
    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            op = token
            i += 1
            if op in "Zz":
                out.append(("Z",))
                x, y = start_x, start_y
                control, op = None, ""
                continue
        if not op:
            raise ValueError(f"{name}: coordinates before any command")
        letter = op.upper()
        if letter not in _ARITY:
            raise ValueError(f"{name}: unsupported path command {op!r}")
        count = _ARITY[letter]
        raw = tokens[i:i + count]
        if len(raw) != count or any(t.isalpha() for t in raw):
            raise ValueError(f"{name}: {op} wants {count} numbers")
        if letter == "A" and (raw[3] not in ("0", "1")
                              or raw[4] not in ("0", "1")):
            # `a1 1 0 011.5 2` packs the two flags into one token. No icon
            # here is written that way, and guessing at one would draw the
            # wrong curve silently.
            raise ValueError(f"{name}: arc flags run together: {raw[3:5]}")
        n = [float(t) for t in raw]
        i += count
        dx, dy = (x, y) if op.islower() else (0.0, 0.0)

        if letter == "M":
            x, y = n[0] + dx, n[1] + dy
            out.append(("M", x, y))
            start_x, start_y = x, y
            control, op = None, _AFTER[op]
        elif letter in "LHV":
            if letter == "L":
                x, y = n[0] + dx, n[1] + dy
            elif letter == "H":
                x = n[0] + dx
            else:
                y = n[0] + dy
            out.append(("L", x, y))
            control = None
        elif letter in "CS":
            if letter == "C":
                x1, y1, x2, y2, x3, y3 = (n[0] + dx, n[1] + dy, n[2] + dx,
                                          n[3] + dy, n[4] + dx, n[5] + dy)
            else:
                # A smooth cubic's first control point is the reflection of
                # the last one, or the current point if there was not one.
                x1, y1 = (2 * x - control[0], 2 * y - control[1]) \
                    if control else (x, y)
                x2, y2, x3, y3 = (n[0] + dx, n[1] + dy, n[2] + dx, n[3] + dy)
            out.append(("C", x1, y1, x2, y2, x3, y3))
            control = (x2, y2)
            x, y = x3, y3
        else:
            x3, y3 = n[5] + dx, n[6] + dy
            out.extend(_arc(x, y, n[0], n[1], n[2], int(n[3]), int(n[4]),
                            x3, y3))
            control = None
            x, y = x3, y3
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
