# The automapper's roster and notes

**Status: built.** The bar colours, the readied items, the note tooltip, the
icons, the two status icons the record can actually justify, and the quickfight
badge. `automap/panel.py` is the roster, `ui/icons.py` the icons, and
`docs/98-automap-notes.md` covers the notes.

---

## The order the cards are in

**Fixed, `#160`.** The card at the top is now the character the game lists
first. `automap/live.py`'s `characters()` and `editor/roster.py`'s
`_load_save` both walked `SaveGame0.characters`, ascending slot order, while
the C64 lists the party from the **highest** occupied slot down. Measured in
the running game: `read_snapshot` answered `GARRETT, GRIMNIR, ASTRID` while
the C64 screen beside it read `ASTRID, GRIMNIR, GARRETT`.

Both now walk `SaveGame0.marching_order`, the occupied slots in descending
index order -- not simply `reversed(range(8))`, because `ALTER ▸ DROP` leaves
a hole where the dropped character stood and that form would count it.
`Character.slot` and `Member.index` still carry the real slot, so nothing
downstream that writes by slot needed to change. See
[`30-savegame-layout.md`](30-savegame-layout.md), "The slot array runs backwards
from the marching order", for how the rule was established.

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
`goldbox/items.py` from the item block the poll already reads —
`live.readied(payload, slot, names)`.

* **Readied only.** The whole inventory would swamp the card; what matters
  mid-crawl is what is in hand.
* One line, comma separated, shortened with an ellipsis to whatever width the
  card leaves it, with the full list in the tooltip. The label sets no tooltip
  of its own, so it answers with the card's, which already carries
  `Readied: ...`.
* **It shares the row with the badges and it is the half that gives way.** The
  condition badges and the quickfight badge sit at the right-hand end of this
  same line, drawn at a fixed width, and `ReadiedLabel.SQUEEZED` is 0 so the
  words take whatever is left -- however little. Donald settled the order:
  *"I would rather see active effects than readied items. That is a fine
  trade-off as far as space goes."* (`#161 (A roster card loses a character's
  classes and its Level up button once four condition badges are lit)`.) With
  every badge lit and a full hand the line draws about a word; with nothing
  running it draws the lot.
* **The line never adds to the window's floor.** `panel.ReadiedLabel.SHORT` is
  0, which makes it the first row on a card to give way: eight cards in a
  column that does not scroll, each insisting on a line of height, is eight
  lines added to a page that still has to fit a 720-high screen (#97, #100).
  Anywhere above that floor it is drawn in full. Its point size is set in
  `wish/window.ui` rather than inherited, so it does not get taller as the UI
  font grows either.
* A character with nothing readied gets a **blank line, not the word "none"** —
  the absence is the information — and the line stays, so the cards below do not
  shift when a sword is put away.
* An unidentified item shows the shorter name the game shows.
* Item names come from a game disk's `ITEMNAMES`, read once and cached. With no
  disk the line is blank rather than a row of word indices.

## 3. The top row: the name, the classes and level, and the Level up button

**Three things, and the name is the only one that gives way.** The roster
column is capped at 220px and the scrollbar takes 14 of them, so a card draws
in 206. The row used to hold six things -- the name, the condition badges, the
classes, the level, the quickfight badge and the button -- and asked for 277px
with nothing running and 357 with five spells up. Whatever was rightmost fell
off, cut rather than shortened and with nothing on the card to say so: a
three-class character with four badges lit read `MU/C`, and a character who had
earned a level got `Lev`, 32 of the button's 80 pixels
(`#161 (A roster card loses a character's classes and its Level up button once
four condition badges are lit)`,
`#168 (A character ready to level loses the Level up button, even with nothing
running)`).

Both badge rows moved to the readied line and the name became a
`panel.CardNameLabel`, whose `SQUEEZED` is 0: it yields the whole of its width
before the classes or the button lose a pixel. Donald's reasoning is what makes
that the cheap side of the trade -- *"The level up button will never be there
for very long. It will be clicked as soon as it appears. So, cutting off the
name for a little while is fine."* A name is also the one thing on the row
still recognisable from its first few letters; `MU/C` for `MU/C/T  L8` is not.

The floor is 0 rather than a number measured here on purpose. The classes label
and the button are both set in points in `wish/window.ui`, so how many pixels
they take is the machine's business, and any floor generous enough on this desk
is a floor that cuts the button where the font is wider. **There is no spacer
on the row either**: a `QSpacerItem` shrinks in proportion to its own size hint
when the row is short, so it kept 40px of the width the name was giving up, and
`BOB` beside a Level up button drew as `B...`.

**The 32px stub was clickable**, measured before the fix: `visibleRegion()` on
the button answered `QRect(0, 0, 32, 18)`, and `childAt` hands every one of
those pixels to the button, which is the same recursion the mouse dispatcher
uses. So the fault was ugly rather than disabling -- nothing was unreachable,
and nothing on the card said it was a button.

## 4. Notes show their text on hover

`MapCanvas.tooltip_at` answers with every note on the square under the pointer,
one per line, in the pattern the combat view's `tooltip_at` set. See
`docs/98-automap-notes.md`.

## 5. The icons

**Path data, not a font.** `ui/icons.py` holds each icon's SVG path in a
uniform 640×640 box; `ui/iconpaint.py` fills it into a `QPainterPath` at
whatever size the caller wants. The weighing against `qtawesome` and against
bundling the 405 KB Solid `.otf` is in `docs/98-automap-notes.md`; the short of
it is that the map draws with `QPainter`, the SVG export gets the icons free,
and nothing ships that the release build has to be told about.

**There are no class icons.** There were — a hat, a cross, a hood and a sword
beside the class text — and they are gone: four 13-pixel glyphs nobody could
tell apart at that size, saying nothing the words "fighter/thief" beside them
did not. The drawings and the reasoning survive in
`docs/109-icon-choices.md`; the card shows the class as text and only as text.

**Do not rely on system fonts** for any of this. Measured on this machine,
crossed swords and a cross come from DejaVu Sans, a shield and a dagger only
from Noto Sans Symbols2, and a scroll or a pin only from a colour emoji font.
Windows ships a different set again, so the same code would draw a different map
on every machine.

**One glyph now does exactly that, deliberately.** The Encounter note is
**U+2694**, Donald's choice, and it accepts the cost this paragraph describes:
it is the platform's drawing, not ours. It replaced a pair of crossed blades we
drew that read as a starburst at every size. It is the only one, and
`docs/109-icon-choices.md` records what it renders as here and what is not known
about the other platforms.

## 6. Status icons — two, and only two

The card marks the conditions the **record actually tells us**, at the
right-hand end of the readied line and in the danger red:

| condition | where it comes from | icon |
|---|---|---|
| at 0 hit points | the roster block's current hit points | `skull` |
| levels drained | `levels_drained`, record `0x0A1`, CONFIRMED | `arrow-down-long` |

The tooltip says what each means, and the skull's says the thing the record does
not: 0 is dead **or** dying and nothing decoded distinguishes them. That is the
same reason `automap/actions.py` refuses to heal a character at 0.

## 7. The quickfight badge

Roster block `+0x0C`, bit 7, CONFIRMED — the bit the combat menu's QUICK sets,
which `automap/actions.py` also clears. `live.Character.quickfight` reads it
off the roster page the poll already has, so the panel never reads memory of its
own, and `actions.QUICKFIGHT` is built from `live.ROSTER_QUICKFIGHT` and
`live.QUICKFIGHT_BIT` so the badge and the write cannot come to disagree.

| | |
|---|---|
| glyph | `sparkling-sabre`, game-icons.net, Lorc |
| tooltip | `Quickfight` |
| where | the right-hand end of the **readied line**, after the condition badges |

**Its own `IconRow`, not the conditions one**, and the reason is what the two
mean. The conditions are drawn in the danger red and are things that have
happened *to* a character; quickfight is a setting that character's player made
from the combat menu, and it keeps its own widget and its own colour. Both rows
sit on the readied line because that is where Donald put them --
*"Are you suggesting putting the icons on the right side of the row that
contains readied items? I think that could work"*, and *"I think the quick
fight icon should go where the active effects go."*

**An `IconRow` is at most 13px tall and asks for none of it.** Height is a
maximum with a `minimumSizeHint` of 0, not a fixed size: eight cards, each with
two badge rows insisting on 13px, would hand back the floor
`#135 (The automapper's roster column does not scroll, so a full party puts a
944px floor under the window)` took off the window. Width is fixed, which is
what makes the badges the half of the readied line that does not give way.

## 8. The status effects we could badge, and what with

**The old objection is retired.** This section used to say a poisoned or
paralysed icon "would be an invented mapping", on the reading that the effect
ids at `$4900` and the trait codes at `0x0AD` were two code spaces. They are
one: `LIBRARY $4028` reads the arrays first and falls back to the character's
own slots, which is why one table names both
([active effects](133-active-effects.md)). `P3-EFFECTS.D64` — twenty-six spells
running — promoted seventeen codes, and 66 of `goldbox/traits.py`'s 129 names are
CONFIRMED today.

So the name is no longer the blocker. **The glyph is**, and this is the menu.
Nothing below is implemented: Donald is choosing.

**Restricted to what can be true of a player character.** Ids 64 and up are
monster attack forms — poison bites, gazes, breath weapons — and belong on a
monster's tooltip, not a roster card. The four exceptions are the passive item
powers a character can carry, and 89 is one of them.

Every glyph below was rendered at 13px through `ui/iconpaint.py` and judged on
the magnified image, the way `docs/109-icon-choices.md` says. "None" is a real
answer and there are six of them.

### The fifteen Donald named

| code | name | confidence | candidate | at 13px |
|---|---|---|---|---|
| 1 | Bless | CONFIRMED | `person-rays` | a figure with rays off it; 35px of ink, reads |
| 5 | Detect Magic | CONFIRMED | `wand-magic` | one clean diagonal wand. `wand-magic-sparkles` is five pieces and mush |
| 8 | Protection from Evil | CONFIRMED | `user-shield` | a figure carrying a shield; tells apart from plain `shield` at 13 |
| 10 | Resist Cold | CONFIRMED | `snowflake` | thin arms, 57px, unmistakable |
| 12 | Enlarge | CONFIRMED | `maximize` | four arrows outward, one connected mass |
| 17 | Shield | CONFIRMED | `shield` | 71px of solid ink — the most legible glyph tested |
| 19 | Find Traps | CONFIRMED | `magnifying-glass` | clean ring and handle |
| 20 | Resist Fire | CONFIRMED | `fire-flame-simple` | one flame. Plain `fire` has an inner counter that half-closes at 13 |
| 25 | invisible | CONFIRMED | `ghost` | one silhouette. `eye-slash` is the literal reading and at 13 the eye is gone — what survives is the slash |
| 28 | Mirror Image | CONFIRMED | `clone` | two offset frames |
| 35 | under an allied Prayer | CONFIRMED | `person-praying` | one silhouette, 38px |
| 37 | blinking | CONFIRMED | **none** | nothing in FA Free says "flickers out and back". `shuffle` breaks into 22/11/5 and reads as "randomise" |
| 38 | extra strength | CONFIRMED | `dumbbell` | clear |
| 39 | hasted | CONFIRMED | `forward-fast` | the double chevron; clearest of the lot after `shield` |
| 89 | displaced | CONFIRMED | **none** | `copy` is the same drawing as `clone`; on one card nobody would tell it from Mirror Image |

89 is above 64 and belongs here anyway: it is one of the four passive item
powers, carried by the player's own CLOAK OF DISPLACEMENT.

### The rest of the CONFIRMED ones a character can carry

| code | name | candidate | at 13px |
|---|---|---|---|
| 3 | wielding an undead-slaying weapon | — | the weapon's, not the character's; the readied line already says it |
| 9 | Protection from Good | **none** | nothing distinguishes it from Protection from Evil |
| 14 | Friends | **none** | a charisma bonus has no picture |
| 16 | Read Magic | `book-open` | clear at 13 — but it ends when the scroll is read |
| 24 | sees invisible creatures | `eye` | clear, and already the toolbar's preview icon; reuse across two surfaces is the only cost |
| 41 | Protection from Normal Missiles | **none** | FA Free has no arrow-on-shield |
| 61 | wearing a Ring of Fire Resistance | `ring` | clear, but it says what Resist Fire says |
| 107, 124 | elf / half-elf resistance to sleep and charm | — | true of every elf that ever existed; a badge on all of them says nothing |

### PROBABLE, and the ones a player would actually want

Every one of these is the guide's name with no C64 carrier. A badge here is a
name we have not proved, which is a decision and not a detail.

| code | name | candidate | at 13px |
|---|---|---|---|
| 11 | charmed | `heart` | clear |
| 13 | Reduce | `minimize` | four corner brackets, 16px each — thin, and the weakest of the size pair |
| 27 | feather falling | `feather-pointed` | clear |
| 31 | helpless | `person-falling` | readable |
| 33 | blind | `eye-slash` | marginal, and it is what invisible would otherwise want |
| 34 | diseased | `virus` | clear |
| 42 | slowed | `hourglass-half` | clear |
| 52 | held or paralysed | `handcuffs` | 53px, clear. `hands-bound` also works |
| 53 | sleeping | `bed` | clear; `moon` is equally clear and less literal |
| 55 | poisoned | **none good** | `skull-crossbones` collides with the dead skull, and `droplet` and `vial` read as water and a potion |
| 2, 36 | Curse, Bestow Curse | **none** | |
| 29 | Ray of Enfeeblement | **none** | |

## The licence, and its two traps

**Historical: Wish drew no Font Awesome icon after 2026-09-01.** `#167` replaced
the last of them and `fontawesome-LICENSE.txt` came out with it; `git log --
fontawesome-LICENSE.txt` has the file. The section is kept because the traps
below are about attribution generally and cost this project real time. Every
icon is now game-icons.net under **CC BY 3.0**, credited from
`ui.icons.ARTISTS` into `THIRD_PARTY_LICENSES.md`.

Confirmed at the time against the package's own `LICENSE.txt`. Font Awesome
Free is triple-licensed —
icons **CC BY 4.0**, fonts **SIL OFL 1.1**, code **MIT** — and all three are
compatible with GPL-3.0. The obligation we carry is attribution: a line in the
README and a line in the About box, both naming the work, the author and the
licence.

* **Brands must not ship.** The licence forbids using the brand logos except to
  represent the company in question, and the set includes
  `wizards-of-the-coast`. None is used.
* **Subsetting the font would make an OFL "Modified Version"** which may not
  keep the reserved name "Font Awesome". Moot: no font ships.

## Verification — in `tests/test_panel.py`

What the card can hold in the width it is given, all of it against a real
window laid out at the real 220px column, and none of it against a pixel count
measured on one machine:

* A three-class character with every badge lit, quickfight on and a full hand
  keeps her classes, her level, both badge rows and the Level up button -- each
  asserted whole through `QWidget.visibleRegion()`, which is the clip the
  column's edge actually applies.
* The same, at +0, +3, +6 and +10 point of UI font.
* A character ready to level with nothing running gets the **whole** button.
* The name is what gives way: the button appearing costs the name label at
  least the button's own width and costs the classes nothing. Both numbers are
  measured in the same run.
* A three-letter name beside a Level up button is not shortened.
* The badges are drawn whole and the readied line shortens, with the full list
  still in the card's tooltip.
* The badge rows cost the card's floor no height -- the control is the same
  card with them hidden.
* `gamedata.synthetic_party` contains characters who **can** level, which is
  what stops `#168 (A character ready to level loses the Level up button, even
  with nothing running)` coming back: a test party in which nobody can train
  cannot catch a fault in the control that trains them.

## Verification — in `tests/test_automap.py`

* A character with nothing readied shows a blank line, not a placeholder, and
  the card does not change height.
* A long readied list is elided to the card's width and kept whole in the
  tooltip.
* The line asks for the same height at +0, +3, +6 and +10 point, and asks the
  layout for nothing at all, so the window's floor with eight cards showing is
  the floor without the feature.
* `live.readied` returns the readied items and not the rest — checked against
  the player's own equipped party, and empty with no disk.
* The attribution is in the README and the About box, and the licence file is in
  the repository.
* A character at 0 hit points shows the skull and a drained one the arrow;
  a whole character shows neither.
* An effect is still labelled by its number.
* The quickfight badge appears only when roster `+0x0C` bit 7 is set, carries
  the tooltip `Quickfight`, stays out of the conditions row, and does not change
  the card's height when it goes.
* `live.ROSTER_QUICKFIGHT` and `live.QUICKFIGHT_BIT` are the same byte and mask
  `actions.QUICKFIGHT` writes.
* `person-running` is Font Awesome's path verbatim — three subpaths — and holds
  its ink at 13px.
