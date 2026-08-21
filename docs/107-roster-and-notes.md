# The automapper's roster and notes — plan

**Status: 1 is done; 2 to 4 are planned.** Four changes to the live panel and
the map notes.

---

## 1. Hit point bar colours

**Done.** `automap/panel.py`:

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
literal, so a bar is on a light ground whichever theme the system is in. The
cards are light islands in a window that follows the theme; only the fill colour
had to be chosen, and it needed no dark variant.

**Colour blindness.** Green and red are the pair that fails, not the yellow:
simulated deuteranopia puts them 1.12:1 apart, which is nothing, while the
yellow stands 3.1:1 from the green and 2.8:1 from the red. Nothing was added to
separate green from red, because **the fill length already does it** -- under
these thresholds the colour is a function of how full the bar is, so a red bar
is at most a quarter full and a green one more than three quarters -- and the
numbers are written across the bar besides. A stripe or an icon would be a
fourth encoding of the same fact.

Worth keeping: three states, not a gradient. A gradient looks better and tells
you less at a glance, which is the wrong trade in a panel you glance at.

## 2. Readied items under the experience bar

Show each character's **readied** items on their roster card, under the bars.

Everything needed is decoded: `por/items.py` reads the sixteen item slots and
the readied bit, and the editor's inventory table already shows exactly this.
Item names come from the game disk, so a card without a game disk should show
nothing rather than numbers.

Design notes:

* **Readied only.** The whole inventory would swamp the card; what matters
  mid-crawl is what is in hand.
* One line, comma separated, elided at the card's width, with the full list in
  the tooltip.
* A character with nothing readied gets a blank line, not the word "none" --
  the absence is the information.

## 3. Notes should show their text on hover

A note currently draws a marker and nothing else, so finding what one says
means opening it. **Hovering the marker should show the note's text in a
tooltip.** The map already tracks notes per square, so this is a tooltip on the
canvas, keyed by the square under the pointer -- the combat view's
`tooltip_at` does the same job and is the pattern to follow.

## 4. A better marker than an asterisk, and class icons

**Font Awesome Free is usable.** It is triple-licensed: the icons **CC BY 4.0**,
the fonts **SIL OFL 1.1**, the code **MIT**. All three are compatible with this
project's GPL-3.0, and the only obligation is attribution for the icons -- a
line in the README and in the About box.

`qtawesome` (MIT) packages Font Awesome for Qt and is the least effort. Bundling
the `.otf` and loading it with `QFontDatabase.addApplicationFont` is the other
way, and keeps the dependency list shorter.

**Do not rely on system fonts.** Measured on this machine:

| glyph | comes from |
|---|---|
| crossed swords, cross, hammer, star | DejaVu Sans -- everywhere |
| shield, dagger, note page | Noto Sans Symbols2 only |
| scroll, bow, pin, book, gem | a colour emoji font only |

Windows ships a different set again, so the same code would draw a different
map on every machine, and some glyphs would be colour emoji in a line-art map.
Shipping the font is what makes it predictable.

**For notes**, a pin or a note-page glyph, in the map's own ink so it reads as
part of the drawing rather than as an emoji dropped on top.

**For the roster**, an icon beside each class, **in addition to the text label**
and never instead of it -- the text is what a screen reader gets, and what
someone who does not recognise the icon gets. Multi-class characters show one
icon per class.

| class | icon | code point |
|---|---|---|
| magic-user | `hat-wizard` | U+F6E8 |
| cleric | `cross`, or `hands-praying` | U+F654 |
| thief | `mask` | U+F6FA |
| fighter | **nothing suitable** | — |

**Font Awesome Free has no sword.** `sword` and `swords` are Pro only, and
`khanda` is a Sikh religious emblem — wrong in meaning and illegible at 12
pixels. So the fighter's icon, and the "encounter" note type in
`docs/98-automap-notes.md`, have to be drawn by us. Free *does* carry a
tabletop set added in 5.4.0 — `hat-wizard`, `dragon`, `dungeon`, `scroll`,
`dice-d20`, `ring`, `ghost` — so the earlier note here that it "has no wizard
hat" was wrong.

Reckon on **four to six small glyphs of our own**: crossed swords, a chest,
poison, paralysis, a note dog-ear. `automap/render.py`'s existing `Line`,
`Poly` and `Rect` primitives already express that kind of shape, and anything
we draw ourselves carries no attribution and no licence question.

## Two licence traps

Confirmed against the package's own `LICENSE.txt`, not from memory:

* **Brands must not ship.** The licence forbids using the brand logos except to
  represent the company in question, and the set includes
  `wizards-of-the-coast`. Bundle Solid only.
* **Subsetting the font makes an OFL "Modified Version"**, which may not keep
  the reserved name "Font Awesome". If we subset to save space, it has to be
  renamed.

Otherwise there is no conflict with GPL-3.0. Ship `LICENSE.txt` beside the
font, and carry an attribution line in the README and the About box.

## Verification

* A character with nothing readied shows a blank line, not a placeholder.
* Hovering a note shows its whole text, and a very long note does not stretch
  the tooltip off the screen.
* Class icons appear beside the class name, never instead of it.
* If Font Awesome ships, its attribution appears in the README and the About
  box, and the licence files are in the repository.
