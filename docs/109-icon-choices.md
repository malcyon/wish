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

## Why the rest lost

### Magic-user — `wizard-hat`, ours

Cone joined to its brim, one silhouette, so it cannot come apart.

| rejected | why |
|---|---|
| `hat-wizard` (FA, was in use) | the fin — brim separates from the cone at 13. **It is now the application icon**, which is never drawn below 16 and sits on its own tile; below 22 px `ui/appicon.py` slides the brim up against the cone. See [`132-logo.md`](132-logo.md) §6. That does not readmit it here |
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

## The toolbar wiring is not done — and cannot be from here

`tests/test_wish.py::test_editor_imports_nothing_live` greps every file in
`editor/` and fails if the word `automap` appears in one. `icon_pixmap` lives
in `automap/iconpaint.py`, so the two lines that would do it —

```python
from automap.iconpaint import icon_pixmap                    # in the imports
button.setIcon(QIcon(icon_pixmap(name, 16, QColor("#5c6b7a"))))
```

— fail that test in `editor/window.py`, where `button_open`, `button_save`,
`button_save_as` and `button_preview` are wired. The guard is about the editor
never touching a live machine and `iconpaint` is pure drawing, but relaxing a
guard to let a change through is Donald's call, not an agent's.

**Two ways out, both bigger than the wiring:** move `icons.py` and
`iconpaint.py` to a package neither `automap` nor `editor` owns, or narrow the
grep from the package name to what it is actually promising. Until then the
four buttons stay text-only, which is what they are today.

## Where else icons would earn their place

| place | what | worth it? |
|---|---|---|
| map | `stairs` | **done** — a `Stairs` note type, key `S`, in `automap/notes.py` |
| roster | class icons | **done** — beside the class text, never instead of it |
| roster | dead, level-drained | **already done** — skull and a down arrow |
| toolbar | open, save, save as, preview | **chosen, blocked** — see above |
| map | doors, locked, wizard-locked | **no** — `render.py` draws these better than a font can |
| combat | party, enemy, active | **no** — coloured squares with hit points in them are unambiguous |
| roster | poisoned, paralysed | **blocked** — the effect codes are not decoded |

## Licence

Font Awesome Free paths are verbatim from `svgs-full/solid/`, licensed CC BY
4.0, attributed in the README and the About box with the text in
`docs/licences/`. The app icon is the one place a glyph is **changed**: it is
recoloured, and below 22 px `hat-wizard`'s brim is moved. CC BY wants that said,
and Help > About says it. **Nothing comes from `brands/`** — the licence forbids
brand-logo use and the set carries `wizards-of-the-coast`. The font itself is
not shipped and not subset: subsetting makes an OFL "Modified Version" and may
not keep the reserved name. Anything under `OURS` is ours outright.
