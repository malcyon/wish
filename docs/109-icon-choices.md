# Icons — what was chosen

**Status: chosen and wired.** The candidates are gone from `automap/icons.py`;
what is left is what ships.

| place | icon | source |
|---|---|---|
| magic-user | `wizard-hat` | **ours** |
| thief | `hood` | **ours** |
| cleric | `cross` | Font Awesome Free |
| fighter | `sword` | **ours** |
| `Treasure` note | `open-treasure-chest` | game-icons.net, Skoll |
| `Encounter` note | `crossed-sabres` | game-icons.net, Lorc |
| `Exit` note | `exit-door` | game-icons.net, Delapouite |
| `Locked` note | `plain-padlock` | game-icons.net, Delapouite |
| map, `Stairs` note | `stairs` | game-icons.net, Delapouite |
| `Danger` note | `hazard-sign` | game-icons.net, Lorc |
| `Note` note, and the unknown-kind fallback | `position-marker` | game-icons.net, Delapouite |
| `Done` note | `check-mark` | game-icons.net, Delapouite |
| note editor, delete | `trash-can` | game-icons.net, Delapouite |
| toolbar, open | `open-folder` | game-icons.net, Delapouite |
| toolbar, save and save as | `save` | game-icons.net, Delapouite |
| toolbar, preview changes | `brass-eye` | game-icons.net, Lorc |
| Fast Travel help | `circle-info` | Font Awesome Free |
| roster, quickfight badge | `sparkling-sabre` | game-icons.net, Lorc |
| Person note | `person` | game-icons.net, Delapouite |
| application icon (temporary stand-in) | `pointy-hat` | game-icons.net, Lorc |

`person-running` was the quickfight badge's Font Awesome original; nothing has
drawn it since `sparkling-sabre` replaced it (`#4`/`#136`), and its path data
is deleted from `ui/icons.py` along with `skull` and `arrow-down-long`, the
other two condition-badge originals the same batch superseded.

The last row is not one of these. It is the *app* icon, judged in
[`132-logo.md`](132-logo.md) against a different bar — 16 px and up, on its own
tile. `hat-wizard`, the glyph the sheet below rejected for every *other* slot,
was the app icon until `#167` swapped in `pointy-hat` as a stand-in while an
artist is commissioned; see `132-logo.md` and `ui/appicon.py`.

The sheet is still buildable and now shows the chosen set:

    .venv/bin/python tools/iconsheet.py work/reports/icon-sheet.png

Every icon at 13, 15 and 26 pixels, in `NOTE` ink in a map cell with a wall
against it and in `MUTED` on a roster card, and then magnified 8× and 5×. **The
magnified column is the one that decides**, and it is where a replacement
drawing has to be judged too.

## The sizes an icon is actually drawn at

This changed, and it changes what the rule below is for.

| place | size | file |
|---|---|---|
| the map cell | **26** | `render.NOTE_SIZE` |
| the note editor's picker | 15 | `noteeditor.ICON` |
| the notes list in the panel | **13** | `panel.ICON_SIZE` |
| the roster card's conditions and quickfight badge | **13** | `panel.ICON_SIZE` |
| the toolbar | 16 | `editor/window.py::_toolbar_icons` |
| the Fast Travel help button | 16 | `actionbar.HELP_SIZE` |
| the application icon | 32 and up | `ui/appicon.py` |

Donald: *"Can you double the size of the note icons? They are very small. The
square they are marking is much larger than the actual icon."* So the map draws
at 26 in a 34px cell, and 13 survives in one place only — the notes list.

Two things had to move with it, both visible in a rendering from
`tools/iconsheet.py` and both now pinned by a test:

* **the count on a multi-note square.** It hung off the bottom-right of the
  *icon*, which put it outside the cell as soon as the icon grew. It is placed
  against the **cell's** bottom-right corner now, `NOTE_INSET` from each edge so
  it clears the 3px wall stroke, on a disc of paper so it reads over the glyph
  behind it.
* **the party marker.** At 13 the note sat in a corner and the two never met; at
  26 the note is most of the square. Notes are now drawn **before** the marker,
  so on the one square that carries both, the marker is on top. Where the party
  is standing is the one thing on this map that must not be in doubt.

22 is the calmer number — at 26 a note on the party's own square wraps the
triangle fairly tightly — but 26 is legible, does not swamp the roofed shading,
and is what was asked for.

## The 13px rule, as the sheet corrected it

**Scope first: this rule now binds on the notes list and nowhere else.** It was
written when the map drew at 13 and the roster class icons drew at 13; the map
draws at 26 and the class icons are gone. It is not wrong, it is narrow — and it
is still the bar a new icon has to pass, because the notes list is a real place
a real user reads.

The rule the shortlist was built on was "a solid silhouette with at most one
hole". Two things on the sheet corrected it:

* **a large second counter survives.** `mask` at 13 keeps both eye holes and
  Font Awesome's `floppy-disk` — since replaced by game-icons.net's `save`,
  below — kept both its shutter and its hub. The rule is about *feature size*,
  not hole count, and 64 units in the 640 box — Font Awesome's `location-dot`'s
  counter, since replaced by `position-marker` — is about the floor.
* **the failure that matters is separation, not mush.** `hat-wizard` reads as a
  fin because its brim is a *separate subpath* that stops touching the cone;
  `wand-sparkles`' stars come away as three loose dots for the same reason.
  Anything drawn as one connected mass survived every size on the sheet.

So: **one connected silhouette, every feature at least about 64 units.** That
is the rule `ui/icons.py` now carries.

**`person-running` is the one exception on the sheet, and it is a real one.**
Three subpaths — head, body, trailing arm — 34 pixels of ink at 13, in pieces
of 25, 5 and 4. It passes because the rule is about *unexpected* separation:
`hat-wizard`'s brim reads as a fin because nobody expects a hat to come in two
parts, where a runner's head and trailing arm are exactly what a runner looks
like. Measured up the ladder it holds from 12 upwards and only loses the arm at
11. The 13px cell it is drawn in is the roster card's quickfight badge.

## P77 — replacing the five icons we drew ourselves

Donald: *"For the font awesome choices, can you make sure the sheet includes
every AI-generated icon, and where it is used in the app? We need to fix the
class icons in the roster, too. But I'll forget where they are used."*

Five glyphs in `ui/icons.py` under `OURS`. The cleric's `cross` is Font Awesome
already and does not change; so is every toolbar and note icon not listed here.

| ours | where a user sees it | drawn at | why it was drawn rather than lifted |
|---|---|---|---|
| `wizard-hat` | the **magic-user** mark on a roster card, beside the class text | 13 px | FA's `hat-wizard` comes apart at 13 — the brim is a separate bar |
| `hood` | the **thief** mark on a roster card | 13 px | FA's `mask` is legible but reads as goggles |
| `sword` | the **fighter** mark on a roster card | 13 px | Font Awesome Free has **no sword**: `sword` and `swords` are Pro-only |
| ~~`swords`~~ | the **Encounter** note | — | **gone.** Replaced by U+2694 — see below |
| ~~`chest`~~ | the **Treasure** note | — | **gone.** Replaced by `gem`, regular weight — see below |

`automap/notes.py` is the note mapping; the map cell size is
`render.NOTE_SIZE = 26`, the notes list is `panel.ICON_SIZE = 13` and the editor
button is `noteeditor.ICON = 15`.

### The two Donald chose

**`Treasure` → Font Awesome's `gem`, the REGULAR weight**, not the solid, and
picked specifically: an outline says *thing on the floor* where a filled lozenge
on graph paper reads as terrain, which is the objection the drawn chest existed
to answer. It is the one icon in `ui/icons.py` lifted from `svgs-full/regular/`
rather than `svgs-full/solid/`, and the module docstring says so.

Measured, at half-coverage, in the 640 box:

| size | ink | pieces | holes |
|---|---|---|---|
| 13 | 36 px | **1** | 16, 3, 2, 2 |
| 15 | 57 px | **1** | 16, 4, 3, 3 |
| 26 | ~190 px | **1** | table facet plus the three crown facets |
| 56 | 704 px | **1** | 274, 56, 39, 39 |

**It survives 13 px**: one connected silhouette, and the table — the big facet
under the crown — is 16 px of paper, well clear of the 64-unit floor. The three
crown facets are 2–3 px each and are the marginal part; they go grey rather than
white and the icon still reads as a gem, which is the same verdict `hood` got
and by the same measurement. The solid weight is denser (52 px of ink at 13
against 36) and would have been the safer choice on legibility alone; it is not
the one that was asked for, and the outline holds.

**`Encounter` → U+2694 ⚔, crossed swords.** This is the only glyph in the
program that is **not** path data, and that is the whole of what has to be said
about it: it renders from whatever font the platform resolves the code point to.

| | |
|---|---|
| here (Linux, PyQt6) | **DejaVu Sans, monochrome.** 173 non-white colours in a 56px render, all of them grey — antialiasing, not colour |
| with U+FE0F appended | the colour emoji font, 362 colours, **not monochrome** — so an emoji font *is* installed and Qt will use it when asked |
| with U+FE0E appended | still DejaVu Sans, and the selector itself is a zero-width glyph from Noto Sans: same advance, same ink |
| Windows, macOS | **not verified here.** U+2694 is in Segoe UI Emoji and Apple Color Emoji as well as in monochrome faces, and Qt 6's own fallback chain — not the platform's shaper — picks. It may well come out as a colour emoji sitting among monochrome icons |

U+FE0E is the text-presentation selector and is the correct request. On this
machine it changes nothing because nothing needed changing; whether Qt honours
it on a platform that *does* default to emoji is not something a Linux box can
answer, and appending it costs a second glyph run for a zero-width character.
**Implemented bare, as asked.** If Windows shows a colour emoji, U+FE0E is the
first thing to try and this is where the evidence is.

What it buys: a real pair of crossed swords in place of a drawing that read as a
starburst at every size, which was the standing complaint about `swords`. What
it costs: at 13 px it is visibly lighter than the Font Awesome solids beside it
in the notes list — DejaVu draws the blades as thin outlines — and it is the one
icon whose appearance we do not control.

`ui/iconpaint.py` fits it to the same box the paths get, measured by its **ink**
rather than its advance: at 13 px DejaVu's ⚔ is 9×10 of ink inside an 11.6
advance, so drawing it as text would put it half out of the cell and two pixels
smaller than its neighbour.

One thing measuring the candidates turned up about **our own** drawings: at 13
px, counting a pixel as ink only when it is at least half covered, `hood` comes
apart into 43 px of cowl-and-shoulders and 7 px of crown. The bridge either
side of the face is antialiased below half, so it is grey rather than white and
the icon still reads — but by the rule this file applies to everybody else's
glyphs, ours is the marginal one.

### What Font Awesome Free actually offers

Every candidate below was rasterised at 13 px and counted, not judged by name.
"pieces" is the 13 px rule: **one connected silhouette or it fails**.

| slot | candidate | at 13 px | verdict |
|---|---|---|---|
| magic-user | `hat-wizard` | **2 pieces**, 28 + 18 | still fails, exactly as it did in 2026-08. The app icon gets away with it at 16 px on a tile; 13 px on a roster card does not |
| | `book-open` | 1 piece, one 20 px hole | **the only candidate that survives and means spellcaster** |
| | `star`, `bolt` | 1 piece each | survive; they say "magic" only by convention |
| | `wand-magic`, `wand-magic-sparkles`, `wand-sparkles` | 2, 5 and 5 pieces | all fail |
| thief | `user-secret` | 1 piece, holes 7 and 1 | survives — better than this file recorded ("mush"), and the hat and coat read |
| | `mask` | 1 piece, both eyes | survives; the goggles objection is why it was dropped and still stands |
| | `user-ninja` | **2 pieces** | the head comes away from the body |
| | `key` | 1 piece | survives, means locks |
| fighter | `shield` | 1 piece | survives, and says *defence* |
| | `shield-halved` | 1 piece plus a stray pixel, 15 px hole | survives; reads as half of something |
| | `khanda` | 1 piece, six 1–2 px holes | **not usable**: a Sikh religious emblem, wrong in meaning whatever it looks like |
| | `helmet-safety`, `hand-fist`, `gavel` | 2, 2 and 3 pieces | all fail, and all mean something else |
| encounter | `burst` | 1 piece | survives — impact rather than swords |
| | `skull` | 1 piece, both eyes | survives, but a skull already means *dead* on the roster card |
| | `dragon` | 1 piece | passes the rule and is a blob in practice |
| | `explosion`, `skull-crossbones`, `hand-fist` | 3, 2 and 2 pieces | fail |
| treasure | `gem` | 1 piece, one 7 px hole | survives, and is unmistakable |
| | `box-open` | 1 piece | survives; an open box reads as loot |
| | `vault`, `sack-dollar`, `briefcase`, `coins` | 2, 2, 2 and 10 pieces | fail |

**The honest answer for the fighter is that there is nothing.** Font Awesome
Free has no sword, no dagger, no axe and no spear; the nearest glyph in meaning
is a shield, which is a different idea. That is the one slot where dropping our
drawing costs something a replacement does not give back.

**Two are now replaced** — `chest` and `swords`, above — and the three class
icons are Donald's call.

### P77 is worth reopening, and the reason is the size change

Every "fails" in the table above is a 13 px verdict, and 13 px was the map. The
map draws at **26** now. `hat-wizard`'s brim separating from its cone,
`user-ninja`'s head coming away from its body, `wand-sparkles` falling into
loose dots — none of those is a failure at 26, and two of them are the reasons
`wizard-hat` and `hood` were drawn in the first place.

That does not automatically readmit anything: the notes list is still 13, so a
*note* icon still has to pass. But the class icons are not drawn on the map at
all, and if they come back at any size above about 20 the honest answer is that
Font Awesome has candidates it did not have before. Not swapped here — the
choice is Donald's, and the sheet is what he chooses from.

## Why the rest lost

### Magic-user — `wizard-hat`, ours

Cone joined to its brim, one silhouette, so it cannot come apart.

| rejected | why |
|---|---|
| `hat-wizard` (FA, was in use) | the fin — brim separates from the cone at 13. **It is now the application icon**, which is never drawn below 16 and sits on its own tile, where the separation is Fonticons' drawing and is left alone. See [`132-logo.md`](132-logo.md) §6. That does not readmit it here |
| `wand-sparkles` | a bar and three square dots that have nothing to do with it |
| `wand-magic` | survives, but a bare diagonal bar says nothing about magic |
| `wand`, ours | survives; the hat is the more legible of the two |
| `scroll` | a solid block with a step in it at 13; only reads at 20 |
| `parchment`, ours | failed outright — reads as a cotton reel at every size |

### Thief — `hood`, ours

Pointed cowl, face, shoulders. One hole and it holds at 13
(`test_the_hood_keeps_its_face`).

| rejected | why |
|---|---|
| `mask` (FA, was in use) | legible, but it reads as goggles — that was the objection |
| `user-ninja` | a slit-eyed head over a detached hump |
| `user-secret` | mush |
| `key` | survives, but means "locks", not "thief" |
| `dagger`, ours | survives — **and is the sword.** One pixel of guard separates them |

### Cleric — `cross`, Font Awesome

Clean at every size, unambiguous, already in use.

| rejected | why |
|---|---|
| `hands-praying` | two blobs with a white gap up the middle; reads as leaves |
| `book-bible` | a filled rectangle, which on the map reads as *terrain* |
| `mace`, ours | survives, but the cross is clearer and already drawn |

### Fighter — `sword`, ours

Font Awesome Free has no sword: `sword` and `swords` are Pro only.

| rejected | why |
|---|---|
| `shield` | a rounded blob; a shield only once you are at 20 |
| `shield-halved` | the seam survives, but it reads as "half" of something |

`swords`, ours, is gone: it read as a starburst, and U+2694 is the encounter
mark now.

### Toolbar

**Superseded by `#167`, below** — the buttons now draw game-icons.net's
`open-folder`, `save` and `brass-eye`. Left here as the record of why Font
Awesome's `folder-open` and `floppy-disk` were picked at the time.

Four buttons, three icons. `folder-open` and `floppy-disk` were the only
candidates in their slots and both read at 13. **Save As shares the floppy**:
the icon says which family the action belongs to and the label says which
member of it, which is the same division of labour the class icons use.

| rejected | why |
|---|---|
| `file-export` | the arrow is a nub at 13 |
| `file-pen` | the pen is a diagonal smear at 13 |
| `magnifying-glass` | the best glyph on the sheet, but in a toolbar it means *search* |
| `code-compare` | mush at 13 |

`eye` over `magnifying-glass` is a semantic call, not a legibility one: the
eye's concentric rings hold at 13 and "preview" is a view, not a search.

## The toolbar wiring is done

It was blocked: `tests/test_wish.py::test_editor_imports_nothing_live` fails if
the word `automap` appears anywhere under `editor/`, and `icon_pixmap` lived in
`automap/`. Moving the drawing to a package neither side owns — `ui/icons.py`
and `ui/iconpaint.py` — settled it. `editor/window.py::_toolbar_icons` paints
the four buttons at `TOOLBAR_ICON = 16`.

## Where else icons would earn their place

| place | what | worth it? |
|---|---|---|
| map | `stairs` | **done** — a `Stairs` note type, key `S`, in `automap/notes.py` |
| roster | class icons | **done** — beside the class text, never instead of it |
| roster | dead, level-drained | **already done** — skull and a down arrow |
| toolbar | open, save, save as, preview | **done** — `editor/window.py::_toolbar_icons`, 16 px |
| Fast Travel | the help affordance | **done** — `circle-info` on a `QToolButton`, `autoRaise` so it highlights on hover. It was a `QLabel` with a drawn circle and a `?`, which said nothing about being hoverable |
| map | doors, locked, wizard-locked | **no** — `render.py` draws these better than a font can |
| combat | party, enemy, active | **no** — coloured squares with hit points in them are unambiguous |
| roster | poisoned, paralysed | **blocked** — the effect codes are not decoded |

## `#167` — Font Awesome leaves the note icons, the toolbar and the app icon

Ten icons, then a further two, went this way: chosen by Donald and copied
verbatim from his game-icons.net archive.

| replaced | new glyph | artist |
|---|---|---|
| `door-open` | `exit-door` | Delapouite |
| `lock` | `plain-padlock` | Delapouite |
| `stairs` | `stairs` | Delapouite |
| `triangle-exclamation` | `hazard-sign` | Lorc |
| `location-dot` | `position-marker` | Delapouite |
| `check` | `check-mark` | Delapouite |
| `trash-can` | `trash-can` | Delapouite |
| `folder-open` | `open-folder` | Delapouite |
| `floppy-disk` | `save` | Delapouite |
| `eye` | `brass-eye` | Lorc |

**`stairs` and `trash-can` are the same name in both sets.** Font Awesome's
`svgs-full` has an icon of each name, and so does game-icons.net. Nothing else
in the program drew the Font Awesome originals — the `Stairs` note and the
note editor's delete button, respectively, were their only callers, and both
moved to the game-icons.net glyph. So the Font Awesome entries are deleted
from `FONT_AWESOME` outright rather than kept under another key: there is
nothing left to shadow, and a name that shipped under two sets with no caller
for one of them would be a dead entry waiting to be picked up by accident.
`tests/test_conditionbadges.py::test_the_two_sets_are_drawn_in_their_own_boxes`
and the `ARTISTS` test both assert `GAME_ICONS` and `FONT_AWESOME` share no
name, so a collision left in place would fail the build rather than ship
silently.

Every one of the ten went through
`tests/test_conditionbadges.py::test_our_parser_draws_what_an_svg_renderer_draws`,
which is parametrised over every name in `GAME_ICONS` and renders each at 13,
26, 128 and 512 px against Qt's own SVG renderer, pixel for pixel. All ten
pass at every size — the parser reads the artist's `d` correctly, which is
what proves nothing was redrawn.

**The last two note icons, and the app icon.** `gem` (the Treasure note, drawn
in `svgs-full/regular/`) is replaced by `open-treasure-chest` (Skoll), and the
Encounter note's U+2694 -- the one glyph in the program that was a font
character rather than a path, see `ui/icons.py`'s `TEXT_GLYPHS` -- is replaced
by `crossed-sabres` (Lorc), a path like every other note now. `hat-wizard`,
the application icon, is replaced by `pointy-hat` (Lorc) as a stand-in:
Donald, *"I am paying an artist to create an app logo and icon. In the
meantime, please use pointy-hat."* Both went through the same pixel-for-pixel
check as the ten. `crossed-sabres`' control points overshoot its 512 box by
`extent()`'s conservative bound the same way `brass-eye`'s do; its rendered
ink does not, and `tests/test_automap.py`/`tests/test_conditionbadges.py`
carry the same measured exclusion.

**The Person note's `user` is the last one, and it finishes `#167`
completely.** `person` (Delapouite) replaces it, so nothing in the program
renders a Font Awesome glyph any more. `hat-wizard` is the one name still in
`ui.icons.FONT_AWESOME`, parked unreferenced as the path data a revert of
`pointy-hat` would need; that is why it stays in the table even though the
licence it drew has come out (see Licence, below).

## Licence

**Nothing draws a Font Awesome glyph any more**, so `fontawesome-LICENSE.txt`
and the Font Awesome paragraph in the README and the About box came out with
`person` replacing `user`. `ui.icons.FONT_AWESOME` still parks `hat-wizard`'s
path data, unreferenced, as what a revert of `ui/appicon.py`'s `pointy-hat`
stand-in would need back; bringing that icon back onto the screen means
bringing the licence back too, recoverable from git history at the commit
that removed it. While it drew, Font Awesome Free's paths were verbatim from
`svgs-full/solid/`, licensed CC BY 4.0. **Nothing came from `brands/`** — the
licence forbids brand-logo use and the set carries `wizards-of-the-coast`.
The font itself was never shipped and never subset: subsetting makes an OFL
"Modified Version" and may not keep the reserved name. Anything under `OURS`
is ours outright. `TEXT_GLYPHS` is empty now that `crossed-sabres` replaced
its one entry.

Nothing is redrawn: the app icon recolours `pointy-hat` -- game-icons.net,
CC BY 3.0, Lorc -- and puts it on a tile, and the path data is theirs,
untouched, at every size.
