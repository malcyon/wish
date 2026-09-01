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
red** -- once there is anything to colour by.

**The objection this section used to raise is retired.** It said the `$4900`
timed-effect ids might not share the record's `0x0AD` namespace, and that no
save we hold was taken mid-effect so nothing could settle it. Both halves are
wrong. `P3-EFFECTS.D64` was saved with twenty-six spells running
([133](133-active-effects.md)), and the question is settled the other way:
**it is one namespace**, because `LIBRARY $4028` reads the arrays first and
falls back to the character's own slots, so `goldbox/traits.py` names both.
A Sleep cast in a live fight writing id 53 on each sleeper is the same
namespace seen from the running game ([50](50-experiments.md), "What a Sleep
writes, and what it does not").

An id with no name still shows as its number, which is visibly unknown rather
than quietly mislabelled -- but that is now a gap in the name table, not a
doubt about which table applies.

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

Feed both into `goldbox/savegame.py` unchanged: `SaveGame0.from_bytes()` takes
exactly those bytes and gives back records, party position, area and the icon
table with no new decoding at all. That is the payoff of having kept `goldbox/`
transport-free.

Poll only while the tab is visible, at the backend's own interval -- 200 ms
for VICE, 500 ms for the Ultimate. `File > Preferences…` overrides it;
0 there means "the backend's own", which is the default.

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

1. **Done, as `automap/live.py`** — not a separate `snapshot.py`. The two
   reads, `read_blocks`/`read_snapshot`, and the dataclasses (`Snapshot`,
   `Character`, `Effect`, `ClassProgress`) are there, with no Qt. Tested
   headless against captured bytes and against `PORSAVE11.D64` read straight
   off a disk (`test_the_party_reads_the_same_live_as_it_does_off_the_disk`,
   `tests/test_automap.py`).
2. ~~The experience table~~ **Done, a different way.** `work/goldbox-research/por_xp_tables.txt`
   is gone; the table came instead from `goldbox/levels.py`, generated into
   [`89-level-tables.md`](89-level-tables.md) and verified against the game
   rather than transcribed. `automap/live.py` already draws the experience bar
   from `levels.progress()`.
3. **The hit point bar, the experience bar and the per-character effects are
   all done** — `automap/panel.py`'s `CharacterCard.show_character`, `Bar` and
   `hp_colour`, and a row of condition badges beside the readied line. Donald
   chose the glyphs on `#4 (Condition badges on the roster card)` and the last
   two on `#142 (The party effects line is computed every poll and shown
   nowhere)`; which effect ids each badge covers, and how each glyph survives
   13 px, is [`136-condition-badges.md`](136-condition-badges.md).
4. **Built, folded into the bottom strip rather than a separate panel — lost,
   and rebuilt as icons.** `BottomStrip.show_effects` (`automap/panel.py`)
   draws **one icon row for the whole roster** above the square and the area
   name, with each spell's name in the row's tooltip. Monster effects are
   counted in that tooltip rather than listed, deliberately: a monster's
   effects belong to whatever is being fought, and the combat view is where
   they will mean something.

   **It reached nothing at all for months.** It was a `QLabel` called
   `strip_effects`, removed from `wish/window.ui` in the UI redesign
   (`72ee9a9`), so `findChild` returned `None` and the `if self.effects is not
   None:` guard discarded the line in silence, five times a second. Donald
   settled the shape it came back in on `#142 (The party effects line is
   computed every poll and shown nowhere)`: one row of icons rather than eight
   cards each holding a mostly-blank line. `automap/panel.py`'s `child()` now
   names any widget the form does not have, in the debug log, so the same thing
   cannot happen quietly again.
5. **Where is done**, in the same strip. **The loaded-files list was built
   collapsed, then taken back out.** `BottomStrip.__init__`'s comment says
   why: a reverse-engineering number in a window somebody is playing a game in
   was the wrong thing to show a player. It goes to the debug log now, and
   only when it changes.

---

## Verification

* `automap/live.py` against `PORSAVE11.D64`'s bytes gives six characters with
  ROLAND at 5 of 7 and wounded —
  `test_the_party_reads_the_same_live_as_it_does_off_the_disk`
  (`tests/test_automap.py`).
* Against `PORSAVE13.D64`, the area reads `GEO14`, the Slums — proven on the
  decode path `live.py` reuses unchanged rather than through the live reader
  itself: `test_the_boundary_pair_settles_the_area_byte`
  (`tests/test_savegame.py`), PORSAVE12 and PORSAVE13 either side of the
  doorway.
* A snapshot of all zeros is rejected — `test_a_machine_full_of_zeros_is_not_a_party`.
* Switching away from the tab stops the polling —
  `test_only_the_visible_tab_is_read` and `test_a_hidden_map_tab_reads_nothing`
  (`tests/test_wish.py`).
* With the effects arrays zeroed, `BottomStrip.show_state` sets the text to
  "none" — but no test asserts it.
  `test_the_strip_says_when_the_party_is_not_readable` never reads
  `.effects.text()` despite its name, and is worth a look.
* A hit point bar at 5 of 7 is coloured as hurt, and a full one is not —
  `test_a_wounded_character_is_coloured_and_a_whole_one_is_not`, which cites
  this page's own example.
* The experience bar draws from `goldbox/levels.py`, checked against
  twenty-nine level-ups driven through the training school and read off the
  record before and after each one — `tests/test_levels.py`.
* Not verified, because neither is buildable yet: an empty per-character
  effects strip that leaves no gap in the layout, and a live spell's duration
  counting down to a row that disappears on expiry. Nothing renders a
  per-character effect anywhere today (item 3 above), so there is no strip and
  no row for either to be true of.
