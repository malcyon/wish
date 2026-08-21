# A commissions panel

**Status: built and wired.** A quest log on the Automapper tab: what the City
Council has asked the party to do, and what it has already paid for.
`por/commissions.py` decodes it, `automap/commissions.py` draws it, it sits in
the right-hand column of the map tab under the notes, and
`tests/test_commissions.py` holds the verification below.

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

## The offer and the ledger entry are the same byte

Playing the slums, the panel showed *clear the slums* under **Available** and
*slums cleared* under **In progress** at the same time, which reads as two
commissions. It is one byte.

`ECL08`'s board gates candidate 0 on `$4AA6 + 21 != 255`, and `$4AA6 + 21` **is**
the ledger entry the clerk pays for. The two halves of the panel were showing
the same flag from two ends: the board's imperative on the way in, and the
clerk's own speech -- which is phrased as the finished state, "slums cleared" --
on the way out.

The byte's four states, from `por/commissions.py`:

| value | what it means |
|---|---|
| 0 | untouched |
| 1-253 | an area script's own marker. For the slums it counted 3, and `$4ABB` -- documented as "slum progress, N of 25" -- read 3 at the same moment, so the two count the same thing |
| 254 | done; the reward is still at the City Hall |
| 255 | paid |

**It is not one-to-one in either direction**, which is why the panel does not
collapse the two into a single "quest" row:

* offer 2, *bring back books, maps and tomes*, settles **six** ledger entries
  (4-9);
* offer 4, *see Councilman Cadorna*, is gated on `$4A97` and `$4ABE` as well as
  ledger 18, and offer 13 has two separate routes through the same test;
* offer 9 is withdrawn -- an unconditional `GOTO` past its own body -- and
  settles nothing at all;
* several ledger entries (2, 11, 24, 25) are never offered by the board.

So the data does not carry a quest-log concept. What it carries is a board of
sixteen speeches and a ledger of twenty-six bytes, related by the gates.

**What the panel does about it**, in `automap/commissions.py`:

* *Available from the clerk* keeps the board's own imperative, and each row's
  tooltip names the ledger entries that offer would settle.
* The ledger group is headed **Working towards**, not *In progress*, so a
  completion phrase under it reads as a destination rather than a claim.
* A row whose entry is also on the board right now says **on the board**, and
  its tooltip says outright that it is one commission in one state, not two.
* Every row keeps its address and raw value in the tooltip, because the value
  between 1 and 253 means whatever its own area script decided.

`test_the_commissions_panel_does_not_show_one_flag_as_two_commissions` pins it.

## Shape

A panel in the right-hand column of the map tab, between the notes list and the
messages. Three groups:

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

**Wired** in `automap/window.py`: `poll_live` reads the two blocks itself and
hands the panel the `SAVEDGAME0` bytes — `Snapshot` does not keep them — once
the snapshot has decoded. On a poll that yields nothing the panel is left
alone, because plot flags do not change while the game is in a menu and a quest
log that blanked every time somebody opened one would be a flicker.

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
