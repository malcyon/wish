# The DOS saved game's variable array is the ECL VM's memory, at the VM's own addresses

The question behind `#218 (Three live regions of the DOS saved game are
named but not understood)`: three regions of `SAVGAM<slot>.DAT` were known
to be live and engine-written, and nobody knew what wrote them or why.
Answered by reading the engine's VM out of `GAME.OVR`, reading the scripts
that drive it, and then watching both under DOSBox-X.

**The answer -- CONFIRMED, by the code, the script text and the running
game: the 5120-byte array at file offset 1 is three heap blocks the ECL VM
addresses as `$4900`-`$4CFF`, `$6B00`-`$6EFF` and `$9700`-`$98FF`.** The
project had named the second and third blocks `$4D00`-`$52FF` as if the
array were one contiguous range, and that name is what hid every one of the
three regions: under their real addresses they are words the C64 side of this
knowledge base had already read.

| region, as named before | is | holds | written by | grade |
|---|---|---|---|---|
| `$4FD2`, `$4FD3` | `$6DD2`, `$6DD3` | how many five-minute rest passes between interruption checks, and the percentage chance of one | the area script's entry 2, on ENCAMP | CONFIRMED |
| `$507A`-`$507C` | `$6E7A`-`$6E7C` | the overland script's loop registers while it searches its special-square table | `ECL1A` entry 1, on every overland step | CONFIRMED |
| file bytes 12804, 12805 | `$C04E`, `$C04F` | the wall-art nibble in front of the party, and the square's attribute byte | the step routine, from the `GEO` planes | CONFIRMED |

Nothing in any of the three is something a conversion loses: the first is
zero between camps in the running engine, the second is rewritten before it
is read, and the third is recomputed on the first step or turn.

Grades follow `docs/50-experiments.md`'s scale. "The build" is the 1.3
`GAME.OVR` in the player's copy of *Forgotten Realms: The Archives*; file
offsets are into it, and `tools/dosovrmap.py` turns them into `seg:off` and
back. Runs are under `work/issue218/`.

## The address classes

Every VM load and store begins with the classifier at `GAME.OVR:0x7BCE`
(overlay unit `0x2B`), which sorts a sixteen-bit address into five classes:

```
7bd8  cmp [bp+6], 0x4900 / 0x4CFF   -> 0
7bea  cmp [bp+6], 0x6B00 / 0x6EFF   -> 1
7bfc  cmp [bp+6], 0x9700 / 0x98FF   -> 2
7c0e  cmp [bp+6], 0x9900 / 0xB6FF   -> 3
                                       4 otherwise
```

The word store at `0x814A` then does, per class: `les di, [0x49D2]; add di,
2*addr; mov es:[di+0x6E00], dx` -- `2*(addr - $4900)`, wrapping -- and the
same with `[0x49D6]` and `+0x2A00` (`2*(addr - $6B00)`), `[0x49DA]` and
`-0x2E00` (`2*(addr - $9700)`), and the script buffer `[0x49DE]` with
`+0x6700` (`addr - $9900`, one byte wide). Those are the four heap blocks the
save routine writes, in file order (`#218 (Three live regions of the DOS saved game are named but not understood)`'s first comment has the
`BlockWrite` list). Class 4 is engine state reached by address: the load
routine at `0x82DF` hands back `$C04B`, `$C04C`, `$C04D`, `$C04E`, `$C04F`
as `[0x6AAD]`, `[0x6AAE]`, `[0x6AAF] >> 1`, `[0x6AB0]`, `[0x6AB1]`
(`0x83CA`-`0x8416`), `$033D` as the raw facing `[0x6AAF]`, and `$00FB`,
`$00FC` as `[0x6F6A]`, `[0x6F6C]`; the store translates a facing 0-3 to
0/2/4/6 on the way in (`0x8264`-`0x82A3`).

So file word `k`, at offset `1 + 2k`:

| words | named until now | VM address | on the C64 |
|---|---|---|---|
| 0-1023 | `$4900`-`$4CFF` | the same | the same |
| 1024-2047 | `$4D00`-`$50FF` | `$6B00`-`$6EFF` | the resident character record `$6B00`-`$6D43` (`41-memory-regions.md`), then engine variables and the script registers `150-departing-prologues.md` lists |
| 2048-2559 | `$5100`-`$52FF` | `$9700`-`$98FF` | the workspace where monster-group names are composed (`50-experiments.md`) |

`goldbox.dos_savegame.word(save, address)` and `tools/dossavcensus.py` still
take the contiguous name; `tools/dosvmwatch.py`'s `vm_address()` translates
it. The renaming that matters:

| named until now | VM address | already known as |
|---|---|---|
| `$4FD2`, `$4FD3` | `$6DD2`, `$6DD3` | `113-world-map.md` item 5's GUESS; `50-experiments.md`'s "encounter-frequency reading ... stays GUESS" |
| `$5079`-`$507D` | `$6E79`-`$6E7D` | the VM's own working registers, `150-departing-prologues.md` |
| `$5082` | `$6E82` | the departing square's attribute, `118-debug-mode.md` |
| `$5200`, `$5208` | `$9800`, `$9808` | the name workspace `ECL14` walks 10..18 |
| `$507F`, `$5080`, `$5203`, `$5204`, `$5207`, `$520A`-`$520E` | `$6E7F`, `$6E80`, `$9803`, `$9804`, `$9807`, `$980A`-`$980E` | `ECL1A`'s `ENCMENU [$9805], [$9803], ... [$9807]` names three |
| `$4DB8`, `$4DC3`, `$4E0C` | `$6BB8`, `$6BC3`, `$6C0C` | offsets `0xB8`, `0xC3`, `0x10C` into the C64's resident character record |

`141-dos-savegame.md` used to say that `$4B00`-`$52FF` had no C64
counterpart because no script names an address at or above `$4AF9`. That was
true of the names and not of the bytes: 28 of the 30 DOS `ECL*.DAX` blocks
name `$6DD2`, and all 30 name `$6E79`.

## `$6DD2`/`$6DD3`: the rest-interruption interval and chance

**Written** by each area's script in entry 2, "before camping", through the
VM store. The only engine-side writer, found with
`tools/dosptrfields.py --pointer 0x49d6`, is the area-init routine at
`GAME.OVR:0x7689`, which zeroes both (`0x76FF`-`0x7710`) beside `[0x49ED] =
0x9900`. The four measured pairs are the four scripts' text (addresses are
the C64 listing's; the DOS `ECL00` block carries a three-byte insertion and
the DOS `ECL15` a two-byte deletion ahead of these, so their operands sit
three bytes later and two bytes earlier, and the statements are the same):

| area | script | statements | pair measured over 21 containers |
|---|---|---|---|
| New Phlan | `ECL00 $9A79` | `SAVE 1, [$6DD2] / SAVE 101, [$6DD3]` | (1, 101) |
| the Slums | `ECL14 $9A3C` | `SAVE 24, [$6DD2] / SAVE 24, [$6DD3]` | (24, 24) |
| Sokol Keep | `ECL15 $9A34` | `SAVE 2, [$6DD2] / SAVE 1, [$6DD3]` | (2, 1) |
| the overland | `ECL1A $B0F3` | `SAVE 10, [$6DD3] / SAVE 96, [$6DD2]` | (96, 10) |

**Read** by the rest loop, `GAME.OVR:0x24A66` (unit `0x8C` entry `0x2A`,
called from the camp menu at `0x1802E`). Each pass consumes five of the rest
request's field 1 (`0x24246(1, 5)`), advances the clock by five of the same
field (`0x241A1(1, 5)`, field 1 of the seven-digit clock at `$49C6` being the
minute units per `142-dosbox-x-debugger.md`), runs the healing and expiry
passes, and then:

```
24b9f  cmp word es:[di+0x5A4], 0     ; $6DD2 == 0: never interrupt
24ba7  inc word [0x49FB]             ; passes since the last check; a DS global, not saved
24bb2  cmp ax, es:[di+0x5A4]         ; fewer than $6DD2: not yet
24bbb  mov [0x49FB], 0
24bc4  lcall 0xB0:0x48 (100, 1)      ; d100
24bcf  cmp ax, es:[di+0x5A6]         ; roll > $6DD3: nothing happens
24bd6  lcall 0xBA:0x17E3             ; a frame, then the string at unit offset 0xC79
```

The string is "The Party is rudely interrupted!", the rest ends, and the
routine returns 1 to the camp menu, which runs the script's entry 3 -- the
one `tools/eclwalk.py` already labels "camp interrupted". So the Slums are
checked every two hours at 24%, the overland every eight hours at 10%, Sokol
Keep every ten minutes at 1%, and New Phlan every five minutes at 101%,
which a d100 never beats: **resting in the streets of New Phlan is
interrupted on the first pass, every time.**

Why the corpus partitioned perfectly and the live image read zero: a save is
taken from inside ENCAMP, so entry 2 has just run and the file carries the
pair; the area-init routine zeroes it on load and nothing writes it until the
next ENCAMP. That is `142-dosbox-x-debugger.md`'s "24 in the file, 0 live".

**Watched.** `tools/dosvmwatch.py --save work/p59-wallset/ycol --slot C`,
a `BPM` on each byte, then E: `$6DD3` 0 -> 10, then `$6DD2` 0 -> 96, both at
`CS:0CCE` with `03 f8 26 89 95 00 2a` behind it -- the class-1 store at
`GAME.OVR:0x819C`, unit `0x2B` code offset `0xCC9` plus the instruction's
five bytes. `work/issue218/watch1/watch.json`.

**The Slums block is patched on DOS, and the patch is the reason every Slums
specimen holds (24, 24) with `$4A0B` clear.** `50-experiments.md` reads
`ECL14`'s entry 2 as "24 into both when `$4A0B` is 255 and 0 otherwise",
which is what the C64 bytes say. The DOS block (`ECL2.DAX` 20) differs from
the C64 `ECL14` in ten bytes, and two of them are in that entry:

```
$9A24  COMPARE [$6E82], 0
$9A2A  IF<>   (C64: 17)      IF=   (DOS: 16)
$9A2B  GOTO   $9A2F (C64)    GOTO  $9A3C (DOS)
$9A2F  SAVE 0, [$6DD2] / SAVE 0, [$6DD3]
$9A3C  SAVE 24, [$6DD2] / SAVE 24, [$6DD3]
```

On DOS an ordinary square goes to (24, 24) and a special one to (0, 0). On
the C64 both arms of that test reach (0, 0), so a C64 party resting in the
Slums is checked for interruption only with the murder flag set. PROBABLE
that a C64 rest in the Slums is never interrupted otherwise; the experiment
is a long rest there with `$6DD2` watched, filed as a question. The same
diff settles the `IF` polarity the walker assumes -- the next statement runs
when the comparison holds -- because with it every one of the 21 pairs is
predicted, New Phlan's `IF>=` and `IF<>` guards and the overland's
`COMPARE [$49E6], 1 / IF=` included.

## `$6E7A`-`$6E7C`: the overland script's special-square search

`ECL1A` entry 1, the step, at `$9B0A`-`$9B9B`, searches a table of fourteen
squares: nine rows at `$B04A` (y = 10, 11, 12, 26, 27, 28, 14, 16, 29), the
squares per row at `$B061` (2, 3, 2, 2, 1, 1, 1, 1, 1), each square's x at
`$B053`, and a handler index at `$B06A` for the `ONGOTO` that follows:

```
$9B0A  SAVE 0, [$6E7C]                     ; index into the x list
$9B10  SAVE 0, [$6E79]                     ; row
$9B16  COMPARE [$6E79], 9 / IF>= / GOTO $A0DA
$9B21  OP$2A [$B061], [$6E79], [$6E7B]     ; squares in this row
$9B2B  OP$2A [$B04A], [$6E79], [$6E7A]     ; this row's y
$9B35  COMPARE [$6E7A], [$49C4] / IF= / GOTO $9B58
$9B41  ADD 1, [$6E79], [$6E79]
$9B4A  ADD [$6E7B], [$6E7C], [$6E7C]
$9B54  GOTO $9B16
$9B58  ADD [$6E7C], [$6E7B], [$6E7B]       ; end of this row's slice
$9B62  COMPARE [$6E7C], [$6E7B] / IF>= / GOTO $A0DA
$9B6E  OP$2A [$B053], [$6E7C], [$6E7D]     ; candidate x
$9B78  COMPARE [$6E7D], [$49C3] / IF= / GOTO $9B91
$9B84  ADD 1, [$6E7C], [$6E7C]
$9B8D  GOTO $9B62
```

Run by hand against the table at x = 7 or 8, the column the specimens stand
in:

| travel y | row | `$6E7A` | `$6E7B` | `$6E7C` | measured |
|---|---|---|---|---|---|
| 28 | 5 | 28 | 10 + 1 = 11 | 11 | (28, 11, 11) |
| 27 | 4 | 27 | 9 + 1 = 10 | 10 | (27, 10, 10) |
| 26 | 3 | 26 | 7 + 2 = 9 | 9 | (26, 9, 9) |
| 25 | none | 29 | 1 | 14 | (29, 1, 14) |
| 24 | none | 29 | 1 | 14 | (29, 1, 14) |

Five of five, including the two rows that refuted "a copy of y": y = 25 and
24 match nothing, the loop runs off the end, and the last row's y, count and
the total of all nine counts are what is left behind. Nothing reads the
three after the loop.

**Watched.** The same run, a `BPM` on `$6E7A` and one step north from
(7, 28): 34 hits, all at the store above -- 29 from the step's entry-0
passability loop over the table at `$B019`, which uses `$6E7A` too, then 10,
11, 12, 26, 27 from this loop -- and (27, 10, 10) with `$49C4` = 27
afterwards. The overlay moved from segment `3088` to `30F6` during the step;
the code offset did not.

## Bytes 12804 and 12805: `$C04E` and `$C04F`

`#218 (Three live regions of the DOS saved game are named but not understood)`'s first comment found the step routine (`GAME.OVR:0x8EAE`) ending in
two far calls whose results it stores at `[0x6AB0]` and `[0x6AB1]`, file
bytes 12804 and 12805, and did not read the callees. They are:

| entry | `GAME.OVR` | takes | returns |
|---|---|---|---|
| `0x3D5:0x2A` | `0x2ED72` | x, y, facing | `GEO` plane 0 high nibble for facing 0, low for 2; plane 1 high for 4, low for 6; indexed `16*y + x` off the loaded map at `[0x6A5C]` |
| `0x3D5:0x34` | `0x2EE71` | x, y | plane 2, the whole byte |

`88-map-files.md`'s layout to the letter: plane 0 is north/east wall art,
plane 1 south/west, plane 2 the attribute with bit 7 roofed and the rest the
script id. So 12804 is the wall-art nibble in front of the party and 12805 the
square's attribute -- the `$C04E` and `$C04F` the scripts read, which
`tools/eclexitkinds.py` already calls `ATTR`. Both return 0 when
`0x2EC16(x, y)` says the square is off the map and `[0x84DC]` is 0 or 10. The
same two calls recompute them at `0x16E60` (a scripted move with wrap, unit
`0x72`) and `0x171E4` (a turn, unit `0x75`), and `0x2DD1A` recomputes 12805
alone on a redraw with `[0x49FA]` = 1 or `$49E6` nonzero (unit `0x3CA` entry
`0x25`).

**For a conversion, nothing changes**: `141-dos-savegame.md`'s zero is
repaired by the first step or turn. UNKNOWN whether a script's entry 4 can
read `$C04F` on load before any step and see that zero: `ECL09`, `ECL11`,
`ECL16` and `ECL17` read it past their entry-4 marker, in subroutines rather
than on the entry's straight path as far as the listing shows. Experiment: a
`BPM` on the live `[0x6AB1]` across a load of a save with 12805 = 0 in one of
those areas, and see whether it changes before the first key.

## Negative results and leads

* **No engine code names `$6E7A`-`$6E7C` at all.** No `les di, [0x49D6]`
  site reaches displacement `0x6F4`-`0x6F8`, and no immediate `7A 6E`,
  `7B 6E` or `7C 6E` appears in `GAME.OVR` or the unpacked `START.EXE`. The
  three are the script's, and only the script's.
* **The immediates `7A 50`, `7B 50`, `7C 50` in `GAME.OVR` are not
  addresses.** All five are `mov al, 0x7A; push ax` -- effect ids 121-124
  pushed to the spell-effect dispatcher in unit `0xB0`. A grep for the
  contiguous names finds nothing because nothing uses them.
* **`$6DD2` is not the step cost** (`113-world-map.md` item 5's GUESS): the
  overland writes it on ENCAMP and the rest loop is its only reader.
* **The VM load's `$035F` case has no body.** `0x83BA cmp ax, 0x35F; jne +0`
  falls to the return with `[bp-2]` uninitialised (`0x82EF` zeroes `[bp-4]`
  only). `ECL1A` entry 0 compares `$035F` against its 29-entry table at
  `$B019` to refuse a move. SPECULATIVE that the DOS overland's passability
  test compares against a stack leftover; the experiment is a `BP` on that
  case's runtime address during a step and `EV AX` on the way out.
* **`ECL1A` differs from `ECL7.DAX` block 26 in two bytes** (`$9923` and
  `$A578`), neither in the loops above nor near the `$6DD2` writes.

## Provenance

The engine code and the script blocks are the game's own bytes and no save
editor touches them. The 21-container corpus is Donald's played lineage plus
agent-driven resaves of it, so under the 2026-09-04 ruling it is
corroboration and not the claim: the four pairs and five triples above are
predicted by the code and the script text, and the corpus agrees 21 of 21.
The watch run's save is one an agent had the engine write, and the watch does
not depend on its contents beyond the square it stands on.
