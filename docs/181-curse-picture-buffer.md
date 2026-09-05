# The picture buffer at `$6300`, which a Curse save carries as `+$1800`

What the 1024 bytes at `+$1800`-`+$1BFF` of a Curse of the Azure Bonds
`SAVEAZURE` are, for `#283 (What Curse keeps in the area map region at +$1800
is unread, and a conversion writes zeroes there)`. They had been called "the
area map the engine builds on load" and "explored-map state" since
`#32 (One Curse session, to get a party with items)`, on the strength of the
region changing between two saves. It is nothing to do with the map.

**It is `ANIMATE00`'s picture buffer: the decoded glyphs and colours of
whatever picture is in the view window, at whatever frame its animation had
reached when the save was written.** On `ENCAMP` that picture is always
`PIC1D`, the camp scene with the tent and the fire, so every engine-written
Curse save carries one frame of a campfire there. CONFIRMED three ways: the
routine read in full, both engine-written specimens matching a decoded frame
byte for byte, and a driven session in which nothing read the region before
the engine zeroed it. Silver Blades keeps the same buffer, and its specimens
carry `PIC3B`.

**Nothing is lost by a conversion writing zeroes.** The engine never reads
what a save put there: a full decode zeroes the buffer first, and between a
load and the first `ENCAMP` the region is not touched at all. So this is the
second of `.claude/rules/conversions.md`'s three reasons -- the destination
derives it -- demonstrated in the running game rather than argued.

## Where it sits, and why it is in the save at all

The save is one KERNAL `SAVE` of `$4B00`-`$67FF`. `CAMP $0CEC`-`$0CFC` (and
`GEN $1FCC`-`$1FDC`, the same sequence for the front end) store `$4B00` in
`$03EE/$03EF`, put `$6800` in X/Y, and call `LIBRARY $317A`:

```
$317A  JSR $31A6 / JSR $319F          keep the registers, SETNAM
$3180  LDA #$0F / LDX $038E / LDY #$FF / JSR $FFBA    SETLFS
$318A  LDA $03EE / STA $FD / LDA $03EF / STA $FE      start = $4B00
$3194  JSR $31B0 / LDA #$FD / JSR $FFD8               SAVE to X/Y = $6800
```

Everything from the header to the roster goes out in one block, and
`$6300`-`$66FF` is simply what lies between the item pages and the roster.
The loader puts no file there: `LIBRARY`'s load-address table (file
`+$15B6` low bytes, `+$15CF` high bytes, the same shape as Pool of
Radiance's at `$41BE`/`$41D7`) reads

| slot | kind | Curse loads it at | Pool of Radiance |
|---|---|---|---|
| 3 | `SECSET` | `$BA00` | `$6500` |
| 5 | `PIC` | `$6F00` | `$8C00` |
| 11 | `ANIMATE` | **`$6800`** | `$8400` |
| 12 | `MON` | `$7C00` | `$6B00` |
| 15-17 | `WALLSET` | `$BB50` / `$BCE0` / `$BE70` | `$6650` / `$67E0` / `$6970` |

so the region is not a loaded character set either, which the `55`/`AA`
patterns in it suggested for a while (the negative results are below).

## `ANIMATE00`, which owns it

883 bytes of 6502, on every side, run at `$6800` with a jump table at its
head: `$6800` and `$6806`/`$6809`/`$680C` draw a picture in one of four
places, `$6803` advances the animation one step. Its variable block at
`$6815` is

```
$6815  00        frame kind: 0 = an 11 x 11 picture, 1 = a 5-row portrait
$6817  D8        colour RAM page
$6818  00 63     the buffer: $6300
$681A  00 CC     the screen page: $CC00
$681C  D0        the charset page, under the I/O area
```

`CAMP $0F5A`-`$0F64` is the `ENCAMP` caller: `LDX #$05 / LDA #$1D / JSR
$43E5` asks the loader for `PIC1D` into slot 5, then `JSR $6800 / JMP $6803`.
`DUNGEON $283B`-`$2849` calls the same two entries for a picture shown in
the world.

**The decode, `$6931`-`$69B7`.** With `$FD/$FE` on the picture:

1. `$6931`-`$6947` zero the frame counter at `PIC+$33` and load `$D021`,
   `$D022`, `$D023` from `PIC+$34`-`+$36`;
2. `$6962`-`$6980` zero four pages from `$6300` **and 65 bytes more,
   `$6700`-`$6740`**;
3. `$6982`-`$6996` XOR-unpack the glyph stream (source `PIC+$38`) onto
   `$6300`: 968 bytes, 121 cells of 8;
4. `$6999`-`$69B4` XOR-unpack the colour stream onto `$6300 + $3C8` =
   `$66C8`: 121 bytes, which run to `$6740`;
5. `$69FA`-`$6A3A` copy the 968 glyph bytes into the charset at `$D4xx`
   (`$681C + 4`, with `$01 &= ~4` around the copy so the RAM under the I/O
   area takes it), `$6A46`-`$6A7A` copy the 121 colour bytes into colour RAM
   eleven per row.

**The animation, `$6923` and `$6A7C`-`$6AB9`.** `PIC+$33` counts frames.
`$6923` looks the count up in the table at `PIC+$00` (`41 42 43 44 00` for
`PIC1D`); a non-zero entry sends the next call through `$6982` again, which
applies one more pair of streams -- a glyph delta and a colour delta -- onto
the buffer; a zero entry sends it through the full decode, which starts the
cycle over. The delay per frame is `PIC+$20 + (entry - $41)`, looped
`PIC+$2C` times against the jiffy clock. So the buffer holds frame 0, then
1, 2, 3, then 0 again, and the save takes whichever is current.

**The unpacker, `$6AC0`.** A stream is a run of count bytes: `n` below `$80`
means `n` literal bytes, each XORed into the destination; `n` from `$80` up
means the next byte XORed in `256 - n` times; `0` ends the stream. XOR onto
a zeroed buffer is the picture; XOR onto the picture is the next frame.
`tools/cursepic.py` is that routine transcribed.

## The format, as the engine reads it

| offset | what |
|---|---|
| `+$00` | frame table, one byte per frame: `$41`, `$42`, ...; a zero ends the cycle |
| `+$20` | per-frame delay, indexed by `entry - $41` |
| `+$2C` | delay loop count |
| `+$2D`, `+$2E` | width and height in cells, 11 and 11 |
| `+$2F` | glyph bytes, 16-bit, 968 |
| `+$31` | cell count, 121 |
| `+$33` | frame counter, written by the engine as it animates |
| `+$34`-`+$36` | background and the two shared multicolour registers |
| `+$38` | the streams: glyphs then colours for the full frame, then a pair per delta frame |

44 of 49 `PIC` files on the Curse sides decode this way, every one of them
11 x 11 with the streams ending on the file's last byte and the decoded
frame count equal to the table's; 40 of 49 on the Silver Blades sides. The
refusals -- `PIC64` and `PIC78`-`PIC7B` on Curse, `PIC5A`, `PIC64` and
`PIC70`-`PIC77` on Silver Blades, 736 or 2679 bytes -- carry no such header
and are drawn by something else.

## The specimens

`tools/cursepic.py match SAVE PIC` compares a save's region with every frame.

| specimen | non-zero bytes | matches | differing bytes |
|---|---|---|---|
| `WISH-SPEC-curse-h-engine-resave` (before the walk) | 526 | `PIC1D` frame 1 | **0 of 1024** |
| `WISH-SPEC-curse-h-engine-resave-walked` | 524 | `PIC1D` frame 3 | **0 of 1024** |
| either against the other three frames | | | 19 to 27 |
| `WISH-SPEC-ssb-d-engine-resave` and `-walked` | 594 | `PIC3B` frame 0 | **0 of 1024** |
| `WISH-SPEC-ssb-d-converted-resave` and `-walked` | 594 | `PIC3B` frame 0 | **0 of 1024** |
| `work/issue192/CURSEH.D64`, the save Wish built | 0 | nothing | 524 to 526 |

So the 23 bytes the two Curse saves differ in, at cells in columns 2-7 and
rows 7-10 of the eleven-wide grid and five of the colour bytes, are frame 1
against frame 3 of the fire -- and nothing about the two squares the party
walked between them. The "526 non-zero bytes the engine writes from a save
that held zeroes" are frame 1 of the camp picture, which `CAMP` decodes on
every `ENCAMP` before the player can reach `SAVE`. Silver Blades' `PIC3B`
has one frame, which is why its four specimens agree.

## Watched in the running game

`tools/cursepicrun.py`, pool slot 1, 2026-09-05, loading `CURSEH.D64` --
the Wish-built save whose region is all zeroes -- through the game's own
front end. The buffer was then overwritten with `$A5` x 1024 through the
monitor, so any read or copy of it would show, and two counting
checkpoints were armed on `$6300`-`$66FF`, one for loads and one for stores.

| step | loads | stores | the buffer | `$6700`-`$6740` |
|---|---|---|---|---|
| after `LOAD SAVED GAME` | -- | -- | 0 non-zero, as the file | roster intact |
| `BEGIN ADVENTURING`, the world drawn | 0 | 0 | 1024 x `$A5` | intact |
| turn right; step forward, blocked; `AREA` drawn | 0 | 0 | 1024 x `$A5` | intact |
| `ENCAMP`, stopped on the first store | **0** | 1 | 1023 x `$A5` | scratch |
| 0.8 s later | 3950 | 2926 | **`PIC1D` frame 1, 0 of 1024 differ** | the picture's colour bytes |
| 1.6 s later | 8556 | 6508 | 259 non-zero: mid-way through a full re-decode | zero |
| 2.4 s later | 11840 | 7744 | frame 1 again | the colour bytes |

The first store was at PC `$6973` with `CAMP` at `$0800`, `$FB/$FC` =
`$6300` and `$FD/$FE` = `$6F00`, X = 4: the `STA ($FB),Y` of the zero-fill
at `$6971`, one byte in, with the load count still zero. **Three runs, three
times the same stop and the same zero.** Between a load and the first
`ENCAMP` the saved content is never read; at `ENCAMP` it is zeroed before
it is read. The camp screen drew correctly over it in every run, which
`work/issue192/run1/05-encamp.png` had already shown from the same save.

**A checkpoint stop ends VICE's monitor for the rest of the run.** After the
one-shot stop and a resume, every later read timed out -- on fresh
connections in runs 1 and 2, and on the connection that caught the stop in
run 3 -- while the game ran on and the screenshot showed the camp scene
drawn. Run 1 got three samples in before that (frame 1, a buffer caught
mid-way through a full re-decode, frame 1 again); the tool now takes the
first store and the frame series in separate runs, the series with
`--no-stop` and no stopping checkpoint at all. **The series has not been
taken**: runs 4 and 5, both `--no-stop`, never reached the world --
`BEGIN ADVENTURING` left the drive reading with no side prompt on screen,
where runs 1 to 3 had `SIDE2` asked for and attached within seconds -- and
the night's emulator budget went to the measurement that mattered. So the
buffer cycling through all four frames in the machine rests on run 1's
three samples and on the two specimens being frames 1 and 3: PROBABLE in
the machine, CONFIRMED from `$6923`-`$6AB9` and the decode.

## The roster page is scratch until the save rebuilds it

A side finding, not chased. At the first store, before the picture had
touched it, `$6700`-`$6740` already held eight-byte groups like `de db db de
d8 d8` -- glyph rows, not roster blocks -- and 0.8 s later it held the
picture's last 65 colour bytes, as step 4 of the decode says it must. Both
engine-written specimens hold an intact roster at `+$1C00`. So `CAMP` uses
the roster page as working memory and rebuilds the roster before `SAVE`
writes it, which is one more reason a conversion's roster page cannot be
read back as the engine's own arithmetic (`.claude/rules/testing.md`).

## Negative results

* **Explored squares.** Refuted: the region does not change as the party
  walks. Zero loads and zero stores across a turn, a step and `AREA`, and the
  two specimens' difference is two frames of one picture.
* **A character set loaded from disk.** The `55`/`AA` byte patterns are
  multicolour glyph rows, but nothing loads at `$6300`: the loader table
  puts `SECSET` and the `WALLSET` pieces at `$BA00`-`$BFFF` in Curse.
* **A table the engine indexes.** `tools/absrefsweep.py
  curse-of-the-azure-bonds 6300 66FF` finds 112 absolute operands into the
  window over 411 files, and every one is a mis-phased byte pair (`8D 63` in
  `STA $xx63`, and the like) or bitmap data. The buffer is reached only
  through `$6818/$6819` and the self-modified `LDA $6300,Y` at `$6A31`.
* **The 3D view.** Refuted the same way: the view changed between the two
  specimens (facing west, then east) and the region changed by 23 bytes,
  all of them in the fire.

## What a conversion should write

**Zero, as it does.** That is a measured zero, not an inherited one: the
engine zeroes the buffer itself before every full decode and reads nothing
from it before then. Nothing on the DOS side corresponds -- this is a C64
display buffer, not a record of anything the party has done -- and a player
arriving with zeroes there sees the camp scene drawn from `PIC1D` exactly as
a player whose save holds frame 1 does.

Writing the decoded `PIC1D` frame instead would make a converted save
byte-identical to an engine-written one, and `tools/cursepic.py` could
produce it off the player's own disk. There is no reason to: it would be
copying the game's art into the save to satisfy a diff, and the region
should be relabelled rather than filled. The labels that still call it the
map, for whoever owns those files:

| where | says | should say |
|---|---|---|
| `tools/cursesavediff.py` `REGIONS`, `tools/ssbsavediff.py` | "the area map the engine builds on load" | `ANIMATE00`'s picture buffer: the camp scene's current animation frame at the moment of the save |
| `goldbox/c64_save.py` module note and the `CURSE_OF_THE_AZURE_BONDS` note, `goldbox/README.md` | "a page of map memory", "map memory at `+$1800`" | the picture buffer |
| `goldbox/dos.py` near the `7424` accounting | "the area map it builds" | the picture buffer |
| `tools/cursedisk.py`, `tools/ssbdisk.py` docstrings, `tools/README.md` rows | "the explored map", "the area map" | the picture buffer |
| `docs/116-second-game.md` §3 | "the region above `$6300` did change between two saves, which is what slots 8-11 would do" | it is the picture buffer, and it changes because the picture animates |
| `docs/175-silver-blades-save-conversion.md` | "594 [engine] the area map the engine builds on load" | `PIC3B` frame 0, 594 non-zero bytes |

## Tools

| tool | what |
|---|---|
| `tools/cursepic.py` | `frames PIC [--png DIR]` decodes a picture and renders each frame; `match SAVE [PIC]` says which frame a save's region holds and exits 0 only on a byte-for-byte match |
| `tools/cursepicrun.py` | the driven session above, with its counting checkpoints and the one-shot stop on the first store |
| `tools/absrefsweep.py` | the census that showed no overlay names the window |
