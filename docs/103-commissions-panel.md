# A commissions panel — plan

**Status: planned, not started.** A quest log on the Automapper tab: what the
City Council has asked the party to do, and what it has already paid for.

The research is done and is in `work/reports/quest-flags.md`. Four lines are
CONFIRMED and buildable from 224 bytes that are already inside `SAVEDGAME0`, so
this needs no new decoding — only a panel.

---

## What can be shown, and how sure we are

| line | where | confidence |
|---|---|---|
| commissions completed | `$4AC1` | CONFIRMED |
| the ledger: not done / reward waiting / paid | `$4AA6 + i`, i = 0..25 | CONFIRMED |
| what the clerk would offer next | `ECL08 $A84D`, re-implemented | CONFIRMED |
| outstanding "summoned to X" appointments | `$4A97`-`$4A9B`, `$4A8C`, `$4A96`, `$4AC2` | CONFIRMED |
| graveyard undead killed, and paid for | `$4A39`-`$4A3F`, `$4A8F`-`$4A95` | PROBABLE |
| slum progress, N of 25 | `$4ABB` | PROBABLE |

The ledger index **is** the quest: each has the clerk's own speech in a 26-entry
jump table, so 1 is Sokal Keep, 11 the graveyard, 20 Tyranthraxus, 25 Cadorna.
`work/analysis4/commissions.py` already names all 26 and reproduces the offer
loop; run against the shipped unplayed save it emits *slums, Sokal Keep, books*,
which is what the game really opens with.

**Not ready, and should not be shown:** per-area sub-bits outside the named
ones, and anything above `$4AFF` — no ECL operand reaches there, so
`docs/41-memory-regions.md`'s `$4A20`-`$4B7F` range is unverified above `$4AFF`.

---

## Shape

A collapsible panel beside the map, in the bottom strip with the rest of the
live data. Three groups:

* **Available** — what the clerk would offer on the next visit.
* **In progress** — accepted, not yet done.
* **Done** — split into *reward waiting* and *paid*, because the difference is
  money the party has not collected.

Sorted by ledger index, which is roughly the plot's own order.

Each row is the quest's name and its state. **Nothing here is editable.** It is
a display, and making it writable would mean writing plot flags, which is a much
larger promise than reading them.

## Where the code goes

`por/commissions.py`, promoted out of `work/analysis4/commissions.py`: the
ledger names, the offer loop, and a function from 224 bytes to a list of rows.
No Qt, so it is testable headless and works from a save file as well as from a
live machine — which also means the CLI can print it.

The panel itself goes in `automap/`, reading through the existing `Target`.

## Verification

* The shipped unplayed `POOL1` save shows nothing done and offers exactly
  slums, Sokal Keep, and books.
* A far-advanced save shows a coherent late-game state.
* Every offered quest is one the clerk's own speech table names.
* Reading is pure: with the panel open, a save taken afterwards is
  byte-identical to one taken before.
