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
| Encounter | `crossed-sabres` | game-icons.net, Lorc | a fight, set or remembered |
| Treasure | `open-treasure-chest` | game-icons.net, Skoll | something to take, or taken |
| Person | `user` | Font Awesome | trainer, shop, quest-giver |
| Exit | `exit-door` | game-icons.net, Delapouite | where this map joins another |
| Locked | `plain-padlock` | game-icons.net, Delapouite | a door that beat you |
| Stairs | `stairs` | game-icons.net, Delapouite | up, down, or wherever the level changes |
| Danger | `hazard-sign` | game-icons.net, Lorc | traps, drains, whatever you avoid |
| Note | `position-marker` | game-icons.net, Delapouite | anything that does not fit the others |
| Done | `check-mark` | game-icons.net, Delapouite | cleared, nothing left here |

`Person` is the only note still drawing a Font Awesome path -- `#166` is what
reassigns it, to `person` (Delapouite), not `#167`.

**The icons are path data, not a font.** `ui/icons.py` carries each icon's SVG
path -- Font Awesome's in a 640×640 box, game-icons.net's in 512×512, `box()`
says which -- and `ui/iconpaint.py` fills it into a `QPainterPath`. Weighed
against `qtawesome` and against bundling `Font Awesome 7 Free-Solid-900.otf`
(405 KB), the paths win here: the map draws with `QPainter` and not `QIcon`,
so the font's one advantage is the use this program has least of; `to_svg`
exports the notes for free because it is already emitting paths; and nothing
ships that `pyproject.toml`, PyInstaller and the release build have to be told
about. The measured trap the font would have brought is also gone — at
`setPixelSize(16)` a glyph's ink and its advance are two different numbers, so
every glyph would need `tightBoundingRect` arithmetic.

`position-marker` is the generic marker (and the unknown-kind fallback)
because it is a **solid silhouette with one counter**, and that counter is
what stops it blobbing at 12px. Drawing it needs winding fill, not Qt's
odd-even default, or the counter fills in.

**One note was a character, not a path, and no longer is.** Font Awesome Free
has no sword — `sword` and `swords` are Pro, and `khanda` is a Sikh religious
emblem, wrong in meaning and illegible at twelve pixels — so the Encounter
note was a drawing of ours, then Donald's choice of **U+2694** rendered from
whatever font the machine had, and is `crossed-sabres` (Lorc) now: a path like
every other note, chosen from his game-icons.net archive on `#167`.
`icons.TEXT_GLYPHS` held U+2694 and is empty since. `docs/109-icon-choices.md`
carries the history, including what U+2694 cost while it was in use.

Brands are not used and must not be: the licence forbids brand-logo use and the
set carries `wizards-of-the-coast`.

Attribution travels with the paths: Font Awesome's in `fontawesome-LICENSE.txt`
and the README and About box, game-icons.net's generated into
`THIRD_PARTY_LICENSES.md` from `ui.icons.ARTISTS`.

## Drawing

`render.py` grew one primitive, `Glyph(x, y, size, name)`, and
`note_primitives(notes)` puts a 26px icon in the square (`NOTE_SIZE`),
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

## The file a square goes in, and the bug that got it wrong

**Fixed.** Reported from Windows: start in the Slums, walk back into town, and
the map switches to New Phlan with the Slums' top-right corner still revealed.
It survived a restart, because it was on disk.

**The cause was one line in the wrong place.** `Automapper.poll` re-reads the
resident map block at `$0400` every tenth poll, and does so *immediately* when
the party's square jumps -- that second check exists precisely because a jump
is what crossing a boundary looks like. But `_check_resident` carried its own
`% RESIDENT_EVERY` guard, so the immediate check did nothing nine times in ten
and the crossing was noticed by the ordinary periodic check instead, up to ten
polls -- two seconds at the default interval -- later. Everything the party did
in that window was recorded against the area it had left, and `set_area` then
wrote it into *that* area's file, where `load_notes` brought it back on the
next visit and it never went away.

**Reproduced live**, before the fix, in a pooled VICE instance
(`tools/instance.py`): `PORSAVE13` in the Slums at `(15,4)`, fasttravel to New Phlan,
one step, and the mapper -- still saying `GEO14` -- recorded New Phlan's
`(14,0)`, `(14,1)`, `(14,2)`, `(14,3)` and `(15,1)` into the Slums' own
`GEO14.json`. The lag between `$0400` becoming `GEO00` and the mapper saying so
was measured at five polls; at start-up it was nine.

The same defect the `--forget` help text describes, then, and not a new one:
what was fixed at the time was the *jump* path, and the rate limit inside
`_check_resident` meant that fix never ran.

Three changes, in `automap/state.py`:

* rate-limiting belongs to `poll`, which knows why it is asking.
  `_check_resident` now always reads.
* a crossing that lands the party *next door* has no jump to notice it by, so
  `_area_may_have_changed` also forces a read on either tell that the map is
  the wrong one: the party on a square this map seals, or a step across an edge
  this map calls solid. Both are tests `Fingerprint` already makes of every
  observation, and both cost no monitor traffic.
* the area is named **before** the fix is recorded, never after.

**Notes were never misfiled on their own** -- nothing writes one -- but a note
made by hand inside that window went to the departing area's file, and the
remembered squares went there every time. A map that still shows a blot from
another area is a file written before the fix: `python -m automap --forget
GEO00` clears one area's squares and keeps its notes.

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
* Every type's icon parses, and `position-marker` keeps its counter under
  winding fill.
* Clicking an existing note opens it populated, with a Delete that removes it
  from the square and from the file; a new note has no Delete to press.
* A boundary crossing puts no square of the new area into the old area's set or
  its file -- driven with a target whose `$0400` block changes partway through,
  which is the whole of what a crossing looks like from outside. All three
  shapes: the party lands far away, it lands on a square this map seals, and it
  lands across an edge this map calls solid.
* The sight radius is a setting and survives an area change.
