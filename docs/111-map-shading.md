# Darker walls, and hatching

**Status: done.** Three shadings for solid rock on the combat map, chosen by one
constant; Donald picked `HATCH`, and `automap/window.py` paints it.

## The three, and the constant

`automap/combat.py`:

```python
FILL, HATCH, CROSS = "fill", "hatch", "cross"
SHADING = HATCH
```

| `SHADING` | what `battlefield` yields for a rock square |
|---|---|
| `FILL` | `Rect(kind="block")`, as before, on a darker fill |
| `HATCH` | `Hatch` — the fill plus one set of 45-degree strokes — and a `Line(kind="rock-edge")` wherever rock meets ground |
| `CROSS` | the same with two sets, at 45 and 135 |

The fill went from `#e7ecf2` to `#c3d0dd`. The old value was the tint a *roofed*
square carries on the area map, which against `#fbfcfd` paper reads as more
paper.

## What the shape of it is

* **`Hatch` is a `Rect`** (`automap/render.py`). A painter that has never heard
  of hatching still fills the square and loses only the strokes, so the window
  and the geometry could land in either order.
* **The strokes are clipped by the geometry**, absolute coordinates, so no
  painter needs a clip region.
* **Anchored at the square's own top-left**, not the canvas. A canvas-anchored
  pattern keeps its origin while the square slides over it, and every stroke
  walks a pixel a scroll.
* **The spacing divides the cell**, so neighbours join up and a mass of rock is
  one run of hatching rather than a grid of tiles.
* **The floor is measured across the strokes**, not along the cell:
  `HATCH_MIN = 4.0` px. Below it `hatch_lines` returns `()` and the square is a
  plain fill. A single hatch is `HATCH_STEPS = 3` per cell and so gives up below
  a 17px cell; the cross is spaced wider at `CROSS_STEPS = 2`, because two sets
  at the single pattern's spacing stop reading as strokes and become a grey.
  The view's own range is `CELL_MIN` 12 to `CELL_MAX` 30.
* **No line between one rock square and the next.** The heavy `rock-edge` runs
  only where rock meets ground, which is Dyson Logos's inked outline round a
  mass with a lighter interior — and the difference between a map somebody drew
  and a map something tiled.
* Fills are all emitted before the outline, because a stroke sits astride the
  line it is drawn on and a later fill would paint over half of it. Combatants
  come after both.

Tested in `tests/test_shading.py`, including the crowded fight: thirteen
combatants over cross-hatching, every one of them emitted after the last rock
primitive and each holding a whole square.

## What the window paints

**Landed.** `CombatCanvas._draw` in `automap/window.py` has two more branches
and the fill moved:

* `BLOCK` is `#c3d0dd`, `HATCH_PEN` is `#68809a` (`render.ROCK_FILL` and
  `ROCK_HATCH`).
* **`Hatch` is tested before `Rect`**, because a `Hatch` *is* a `Rect` and the
  older branch would swallow it. It fills with no pen, then strokes `lines` at
  1px. Empty `lines` — the small-cell fallback — is therefore a plain fill and
  needs no separate branch.
* **`Line`**, which this canvas ignored entirely: 2.5px in `INK` for
  `rock-edge`, 1px otherwise. Without it the inked outline round a mass of rock
  was invisible, and at the smallest cell the rock had no edge at all.

The area map's `_draw` is untouched: `map_primitives` yields no `Hatch`, and a
branch for a primitive that cannot arrive is a lie about what the code does.

Painted offscreen and counted in `tests/test_shading.py`: strokes darker than
the fill inside the rock at a full cell, none at `CELL_MIN`, and the boundary
inked at both.

## Both themes

There is no dark theme in the window yet; the screenshots were rendered against
one to check the shading holds, and it does. What the pattern needs is a fill
one step off the paper and a pen between the two — on dark paper `#161d24`,
rock `#2f3d4c` and pen `#7d8ea1`, with the heavy outline in the light ink. The
hatching is what carries the reading, so it survives the inversion better than
the flat fill does: a flat fill has only its own lightness to work with.

## The area map

The same primitive would work there — `map_primitives` can yield `Hatch` where
it yields `Rect(kind="roofed")`, and `to_svg` already draws one. **But the
meaning is wrong.** Hatching means solid rock to anyone who reads dungeon maps,
and `roofed` is floor you can stand on. If the area map is to carry hatching it
should carry it outside the walls, over what has never been explored, which is
the part that actually is solid. Not done: not asked for, and it wants its own
decision about fog.
