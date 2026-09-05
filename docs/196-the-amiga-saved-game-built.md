# Building the Amiga Pool of Radiance saved game

What a player gets: convert a party standing in the Slums at half past nine at
night with half the quests done, and it arrives on the Amiga **in the Slums at
half past nine at night with half the quests done**. Until 2026-09-05 it
arrived on SSI's square in New Phlan at 05:48, because the only
`savgam<letter>.dat` this library could put around a converted party was one
copied off the player's own disk 1.

`#316 (Write the Amiga Pool of Radiance saved game from the source save, so a
converted party arrives where it was standing)`. The companion pages are
[`191-the-amiga-save-disk.md`](191-the-amiga-save-disk.md), which is the disk
the file goes on, [`165-amiga-savegame.md`](165-amiga-savegame.md), which is
the file's shape read out of the save routine, and
[`141-dos-savegame.md`](141-dos-savegame.md), which is the field map -- because
the Amiga's map **is** the DOS one.

## 1. The file, against DOS's

**CONFIRMED**, from the two save routines and from ten Amiga saved games.

| | DOS `SAVGAM<slot>.DAT` | Amiga `savgam<letter>.dat` |
|---|---|---|
| length | 13,137 | 13,141 |
| container number | byte 0, **and** `$5012` | `$5012` only |
| variable array | 5120 bytes at 1, `u16le` | 5120 bytes at **0**, `u16be` |
| the area's script | 7680 at 5121 | 7680 at **5120** |
| x, y, facing | 12801, 12802, 12803 | 12800, 12801, 12802 |
| wall in front, square property | 12804, 12805 | 12803, 12804 |
| -- | -- | **12805-12809, five bytes nothing reads** |
| view type, game mode, party size | 12806, 12807, 12808 | 12810, 12811, 12812 |
| the `CHRDAT` name table | 328 at 12809, 41-byte stride | 328 at 12813, 41-byte stride |

**That is where the four bytes are.** The Amiga is one byte shorter at the
front and five longer in the middle. The five are two the seven-byte square
struct pads to and the first three of wallset entry 0, which the game's own
ten-byte write runs into (`docs/165` §"Pool of Radiance, 13 bytes at 12800");
they are zero in all ten saved games here.

**The name table's entries are eight plain bytes** where DOS spends a count
byte and eight, and **only as many are filled as the party has characters**.
CONFIRMED from `work/issue105`'s `savgamE.dat`, which Amiga Pool of Radiance
itself wrote for a one-character party: `CHRDATE1` in entry 0 and Amiga heap
addresses in entries 1 to 7.

## 2. The DOS map holds here, at the same addresses

**CONFIRMED**, and the corroboration is that the shipped Amiga slot A is a
**New Phlan** party, so every per-area value in it can be checked against
`docs/141`'s figure for New Phlan. Ninety-two of the 2560 words are non-zero
and every one lands where the DOS page says:

| address | Amiga slot A | what `docs/141` says |
|---|---|---|
| `$49FD`, `$49FE` | 11, **10** | the per-area constants `ECL00` writes -- New Phlan's 10 |
| `$4FD2`, `$4FD3` | **1, 101** | the rest-interruption pair, New Phlan's |
| `$4FE1`, `$506D`, `$50F6` | 255, 16, 1 | the three documented constants |
| `$4AFA`-`$4AFC` | 0, `$FFFF`, `$FFFF` | New Phlan's wallset triple |
| `$4AFD`-`$4AFF` | 1, `$FFFF`, `$FFFF` | the wall-index map beside it |
| `$5012`, `$503E` | 3, 6 | the container number and the party size |
| `$5082`, `$5200` | 25, 25 | equal to each other and to tail byte 12804 |
| `$5227`+ | text | `YOU HAVE SURPRISED A PARTY OF  ORCS.` |

`$49FC` is the exception `docs/141` already names: the Amiga reads 1, DOS 6 or
4 by area, the C64 2. Three ports, three values, nothing to convert.

**And the sweep: every one of the 92 distinct non-zero words the ten Amiga
saved games hold is either written by `goldbox.amiga.por_savegame_writes` or
named in `POR_SAVGAM_UNSOURCED`, with none left over.**

## 3. The area's script is on disk 2, in one `ecl.dax`

The 7680-byte script buffer is live on load -- DOS dies in `Load3DMap` when it
holds somebody else's area -- `#60 (Put a converted party where it actually
stood, not where the template stood)` -- so a converted saved game has to
stage the party's own. DOS reads `ECL<n>.DAX` out of the game directory. **The
Amiga keeps every area's script in a single `/ecl.dax` on disk 2, the `POOLDATA`
volume**, so a conversion to Amiga needs the player's **disk 2**, and does not
need disk 1 at all.

**CONFIRMED.** 138,312 bytes: a big-endian index of
`id:u16 offset:u32 stored:u16 unpacked:u16`, 290 bytes of it, 29 entries,
block ids **0-11 and 13-29**, and the last block ends exactly at the end of the
file. Area 30 (`ECL1E`) has no Amiga block -- 29 of the C64's 30, which
[`117-save-conversion.md`](117-save-conversion.md) already recorded -- and 12
is not an area on any port.

### The depacker

Each block is ByteKiller-packed. `goldbox/amiga_dax.py` transcribes the routine
at `/program` hunk 27 + `$7346` (file offset `0x4887A`), read with
`tools/amiga68k.py`: a bit stream consumed **backwards** from the end of the
block, output written backwards from its end, and a trailer of three big-endian
longwords -- unpacked length, checksum, first bit buffer.

| tag | what follows |
|---|---|
| `0` `0` | a 3-bit count, then count + 1 literal bytes |
| `0` `1` | an 8-bit offset, two bytes copied |
| `1` `00` / `1` `01` | a 9- or 10-bit offset, three or four bytes copied |
| `1` `10` | an 8-bit count and a 12-bit offset, count + 1 bytes copied |
| `1` `11` | an 8-bit count, then count + 9 literal bytes |

The stream carries a running XOR of every longword it reads and the routine
ends with `tst.l d5` on it, so a block that unpacks to the stated length with a
non-zero checksum was read wrong. **All 843 blocks of all 23 `.dax` files on
disk 2 unpack to their stated length with a zero checksum** -- the same figure
`docs/117` records from the lost `work/amiga/dax.py`, reproduced by an
independent transcription.

**The oracle that makes it CONFIRMED rather than plausible**: block 0 unpacked,
**from byte 2 on**, is byte for byte the 7468 bytes the shipped `savgamA.dat`
carries in its script buffer, followed by zeros to 7680. Every block opens
`88 13`, `u16le` 5000, which is the ECL load address all three ports use.

## 4. What the running game did with one

Two WinUAE runs on 2026-09-05, `docs/143-winuae-debugger.md` §1, holder
`por316`; screenshots in `work/issue316/`. Both parties were written onto a
freshly formatted `POOLSAVE` save disk with `tools/toamigapor.py --save-disk`,
which reads **only** disk 2.

| | source | what the status line read |
|---|---|---|
| run 1 | C64 `WISH-SPEC-porunconscious1`, the Slums | **`14,4 W 21:22`**, six characters, BRUTUS in red at 0 hit points |
| run 2 | DOS `WISH-SPEC-por-item-granted` slot D, the Slums | **`14,5 S 10:56`**, THRENDER GRONE, AC 1, HP 11 |

The shipped saved game reads `0,4 W 05:48` in New Phlan, so neither of those is
the disk's. Each is its own source save's square, facing and clock.

### The engine's own resave is the strongest evidence, and it names the area

Both parties were camped and saved back through `ENCAMP > SAVE` onto the disk
we formatted. Comparing our container with the one the engine then wrote:

| | run 1 (B against C) | run 2 (D against E) |
|---|---|---|
| bytes differing of 13,141 | **121** | **138** |
| of those, outside the character table | **5** | **5** |

The five are the same five in both runs:

| word | ours | the engine's | what it is |
|---|---|---|---|
| `$49FD` | 0 | 8 / 11 | the wall colours the arriving area's ECL prologue writes |
| `$49FE` | 0 | **9** | the same, and **9 is the Slums'**: `ECL14` opens `SAVE [$6E7D],[$49FD] / SAVE 9,[$49FE]` |
| `$4FD2` | 0 | **24** | the rest-interruption pair, and `docs/141` gives the Slums (24, 24) |
| `$4FD3` | 0 | **24** | " |
| `$507D` | 0 | 8 / 11 | `$6E7D` under its VM name |

**The engine could only have got 9 and (24, 24) from the script we staged.**
They are written by the Slums' own `ECL14` prologue on entry; they are in
neither source save; the shipped Amiga saved game holds New Phlan's 10 and
(1, 101) instead. So the run confirms three things at once, and the third is
the one the ticket is about:

1. the depacker read `ecl.dax` block 20 correctly, because the engine *ran* it;
2. the five words the writer declares as engine-rebuilt **are** rebuilt, now
   measured on the Amiga rather than argued across from DOS;
3. the party is in the area its own save named.

The rest of the difference is byte 6 of each filled name -- `CHRDATB<n>`
against `CHRDATC<n>`, correctly, since the engine saved to a different slot --
and the 33 bytes of Amiga heap scratch after each of the eight names. **The
whole variable array apart from those five words, the whole 7680-byte script
buffer, the square, the clock, all 217 quest flags, the view type, the game
mode and the party count are byte for byte identical**, in both runs.

`AmigaDisk.verify()` is clean before and after each run and the slot list reads
`' BC       '` and `'   DE     '`.

### Two bytes the runs settled that no census could

12803 (the wall in front) and 12804 (the square property) are `fn(x, y,
facing)` and `fn(x, y)`, and nothing offline can compute them, so the writer
writes 0. **The engine's own resave holds 0 in both, in both runs**, at the
square the party loaded onto. Zero there is what the engine itself had, not
merely something it tolerated.

## 5. What is refused, and why refusing is the answer

**A party on the travel grid.** Two bytes of an outdoor Amiga saved game have
never been seen: `docs/141` reads DOS's view-mode byte as 3 outdoors, while the
Amiga's own code names the same byte 1 = 3D and 2 = overland, and there is no
Amiga overland saved game anywhere on this machine to say which is right here.
The wall byte is the second. Writing either would be inventing a value.

*The experiment, and it is one WinUAE run*: load a slot, walk out of New Phlan
onto the travel grid, save to a fresh slot, and read bytes 12803 and 12810 of
the `savgam<letter>.dat` the engine wrote.
`#321 (An Amiga Pool of Radiance conversion refuses a party standing on the
travel grid, because no outdoor Amiga saved game has ever been read)`.

**An area with no block in `ecl.dax`** -- area 30 -- and an area with no row in
`goldbox/areas.py`. Neither has a script to stage.

## 6. What this does not establish

* **The sheet portrait.** `$49FF` gates it on the C64 (`LIBRARY $48A9`, bit 7)
  and on DOS -- `#57 (Convert the character portrait across ports)` -- and the
  writer writes 3 there when a portrait crossed and 0 when none did, mirroring
  DOS. Both runs loaded and played, and the engine
  left the word alone in both -- 3 in run 1, **0 in run 2**. Neither run opened
  a character sheet, so whether Amiga Pool of Radiance draws a sheet portrait at
  all, and whether this word gates it, is **UNKNOWN**:
  `#322 (Nobody has looked at an Amiga Pool of Radiance character sheet to see
  whether it draws a portrait at all)`.
* **A party smaller than six from the C64 side.** Run 2's party was one
  character and came from DOS; the C64 run was six.
* **A saved game with more than one converted slot on the disk.** Each run
  wrote one and the engine added the second.
* **Any Amiga title but Pool of Radiance.** Curse and Silver Blades have their
  own containers (`docs/165`), Silver Blades stages no script at all, and
  nothing here has been run against either.
* **A boot that always works.** Two of five boots of the cracked disk 1 in this
  session came up on a white screen and had to be restarted, with the save disk
  and the sequence otherwise identical. It is the cracked loader rather than
  anything on the save disk -- the third attempt with the same three images and
  the same timing reached the code wheel -- but a driver that assumes one boot
  is one run will be wrong about a fifth of the time.

## 7. Reproducing it

```sh
tools/toamigapor.py work/por2.adf --to B --save-disk work/poolsave.adf \
    --c64 ~/wish-specimens/por-c64/WISH-SPEC-porunconscious1.d64 --provenance
```

`work/por2.adf` is a copy of Amiga disk 2. `--provenance` prints one line per
run of bytes saying where each came from; the run's summary line says
`13141/13141 bytes accounted for, 0 left to nobody`, and a number other than
zero there is the whole of what "no template" means.

`--container <letter>` is still there and is an **experiment rather than a
conversion**: it copies that slot's saved game off the disk on the command
line, so the party is ours and the place is somebody else's, and the run says
so in words.

For the WinUAE half, `docs/191-the-amiga-save-disk.md` §7 is the procedure
unchanged, with `--data-disk` added and `--container` dropped.
