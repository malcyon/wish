# Acting on the running game — plan

**Status: planned, not started.** Buttons on the Automapper tab that change the
live game's state, modelled on Gold Box Companion.

Everything here writes to a running machine. Reading is safe and reversible;
writing is neither, so each action below states **when it is legal** as well as
what it does. `automap/target.py` already carries `write`, and the mode flag at
`$6E11` is what decides legality — `2` is combat.

---

## The actions

### 1. Heal the whole party

Set each party member's current hit points to their maximum. Current HP is not
in the saved 256 bytes of a record, so this is a live-only write; the address is
the roster block, not the record.

**Legal anywhere.** Healing mid-fight is a cheat rather than a corruption
risk — the game recomputes nothing that would notice.

**Research needed:** which byte the game actually reads for current hit points
during combat, and whether writing it mid-round survives the round's own
bookkeeping. `docs/100-live-view.md` has the roster layout.

### 2. Store and restore memorised spells

One button stores the memorised list for every party member; another writes it
back. This is the one people ask for most: resting to re-memorise is the game's
slowest loop.

**Illegal in combat.** Refuse while `$6E11` is 2, and say so.

The spell fields are already decoded — record `0x0EE`–`0x0F3` is the castable
count nibble-packed, and `editor/spellwidget.py` reads and writes the spellbook
and the memorised list. The store is a file under the config directory, keyed
by character name and save disk, so it survives closing the window.

**Open question:** whether writing the memorised list live is enough, or whether
the game caches a derived per-round list that also needs poking.

### 3. Turn quickfight off after a fight

Depends on **finding the quickfight flag** — see `docs/80-fields-wanted.md`.

Once found, this is a checkbox rather than a button: watch `$6E11`, and when it
leaves 2, clear the flag for every party member. The point is that the game does
not clear it itself, so the next fight — possibly a dangerous one — starts with
characters the player does not control.

### 4. Level up without the training hall

Raise a character's level, hit dice and derived combat numbers to what
`por/levels.py` says the next level gives, without walking to a trainer.

**Illegal in combat.**

The level tables are already verified against real records, so the numbers are
known. What is *not* known is everything the trainer touches besides them: the
score-altered bit at `0x0B8` is one candidate, and the experiment in
`docs/80-fields-wanted.md` on ability-score changes at the trainer should land
first, because it answers the same question from the other side.

**This is the riskiest action here.** A half-levelled character is a corrupt
character. It should refuse rather than guess whenever a field it would write is
not CONFIRMED.

### 5. Identify every item

Set the identified bit on all items in the party's possession. Item byte
semantics are decoded — `por/items.py` — and the editor already toggles this
per item.

**Illegal in combat**, and worth a confirmation: identification is part of the
game's economy, and unlike healing there is no in-game way to undo it.

---

## Shape

A row of buttons under the map, disabled with a reason in their tooltip when
the mode flag says the action is illegal. No dialogs for the reversible ones;
one confirmation for levelling and for identify-all.

Every write goes through `Target.write`, so the Commodore 64 Ultimate backend
inherits all of it.

**Nothing here writes to a disk.** These change the machine's memory, and the
player saves in the game as usual. That keeps the losslessness promise intact:
`wish` still never writes a save file except through the editor's own save path.

## Order of work

1. Heal, which is the simplest write and proves the path.
2. Identify all.
3. Store and restore spells.
4. Quickfight, once the flag is found.
5. Levelling, last, and only on CONFIRMED fields.

## Verification

* Each action's effect is visible in the game's own display without reloading.
* Each action refuses in combat where it should, and says why.
* A save taken after an action loads clean, and `wish-cli --export` on it
  round-trips byte-identical.
* With no emulator attached the buttons are disabled, not merely inert.
