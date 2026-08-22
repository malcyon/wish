# Editing effects

A plan, not a record of work. Nothing below is built.

## The finding that reframes it

Until 2026-08-22 the sheet's `Active effects` box was believed to be the active
effects. It is not. `P3-EFFECTS.D64` was saved with twenty-six spells running
and **every character's ten slots at `0x0AD` came out exactly as they went in**
— elf seed 107, half-elf seed 124, nothing else ([the saves we made
ourselves](90-specimens.md)).

So there are two lists, and they share one code namespace:

| | where | how many | scope | what puts a code there |
|---|---|---|---|---|
| **traits** | record `0x0AD`–`0x0B6` | 10 per character | one character | `GEN $0BF3` at creation, `SPELLE04 $ADD4` for a passive item, a monster's own record |
| **active effects** | `SAVEDGAME0` `$4900` id, `$4940` owner, `$4980` duration, `$4B80` magnitude | 64 for the whole save | a character, a monster, or the party | a cast spell, a monster's attack |

`LIBRARY $4028` reads the arrays first and falls back to the character's own
slots, which is why one table names both. A code in the arrays is therefore
evidence about `por/traits.py` and vice versa.

**The editor already holds both.** `party.save0` is the whole `$4900`–`$64FF`
image and `store_save` writes it back, so neither list needs new I/O.

## What to build

**Two panels, never one.** Merging them would hide the only thing that matters
about the pair — a trait has no duration and never expires, an effect does and
does.

* **`Traits`** — the box now titled `Active effects`. Ten rows, per character,
  editable in place. Rename the box: the title is a refuted claim, and
  `por/layout.py`'s label for `item_effects` should move with it.
* **`Active effects`** — new, and it belongs to the *save*, not to the selected
  character, so it goes beside the roster rather than in the character sheet.
  One row per non-zero id, showing who it is on and how much is left. Absent
  for a `.chr` export, which has no `SAVEDGAME0`.

Both lists show a name, never a number. A code nobody has named already falls
back to `trait <n>`; keep that and nothing else numeric on the face of the
sheet.

## What the user picks from

One list of 129 names, filtered as you type, in two labelled sections:

```
Seen in this game          Bless
                           Detect Magic
                           Enlarge
                           ...
From the DOS table         Animate Dead
                           Bestow Curse
                           ...
```

That is the honest treatment of a PROBABLE name and it never says PROBABLE. The
section heading is a **provenance** statement — where the name came from — which
a player can read and act on, rather than a confidence grade, which they cannot.
The second section is not hidden and not greyed: 62 of the names are there and
several are the ones somebody would most want.

The number appears in exactly two places: in a row's tooltip, and as the whole
of the name when there is no name. `describe()` already does the second.

**Prerequisite.** `por/traits.py` still marks the seventeen codes that
`docs/90-specimens.md` promoted this afternoon as PROBABLE, and
`tests/test_corrections.py` asserts `CONFIRMED == 49`. Promote the seventeen and
move that number in the same commit, before the picker exists — otherwise the
first section is wrong by seventeen entries on the day it ships.

## Adding, and running out of room

**Traits.** Add writes the picked code into the lowest zero slot and compacts:
every block on the disks is contiguous from slot 0, and the one non-zero tail
value ever observed is the fill 255, always in slot 9. Three overlays scan all
ten, so a hole is probably harmless — compacting anyway costs nothing and keeps
the block the shape the game writes.

With all ten full, **do not** silently drop one and do not offer an eleventh.
Disable Add and let the row's Remove be the way through; ten is a real ceiling
and the ten visible rows are already what says so. A player carrying ten is
carrying eight they did not put there, which is itself worth seeing.

**Active effects.** 64 slots, party-wide, and no save we hold uses more than 23.
Running out is not a case to design for; if it happens, the same rule.

**Remove clears all four arrays**, not just the id. The game clears only the id
(`CAMP $131F`, [N7](125-bug-notes.md)) and leaves owner, duration and magnitude
behind as residue that once looked like a refutation of the whole decode. Id
zero is what everything tests, so clearing the other three is safe and strictly
tidier than what the game does.

## Duration and magnitude

**Not editable in the first cut, and offered as a number never.**

The duration byte is a count in bits 0–5 and a **unit in bits 6–7 that is not
decoded**. A spinner labelled "duration" over a unit nobody can name is the
worst kind of control: it looks authoritative and means nothing. A raw
`0`–`255` box with a note explaining the packing is the help text this project
just spent an afternoon deleting.

Instead: a new effect gets **the duration and magnitude the game itself wrote
for that id**, harvested from `P3-EFFECTS.D64` into a small table in
`por/effects.py`, and the row shows what that came to in the game's own terms —
the count, and the unit spelled as whatever the decode eventually calls it. An
id we have never seen the game write gets the modal duration of its neighbours
and is marked the way an unnamed code is marked.

The second cut, once bits 6–7 are decoded, turns that into `lasts: 8 turns`
with a spinner behind it. Decoding it is one experiment: cast one spell,
`SAVE GAME`, camp a known interval, save again, and difference the array.

## Which writes are safe

`docs/95-wish-cli.md` divides `wish`'s writes into five confirmed in play and
everything else. **Effects are in the second group and so are traits.** Nothing
in either list has been written back, booted and seen.

Two facts do carry over:

* `0x0AD` is below `0x100`, so a trait edit **reaches a save slot** — unlike the
  fields past `0x100` that only exist in a `.chr`.
* The effect arrays are inside `SAVEDGAME0`, which the game reloads verbatim;
  there is no checksum anywhere in it ([the save layout](30-savegame-layout.md)).

The bar before this ships as anything but a preview is one experiment, on a
throwaway party, and it answers both halves at once:

1. write **1 Bless** into a free effect slot, owner = character 0, duration and
   magnitude copied from the `P3-EFFECTS.D64` observation;
2. boot, look at the character, confirm the game shows it;
3. camp past the duration and confirm it **expires** rather than sticking.

A trait needs its own run and its own question, because a trait has no duration:
write **20 Resist Fire** into a free slot at `0x0AD` and confirm the game
applies it and never takes it away. That is the whole difference between the two
lists, demonstrated.

## What a nonsense combination could do

The editor refuses nothing — the spellbook precedent — but it should know what
it is not refusing.

| written | what could happen |
|---|---|
| a monster's code on a player: 83 petrifying gaze, 121 acid squirt, 81 dragon fear | the handler reads fields a monster's record carries and a player's does not — attack forms at `0x0D9` are `02 00 01 00 02 00 00 00` in every player character. Garbage attack at best |
| 63, or 54 | `por/traits.py` records both as having no handler. A dispatch with no entry is how a jump through an unset vector happens |
| 92 | the DOS table calls this id unused and TYRANITHRAXUS carries it. Nobody knows what runs |
| 255 anywhere but slot 9 | fill, in every one of the 38 records that carry it. A real code after it has never been observed and the reader may stop there |
| the same id in two slots | applied twice, or expired once. Untested either way |
| a spell effect in a **trait** slot | it never expires, because a trait slot has no duration and `LIBRARY $4028` falls back to it. A permanent 39 Haste is the interesting case: AD&D ages the hasted character, and nothing will ever remove it |
| an owner byte naming an empty party slot, or a monster that is not in the fight | the effect belongs to nobody. `active_effects` filters on the id, so it stays in the list forever |

Show these the way an unknown spell is shown — coloured, with the reason in the
tooltip — and write the bytes anyway.

## Where the code goes

The four addresses, the `Effect` record, the owner encoding and the duration
packing live in the live-map package today. `editor/` may not import that
package and `tests/test_wish.py` enforces it by grepping the source, so the
decode moves down to **`por/effects.py`** — no Qt, no I/O — and both packages
import it from there. Same argument that put `por/traits.py` in `por/`: one
table cannot be allowed to become two.

While moving it, fix what it says. Its `conditions` docstring and
`docs/107-roster-and-notes.md` both state that the effect ids are a different
code space from `por/traits.py` and that nothing maps one onto the other. Today
settled that: it is one namespace, so the poisoned and paralysed icons the live
view has been withholding are now nameable.

## Files

| file | what changes |
|---|---|
| `por/traits.py` | promote the seventeen; `tests/test_corrections.py` moves with it |
| `por/effects.py` | new — the four arrays, the `Effect` record, the observed durations |
| `editor/effects.py` | the trait table becomes editable; a picker dialog |
| `editor/character.ui` | `Active effects` → `Traits`; the new panel beside the roster |
| `por/layout.py` | the `item_effects` label follows the box title; regenerate `docs/20-character-record.md` |
| `tests/test_editor.py` | the picker, the full-block case, and that a hidden panel writes back untouched |
