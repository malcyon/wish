# The automapper's roster and notes — plan

**Status: planned, not started.** Four changes to the live panel and the map
notes.

---

## 1. Why some hit point bars are brown

**They are not brown, they are amber, and it means "not at full health".**
`automap/panel.py`:

```
WELL   #2f7d4f   green    at full hit points
HURT   #c07d18   amber    below full, at or above a third
DANGER #c0392b   red      below a third
```

`HURT_BELOW = 1.0`, so **a single point of damage turns the bar amber.** That is
why a party that has taken a scratch looks half-wounded, and why the amber reads
as brown next to the green.

Two things to change, and they are separate decisions:

* **The threshold.** Amber below full is too eager. Two thirds is the usual
  choice and matches what the colour is trying to say.
* **The colour.** `#c07d18` is dark enough to read as brown against the panel.
  Lift it toward a true amber, and check both against the dark theme.

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

| class | candidate |
|---|---|
| fighter | crossed swords |
| magic-user | wand, or a hat |
| cleric | a holy symbol |
| thief | a mask, or a dagger |

Font Awesome Free's set is small and has no wizard hat, so expect to compromise
or draw four small glyphs by hand -- four 16x16 shapes we own outright is not
much work, and sidesteps attribution entirely. **Worth pricing both before
adding a dependency.**

## Verification

* A character at full hit points is green; one point down is amber, not brown;
  below a third is red. Check on both themes.
* A character with nothing readied shows a blank line, not a placeholder.
* Hovering a note shows its whole text, and a very long note does not stretch
  the tooltip off the screen.
* Class icons appear beside the class name, never instead of it.
* If Font Awesome ships, its attribution appears in the README and the About
  box, and the licence files are in the repository.
