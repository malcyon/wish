# The automapper's roster and notes

**Status: built.** The bar colours, the readied items, the note tooltip, the
icons, and the two status icons the record can actually justify.
`automap/panel.py` is the roster, `automap/icons.py` the icons, and
`docs/98-automap-notes.md` covers the notes.

---

## 1. Hit point bar colours

| remaining | colour | |
|---|---|---|
| above 75% | `#2f7d4f` | green |
| above 25%, at or below 75% | `#e6c229` | yellow |
| 25% or below | `#c0392b` | red |

Both boundaries fall to the worse state, and `hp_colour` uses `<=` for that
reason; `test_the_hit_point_bands_keep_their_boundaries` pins it.

Before this, `HURT_BELOW = 1.0` meant a single point of damage turned the bar
off green, so a scratched party looked half-dead, and the old `#c07d18` was dark
enough (relative luminance 0.26) to read as brown next to the green. The new
yellow sits at 0.56 and carries 9.5:1 against the black numbers drawn across it.

**Themes.** The card is `#ffffff` and the bar's empty track `#fbfcfd`, both
literal, so a bar is on a light ground whichever theme the system is in.

**Colour blindness.** Green and red are the pair that fails, not the yellow:
simulated deuteranopia puts them 1.12:1 apart, while the yellow stands 3.1:1
from the green and 2.8:1 from the red. Nothing was added to separate green from
red, because **the fill length already does it** — under these thresholds a red
bar is at most a quarter full and a green one more than three quarters — and the
numbers are written across the bar besides.

Three states, not a gradient. A gradient looks better and tells you less at a
glance.

## 2. Readied items, under the bars

Each card carries one line of what that character has **in hand**, decoded by
`por/items.py` from the item block the poll already reads —
`live.readied(payload, slot, names)`.

* **Readied only.** The whole inventory would swamp the card; what matters
  mid-crawl is what is in hand.
* One line, comma separated, elided to the card's 248px, with the full list in
  the tooltip.
* A character with nothing readied gets a **blank line, not the word "none"** —
  the absence is the information — and the line stays, so the cards below do not
  shift when a sword is put away.
* An unidentified item shows the shorter name the game shows.
* Item names come from a game disk's `ITEMNAMES`, read once and cached. With no
  disk the line is blank rather than a row of word indices.

## 3. Notes show their text on hover

`MapCanvas.tooltip_at` answers with every note on the square under the pointer,
one per line, in the pattern the combat view's `tooltip_at` set. See
`docs/98-automap-notes.md`.

## 4. The icons

**Path data, not a font.** `automap/icons.py` holds each icon's SVG path in a
uniform 640×640 box; `automap/iconpaint.py` fills it into a `QPainterPath` at
whatever size the caller wants. The weighing against `qtawesome` and against
bundling the 405 KB Solid `.otf` is in `docs/98-automap-notes.md`; the short of
it is that the map draws with `QPainter`, the SVG export gets the icons free,
and nothing ships that the release build has to be told about.

**Class icons stand beside the class text and never instead of it** — the text
is what a screen reader gets, and what somebody who does not recognise a domino
mask gets. Multi-class shows one icon per class, in the card's own class order.

| class | icon | source |
|---|---|---|
| magic-user | `hat-wizard` U+F6E8 | Font Awesome Free |
| cleric | `cross` U+F654 | Font Awesome Free |
| thief | `mask` U+F6FA | Font Awesome Free |
| fighter | a sword | **ours** |

**Font Awesome Free has no sword.** `sword` and `swords` are Pro only, and
`khanda` is a Sikh religious emblem — wrong in meaning and illegible at twelve
pixels. So the fighter's blade, the crossed swords of the Encounter note and the
treasure chest are drawn here, from straight lines in the same 640 box, thick
enough not to read as a scratch beside 3px walls.

**Do not rely on system fonts** for any of this. Measured on this machine,
crossed swords and a cross come from DejaVu Sans, a shield and a dagger only
from Noto Sans Symbols2, and a scroll or a pin only from a colour emoji font.
Windows ships a different set again, so the same code would draw a different map
on every machine.

## 5. Status icons — two, and only two

The card marks the conditions the **record actually tells us**, beside the name
and in the danger red:

| condition | where it comes from | icon |
|---|---|---|
| at 0 hit points | the roster block's current hit points | `skull` |
| levels drained | `levels_drained`, record `0x0A1`, CONFIRMED | `arrow-down-long` |

The tooltip says what each means, and the skull's says the thing the record does
not: 0 is dead **or** dying and nothing decoded distinguishes them. That is the
same reason `automap/actions.py` refuses to heal a character at 0.

**Poisoned and paralysed are still blocked, and `por/traits.py` does not unblock
them.** That module names the **trait** codes in the ten slots at record `0x0AD`
— racial abilities and monster specials — and its own docstring warns that item
byte `+14` shares those slots without sharing their meaning. The effect table
the live view reads is a different structure: four parallel 64-slot arrays at
`$4900`, whose id byte is written by whatever applied the effect. Nothing in the
project maps one code space onto the other, and **no save we hold carries a
single active effect**, so there is nothing to check a mapping against. Naming
`effect 64` "poison" because trait 64 is poison would be inventing the table.

So the effects keep their numbers, and the way to unblock this is to capture a
save with a poisoned character in it and read the id — not to borrow a name from
a table that answers a different question.

## The licence, and its two traps

Confirmed against the package's own `LICENSE.txt`, which is committed at
`docs/licences/fontawesome-LICENSE.txt`. Font Awesome Free is triple-licensed —
icons **CC BY 4.0**, fonts **SIL OFL 1.1**, code **MIT** — and all three are
compatible with GPL-3.0. The obligation we carry is attribution: a line in the
README and a line in the About box, both naming the work, the author and the
licence.

* **Brands must not ship.** The licence forbids using the brand logos except to
  represent the company in question, and the set includes
  `wizards-of-the-coast`. None is used.
* **Subsetting the font would make an OFL "Modified Version"** which may not
  keep the reserved name "Font Awesome". Moot: no font ships.

## Verification — in `tests/test_automap.py`

* A character with nothing readied shows a blank line, not a placeholder, and
  the card does not change height.
* A long readied list is elided to the card's width and kept whole in the
  tooltip.
* `live.readied` returns the readied items and not the rest — checked against
  the player's own equipped party, and empty with no disk.
* Class icons appear beside the class name, never instead of it.
* The fighter's icon is one of ours, not a Font Awesome name.
* The attribution is in the README and the About box, and the licence file is in
  the repository.
* A character at 0 hit points shows the skull and a drained one the arrow;
  a whole character shows neither.
* An effect is still labelled by its number, and the trait table is not
  borrowed to name it.
