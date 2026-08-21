# A commissions panel

**Status: the reading half is built.** A quest log on the Automapper tab:
what the City Council has asked the party to do, and what it has already paid
for. `por/commissions.py` decodes it, `automap/commissions.py` draws it, and
`tests/test_commissions.py` holds the verification below. It is **not wired
into `automap/window.py`** yet -- that is the one step left.

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

## Where the code is

`por/commissions.py`, promoted out of `work/analysis4/commissions.py`: the 26
ledger names and the script that finishes each, the three states, `$4AC1`, the
`ECL08 $A84D` offer loop, and the eight appointment flags. `read(source)`
returns the lot; `summary_lines(source)` is the same thing as text, for the
CLI. `source` is the 224 flags, the `$4A00` page, a whole `SAVEDGAME0` payload
or a `SaveGame0` — the lengths are distinct, so no flag is needed. No Qt.

`automap/commissions.py` is the panel: `CommissionsPanel()`, one entry point
`update_from(source)` taking exactly what the decoder takes, and
`set_message(text)` for when there are no bytes. It redraws only when the flag
block changes, and holds nothing that can be typed into.

**Wiring, still to do** — in `automap/window.py`: build a `CommissionsPanel()`
beside `RosterPanel`, and in `poll_live` call `update_from(save0_bytes)` with
the block `read_blocks` already fetches (`Snapshot` does not keep the raw bytes,
so either widen it or hand the panel the bytes directly). On a poll that
returns nothing, leave the panel alone — plot flags do not change while the
game is in a menu.

## Verification — done, in `tests/test_commissions.py`

* The shipped unplayed `POOL1` save shows nothing done and offers exactly
  slums, Sokal Keep, and books.
* `work/fields/npc_party.d64` reads `$4AC1` = 6, ledger 0, 1, 2, 4-9, 10, 12,
  13, 20, 21 paid — six of them the major ones, which is what `$4AC1` counts —
  and offers nomads, kobolds, lizardmen.
* Every offer on the board settles a ledger index the clerk's speech table
  names; the withdrawn candidate settles nothing and is never offered.
* Reading is pure: the decoder copies its input, and the specimen save's bytes
  are identical after the panel has drawn them.
