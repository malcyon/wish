# The DOS saved game: SAVGAM?.DAT

The DOS counterpart of [`30-savegame-layout.md`](30-savegame-layout.md): what
is at each offset of the 13137-byte `SAVGAM<slot>.DAT`, with a grade per
claim. Established in #59 by differential analysis under DOSBox — one known
in-game change per save pair, then bisection with hand-built saves the game
was made to load. `goldbox/dos_savegame.py` is the machine-readable form and
the reasoning is in [`50-experiments.md`](50-experiments.md) "Mapping the DOS
saved game" and "The DOS saved game outdoors".

## The corpus, and how to re-take a count

**Every count on this page is a count of engine-written saves, and
`tools/dossavcensus.py` re-takes it rather than quoting it.** That matters
because the corpus keeps changing: eight of the twelve specimens the original
pass counted lived under `work/` and are gone, and later work has made ones
it never had.

```sh
.venv/bin/python tools/dossavcensus.py work/p26 work/p50-outdoor work/p59-wallset
```

What it finds on this machine as of 2026-09-04 is **21 genuine
engine-written containers**, 11 indoors and 10 on the travel grid:

| where | how many | what they are |
|---|---|---|
| Donald's played party | 3 | slots A (New Phlan), B (Sokol Keep), J (the Slums), in the Steam `SavesDir` |
| the archives' own | 1 | `games/POOLRAD/Default files/Saves/SAVGAMA.DAT`, a Slums save and *not* the same file as Donald's slot A |
| #26's resaves | 7 | the engine's own `ENCAMP > SAVE` of a party loaded out of a save built from 13137 zeroes, `work/p26/run*` and `work/p26/issue191/run` |
| overland | 10 | `work/p50-outdoor/SAVGAMC.DAT` and the nine of `work/p59-wallset` |

**Two kinds of file are excluded from every count and the tool marks both.**
A file we assembled is not evidence about what the engine writes, so
`BUILT-`, `SEED-` and `work/p26/issue191/built/` are out; and
`Default files/Saves/SAVGAMB.DAT` is a **shipped stub** rather than a played
party — its ECL buffer is 7680 zero bytes, it holds nine nonzero VM words, no
quest flags and a 00:00 clock, and it is the only file that disagrees with
the tail constants below.

The three overland saves of #59's August pass, made by sailing there, are
gone; where a claim rests on them and cannot be re-taken, this page says so.

**The other three titles are in their own section below.** Every offset in
this page is Pool of Radiance's; Curse and Silver Blades put the same regions
in different places and Pools of Darkness writes a `SAVGAM<slot>.PTY` instead.

## The file, in five regions

| offset | size | what | grade |
|---|---|---|---|
| 0 | 1 | the current area's `.DAX` container number, 1-8 — numerically the C64 `POOL` disk side that carries the same area (A/B/J = 3/4/2 = the C64 disks for New Phlan, Sokol Keep, the Slums) | CONFIRMED |
| 1-5120 | 5120 | 2560 `u16le` **VM variables**, indexed by ECL address: `offset = 1 + 2*(addr − $4900)`. Sparse: **2407 of 2560 words are zero in all 11 engine-written indoor specimens, and 2402 across all 21**. The five words in the difference are exactly `$49C3`, `$49C4`, `$507A`, `$507B` and `$507C` — the travel square and the three overland-only words below, nothing else. Re-take it with `tools/dossavcensus.py` | CONFIRMED |
| 5121-12800 | 7680 | the **ECL text buffer**: the current area's script, byte-identical to its `ECL<n>.DAX` block from byte 2 on — every block opens `88 13`, `u16le` 5000, and the save carries everything after it. Bytes past the script's end are **all zeros** in every specimen held (6 of 6 checked, remnants of 209/1972/3/1113 bytes; an earlier claim of stale remnants was wrong). **Live on load**: a save built for a new area that still carries the old area's script dies in `Load3DMap` however many other variables it writes, so writing the target area's own script is one of the writes of the recipe below | CONFIRMED — #60, `work/p60/run2` variant X1; zero-fill measured in #59's outdoor pass |
| 12801-12808 | 8 | the square and the party size — see below | CONFIRMED |
| 12809-13136 | 328 | **eight** 41-byte character slots, of which six are filled. Each is a length-prefixed `CHRDAT<letter><n>` filename followed by 32 bytes of heap junk. **The filenames are live**: the engine loads the party from the files named here, not from the slot letter chosen at the LOAD menu — slot J's file staged as slot C loaded J's characters — and its own resave rewrites the letters. This page said "six entries, then 82 bytes of UI scratch" until #175; the 82 are slots 6 and 7 holding the stack, which is why they read `lter Exit` and `Camp: ` at exactly the 41-byte stride | CONFIRMED as 328 bytes of `CHRDAT` slots; the count of **eight** is CONFIRMED for Pools of Darkness and Silver Blades from the code and PROBABLE here — see the settling experiment below |

## The square and the party size

| offset | what | grade |
|---|---|---|
| 12801, 12802 | x, y — **indoors**. Outdoors both freeze at the square the party last stood on indoors and the live square is `$49C3`/`$49C4` | CONFIRMED — #6, re-proven by the step diff (4→5 on one step east); staleness **10 of 10** outdoor specimens, each frozen at its own lineage's last indoor square |
| 12803 | facing, the C64's value doubled: 0 N, 2 E, 4 S, 6 W — and **still live outdoors** (2/0/2 = E/N/E against the screen while x,y sat stale) | CONFIRMED — turn diff, 0→2 on one right turn; outdoors 3 of 3. The ten seeded overland saves do not add to that count: `tools/dosoutdoorprobe.py` walks with the arrows, which move rather than turn, so the facing byte never had to change |
| 12804 | **unnamed, and engine-maintained.** 0 in the eight walked-in indoor saves, 14 in B and in all three outdoor saves, 9 in the run-9 resave, **14 in the engine's own resave of a party standing indoors in the Slums** (#26, `work/p26/run2`). No byte offset and no VM word anywhere in the file carries its value vector, and none shares its partition — searched exhaustively over 13 files. It is computed at save time from state the save does not otherwise hold. **The engine writes it itself**: a hand-built save carrying 0 came back holding 9, and a from-nothing save carrying 0 came back holding 14. Refuted: `$49F0`, `$49F1`, `$49FE`, `$4AC4`, a step counter (flat across a turn, an indoor step and two overland steps); and **refuted, by #26's run: that the value partitions on indoors and out.** This page used to say "0 indoors and 14 outdoors are the measured values to write" and an indoor resave holding 14 is what took it out. A conversion writes 0 indoors because that is what 8 of the 9 indoor specimens hold and a save carrying it loads, not because 0 means indoors | UNKNOWN as a meaning; CONFIRMED engine-maintained |
| 12805 | **the low byte of VM word `$5200`** — and of `$5082`, which equals `$5200` — in **21 of 21** engine-written specimens, including a pair that moved together 26→0 on one indoor step and 26→1 across the boat, and the engine's resave (26→0 in both places at once) | CONFIRMED as a copy; which direction, unknown |
| 12806 | **1 in the 11 indoor specimens, 3 in the 10 outdoor ones** — but it is *perfectly* correlated with `$49E6`, so nothing in the corpus separates "view mode" from a second encoding of the indoors flag. A converter can write it from `$49E6`, which it already knows | PROBABLE as view mode; CONFIRMED as a function of `$49E6`, **21 of 21** |
| 12807 | **2 in all 21 genuine specimens**, indoors and out, before and after the engine's resave (0 only in the stub) | CONFIRMED as a constant to write; its meaning UNKNOWN |
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
| `$49C5` | area id (= geo block id, `goldbox/areas.py` numbering) — but **0 in all three outdoor saves**, *not* the C64's SQRDATA number (the C64 holds 5 there for window 26) | CONFIRMED indoors — three saves, plus moving a save to a new area only works when this word is set to the target's id; outdoor value CONFIRMED, its consumer UNKNOWN |
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
| `$4FD2`, `$4FD3` | **a per-area pair the engine derives**, not the RNG seed this page once guessed at. Twenty-one engine-written specimens partition **perfectly by area, with one pair each**: New Phlan (1, 101) three times, the Slums (24, 24) seven times, Sokol Keep (2, 1) once, the overland (96, 10) ten times. Derived rather than carried, because two seeds holding *different* pairs — slot A's (1, 101) and slot B's (2, 1) — both came back (96, 10) once the party stood on the travel grid, and a party that walked out of the Slums into New Phlan came back holding New Phlan's. An older measurement, taken another way, agrees -- and it is a second source for the *derived* half rather than a twenty-second specimen for the partition, because slot J is one of the twenty-one already counted above, in the Slums' seven: `142-dosbox-x-debugger.md`'s memory-image search, run on that slot long before this partition was noticed, records these as the **only two** of 2560 words where the live image and the file disagree — `$18` = 24 in the file, which is the Slums pair, and **0 live**. So the value in the file is not simply the live VM word, which is a further reason to read it as derived at save or load time rather than carried. **What the numbers mean is UNKNOWN**: they are not the GEO block's dimensions, which are 32×32 for all four areas. Settling experiment: put a party in a fifth area and read the pair, then a `BPM` read-watch on `$4FD2` to catch what consumes it | CONFIRMED as area-derived and engine-written; the meaning UNKNOWN |
| `$507A`, `$507B`, `$507C` | **overland-only, engine-written, and they track the travel y in a band and then stop** — the only three words in the array that are nonzero in an outdoor save and zero in all eleven indoor ones, and every outdoor seed carried zero in all three and came back holding values. See the table below; **"a copy of the travel y" is refuted as a general rule** | CONFIRMED overland-only and engine-written; the meaning UNKNOWN |
| `$5082` | **equals `$5200` in 21 of 21** engine-written specimens, which makes it a third name for the value file byte 12805 also carries. Not previously noted; found by searching the variable array for words whose value vector across the whole corpus is identical | CONFIRMED as a copy |
| `$4B00`-`$52FF` | **DOS engine state with no C64 counterpart.** No ECL script in the 30-script corpus references any address at or above `$4AF9` (2544 distinct bracketed addresses checked), and on the C64 `$4D00` upwards is the twelve character slots, not variables. So nothing here can be sourced from a C64 save; it has to be measured. Live and still unnamed: `$4DB8`, `$4DC3`, `$4E0C`, `$4FA8`, `$4FC0`-`$4FC1`, `$4FC6`, `$4FC8`, `$507D`, `$507F`-`$5080`, `$5202`-`$5207`, `$520A`-`$520F`. Constant in all twelve: `$4FE1` = 255, `$506D` = 16, `$50F6` = 1 | UNKNOWN individually; the boundary CONFIRMED |
| engine-rebuilt | `$49F0`, `$49F1`, `$49FE`, `$4FD2`, `$4FD3`, `$5079`, `$5082`, `$5200`, `$5208` — the nine words the engine rewrote by itself when it loaded a hand-built save and the party moved (`work/p59/retarget-C.DAT` against `work/p59/run9/SAVGAMD.DAT`). The load path was already bisected as not needing them | CONFIRMED engine-maintained |

### `$507A`-`$507C`: a rule that holds in a band, and a refutation

Ten engine-written overland saves, from three seed lineages and four boots,
across window 26's column x = 7 and x = 8:

| travel y | `$507A` | `$507B` | `$507C` | saves |
|---|---|---|---|---|
| 28 | 28 | 11 | 11 | 4 |
| 27 | 27 | 10 | 10 | 2 |
| 26 | 26 | 9 | 9 | 1 |
| **25** | **29** | **1** | **14** | 2 |
| **24** | **29** | **1** | **14** | 1 |

At y 26-28 `$507A` is the travel y and `$507B` = `$507C` = y − 17, and it is
tempting to write that down as a copy. **It is not one.** At y 25 and below
the triple is (29, 1, 14) and does not move with the square at all.

**Reproducible, not noise.** The (7,25) reading was taken twice, on two
separate boots from two different seeds — one party that walked there from
(7,29) over four steps, and one seeded at (7,26) that took a single step —
and both wrote exactly (29, 1, 14).

**And the pair to diff is the same-slot one.** `work/p59-wallset/ycol/SAVGAMC.DAT`
at (7,28) against `work/p59-wallset/y25/SAVGAMC.DAT` at (7,25) — both engine
written, both from a slot A seed, both saved to **slot C**, and their clocks
happen to agree — differ in **23 bytes**, of which only **five words** sit
below the character table:

| word | (7,28) | (7,25) |
|---|---|---|
| `$49C4` | 28 | 25 |
| `$5079` | 13 | 6 |
| `$507A` | 28 | **29** |
| `$507B` | 11 | **1** |
| `$507C` | 11 | **14** |

Byte 0, the tail 12801-12808 and the whole 7680-byte ECL buffer are identical,
so nothing about the place, the party or the script moved. The remaining 18
bytes are in the six 41-byte character entries and are the heap scratch this
page calls engine-refilled junk.

**A caution about the obvious diff, because it looks alarming.** Diffing the
consecutive saves E and F of the `ycol` walk gives **25** differing bytes
rather than 7, and an earlier version of this section said "only" seven. Six
of the extra eighteen are byte +7 of each character entry — the **slot
letter** in `CHRDATE<n>` against `CHRDATF<n>`, because those two specimens
were saved to different slots — and the other twelve are the same per-entry
heap scratch. Diff two saves under one slot letter, or the confound is in
every comparison.

So whatever these words are, they are deterministic and position-dependent
and they are **not** the travel square. Settling experiment: a `BPM`
write-watch on `$507A` in DOSBox-X across a dozen overland steps, which is
how `$49C3` was confirmed. `work/p59-wallset/ycol` and `y25`.

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

1. byte 0 = the target area's DAX number (`goldbox/areas.py`'s `Area.disk`);
2. `$49C5` = the target area id;
3. `$49F2` = the target area id;
4. `$5012` = the target area's DAX number;
5. `$4AFA`-`$4AFC` = the target's wallset triple (sourceable from the C64
   save's cache slots 15-17, which carry the same numbers);
6. `$4AFD`-`$4AFF` = (1,2,3) or (1,$FFFF,$FFFF) to match;
7. **5121-12800 = the target's `ECL<dax>.DAX` block, from byte 2 on**;
8. 12801-12803 = x, y, facing×2;
9. `$503E` and byte 12808 = the party size.

The flags and everything else may stay the template's. `goldbox.dos_savegame.retarget`
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

And end to end through `goldbox.dos.write_dos_save`, both walked: `PORSAVE13` in
the Slums onto template A comes up at 15,4 W 21:15, and `PORSAVE12` in New
Phlan onto template J at 0,4 W 16:58 — each party's own square, facing and
clock, with six characters on the roster (`work/p60/run3` and `run4`).

## The container in the other three titles

Measured for `#53 (Read and write DOS saves for Curse, Silver Blades and
Pools of Darkness)`. This section replaced a table of file sizes and two spot
checks, three of whose claims were wrong; they are corrected here rather than
layered on. The `CHRDAT` table was given as 12822 and 5142, which is where
the ASCII starts and not
where the entry does (the length byte is at 12821 and 5141, and Pool of
Radiance's own `PARTY_TABLE` is the length byte's offset, so the table
disagreed with itself); Silver Blades' variable array was called "far
smaller", and it is not smaller at all — what is missing is the script buffer;
and Pools of Darkness was given a `SAVGAM<slot>.DAT` "plus a separate
`SAVGAM<slot>.PTY`", where it writes the `.PTY` **instead** and keeps a
12-byte `VAULT<slot>.DAT` beside it.

`goldbox/dos_savegame.py`'s `SAVE_SHAPES` is the machine-readable form: one
row per title, region widths rather than offsets, and the widths must add up
to the size the file is or the row raises at import. `tools/dossavgam.py`
prints the map and the anchors.

Measured against **thirteen containers** — Donald's played Pool of Radiance
A/B/J out of the Steam `SavesDir`, the archives' own Pool of Radiance A/B,
Curse A/B, Silver Blades A/B, Pools of Darkness A/B and Treasures of the
Savage Frontier A/B — deduplicated on their bytes, because the archives ship
most save directories twice and for three titles the copies are identical.

| region | Pool of Radiance | Curse | Silver Blades | Pools of Darkness | grade |
|---|---|---|---|---|---|
| ECL variables, **one byte each**, variable *N* at offset *N*−1 | — | — | — | **1024** | CONFIRMED from the writer (#175) — see the next section |
| container-number byte | 1 | 1 | 1 | — | CONFIRMED — it equals `$5012` in all nine containers that have both |
| ECL variables, `u16le` from `$4900` | 2560 | 2560 | 2560 | — | CONFIRMED for the three; the word count is Pool of Radiance's and untested in the other two |
| staged `ECL<n>.DAX` script | 7680 | 7680 | — | — | CONFIRMED for Pool of Radiance; PROBABLE for Curse, whose buffer is all zero in both shipped saves |
| unnamed, before the square block | — | 12 | 12 | — | UNKNOWN — Curse and Silver Blades read `07 0d 00 00 00 00 00 00 00 01 00 ff` in both specimens each. **Pools of Darkness has none**: the four this table gave it were the last four bytes of its own square block (#175) |
| square block, last byte the party size | 8 | 8 | 8 | **12** | CONFIRMED — the party-size byte reads 6 in all thirteen, and Pools of Darkness' twelve bytes are named one `BlockWrite` at a time below |
| 41-byte `CHRDAT` slots | 8 × 41 | 8 × 41 | 8 × 41 | 8 × 41 | CONFIRMED as 328 bytes in all thirteen; **eight** slots CONFIRMED for Pools of Darkness and Silver Blades from the code, PROBABLE for the other two |

**The last two slots are the 82 bytes this page called UI scratch.** Pools of
Darkness' save routine copies each character's filename to `[bp + 41*i −
0x171]` for `i` up to 8 and then writes `0x148` = 328 bytes in one
`BlockWrite` (`GAME.OVR:0x13595` and `0x13647`), so the region is eight slots
and the party fills six of them; the rest is the stack under the buffer, which
is why it reads `Camp: ` and `Choose a FUNCTION`. Its *loader* reads the same
328 bytes out of a **Silver Blades** container after seeking to 5140 — which
is that shape's own count byte exactly — so the eight-slot reading is the
engine's for that title too. Settling experiment for Pool of Radiance and
Curse: the same `BlockWrite` census on their `GAME.OVR`s.

**Curse and Silver Blades share Pool of Radiance's variable array**, at the
same offset with the same ECL addresses. Two readings 1602 words apart agree:
`$5012` equals the header byte (2 and 2 in Curse, 1 and 1 in Silver Blades)
and `$503E` equals the party-size byte (6 in both). `$49E6`, the indoors flag,
reads 1 in all four. A variable array at any other offset could not agree with
the header byte by accident.

**Silver Blades stages no script.** That is the whole of why its save is less
than half the size: 13137 − 7680 + 12 = 5469. Its scripts are not smaller —
its largest `ECL<n>.DAX` block is 7678 bytes against Pool of Radiance's 7679,
and every one of the four titles' 132 blocks fits the 7680-byte buffer — so
the engine reloads the script from the container rather than carrying it. The
one write of the recipe above that needs the player's own game files is the
one Silver Blades and Pools of Darkness would not need.

**What is missing for Curse and Silver Blades is a played save.** Both
containers of each is a shipped starting party: 272 to 295 nonzero bytes in
the whole file, an all-`$FF` square, a zero clock, no quest flags and a script
buffer that is entirely zero. Nothing about the variable array's *contents*
can be measured from them and the `07 0d` block cannot be attributed. The
Steam `SavesDir` holds Pool of Radiance's app id and no other — the same
specimen `#113 (Play DOS Curse far enough to save a party with items)` is
about. **Pools of Darkness is no longer in that list**: see the next section.

**The size names the shape, not the game.** Treasures of the Savage Frontier
writes the same 1364-byte `SAVGAM<slot>.PTY` and 12-byte `VAULT<slot>.DAT`
that Pools of Darkness does, with the same 336-byte tail, and its two
containers read cleanly through the Pools of Darkness row. Only the directory
a file came from says which game wrote it.

## Pools of Darkness: the byte-wide variable array (#175)

**The 1024 bytes at the front are the ECL variable array, one byte per
variable, and variable *N* is at file offset *N*−1.** Not the 2560 `u16le`
words the first three titles write, which is why nothing here could find
`$5012` or `$503E` under any origin: the array is byte wide and based at 0
rather than at an ECL address. `goldbox.dos_savegame.pod_var` reads it and
`SAVE_POOLS_OF_DARKNESS` is the shape.

Read out of `GAME.OVR` rather than out of a save, so the played-save blocker
this ticket carried from the day it was filed never had to be lifted.
`tools/dosptrfields.py` is what censuses the structure, and
`tools/dospod.py` is the drive that produced the containers the readings are
checked against.

### Where the file comes from, byte for byte

The save routine's eight `BlockWrite` calls, in file order
(`GAME.OVR:0x134BA` onwards). The load routine at `0x12BC5` reads the same
eight regions in the same order.

| file | size | source | grade |
|---|---|---|---|
| 0–1023 | 1024 | `[DS:0x87F8]^`, the variable array | CONFIRMED |
| 1024–1028 | 5 | `DS:0xA9F3`–`0xA9F7` — x, y, facing and two engine bytes | CONFIRMED |
| 1029 | 1 | `DS:0x880D`, the **previous** interface mode | CONFIRMED |
| 1030 | 1 | `DS:0x880C`, the **current** interface mode | CONFIRMED |
| 1031–1032 | 2 | `DS:0xA9F8`, a word the dungeon loader passes to `LoadMap` | CONFIRMED |
| 1033–1034 | 2 | `DS:0xA9FA`, its second argument | CONFIRMED |
| 1035 | 1 | the count of character files the writer's loop emitted | CONFIRMED |
| 1036–1363 | 328 | eight 41-byte filename slots | CONFIRMED |

1024 + 5 + 1 + 1 + 2 + 2 + 1 + 328 = 1364, the whole file with nothing over.
**The block really is 1024 bytes**: `GAME.OVR:0x1A275` is
`mov ax, 0x400 / lcall GetMem / mov [0x87F8], ax`, and it is the only write to
that pointer in either binary, so the first region is one allocation written
whole rather than a window onto something larger.

**So the square is at 1024, not 1028.** The four bytes this page called
"unnamed, before the square block" were the *last four* of a twelve-byte
square block, and `position()` returned three bytes of engine state for this
title until #175.

### Variable *N* at offset *N*−1

`GetVar` (`GAME.OVR:0x6F14`) and `SetVar` (`0x6D51`) both do `ax := index;
dec ax`, dispatch a handful of indices to engine globals, and otherwise reach

    les di, [0x87F8] / add di, ax / add di, 0xFFFF     ; block[index − 1]

one byte wide, two when the caller asks for a word. The intercepted indices
corroborate the arithmetic rather than escaping it: index 34 reads and writes
`es:[di+0x21]` — offset 33, its natural home — at `0x6E1B`, and index 58
writes `es:[di+0x39]` (offset 57) at `0x6EB1`.

`tools/dosptrfields.py GAME.OVR --pointer 0x87f8` finds 248 load sites and
displacements 0–58 and 195–197 and nothing else, so **variables 1–59 and
196–198 are the engine's** and every other index is whatever an `ECL1.DAX`
script puts there.

### What the engine keeps in it

| variable | file | what | grade |
|---|---|---|---|
| 5–11 | 4–10 | **the clock**, seven digits, one byte each — see below | CONFIRMED as the region; the ordering CONFIRMED for the minutes |
| 19 | 18 | **the current dungeon map**, the id the loader passes to `LoadX` (`0x12FCA`) | CONFIRMED — 16 in all eight played containers and 0 in the shipped ones, and it is one of the three bytes the community's own debug-menu recipe edits (below) |
| 22 | 21 | a second copy of the current map: zeroed by the initialiser and 16 in all eight played containers, the same value variable 19 holds | PROBABLE — never seen to disagree with variable 19, and no specimen separates them |
| 198 | 197 | a third: 16 in seven of the eight played containers and 0 in the eighth | PROBABLE — the eighth is the one standing at a door with a script message pending, so what distinguishes it is not established |
| 23, 24 | 22, 23 | **the square before the last step** | CONFIRMED — one step west wrote (11,2) here as 1024 went 11 → 10 |
| 32 | 31 | **the party count**. The save routine's own loop bound: `cmp al, es:[di+0x1f]` at `0x13205` | CONFIRMED — 6 in all ten containers, and equal to the count byte at 1035 in all ten |
| 34 | 33 | **dungeon (nonzero) or wilderness (zero)**. Two sites switch the interface mode on this byte alone — `0x1522` and `0x6E1B` write mode 4 when it is set and 3 when it is not — and `GetVar` index 17 halves the facing only when it is set | CONFIRMED as the selector, from two call sites; **never observed zero** — all ten containers are in a dungeon |
| 37, 38 | 36, 37 | the wilderness square | PROBABLE (code only); zero in all ten |
| 58 | 57 | the wilderness region, indexed into a table at `DS:0x7D08` (`0x12FE7`) | PROBABLE (code only); zero in all ten |
| 18, 27, 39, 43, 44, 52, 57, 83, 85, 151, 192, 193 | | live and unnamed — see the census below | UNKNOWN |
| 751–764 | 750–763 | a **script string buffer**: one container holds `PASSENGER DOCK` in ASCII here, and its screen reads `THIS DOOR READS 'PASSENGER DOCK'` | PROBABLE — one specimen |

**A second, independent source says the same thing.** The community's recipe
for reaching Pools of Darkness' hidden debug area is to hex-edit the `.PTY`
and *set offsets 18, 21 and 197 to 1* —
[`126-forum-findings.md`](126-forum-findings.md), where the same three offsets
set to 2 do it for Dark Queen of Krynn. Those are **single bytes**, which only
makes sense if the array is byte wide, and under this decode they are
variables 19, 22 and 198: the map id the loader reads, and two copies of it.
Found by a different person by a different method, years earlier, and it
agrees offset for offset.

**There is no separate quest-flag region, and that is the answer rather than a
gap.** The whole 1024 bytes *is* the variable space, so a flag an ECL script
sets is a byte in it at the index the script names. Which indices Pools of
Darkness' scripts use is a question for `ECL1.DAX` and not for the save file.

### The clock: seven digits at 4–10

`GAME.OVR:0x27AF4` copies `block[i + 4]` for `i` in 0..6 into a local word
array, adds one to the digit it was asked for, calls the carry routine at
`0x279F6` after each addition, and copies all seven back. Pool of Radiance's
clock is the same idea in six words instead of seven bytes.

| digit | file | radix | what |
|---|---|---|---|
| 0 | 4 | 10 | sub-minute |
| 1 | 5 | 10 | minute units |
| 2 | 6 | 6 | minute tens |
| 3 | 7 | 24 | hour |
| 4 | 8 | 30 | day |
| 5 | 9 | 12 | month |
| 6 | 10 | 100 | year, and its overflow is what ages the party |

The carry routine indexes a seven-word table at `DS:0x6D0A`. That resolves to
`GAME.EXE` file offset `0xE8F0` under a DGROUP base of `0x7BE6`, and what is
there is `0a 00 0a 00 06 00 18 00 1e 00 0c 00 64 00` — Pool of Radiance's own
six radices with **100** appended, with clean boundaries either side. It is
the only run of seven plausible radices in either binary. When digit 6
overflows, the routine walks the character list adding one to the word at
record offset `0xB0` in every character, which is the party ageing a year.

CONFIRMED for the region and for the minutes: the two containers whose status
line was captured read `00:04` and `00:07` on screen against file offset 5 =
4 and 5 = 7, with every other digit zero. PROBABLE for the four digits above
the minutes, where the radix table is the only evidence — no container on
this machine has a clock past nine minutes. Settling experiment: drive
`tools/dospod.py` far enough to pass an hour and read offsets 6 and 7.

### The square block, 1024–1035

| file | what | grade |
|---|---|---|
| 1024, 1025 | x, y on a 16 × 16 grid. The dungeon step at `0x7870` wraps 0 → 15 and 15 → 0 in both | CONFIRMED — `11,2 S 00:04` and `8,2 W 00:07` on the game's own status line against (11,2) and (8,2) in the file, and one step west moved 1024 from 11 to 10 alone |
| 1026 | facing, **doubled**: 0 N, 2 E, 4 S, 6 W, which is Pool of Radiance DOS's own encoding at 12803. `SetVar` index 17 takes 0–3 and stores 0/2/4/6 | CONFIRMED for S and W — one right turn from `11,2 S` to `11,2 W` moved this byte from 4 to 6 and **no other byte in the first 1036**. N and E are the code's reading only |
| 1027, 1028 | `DS:0xA9F6` and `DS:0xA9F7`, reachable as variables 50 and 45 | UNKNOWN — 1028 is 3 in six played containers and 0 in the two saved right after a step |
| 1029 | the **previous** interface mode. `DS:0x880D` is only ever assigned from `DS:0x880C` | CONFIRMED as the previous mode from the code; 4 in all ten containers |
| 1030 | the **current** interface mode: 3 wilderness, 4 dungeon, and 2 in all eight engine-written containers because the game is showing its own save menu when it writes the file | CONFIRMED as the mode; the 3/4 pairing CONFIRMED from `0x1522` and `0x6E1B`, the 2 measured |
| 1031–1032 | `DS:0xA9F8`. The loader takes the dungeon branch when this word is positive and the wilderness branch when it is not, and `SetVar` zeroes it when the party leaves a dungeon | PROBABLE — 1 in all eight played containers, 0 in the shipped stubs |
| 1033–1034 | `DS:0xA9FA`, `LoadMap`'s second argument | UNKNOWN — zero in all ten |
| 1035 | the count of character files, which is the party size | CONFIRMED — the writer's own loop counter, and 6 in all ten |

### The corpus, and what the shipped containers actually are

**`FillChar(block, 1024, 0)` and six assignments is the whole of a shipped
container.** `GAME.OVR:0x1A4B5` zeroes the block and then writes
`es:[di+0x26] = 3`, `es:[di+0x21] = 1`, `es:[di+0x15] = 0`,
`es:[di+0x38] = 0xA` and `es:[di+0x11] = 4`, and the party count at
`es:[di+0x1f]` follows when six characters join. That is offsets 38, 33, 21,
56, 17 and 31 — **exactly and only** the five nonzero bytes both shipped
containers hold, at 17 = 4, 31 = 6, 33 = 1, 38 = 3, 56 = 10. So they are not
merely unplayed; they are the initialiser's output, which is why no amount of
reading them named a field. CONFIRMED — the code and both containers agree on
all five.

**Eight engine-written containers exist**, from `tools/dospod.py` drives under
`work/p175` (`clock1`, `diff1`, `diff2`, `run16`, `run17`), all in a dungeon
at 00:04–00:07 with a six-strong party.
`tools/dossavcensus.py --title pools-of-darkness work/p175` re-takes every
count on this page and marks the two shipped stubs; 36 of the 1024 variables
are live in at least one of them and 988 are zero in all twelve.

**The two one-action diffs are the strongest evidence here**, and they are
single-byte:

| pair | action | bytes that moved below 1036 |
|---|---|---|
| `diff1/C` → `diff1/D` | one right turn | 1026 only, 4 → 6 |
| `diff1/D` → `diff1/E` | one step west | 5 (the clock), 22 and 23 (the previous square, → 11, 2), 26, 56, 1024 (11 → 10) and 1028 |

### Negative results, so nobody re-runs them

* **There is no header byte and no `$4900`-based word array**, and there is now
  a reason rather than an absence: the array is byte wide and 1-based from
  file offset 0, so nothing in it can line up with `$5012` or `$503E` under
  any origin. This page's earlier CONFIRMED "not the same array shifted"
  stands and is explained.
* **The `07 0d` at 1024–1025 is not a mystery pair**: it is the dungeon square
  (7, 13) the initialiser leaves. Curse and Silver Blades' twelve unnamed
  bytes **also open `07 0d 00 00 00`**, which is byte for byte what Pools of
  Darkness writes from `DS:0xA9F3`–`0xA9F7`. Worth the same `BlockWrite`
  census on their `GAME.OVR`s before anyone calls those twelve
  unattributable.
* **The eight-slot name table is not a Pools of Darkness peculiarity.** Its
  own loader reads 328 bytes at 5140 out of a *Silver Blades* container,
  which is the party-import path from the previous game, and 5140 is that
  shape's count byte exactly.
* **Treasures of the Savage Frontier's two containers differ from Pools of
  Darkness' in three bytes and nowhere else**: 82, 84 (2 and 3, zero in Pools
  of Darkness) and 1026, the facing. Both titles' A and B are byte-identical
  to each other, so the four shipped containers are worth one specimen
  between them.
* **A wilderness Pools of Darkness save has never been seen.** All ten
  containers hold variable 34 = 1, so everything this page says about the
  wilderness square, the wilderness region and interface mode 3 rests on the
  code alone. Experiment: drive out of the dungeon and save.

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
| wallset triple | the area's | **(0,$FFFF,$FFFF), written by the engine** — see below |
| wall map `$4AFD`-`$4AFF` | (1,2,3) or (1,$FFFF,$FFFF) | (1,$FFFF,$FFFF), written with it |
| `$4FD2`, `$4FD3` | the area's pair | (96, 10), the overland's pair |
| `$507A`, `$507B`, `$507C` | 0 in all 11 indoor specimens | nonzero in all 10 outdoor ones — see the variable table |

One overland step costs 12 hours on the clock. The DOS overland has no
`SQRDATA` files at all — the three windows are ordinary `GEO` blocks 25-27
in `GEO6`-`GEO8.DAX` plus `SQRPACI.DAX`/`WILDCOM.DAX`, which is presumably
why `$49C5` has nothing to carry out there.

### The wallset triple outdoors is live, not stale — CONFIRMED

This page used to say the outdoor triple's `(0,$FFFF,$FFFF)` could not be
told from the departure template's, because every overland specimen had left
from New Phlan, which holds the same three words. The separation is to depart
from somewhere else and **keep** the triple rather than overwrite it, and
`tools/dosoutdoorprobe.py --wallset keep` is the thing that does it.

Seeded from Donald's slot B — Sokol Keep, `(1, 5, 9)` — onto window 26 at
local (7,29), that triple left in place, then loaded and walked, with the
game's own `ENCAMP > SAVE` taken at three squares:

| file | travel square | `$4AFA`-`$4AFC` | `$4AFD`-`$4AFF` |
|---|---|---|---|
| the seed (ours) | (7,29) | **(1, 5, 9)** | **(1, 2, 3)** |
| C, D, E (the engine's) | (7,28), (8,28), (8,27) | (0, $FFFF, $FFFF) | (1, $FFFF, $FFFF) |

**The engine replaced a triple it had never held, three times of three.** So
`(0, $FFFF, $FFFF)` is measured for the overland rather than inherited.

**And the outdoor load path does not read the triple at all.** The save
carrying Sokol Keep's `(1, 5, 9)` on a travel window loaded and drew,
reporting `20,29 N 01:22` on the status line
(`work/p59-wallset/keep/loaded.png`). Indoors, a triple that does not match
the area kills the load in `LoadWallSet`; outdoors a wrong one is not
noticed.

### A seeded overland save is not the same specimen as a played one

`tools/dosoutdoor.py` and `tools/dosoutdoorprobe.py` put a party on the
travel grid by writing the fields and letting the engine resave, which is
much cheaper than sailing there. It is not equivalent, and at least one word
proves it. #59's August pass measured `$4DC3` = 118 indoors and **226**
outdoors, on three saves made by taking the boat. All ten seeded overland
saves held here read **118** — the value their New Phlan and Sokol Keep
sources carried — so the engine did not write it on the way out.

**PROBABLE: `$4DC3` is written by the transition that puts a party outdoors,
not by the party being outdoors.** The three played specimens are gone and
cannot be re-read, so this rests on their recorded value against ten seeded
ones. The settling experiment is to play out to the overland by boat once
more and read `$4DC3` in the save; `docs/50-experiments.md` has the route.
The same caution covers `$4DB8`, `$4E0C` and `$4FA8`, which sit in the same
group and which no seeded save has ever been seen to change.

## What a conversion inherits: nothing (#26)

The rule in `.claude/rules/conversions.md` is **measured versus inherited**: a
value we established is fine at any number, and a value taken from somebody
else's save is not. This section used to be a list of what a converted save still
took from a template. It is now a list of nothing, because there is no
template: `goldbox.dos.new_dos_save` builds all 13137 bytes from 13137 zeroes,
and `goldbox.dos.SAVGAM_UNSOURCED` carries a stated reason for every zero it
writes that a real save has ever been seen to hold something at.

**The party in a save built that way loads, walks and changes area**, and the
engine's own `ENCAMP > SAVE` writes it back --
[`117-save-conversion.md`](117-save-conversion.md), "A DOS save from
nothing", and `tools/dosnewsave.py` is the run. That is what turns a census
into a measurement: a census says what a saved party held, and only the
running game says what the load path reads.

| group | bytes | how it is written |
|---|---|---|
| written from the C64 party | 593 | the quest flags, the script scratch, the clock, the square, the party size, the six filenames -- and the place, which is byte 0, `$49C5`, `$49F2`, `$5012`, the wallset triple, the wall map and `$49E6` |
| the area's own script | 7680 | `ECL<n>.DAX` from byte 2 on, then zero to the end of the buffer -- 6 of 6 specimens hold zeros past the script's end |
| documented constants | 10 | `$4FE1` = 255, `$506D` = 16, `$50F6` = 1, and the four tail bytes 12804-12807 from `put_tail_state` |
| zeroed with a reason | 784 | `SAVGAM_UNSOURCED`'s 510 bytes of variables, and the 274 of character-table heap and menu text |
| zeroed because every specimen reads zero there | 4070 | the rest of `$4900`-`$52FF` |

**Three kinds of reason appear in `SAVGAM_UNSOURCED`,** and they are the three
legitimate ones in `.claude/rules/conversions.md`:

**1. The engine rebuilds it.** Twenty words, and every one of them was
*seen* being rebuilt -- each came back nonzero from the engine's own
`ENCAMP > SAVE` of a party loaded out of a save built entirely from zeroes.

| what | words | which run wrote them |
|---|---|---|
| the previous square | `$49F0`, `$49F1` | loading and one step |
| the two wall colours, which the arriving area's own ECL prologue writes -- `ECL00` opens `SAVE [$6E7D],[$49FD] / SAVE 10,[$49FE]` | `$49FD`, `$49FE` | loading |
| unnamed | `$4FD2`, `$4FD3`, `$507D`, `$5208`, `$520F` | loading |
| unnamed | `$5079`, `$5082`, `$5200` | walking into another area |
| unnamed | `$4FC0`, `$4FC6`, `$4FC8` | one fight |
| the pending-encounter record | `$5202`, `$5205`, `$5206` | one fight |
| the encounter and monster message buffers | `$522C`+ and `$5290`+ | one fight, which filled them with the sentence the game shouted |

Eleven of the twenty are new to this list; the other nine were #59's. The
runs are `work/p26/run2` (load, two steps, resave), `run4` (a walk that left
the Slums for New Phlan) and `run5` (a wandering encounter, fought).

Byte 12804 is in this group too, and the run **refuted** what this page used
to say about it. It read "0 indoors and 14 outdoors are the measured values
to write". The engine's own resave of a party standing **indoors** in the
Slums, walked in from a from-nothing save, holds **14** -- so the value does
not partition on indoors and out, and the doc's own corpus already had an
indoor 14 in slot B. What is CONFIRMED is only that the engine maintains it:
it replaced a written 0 with 14 in `work/p26/run2` and with 9 in #59's run 9.

**2. The C64 save has no such field.** Everything at `$4AF9` and above: no
ECL script references any address there (2544 distinct addresses across 30
scripts), and on the C64 that range is `$4B00`-`$4CFF` header remainder and
then the twelve character slots from `$4D00`. `$49FC` is here for a different
reason -- `ECL0F` is the one script of thirty that names it, and it saves it,
overwrites it and puts it back, so nothing outlives a visit; the two ports
disagree on it besides. `$49FF` is named by none of the thirty.

**3. Nobody has decoded it, and zero is what the running game accepted.**
`$4FC0`, `$4FC6` and `$4FC8` were in this list until 2026-09-02 and are not
any more: the fight run in group 1 above watched the engine write all three,
so they belong there rather than here. `$4FC1` alone is still unseen.
`$4DB8`, `$4DC3`, `$4E0C`, `$4FA8`, `$4FC1`,
`$507F`-`$5080`, `$5203`, `$5204`, `$5207`,
`$520A`-`$520E`, most of the message buffer from `$5227`, and the 274 bytes
of character-table heap and menu text. What each **means** is still UNKNOWN
and this does not claim otherwise. What is settled is that a save carrying
zero in all of them loads, draws its map, walks, changes area, fights and is
resaved by the engine -- and that the engine refilled all 274 display bytes
itself, with heap pointers and the words `Save View M` and `Camp: `.

**What would still move this section.** The message buffer's tail is declared
whole -- 217 words from `$5227` -- because it is one buffer, not 217
findings; only 65 of those words have been seen holding anything.

**The census behind the last row of the table above has been re-taken and is
no longer PROBABLE.** It used to read against **four** surviving containers,
noting that #59's twelve gave 2401 words zero and its nine indoor ones 2407,
and that the six words in the difference could not be named because the three
overland specimens were gone. `tools/dossavcensus.py` over the 21 that exist
now gives **2407 zero across the 11 indoor** — the same figure again, on
eleven specimens rather than nine — and **2402 across all 21**. The words in
the difference are **five, not six**, and all five are named: `$49C3` and
`$49C4`, the travel square, and `$507A`-`$507C`. The sixth word of the
earlier count belonged to a specimen nobody can re-read, so it stays
unaccounted for rather than being declared not to have existed.

**A conversion writes both kinds now** (#190), so neither figure alone is the
one it rests on: an indoor conversion is one of the eleven and an outdoor one
is one of the ten. That costs the sweep nothing, because the five words of the
difference — `$49C3`, `$49C4` and `$507A`-`$507C` — are each either written by
the converter or declared as dropped, so an outdoor save is covered by the same
accounting: 13137 of 13137 bytes, 0 unwritten, on both of the runs that proved
it in the game. CONFIRMED, and re-takeable in a second by anybody.

## What this leaves open

* **What the undecoded words mean.** Every one of them now has a *value* a
  conversion writes with a reason, and none of them has a name. The negative
  results are in the tables above so nobody re-runs them: 12804 has no copy
  anywhere in the file, `$49F0` is not a step counter, `$49FC` is not the
  party count, and 12804 does not partition on indoors and out.
* **The words the engine has never been seen writing**, which is what is
  left of the blocker list once #26's four runs and #59's overland probes
  are counted: `$49FC`, `$49FF`, `$4DB8`, `$4DC3`, `$4E0C`, `$4FA8`,
  `$4FC1`, `$507F`, `$5080`, `$5203`, `$5204`, `$5207` and
  `$520A`-`$520E`. Zero in each of them is CONFIRMED survivable -- a party
  carrying it loads, walks, changes area and fights -- and nothing says what
  would put a value there. The experiment for each is a `BPM` write-watch in
  DOSBox-X on its word offset, one per word, played until it fires.
  **`$507A`-`$507C` came off this list**: ten overland saves seeded with
  zeroes in all three came back holding values, so the engine writes them —
  and #190's two conversions, built from nothing rather than seeded from a
  copy, came back holding exactly what the band table below predicts,
  (29, 1, 14) at y 25 and (26, 9, 9) at y 26. Predicted before the run and
  reproduced from a different lineage, which is a reproduction rather than a
  re-reading of the same specimens.
* **What `$4FD2`/`$4FD3` count.** They partition perfectly by area over 21
  specimens and are nothing else this page can find. Experiment: a fifth
  area, then a `BPM` read-watch on `$4FD2`.
* **What `$507A`-`$507C` are.** They track the travel y for y 26-28 and
  freeze at (29, 1, 14) for y 24-25, reproducibly on two boots from two
  lineages, and again on two from-nothing conversions (#190). Experiment: a `BPM` write-watch on `$507A` across a dozen
  overland steps.
* **Whether a played overland save differs from a seeded one** beyond
  `$4DC3` -- the one word measured to differ. Experiment: sail out by boat
  once and census the result against `work/p59-wallset`.
* Moving an outdoor save to a new area (the #60 recipe with `$49E6` = 0 and
  `$49C3`/`$49C4` in place of the square bytes) has not been driven;
  `#190 (A C64 party standing on the travel grid cannot be written into a
  DOS save)` owns the converter form of it.
* **Pools of Darkness in the wilderness.** All ten containers hold variable
  34 = 1, so the wilderness square, the wilderness region and interface mode
  3 rest on the code alone. Experiment: `tools/dospod.py` out of the dungeon,
  then save.
* **The four clock digits above the minutes in Pools of Darkness.** No
  container here has run past nine minutes, so the hour, day, month and year
  positions rest on the radix table. Experiment: drive past an hour and read
  offsets 6 and 7.
* **Whether Pool of Radiance and Curse write eight name slots too.** Pools of
  Darkness and Silver Blades do, from the code. Experiment: the same
  `BlockWrite` census on `POOLRAD/GAME/POOLRAD/GAME.OVR`.
* `#57 (Carry the character portrait across ports)` asks what the game does
  with `icon_choice` on load. Its four bytes have since been decoded on that
  issue -- `portrait_head`, `portrait_body`, `icon_head`, `icon_body` -- and
  all four live in the **character record**, not in `SAVGAM<slot>.DAT`.
  Nothing in this file bears on it, which is the answer rather than a gap.
