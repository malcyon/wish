# The DOS saved game: SAVGAM?.DAT

The DOS counterpart of [`30-savegame-layout.md`](30-savegame-layout.md): what
is at each offset of the 13137-byte `SAVGAM<slot>.DAT`, with a grade per
claim. Established in #59 by differential analysis under DOSBox — one known
in-game change per save pair, then bisection with hand-built saves the game
was made to load — against twelve Pool of Radiance specimens: Donald's slots
A, B and J, four saves taken one action apart, two engine resaves of
converted parties, and three saves made on the overland travel map by
playing there (`work/p59-outdoor`), plus a DOSBox-X debugger pass on the
live outdoor game. `por/dos_savegame.py` is the machine-readable form and the
reasoning is in [`50-experiments.md`](50-experiments.md) "Mapping the DOS
saved game" and "The DOS saved game outdoors".

## The file, in five regions

| offset | size | what | grade |
|---|---|---|---|
| 0 | 1 | the current area's `.DAX` container number, 1-8 — numerically the C64 `POOL` disk side that carries the same area (A/B/J = 3/4/2 = the C64 disks for New Phlan, Sokol Keep, the Slums) | CONFIRMED |
| 1-5120 | 5120 | 2560 `u16le` **VM variables**, indexed by ECL address: `offset = 1 + 2*(addr − $4900)`. Sparse: 2407 of 2560 words are zero in all nine specimens | CONFIRMED |
| 5121-12800 | 7680 | the **ECL text buffer**: the current area's script, byte-identical to its `ECL<n>.DAX` block from byte 2 on — every block opens `88 13`, `u16le` 5000, and the save carries everything after it. Bytes past the script's end are **all zeros** in every specimen held (6 of 6 checked, remnants of 209/1972/3/1113 bytes; an earlier claim of stale remnants was wrong). **Live on load**: a retarget that leaves the template's script staged dies in `Load3DMap` however many variables it writes, so staging the target's script is one of the writes of the recipe below | CONFIRMED — #60, `work/p60/run2` variant X1; zero-fill measured in #59's outdoor pass |
| 12801-12808 | 8 | the square and the party size — see below | CONFIRMED |
| 12809-13136 | 328 | six 41-byte character entries, then 82 bytes of UI scratch (menu-text fragments, heap pointers). Each entry is a length-prefixed `CHRDAT<letter><n>` filename followed by 32 bytes of heap junk. **The filenames are live**: the engine loads the party from the files named here, not from the slot letter chosen at the LOAD menu — slot J's file staged as slot C loaded J's characters — and its own resave rewrites the letters | CONFIRMED |

## The square and the party size

| offset | what | grade |
|---|---|---|
| 12801, 12802 | x, y — **indoors**. Outdoors both freeze at the last indoor square (the pier, 15,1, in all three overland saves) and the live square is `$49C3`/`$49C4` | CONFIRMED — #6, re-proven by the step diff (4→5 on one step east); staleness 3 of 3 outdoor specimens |
| 12803 | facing, the C64's value doubled: 0 N, 2 E, 4 S, 6 W — and **still live outdoors** (2/0/2 = E/N/E against the screen while x,y sat stale) | CONFIRMED — turn diff, 0→2 on one right turn; outdoors 3 of 3 |
| 12804 | unknown; 0 in A/J, 14 in B **and** in all three outdoor saves | UNKNOWN |
| 12805 | equals VM word `$5200` in **all six** specimens (26/0/0 indoors, 1/1/1 outdoors); volatile indoors | PROBABLE that one copies the other; which way, unknown |
| 12806 | **1 in the three indoor saves, 3 in the three outdoor ones** — reads as the engine's view-mode byte | PROBABLE — perfect 6-specimen correlation, no live watch (the tail is not resident contiguously, see below) |
| 12807 | 2 in every specimen | UNKNOWN |
| 12808 | **party size**, one byte; 6→1 when a six-member template carried a one-member party through the engine's own resave | CONFIRMED |

**The tail is assembled at save time, not dumped from a struct**: the byte
run 12801-12817 (stale square + `CHRDATD1`) appears nowhere in the first
megabyte of the running game (`work/p59-outdoor/run2.log`), so 12804-12807
have no single live address to watch.

## The named VM variables

Where an address matches the C64's, that is measured, not assumed — the two
ports share the ECL address space, which is the same mechanism that lets the
quest flags convert unconditionally.

| address | what | grade |
|---|---|---|
| `$49C0`-`$49C2` | **zero in every DOS save**, indoors and out — the square is *not* here, unlike the C64; it is at file 12801-12803 indoors and `$49C3`/`$49C4` outdoors | CONFIRMED — 6 of 6 |
| `$49C3`, `$49C4` | **the overland travel square, window-local**: (7,29) → (7,28) → (8,28) across the three outdoor saves against on-screen `20,29`/`20,28`/`21,28` — world x = local x + 13 for window 26 (`WINDOW_X_OFFSET`) — and a live `BPM` caught one east step writing `$49C3` 7→8 (writer `2E33:095E`). Zero in the three indoor specimens, stale after a return indoors | CONFIRMED — two independent sources |
| `$49C5` | area id (= geo block id, `por/areas.py` numbering) — but **0 in all three outdoor saves**, *not* the C64's SQRDATA number (the C64 holds 5 there for window 26) | CONFIRMED indoors — three saves + the retarget requires it; outdoor value CONFIRMED, its consumer UNKNOWN |
| `$49C6`-`$49CB` | **the clock, six digit words, exactly the C64's six bytes**: sub-minute, minute units, minute tens, hour, day, month. A reads 10:02 day 16 and displayed 10:02; one step moved `$49C7` 2→3 as the display moved 10:02→10:03; saving costs no time | CONFIRMED |
| `$49E6` | **the indoors flag**: 1 in the three indoor specimens, 0 in the three outdoor ones, and the boat-back transition was caught live writing it 0→1 (writer `30F6:0CA1`) | CONFIRMED |
| `$49F2` | the area script id | CONFIRMED as the field; carried in every working retarget, never tested absent |
| `$4A20`-`$4AF8` | the quest flags, byte-to-word at the C64's addresses | CONFIRMED — prior work, #26 |
| `$4AFA`-`$4AFC` | **the wallset triple**: up to three `WALLDEF<n>.DAX` / `8X8D<n>.DAX` block ids, `$FFFF` = empty. Byte-identical to the C64 loaded-files cache slots 15-17 for the same area — PORSAVE13's Slums triple (2,4,1) is slot J's, PORSAVE's Sokol Keep (1,5,9) is slot B's. **New Phlan is the exception**: the C64 loads no `WALLSET` there and all three slots read `$FF`, where DOS slot A holds `(0, $FFFF, $FFFF)`. Without the triple a retarget dies in `LoadWallSet` | CONFIRMED |
| `$4AFD`-`$4AFF` | (1,2,3) with three sets loaded, (1,$FFFF,$FFFF) with one — read as the wall-index map | PROBABLE |
| `$4FE1` | 255 in all three | UNKNOWN |
| `$503E` | **party size** as a VM word; 6→1 in the one-member resave, 6 in Curse's and Secret's six-member defaults | CONFIRMED |
| `$5012` | the DAX container number again, as a VM word. **The geo load reads this, not the header byte**: a retarget carrying everything else still dies with `Unable to load geo in Load3DMap.` until this word is written | CONFIRMED |
| `$5200` | equals file byte 12805 in all six specimens; written 1→0→1 by the boat-back transition (writer `30F6:0CF2`) | PROBABLE scratch; unnamed |
| `$5227`+ | the encounter-message string buffer, one ASCII character per word — "YOU SPY A GROUP OF SEEDY-LOOKING GOBLINS." in J | PROBABLE |
| the rest | ~30 more live words (`$49F0`, `$49FC`-`$49FF`, `$4FC0`-`$4FD3`, `$5079`-`$507D`, `$5201`-`$520F`, …) hold small values that move with area and play; none is needed by the load path (bisected out) and none is named. Outdoor evidence so far: `$49F0` moved 14→15 on the one step that crossed 10:15→22:15 and then sat still through two watched steps (no `BPM` hit); `$507A` held the travel y twice but did not track x; `$49FC`-`$49FF` are (6,11,10,3) in five specimens and (4,11,9,3) in J, indoors and out alike; `$4FD2`/`$4FD3` differ in every save and read 0 live (a seed?) | UNKNOWN |

## The retarget recipe (#60)

Two recipes are **refuted**. The naive one — header byte, `$49C5`, `$49F2`,
square — exits to DOS with `Unable to load geo in Load3DMap.`, and so does
#59's seven-write recipe when it is run on a template it was not found on:
every one of #59's twelve variants happened to carry the *target's* ECL
buffer, so the buffer was never a variable and "dead on load" was a reading
of that accident. `work/p60/run2` variant X1 is the control it lacked —
slot A, all seven writes, its own buffer left staged — and it dies in
`Load3DMap`.

The writes. The first seven are what the load path checks — take any one
away and the game exits to DOS — and the last two are the party rather than
the place:

1. byte 0 = the target area's DAX number (`por/areas.py`'s `Area.disk`);
2. `$49C5` = the target area id;
3. `$49F2` = the target area id;
4. `$5012` = the target area's DAX number;
5. `$4AFA`-`$4AFC` = the target's wallset triple (sourceable from the C64
   save's cache slots 15-17, which carry the same numbers);
6. `$4AFD`-`$4AFF` = (1,2,3) or (1,$FFFF,$FFFF) to match;
7. **5121-12800 = the target's `ECL<dax>.DAX` block, from byte 2 on**;
8. 12801-12803 = x, y, facing×2;
9. `$503E` and byte 12808 = the party size.

The flags and everything else may stay the template's. `por.dos_savegame`'s
`retarget` is the machine-readable form and `RETARGET_WRITES` the list.

**CONFIRMED for three area pairs**, each loaded and walked: 0 → 20 (#59 run
9), 21 → 20 and 20 → 0 (`work/p60/run2`, X2 and X3). The script buffer is why
a converter needs the DOS **game** directory and not only a template save:
`ECL<n>.DAX` is the only copy of the target's script.

**An empty wallset triple is legal**, which matters because New Phlan is the
one area a C64 save can offer nothing better for. Retargeted into area 0 with
`($FFFF, $FFFF, $FFFF)` the game draws a view **pixel-identical** to the same
retarget carrying DOS's own `(0, $FFFF, $FFFF)` — `work/p60/run3` Z0 against
`run2` X3, the only differing pixels being the colour-cycling command bar.

And end to end through `por.dos.write_dos_save`, both walked: `PORSAVE13` in
the Slums onto template A comes up at 15,4 W 21:15, and `PORSAVE12` in New
Phlan onto template J at 0,4 W 16:58 — each party's own square, facing and
clock, with six characters on the roster (`work/p60/run3` and `run4`).

## Per-title sizes

| title | SAVGAM size |
|---|---|
| Pool of Radiance | 13137 |
| Curse of the Azure Bonds | 13149 — same shape: `$503E` = 6, CHRDAT table at 12822, +12 throughout the tail | 
| Secret of the Silver Blades | 5469 — `$503E` = 6 holds, CHRDAT table at 5142; the variable array is far smaller |
| Pools of Darkness | 1364, plus a separate `SAVGAM<slot>.PTY` — not this shape |

Only Pool of Radiance is mapped; the other three rows are file sizes and two
spot checks, PROBABLE at best.

## The outdoor form (#59's outdoor pass)

Three engine-written overland saves exist — `work/p59-outdoor/SAVGAMC.DAT`,
`D`, `E`: slot A's party sailed WEST from New Phlan's passenger dock and
landed at world (20,29) on window 26, then stepped north and east. The route
itself is in `ECL00`: the harbor master at (11,1) sells SOKAL/EAST/WEST/BAY
passage into `$4AC4`, and boarding at the pier end (15,1) runs
`SAVE 7,[$49C3] / SAVE 29,[$49C4] / SAVE 7,[$6E12] / NEWECL 26`.

What an outdoor save holds, against an indoor one (3 specimens, plus the
live watches in `run2.log`):

| field | indoors | outdoors |
|---|---|---|
| byte 0, `$5012` | area's DAX number | unchanged mechanism — 7 for area 26 |
| `$49F2` | area id | area id (26) |
| `$49C5` | area id | **0** — not the C64's SQRDATA number |
| `$49E6` | 1 | **0** |
| square | file 12801-12803 | `$49C3`/`$49C4`, window-local; 12801/12802 stale, 12803 (facing) still live |
| ECL buffer | script from byte 2 | same rule — `ECL7.DAX` block 26, 6567 of 6567 |
| wallset triple | the area's | (0,$FFFF,$FFFF) — but that is also the departure template's value, so live-versus-stale is unmeasured |

One overland step costs 12 hours on the clock. The DOS overland has no
`SQRDATA` files at all — the three windows are ordinary `GEO` blocks 25-27
in `GEO6`-`GEO8.DAX` plus `SQRPACI.DAX`/`WILDCOM.DAX`, which is presumably
why `$49C5` has nothing to carry out there.

## What this leaves open

* `$49F0`, `$49FC`-`$49FF`, `$4FC0`-`$4FD3`, `$5079`-`$507D`,
  `$5200`-`$520F`, 12804-12807 — live, unnamed. Each needs its own
  one-change differential; the negative results so far are in the tables
  above.
* Whether the wallset triple is live or stale outdoors. Settling experiment:
  sail out from an area with a different triple (Sokol Keep's boat, 1,5,9)
  and read `$4AFA`-`$4AFC` in the overland save.
* An outdoor *retarget* (the #60 recipe with `$49E6` = 0 and
  `$49C3`/`$49C4` in place of the square bytes) has not been driven; #50
  owns the converter form of it.
* `#57`'s portrait question was not touched.
