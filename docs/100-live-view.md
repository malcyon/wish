# The live view

**Status: built**, on the Automapper tab -- roster down the left, map on the
right, a strip along the bottom. See
[the automapper](96-live-memory-automapper.md) for what landed and what is still
open; this note is kept for *what to show* and *how to read it*, which is
unchanged.

A read-only view of what the running game holds right now.
This is the thing Gold Box Companion's HUD does and the reason it is missed: not
editing, just *seeing* — who is hurt, what is still up, how long the blessing
has left.

Combat is **not** here. It belongs on the Automapper tab, where the area map
becomes the combat map for the duration of a fight — see
[the combat view](101-combat-view.md).

---

## What there is to show

Everything below is already decoded, so this is presentation rather than
research. Live addresses, because `SAVEDGAME0` is a verbatim image of
`$4900`–`$64FF` and the character record base is `$6B00`:

| panel | from | what |
|---|---|---|
| **Party** | records at `$4D00` + roster at `$8300` | name, class, level, AC, current/max hit points, THAC0, movement, damage bonus |
| **Effects** | `$4900`–`$493F` id, `$4940`–`$497F` owner, `$4980`–`$49BF` duration, `$4B80`–`$4BBF` magnitude | active timed effects, per character or party-wide, with what remains |
| **Where** | `$49C0`–`$49C2`, `$49C7`–`$49C9`, `$4BC2` | square, facing, the clock in minutes, and the area by name |
| **Loaded** | `$4BC0`–`$4BD8` | the loader's 25-entry cache: which `GEO`, `ECL`, `MON`, `PIC` are resident. Mostly of interest while reverse engineering, so keep it collapsed |

The party panel should look like the game's own list — **name, AC, hit points,
wounded in red** — for the same reason the editor's roster does: it is what the
player recognises. The editor already has `RosterModel`; reuse it against a live
snapshot rather than writing a second one.

### One card per character

Gold Box Companion's HUD is the model, and it is the right one: a row of cards
above the game, each carrying everything you glance at mid-fight.

| element | from |
|---|---|
| **Hit point bar** | roster `+0x19` over record `hp_max` at `0x076` |
| **Experience bar** | record `0x0E8` (24-bit) against the next level's threshold |
| **Status effects** | the effect arrays, filtered to this character |
| name, class, level, AC | record and roster |

**Bars, not just numbers.** `5 / 7` needs reading; a bar two-thirds full does
not, and mid-fight that is the whole difference. Colour the hit point bar by
proportion — comfortable, hurt, in danger — and keep the numbers beside it for
when the exact value matters.

**The experience bar needs the level table**, which is not in the repo yet:
`work/goldbox-research/por_xp_tables.txt` was fetched during the research pass
and holds the thresholds per class. Bring it in as a generated table beside
`docs/86-spell-table.md`, and derive the bar from `experience` against the next
threshold for the character's class. For a multi-class character the game splits
experience between classes, so show a bar per class or the lowest — decide once
the table is in and the arithmetic can be checked against a real character.

**Status effects belong on the card, not only in their own panel.** Gold Box
Companion lists each character's effects above their portrait, and that is why
it is useful: you see that *this* one is blessed and *that* one is held without
reading a table. Show them as short labels on the card, and keep the separate
Effects panel for the full picture including party-wide and monster entries.

Colour them the way the game's own information reads: **good in green, bad in
red** -- once there is anything to colour by. **As built they are numbers.**
The forty-odd named codes in `editor/effects.py` are the *record's* list at
`0x0AD`, and whether the `$4900` timed-effect ids share that namespace is
unproven: no save we hold was taken mid-effect, so the arrays are zero in all
of them and nothing on disk can settle it. Until it is settled an id shows as
its number, which is visibly unknown rather than quietly mislabelled.

**Effects is the panel that earns the tab.** Nothing else in the project shows
them, the game itself only hints, and the decode is recent: the four parallel
64-slot arrays, owner `0`–`7` for a party member, `8+` for a monster, `$FF` for
the whole party, and bits 6–7 of the duration byte selecting the time unit.
Expiry clears only the id, so **filter on a non-zero id** or you will show
effects that ended.

---

## How it reads

One batched read per poll, not a dozen small ones — the cost is per round trip,
not per byte, measured at 14.3 ms either way under VICE.

`$4900`–`$64FF` is `$1C00` bytes and covers the header, the effect arrays, every
character record and the item area in a single read. `$8300`–`$83FF` is a second
for the roster. **Two reads, whole tab.**

Feed both into `por/savegame.py` unchanged: `SaveGame0.from_bytes()` takes
exactly those bytes and gives back records, party position, area and the icon
table with no new decoding at all. That is the payoff of having kept `por/`
transport-free.

Poll only while the tab is visible, at the backend's own interval.

---

## Read-only, and why

No editing here, and it is not timidity. Two things are already known:

* **Live pokes into the item area do not stick.** Writing `$5A98` was reverted
  by the game, so `$5900`+ is a copy fed from a master elsewhere. Anything
  offering to edit it would be lying.
* **The game is heavily overlaid.** An address means what we think only while
  its overlay is resident, and a write to the wrong overlay has already
  corrupted a live routine once.

The editor tab edits files, safely and losslessly. That is the right place for
editing. If live editing ever earns its way in, it starts as one field with one
proven experiment behind it, not as a general poke.

**Validate before trusting.** Each snapshot should be sanity-checked — position
inside 0–15, a plausible party count, records that decode — and a failed check
should hold the last good snapshot and say "not readable right now" rather than
render nonsense. During combat, in camp, on a menu, and at the title screen, some
of this simply is not there.

---

## Structure

```
automap/live.py    two reads -> plain dataclasses, no Qt
automap/panel.py   the cards and the bottom strip
```

`live.py` takes a `Target` and returns data. It contains no Qt and no backend
knowledge, so it is testable against a dictionary of bytes -- a save file *is* a
captured snapshot -- and works against the Ultimate the day that backend exists.

**It is under `automap/` and not `wish/live/`, as this plan first said.** The
panel is part of the Automapper window, which lives in `automap/`, and `wish/`
imports `automap/` rather than the other way round.

---

## Making it useful rather than a debug dump

Three things decide whether this gets looked at twice:

* **Wounded reads at a glance.** Colour, and a bar, not just `5 / 7`.
* **Effects count down visibly.** A duration that ticks is worth watching; a
  number that changes only when you look is not.
* **It says when it is stale.** A snapshot from four seconds ago during a
  disk load should say so, not pretend.

And one thing to resist: this should not become a second character sheet. If a
number is only interesting while editing, it belongs on the editor tab.

---

## Order of work

1. `snapshot.py` — the two reads and the dataclass, tested headless against
   captured bytes. A save file *is* a captured snapshot, so
   `PORSAVE11.D64` and `PORSAVE13.D64` are ready-made fixtures.
2. The experience table, generated from
   `work/goldbox-research/por_xp_tables.txt` into `docs/` beside the spell and
   item tables. Needed before any experience bar can be drawn, and useful to the
   editor too.
3. The party cards: hit point bar, experience bar, per-character effects.
4. The effects panel — the full picture, including party-wide and monster rows.
5. Where, and the collapsed loaded-files list.

Step 1 is worth landing alone: it turns "read the live game" into a pure
function, which is also what a future Ultimate backend needs.

---

## Verification

* `snapshot.py` against `PORSAVE11.D64`'s bytes gives six characters with
  ROLAND at 5 of 7 and wounded — the same assertion the editor's roster test
  makes, from the same bytes by a different path.
* Against `PORSAVE13.D64`, the area reads `GEO14`, the Slums.
* A snapshot of all zeros is rejected rather than shown as six dead characters.
* Switching away from the tab stops the polling — assert no reads while hidden.
* With the effects arrays zeroed, the panel says "none", not six blank rows.
* A hit point bar at 5 of 7 is two-thirds full and coloured as hurt; at full it
  is not coloured as hurt.
* An experience bar sits between the character's current level threshold and the
  next, and is checked against a character whose level the game itself displays.
* A character with no effects shows an empty strip on their card, not a gap that
  shifts the layout.
* Live, in the game: cast a spell with a duration and watch it count down, then
  confirm the row disappears when the game clears the id.
