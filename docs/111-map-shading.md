# Darker walls, and hatching — plan

**Status: planned, not started. Small, and mostly a matter of taste.**

The combat map draws impassable squares as a very light grey fill. Donald wants
them **darker**, and raises **cross-hatching in the style of Dyson Logos's
dungeon maps**.

## Why hatching suits this

The map's whole visual argument is hand-drawn graph paper: line art, a faint
lattice, doors as breaks in a wall with a leaf drawn in. A flat grey fill is the
one element that looks like a computer drew it. Hatching is what an ink-and-pen
cartographer actually does to mark solid rock, so it is more in keeping than a
darker fill would be, not less.

## Three options, cheapest first

| option | what | cost |
|---|---|---|
| **darker fill** | one constant | minutes |
| **diagonal hatching** | parallel lines at 45 degrees, clipped to the square | small |
| **cross-hatching** | two sets at 45 and 135 | small, and denser |

All three are the same change to `automap/combat.py`'s `battlefield`, which
already yields drawing primitives, plus a new primitive in `render.py`. **Do the
darker fill first** — it may be all that is wanted, and it costs one line.

## What to watch

* **Hatching must not fight the combatants.** Party green and enemy red sit on
  top of it; hatching that is too dense turns the map into texture and the
  squares stop reading. Try it with a crowded fight, not an empty map.
* **Hatch at the square, not the canvas.** Lines drawn across the whole map and
  clipped will crawl as the camera moves, because the pattern's origin stays
  put. Anchor the pattern to each square's own top-left corner.
* **It has to survive scaling.** The cell size varies with the window; hatching
  spaced in absolute pixels goes solid when the cells are small. Space it as a
  fraction of the cell, with a floor below which it falls back to a plain fill.
* Dyson's maps also carry a heavy outer line around solid mass and a lighter
  interior. Worth trying: hatch the interior, and thicken the boundary between
  passable and impassable.

## Also worth considering at the same time

The area map draws walls but does not shade anything. If hatching works on the
combat map, the same primitive would let indoor squares carry it, which is
currently a flat tint.

## Verification

* A crowded fight still reads at a glance: every combatant square is
  unmistakable against the hatching.
* Hatching does not crawl when the camera scrolls.
* At the smallest cell size it degrades to a plain fill rather than a solid
  block.
* Both themes, since the map's ink and paper differ between them.
