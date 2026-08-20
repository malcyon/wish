# Note-taking on the automap — plan

**Status: planned, not started.** For review before any of it is built.

Today a square can hold one string, edited through a dialog and drawn as a small
`*`. That is a placeholder, not a design. This is what it should become.

---

## What notes are actually for

Worth being concrete, because it decides the shape. Playing the slums, the notes
a person wants to make are:

* **"there is a fight here"** — a set encounter, so you know not to walk back
  into it, or that you still owe it a visit.
* **"treasure, needs a thief"** — something found and not yet taken.
* **"locked, come back"** — a door you could not open.
* **"exit to Kuto's Well"** — where the block joins its neighbours.
* **"fortune teller"**, **"Ohlo"**, **"the trainer"** — who is where.
* **"cleared"** — this corner is done, stop coming back.

Two things fall out of that list. Most notes are a **kind** plus a few words,
not free prose. And a good half of them are things the player wants to see
*from across the map* without hovering — the whole point is not walking back
into a fight.

So: a small set of **note types**, each with an icon, plus optional text.

---

## The types

| type | icon | for |
|---|---|---|
| Encounter | crossed swords | a fight, set or remembered |
| Treasure | a small chest or coin | something to take, or taken |
| Person | a standing figure | trainer, shop, quest-giver |
| Exit | an arrow through the wall | where this map joins another |
| Locked | a keyhole | a door that beat you |
| Danger | an exclamation | traps, drains, whatever you want to avoid |
| Note | a dog-ear | anything that does not fit the above |
| Done | a tick | cleared, nothing left here |

Eight is enough to be scannable and few enough to fit a toolbar. The set is
data, not code — a table in `automap/notes.py` — so adding one later is a line.

Drawing: the icon in the square's corner, so it does not collide with the party
marker or with a door on that square's wall. **Never draw a note in a way that
hides a wall** — the map's job is the walls, and a note that obscures one has
made the map worse. A square with several notes draws the first and a small
count.

---

## Interaction

The current dialog is wrong in one specific way: it makes adding a note a modal
interruption, and you are adding notes *while playing*, with the game in the
other window.

* **Click a square** — a small popover at that square: type picker as eight
  icons, a one-line text field, Enter to accept, Escape to cancel. No modal
  dialog, no OK button.
* **Right-click a square with notes** — edit or delete, listed.
* **Hover** — tooltip with the text, so the icon alone is enough most of the
  time.
* **A notes panel** beside the map, listing every note in the area with its
  square. Click a row to flash the square. This is what makes notes useful for
  *finding* something again, which the icons alone do not solve.
* **`N`** puts a note on the square the party is standing in, without the mouse
  — the common case while playing.

Notes are visible **regardless of fog**. A note is something you know; hiding it
because the square is currently fogged would be perverse.

---

## Storage

Extend the existing per-area JSON rather than adding a second file:

```json
{
  "seen": ["3,14", "3,13"],
  "notes": {
    "6,2": [
      {"type": "person", "text": "arena master", "at": "2026-08-20T12:14:03"},
      {"type": "encounter", "text": "dueling pairs"}
    ]
  }
}
```

Three deliberate choices:

* **A list per square**, not one string. Squares genuinely hold two things — a
  fight *and* the treasure it guards.
* **`type` is a string**, not an index, so the file stays readable and a renamed
  or removed type degrades to an unknown icon instead of silently becoming a
  different one.
* **The old format must keep loading.** `"6,2": "some text"` becomes one note of
  type `note`. Nobody's notes get eaten by an upgrade; there is a test for it.

Notes are keyed by area, so `GEO14.json` is the slums. That is already how it
works and it survives `--forget`, which clears squares and keeps notes.

---

## What this does not do, on purpose

* **No note types with mechanics.** A note is a note; it does not track quest
  state or tick itself off. The game is the authority on what has happened, and
  a note that claims otherwise is worse than no note.
* **No auto-generated notes.** It would be easy to drop an "encounter here" pin
  when combat starts, and tempting — but the map would fill with pins for every
  wandering monster, and the useful signal is the ones a person chose to make.
  Revisit only if the ECL script ids turn out to name *set* encounters
  specifically, which `docs/50-experiments.md` suggests they might.
* **No sharing or export yet.** An SVG or PNG export with notes drawn is
  obviously wanted, but it is a separate task and the renderer already emits
  primitives, so it costs little later.

---

## Order of work

1. `automap/notes.py` — the type table, a `Note` dataclass, load and save
   including the old-format upgrade. Headless, tested.
2. Drawing: icons as primitives from `render.py`, so the SVG path gets them
   free. Corner placement, collision with walls checked by eye on a dense map
   such as `GEO14`.
3. The popover, replacing the modal dialog. `N` for the party's square.
4. The side panel, and click-to-flash.

Step 1 is worth landing alone: it makes the storage right before there is data
in the wrong shape to migrate.

---

## Verification

* Old-format notes load, and are rewritten in the new shape without loss.
* A square with three notes draws one icon and a count, and its tooltip lists
  all three.
* Notes on a fogged square are still drawn.
* No note primitive overlaps a wall segment on `GEO14`, which is the densest
  map we have.
* `--forget ALL` clears squares and leaves every note untouched.
