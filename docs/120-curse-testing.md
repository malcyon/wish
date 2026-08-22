# Testing Curse of the Azure Bonds against this tooling

**Status: tiers 1, 2 and 5.1 are done and automated in `tests/test_curse.py`.
Tiers 3, 4 and 5.2 need the emulator and are not started.** The goal is a
**base-level check**, not coverage: enough evidence to say "the tooling reads
the second game" or "here is exactly where it stops", and to keep that answer
from silently rotting.

`docs/116-second-game.md` already established the important half — Curse uses
the same 580-byte character record, the same `GEO` format, the same roster
block, and a save image that is Pool of Radiance's constants plus `$200` — and
`tests/test_second_game.py` pins it. This document is about the gap between
*the decoders read Curse's bytes* and *the program works on Curse* — a gap that
was wide because everything above `por/` named Pool of Radiance's files by
hand, and that `por/games.py` closed.

The single most useful check in this document is **tier 5.1: export a Curse
save disk to YAML and re-import it byte-identically.** It exercises the whole
path — D64, PRG, save geometry, slots, roster, items, icons, YAML — and asserts
nothing about meaning, so it can pass before any Curse field is understood. It
passes, on `CURSESAVE2.D64` and `CURSE_C.D64`, with Pool of Radiance's
`PORSAVE11.D64` as the control.

---

## What already holds, and is not being re-tested

| | Confidence | Where |
|---|---|---|
| 580-byte record, every named offset | CONFIRMED | `docs/116`, `tests/test_second_game.py` |
| `class_bits` one bit per level-array slot, paladin 6 / ranger 7 | CONFIRMED | same |
| roster block equals record `0x100`–`0x11F` | CONFIRMED | same |
| save geometry is Pool of Radiance plus `$200` | CONFIRMED | same |
| all sixteen `GEO` files decode, reciprocity ≥ 93.5% | CONFIRMED | same |
| `ITEMS` is 128 × 16, class-usage byte a bit-superset | CONFIRMED | same |
| `ITEMNAMES` reads after one address change (`$9E00`) | CONFIRMED | same |

Everything below is what that suite does **not** touch.

---

## The tiers

| tier | what it proves | emulator | state |
|---|---|---|---|
| 1 static inventory and parse | the disks are what we think, and records come out sane | no | **done** — `tests/test_curse.py` |
| 2 map files | the `GEO` decoder is right about Curse, not merely quiet | no | **done** — same |
| 3 live memory | whether any resident address transfers | **yes** | blocked on the game's start-up check |
| 4 automapper | position, facing, area id | **yes** | depends on tier 3 |
| 5 editor round trip | the whole read/write path is lossless on Curse | 5.1 no, 5.2 yes | **5.1 done**; 5.2 needs the emulator |

Tiers 1, 2 and 5.1 are the ones worth having whatever else happens. They are
cheap, they are automatable, and they fail loudly. All three now run on every
`pytest` and skip when the player has no Curse disk.

---

## Tier 1 — static: inventory and parse

**Done, in `tests/test_curse.py`.** No emulator, no fixtures; every test skips
when the player has no Curse disk, and every assertion runs over Pool of
Radiance too.

### 1.1 Disk directory inventory

**Proves:** that the two games' file sets correspond where we assume they do,
and names every place they do not. **Asserted by**
`test_curse_speaks_pool_of_radiances_file_vocabulary`,
`test_curse_ships_spelln64_and_no_spelln00` and
`test_curse_map_ids_are_sparse_so_nothing_may_enumerate_by_count`, each with
the Pool of Radiance side of the comparison in the same test.

Measured over the six `CURSE_?.D64` sides in `work/curse/` against the nine
`POOL*.D64`:

| | Pool of Radiance | Curse |
|---|---|---|
| directory entries, all sides | 564 | 411 |
| `GEO` files | 29 | 16 |
| stems shared (digits normalised) | — | 65 |

Five differences matter, and all five are new information:

| observation | consequence | Confidence |
|---|---|---|
| **Curse's `GEO` ids are sparse and grouped by chapter**: `01 03 04` / `10 11 15` / `20 21 25` / `32 33 35` / `40 42 43 45`. Pool of Radiance runs `GEO00`–`GEO1F` dense | anything that *enumerates* maps by counting must enumerate by directory instead | CONFIRMED |
| **`GEO15` exists in both games and means different places.** | `por/areas.py:GEO_NAMES` is now keyed by game title first and `area_name` degrades an unknown title to `"area 15"`, so the collision no longer mislabels | CONFIRMED, and cleared |
| **No `SQRPACI*`, `SQRDATA*` or `WALLS*` on any Curse side.** Curse has `WALLDEF00`–`WALLDEF0F` and `WALLSET00`–`WALLSET0F` only | the combat square renderer, which `docs/50-experiments.md` places at `$0400` from `SQRPACI01`, has no counterpart of that name | CONFIRMED |
| **No `LOAD/SAVE` file.** Pool of Radiance carries one | save/load is not the same overlay, so nothing about its addresses transfers | CONFIRMED |
| **`SPELLN64` exists on `CURSE_A.D64` (8 blocks); `SPELLN00` does not.** Pool of Radiance carries both | `docs/116` §5 says "Curse has no `SPELLN` file". That is too strong and should be corrected to "no `SPELLN00`" | CONFIRMED |

Curse-only stems worth a line each, unexplained: `FSDEF`, `STOP`, `FASTL.O`
(against Pool of Radiance's `FAST1.O`).

### 1.2 Save-disk shape

**Asserted by** `test_the_curse_save_is_one_file_where_pool_of_radiance_writes_two`:
`SAVEAZURE` is one 7426-byte PRG loading at `$4B00`, against Pool of Radiance's
`SAVEDGAME0` + `SAVEDGAME1` pair.

**A Curse character export has a directory block count of zero and a valid
sector chain** — `\x02BRUTUS` on `CURSESAVE2.D64` reports 0 blocks and reads
back 582 bytes at `$7C00`. `tests/gamedata.py:curse_file()` used to skip any
zero-block entry and so hid every Curse-written character file; it now follows
the sector chain and ignores the count. The same defect hid all six Death
Knights of Krynn sides, whose cracked directory reports 0 for every file.

### 1.3 Records out of a Curse save parse sane

**Asserted by** `test_every_curse_character_parses_with_fields_a_person_would_recognise`,
over every whole Curse save on the player's disks — SSI's six pregens on
`CURSE_C.D64` *and* the player's own three-character `CURSESAVE`/`CURSESAVE2` —
with `test_pool_of_radiance_characters_satisfy_the_same_invariants` as the
control on `PORSAVE11.D64`.

What it checks, and what came of it:

| check | outcome |
|---|---|
| name reads to its NUL and is printable PETSCII | holds. `F/T` is a real name, so punctuation is in |
| name is NUL-*padded* | **false, and dropped.** The game terminates at the first NUL and leaves the rest: `MALCYON\x00N` and `SILAS\x00S` are characters renamed shorter, and `PALADIN` carries `\x01\x01` in the field's last two bytes |
| six scores 3–18, exceptional strength 0–100 | holds; Curse's own range is 11–18 |
| race 1–7, level 1–40, hp 1–999, `hp_rolled ≤ hp_max` | holds |
| five saving throws 1–20, movement 1–24 | holds |
| `armour_class_base` decodes to 10 | holds for every player character in both games — the `60 - value` encoding intact |
| `class_bits` is one bit per non-zero slot of the **eight-wide** array at `0x0C9`, and no slot exceeds `level` | holds, including `0x40` paladin in slot 6 and `0x80` ranger in slot 7 |

Left undone, and deliberately: hit points against `por/levels.py`'s caps, which
are Pool of Radiance's and unmeasured for Curse; and the spellbook's width,
which no Curse specimen settles — Silver Blades does, see `docs/121`.

### 1.4 The control

Every assertion runs over Pool of Radiance too, in the same test. An invariant
that only ever runs on one game is an invariant that will be quietly broken for
the other.

---

## Tier 2 — map files

**Done, in `tests/test_curse.py`.** No emulator. The decoder already ran; what
was untested was whether it is *right* rather than *not obviously wrong*.

| check | outcome | Confidence |
|---|---|---|
| all 16 `GEO` files are 1024 bytes, four planes | pass | CONFIRMED |
| barrier reciprocity > 92% on each | pass — mean **0.984**, worst `GEO15` **0.935** | CONFIRMED |
| wall-art nibble order — north/east high/low at `$000`, south/west at `$100` | pass — art-presence reciprocity mean **0.994**, worst `GEO33` **0.919** | **CONFIRMED**, was PROBABLE |
| the barrier field is two bits per direction, `N=0-1 E=2-3 S=4-5 W=6-7` | pass | CONFIRMED |
| `$200` bit 7 is roofed/indoor | not checked | GUESS — unchanged |
| `$200` low bits are a per-square script id, and the area's own ECL masks them | not checked | UNKNOWN — Curse's ECL scripts have not been decoded here |

**The art transposition is settled, and by a better discriminator than the
histogram this plan proposed.** `Geo.reciprocity` reads barriers only, so it
survives any consistent transposition of the art. A second measure does not:
whether an edge carries wall art *at all* must agree read from both of the
squares it divides. Curse scores 0.994 on it. Deliberately re-parse the same
sixteen files wrong and it collapses:

| reading | barrier reciprocity | art reciprocity |
|---|---|---|
| as decoded | 0.984 | **0.994** |
| art planes `$000` and `$100` exchanged | 0.984 (blind to it) | **0.540** |
| high and low nibble exchanged in both art planes | 0.984 (blind) | **0.429** |
| barrier directions read `W S E N` | **0.797** | 0.994 |

Both mangles are asserted, so the floors are evidence rather than decoration:
a wrong parse has to fall through them. Presence and not *value* is the right
comparison — the art index differs across a one-way wall, and Curse indexes a
different `WALLDEF`/`WALLSET` pair than Pool of Radiance's `WALLS*` anyway. Art
*indices* differing is expected and harmless; art *planes* differing is not.

**The per-file art floor is Curse's alone.** Pool of Radiance scores 0.960 mean
and 0.646 on `GEO1E`, because it draws genuinely one-sided walls; Curse's worst
is 0.919 and Silver Blades has no one-sided edge at all. So Pool of Radiance is
asserted on the corpus mean only, and that difference is itself a test rather
than folklore.

**Deliberately not tested:** what the art indices draw. That needs the charsets
and the renderer, and it is not a base-level question.

---

## Tier 3 — live memory under VICE

**This tier needs the emulator, and only one agent may drive it.** Check
`ss -tnp | grep 6502` before connecting; never kill a process holding the
monitor.

**The honest expectation: overlay bases and absolute addresses do not transfer
between titles.** `docs/116` already measured five constants that moved
(`$6B00`→`$7C00`, `$4900`→`$4B00`, `$6F00`→`$9E00`, `$24B4`→`$2714`,
marker `$01`→`$02`), and it found no address that stayed. So this is a
**discovery procedure, not a verification**. Anything written as "check that
`$49C0` is the party x" is the wrong shape of task.

### The recipe

For each wanted value, in this order:

1. **Know it from a save.** Save in Curse at a known square. `SAVEAZURE` is a
   verbatim image of `$4B00`–`$67FF`, so the save *is* the memory — read x, y,
   facing at `$4BC0`–`$4BC2` from the file, offline, with no emulator at all.
2. **Search RAM for it live.** With the game running at that square, sweep for
   the byte triple. The save-image range is the first place to look and should
   hit; the interesting result is any *second* copy, which is where the live
   engine keeps its working value.
3. **Corroborate with a second value.** One byte matching is a coincidence
   factory. Take a value with more entropy — the game clock, or a character's
   16-bit experience — and require both to land at the offsets the save
   predicts.
4. **Change it in game and re-read.** Walk one square north. The candidate must
   change by exactly what walking one square north changes, and nothing else in
   the header may move except the clock and the previous-position pair.

Only after step 4 is an address CONFIRMED. Steps 1–3 give PROBABLE at best.

### What to look for, and what it would tell us

| value | offline from `SAVEAZURE` | live address | Confidence now | if step 4 fails |
|---|---|---|---|---|
| party x, y, facing | `$4BC0`–`$4BC2` | expect `$4BC0`, unproven | PROBABLE — confirmed from two save diffs, never live | the engine keeps a working copy elsewhere and the save is written from it; find the copy |
| area id | `$4DC2`, dirty bit `$80` | expect `$4DC2` | PROBABLE | same |
| game clock | `$4BC7` | expect `$4BC7` | PROBABLE | the clock is derived, not stored live |
| loaded-file cache | `$4DC0`, 25 entries | expect `$4DC0` | PROBABLE | harmless; it is a cache |
| character slots | `$4F00 + n*$100` | expect `$4F00` | CONFIRMED in the file, UNKNOWN live | the game relocates records into a work area, which would matter for tier 5.2 |
| resident `GEO` | — | Pool of Radiance leaves it at `$0400` | UNKNOWN | Curse relocates the map; find it by searching for a known `GEO` payload |
| `LIBRARY` `GEO` stem digits | — | `$2714` per `docs/116` | PROBABLE — derived from the file, never read live | the overlay relocates differently; fall back to the resident-`GEO` search |
| combat mode flag | — | Pool of Radiance `$6E11` | UNKNOWN | expected; Curse has no `SQRPACI` and its combat overlay is a different build |

**Blocker, stated plainly:** getting to a live Curse world requires passing the
game's start-up check, exactly as Pool of Radiance does. That is out of scope
for this repository and is not planned around here. Everything in tiers 1, 2
and 5.1 is deliberately arranged to need no emulator, so the plan degrades to
"most of it still runs" rather than "none of it runs".

**Second blocker:** a live session must not write to
`/home/donald/c64/Pool of Radiance Disks/`. Curse work uses `work/curse/`,
which is gitignored.

---

## Tier 4 — the automapper

**Needs the emulator, and needs tier 3 first.** There is nothing to test until
an address is known.

| component | transfers? | what has to be re-derived | Confidence |
|---|---|---|---|
| `Geo` rendering and shading | yes, unchanged | nothing | CONFIRMED |
| party position and facing | probably | the three addresses (tier 3) | PROBABLE |
| `ResidentGeo` strategy — find the loaded map in RAM and match it | probably | where Curse leaves it; `$0400` is a Pool of Radiance fact | GUESS |
| `FilenameDigits` strategy — read the two digits patched into the `GEO00` stem | probably not as written | `$2714` instead of `$24B4`, **and the digit format**: Curse's ids are sparse (`GEO45`), so the two bytes are still two bytes but the candidate set is not `00`–`1F` | PROBABLE |
| `Fingerprint` strategy — narrow candidates by what the party can and cannot do | yes | the candidate list must come from the Curse disks' directory, not a count | PROBABLE |
| area names | **structure done, content not** | `por/areas.py:GEO_NAMES` is keyed by game title and `area_name` degrades an unknown map to `"area 15"` rather than lying, so the `GEO15` collision is gone. Curse's own names are still nobody's — naming a map needs the game | CONFIRMED for the table, UNKNOWN for the names |
| one step costs one minute (`automap/state.py`) | unknown | measure | UNKNOWN |

**What a failure would tell us.** If `ResidentGeo` cannot find the map anywhere
in the 64K, Curse either relocates it into a bank the monitor's `cpu` view does
not show, or decompresses it — and the second would be a genuinely new fact
about the engine, worth more than the automapper is.

**The minimum that counts as "the automapper works on Curse":** stand in a
known Curse area, and have the live view name the right `GEO`, draw the right
walls, and move the marker correctly for four steps and four turns. That is a
base-level check. Full exploration tracking, notes and the world map are not.

---

## Tier 5 — the editor

### 5.0 The blocker, cleared

**`por/games.py` is the game parameter this section asked for**: a frozen
`Game` descriptor per title carrying the save file name, the load address, the
payload size and the roster's place, threaded through `por/savegame.py`,
`por/yaml_io.py` and `editor/`. `games.detect(disk)` names the title from the
disk's own directory, so a Curse save opens with no argument, and
`por/items.py`, `por/icons.py` and `editor/inventory.py` needed no change at
all because they already worked in payload offsets. All six titles are in the
table.

Nothing about the record layout was duplicated, which was the risk this section
named: `docs/116` is unambiguous that the offsets are identical, so a second
`layout.py` would have been wrong.

### 5.1 The byte-identical round trip — the strongest single check

**Done. All three round trips pass**, in `tests/test_curse.py`, with Pool of
Radiance's two-file save as the control. Every byte of a Curse save survives
read → decode → encode → write through the same code the editor uses, and none
of it asserts what any byte *means* — which is why it passes while half of
`docs/116` §6 is still NOT FOUND.

| # | round trip | result |
|---|---|---|
| a | `SAVEAZURE` payload → `SaveGame0` → bytes | byte-identical |
| b | Curse save disk → YAML → new disk | byte-identical D64 images, on `CURSESAVE2.D64` and `CURSE_C.D64` |
| c | a Curse `\x02NAME` export → `CharacterRecord` → bytes | byte-identical: `\x02BRUTUS`, 582 bytes, marker `$02`, load `$7C00` |

One edited field is checked too: setting gold moves at most two bytes of the
whole image.

### 5.2 An edited field takes effect in game

**Needs the emulator, and only after 5.1 passes.** **Proves:** that the write
path targets bytes the game actually reads. **Cost:** an hour per field.
**Failure means:** the field is cached somewhere else — the roster block is the
known example, and `editor/binding.py` already notes that editing the record's
copy of AC achieves nothing.

Three fields, chosen because each fails differently:

| field | why this one |
|---|---|
| character name at `0x000` | visible immediately, no derivation, no cache |
| gold at `0x0C1` | Curse's import zeroes it and sets platinum to 300, so the game demonstrably writes here |
| current hit points | lives in the **roster block**, not the record — the case that catches a tool editing the wrong copy |

Do not attempt an edited-field test before the round trip passes. An edit that
appears not to take effect, on a path that is silently lossy, is unreadable
evidence.

---

## Blockers, honestly

Four of the seven blockers this section listed are cleared: `wish` opens a
Curse save, `curse_file()` follows the sector chain instead of trusting the
block count, `por/areas.py:GEO_NAMES` is keyed by title, and the `PIS` rip
supplies six clean sides. What is left:

| blocker | severity | what would clear it |
|---|---|---|
| **live testing needs past the game's start-up check** | blocks tiers 3, 4 and 5.2 | out of scope for this repository; tiers 1, 2 and 5.1 are arranged not to need it |
| no Curse save from a *played* party with inventory | the item area at `$5B00` stays PROBABLE and no Curse item record has ever been seen | play far enough to pick something up, then save. Needs the emulator |
| Curse's level caps and spell tables are not measured | tier 1.3's "hit points in range" check cannot be strict, and is not asserted | table data; a day of reading the disks, no emulator |
| the spellbook's width in Curse | no Curse specimen writes past `0x07C`, so `docs/116`'s NOT FOUND stands *for Curse* | already settled for the family by Silver Blades — `docs/121` |
| Curse's `$200` attribute plane — indoor bit and script id | GUESS and UNKNOWN, tier 2 | needs Curse's ECL decoded, which nothing else depends on |

**On the archives.** The disks are under `/home/donald/c64/All Games/`. Use
`Curse_of_the_Azure_Bonds.SSI.PIS.zip` — six clean sides. The two archives
labelled "with docs" carry `advtjrnl.txt`, `rulebook.txt` and a
`..._Journal.d64`: **that is the manual and the adventurer's journal, and it
must never enter this repository in any form, transcribed or otherwise.**
Extract only into `work/`, which is gitignored, and extract only the `.d64`
sides.

---

## Out of scope

A base-level check is defined as much by what it refuses as by what it covers.
None of the following is planned, and each is left out for a reason.

| not tested | why that is right |
|---|---|
| **Every Curse field's meaning.** `docs/116` §6 lists eight open questions — the item area, the memorised-spell width, the spellbook width, dual-class, azure-bond state, the spell-name table, the combat slots | Answering them is research, not testing. The round trip in 5.1 passes without any of them, which is exactly the property that makes it the right check |
| **Curse's ECL bytecode.** Pool of Radiance's is fully decoded; Curse's is not | Weeks. Nothing in tiers 1–5 depends on it |
| **Combat.** `$6E11`, the arena, the position table, the initiative order | Curse ships no `SQRPACI`/`SQRDATA`; its combat overlay is a different build, so every address must be rediscovered. That is a project, not a check |
| **Item and spell semantics.** That Curse item id *n* means the same object as Pool of Radiance's | The tables were shown to have the same *shape*; agreeing on *meaning* is a separate claim and nothing here needs it |
| **The DOS build.** `docs/117-save-conversion.md` is that plan | Different question, different blockers |
| **Portraits, icons and art beyond round-tripping the 36 bytes** | The bytes must survive; what they draw is not this project's promise |
| **Long play.** Finishing a chapter, testing quest flags | The persistent-flag region is UNKNOWN even in Pool of Radiance (`docs/117`, obstacle 1). Testing Curse's would be measuring an unknown against an unknown |
| **Copy protection, in any form** | Out of scope, and not discussed here |

The line is drawn at: **the tooling reads Curse's containers, decodes its
records and maps, and writes back every byte it was given.** Everything past
that is the second game's own reverse-engineering project, and this document is
not it.
