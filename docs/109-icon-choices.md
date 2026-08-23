# Icons — what was chosen

**Status: chosen and wired.** The candidates are gone from `automap/icons.py`;
what is left is what ships.

| place | icon | source |
|---|---|---|
| magic-user | `wizard-hat` | **ours** |
| thief | `hood` | **ours** |
| cleric | `cross` | Font Awesome Free |
| fighter | `sword` | **ours** |
| map, `Stairs` note | `stairs` U+E289 | Font Awesome Free |
| toolbar, open | `folder-open` | Font Awesome Free |
| toolbar, save and save as | `floppy-disk` | Font Awesome Free |
| toolbar, preview changes | `eye` | Font Awesome Free |
| application icon | `hat-wizard` | Font Awesome Free |

The last row is not one of these. It is the *app* icon, judged in
[`132-logo.md`](132-logo.md) against a different bar — 16 px and up, on its own
tile — and it is the one glyph the sheet below rejected.

The sheet is still buildable and now shows the chosen set:

    .venv/bin/python tools/iconsheet.py work/reports/icon-sheet.png

Every icon at 13, 16 and 20 pixels, in `NOTE` ink in a map cell with a wall
against it and in `MUTED` on a roster card, and then magnified 8×. **The
magnified column is the one that decides**, and it is where a replacement
drawing has to be judged too.

## The 13px rule, as the sheet corrected it

The rule the shortlist was built on was "a solid silhouette with at most one
hole". Two things on the sheet corrected it:

* **a large second counter survives.** `mask` at 13 keeps both eye holes and
  `floppy-disk` keeps both its shutter and its hub. The rule is about *feature
  size*, not hole count, and 64 units in the 640 box — `location-dot`'s counter
  — is about the floor.
* **the failure that matters is separation, not mush.** `hat-wizard` reads as a
  fin because its brim is a *separate subpath* that stops touching the cone;
  `wand-sparkles`' stars come away as three loose dots for the same reason.
  Anything drawn as one connected mass survived every size on the sheet.

So: **one connected silhouette, every feature at least about 64 units.** That
is the rule `automap/icons.py` now carries.

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
| `swords` | the **Encounter** note — the glyph in the map cell, the row in the notes list, and the button in the note editor's picker | 13, 13 and 15 px | the same: no swords in FA Free |
| `chest` | the **Treasure** note, in the same three places | 13, 13 and 15 px | drawn as an outline, because a filled rectangle on graph paper reads as *terrain* |

`CLASS_ICON` in `automap/panel.py` is the roster mapping and `automap/notes.py`
is the note one; the map cell size is `render.NOTE_SIZE = 13` and the editor
button is `noteeditor.ICON = 15`.

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

**Nothing is replaced yet** — the choice is Donald's, and the sheet is what he
chooses from.

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
| `swords`, ours | reads as a starburst, and already means "encounter" on the map |
| `shield` | a rounded blob; a shield only once you are at 20 |
| `shield-halved` | the seam survives, but it reads as "half" of something |

### Toolbar

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
| map | doors, locked, wizard-locked | **no** — `render.py` draws these better than a font can |
| combat | party, enemy, active | **no** — coloured squares with hit points in them are unambiguous |
| roster | poisoned, paralysed | **blocked** — the effect codes are not decoded |

## Licence

Font Awesome Free paths are verbatim from `svgs-full/solid/`, licensed CC BY
4.0, attributed in the README and the About box with the text in
`docs/licences/`. Nothing is redrawn: the app icon recolours `hat-wizard` and
puts it on a tile, and the path data is theirs, untouched, at every size.
**Nothing comes from `brands/`** — the licence forbids
brand-logo use and the set carries `wizards-of-the-coast`. The font itself is
not shipped and not subset: subsetting makes an OFL "Modified Version" and may
not keep the reserved name. Anything under `OURS` is ours outright.
