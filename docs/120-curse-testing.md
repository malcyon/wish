# Testing Curse of the Azure Bonds against this tooling

**Status: all five tiers are done.** Tiers 1, 2 and 5.1 are automated in
`tests/test_curse.py`; tiers 3, 4 and 5.2 were done under VICE and what survives
without an emulator is pinned in `tests/test_curselive.py`. The write-up for the
live tiers, `work/reports/p8-curse-live.md`, is lost. The goal was a **base-level
check**, not coverage: enough evidence to say "the tooling reads the second
game" or "here is exactly where it stops", and to keep that answer from silently
rotting.

**The one-line answer: it works.** A Curse save round-trips byte-identically,
an edited field appears on the game's own character sheet, and the automapper
names the right map and follows the party — with exactly one address to
re-derive, the party position, which in Curse is not in the save image at all.

`docs/116-second-game.md` already established the important half — Curse uses
the same 580-byte character record, the same `GEO` format, the same roster
block, and a save image that is Pool of Radiance's constants plus `$200` — and
`tests/test_second_game.py` pins it. This document is about the gap between
*the decoders read Curse's bytes* and *the program works on Curse* — a gap that
was wide because everything above `goldbox/` named Pool of Radiance's files by
hand, and that `goldbox/games.py` closed.

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
| 3 live memory | whether any resident address transfers | **yes** | **done** — one does, `$0400`; the rest moved |
| 4 automapper | position, facing, area id | **yes** | **done** — works, with one address to re-derive |
| 5 editor round trip | the whole read/write path is lossless on Curse | 5.1 no, 5.2 yes | **done** — three edited fields appear in game |

Tiers 1, 2 and 5.1 are the ones worth having whatever else happens. They are
cheap, they are automatable, and they fail loudly. All three now run on every
`pytest` and skip when the player has no Curse disk. What tiers 3, 4 and 5.2
left behind that can run without an emulator — the constants, the code paths
against a hand-built machine, and the route the party actually walked — is in
`tests/test_curselive.py`.

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
| **`GEO15` exists in both games and means different places.** | `goldbox/areas.py:GEO_NAMES` is now keyed by game title first and `area_name` degrades an unknown title to `"area 15"`, so the collision no longer mislabels | CONFIRMED, and cleared |
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

Left undone, and deliberately: hit points against `goldbox/levels.py`'s caps, which
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

**Done.** The write-up, `work/reports/p8-curse-live.md`, carried the evidence for every line
below and is lost; `tests/test_curselive.py` pins the constants and the code paths.

**One resident address transfers between the two titles, and it is the one the
automapper most needs: the loaded map block at `$0400`.** Everything else moved,
and one thing moved further than "plus `$200`": Curse's *live* party position is
not in the save image at all.

| value | Pool of Radiance | Curse, live | Confidence |
|---|---|---|---|
| whole save image, resident at its own load address | `$4900` | **`$4B00`, all 7424 bytes byte-identical to the file** | CONFIRMED |
| character slots | `$4D00 + n·$100` | **`$4F00 + n·$100`** | CONFIRMED |
| roster block | `SAVEDGAME1` | **`$6700`** | CONFIRMED |
| record staging page | `$6B00` | **`$7C00`** | CONFIRMED |
| **live** party x, y, facing | `$49C0`–`$49C2` | **`$C04B`–`$C04D`** | CONFIRMED |
| the save image's own x, y, facing | the same bytes | `$4BC0`–`$4BC2`, **written only when the game saves** | CONFIRMED |
| game clock | `$49C7` | **`$4BC7`**, live and ticking | CONFIRMED |
| area byte | `$4BC2` | **`$4DC2`** (payload `+$2C2`), read `$81` | PROBABLE |
| resident `GEO` block | `$0400` | **`$0400` — unchanged** | CONFIRMED |
| `LIBRARY`'s `GEO` stem digits at `$2714` | — | **not there**; `$2710` is code. The `docs/116` figure came from the file and does not hold live. Nothing depends on it | — |
| combat mode flag | `$6E11` | **`$7F11`** | CONFIRMED. `LINKER` is resident at `$2D00` and begins `LDA $7F11`; its name table at `$2D42` is Pool of Radiance's entry for entry, so `2` is still COMBAT. Sampled world `1` / camp `9` / roster `0`. `Game.mode_flag` is set and the five live actions no longer refuse (#29) |

**How `$C04B` was earned**, because it is the one that a "check `$4BC0`" task
would have got wrong in both directions. `$4BC0`–`$4BC2` *is* the position
triple and *is* resident — but walk the party and it does not move: the status
line read `5,13` facing west while `$4BC0` still read `07 0d 02`. Diffing two
64K dumps either side of those steps left exactly one candidate, `$C04B`
(`07 0d 02` → `05 0d 03`), and three bytes away sits the engine's own
self-modified `LDA #$05 / STA $C04B / LDA #$0D / STA $C04C` at `$C1F5`. Three
lines of evidence: the only pair in the machine that changed the way a westward
step must, agreement with the status line at every later reading, and the
instruction that writes it.

**The clock advances one minute per *completed* forward step**, and by nothing
at all on a turn or on a step the game refused. Measured over four turns and one
refusal at an unchanged clock. Consequence in tier 4.

**The area byte stays PROBABLE**: `$4DC2` read `$81` — area 1 with the `$80`
bit, and `GEO01` was what was resident — but **no boundary crossing was
observed**, and this document's own rule is that a negative needs a negative
example.

**The start-up check did not block the rip used here**, which is why this tier
ran at all. Nothing further about it belongs in this repository. A live session
still writes only to `work/`, never to the player's own disks.

---

## Tier 4 — the automapper

**Done.** Driven against a live Curse session with `automap/` **unmodified**;
the run was recorded in `work/reports/p8-curse-live.md`, now lost, and
`tests/test_curselive.py` pins what
can be checked without an emulator.

| component | verdict | evidence |
|---|---|---|
| `Geo` decode and rendering | transfers unchanged | every step the game allowed crosses an edge `GEO01` calls passable; the one it refused is an edge `GEO01` calls solid |
| `ResidentGeo` at `$0400` | **transfers unchanged** | `identify()` returned `GEO01` — an exact 1024-byte match against the disk copy. The `$0400` in `automap/area.py` is not a Pool of Radiance fact after all |
| `party_fix`, status-line path | **transfers unchanged** | Curse draws `S 0:03  5,13` on the same row 14 of the same `$CC00` screen and `RE_STATUS` matches it as written |
| `party_fix`, memory fallback | **does not transfer** | `$49C0` in a running Curse is engine code. Curse's live triple is `$C04B`, which is *outside* the save image, so a per-title base cannot simply be a payload offset |
| `Fingerprint` | transfers unchanged | 16 candidates → **2** on four completed steps and one refusal, **0 contradictions**, `GEO01` among the survivors and equal to what `ResidentGeo` said independently |
| `automap/state.py`'s `_refused` | **never fires on Curse** | it infers a refusal from clock+1 with the square unchanged, and Curse's clock does not advance on a refused step. Its docstring already allows this; a driver that wants refusals must compare squares |
| one step costs one minute | **CONFIRMED for a completed forward step**, and zero for a turn or a refusal | the clock ran `0:01 → 0:03 → 0:07` over six steps and stood still through four turns and one refusal |
| area names | structure done, content not | `goldbox/areas.py:GEO_NAMES` is keyed by title and Curse's table is empty, so `area_label` degrades rather than lying. Naming Curse's sixteen maps still needs somebody who has played it |
| `FilenameDigits` | **moot** | there is no filename strategy in `automap/area.py`, and `$2714` is code in a running Curse anyway |

**What is left to make this work in the product**, as against in the experiment:
a per-title party base for the memory fallback. It is a `goldbox.games`-shaped
change — `automap/target.py` and `automap/area.py` both hold their addresses as
module constants — and the value for Curse is `$C04B`.

**What a failure would have told us**, kept because it is the reasoning: if
`ResidentGeo` had found the map nowhere in the 64K, Curse would either relocate
it into a bank the monitor's `cpu` view does not show or decompress it, and the
second would have been a genuinely new fact about the engine. It found it at
`$0400` on the first look.

---

## Tier 5 — the editor

### 5.0 The blocker, cleared

**`goldbox/games.py` is the game parameter this section asked for**: a frozen
`Game` descriptor per title carrying the save file name, the load address, the
payload size and the roster's place, threaded through `goldbox/savegame.py`,
`goldbox/yaml_io.py` and `editor/`. `games.detect(disk)` names the title from the
disk's own directory, so a Curse save opens with no argument, and
`goldbox/items.py`, `goldbox/icons.py` and `editor/inventory.py` needed no change at
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

**Done, on all three fields, first attempt.** `wish export` → edit → `wish
import` → load the new disk in the game and read the answer off the game's own
screens. This is the strongest single claim the editor can make about a second
title.

| field | where it lives | edit | what the game showed |
|---|---|---|---|
| character name | record `0x000` | `BRUTUS` → `CAESAR` | party list `CAESAR 10 7` |
| gold | record `0x0C1` | `0` → `777` | character sheet `GOLD 777` |
| current hit points | **roster block `+$19`**, not the record | `11` → `7` | party list and sheet, `HP 7` |

The third is the one that mattered: it was chosen because it catches a tool
editing the record's copy instead of the roster's — `editor/binding.py` already
notes that editing the record's copy of AC achieves nothing — and `wish` edited
the right one.

The same sheet corroborated the read side in one screen: `STR 18(98)`,
`PLATINUM 300`, `AC 10`, `THACO 18`, `DAMAGE 1D2+5`, `MOVEMENT 12`,
`MALE HUMAN AGE 21`, `NEUTRAL GOOD`, `FIGHTER` — every one of them what
`goldbox.record` reads out of the same bytes.

Do not attempt an edited-field test before the round trip passes. An edit that
appears not to take effect, on a path that is silently lossy, is unreadable
evidence.

---

## Blockers, honestly

Five of the seven blockers this section listed are cleared: `wish` opens a
Curse save, `curse_file()` follows the sector chain instead of trusting the
block count, `goldbox/areas.py:GEO_NAMES` is keyed by title, the `PIS` rip supplies
six clean sides, and **the game's start-up check did not block the live tiers on
that rip**. What is left:

| blocker | severity | what would clear it |
|---|---|---|
| the area byte across a boundary is unwatched | `$4DC2` stays PROBABLE | drive the party over an area edge and read it either side. One session |
| the automapper's memory fallback has no per-title base | the live view works off the status line and has nothing to fall back to in camp or combat | thread a party base through `automap/target.py` the way `goldbox/games.py` threads the save geometry. Curse's value is `$C04B`, and it is *not* a save-image offset |
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
