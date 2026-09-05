# The DOS Decode Kit

`github.com/DrEvil-TitaniumHelix/dos-decode-kit`, read at commit `d9f7fb4`
(three commits, 2026). A stranger's repository: a *method* for reverse
engineering DOS games, with the tooling that did it, proven on Midwinter (1989)
and **DOS Pool of Radiance**. Everything below is the comparison against our own
tables and what the comparison changed.

**Licence: MIT** (tools and documents), with an explicit note that the games
remain their rights holders'. So anything in it we ever wanted could be used
with attribution — but nothing has been copied here and nothing needs to be:
what is worth having is the *findings*, and the code we already have.

**It ships no game data.** 139 files, all `.py`, `.md`, `.html`, `.js`; the
`.gitignore` excludes `*.exe`, `*.DAX`, `*.SAV`, `*.ITM` and the generated
`game_data.js`. Verified by listing every file. Clone lives in
`work/dos-decode-kit/`, which is gitignored.

**One file is addressed to an AI agent** — `docs/HANDOFF_for_fable.md`, a brief
written for a model to pick up the decode. It was read as data, nothing in the
repository was executed, and it contains no instruction aimed at a reader other
than its own author's next session.

Cite it as a **third-party document**: PROBABLE evidence, never CONFIRMED on its
own. Its own author grades findings *verified* / *uncertain*, which is the same
discipline as ours and makes it easier to read than most.

---

## What changed our understanding

### 1. The ECL scripts are the same bytes on the C64 and DOS — CONFIRMED

The repository's ECL write-up quotes the header of its DOS `ECL1.DAX` block 18
(Podol Plaza). Those twenty bytes are **byte-identical to the C64's `ECL12`**,
which `docs/88-map-files.md` independently matched to Podol Plaza by map shape.
That prompted a full diff of the C64 `ECL` files against the DOS
`ECL<1-8>.DAX` blocks in the player's own copy of the DOS game.

**The mapping is the file name: C64 `ECLnn` (hex) is DOS block id `nn` (decimal),
in whichever `ECL<1-8>.DAX` happens to carry it.** Of the 29 pairs:

| result | count | which |
|---|---|---|
| byte-identical | **7** | `ECL03`, `ECL04`, `ECL05`, `ECL09`, `ECL18`, `ECL19`, `ECL1D` |
| within 16 bytes | **6** | `ECL1A` (2), `ECL16` (3), `ECL0F` (5), `ECL17` (6), `ECL14` (10), `ECL02` (16) |
| substantially different | 16 | the rest, mostly with a small length change early |
| no DOS block at all | 1 | `ECL1E` |

`ECL1E` having no counterpart **confirms `docs/128-guide-and-scripting.md`** from
a second direction: DOS has no script 30, and the C64 port put its attract-mode
demo in the slot DOS left free.

What this is worth: our 62-opcode VM table, taken
from the C64 `DUNGEON` dispatch tables, **disassembles the DOS scripts directly**,
and `work/analysis6/ecl6.py` can be pointed at a decompressed `.DAX` block as-is
— both the table (`work/reports/ecl-opcodes.md`) and the decoder are currently
absent from `work/`.
It also answers, for Pool of Radiance, the experiment `docs/117-save-conversion.md`
proposes for Curse ("decode DOS `ECL*.DAX` and diff against the C64 disks") —
the technique works, and the answer is "the same bytes".

**UNKNOWN: why the other sixteen differ.** The experiment is cheap and ours:
disassemble both sides with `ecl6.py`, which reaches 100% of every byte, and diff
the instruction streams rather than the bytes. A uniform offset shift would say
the C64 relaid a table; scattered differences would say the ports were compiled
from edited sources.

### 2. `88 13` is the format's own header word, not a load address — CONFIRMED

Every one of the 30 C64 `ECL` files begins `88 13 01 01`, i.e. the word **5000**.
`docs/141-dos-savegame.md` already records that every DOS block opens the same
way. `goldbox/d64.load_payload` strips those two bytes *as a PRG load address*; the
outcome is right (the bytecode does start at +2) and the name is wrong — the
files are loaded at `$9900`, not `$1388`, and `ECL64`/`ECL65`, which are 6502
code rather than bytecode, carry `00 10` there instead.

The header is **five 4-byte records**, `[word][01 01]`, which is what the
repository found on DOS and what the (now-lost) `work/reports/ecl-opcodes.md`
called "the five-word entry header". On the C64 records 1–4 are plain absolute addresses in
the block's own `$9900` space — `ECL12` reads `$99B9 $9AB7 $9914 $9960`, and the
repository lists exactly those four for its DOS block 18.

**This settles their largest open item.** They read the high bit of `$99B9` as a
flag, masked to `$19B9`, could not make the result land inside the block, and
recorded the entry points as "not statically reducible … UNCERTAIN". They are
absolute addresses, base `$9900`. Their empirically fitted label formula
`file_offset = label − 0x98F1` is that base out by fifteen bytes.

Nothing of ours needs changing except the wording where the two bytes are called
a load address. **That is `goldbox/d64.py`'s and `goldbox/geo.py`'s owner's call, not
this document's** — flagged, not edited.

### 3. GEO wall slices have names, and slice 4 is the door — CONFIRMED for slice 4

`goldbox/geo.py` decomposes a wall nibble as `wallset = (v−1)//5`, `slice = (v−1)%5`
and gives the five slices no meaning. The repository derives the same
decomposition independently on DOS and adds an order: **`[base, window, gate,
plain, door]`**.

Measured across all 29 of our `GEO` files, every wall edge against its own
passability field:

| slice | their name | edges | crossable | locked or barred |
|---|---|---|---|---|
| 0 | base-ledge | 3010 | 17.0% | 9 |
| 1 | window | 1924 | 23.6% | 2 |
| 2 | gate / arch | 1673 | **62.3%** | 0 |
| 3 | plain stone | 5178 | **2.8%** | 8 |
| 4 | door | 1013 | **85.6%** | **123** |

**Slice 4 is the door slice: 123 of the game's 142 locked and barred edges are
on it, and 86% of them are crossable.** Slice 3 is the commonest and almost never
crossable, which is "plain stone"; slice 2 is crossable and never locked, which is
an arch. CONFIRMED for 2, 3 and 4.

Slices 0 and 1 are **UNKNOWN**: passability does not separate them. What would
settle it: render one edge of each slice from `WALLSET`/`WALLDEF` and look, which
is the same render-to-validate step the repository used.

This belongs in `docs/88-map-files.md` and `goldbox/geo.py`. Flagged, not edited.

---

## Where it contradicts us

### DOS record offset 284 is current movement, not a class group

`FINDINGS_pool_of_radiance.md` claims **"CHRDATA offset 284 = AD&D class group
(9 = Warrior, 6 = Priest, 12 = Rogue/Mage)"**, and builds a class-resolution
heuristic on top of it.

**It is `movement_current`.** `goldbox/dos_layout.py` has `0x11C` (= 284) as current
movement, graded from 24 real DOS records: **12 for everyone unencumbered and 6
for SILAS, who wears plate mail**. `docs/127-community-formats.md` has the same
byte as the community workbook's `MOV_Current`, independently. The DOS class
byte is at `0x02F`.

The reason their reading looked right is that 12, 9 and 6 are the AD&D encumbered
movement rates, and armour weight correlates with class: a fighter in plate reads
9 or 6, a magic-user in robes reads 12. **SILAS refutes it directly** — a fighter
reading 6, which their table would call a priest.

Settled; no experiment needed. Two of our sources agree and one of them is
measured on records they do not have.

### Their ECL opcode names are wrong from `$0A` to `$12` and `$21` to `$27`

Their table names 40 opcodes from the DOS dispatch chain. Against ours:

| ours | theirs | verdict |
|---|---|---|
| `$00`–`$09`, `$13`–`$1E`, `$20`, `$25`, `$26` | same effect, different words | agree |
| `$1F` unused, no handler | "no `cmp al,0x1F` exists — gap in the ladder" | **agree, independently** |
| `$0A LOADCHAR` | `MOVE_PARTY` | ours |
| `$0B LOADMON` | `ADD_NPC` | ours |
| `$0C SETUPMON` | `LOOP_INIT` | ours |
| `$0D APPROACH` | `LOOP_NEXT` | ours |
| `$0E PICTURE` | `START_COMBAT` | ours |
| `$0F INPUTNUM` | `SHOW_PICTURE` | ours |
| `$11 PRINT` / `$12 PRINTCLEAR` | `DISPLAY_WINDOW` ×2 | ours |
| `$21 LOADFILES` | `SET_AREA_ENCOUNTER` | ours |
| `$23 SURPRISE` | `RANDOM_PICK` | ours |
| `$24 COMBAT` | `AREA_STEP_EVENT` | ours |
| `$27 TREASURE` | `LOAD_RESOURCE_PIC` | ours |

Ours wins twice over: the operand counts come from the VM's own `$1625` table
checked instruction-by-instruction against 16,233 decoded instructions, and the
DOS guide's independent list (`docs/128` §"sixty-two for sixty-two") agrees with
all 62 mnemonics. Their names appear to be slid by a few positions in two runs.
Their **operand counts**, by contrast, agree with ours almost everywhere, which
is what a handler-shape analysis would get right.

Also: they say the dispatch chain covers `$00`–`$3D` contiguously, which matches
our 62 opcodes exactly, and then name only 40 of them. `$1F` unused is agreed by
three sources now.

### Their GEO plane 2 and plane 3 readings

They read plane 2 as a backdrop/texture id (`$00` open street, `$8x` building
variants) and plane 3 as one interactive flag per direction. Ours is
`bit 7 = indoor` plus a **per-square ECL script id** (proved by `AND mask` then
`ONGOTO` in the scripts themselves) and **two bits per direction** of
passability. Ours is finer, proved from the scripts, and corroborated by the
Gold Box guide's `GB_GEO` (`docs/128`). Their `$8x` is our bit 7; their `$0B` is
our script id 11.

No experiment needed. Recorded because their reading is plausible enough to
mislead someone reading it first.

---

## What they have that we do not

Leads, at the confidence a third-party document earns.

| what | value | confidence |
|---|---|---|
| **`GAME.OVR` is a Turbo Pascal `FBOV` overlay of 34 units**, with the INT 3Fh descriptor layout, 675 functions found by the `55 89 E5` prologue (**not** `8B EC` — why a naive scan finds none), 404 entry points, and a per-unit role table | the structural map anyone disassembling DOS Pool of Radiance would otherwise build from scratch. Bears on #59 (Map the DOS saved game, not just the character record) | PROBABLE |
| **Far-call resolution**: `START.EXE` has zero relocations, so resident `seg:off` → file offset `0x200 + seg*16 + off`; `seg $AF8` is the Turbo Pascal SYSTEM runtime and its 1792 calls are language, not game | one rule that makes every `lcall` in the overlay legible, and separates runtime from game logic | PROBABLE |
| **Named resident segments**: `$BA` video, `$B0` RNG, `$709` graphics/text, `$7C` ECL loader, `$802` `.DAX` open, `$3D0` combat spawn, `$3D5` encounter, `$2B` the ECL VM's operand helpers | a vocabulary for reading the overlay | PROBABLE |
| **`LoadWallSet` and `Load3DMap` are in unit `0x3bd`** (strings at `0x2f6ac` / `0x2f995`) | `docs/141` knows both by their error strings only; this says where the code is | PROBABLE |
| **The DOS ECL VM's globals**: PC `[0x49ED]`, buffer far-pointer `[0x49DE]`, opcode latch `[0x6F7F]`, stop flags `[0x442E]`/`[0x49FF]`, the six-byte compare-flag bank `[0x6F78]`–`[0x6F7D]` | the DOS mirror of our `$6E45` flags and `$1590` loop | PROBABLE |
| **The EGA image format**: `u8 width_px`, three header bytes, 4bpp, two pixels per byte, high nibble first, standard EGA 16 palette; `8X8D` sheets need an 8-byte header, not 4 | with it, every DOS art file is renderable. Bears on #57 (Carry the character portrait across ports) | PROBABLE |
| **Which DAX holds which art**: `CHEAD` portraits, `CBODY` a 128-frame player combat animation of weapon poses, `BODY1-8`/`CPIC1-8` monster combat sprites, `COMSPR` tactical figures, `8X8D1-8` wall tile sets, `WALLDEF1-8` the face composition tables | #57 (Carry the character portrait across ports) needs to know what the DOS art set *is* before it can be numbered | PROBABLE |
| **`BACPAC.DAX` is 40 wilderness terrain tiles at 24×24** — grass, rock, boulders, water — and is *not* the city backdrop | a target count for #11 (Draw the wilderness on the automapper) / `docs/137`: the C64's equivalent is `SQRPACI0n`/`SQRDATA0n`, and 40 icons is what to expect to find | PROBABLE |
| **The first-person view is a 40-column grid compositor, not geometry** — wall rows are 40-character strings, walls are drawn as column-range × row-range tile fills between rows 24 and 32, and no unit pairs perspective arithmetic with the blitter | closes "where is the 3-D maths" with "there is none" | PROBABLE |

## What agrees with us and adds nothing

Worth recording so nobody looks twice.

* **The DAX container and its RLE codec.** Their `kit/dax.py` and our
  `goldbox/dos_savegame.dax_index` / `dax_unpack` are the same format, field for
  field and opcode for opcode — `u16` directory length, 9-byte entries
  `{u8 id, u32 off, u16 unpacked, u16 packed}`, then `c < 0x80` copies `c+1`
  literals and `c >= 0x80` repeats the next byte `256−c` times. Two independent
  derivations, identical answer.
* **`GEO` is 16×16 with four planes**, planes 0 and 1 holding N/E and S/W wall
  nibbles. They considered 32×32 and withdrew it. Ours has been settled since
  `docs/88`.
* **The 63-byte DOS item record**, which they reach from the treasure files and
  we from the character files. They read `ITEM1`–`ITEM4` and count 110 items;
  ours reads `ITEM1`–`ITEM8` and reproduces 157 of
  163 C64 records, asserted in `tests/test_dosbox.py`. Ours is the wider sample.
* **The ECL text codec is 6-bit**, four characters per three bytes. Ours has been
  decoded since the first ECL pass; theirs is the DOS closed form. Given §1 —
  the blocks are the same bytes — the two codecs must be the same codec, which
  is now a consequence rather than an assumption.
* **The Gold Box engine is shared across the family** and one codec unlocks all
  of it. Known.

## The method, as a method

The repository's other half is `METHODOLOGY.md` and a §6 in the ECL document
generalising the bytecode decode. Read against `docs/144-decoding-a-new-title.md`
it is mostly the same advice arrived at separately, with three things ours does
not say in those words:

* **"Find the interpreter, not the data, first"** — score function prologues by a
  *selector signature*, a contiguous run of `cmp al,imm8` with a byte-buffer
  read, and the dispatch loop falls out.
* **A jump-table scan returning nothing is a signal, not an absence** — Turbo
  Pascal and early C compile a dense `CASE` to a compare chain.
* **Name opcodes by their side effects on known globals before decoding
  operands** — a PC write is a jump, a stop-flag set is END, a `FreeMem` is
  teardown. They claim 80% of an opcode set from effects alone; on their own
  showing (above) the ones they got wrong are exactly the ones where two opcodes
  have similar effects.

Their model-routing advice is about a model that no longer exists and is not
transferable.
