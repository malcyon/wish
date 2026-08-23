# A high-level party for automated testing — plan

**Status: the level-up specification is measured, and four of the six ceilings
the game implements are reached.** Twenty-nine trainings driven through the game's own
school, every one diffed across the 580-byte record: the tables, the rules and
the corrections are in `work/reports/p18-party.md`, and §7 below is the
summary. The party is on `work/drive/P18PARTY.D64`.

The training hall is **area 11**, which has
no map of its own: it reuses `GEO00`, so the schools are New Phlan's own
squares under a second script — `(5,0)` clerics, `(7,0)` magic users,
`(8,0)` fighters, `(9,0)` thieves, `(7,1)`/`(7,2)`/`(8,2)`/`(9,2)` the arena.
Only script ids **10** (at `(6,1)`, `(6,2)`) and **17** (at `(9,0)`) reach it,
because `ECL00`'s table sends only those to `NEWECL 11` — and a **warp cannot
be used**, because `ECL0B` dispatches on the departing square's attribute byte.
Walk in; `(9,0)` is both the shortest way in and the thieves' school.

Two practical notes the run paid for. `LOW EXPERIENCE OR WRONG CLASS` is
usually the class half: the school's filter is `$6DA8 = 0x70 | class_bit` and
the bits are `por.games.CLASS_BITS_CLASSIC` — 1 magic-user, 2 cleric, 4 thief,
**8 fighter**. And training costs gold — a flat **1000 gp at every level**,
measured across twenty-nine of them — so a generated party needs money as well
as experience.

**The generator is still not written.** The deliverable is **a generator, not a
disk** — `por/testparty.py` plus a test-time disk builder. A disk is game data
and cannot be committed; a party we can rebuild from code at any moment can.

## Why now: a correction the project cannot settle

`por/layout.py` names `0x0A3` `turn_class` at CONFIRMED, on thirteen undead
specimens that match the AD&D 1e turning table exactly. The Curse of the Azure
Bonds survey (`docs/116-second-game.md`) says `0x0A4` instead: non-zero only for
characters who *turn* undead — 6 for Curse's level-5 cleric, 1 for Pool of
Radiance's level-1 cleric ROLAND — and zero in `0x0A3` for every player
character in either game.

**Both readings are probably right, and they are not the same field.** One is
*which row of the table a creature answers to* (a monster property, which is
what all thirteen specimens are); the other is *the level a character turns at*
(a character property). `docs/60-goldbox-field-checklist.md` lists the second
separately as "Level undead — effective level for turning undead. Cheapest
isolating action: train a cleric."

**Settled, and without the undead fight.** ROLAND was trained cleric 1 to 6 in
the game's own school: `0x0A4` moved at every single level and `0x0A3` did not
move once. So `0x0A4` is the character's turning level and `0x0A3` is the
monster property `por/layout.py` documents. What `0x0A4`'s value *means* is
still open — it runs `1 2 3 5 6 7` against cleric levels 1-6, skipping 4.

The rest of the argument stands: every remaining question in
`docs/90-specimens.md`'s "still wanted" list needs a character the party does
not have, so the artefact to build is the means of making characters, not one
character.

---

## 1. The party

Six characters, at or near every ceiling the game implements. `docs/89-level-tables.md`
is the source for levels and thresholds.

| # | name | race | sex | class(es) | level(s) | XP | what a test run proves with it |
|---|---|---|---|---|---|---|---|
| 1 | WARDEN | human | F | cleric | 6 | 30,000 | the turning question, `0x0A3` vs `0x0A4`; cleric spell slots 3/3/2 **plus a WIS 18 bonus** → the high nibble of `spells_castable` at `0x0EE` above 1; the spellbook bitmask with every cleric id set |
| 2 | EMBER | human | M | magic-user | 6 | 42,000 | the top spell level the game implements (4/2/2, third-level spells); the low nibble of `0x0EE`; a spellbook that is a *subset*, which is the only thing distinguishing `0x078` from "all bits set"; THAC0 19, the class's only step |
| 3 | PILFER | halfling | M | thief | 9 | 115,000 | **the highest level anywhere in the game's tables.** Every one of the eight thief skills non-trivial and none at its level-1 value; read-languages was **−5** for a halfling at level 1, so this is the signed field crossing zero. Also the small size flag at `0x099` |
| 4 | BULWARK | human | M | fighter | 8 | 130,000 | the class ceiling: THAC0 13, hp_max 112, and **3/2 attacks**, which is the only reason to care about `0x0D9`. Carried **wounded** (hp_current < hp_max) because a wounded *export* is still wanted and settles `0x119` |
| 5 | GRIMSTONE | dwarf | M | fighter/thief | F7 / T8 | 150,000 | the specimen `docs/90-specimens.md` names as missing: **a multi-class character above level 1**, with two *different* non-zero entries in the per-class array at `0x0C9`–`0x0CC`. That is the only thing that can separate `0x0A0` ("character level") from "the single class's level". Plus `class_bits` 12, infravision 6, size small |
| 6 | ASTRA | half-elf | F | cleric/fighter/magic-user | 6 / 6 / 6 | 135,000 | the widest class bitmask the game supports (`class_bits` 11) and **the only record in which both nibbles of `0x0EE` are non-zero at once** — cleric capacity and magic-user capacity in the same byte. Also the half-elf trait seed 124 at `0x0AD` |

~~Multi-class experience divides between classes~~ — **it does not.** LADY
KATHERINE, magic-user 1 / thief 7 with 70,100 points, was offered thief 8,
whose single-class threshold is 70,001. The trainer reads the whole total
against the single-class table, so the XP column above is over-provisioned and
GRIMSTONE and ASTRA need no more than a single-class character of the same
level.

**Ability scores are high but not uniform.** All-18 is the signature of the
edited disk in `docs/90-specimens.md`, and a party that looks hacked is a party
whose every anomaly gets blamed on us. WARDEN needs WIS 18 for the bonus-slot
test and PILFER DEX 18 for the thief skills; nothing else needs to be extreme.

**Names must be A–Z and at most 20 bytes**, per the name-entry compare at
`$0C46` (`docs/70-driving-the-game.md`): any byte ≥ `$5B` is rejected. That
constrains creation in game; it costs nothing to obey when generating.

---

## 2. How the party gets built

Three routes, and the choice matters more than the party does.

| route | cost | authority | fails how |
|---|---|---|---|
| **a. generate** — build 580-byte records with `por/`, write a disk | hours | **only as good as our model** | silently. A record built wrong loads, plays, and validates our own mistake |
| **b. play** — grant XP into `0x0E8` and let the training hall level each character | a long unattended VICE run | **the game's own arithmetic** | visibly. Either the trainer levels the character or it does not |
| **c. hybrid** — do (b) once per class-level, diff the record before and after, write the generator from the diff | (b) plus a day | the diff is the specification | — |

### Recommended: (c), and the reason is the circle

Route (a) alone cannot work, and it is worth saying exactly why rather than
gesturing at it. The generator would write `hp_max`, `thac0_base`, the saving
throws and the thief skills from `por/levels.py`. A test would then read those
same bytes back through `por/layout.py` and assert they are what we wrote.
**That test passes whether or not the game agrees**, and its passing would be
recorded as evidence that the fields are understood. Half the fields a level-up
touches are currently PROBABLE, one is unmeasured and one has no table in the
project at all — so a fully generated party is a party built out of our
guesses, wearing the authority of a test fixture.

**The circle breaks at the trainer.** Experience at `0x0E8` is CONFIRMED and
three bytes wide, and `wish` can already write it into a live machine or a save
disk. So:

1. take one level-1 character of a class, on a copy of a save disk;
2. write `0x0E8` to just past the next threshold;
3. drive the party to the training hall — `docs/70-driving-the-game.md` has the
   route, `7,2` in New Phlan, and the withdrawal of the "dead end" claim;
4. save, and **diff the 580 bytes before against after**.

That diff *is* the level-up specification. It names every byte the trainer
touches, including the ones we do not know we are missing, and it costs one
scripted visit per level rather than a campaign. Repeat per class and the
generator is written from measurements. The remaining characters are then
generated, because by then generating is replaying something observed.

**What (b) alone would cost:** fighter 1→8 is seven visits, thief 1→9 eight,
and six characters is on the order of forty. Each is a scripted menu walk of a
minute or two, so a single unattended run — acceptable once, unacceptable as
the way a party is rebuilt every time the format understanding changes. Which
is precisely why the product of the exercise must be the generator.

**The order matters.** Do not build the six first and validate afterwards. The
diff comes first; the generator is written from it; the six fall out.

---

## 3. The auto-level-up debug button

**Superseded, and there is no need for a debug variant.** Reading the trainer's
own routines out of `GEN` closed every blocker; `automap.actions.LevelUp` now
writes what the training hall writes, and `por/levelup.py` reproduces the
records this section's diffs produced byte for byte. See
[`135`](135-levelling.md). The rest of this section is the reasoning that got
there and the confidence table it argued from, both of which are still worth
reading; it is no longer the plan.

**Most of it already exists and deliberately refuses.** `automap/actions.py`
carries a `LevelUp` action whose entire implementation is
`level_up_blockers()` — a list, as data, of every field it cannot derive — and
whose `run` writes nothing. That refusal is correct and **must stay**: the
shipped action becomes possible by promoting fields in `por/layout.py`, not by
editing the action.

The debug button is a **second** action beside it, not a loosening of the first.

| | `level-up` (today) | `debug-level-up` (this plan) |
|---|---|---|
| visible | always, disabled with reasons | **only in debug mode** — see `docs/118-debug-mode.md` |
| writes | nothing | every field it can, from `por/levels.py` |
| unknown fields | is the reason it refuses | written from the table and **reported as unvouched** in `outcome.notes` |
| claim | "this is what the game would do" | "this is what our tables say; the game has not agreed" |

It hangs off the debug mode in `docs/118-debug-mode.md` (being written
concurrently — do not edit that file) and appears on the existing `ActionBar`,
which already builds one button per action and asks `legality` on every poll.
`Action.confirm` is non-empty for `level-up` today; the debug one keeps a
confirmation for the same reason — there is no undo in the game.

It must also work **off a disk, not only against a running machine**: actions
already take `apply(target, disk=...)`, and building a test party is a disk
operation.

### What a level-up has to touch, and whether we can write it

| field | offset | what levelling does to it | project confidence | can we write it today? |
|---|---|---|---|---|
| `experience` | `0x0E8` | set past the threshold | **CONFIRMED** | **yes** |
| `level` | `0x0A0` | +1 | **PROBABLE** in `por/layout.py`, **CONFIRMED** in `docs/80-fields-wanted.md` — *the two disagree* | value known; the contradiction blocks |
| `level_cleric` / `_fighter` / `_magic_user` / `_thief` | `0x0C9`–`0x0CC` | +1 in the advancing class only | PROBABLE — every specimen is level 1, so "level" and "class present" are indistinguishable | value known; GRIMSTONE is what settles it |
| `thac0_base` | `0x071` | the table row, stored `60 − THAC0` | PROBABLE — matches the AD&D table on all 12 of Donald's characters | value known |
| `hp_max` | `0x076` | **+ a hit-die roll + CON bonus** | field CONFIRMED; the *roll* is not a formula | **no** — this is a die, not arithmetic |
| `hp_rolled` | `0x0ED` | + the same die | PROBABLE; nothing derives one from the other | **no** |
| `hp_current` | `0x119` | + the same delta | CONFIRMED, **export only** | follows `hp_max` |
| five saving throws | `0x09A`–`0x09E` | the table row **plus modifiers** | fields CONFIRMED; the modifiers **UNMEASURED** — two level-1 fighters store `14,15,16,17,17` and `11,12,13,14,14` | **no** |
| `spells_castable` | `0x0EE` | new capacity, nibble-packed, cleric high / magic-user low | PROBABLE, checked only at level 1 | **no** |
| `spells_known` | `0x078`–`0x07E` | a cleric gains every spell of the new level; a magic-user learns by roll | CONFIRMED, and `por/spells.spellbook_bytes` writes it | **cleric yes, magic-user no** |
| eight thief skills | `0x0A5`–`0x0AC` | the per-level table | fields CONFIRMED (and **signed**); **there is no per-level thief table in this project at all** | **no** |
| attacks per round | `0x0D9` | 1 → 3/2 at fighter 7 | CONFIRMED — `0x0D9`–`0x0E0` is `attack_forms`, count and damage per form, read on 20 creatures | **yes** |
| turning power | `0x0A4` | rises with cleric level | PROBABLE — non-zero on eight records, every one a cleric; the *value* is unexplained, as three level-5 clerics read 1, 4 and 6 | **no** |
| roster THAC0 / AC / damage bonus | `SAVEDGAME1` `+0x0E` / `+0x0F` / `+0x17` | recomputed | PROBABLE, and `por/derive.py` computes all three | **yes, derived** |

Three of those blockers are cheap to remove and one is not:

* **The thief skill table** is a transcription job, no experiment required.
* **The saving-throw modifiers** fall straight out of the trainer diff — level a
  fighter and read which five bytes move by how much.
* **`spells_castable`** likewise: WARDEN at cleric 6 with WIS 18 makes the
  wisdom bonus visible in one byte. (Note that `por/spells.py`'s `capacity()`
  docstring still says "no field holding it has been found"; `0x0EE` is that
  field, and the docstring is stale.)
* **`hp_max` is a die roll and will never be a formula.** For a *test* party
  that does not matter — pick the table maximum and record that the number is
  chosen, not derived. It matters enormously for a shipped level-up button, and
  is the honest reason `level-up` should keep refusing after `debug-level-up`
  works.

---

## 4. Where the artefact lives

**Not in the repository.** A save disk is a `.d64`, which
`tests/test_repository_contents.py` rejects outright; and a slice of one under
`tests/fixtures/` is exactly the copy the allowlist exists to catch. Do not add
to that allowlist.

Instead, three pieces:

| piece | where | why it is allowed |
|---|---|---|
| the six records | `por/testparty.py`, built at run time from `por/layout.py` and `por/levels.py` | generated from a format we documented — the same argument as `tests/gamedata.synthetic_geo` |
| the disk | `work/drive/`, built at test time | `work/` is `.gitignore`d and `CLAUDE.md` already names it as where disk images belong |
| the base disk | **the player's own**, via `tests/gamedata.save_disk("PORSAVE")` | read-only, never written, skipped when absent |

### How a VICE run gets a disk to boot

```
tests/gamedata.save_disk("PORSAVE")        # the player's; skips if absent
  shutil.copy(...)             -> work/drive/TESTPARTY.D64     # never write the original
  D64.open(copy)
    SaveGame0.from_prg(disk.read_file(b"SAVEDGAME0"))
    save0.write_record(slot, record)  x6
    roster writes into SAVEDGAME1 via por/savegame.RosterBlock
    disk.write_file_inplace(b"SAVEDGAME0", save0.to_prg())
    disk.write_file_inplace(b"SAVEDGAME1", save1.to_prg())
    disk.save(copy)
  Session(...); sess.save_disk = copy; sess.boot(); sess.load_save()
```

`write_file_inplace` refuses to change a file's block count, which is not a
limitation here: both payloads are fixed sizes (7168 and 2048) and a rewritten
save occupies exactly the chain it already had.

`tools/walkrun.py` already does the copy step — `shutil.copy(BASE_SAVE,
work/drive/SIDE0.D64)` — and `Session.attach` already refuses any path outside
`work/drive/`. Nothing new is needed to get the disk into the emulator; what is
new is what goes on it.

**The read-only rule is the same promise `wish` already makes**: the source
disk under `/home/donald/c64/Pool of Radiance Disks/` is opened and never
written, and every byte of the copy is either the player's own or generated by
us.

---

## 5. Is the party legal in the game's own eyes?

| constraint | what we believe | confidence |
|---|---|---|
| six player characters per party | the code tests `CMP #$06` against a count of bit 7 at `0x0B8` | **CONFIRMED** — the limit is in code, not anecdote |
| class ceilings: cleric 6, fighter 8, magic-user 6, thief 9 | `GEN` `$1E5C`, eight bytes in class-bit order, read by the level-up routine at `GEN` `$1E21` | **CONFIRMED** — P49. The routine takes the class index from `$2B58`, raises `$2B50,X`, `CMP $1E5C,X`, and on a value above the table clamps to it and bumps `$2B74`. The table reads `06 06 09 08 00 00 00 00` — magic-user 6, cleric 6, thief 9, fighter 8 |
| experience thresholds | the tables | **PROBABLE** — transcribed. Only the THAC0 column has been checked against the game, and checking it found two errors |
| experience field width | 24-bit LE at `0x0E8` | **CONFIRMED** |
| race level limits (dwarf, halfling, elf) | the 28 bytes at `GEN` `$1E64`, seven races of four classes | **CONFIRMED** — P49, same read. `$1E3D`-`$1E49` takes the race from `$6B72`, forms `race * 4 + class`, and the check at `$1E4A` clamps against it exactly as the class ceiling does. All 28 bytes match `por/levels.py`'s `racial_limits`, 99 for unlimited |
| which classes a race may take | the creation menu offers HUMAN only CLERIC / FIGHTER / MAGIC-USER / THIEF | **CONFIRMED for human**; the other five races' menus are undocumented here |
| ability-score minimums per class | nothing in the project | **UNKNOWN** |
| hit points the game will accept | `hp_max` is 16-bit; no character has exceeded 255 | field width CONFIRMED; any **validation** is UNKNOWN |
| whether a loaded save is validated | nothing suggests a checksum, and `wish` writes saves the game loads happily | **GUESS** — see `docs/117-save-conversion.md`, obstacle 7. It has never been *looked for* |

**The ceilings are the game's, not the table's.** `GEN $1E21` is the routine
that was missing when this section was written: it clamps rather than refuses,
so an over-cap character does not fail to train — the game writes the ceiling
back over the level. What a *loaded* over-cap save does is still open, because
the clamp is on the training path and nothing has been seen re-validating a
save on load.

**Build to the documented ceilings and no higher.** An illegal party that
misbehaves would poison every experiment run on it.

---

## 6. Verification

Four gates, weakest first. Only the last two are evidence about the *game*.

1. **Round trip.** `CharacterRecord.from_bytes(generated).to_bytes()` is
   byte-identical, and every field decodes to what the builder was asked for.
   Catches encoder bugs and nothing else.
2. **Derived agreement.** `por/derive.check(record, roster_block, readied)`
   returns no complaints — the cached roster THAC0, armour class and damage
   bonus match what the rules say for the record we built. Catches a stale
   cache, which is the failure mode a hand-built save has.
3. **The game's own decoder.** Boot the disk under `tools/session.py`, open each
   character sheet, and read it off the screen — the game runs in text mode with
   its own charset, so this is screen codes, not OCR. Name, class, level, hit
   points, armour class and THAC0 come back from a decoder that is completely
   independent of `por/layout.py`. **This is the gate that breaks the circle**,
   and no generated party should be used for anything before it passes.
4. **Behaviour.** The sheet showing 6 does not prove the game *treats* the
   cleric as level 6.

### The first experiment: `0x0A3` versus `0x0A4`

Run it before anything else, because it is what the party was built for.

Build WARDEN twice, identical except for two bytes, and make the two readings
predict **visibly different outcomes** rather than the same one:

| variant | `0x0A3` | `0x0A4` |
|---|---|---|
| A | 1 | 10 |
| B | 10 | 1 |

Put the party in front of undead and press TURN UNDEAD. A cleric turning at
level 1 rolls to turn skeletons; one turning at level 10 destroys them
outright. Whichever variant destroys them names the field, in one fight, with
no ambiguity — and if *both* behave the same, the turning level is derived from
`0x0A0` and neither byte is it, which is also an answer.

Getting to the undead does not require playing to them: the current area at
`$4BC2` and the party square at `$49C0`/`$49C1` are CONFIRMED fields, so the
save can start in Sokal Keep. That an arbitrary area-plus-coordinates pair is
legal has never been tested, so try it and fall back to walking.

Whatever it returns, **prune afterwards**: `por/layout.py`, the generated
`docs/20-character-record.md` and `docs/80-fields-wanted.md` all currently state
the `0x0A3` reading as CONFIRMED, and `docs/116-second-game.md` states the other.
One of those has to go, and a doc that accretes the correction without deleting
the superseded text is how contradictions got in before.

---

## Contradictions found while planning — all three since settled

| where | how it came out |
|---|---|
| `0x0A0` PROBABLE in `por/layout.py`, CONFIRMED in `docs/80-fields-wanted.md` | CONFIRMED. Twenty-one shipped `MON*` records name their own level, and `0x0A0` matches nineteen; the two that differ read 7 in the per-class array too, so the designer's label is what is wrong |
| `0x0D9` read as attacks-doubled, and BRUTUS reading `03` where that predicts `02` | **the premise was false.** The `03` came from a dump starting at `0x0D8`, off by one; `0x0D9`–`0x0E0` is `attack_forms`, count and damage per form, CONFIRMED on twenty creatures |
| `por/spells.py` `capacity()`: "no field holding it has been found" | `0x0EE`–`0x0F0`, nibble-packed magic-user low, cleric high. Docstring rewritten |

---

## Order of work

1. **Answer the validation question first**, because it is one boot and it
   decides how ambitious the party may be: build a cleric 7 (one past the
   ceiling `GEN $1E5C` holds), load it, read the sheet. The clamp at `$1E21`
   is on the training path only; whether a *load* re-validates is untested.
2. **The trainer diff.** Grant experience, train one level, diff 580 bytes.
   Once per class; fighter first, because it moves the most.
3. **Write the level-up table from the diff**, and empty the entries of
   `LEVEL_UP_BLOCKERS` that the diff answers.
4. `por/testparty.py` — the six records, generated, no disk.
5. The test-time disk builder, off `tests/gamedata.save_disk`, skipping without
   disks.
6. `debug-level-up` on the debug mode's action bar, `docs/118-debug-mode.md`.
7. **The turning experiment.**
8. Prune the docs the answer contradicts.

Steps 1 and 2 need the emulator and are single-threaded: one agent, and it
checks `ss -tnp | grep 6502` before connecting. Steps 4 and 5 do not touch VICE
at all and can run beside them.

---

## 7. What the trainer actually wrote

**Twenty-nine level-ups, 2026-08-22.** Full tables, evidence and the driving
notes are in `work/reports/p18-party.md`; this is the part a reader of the plan
needs.

The party on `work/drive/P18PARTY.D64`:

| name | race | class(es) | level(s) |
|---|---|---|---|
| MALCYON | elf | magic-user | 6 |
| LADY KATHERINE | half-elf | magic-user / thief | 6 / 9 |
| ROLAND | human | cleric | 6 |
| SILAS | human | fighter | 8 |
| MAGNUS | dwarf | fighter | 5 |
| BRUTUS | human | fighter | 2 |

Four of the six ceilings are reached, and LADY KATHERINE is the multi-class
specimen above level 1 that `docs/90-specimens.md` lists as missing — with two
*different* non-zero entries in `0x0C9`-`0x0CC`, both far above 1.

### The level-up specification

Every field the trainer touched, and nothing else touched anything:

| offset | field | what training does |
|---|---|---|
| `0x071` | `thac0_base` | class table row, `60 − THAC0`; multi-class takes the **best** |
| `0x076` | `hp_max` | **recomputed** as `hp_rolled + level × CON bonus` |
| `0x098` | `attack_level` | the fighter's level from 2 up; 0 otherwise |
| `0x09A`-`0x09E` | saving throws | class table **plus a racial modifier**, rewritten from scratch; multi-class takes the field-wise **minimum** |
| `0x0A0` | `level` | the **maximum** of the per-class levels |
| `0x0A4` | `turn_power` | the cleric's turning level |
| `0x0A5`-`0x0AC` | thief skills | the per-level table |
| `0x0BB`-`0x0C4` | coin | 1000 gp taken, everything else **converted to platinum** |
| `0x0C9`-`0x0CC` | per-class levels | +1 in the class trained |
| `0x0D9` | `attack_forms[0]` | 2 → 3 at fighter 7 and nowhere else |
| `0x078`-`0x07E` | `spells_known` | cleric gains a whole spell level; magic-user one bit, chosen at a menu |
| `0x0E8` | `experience` | **clamped** to one less than the next threshold |
| `0x0ED` | `hp_rolled` | + the die roll |
| `0x0EE`-`0x0F0` | `spells_castable` | class table **plus the WIS bonus**, cleric high nibble, magic-user low |
| `0x10E` / `0x119` / `0x11B` | roster | THAC0 follows `0x071`; hp_current is **set to `hp_max`**; movement recomputed |

Six of the blockers in §3's table are now answerable, and one is not:

* **The saving-throw modifiers** are racial and flat. The dwarf MAGNUS reads
  exactly three lower than the human SILAS on all five columns at every level.
* **`spells_castable`** is the class table plus the wisdom bonus, and ROLAND's
  WIS 16 makes it visible: cleric 6 stores `50 50 20`, which is `3,3,2` plus
  `+2,+2,0`.
* **The thief table** is `GEN $102E` plus a racial row at `$1076`, and
  **race is the whole of the adjustment** -- `GEN $1FEC` reads no ability
  score. The half-elf ladder measured here is those two rows added.
* **`hp_max`** is derived after all, and only `hp_rolled` needs a die.
* **`0x0A0`** is `max()` of the per-class array — settled by five magic-user
  levels on a thief 9 that never moved it.
* **`0x0D9`** is attacks × 2 for a player character. It went 2 → 3 at fighter 7,
  which is exactly where 3/2 attacks appear.
* **`0x0A4`'s value** is still unexplained.

### Corrections this run forces

* **`por/levels.py` is wrong at fighter 4**: the breath save is **15**, not 16.
  Two characters, at that level and no other.
* **Experience is clamped, not spent.** The previous session read 5002 → 2500
  as "−2502, twice the thief threshold"; 2500 is simply `threshold(3) − 1`.
  Trained at 70,100 into thief 8, LADY KATHERINE came out at 70,100 — below the
  clamp, so untouched.
* **The fee is 1000 gp at every level**, not only the first.
* **Training heals.** MAGNUS went in at 2 of 9 and came out at 13 of 13, so a
  wounded high-level character cannot be produced by the trainer.
* **At the ceiling the trainer refuses**, printing `NO MORE ADVANCEMENT
  POSSIBLE`. `GEN $1E21`'s clamp sits behind that refusal and has still never
  been seen to fire.

### Still not built

A half-elf cleric/fighter/magic-user, a dwarf fighter/thief, a wounded fighter
8 on disk, and `por/testparty.py` itself. The specification for the last of
those is the table above.
