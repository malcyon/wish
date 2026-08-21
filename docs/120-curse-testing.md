# Testing Curse of the Azure Bonds against this tooling — plan

**Status: planned, not started.** The goal is a **base-level check**, not
coverage: enough evidence to say "the tooling reads the second game" or "here
is exactly where it stops", and to keep that answer from silently rotting.

`docs/116-second-game.md` already established the important half — Curse uses
the same 580-byte character record, the same `GEO` format, the same roster
block, and a save image that is Pool of Radiance's constants plus `$200` — and
`tests/test_second_game.py` pins it. This plan is about the gap between *the
decoders read Curse's bytes* and *the program works on Curse*, which is wider
than it looks, because everything above `por/` names Pool of Radiance's files
by hand.

The single most useful check in this document is **tier 5.1: export a Curse
save disk to YAML and re-import it byte-identically.** It exercises the whole
path — D64, PRG, save geometry, slots, roster, items, icons, YAML — and asserts
nothing about meaning, so it can pass before any Curse field is understood. It
is also the one that cannot run today, for a reason named below.

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

| tier | what it proves | cost | emulator | blocked today |
|---|---|---|---|---|
| 1 static inventory and parse | the disks are what we think, and records come out sane | hours | no | no |
| 2 map files | the `GEO` decoder is right about Curse, not merely quiet | hours | no | no |
| 3 live memory | whether any resident address transfers | a day, iterative | **yes** | the game's start-up check |
| 4 automapper | position, facing, area id | half a day after tier 3 | **yes** | depends on tier 3 |
| 5 editor round trip | the whole read/write path is lossless on Curse | half a day + a game parameter | 5.1 no, 5.2 yes | **yes — see 5.0** |

Tiers 1, 2 and 5.1 are the ones worth having whatever else happens. They are
cheap, they are automatable, and they fail loudly.

---

## Tier 1 — static: inventory and parse

**No emulator. Automate as tests that skip when no Curse disk is present,
exactly as `tests/gamedata.py` already does.** Add to
`tests/test_second_game.py`; do not add fixtures.

### 1.1 Disk directory inventory

**Proves:** that the two games' file sets correspond where we assume they do,
and names every place they do not. **Cost:** an hour, and most of it is already
done below. **Failure means:** an assumption about a file's existence — not its
contents — is wrong, which is the cheapest kind of bug to find and the most
annoying to find late.

Measured while writing this, over the six `CURSE_?.D64` sides in `work/curse/`
against the nine `POOL*.D64`:

| | Pool of Radiance | Curse |
|---|---|---|
| directory entries, all sides | 564 | 411 |
| `GEO` files | 29 | 16 |
| stems shared (digits normalised) | — | 65 |

Five differences matter, and all five are new information:

| observation | consequence | Confidence |
|---|---|---|
| **Curse's `GEO` ids are sparse and grouped by chapter**: `01 03 04` / `10 11 15` / `20 21 25` / `32 33 35` / `40 42 43 45`. Pool of Radiance runs `GEO00`–`GEO1F` dense | anything that *enumerates* maps by counting must enumerate by directory instead | CONFIRMED |
| **`GEO15` exists in both games and means different places.** `automap/state.py` maps `GEO15` → "Sokol Keep" | a Curse party in `GEO15` would be labelled Sokol Keep. The area-name table is per-title and is not marked as such | CONFIRMED |
| **No `SQRPACI*`, `SQRDATA*` or `WALLS*` on any Curse side.** Curse has `WALLDEF00`–`WALLDEF0F` and `WALLSET00`–`WALLSET0F` only | the combat square renderer, which `docs/50-experiments.md` places at `$0400` from `SQRPACI01`, has no counterpart of that name | CONFIRMED |
| **No `LOAD/SAVE` file.** Pool of Radiance carries one | save/load is not the same overlay, so nothing about its addresses transfers | CONFIRMED |
| **`SPELLN64` exists on `CURSE_A.D64` (8 blocks); `SPELLN00` does not.** Pool of Radiance carries both | `docs/116` §5 says "Curse has no `SPELLN` file". That is too strong and should be corrected to "no `SPELLN00`" | CONFIRMED |

Curse-only stems worth a line each, unexplained: `FSDEF`, `STOP`, `FASTL.O`
(against Pool of Radiance's `FAST1.O`).

### 1.2 Save-disk shape

**Proves:** that a save disk written by Curse is a container `por/d64.py` reads.
**Cost:** minutes. **Failure means:** the D64 reader has a gap, which would
block every later tier.

Observed on `work/curse/CURSESAVE2.D64`:

| entry | block count in the directory | actually reads |
|---|---|---|
| `SAVEAZURE` | 30 | 7426 bytes, load `$4B00` |
| `\x02BRUTUS` | **0** | 582 bytes, load `$7C00` |

**A Curse character export has a directory block count of zero and a valid
sector chain.** PROBABLE — one specimen, but the file is exactly what `docs/116`
§4 describes the export routine producing, so the game wrote it.

This is a live defect, not a curiosity: `tests/gamedata.py:curse_file()` does

```python
if entry is None or not entry.block_count:
    continue
```

so it would **silently skip every Curse-written character file**. The `not
entry.block_count` guard exists to reject the empty-entry case; it needs to be
"the file has no sector chain", not "the count field is zero". Fix and add a
test that reads a Curse export by name.

### 1.3 Records out of a Curse save parse sane

**Proves:** the record decoder is not merely round-tripping bytes but producing
values a person would recognise. **Cost:** an hour. **Failure means:** an
offset that happens to be inert in Pool of Radiance is live in Curse.

`tests/test_second_game.py:_sane_record` already checks race, hit points,
level, saving throws and movement over SSI's six pre-generated characters.
Extend it, over **the player's own Curse save** as well as SSI's:

| check | expected | Confidence |
|---|---|---|
| name is printable ASCII, NUL-padded, non-empty | yes | CONFIRMED |
| the seven scores at `0x014` are 3–18, exceptional strength 0–100 | yes | CONFIRMED |
| `0x065`–`0x06B` equals `0x014`–`0x01A` | yes | CONFIRMED (§2.2 of `docs/116`) |
| `char_class` at `0x073` is zero; `class_bits` at `0x0EB` is the field to read | yes | CONFIRMED |
| hit points ≤ the level tables allow for the class and level | probably | PROBABLE — `por/levels.py` carries paladin and ranger rows but Curse's caps are **not measured** |
| the spellbook at `0x078` has no bit set above the highest known spell id | unknown | UNKNOWN — Curse has 100 ids and no Curse specimen writes past `0x07D` |
| money fields are 16-bit and in range | yes | PROBABLE |

The last three are where a base-level check earns its keep: they will either
pass quietly or hand us a real question.

### 1.4 The control

Every assertion added must run over Pool of Radiance too, in the same test, as
`test_second_game.py` already does. An invariant that only ever runs on one
game is an invariant that will be quietly broken for the other.

---

## Tier 2 — map files

**No emulator. Cost: hours.** The decoder already runs; what is untested is
whether it is *right* rather than *not obviously wrong*.

| check | what it proves | expectation | Confidence |
|---|---|---|---|
| all 16 `GEO` files are 1024 bytes, four planes | plane structure identical | pass | CONFIRMED |
| reciprocity > 92% on each | planes are not swapped or shifted | pass, worst 93.5% | CONFIRMED |
| wall-art nibble order — north/east high/low at `$000`, south/west at `$100` | the art planes are not transposed | pass | PROBABLE — reciprocity would survive a *consistent* transposition of art, because it only reads barriers |
| the barrier field is two bits per direction, `N=0-1 E=2-3 S=4-5 W=6-7` | passability decodes | pass | PROBABLE |
| `$200` bit 7 is roofed/indoor | attribute plane means the same | pass | GUESS — never checked in Curse |
| `$200` low bits are a per-square script id, and the area's own ECL masks them | the script-id reading transfers | unknown | UNKNOWN — Curse's ECL scripts have not been decoded here |

**The one worth adding a test for is the art transposition.** Reciprocity is
computed from barriers only, so it cannot catch it. The cheap discriminator:
in a corridor, an edge with wall art on one side has wall art on the other, and
the *counts* of each art value should be near-symmetric between the two planes.
Compute the north/south and east/west art histograms across all sixteen files
and compare them with Pool of Radiance's. Wildly different shapes mean the
planes are not what we think.

**A mismatch would mean** Curse uses different wall art indices into a different
`WALLDEF`/`WALLSET` pair — which its file list already suggests it does, since
Curse ships `WALLDEF00`–`WALLDEF0F` where Pool of Radiance ships `WALLS*`. Art
*indices* differing is expected and harmless; art *planes* differing is not.

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
| `AREA_NAMES` in `automap/state.py` | **no** | every name. It is a Pool of Radiance table with no title key, and `GEO15` collides | CONFIRMED |
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

### 5.0 The blocker, first

**A Curse save cannot be opened by `wish` or `wish-cli` today, and it is not a
one-line fix.** The whole upper stack names Pool of Radiance's files and base
literally:

| where | hardcoded |
|---|---|
| `editor/roster.py` | `SAVE0`/`SAVE1` = `SAVEDGAME0`/`SAVEDGAME1`; "is this a save disk" is `SAVE0 in names` |
| `editor/window.py` | writes back to `b"SAVEDGAME0"` / `b"SAVEDGAME1"` |
| `por/yaml_io.py` | reads and writes both files by name; `SAVE0_LOAD_ADDRESS` throughout |
| `por/savegame.py` | `SAVE0_LOAD_ADDRESS = 0x4900`, `SAVE1_LOAD_ADDRESS = 0x8300`, `ITEM_AREA_BASE = 0x5900`, `ICON_TABLE_BASE = 0x4BE0` |
| `por/items.py` | `NAMES_LOAD_ADDRESS`; `tests/test_second_game.py` monkeypatches it to `$9E00` |
| `automap/paths.py`, `automap/__main__.py`, `editor/window.py`, `wish/__main__.py` | glob `POOL*.D64` |
| `tests/test_binary_roundtrip.py` | an absolute path to one machine's disk directory |

Curse has **one** save file, `SAVEAZURE`, at `$4B00`, with the roster inside it
at `$6700` — so this is not "the same two files at a different address", it is a
different container shape.

**The smallest honest change is a game parameter**: a `Game` value carrying the
save filenames, the load addresses, the roster base, the item base, the item
name base and the disk glob, threaded from `Party.__init__` and the YAML entry
points down into `savegame.py`. Not a second copy of the code, and not a second
layout table — `docs/116` is unambiguous that the record offsets are identical,
so a second `layout.py` would be wrong.

Estimate: a day, most of it threading rather than thinking. **Do this before
tier 5.1, because tier 5.1 is the check worth having.**

### 5.1 The byte-identical round trip — the strongest single check

**Proves:** that every byte of a Curse save survives read → decode → encode →
write, through the same code the editor uses. It asserts nothing about what any
byte *means*, which is why it can pass while half of `docs/116` §6 is still
NOT FOUND. **Cost:** minutes to run, once 5.0 is done. **No emulator.**
**Failure means:** a region is being decoded and re-encoded lossily — the exact
failure a reverse-engineering tool must never have, because a silent misparse
looks like a discovery.

Three round trips, each stricter than the last:

| # | round trip | expected |
|---|---|---|
| a | `SAVEAZURE` payload → `SaveGame0`-equivalent → bytes | byte-identical |
| b | Curse save disk → YAML → new disk | the two D64 images identical outside the directory timestamps |
| c | a Curse `\x02NAME` export → `CharacterRecord` → bytes | byte-identical (already passes for save slots; **not** for exports, see 1.2) |

(c) is nearly free and should be added to `tests/test_second_game.py` **now**,
before 5.0, since it needs no editor at all — only the `curse_file` fix.

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

| blocker | severity | what would clear it |
|---|---|---|
| **`wish` cannot open a Curse save at all** (5.0) | blocks tier 5 entirely | a game parameter; a day's work, no research needed |
| **live testing needs past the game's start-up check** | blocks tiers 3 and 4 | out of scope for this repository; tiers 1, 2 and 5.1 are arranged not to need it |
| `tests/gamedata.py:curse_file()` skips zero-block entries | blocks reading Curse character exports in tests | change the guard to test for a sector chain; hours |
| `por/d64.py` refuses `CURSE4.D64` (175531 bytes, 35 tracks plus error bytes) | one side of one rip unreadable | the `PIS` rip in `Curse_of_the_Azure_Bonds.SSI.PIS.zip` is all six sides at 174848 and is the set to use |
| no Curse save from a *played* party with inventory | the item area at `$5B00` stays PROBABLE and no Curse item record has ever been seen | play far enough to pick something up, then save. Needs the emulator |
| Curse's level caps and spell tables are not measured | tier 1.3's "hit points in range" check cannot be strict | table data; a day of reading the disks, no emulator |
| `automap/state.py:AREA_NAMES` has no title key and `GEO15` collides | tier 4 would confidently mislabel | key the table by title when 5.0's game parameter lands |

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
