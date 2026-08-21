# Acting on the running game

**Status: built and wired.** `automap/actions.py` is the engine, driven by
`tests/test_actions.py` against `MemoryTarget`; `automap/actionbar.py` is the
row of buttons under the map on the automapper tab.

Everything here writes to a running machine. Reading is safe and reversible;
writing is neither, so each action states **when it is legal** as well as what
it does. `automap/target.py` carries `write`, so the Commodore 64 Ultimate
backend inherits all of it, and the mode flag at `$6E11` is what decides
legality — `2` is combat.

**Nothing here writes to a disk.** These change the machine's memory, and the
player saves in the game as usual. That keeps the losslessness promise intact:
`wish` still never writes a save file except through the editor's own save path.

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

`actions()` returns the whole set, in build order.

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

### 2. Identify every item — `identify`

Clears the low three bits of each item's byte `+6`, which hide its name words
until it is identified. Bit 7 is readied and is never touched.

**Illegal in combat**, and it carries a `confirm`: identification is part of the
game's economy and there is no in-game way to undo it.

**The write may not stick.** `$5900`+ is a copy fed from a master elsewhere —
poking an item's weight there was reverted by the game — so this is the one
action whose effect is worth checking in the game's own item list. Not yet
tested live: the party on the test disk carried no unidentified item.

### 3. Store and restore memorised spells — `store-spells`, `restore-spells`

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

### 4. Turn quickfight off — `clear-quickfight`

**The bit is found**: roster block `+0x0C`, bit 7. QUICK on the combat menu
moved exactly that bit for exactly the character quickfought, and it survives a
fight onto the disk — eight of the player's own saves carry it set for one
character.

**Legal anywhere**, and `QuickfightWatcher` will clear it on the tick `$6E11`
leaves 2, if the caller turns that on. It fires on the edge only, so it does
not fight a player who turns quickfight on deliberately in the *next* fight.

**Its effect is unproven.** Setting the bit out of band did not take a
character away from the player, so it may mark "the computer is playing this
character's action" rather than a sticky quickfight. Clearing it restores the
byte every clean save has, so the write cannot hurt; whether it *helps* waits
on the experiment in [fields wanted](80-fields-wanted.md).

### 5. Level up without the training hall — `level-up`

**It refuses, and that is the implementation.** The tables in `por/levels.py`
are verified and they answer for six fields; the trainer touches more than six.

| field | why it cannot be written |
|---|---|
| `hp_max` | the trainer rolls a hit die and adds the constitution bonus; the table's `hp_max` is the maximum roll |
| `hp_rolled` | `0x0ED` moves with it and nothing derives one from the other |
| saving throws | `por/levels.py` carries a *base* table and says so — two characters of the same class and level store different saves, so the record holds modifiers nobody has measured |
| `spells_castable` | `0x0EE` is nibble-packed capacity including a wisdom bonus that has never been checked against a record |
| thief skills | there is no per-level thief skill table in the project at all |

On top of that, none of the six fields it *could* write is CONFIRMED, and what
else the trainer touches is unmeasured — see
[fields wanted](80-fields-wanted.md).

`level_up_blockers()` is that list, as data. It empties itself as
`por/layout.py` promotes fields, so this becomes an action by making the fields
CONFIRMED rather than by editing the action.

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

**One read, not six.** Every `legality` asks the machine for `$6E11`, and six
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
* A save taken after an action loads clean, and `wish-cli --export` on it
  round-trips byte-identical — **not yet run**.
* With no emulator attached the buttons are disabled, not merely inert.
