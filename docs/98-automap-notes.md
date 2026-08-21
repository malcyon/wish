# Note-taking on the automap

**Status: built.** `automap/notes.py` is the model, `automap/icons.py` the
icons, `automap/noteeditor.py` the popover, `NotesPanel` in `automap/panel.py`
the list, and `tests/test_automap.py` holds the verification below.

A note is a **kind plus a few words** — "there is a fight here", "locked, come
back", "exit to Kuto's Well". Half of them are things you want to see from
across the map without hovering, which is why the kind carries an icon and the
words are the tooltip.

---

## The types

`TYPES` in `automap/notes.py`, in picker order. The table is data, so adding a
type is one line.

| type | icon | source | for |
|---|---|---|---|
| Encounter | crossed swords | ours | a fight, set or remembered |
| Treasure | chest | ours | something to take, or taken |
| Person | `user` | Font Awesome | trainer, shop, quest-giver |
| Exit | `door-open` | Font Awesome | where this map joins another |
| Locked | `lock` | Font Awesome | a door that beat you |
| Stairs | `stairs` | Font Awesome | up, down, or wherever the level changes |
| Danger | `triangle-exclamation` | Font Awesome | traps, drains, whatever you avoid |
| Note | `location-dot` | Font Awesome | anything that does not fit the others |
| Done | `check` | Font Awesome | cleared, nothing left here |

**The icons are path data, not a font.** `automap/icons.py` carries each icon's
SVG path in a 640×640 box and `automap/iconpaint.py` fills it into a
`QPainterPath`. Weighed against `qtawesome` and against bundling
`Font Awesome 7 Free-Solid-900.otf` (405 KB), the paths win here: the map draws
with `QPainter` and not `QIcon`, so the font's one advantage is the use this
program has least of; `to_svg` exports the notes for free because it is already
emitting paths; and nothing ships that `pyproject.toml`, PyInstaller and the
release build have to be told about. The measured trap the font would have
brought is also gone — at `setPixelSize(16)` the ink of `location-dot` is 14×18
with a 3px descender and the advance differs per icon, so every glyph would need
`tightBoundingRect` arithmetic.

`location-dot` is the generic marker because it is the only candidate that is a
**solid silhouette with one counter**, and that counter is what stops it
blobbing at 12px. Drawing it needs winding fill, not Qt's odd-even default, or
the counter fills in.

**Font Awesome Free has no sword** — `sword` and `swords` are Pro, and `khanda`
is a Sikh religious emblem, wrong in meaning and illegible at twelve pixels — so
the crossed swords, the chest and the fighter's blade are ours, built from
straight lines in the same 640 box. Brands are not used and must not be: the
licence forbids brand-logo use and the set carries `wizards-of-the-coast`.

Attribution travels with the paths: `docs/licences/fontawesome-LICENSE.txt`, a
line in the README, and a line in the About box.

## Drawing

`render.py` grew one primitive, `Glyph(x, y, size, name)`, and
`note_primitives(notes)` puts a 13px icon in the square's **top-right corner**,
3px in. That inset is measured against the 3px wall stroke, half of which lies
inside the cell: `test_a_note_never_lands_on_a_wall` puts a note on all 256
squares of `GEO14` and checks every one against every wall segment. A square
with several notes draws the first one's icon and a count.

**Notes are drawn regardless of fog.** A note is something you know.

## Interaction

* **Click an empty square** — a popover at that square: nine icons, a one-line
  text field, Enter to keep, Escape to drop. No modal dialog. A type's initial
  letter picks it while the text field does not have focus.
* **Click a square that already has a note** — the same popover, **opened on
  that note**: its type picked, its words in the field, and a **Delete** button
  beside Keep. The first version opened blank and offered no way to remove
  anything, so a note was something you could make and not unmake; that was the
  worst bug in this feature and it is what these two lines exist to prevent.
* **Several notes on one square** — the others are listed above the field, each
  a row you can click to edit and a bin you can click to delete.
* **Right-click a square with notes** — the same edits from a menu.
  `AutomapWindow.note_menu_entries` is that offer as data, so it is tested
  without a display.
* **Hover** — the tooltip lists every note on the square, `MapCanvas.tooltip_at`
  answering, as the combat canvas does.
* **`N`** — a note on the square the party is standing in, without the mouse.
* **The notes panel**, top right, lists every note in the area with its square;
  clicking a row flashes the square on the map. That is what makes notes useful
  for *finding* something again, which the icons alone do not solve.

An empty note of the default type adds nothing: it would draw a marker that
says nothing.

## Storage

The existing per-area JSON, extended:

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

* **A list per square**, because squares hold two things — a fight and the
  treasure it guards.
* **`type` is a string**, so the file stays readable and an unknown type keeps
  its own name and draws the neutral marker instead of silently becoming a
  different type.
* **The old format still loads.** `"6,2": "some text"` becomes one note of type
  `note`, and is rewritten in the new shape without loss.
* Junk costs only the junk: an unparseable square or note is dropped, not
  raised, because the file is hand-editable by design.

`--forget` still clears squares and keeps notes.

## What this does not do, on purpose

* **No note types with mechanics.** A note does not track quest state. The game
  is the authority on what has happened.
* **No auto-generated notes.** The map would fill with pins for every wandering
  monster; the useful signal is the ones a person chose to make.
* **No export yet.** `to_svg(geo, notes=...)` already draws them, so the export
  is a caller away.

## Verification — in `tests/test_automap.py`

* Old-format notes load and are rewritten in the new shape without loss.
* A square with three notes draws one icon and a count, and its tooltip lists
  all three.
* Notes on a fogged square are still drawn.
* No note primitive overlaps a wall segment anywhere on `GEO14`.
* `--forget ALL` clears squares and leaves every note untouched.
* Every type's icon parses, and `location-dot` keeps its counter under winding
  fill.
* Clicking an existing note opens it populated, with a Delete that removes it
  from the square and from the file; a new note has no Delete to press.
