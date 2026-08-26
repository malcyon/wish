# The DOS saved game: SAVGAM?.DAT

The DOS counterpart of [`30-savegame-layout.md`](30-savegame-layout.md): what
is at each offset of the 13137-byte `SAVGAM<slot>.DAT`, with a grade per
claim. Established in #59 by differential analysis under DOSBox — one known
in-game change per save pair, then bisection with hand-built saves the game
was made to load — against **twelve genuine engine-written Pool of Radiance
specimens**: Donald's slots A, B and J, the archives' own
`games/POOLRAD/Default files/Saves/SAVGAMA.DAT` (a Slums save, and *not* the
same file as Donald's slot A), four saves taken one action apart, an engine
resave of a converted party, and three saves made on the overland travel map
by playing there (`work/p59-outdoor`), plus a DOSBox-X debugger pass on the
live outdoor game. A thirteenth file, `Default files/Saves/SAVGAMB.DAT`, is a
**stub and is excluded from every count**: its ECL buffer is 7680 zero bytes,
it holds nine nonzero VM words, no quest flags and a 00:00 clock. `por/dos_savegame.py` is the machine-readable form and the
reasoning is in [`50-experiments.md`](50-experiments.md) "Mapping the DOS
saved game" and "The DOS saved game outdoors".

## The file, in five regions

| offset | size | what | grade |
|---|---|---|---|
| 0 | 1 | the current area's `.DAX` container number, 1-8 — numerically the C64 `POOL` disk side that carries the same area (A/B/J = 3/4/2 = the C64 disks for New Phlan, Sokol Keep, the Slums) | CONFIRMED |
| 1-5120 | 5120 | 2560 `u16le` **VM variables**, indexed by ECL address: `offset = 1 + 2*(addr − $4900)`. Sparse: **2401 of 2560 words are zero in all twelve specimens** | CONFIRMED |
| 5121-12800 | 7680 | the **ECL text buffer**: the current area's script, byte-identical to its `ECL<n>.DAX` block from byte 2 on — every block opens `88 13`, `u16le` 5000, and the save carries everything after it. Bytes past the script's end are **all zeros** in every specimen held (6 of 6 checked, remnants of 209/1972/3/1113 bytes; an earlier claim of stale remnants was wrong). **Live on load**: a save built for a new area that still carries the old area's script dies in `Load3DMap` however many other variables it writes, so writing the target area's own script is one of the writes of the recipe below | CONFIRMED — #60, `work/p60/run2` variant X1; zero-fill measured in #59's outdoor pass |
| 12801-12808 | 8 | the square and the party size — see below | CONFIRMED |
| 12809-13136 | 328 | six 41-byte character entries, then 82 bytes of UI scratch (menu-text fragments, heap pointers). Each entry is a length-prefixed `CHRDAT<letter><n>` filename followed by 32 bytes of heap junk. **The filenames are live**: the engine loads the party from the files named here, not from the slot letter chosen at the LOAD menu — slot J's file staged as slot C loaded J's characters — and its own resave rewrites the letters | CONFIRMED |

## The square and the party size

| offset | what | grade |
|---|---|---|
| 12801, 12802 | x, y — **indoors**. Outdoors both freeze at the last indoor square (the pier, 15,1, in all three overland saves) and the live square is `$49C3`/`$49C4` | CONFIRMED — #6, re-proven by the step diff (4→5 on one step east); staleness 3 of 3 outdoor specimens |
| 12803 | facing, the C64's value doubled: 0 N, 2 E, 4 S, 6 W — and **still live outdoors** (2/0/2 = E/N/E against the screen while x,y sat stale) | CONFIRMED — turn diff, 0→2 on one right turn; outdoors 3 of 3 |
| 12804 | **unnamed, and engine-maintained.** 0 in the eight walked-in indoor saves, 14 in B and in all three outdoor saves, 9 in the run-9 resave. No byte offset and no VM word anywhere in the file carries its value vector, and none shares its partition — searched exhaustively over 13 files. It is computed at save time from state the save does not otherwise hold. **The engine writes it itself**: a hand-built save carrying 0 came back from the engine's own resave holding 9. Refuted: `$49F0`, `$49F1`, `$49FE`, `$4AC4`, a step counter (flat across a turn, an indoor step and two overland steps) | UNKNOWN as a meaning; CONFIRMED engine-maintained, and the value depends on where the party stands, so **0 indoors and 14 outdoors are the measured values to write** -- neither is inherited, and writing the indoor 0 into an outdoor save would be |
| 12805 | **the low byte of VM word `$5200`** — equal in **13 of 13** files, including a pair that moved together 26→0 on one indoor step and 26→1 across the boat, and the engine's resave (26→0 in both places at once) | CONFIRMED as a copy; which direction, unknown |
| 12806 | **1 in the nine indoor specimens, 3 in the three outdoor ones** — but it is *perfectly* correlated with `$49E6`, so nothing in the corpus separates "view mode" from a second encoding of the indoors flag. A converter can write it from `$49E6`, which it already knows | PROBABLE as view mode; CONFIRMED as a function of `$49E6`, 12 of 12 |
| 12807 | **2 in all 12 genuine specimens**, indoors and out, before and after the engine's resave (0 only in the stub) | CONFIRMED as a constant to write; its meaning UNKNOWN |
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
| `$49C5` | area id (= geo block id, `por/areas.py` numbering) — but **0 in all three outdoor saves**, *not* the C64's SQRDATA number (the C64 holds 5 there for window 26) | CONFIRMED indoors — three saves, plus moving a save to a new area only works when this word is set to the target's id; outdoor value CONFIRMED, its consumer UNKNOWN |
| `$49C6`-`$49CB` | **the clock, six digit words, exactly the C64's six bytes**: sub-minute, minute units, minute tens, hour, day, month. A reads 10:02 day 16 and displayed 10:02; one step moved `$49C7` 2→3 as the display moved 10:02→10:03; saving costs no time | CONFIRMED |
| `$49E6` | **the indoors flag**: 1 in the three indoor specimens, 0 in the three outdoor ones, and the boat-back transition was caught live writing it 0→1 (writer `30F6:0CA1`) | CONFIRMED |
| `$49F2` | the area script id | CONFIRMED as the field; carried in every save that has successfully moved a party to a new area, never tested absent |
| `$4A20`-`$4AF8` | the quest flags, byte-to-word at the C64's addresses | CONFIRMED — prior work, #26 |
| `$4AFA`-`$4AFC` | **the wallset triple**: up to three `WALLDEF<n>.DAX` / `8X8D<n>.DAX` block ids, `$FFFF` = empty. Byte-identical to the C64 loaded-files cache slots 15-17 for the same area — PORSAVE13's Slums triple (2,4,1) is slot J's, PORSAVE's Sokol Keep (1,5,9) is slot B's. **New Phlan is the exception**: the C64 loads no `WALLSET` there and all three slots read `$FF`, where DOS slot A holds `(0, $FFFF, $FFFF)`. Without the triple, a save moved to a new area dies in `LoadWallSet` | CONFIRMED |
| `$4AFD`-`$4AFF` | (1,2,3) with three sets loaded, (1,$FFFF,$FFFF) with one — read as the wall-index map | PROBABLE |
| `$503E` | **party size** as a VM word; 6→1 in the one-member resave, 6 in Curse's and Secret's six-member defaults | CONFIRMED |
| `$5012` | the DAX container number again, as a VM word. **The geo load reads this, not the header byte**: a save carrying every other write of the recipe below still dies with `Unable to load geo in Load3DMap.` until this word is written | CONFIRMED |
| `$5200` | equals file byte 12805 in all six specimens; written 1→0→1 by the boat-back transition (writer `30F6:0CF2`) | PROBABLE scratch; unnamed |
| `$5227`+ | the encounter-message string buffer, one ASCII character per word — "YOU SPY A GROUP OF SEEDY-LOOKING GOBLINS." in J | PROBABLE |
| `$49EB` | a script variable: 0 in New Phlan, 1 in the Slums, Sokol Keep and outdoors — **and the C64's byte at the same address reads the same way** (0 in ten New Phlan saves, 1 in both Slums saves). ECL00 writes 1 into it when the party boards a boat | CONFIRMED as the same field on both ports; what it gates, UNKNOWN |
| `$49FD`, `$49FE` | **per-area constants the area's own ECL prologue writes.** `ECL00` (New Phlan) opens `SAVE [$6E7D],[$49FD] / SAVE 10,[$49FE]`; `ECL14` (the Slums) opens `SAVE [$6E7D],[$49FD] / SAVE 9,[$49FE]`. Every DOS specimen agrees (10 New Phlan, 9 Slums) and so does every C64 save. Sokol Keep's `ECL15` never writes `$49FE`, which is why slot B stands there still holding New Phlan's 10. The engine rewrote 10→9 by itself after loading a save retargeted into the Slums | CONFIRMED — the script text and 12 specimens on two ports |
| `$4A00`-`$4A1F` | the per-script scratch, the C64's `SCRIPT_SCRATCH` at the same addresses, zeroed on every area change. Six words are live here and they partition cleanly by area; `$4A00` is 255 in both ports' Slums saves and 0 in both ports' New Phlan saves | CONFIRMED as the same region; the individual words UNKNOWN |
| `$49FC`, `$49FF` | ECL-visible, but the two ports **disagree**: DOS reads (6, 3) — 4 for `$49FC` in the Slums — where the C64 reads (2, 129/1). So they are not copyable across even though the address is shared. `$49FC` is not the party count: J holds 4 with six live characters | UNKNOWN, and refuted as party count |
| `$4B00`-`$52FF` | **DOS engine state with no C64 counterpart.** No ECL script in the 30-script corpus references any address at or above `$4AF9` (2544 distinct bracketed addresses checked), and on the C64 `$4D00` upwards is the twelve character slots, not variables. So nothing here can be sourced from a C64 save; it has to be measured. Live and still unnamed: `$4DB8`, `$4DC3`, `$4E0C`, `$4FA8`, `$4FC0`-`$4FC1`, `$4FC6`, `$4FC8`, `$507A`-`$507D`, `$507F`-`$5080`, `$5202`-`$5207`, `$520A`-`$520F`. Constant in all twelve: `$4FE1` = 255, `$506D` = 16, `$50F6` = 1 | UNKNOWN individually; the boundary CONFIRMED |
| engine-rebuilt | `$49F0`, `$49F1`, `$49FE`, `$4FD2`, `$4FD3`, `$5079`, `$5082`, `$5200`, `$5208` — the nine words the engine rewrote by itself when it loaded a hand-built save and the party moved (`work/p59/retarget-C.DAT` against `work/p59/run9/SAVGAMD.DAT`). The load path was already bisected as not needing them | CONFIRMED engine-maintained |

## The recipe for moving a save to a different area (#60)

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

The flags and everything else may stay the template's. `por.dos_savegame.retarget`
is the function that applies these writes, and `RETARGET_WRITES` holds the list
above in machine-readable form.

**CONFIRMED for three area pairs**, each loaded and walked: 0 → 20 (#59 run
9), 21 → 20 and 20 → 0 (`work/p60/run2`, X2 and X3). The script buffer is why
a converter needs the DOS **game** directory and not only a template save:
`ECL<n>.DAX` is the only copy of the target's script.

**An empty wallset triple is legal**, which matters because New Phlan is the
one area a C64 save can offer nothing better for. A save moved into area 0 with
`($FFFF, $FFFF, $FFFF)` in the triple draws a view **pixel-identical** to the
same move carrying DOS's own `(0, $FFFF, $FFFF)` — `work/p60/run3` Z0 against
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

## What a conversion still has to inherit

The rule in `CLAUDE.md` is **measured versus inherited**: a value we
established is fine at any number, and a value taken from somebody else's
save is not. This is the list, in the three legitimate groups, measured over
the twelve genuine specimens. `por.dos.write_dos_save` writes the quest
flags, the script scratch, the clock, the party size, the square, the six
character filenames and — when the areas differ — the nine retarget writes
and the ECL buffer. Everything else in the file it copies from the template.

**1. The engine rebuilds it, so writing anything is pointless.** Nine VM
words came back rewritten when the engine loaded a hand-built save and the
party moved (`work/p59/retarget-C.DAT` against `work/p59/run9/SAVGAMD.DAT`),
and the load path was already bisected as not reading them:
`$49F0`, `$49F1` (the previous square), `$49FE` (the area's ECL prologue
writes it), `$4FD2`, `$4FD3`, `$5079`, `$5082`, `$5200`, `$5208`. Byte 12804
is in this group too — the engine replaced our 0 with 9.

**2. The C64 save has no such field.** Everything at `$4AF9` and above:
no ECL script references any address there (2544 distinct addresses across
30 scripts), and on the C64 that range is `$4B00`-`$4CFF` header remainder
and then the twelve character slots from `$4D00`. There is nothing to copy
from. These have to be measured on the DOS side or left to the engine, and
some already are: `$4FE1` = 255, `$506D` = 16, `$50F6` = 1 and byte 12807 = 2
in all twelve, so those are constants a converter can write outright.

**3. Nobody has decoded it — the blocker list.** Every entry here carries the
experiment that would remove it.

| what | bytes | what would settle it |
|---|---|---|
| `$49FC`, `$49FF` | 4 | ECL-visible, but the ports disagree — DOS reads (6/4, 3) where the C64 reads (2, 129/1). A read-watch on either in DOSBox-X |
| `$4DB8`, `$4DC3`, `$4E0C`, `$4FA8`, `$4FC0`-`$4FC1`, `$4FC6`, `$4FC8`, `$507A`-`$507D`, `$507F`-`$5080` | 30 | DOS-only engine state. `$507A`-`$507D` are zero in all nine indoor specimens, so zero is measured for an indoor conversion; the rest partition by area. Read-watches, one per word |
| `$5202`-`$5207`, `$520A`-`$520F` and the encounter-text buffer `$5227`+ | 154 | they change together and sit immediately before a readable encounter message, so PROBABLE the pending-encounter record. A converted party has no encounter pending; the experiment is a hand-built save with the block zeroed, loaded and walked |
| the character table's 29 junk bytes per entry and the 82 bytes of UI scratch after it | 246 | PROBABLE display scratch — the bytes contain readable fragments of menu words ("camping"), and the engine rewrote 55 of them on its own resave with no visible effect. Same experiment: zero them, load, look |
| byte 12804 | 1 | in group 1, not a blocker; naming it needs a write-watch on the save routine |

`$49EB` and `$4A00`-`$4A1F` used to head that table and have come off it.
They are ECL-visible and CONFIRMED the same fields on both ports, so
`write_dos_save` now copies them from the C64 the way it copies the quest
flags — the whole scratch window rather than the six live words in it, since
the other twenty-six read zero on both ports in every specimen and one loop is
fewer special cases than seven addresses. **What each word gates is still
UNKNOWN.** What changed is the provenance: the party being converted, at its
own address, instead of whichever stranger's save the template came from. It
is right on a retarget too, and that is the case that matters — the C64
party's scratch belongs to the area it is standing in, which is the area the
DOS save is being moved to.

**430 bytes of 13137**, 3.3% of the file, would still be inherited after
every finding above is acted on — down from 444, and from the whole of the
8016 bytes this issue opened with. None of it is party or place data.

## What this leaves open

* The blocker list above. `$49F0`/`$49F1`, `$49FE`, `$5200` and bytes
  12805-12807 came off it in #59's file-level pass; what is left is in the
  table. The negative results are in the tables above so nobody re-runs them:
  12804 has no copy anywhere in the file, `$49F0` is not a step counter, and
  `$49FC` is not the party count.
* Whether the wallset triple is live or stale outdoors. Settling experiment:
  sail out from an area with a different triple (Sokol Keep's boat, 1,5,9)
  and read `$4AFA`-`$4AFC` in the overland save.
* Moving an outdoor save to a new area (the #60 recipe with `$49E6` = 0 and
  `$49C3`/`$49C4` in place of the square bytes) has not been driven; #50
  owns the converter form of it.
* `#57`'s portrait question was not touched.
