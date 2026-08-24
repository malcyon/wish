# The loaded-files cache

`$4BC0`-`$4BD8` in `SAVEDGAME0`, `$6E13`-`$6E2B` while the game runs. Twenty-five
slots, one per **file kind**, each holding a file number. The slot index picks a
filename stem out of `LIBRARY`; the byte in it is the stem's two hex digits. So
slot 2 holding `$14` means `GEO14` is the resident map, and that is why
`$4BC2` is the area.

Bit 7 is a reload marker, not data. `$FF` means the slot is empty, and it is the
only value that survives a load without being reloaded.

## The twenty-five slots

Read straight out of `LIBRARY`: `$4209,X` maps a slot to a stem, the stem is at
`$4196`/`$41AA` with its length at `$4182`, and the address the file loads at is
`$41BE`/`$41D7,X`. CONFIRMED.

| slot | stem | loads at | what it is |
|---|---|---|---|
| 0 | `GDRIVE` | `$C000` | the movement driver: `GDRIVE01` indoors, `GDRIVE00` on the travel grid |
| 1 | `SQRPACI` | `$0400` | overland square graphics, the travel grid's map block |
| 2 | **`GEO`** | `$0400` | **the resident map** — the area id |
| 3 | `SECSET` | `$6500` | per-area set, from `LOADFILES`' second operand |
| 4 | `SQRDATA` | `$8C00` | the overland square data — the travel grid's "map" |
| 5 | `PIC` | `$8C00` | a full-screen picture |
| 6 | `SPELLN` | `$AF00` | spell names |
| 7 | `SPELLE` | `$A700` | spell effects |
| 8 | **`ECL`** | `$9900` | **the area's script** — the id `NEWECL` switches on |
| 9 | `WALLS` | `$ED50` | wall renderer tables, under the KERNAL |
| 10 | `SPRITE` | `$8400` | a monster or NPC sprite |
| 11 | `ANIMATE` | `$8400` | animation |
| 12 | `MON` | `$6B00` | a monster record, in the character-record window |
| 13 | `BODY` | `$8C00` | portrait body, from record `0x0FF` |
| 14 | `HEAD` | `$9000` | portrait head, from record `0x0FE` |
| 15 | `WALLSET` | `$6650` | wall graphics, piece 0 |
| 16 | `WALLSET` | `$67E0` | piece 1 |
| 17 | `WALLSET` | `$6970` | piece 2 |
| 18 | `WALLDEF` | `$8C00` | wall definitions, piece 0 |
| 19 | `WALLDEF` | `$8C00` | piece 1 |
| 20 | `WALLDEF` | `$8C00` | piece 2 |
| 21 | `CHARPIC` | `$9900` | the icon charset |
| 22 | `CHARPIC` | `$8C00` | the same file, staged |
| 23 | `COMPIC` | `$8C00` | a combat picture |
| 24 | `ITEMFILE` | `$9900` | an area's item drop list |

Twenty slots, twenty stems, three kinds taking more than one slot: `WALLSET` and
`WALLDEF` take three each because the renderer holds three wall pieces at once,
and `CHARPIC` takes two. The three `WALLSET` load addresses are 400 bytes apart
and every `WALLSET` file on the disks is exactly 400 bytes, ending at `$6B00`
where the character record begins.

## The rule for a filename

`stem` + the byte as **two hex digits**, upper case: `LIBRARY $4255`-`$4265`
takes the low nibble and then the high nibble through the nibble-to-PETSCII
routine at `$4894` and writes them over the stem's own last two characters with
`STA ($4C),Y`. That indirect store is why an earlier search for absolute writes
into the stem block found nothing and concluded the stems were never patched —
they are, through a pointer.

Every value in every one of the ~60 specimen saves resolves to a file that
exists on Donald's disks. That is the check that could have failed and did not.

## What the loader does with it

`LIBRARY $4225` is "ensure file number `A` of kind `X` is loaded", and `$4222`
is "reload slot `X` if it is dirty".

* `A = $FF` — do nothing. The slot stays empty.
* `A & $7F = $7F` — mark the slot empty without loading.
* masked `A` equals the slot — store it clean and return; **no load**.
* otherwise — store it, build the filename, load the file, then walk every
  other slot and set bit 7 on any whose memory range this load overwrote
  (`$427E`-`$42C5`, ranges from `$41BE`/`$41D7` and end addresses in the two
  25-byte arrays at `$2C16` and `$2C2F`, which sit immediately below `LIBRARY`'s
  base and are a fourth independent check that the base is `$2C48`).

`$41F0,X` says whether slot `X` may be marked by that scan: `$00` exempts it —
the three `WALLDEF` slots, which live in the staging buffer — and `$FF` at slot
24 ends the loop.

## Saving and loading

* **Saving.** `CAMP $0D00`: `LDX #$18 / LDA $6E13,X / STA $4BC0,X` — all 25
  copied verbatim. Then `$0D0B`: `LDA $49F2 / STA $4BC8` overwrites slot 8 with
  the **masked** script id, so the `ECL` slot in a save is always clean.
* **Loading.** `GEN $25DE`: `LDA $4BC0,X / ORA #$80 / STA $6E13,X` —
  **bit 7 is forced on for all 25**, so the bit a save carries changes nothing.
  `$FF` is unaffected, which is what makes it the empty marker.

`DUNGEON` then reloads whatever carries bit 7 and runs the arriving script's
entry 4, which refills the rest: `LOADFILES` (`$2041`) writes slot 3 from its
second operand and then, indoors, slot 2 from `$49C5`, slot 9 from its third
operand and slot 0 with `1`; on the travel grid it writes slot 4, slot 1 and
slot 0 with `0` instead. `LOADPIECES` (`$28DC`) writes the `WALLSET` and
`WALLDEF` triples from one operand each.

**That is why `$4BC0` reads `01` indoors and `00` outdoors** — it is not a flag,
it is which `GDRIVE` overlay is resident.

## The two entries a save actually needs

CONFIRMED, twice, in the running game. `work/p24/build.py` and
`work/p24/build2.py`.

A save whose cache is `$FF` in every slot except **slot 2 (`GEO`)** and
**slot 8 (`ECL`)** loads, draws and plays. The engine refills the rest itself.

| test | template | cache written | result |
|---|---|---|---|
| A | `PORSAVE13`, the Slums | slot 2 = `$14`, slot 8 = `$14`, rest `$FF` | loaded, status line `W 21:15 15,4`, `$0400`-`$07FF` byte-identical to `GEO14`, walked east across the boundary into New Phlan |
| B | `PORSAVE`, New Phlan, retargeted to Sokol Keep | slot 2 = `$15`, slot 8 = `$15`, rest `$FF`, plus `$49C0`-`$49C2` = 8,14,0, `$49C5` = `$15`, `$49E6` = 1, `$49F2` = `$15` | loaded, ran `ECL15`'s own arrival — "THE BOAT DISEMBARKS YOU AT SOKAL KEEP." — settled at `(8,14)` facing north, `$0400`-`$07FF` byte-identical to `GEO15`, and walked. Cache refilled to `GDRIVE01`, `GEO15`, `SECSET02`, `ECL15` and the wall triple `01 05 09` |

Test B needed one more byte than the cache, `$49EA`; see below.

**The placement question is settled: a deliberately-placing script wins.**
Test B rebuilt with `$49C0`-`$49C2` = `(8,12)` — neither the save's square nor
the arrival — came up at **`(8,14)`**: the boat message printed, `$4A02` went
0 → 1, and the live position `$C04B`-`$C04D` read the script's square while
`$49C0`-`$49C2` still held `(8,12)` (`work/p46/`). So `ECL15 $9A92`'s
message-and-place branch, gated on the scratch flag `$4A02`, overwrites the
saved square when the gate is open — and a converter that zeroes the scratch
arms it, which is safe: the script's own square is legal by construction. An
area with no placing arrival leaves the saved square alone — PROBABLE from the
#24 conversion run, which came up at `(4,3)` where New Phlan's arrival is
`(15,1)`. Indoors the saved square is a shadow: it seeds the live
`$C04B`-`$C04D` during arrival and does not move again until the game saves.

After test A settled, the live cache read

```
01 ff 14 02 ff ff ff ff 14 ff ff ff ff ff ff 02 04 01 02 04 01 ff ff ff ff
```

against the genuine `PORSAVE13`'s

```
01 e4 14 02 ff 1d 00 81 14 ff 80 00 ff 98 96 02 04 01 82 84 81 80 80 82 ff
```

Every slot the arriving script owns — `GDRIVE`, `GEO`, `SECSET`, `ECL`,
`WALLSET`, `WALLDEF` — came back exactly. The ones still `$FF` are the lazy
ones: pictures, sprites, portraits, spell tables and the icon charset, each
loaded the first time something asks for it.

## Why zeroing hangs, and why setting bit 7 does not help

Both failures reported against the converter are explained by the table above.

* **Zeroed.** Twenty-five slots all reading `$00` name `GDRIVE00`, `SQRPACI00`,
  `GEO00`, `SECSET00`, … spread across eight disks, so the loader asks for a
  disk over and over — and `WALLSET00`, `WALLDEF00` and `ITEMFILE00` **do not
  exist on any disk**, so three of those requests can never be satisfied.
* **Bit 7 set on every entry.** It changes nothing at all: `GEN $25DE` sets bit
  7 on all 25 regardless. The low bits are still the template's file numbers,
  so the same wrong files are requested.

The fix is `$FF`, which is the one value the load path leaves alone.

## `$49EA` — the third byte a converted save needs

CONFIRMED. `GEN $08BD` is `LDA $49EA / STA $6E12`, and `$6E12` is the `POOL`
side the loader asks for by number. It is not part of the cache but it is what
makes the cache's entries findable.

Test B above was built from a New Phlan template, so `$49EA` was `3`, and the
game sat on `INSERT SIDE # 3` hunting for `ECL15`, which is on POOL4. Poking
`$6E12 = 4` freed it at once. All eleven New Phlan specimens carry `$49EA = 03`
and both Slums specimens carry `02`, matching `ECL00` on POOL3 and `ECL14` on
POOL2. `118-debug-mode.md`'s area table has the disk for every area.

`117-save-conversion.md` currently lists `$49EA`-`$49EF` among the unattributed
gaps; `$49EA` is no longer one.

## What a converter should write

Given a target area id `N`, its `GEO` number `G` and the disk `D` that carries
`ECLN` — all three in `118-debug-mode.md`'s area table:

| address | value |
|---|---|
| `$4BC0`-`$4BD8` | `$FF` × 25, then slot 2 = `G` and slot 8 = `N` |
| `$49EA` | `D` |
| `$49E6` | 1 indoors, 0 on the travel grid |
| `$49C5` | `G` |
| `$49C0`-`$49C2` | the party's square and facing |

## The outdoor form — areas 25, 26 and 27

CONFIRMED, twice, in the running game (`work/p47/`): once cutting a genuine
wilderness save's cache to the two entries, once retargeting the indoor Slums
template onto travel window `1A` from a cold boot. Both came up `OUTDOORS`,
at the square the save carried, and walked the grid; `$8C00` matched the
window's `SQRDATA` file in 648 of 648 bytes.

The same shape with **slot 4 (`SQRDATA`) in slot 2's role**, and the `SQRDATA`
number `S` (`04`/`05`/`06`) standing in for `G` everywhere `G` appears:

| address | value |
|---|---|
| `$4BC0`-`$4BD8` | `$FF` × 25, then slot 4 = `S` and slot 8 = `N` |
| `$49EA` | `D` — still the disk carrying `ECLN`: 6, 7, 8 for the three windows |
| `$49E6` | 0, and it is sufficient on its own to come up in travel mode |
| `$49C5` | `S` — the seven game-written outdoor specimens all carry it, not `G` and not `N` |
| `$49C3`-`$49C4` | the travel square. `$49C0`-`$49C2` stay stale, as every genuine outdoor save leaves them |

Slot 2 stays `$FF` and stays empty after arrival — no `GEO` is loaded outdoors.
The refill is `LOADFILES`' travel branch: `GDRIVE00`, `SQRPACI00`, `SECSET0n`
and the `SQRDATA` itself. And unlike indoors, the placement question is closed:
a warp carrying (0,0) came up at (0,0) and the retarget carrying (5,2) came up
at (5,2), so the arriving script honours `$49C3`/`$49C4` rather than re-placing
the party.
