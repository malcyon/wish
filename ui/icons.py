"""Small vector icons, as SVG path data. No Qt in here.

**Why paths and not a font.** A write-up since lost,
`work/reports/font-awesome.md`, weighed three ways of getting icons: `qtawesome`, bundling `Font Awesome 7 Free-Solid-900.otf`, and
lifting the path data. The paths win for this program specifically:

* the map draws with `QPainter`, not `QIcon`, so a font's only advantage --
  `qta.icon()` for toolbar buttons -- is the use we have least of;
* a path is drawn into whatever box you give it, where a glyph needs
  `tightBoundingRect` arithmetic because at `setPixelSize(16)` the ink of
  `skull` is 14x18 with a 3px descender and the advance varies per icon;
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
verbatim from `svgs-full/solid/`; the licence text is in
`fontawesome-LICENSE.txt` and the attribution is carried in the
README and the About box. Brands are not used and must not be: the licence
forbids brand-logo use and the set carries `wizards-of-the-coast`.

---

Icons under `GAME_ICONS` are from **game-icons.net**, licensed **CC BY 3.0**,
each verbatim from the artist's own SVG. `ARTISTS` says who drew which, so an
attribution file can be generated from what actually ships rather than retyped.
Donald chose all twenty-one by name; nothing here was picked by an assistant.

**Nine of the ten remaining Font Awesome icons were replaced on `#167`** --
`door-open`, `lock`, `stairs`, `triangle-exclamation`, `location-dot`, `check`,
`trash-can`, `folder-open`, `floppy-disk` and `eye` are gone from
`FONT_AWESOME`, and `exit-door`, `plain-padlock`, `stairs`, `hazard-sign`,
`position-marker`, `check-mark`, `trash-can`, `open-folder`, `save` and
`brass-eye` draw where they used to. `stairs` and `trash-can` are the same
name in both sets; the Font Awesome entry is simply deleted rather than kept
under another key, because nothing else drew it.

**The tenth's replacement finished `#167`'s note icons.** `gem` (the Treasure
note) is gone from `FONT_AWESOME` and `crossed-sabres` and
`open-treasure-chest` draw where `crossed-swords` (a `TEXT_GLYPHS` character,
not a path -- see below) and `gem` used to, for Encounter and Treasure.
`skull`, `arrow-down-long` and `person-running` are also deleted here: nothing
has drawn them since the condition badges replaced them with `death-skull`,
`oppression` and `sparkling-sabre`. That leaves exactly two Font Awesome
names: `user` (the Person note -- `#166` reassigns it, not this issue) and
`hat-wizard` -- parked, unreferenced, until the icon that replaces it is
final (`ui/appicon.py`) and `user` is spoken for, so that Font Awesome's
credit is not removed before every glyph it covers is actually gone.

**`pointy-hat` is the application icon, temporarily** -- Donald's stand-in
for `hat-wizard` while an artist is commissioned, drawn from `ui/appicon.py`.
See `ui/appicon.py`'s own docstring; it is one commit on its own so it can be
reverted without touching anything else here.

Icons under `OURS` are this project's own. Three reasons an icon gets drawn
here rather than lifted: Font Awesome Free has **no sword** -- `sword` and
`swords` are Pro-only, and `khanda` is a Sikh religious emblem, wrong in
meaning and illegible at twelve pixels; `hat-wizard`'s brim is a separate
subpath that stops touching the cone at 13px and reads as a shark's fin; and
`mask` stays perfectly legible while reading as goggles.

`TEXT_GLYPHS` draws a **character** rather than a path, from whatever font the
platform resolves it to. Its one entry was the Encounter note's U+2694 crossed
swords, replaced above by `crossed-sabres`, so the table is empty now.
`ui/iconpaint.py` and `automap/render.py` still know how to draw one -- fitted
to the box by its own ink rather than the 640 box, because it is not path
data -- against the day another glyph needs the same escape hatch.

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
    "user":
        "M320 312C386.3 312 440 258.3 440 192C440 125.7 386.3 72 320 "
        "72C253.7 72 200 125.7 200 192C200 258.3 253.7 312 320 312zM290.3 "
        "368C191.8 368 112 447.8 112 546.3C112 562.7 125.3 576 141.7 "
        "576L498.3 576C514.7 576 528 562.7 528 546.3C528 447.8 448.2 368 "
        "349.7 368L290.3 368z",
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
    # The Exit note. Replaces Font Awesome's `door-open`.
    "exit-door":
        "M217 28.098v455.804l142-42.597V70.697zm159.938 26.88.062 2.327V87h16"
        "V55zM119 55v117.27h18V73h62V55zm258 50v16h16v-16zm0 34v236h16V139z"
        "m-240 58.727V233H41v46h96v35.273L195.273 256zM244 232c6.627 0 12 "
        "10.745 12 24s-5.373 24-12 24-12-10.745-12-24 5.373-24 12-24zM137 "
        "339.73h-18V448h18zM377 393v14h16v-14zm0 32v23h16v-23zM32 471v18h167"
        "v-18zm290.652 0-60 18H480v-18z",
    # The Locked note. Replaces Font Awesome's `lock`.
    "plain-padlock":
        "M256 18.15c-81.1 0-146.6 65.51-146.6 146.45v72.3H159v-69.1c0-53.7 "
        "43.4-97.24 97-97.24 53.5 0 97 44.84 97 97.24v69.1h49.6v-72.3c0-78."
        "94-65.7-146.45-146.6-146.45zM86.9 255.6C72.3 278.4 64 304.7 64 "
        "332.4c0 88.3 85 161.5 192 161.5s192-73.2 192-161.5c0-27.7-8.3-54"
        "-22.9-76.8z",
    # The Stairs note. Replaces Font Awesome's `stairs` -- same name, and
    # the Font Awesome one is deleted above rather than kept under another
    # key, because nothing else drew it.
    "stairs":
        "M64 448v-64h64v-64h64v-64h64v-64h64v-64h64V64h64v384z",
    # The Danger note. Replaces Font Awesome's `triangle-exclamation`.
    "hazard-sign":
        "M254.97 34.75c-30.48-.167-59.02 22.12-79.532 62.156-.075.146-.176."
        "26-.25.406L43.063 326.783l-.22.343C18.5 365.413 13.377 401.515 "
        "28.47 428.03c15.08 26.498 48.627 40.126 93.5 37.908h265.093c44.887 "
        "2.227 78.445-11.404 93.53-37.907 15.09-26.51 9.956-62.595-14.375"
        "-100.874l-.22-.375L335.28 98.064c-.06-.12-.124-.225-.186-.344-20."
        "948-40.263-49.626-62.803-80.125-62.97zm.06 18.844c13.576.13 26.453 "
        "6.93 38.126 18.343 11.606 11.347 22.554 27.453 33.406 48.344.063."
        "122.125.224.188.345l115.22 201.563c.033.053.058.102.092.156l."
        "125.22c12.92 20.274 21.395 38.06 25.282 53.967 3.91 16.01 3.063 "
        "30.648-3.845 42.408-6.908 11.76-19.222 19.533-34.78 23.906-15.444 "
        "4.34-34.508 5.656-57.408 4.5H137.625c-24.845 1.258-44.73-.32-60."
        "405-5.125-15.78-4.84-27.68-13.45-33.72-25.69-6.04-12.237-5.862-26."
        "797-1.5-42.436 4.333-15.535 12.815-32.608 24.875-51.53l.22-.377L"
        "183.562 120c.08-.157.17-.28.25-.438C194.51 98.644 205.32 82.6 216."
        "875 71.376c11.642-11.307 24.58-17.913 38.156-17.78zm47.657 62.093"
        "-28.53 224.032h-41.844L204.438 120.5a293.035 293.035 0 0 0-4.22 "
        "7.97l-.093.218-.125.218-116.938 202.97-.093.187-.126.187C71.28 "
        "350.346 63.598 366.226 60 379.125c-3.598 12.9-3.108 22.322.25 29."
        "125 3.358 6.803 9.925 12.28 22.47 16.125 12.542 3.845 30.67 5.547 "
        "54.405 4.313l.25-.032h234.313l.25.03c21.85 1.138 39.308-.28 51.875"
        "-3.81 12.566-3.533 19.822-8.827 23.687-15.407 3.865-6.58 4.978-15."
        "545 1.813-28.5-3.166-12.958-10.732-29.374-23.094-48.72l-.126-.188"
        "-.125-.218-115.658-202.28-.093-.158-.064-.187c-2.5-4.828-4.99-9."
        "326-7.47-13.532zM231.28 361.875h43.907v43.906H231.28v-43.905z",
    # The Note note, and `type_for`'s fallback for an unknown kind. Replaces
    # Font Awesome's `location-dot`.
    "position-marker":
        "M256 17.108c-75.73 0-137.122 61.392-137.122 137.122.055 23.25 6."
        "022 46.107 11.58 56.262L256 494.892l119.982-274.244h-.063a137.131 "
        "137.131 0 0 0 17.202-66.418C393.122 78.5 331.73 17.108 256 17.108z"
        "m0 68.56a68.56 68.56 0 0 1 68.56 68.562A68.56 68.56 0 0 1 256 222."
        "79a68.56 68.56 0 0 1-68.56-68.56A68.56 68.56 0 0 1 256 85.67z",
    # The Done note. Replaces Font Awesome's `check`.
    "check-mark":
        "M17.47 250.9C88.82 328.1 158 397.6 224.5 485.5c72.3-143.8 146.3-"
        "288.1 268.4-444.37L460 26.06C356.9 135.4 276.8 238.9 207.2 361.9c"
        "-48.4-43.6-126.62-105.3-174.38-137z",
    # The note editor's delete button. Replaces Font Awesome's `trash-can`
    # -- same name, and the Font Awesome one is deleted above rather than
    # kept under another key, because nothing else drew it.
    "trash-can":
        "M199 103v50h-78v30h270v-30h-78v-50H199zm18 18h78v32h-78v-32zm-79."
        "002 80 30.106 286h175.794l30.104-286H137.998zm62.338 13.38.64 8."
        "98 16 224 .643 8.976-17.956 1.283-.64-8.98-16-224-.643-8.976 17."
        "956-1.283zm111.328 0 17.955 1.284-.643 8.977-16 224-.64 8.98-17."
        "956-1.284.643-8.977 16-224 .64-8.98zM247 215h18v242h-18V215z",
    # The editor toolbar's Open button. Replaces Font Awesome's `folder-open`.
    "open-folder":
        "M41 73v304.563L88.697 151H423v-30H185.514l-16-48H41zm62.303 96L43."
        "092 455h381.605l60.211-286H103.303z",
    # The editor toolbar's Save and Save As buttons. Replaces Font Awesome's
    # `floppy-disk`.
    "save":
        "M64 48c-8.726 0-16 7.274-16 16v384c0 8.726 7.274 16 16 16h215v-16"
        "H64V64h63.375v97.53c0 3.924 3.443 7.095 7.72 7.095h169.81c4.277 0 "
        "7.72-3.17 7.72-7.094V64h69.22c.428.318.8.548 1.467 1.094 2.05 1."
        "675 4.962 4.264 8.375 7.406 6.827 6.283 15.65 14.837 24.313 23.5 "
        "8.663 8.663 17.217 17.486 23.5 24.313 3.142 3.413 5.73 6.324 7."
        "406 8.374.546.668.776 1.04 1.094 1.47V330.25l16 16V128c0-2.68-."
        "657-3.402-1.03-4.156a15.312 15.312 0 0 0-1.095-1.844c-.74-1.1-1."
        "575-2.19-2.594-3.438-2.036-2.492-4.768-5.55-8.03-9.093-6.524-7.09"
        "-15.155-16-23.938-24.782-8.782-8.783-17.692-17.414-24.78-23.938-3."
        "545-3.262-6.6-5.994-9.094-8.03-1.247-1.02-2.337-1.855-3.438-2.595"
        "-.55-.37-1.09-.72-1.844-1.094-.754-.373-1.477-1.03-4.156-1.03H64z"
        "m87.72 16h48.56c4.277 0 7.72 4.425 7.72 9.938v70.124c0 5.513-3."
        "443 9.938-7.72 9.938h-48.56c-4.277 0-7.72-4.425-7.72-9.938V73.938"
        "c0-5.512 3.443-9.937 7.72-9.937zM114 212c-4.432 0-8 3.568-8 8v184"
        "c0 4.432 3.568 8 8 8h165v-28h-76.72l15.345-15.375 128-128L352 234"
        ".28l6.375 6.345L406 288.25V220c0-4.432-3.568-8-8-8H114zm238 47.75"
        "L245.75 366H297v128h110V366h51.25L352 259.75zM448 384v64h-23v16h"
        "23c8.726 0 16-7.274 16-16v-64h-16z",
    # The editor toolbar's Preview button. Replaces Font Awesome's `eye`.
    "brass-eye":
        "M255.295 19.137C174.005 18.97 94.94 61.107 51.33 136.643c-64.91 "
        "112.426-26.51 255.934 85.918 320.843 112.427 64.91 255.91 26.41 "
        "320.818-86.015 64.91-112.426 26.474-255.873-85.953-320.783-36.89"
        "-21.298-77.12-31.47-116.818-31.55zm72.264 104.44c23.888.1 47.577 "
        "6.047 69.118 18.476 72.557 41.867 93.585 141.627 46.838 222.55C"
        "396.77 445.52 299.768 477.276 227.21 435.41c-72.556-41.867-93.54"
        "-141.7-46.794-222.62 32.87-56.9 90.563-89.453 147.143-89.214zm69."
        "854 42.398c13.708 22.326 19.042 51.598 15.473 82.795-6.7-12.15-16"
        ".443-22.473-28.955-29.676-40.07-23.07-93.725-5.624-119.54 38.965"
        "-25.818 44.586-14.2 99.74 25.872 122.807 10.52 6.057 21.984 9.31 "
        "33.634 10.014-36.447 22.57-77.037 27.46-108.996 9.016a82.807 82."
        "807 0 0 1-5.738-3.646 121.49 121.49 0 0 0 27.9 22.11c64.273 37.087"
        " 149.69 9.063 191.098-62.618 39.038-67.578 24.853-149.527-30.748"
        "-189.767zm-53.11 62.04c10.274.123 20.466 2.733 29.776 8.092 31."
        "778 18.295 40.878 61.486 20.404 96.846-20.473 35.36-62.59 49.197"
        "-94.37 30.902-27.558-15.865-38.003-50.53-26.94-82.52 4.262 16.973 "
        "19.722 29.677 37.957 29.677 21.485 0 39.085-17.632 39.085-39.11 "
        "0-19.34-14.273-35.523-32.803-38.552 8.006-3.33 16.43-5.157 24.838"
        "-5.327a63.99 63.99 0 0 1 2.055-.007z",
    # The application's own icon, temporarily -- `ui/appicon.py`.
    # `#167`'s stand-in until Donald's artist delivers a logo.
    "pointy-hat":
        "M416.125 42.406c-57.576.457-104.863 25.804-144.813 64.875-41.984 4"
        "1.063-75 97.61-100 155.5.78 4.503 3.06 8.946 7.094 13.658 5.158 6."
        "024 13.183 12.113 23.188 17.593 20.01 10.962 47.79 19.545 75.5 24."
        "47 27.71 4.925 55.505 6.21 75.156 3.438 9.825-1.386 17.538-3.91 21"
        ".813-6.563 4.274-2.653 4.916-3.957 4.812-6.625l.72-.03c-3.408-42.8"
        "28-6-88.797.092-131.94 2.82-19.972 7.668-39.434 15.22-57.624-31.57"
        "3 31.44-62.918 65.425-86.844 94.72 35.418-70.2 86.2-121.398 141.12"
        "5-168.97-11.376-1.71-22.42-2.584-33.063-2.5zM155.21 238.994a406.80"
        "2 406.802 0 0 0-13.334.131c-23.138.575-44.227 2.91-61.876 7.188-23"
        ".532 5.703-40.466 14.888-48.78 26.03-8.317 11.144-10.08 24.667-.97"
        " 45.532 32.86 75.263 117.185 130.26 207.844 148.594 90.66 18.33 18"
        "6.108.147 242.28-66.75 13.59-16.185 15.297-29.312 9.938-43.22-5.35"
        "8-13.908-19.586-28.878-40.78-42.75-14.745-9.65-32.683-18.737-52.75"
        "-27.03 1.506 22.59 3.555 44.877 5.124 65.967v.219c.607 11.402-5.49"
        " 21.585-14.344 27.938-8.853 6.353-20.268 10.08-33.437 12.406-26.33"
        "7 4.654-60.026 3.398-93.344-2.188-33.317-5.585-66.085-15.466-90.28"
        "-29.312-12.097-6.923-22.145-14.85-28.875-24.47-6.73-9.617-9.76-21."
        "554-6.594-33.374l.095-.375.125-.374c7.637-21.206 16.308-42.79 26.0"
        "94-64.094a634.04 634.04 0 0 0-6.133-.068zm6.634 46.662A839.14 839."
        "14 0 0 0 153.031 309c-1.595 6.246-.4 11.407 3.907 17.563 4.374 6.2"
        "5 12.28 12.923 22.844 18.968 21.128 12.09 52.4 21.78 84.095 27.095"
        " 31.694 5.314 64.016 6.28 87 2.22 11.492-2.032 20.53-5.42 25.78-9."
        "19 5.25-3.766 6.864-6.726 6.595-11.78-.517-6.93-1.088-14.027-1.688"
        "-21.25-7.448 4.03-16.47 6.367-26.718 7.813-22.732 3.206-51.79 1.66"
        "5-81.03-3.532-29.242-5.196-58.5-14.055-81.22-26.5-11.36-6.222-21.1"
        "22-13.34-28.375-21.812a58.994 58.994 0 0 1-2.376-2.938z",
    # The Encounter note. Replaces the TEXT_GLYPHS character U+2694.
    "crossed-sabres":
        "M27.084 18.248C-17.903 146.478 143.15 277.92 314.496 381.074c-4.64"
        "5 13.767-5.585 27.628-3.394 40.635 4.44 26.355 20.974 48.997 42.86"
        " 62.425 21.884 13.428 49.776 17.57 75.645 5.765 25.87-11.804 48.69"
        "-38.923 62.737-84.654l-17.865-5.488c-13 42.318-32.806 64.094-52.63"
        " 73.14-19.825 9.047-40.69 5.998-58.116-4.693-17.425-10.69-30.75-29"
        ".095-34.205-49.6-3.455-20.507 2.232-43.318 24.677-65.218 20.743-20"
        ".24 32.068-41.615 30.434-61.24l-18.622 1.552c.74 8.89-4.35 22.76-1"
        "6.684 37.486C222.057 230.8 73.838 128.622 27.084 18.248zm458.05 0C"
        "451.34 98.03 364.527 173.53 270.93 247.166c19.492 15.878 39.56 31."
        "622 59.195 45.012 110.756-84.836 187.878-180.243 155.01-273.93zM12"
        "7.58 292.146c-1.634 19.626 9.69 41 30.434 61.24 22.445 21.9 28.132"
        " 44.712 24.677 65.218-3.455 20.506-16.78 38.91-34.206 49.6-17.425 "
        "10.692-38.29 13.74-58.115 4.694-19.825-9.046-39.632-30.822-52.63-7"
        "3.14l-17.865 5.488c14.046 45.73 36.867 72.85 62.736 84.654 25.87 1"
        "1.805 53.763 7.663 75.648-5.765 21.885-13.428 38.42-36.07 42.86-62"
        ".426 2.19-13.005 1.25-26.863-3.393-40.628 13.986-8.42 27.905-17.02"
        "2 41.648-25.803l-56.967-39.387c-6.55 5.103-13.063 10.2-19.52 15.29"
        "3C150.55 316.46 145.46 302.59 146.2 293.7l-18.622-1.554zm18.1 73.6"
        "14c-26.1 8.6-62.087 36.255-77.104 60.324 4.948 8.63 10.393 15.223 "
        "16.05 20.14 25.846-8.953 59.85-37.406 74.733-60.257-3.007-6.6-7.45"
        "4-13.386-13.68-20.207zm220.863 0c-6.225 6.822-10.67 13.61-13.68 20"
        ".21 14.886 22.85 48.89 51.3 74.736 60.255 5.656-4.918 11.1-11.51 1"
        "6.05-20.14-15.018-24.07-51.004-51.724-77.105-60.325z",
    # The Treasure note. Replaces Font Awesome's `gem`.
    "open-treasure-chest":
        "M410.365 101.005c8.21-22.26 16.21-31.12 20.33-34.45 3.06-2.48 5.73"
        "-3.42 7.92-2.81 4 1.13 8.49 7.45 11.88 16.89 10.89 30.34 10 84.28-"
        ".93 129.51zm-286 72.92c7.52-31 10.28-66.13 7.77-94.92l-43.6-4.86zm"
        "289.46-113-301.2-33.53c-2.5-.28-5.24 1.46-7.11 3-3.67 3-10.42 10.3"
        "2-17.66 27.64l308.68 34.34c5.16-13.25 11.02-23.89 17.31-31.43zm-22"
        "8.78 298.71v-70.72l10.76 1.19 42.24 5.18v70.51zm16-40.34a13 13 0 0"
        " 0 5.34 10.29l-2.34 24.42 17 1.74-4-25a9.54 9.54 0 0 0 5-9.15 13.6"
        "4 13.64 0 0 0-11.06-12.59s.17.1.13.1c-5.95-.68-11.07 3.9-10.07 10."
        "1zm53 64.45-85-9.84v-86.72l-1.05-.09a8.14 8.14 0 0 1-7.27 6.71 8 8"
        " 0 0 1 5.23 8.9 8 8 0 0 1-8 6.66c8.453 4.004 4.341 16.778-4.86 15."
        "1a8 8 0 0 1-8 13.8 8.01 8.01 0 0 1-12.28 10.29v.09a8 8 0 0 1-3.86 "
        "8.37l9.13 5.35v14.25l-12 7.13-12-7.12v-14.26l8.15-4.82a8.21 8.21 0"
        " 0 1-5.07-5.92.418.418 0 0 1 0-.1 8 8 0 0 1-15.18-5c-6.851 7.214-1"
        "8.094-2.065-12.31-10.16-8.346 4.519-16.217-6.676-9.14-13-9.17 2.66"
        "1-14.453-10.083-6.09-14.69a8 8 0 0 1-3.21-15.67c-9.294-1.047-9.548"
        "-14.463-.3-15.86-.669-.164-1.264-.473-1.83-.76l-17.24-1.86.6 167.1"
        "1 309.18 34.49-.6-165.83-107-13.05zm140.06-164 4.72 1.91.91.58 38."
        "72 4.31-23.26-64.77-12.82 37c-.16.46-3.41 9.8-8.27 20.99zm-208.54-"
        "39.74 5 5.49 12.75-11.15 21.45-2.28 16.61 15.35 10.51 8.73 18.54-9"
        ".29 3.44.5c.12-.67.25-1.34.38-2 3.08-16.1 7.35-30.16 7.53-30.75l13"
        ".39-43.91 16.88 42.71 8.42 21.42 10.66-12.39 22.14-25.73 5.78 33.4"
        "5 3.29 19.1 17.1-9.64 35.09-19.79-18.48-51.4-247.86-27.61c2.51 34."
        "94-1.85 77.32-12.39 112h2.32l7-12.86h40.46zm-111.29 97.39c7.6 2.1 "
        "7.9 12.766.43 15.29 7.737.867 9.802 11.153 3 14.94 7.653-.548 11.6"
        "14 8.947 5.84 14 7.313-2.115 13.168 6.216 8.7 12.38 6.288-3.518 13"
        ".657 2.417 11.56 9.31 4.53-4.723 12.506-2.304 13.65 4.14 2.057-5.7"
        "13 9.48-7.141 13.51-2.6-1.285-6.404 5.23-11.566 11.17-8.85-4.564-5"
        ".77.425-14.123 7.67-12.84-6.419-4.541-3.122-14.648 4.74-14.53-7.31"
        "6-3.503-5.375-14.415 2.7-15.18a8 8 0 0 1-5.38-8l-76.43-8.26c-.41.1"
        "9-.746.15-1.16.2zm367.54 139.08-.59-163.86-8.67 7-55.51 46.79.58 1"
        "62zm-26.23-165.2-24.11-15.27-4.18-1.69c-5.91 11.52-13.39 23-22.66 "
        "27.88-5.44 2.88-12.22 4.34-20.16 4.34-11.13 0-24.75-2.91-37.35-8-1"
        "0-4-23.3-11-30.26-21.34-4.9-7.29-6.64-17.77-5.31-32.92l-21.78 10.9"
        "3-19-15.8-11.42-10.53-9.16 1-20.45 17.83-11-11.7h-24.21l-17.61 32-"
        "5.7-7.2-4.42 4.85-10.76 16.35-12.29 4.91L97.611 256h-12.2l-2.776 6"
        ".005 76.9 8.21a8.15 8.15 0 0 1 2-2.9 8 8 0 0 1 10.31-.46 1.657 1.6"
        "57 0 0 1-.14-.24c-4.955-8.368 6.459-16.62 12.87-9.375 6.412 7.245-"
        "3.167 17.571-10.87 11.635a8 8 0 0 1 1.12 2.89l22.62 2.44 168.54 20"
        ".57 51.49-43.38zm-28.34-57.73-36.88 20.79-7.14-41.47-28 32.51-18.1"
        "3-46.11s-16.65 54.58-7 69c7.69 11.45 35.42 22.25 54.33 22.25 5 0 9"
        ".43-.76 12.67-2.48 13.8-7.31 30.15-54.49 30.15-54.49zm-317.08 270."
        "8v-.2c0-3.77-8.21-6.83-18.33-6.83-10.12 0-18.33 3.06-18.33 6.83 0 "
        "3.21 6 5.9 14 6.63v.2c0 3.77 8.21 6.83 18.33 6.83 10.12 0 18.33-3."
        "06 18.33-6.83-.01-3.21-5.98-5.9-14-6.63zm350 6.63c-10.13 0-18.33 3"
        ".06-18.33 6.83s8.21 6.83 18.33 6.83c10.12 0 18.33-3.06 18.33-6.83s"
        "-8.25-6.8-18.38-6.8zm40-16.28c-10.13 0-18.33 3.06-18.33 6.83s8.21 "
        "6.83 18.33 6.83c10.12 0 18.33-3.06 18.33-6.83s-8.22-6.83-18.34-6.8"
        "3z",
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
    "exit-door": "Delapouite",
    "plain-padlock": "Delapouite",
    "stairs": "Delapouite",
    "hazard-sign": "Lorc",
    "position-marker": "Delapouite",
    "check-mark": "Delapouite",
    "trash-can": "Delapouite",
    "open-folder": "Delapouite",
    "save": "Delapouite",
    "brass-eye": "Lorc",
    "crossed-sabres": "Lorc",
    "open-treasure-chest": "Skoll",
    "pointy-hat": "Lorc",
}


OURS: dict[str, str] = {}

ICONS: dict[str, str] = {**FONT_AWESOME, **GAME_ICONS, **OURS}

#: Icons that are a **character**, not a path. `ui/iconpaint.py` draws these
#: with the system font and fits them to the same box the paths are drawn in.
#:
#: Empty now. Its one entry, the Encounter note's U+2694, was replaced by
#: `crossed-sabres` -- a path, so it is drawn by the same hand as every other
#: note. Left in place, empty, in case a future glyph needs the same escape
#: hatch a font character offers.
TEXT_GLYPHS: dict[str, str] = {}

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
