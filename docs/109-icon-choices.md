# Icons — a menu to choose from

**Status: for Donald to pick from. Nothing is decided.**

The first set was chosen from names in a list rather than by looking at the
result, and it shows: `hat-wizard` at 13 pixels reads as **a shark's fin**, and
`mask` reads as a blob. Both are drawings with fine internal detail, and fine
internal detail is exactly what disappears at this size.

## The rule the shortlist is built on

At 13 pixels in one ink colour a glyph survives only if it is a **solid
silhouette with at most one hole**. That is why `location-dot` was picked for
notes and why it works: one counter, and the counter is large. Anything with two
or more interior features turns to mush.

So the candidates below are grouped by silhouette, not by how apt the name is.

## The class icons — what to choose between

Each row is a candidate. **None of these is chosen.** They need rendering at 13,
16 and 20 pixels and looking at, which is the next step.

### Magic-user

| candidate | source | silhouette | risk |
|---|---|---|---|
| `wand-sparkles` | FA Free | a diagonal bar plus three stars | stars may vanish |
| `hat-wizard` | FA Free | tall cone | **reads as a fin; rejected on sight** |
| `sparkles` | FA Free | three four-point stars | no single mass |
| **a plain wand, ours** | drawn | one thick diagonal bar, one star | the star can be dropped at 13px |
| **a scroll, ours** | drawn | a rectangle with curled ends | reads at any size |

### Thief

| candidate | source | silhouette | risk |
|---|---|---|---|
| `mask` | FA Free | two eye holes in a band | **two counters; mush at 13px** |
| `user-ninja` | FA Free | head and shoulders with a band | busy |
| `key` | FA Free | one round bow, one bit | good silhouette, means "locks" not "thief" |
| **a dagger, ours** | drawn | blade, guard, grip | clean, and pairs with the fighter's sword |
| **a hooded head, ours** | drawn | one filled curve | distinct from every other class |

### Cleric

| candidate | source | silhouette | risk |
|---|---|---|---|
| `cross` | FA Free | two bars | reads at 10px; unambiguous |
| `hands-praying` | FA Free | two hands | busy |
| **a mace, ours** | drawn | a bar with a heavy head | avoids religious imagery |

### Fighter

Font Awesome Free **has no sword** — `sword` and `swords` are Pro only. So this
one is ours whatever happens. `automap/iconpaint.py` already carries a sword and
crossed swords drawn for the note types; the question is only which reads better
on a card.

## Where else icons would earn their place

Ordered by how much they would actually help.

| place | what | worth it? |
|---|---|---|
| toolbar | open, save, save-as, preview | **yes** — the buttons are text-only and this is what icon fonts are for |
| map | stairs | **yes** — the map has no glyph for them at all |
| roster | dead, level-drained | **already done** — skull and a down arrow |
| map | doors, locked, wizard-locked | **no** — `render.py` draws these better than a font can |
| combat | party, enemy, active | **no** — coloured squares with hit points in them are unambiguous |
| roster | poisoned, paralysed | **blocked** — the effect codes are not decoded (see below) |

## How to choose

Render every candidate at 13, 16 and 20 pixels, in the map's ink and on a card,
as one sheet. Look at it. Pick. That sheet is the deliverable, not this table --
**the mistake the first time was choosing from names.**

Anything of ours goes in `automap/iconpaint.py` beside the sword, as
`QPainterPath` primitives. Nothing about the licence changes: Font Awesome Free
paths keep their attribution in `docs/licences/`, and anything drawn here is
ours outright.
