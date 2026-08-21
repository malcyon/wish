# Icons — a menu to choose from

**Status: for Donald to pick from. Nothing is decided.**

The sheet is `work/reports/icon-sheet.png`, made by

    .venv/bin/python tools/iconsheet.py work/reports/icon-sheet.png

Every candidate, at 13, 16 and 20 pixels, in `NOTE` ink in a map cell with a
wall against it and in `MUTED` on a roster card, and then magnified 8× so the
pixels are visible. **The magnified column is the one that decides.**

The candidates all live in `automap/icons.py` under `CANDIDATES`, so the sheet
draws them through `iconpaint` — the same code the map and the roster use.
When the pick is made, the winners move up into `FONT_AWESOME` or `OURS` and
the rest of that block goes.

## The rule the shortlist is built on

At 13 pixels in one ink colour a glyph survives only if it is a **solid
silhouette with at most one hole**. That is why `location-dot` was picked for
notes and why it works: one counter, and the counter is large. Anything with two
or more interior features turns to mush.

Two things looking at the sheet corrected:

* **a large second counter can survive.** `mask` at 13 keeps both eye holes and
  `floppy-disk` keeps both its shutter and its hub. The rule is really about
  *feature size*, and 64 units in the 640 box — `location-dot`'s counter — is
  about the floor.
* **the failure that matters is separation, not mush.** `hat-wizard` reads as a
  fin because its brim is a *separate subpath* that stops touching the cone;
  `wand-sparkles`' stars become three loose dots for the same reason. Anything
  drawn as one connected mass survived every size on the sheet.

## The class icons — what to choose between

Verdicts are what the 13px magnification shows, nothing else.

### Magic-user

| candidate | source | at 13 px |
|---|---|---|
| `hat-wizard` | FA Free | **in use.** Cone, then a gap, then a loose bar. The fin |
| `wand-sparkles` | FA Free | a bar and three square dots that have nothing to do with it |
| `wand-magic` | FA Free | clean diagonal bar with a square tip. Survives |
| **`wizard-hat`, ours** | drawn | leaning cone joined to its brim, one silhouette. Survives |
| **`wand`, ours** | drawn | bar with the star grown onto the tip, so the star cannot come loose. Survives |
| `scroll` | FA Free | a solid block with a step in it at 13; only reads at 20 |
| **`parchment`, ours** | drawn | **fails.** A sheet with a roll top and bottom reads as a cotton reel at every size |

### Thief

| candidate | source | at 13 px |
|---|---|---|
| `mask` | FA Free | **in use.** Both counters survive — it reads as goggles, which is the objection, not illegibility |
| `user-ninja` | FA Free | a slit-eyed head over a detached hump |
| `user-secret` | FA Free | mush |
| `key` | FA Free | the bow's counter is large and holds. Survives, and means "locks" |
| **`dagger`, ours** | drawn | survives — **and is the sword.** One pixel of guard separates them |
| **`hood`, ours** | drawn | pointed cowl, face, shoulders. One hole and it holds at 13 (`test_the_hood_keeps_its_face`) |

### Cleric

| candidate | source | at 13 px |
|---|---|---|
| `cross` | FA Free | **in use.** Clean at every size. Unambiguous |
| `hands-praying` | FA Free | two blobs with a white gap up the middle; reads as leaves |
| `book-bible` | FA Free | a filled rectangle — which on the map reads as *terrain*, the one thing an icon there must not do |
| **`mace`, ours** | drawn | eight-lobed head on a haft. Survives, and avoids religious imagery |

### Fighter

Font Awesome Free **has no sword** — `sword` and `swords` are Pro only.

| candidate | source | at 13 px |
|---|---|---|
| `sword` | ours, in use | clean |
| `swords` | ours, in use | reads as a starburst, and it already means "encounter" on the map |
| `shield` | FA Free | a rounded blob; a shield only once you are at 20 |
| `shield-halved` | FA Free | the seam survives. Reads, but as "half" of something |

## Where else icons would earn their place

| place | what | worth it? |
|---|---|---|
| map | `stairs` (U+E289) | **yes** — clean staircase at 13, and the map has no glyph for stairs at all |
| toolbar | open, save, save as, preview | **yes** — the buttons are text-only and this is what icon fonts are for |
| roster | dead, level-drained | **already done** — skull and a down arrow |
| map | doors, locked, wizard-locked | **no** — `render.py` draws these better than a font can |
| combat | party, enemy, active | **no** — coloured squares with hit points in them are unambiguous |
| roster | poisoned, paralysed | **blocked** — the effect codes are not decoded |

The toolbar is the character editor's — `editor/ui_character.py` builds
`button_open`, `button_save`, `button_save_as`, `button_preview` and
`editor/window.py` wires them — so those four buttons are where the choice
lands, at 16 px beside the text and never instead of it.

| button | candidate | at 13 px |
|---|---|---|
| open | `folder-open` | reads |
| save | `floppy-disk` | reads; both counters survive |
| save as | `file-export` | the arrow is a nub at 13, reads at 20 |
| save as | `file-pen` | the pen is a diagonal smear at 13 |
| preview | `eye` | concentric rings; reads |
| preview | `magnifying-glass` | the best glyph on the sheet at 13 — one large counter and a handle |
| preview | `code-compare` | mush at 13 |

## Licence

Font Awesome Free paths are verbatim from `svgs-full/solid/`, licensed CC BY
4.0, attributed in the README and the About box with the text in
`docs/licences/`. **Nothing comes from `brands/`** — the licence forbids
brand-logo use and the set carries `wizards-of-the-coast`. The font itself is
not shipped and not subset: subsetting makes an OFL "Modified Version" and may
not keep the reserved name. Anything drawn in `CANDIDATES_OURS` is ours
outright.
