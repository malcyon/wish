# Acting on the running game

**Status: built and wired.** `automap/actions.py` is the engine, driven by
`tests/test_actions.py` against `MemoryTarget`; `automap/actionbar.py` is the
row of buttons under the map on the automapper tab.

Everything here writes to a running machine. Reading is safe and reversible;
writing is neither, so each action states **when it is legal** as well as what
it does. `automap/target.py` carries `write`, so the Commodore 64 Ultimate
backend inherits all of it, and the loader's mode flag is what decides
legality — `2` is combat, at `$6E11` in Pool of Radiance and `$7F11` in Curse
and Silver Blades.

**Nothing here writes to a disk.** These change the machine's memory, and the
player saves in the game as usual. That keeps the losslessness promise intact:
`wish` still never writes a save file except through the editor's own save path.

## Which title, and the one address that stops it (#29)

**Every address an action writes comes from the `goldbox.games.Game` descriptor.**
The slot area, the item area and the roster page are payload offsets that are
identical in all six titles, so they follow `save_load_address` and nothing
here is a constant: Pool of Radiance's `$4D00`/`$5900`/`$8300` are Curse's
`$4F00`/`$5B00`/`$6700`, and a new title costs a table row. `read_party` takes
the descriptor and reads through the same `live.read_blocks` the roster cards
use, so the write side and the read side cannot come to disagree about where a
title lives.

**The mode flag is the exception, and it is read out of each title's loader.**
It is a byte of `LINKER`'s own resident page rather than of the save image, so
it neither follows the load address nor transfers: `$6E11` in Pool of Radiance,
`$7F11` in Curse and Silver Blades, `+$1100` where the save image moved
`+$200`. `LINKER`'s first instruction names it — `LDA $7F11` on both later
titles' disks — and its overlay name table is the same table entry for entry,
so `2` is COMBAT in all three and only the address is per title.

It is `Game.mode_flag` — CONFIRMED for Pool of Radiance, Curse and Silver
Blades, None for the three Krynn-era titles, whose loaders have not been read.
Silver Blades has been watched through a real fight: `1` `DUNGEON` → `4`
`COM.PREP` → `2` `COMBAT`, with the three combat-illegal actions refusing on
the `2`. An action whose title has None **refuses**, with the reason in its
tooltip and in the `Outcome`: reading Pool of Radiance's byte on a Curse
machine would answer "not combat" whatever the game was doing, which is a gate
that is open rather than a gate that is missing.

What would lift the remaining three, per title: read `LINKER` off the disk and
take the operand of its first instruction. `docs/50-experiments.md`, "the later
titles' mode flag is `$7F11`".

---

## What an action is

| member | what it is for |
|---|---|
| `name` | stable identifier, for settings and wiring |
| `label` | the button's text |
| `description` | one line, for the tooltip |
| `confirm` | non-empty means ask this first; there is no in-game undo |
| `legality(target)` | a `Verdict` — `ok`, and the reason when it is not |
| `apply(target, **kw)` | re-checks legality, then writes; returns an `Outcome` |

`Outcome` carries every `(address, bytes)` that went to the machine and a list
of `notes` — what was deliberately left alone, and why. "Did nothing" and "did
nothing to *this one*, and here is why" are different answers.

**`apply` re-checks legality itself**, and not only for tidiness: a button's
enabled state is a poll interval stale, and a fight can start inside that
interval.

`actions()` returns the whole set, **in the order the bar reads**, and
`actionbar.COLUMNS = 3` breaks that into rows. Donald chose the grouping:

| row | buttons |
|---|---|
| first | Heal the party · Store memorized spells · Restore memorized spells |
| second | Identify all items · Turn quickfight off |

The three that are about spells and hit points sit together; the two that stand
alone sit under them. `Fast Travel` is its own row (`WarpBar`) and levelling is
on the roster card, so neither is in this grid.
`test_the_buttons_are_laid_out_in_the_two_rows_donald_asked_for` pins it.

**The labels are American: "memorized".** The internal names
(`store-spells`, `restore-spells`), the methods, and the record field
`spells_memorised` are unchanged — that field name reaches generated docs and
saved YAML that has to keep loading.

---

## The actions

### 1. Heal the whole party — `heal`

Current hit points to maximum, written to the roster block at
`$8300 + slot * $20`, byte `+0x19`. Current hit points are not in the stored 256
bytes of a record — `0x119` is export-only — so the roster is the only copy a
running game has.

**Legal anywhere**, including mid-fight.

**Confirmed live.** Four wounded characters healed at the party menu and the
game's own list redrew as 11 9 9 7 5 4 against maxima of 11 9 9 7 5 4; SILAS
went 8 → 9 mid-fight at `$6E11 = 2`. See
[the experiments log](50-experiments.md).

**A character at zero is skipped.** Zero is dead or dying and whatever else
marks that is not decoded, so raising the byte alone would be the half-write
levelling refuses over. The outcome says whom it skipped.

### 2. Store and restore memorized spells — `store-spells`, `restore-spells`

`store-spells` remembers record `0x020`, the sixteen-byte packed list, for
every character; `restore-spells` writes it back to
`$4D00 + slot * $100 + 0x20`.

The store is `SpellStore`: JSON under the config directory, keyed by save disk
and character name, so it survives closing the window. An unreadable file is
treated as empty rather than as an error.

Only the memorised list moves. The capacity at `0x0EE` says how many spells of
each level a character *may* prepare and does not change with resting.

**Both illegal in combat.** A list captured mid-fight is a list with the
fight's casting already spent, which is not what anybody means by "store my
spells".

### 3. Identify every item — `identify`

Clears the low three bits of each item's byte `+6`, which hide its name words
until it is identified. Bit 7 is readied and is never touched.

**Illegal in combat**, and it carries a `confirm`: identification is part of the
game's economy and there is no in-game way to undo it.

**The write may not stick.** `$5900`+ is a copy fed from a master elsewhere —
poking an item's weight there was reverted by the game — so this is the one
action whose effect is worth checking in the game's own item list. Not yet
tested live: the party on the test disk carried no unidentified item.

### 4. Turn quickfight off — `clear-quickfight`

**The bit is found**: roster block `+0x0C`, bit 7. QUICK on the combat menu
moved exactly that bit for exactly the character quickfought, and it survives a
fight onto the disk — eight of the player's own saves carry it set for one
character.

**The roster card shows who is on it.** `live.Character.quickfight` reads the
same byte and the same mask — `live.ROSTER_QUICKFIGHT` and
`live.QUICKFIGHT_BIT`, which `QUICKFIGHT` is built from, so the read side and
the write side cannot drift — and the card draws `person-running` under the
readied line. See [the roster](107-roster-and-notes.md).

**Legal anywhere**, and `QuickfightWatcher` will clear it on the tick `$6E11`
leaves 2, if the caller turns that on. It fires on the edge only, so it does
not fight a player who turns quickfight on deliberately in the *next* fight.

**Its effect is unproven.** Setting the bit out of band did not take a
character away from the player, so it may mark "the computer is playing this
character's action" rather than a sticky quickfight. Clearing it restores the
byte every clean save has, so the write cannot hurt; whether it *helps* waits
on the experiment in [fields wanted](80-fields-wanted.md).

### 5. Level up without the training hall — `level-up`

**It writes what the training hall writes.** `GEN $1B8C` is the sequence a
level-up runs; every routine it calls has been read, and `goldbox/levelup.py` names
each one beside the field it fills — see [levelling](135-levelling.md).
Replaying the twenty-nine trainings measured in [`119`](119-test-party.md)
through it reproduces the game's own record **byte for byte** on all thirty-four
before/after pairs, given the hit die it rolled.

**The button is in the roster, not on this bar.** One per character card, at
the right end of the class-and-level line, hidden unless that character has the
experience for another level. The card is which character it means.

**Pool of Radiance only.** `GEN` is a different build in every title and none of
Pool of Radiance's addresses survives into Curse's, so `level_up_blockers`
refuses any other title by name and the button is not drawn at all —
[levelling](135-levelling.md), "One title, and it says so".

**It does not ask which class.** A multi-class character with two ready gets
the one whose threshold *after* the level it is about to gain is largest —
`goldbox.levelup.best_next_class`, ties broken in class-bit order. That is the
number the trainer's experience clamp reads, so it leaves the ceiling as high
as it goes and the other class usually still qualified; pressing again takes
it. The outcome names the class raised — `LADY KATHERINE is a magic-user 2` —
because it is the only place the choice is now visible. Where the clamp would
still cost a class a level it had already earned, `Plan.classes_disqualified`
is non-empty and the window asks first; otherwise nothing is asked.

| what | how |
|---|---|
| `hp_rolled` | one roll of the class hit die — the one field nothing derives, so the outcome reports the number |
| `hp_max` | `hp_rolled + level x constitution bonus`, recomputed |
| saving throws | a level-1 row cut by two per-column bitmasks, then `constitution * 2 / 7` for a dwarf, gnome or halfling |
| `spells_castable` | the class table plus the wisdom bonus, cleric in the high nibble |
| thief skills | the level row plus the racial row, and no ability score |
| which class | `best_next_class`, not the player: highest post-level threshold. `class_for(record)` is the answer, and an explicit `class_name` still overrides |
| a magic-user's new spell | **chosen**, from `offers(record)`. The action refuses without one rather than picking. Asked *after* the class, since only then is it known whether it is needed |

`level_up_blockers()` survives as the gate: any field it writes that is not
CONFIRMED in `goldbox/layout.py` stops the action dead. It is empty today, and it
got there by measurement rather than by lowering the bar.

**No money moves.** The trainer charges 1000 gold at every level and converts
the rest of the coin to platinum; that is what a school costs rather than what
a level costs, so none of the seven coin fields is written, and neither is
movement. **Healing is done**, because the trainer does it: current hit points
end at the *new* maximum, after the die has been rolled. A character at 0 is
refused rather than healed, for the reason `HealParty` gives.

---

## The buttons

Nothing in `automap/actions.py` imports Qt. `automap/actionbar.py` is the Qt
half: `ActionBar` builds one button per action, in three columns so the block is
no wider than the map above it, with the watcher's checkbox beneath. The window
calls `attach(target)` on each live poll, which is

```python
verdict = action.legality(target)
button.setEnabled(verdict.ok)
button.setToolTip(verdict.reason or action.description)
```

`run` asks `action.confirm` first where it is non-empty — identify and level-up
are the two that carry one — calls `action.apply(target, disk=...)`, and reports
`outcome.message` **into the messages panel**, with `outcome.notes` as its
tooltip and the same line under the buttons.

**No pop-up for a result.** What an action did is what the player asked for; a
modal box in front of the map interrupts the game in the other window and has to
be dismissed before the map is usable again. The only dialog left is the
confirmation an irreversible action asks first, because that one needs an
answer.

With no target attached every `legality` is False with a reason, so the buttons
are disabled rather than merely inert.

**One read, not six.** Every `legality` asks the machine for the mode flag, and six
round trips is six times ~14.3 ms of extra emulated time, so `refresh` hands the
actions a wrapper that reads each address once —
`test_the_whole_row_costs_one_read_of_the_mode_flag`.

`QuickfightWatcher` is a checkbox on the same row, off by default and fed from
the same poll: it writes to a running machine on an edge nobody asked for
otherwise.

---

## Verification

* Each action's effect is visible in the game's own display without reloading —
  **done for `heal`**, and the party list is where it shows.
* Each action refuses in combat where it should, and says why — tested.
* A save taken after an action loads clean, and `wish export` on it
  round-trips byte-identical — **not yet run**.
* With no emulator attached the buttons are disabled, not merely inert.
