# A debug mode, and Warp To

**Status: built, and driven.** `wish/debugmode.py` gates it, `automap/actions.py`
implements `Warp` and `Warp Back` on `newecl_writes()`, and the sequence below
has been run against the running game — see `docs/50-experiments.md`, P15 through
P43. What follows is the mechanism and the evidence, not a proposal; where a
section still reads as a plan it is describing UI that was built as described.

---

## The finding: an area exit is nine bytes and an overlay restart

The hypothesis was right. **A script fires**, and it is the area's own `ECL`.
The exit is not a table of doorway squares in the map file and not a patched
filename; it is bytecode reached through the square-attribute dispatch that
`docs/50-experiments.md` already documented, and it ends in one opcode.

The shape, in every one of the eleven scripts that leave a map:

```
COMPARE [$6DD5], 0 / IF= / EXIT     ; gate of unknown meaning -- see below
CALL [$C01E]                        ; GDRIVE00 entry 10
SAVE 255, [$6DC9]                   ; cancel the move the party was making
[ SAVE <x>, mapX / <y>, mapY / <d>, mapDir ]   ; where you land, sometimes
[ SAVE <n>, [$6E12] ]               ; which POOL disk the next area is on
NEWECL <area>
```

`mapX`, `mapY`, `mapDir` are `$C04B`, `$C04C`, `$C04D` — the live party square
inside `GDRIVE00`, of which `$49C0`-`$49C2` is a lagging copy.

**`NEWECL` — opcode `$20`, handler `DUNGEON $2011` — is the whole transition.**
It does not load a map. It does five things:

| at | what | why it matters to us |
|---|---|---|
| `$2011`-`$2016` | `$49F2 = $6E1B & $7F` | the **outgoing** area id, which is how the arriving script knows where you came from |
| `$2019`-`$2023` | evaluate the operand; skip everything if it is `$FF` or equals the current id | **warping to the area you are already in is a no-op** |
| `$2025`-`$2027` | `$6E1B = new \| $80` | the ECL slot of the loaded-files cache, bit 7 = "reload me" |
| `$202A`-`$2032` | zero `$4A00`-`$4A1F` | the origin of the scratch/persistent split |
| `$2034`-`$203E` | `JSR $1A3C`, `INC $6DDD`, `LDX $03BF / TXS`, `JMP $0809` | flush the position, reset the stack, restart `DUNGEON` |

`$1A3C` is `if $49E6 then copy $C04B..$C04D into $49C0..$49C2` — so the save's
party position is written from the live one at exactly this moment, which is why
`$49C0` "lags a move".

The restart re-enters `DUNGEON` at `$0809`, which loads whatever in
`$6E13`-`$6E2B` carries bit 7 and then calls the new script's **entry 4**, the
area-initialisation entry (`work/reports/ecl-opcodes.md`, CONFIRMED). Entry 4
looks like this, in 26 of 30 scripts:

```
SAVE <n>, [$49FD] / SAVE <n>, [$49FE]     ; wall colours
LOADFILES <own GEO>, <n>, <n>             ; the map, at last
LOADPIECES <a>, <b>, <c>
COMPARE [$49F2], <own id> / IF= / EXIT    ; re-entry from itself: change nothing
[ SAVE <x>, mapX / <y>, mapY / <d>, mapDir ]
```

`LOADFILES`' handler is `$2041`: operand 1 goes to `$49C5` unless it is `$FF`,
and `$49C5` is then requested as **file type 2 (`GEO`)** when `$49E6` says
indoors, or **type 4 (`SQRDATA`)** when it says the overland map. Those are
cache slots `$6E15` and `$6E17`, mirrored in a save at `$4BC2` and `$4BC4`.

### Confidence

| claim | confidence |
|---|---|
| An exit is a per-square script id dispatched by the area's `ECL`, ending in `NEWECL` | **CONFIRMED** — the `GEO00` (6,2) prediction in `docs/50-experiments.md`, and eleven scripts with the shape above |
| `NEWECL` sets `$49F2`, `$6E1B\|$80`, zeroes `$4A00`-`$4A1F`, restarts at `$0809` | **CONFIRMED** — read off `DUNGEON $2011`-`$203E` |
| `$6E12` is the `POOL` disk the target area lives on | **CONFIRMED** — 32 of 33 static `SAVE n, [$6E12]` / `NEWECL t` pairs match the disk that carries `ECLt`; the one exception sets it in a `GOSUB` |
| The arriving script loads its own `GEO`, not the departing one | **CONFIRMED** — every script's `LOADFILES` first operand is its own id (see the exceptions below) |
| `$C04B`/`$C04C`/`$C04D` are the party square and writing them teleports | **CONFIRMED** — `$1A3C`; 29 of 30 scripts write them |
| A warp can be performed from outside by making those writes and setting PC to `$2034` | **CONFIRMED** — `docs/50-experiments.md` P15, twice: Slums → New Phlan, `ResidentGeo.identify()` returning an exact `GEO00` match, and the party then walked |
| The loader prompts for a disk when `$6E12` names one that is not in the drive | **CONFIRMED** — P17: POOL2 in the drive, `$6E12` = 3, and the game printed `INSERT SIDE # 3, AND PRESS ANY KEY.` and waited |
| `$6DD5` is "a step was taken" | **GUESS**, demoted — see open question 5 |

**A table of exit squares per area does not exist**, and neither does a patched
filename stem: `automap/area.py`'s `FilenameDigits` was already retired for the
same reason (`$24B4` reads six bytes of graphics). The two mechanisms the
evidence supports are the script and the cache slot; nothing else.

---

## The areas

Thirty scripts, twenty-nine maps, and they are not one-to-one. `ECL0C` does not
exist; `ECL08`, `ECL0B`, `ECL13` and `ECL1E` have no `LOADFILES` and therefore no
map of their own; three scripts carry two maps each.

Arrival is the square the game itself puts you on, harvested from the departing
scripts' `SAVE <n>, mapX` and from the arriving scripts' entry 4. Facing is
`0 N, 1 E, 2 S, 3 W`.

| id | `ECL` | `GEO` | disk | name | arrival | confidence |
|---|---|---|---|---|---|---|
| 0 | `00` | `00` | POOL3 | New Phlan | 15,1 W | CONFIRMED |
| 1 | `01` | `01` | POOL6 | Buccaneer Base | 8,0 S | CONFIRMED |
| 2 | `02` | `02` | POOL4 | Cadorna Textile House | 0,4 W | CONFIRMED |
| 3 | `03` | `03` | POOL5 | Valjevo Castle, north-west and south-east | — | PROBABLE |
| 4 | `04` | `04` | POOL5 | Valjevo Castle, north-east | — | PROBABLE |
| 5 | `05` | `05` | POOL5 | Valjevo Castle, the hedge maze | — | PROBABLE |
| 6 | `06` | `06` | POOL5 | Valjevo Castle, south-west | 4,15 N | PROBABLE |
| 7 | `07` | `07` | POOL5 | Valjevo Castle, the inner tower | 5,7 | PROBABLE |
| 8 | `08` | — | POOL3 | Phlan City Hall | — | CONFIRMED |
| 9 | `09` | `09` | POOL2 | Stojanow Gate | — | CONFIRMED |
| 10 | `0A` | `0A` | POOL4 | Valhingen Graveyard | 0,4 W | CONFIRMED |
| 11 | `0B` | — | POOL3 | the training hall | — | CONFIRMED |
| 13 | `0D` | `0D` | POOL8 | the kobold caves | 6,15 N | CONFIRMED |
| 14 | `0E` | `0E` | POOL3 | Kovel Mansion | 4,0 S | CONFIRMED |
| 15 | `0F` | `0F` | POOL2 | Mendor's Library | — | CONFIRMED |
| 16 | `10` | `10`, `1E` | POOL8 | the lizardman keep | 8,14 N | CONFIRMED |
| 17 | `11` | `11` | POOL7 | the nomad camp | 1,14 E | CONFIRMED |
| 18 | `12` | `12` | POOL1 | Podol Plaza | 0,4 W | CONFIRMED |
| 19 | `13` | — | POOL6 | Cave of Diogenes (the silver dragon's lair) | — | CONFIRMED |
| 20 | `14` | `14` | POOL2 | the Slums | — | CONFIRMED |
| 21 | `15` | `15` | POOL4 | Sokol Keep | — | CONFIRMED |
| 22 | `16` | `16` | POOL7 | Yarash's pyramid | 15,7 E | CONFIRMED |
| 23 | `17` | `17` | POOL7 | Yarash's pyramid, lower | 15,0 S | PROBABLE |
| 24 | `18` | `18`, `1F` | POOL1 | the Wealthy Area (`GEO1F` is the Temple of Bane) | 15,4 W | CONFIRMED |
| 25 | `19` | `19` + `SQRDATA04` | POOL6 | wilderness, west window | — | CONFIRMED |
| 26 | `1A` | `1A` + `SQRDATA05` | POOL7 | wilderness, middle window | — | CONFIRMED |
| 27 | `1B` | `1B` + `SQRDATA06` | POOL8 | wilderness, east window | — | CONFIRMED |
| 28 | `1C` | `1C` | POOL6 | Zhentil Keep outpost | 7,0 S | CONFIRMED |
| 29 | `1D` | `1D`, `20` | POOL8 | Kuto's Well (and its catacombs) | — | CONFIRMED |
| 30 | `1E` | — | POOL1 | the attract-mode demo | — | CONFIRMED |

Names come from `docs/88-map-files.md` (nine city blocks matched by wall
geometry), `work/reports/world-map.md` (the wilderness site list),
`work/reports/quest-flags.md`, and — for the nine rows the first three could not
name — the DOS area tables in `docs/128-guide-and-scripting.md` and
`docs/126-forum-findings.md`.

**The five POOL5 areas are named, at PROBABLE.** The DOS guide's script list
gives 3 north-west and south-east, 4 north-east, 5 the hedge maze, 6 south-west
and 7 the inner tower; a forum area list built from `GEO` record numbers gives
3 north-west, 4 north-east, 5 south-east, 6 south-west and 7 upper level. The
two disagree at 5 and 7 and the likeliest reason is that they index different
things — one scripts, one maps — but nobody has checked. They are PROBABLE
until warping to each in turn matches `$0400` against the disk `GEO`
(`ResidentGeo`) and the floor plan is read against the compass names.

`GEO05` being the hedge maze is corroborated from our side:
[`../goldbox-bugs.md`](../goldbox-bugs.md) bug 4 identified it as a hedge maze
from 126 half-encounter-rate squares laid out along corridors and courtyards,
before any outside source was consulted.

**Area 11 is the training hall, not the arena.** Three independent lines: our
own `ECL0B` prints `THE ROOM IS FILLED WITH DUELING PAIRS.` and
`WE TRAIN ONLY <class> HERE. DO YOU WANT TO TRAIN?` at `$A0DD`, the DOS guide
names script 11 *Civilized Area (Training Hall)*, and a forum area list names
`ECL3` record 11 *Training Hall*. `por/areas.py` still calls it "the arena" and
needs the same correction.

**The doubled maps belong to their neighbours.** DOS numbers maps and scripts in
one space and three maps have no script of their own: `GEO1E` (30) is the
lizardman keep's catacombs, `GEO1F` (31) the Temple of Bane inside the Wealthy
Area, and `GEO20` (32) Kuto's Well's catacombs. That is also why there is no DOS
script 30 — and the C64 put its attract-mode demo in the slot the original
numbering left free (`docs/50-experiments.md`, P20).

Fifteen areas have no known arrival square. For those the warp supplies one
itself — see below — and the dropdown says so.

---

## 1. Where debug mode lives

**Recommendation: an environment variable, `WISH_DEBUG=1`, with `--debug` as an
alias that sets it. No `Settings` field, no persistence.**

`wish/window.py` already makes the argument for the debug log: *"Off at every
start, and deliberately not remembered: a logging setting that survives a
restart is one you forget is on."* A mode that **writes to the running game**
earns that rule twice over. A `Settings` flag is the one option to reject
outright.

An env var over a menu item alone, because the consumer is an unattended test
harness that cannot click. An env var over a bare flag, because `wish`,
`wish-editor` and `wish-automap` are three entry points and the packaged build
is launched from a desktop file; one variable covers all of them.

New module `wish/debugmode.py`, about fifteen lines: `enabled()` reads the
variable once, `enable()` for `--debug` and for tests. Nothing else imports
`os.environ`.

What it gates, and only this:

* the Warp row on the automapper screen;
* a line in the debug log each time a warp is attempted, with the addresses
  written — the log's privacy claims are unaffected, these are our own writes;
* later, if wanted: a raw-poke box and a "run script entry" control, which the
  same research makes almost free (`$6E47`/`$6E48` is the VM's PC and `$1581` is
  its fetch loop).

Nothing about the editor changes. Nothing about the save-file path changes.

---

## 2. The Warp To control

A row under the map, beside `ActionBar`, in the map's own column — the same
argument that put the actions there: it acts on what is drawn above it.

* **`QComboBox`**, thirty entries, sorted by name with the unidentified last.
  Each row reads `New Phlan — GEO00, POOL3`. An area with no name reads
  `ECL1E — no map, POOL1`, which is honest and still selectable.
* **`Warp To` button**, disabled with the reason in its tooltip, exactly as
  `ActionBar` does it: no emulator, not `ViceTarget`, `$6E11 != 1`, or the
  selected area is the current one.
* **A disk line** under the row: `needs POOL7 — POOL3 is in drive 8`. This is
  the same free win `docs/113-world-map.md` identified for the overland map.
* **`Warp Back`**, which restores the id and square captured before the last
  warp. One button, and it turns a warp from a one-way trip into a probe.

The area table is data, not UI: **`por/areas.py`**, a frozen dataclass per area
carrying id, `ECL`, `GEO`s, disk, name, confidence and arrival square, generated
into this document by `tools/gendocs.py` the way `por/layout.py` already is.
`automap/state.py`'s `AREA_NAMES` becomes a view over it, so there is one table
and not two.

---

## 3. What a warp writes

Preconditions, all read first, one round trip:

| read | must be |
|---|---|
| `$6E11` | `1` — `DUNGEON` is the resident overlay |
| `$6E1B & $7F` | not the target; `NEWECL` skips a same-area transition and so would we |
| `$49E6` | non-zero for a `GEO` area, zero for the overland map |
| PC | inside `DUNGEON`'s world key-wait loop, `$10C2`-`$10EB`, **or** inside the key fetcher it calls, `$2E4E`-`$2E6A` — not mid-script, not mid-load. Both bounds are measured, from 400 PC samples of an idle party (P36) |

Then, in this order, and this is the game's own sequence with the operand
evaluation removed:

| # | write | bytes | from |
|---|---|---|---|
| 1 | `$6E12` = disk number | 1 | the departing scripts' `SAVE n, [$6E12]` |
| 2 | `$C04B`-`$C04D` = x, y, facing | 3 | the arrival square, when we are supplying one |
| 3 | `$49F2` = current `$6E1B & $7F` | 1 | `$2011`-`$2016` |
| 4 | `$6E1B` = target \| `$80` | 1 | `$2025`-`$2027` |
| 5 | `$4A00`-`$4A1F` = zero | 32 | `$202A`-`$2032` |
| 6 | PC = `$2034` | — | the tail of `NEWECL`, run as the game runs it |

Then resume. **Entering at `$2034` rather than `$2011` is the whole trick**: it
skips the operand fetch, which needs a script stream we are not in, and keeps
`JSR $1A3C` (flush `$C04B` into `$49C0`) and `INC $6DDD`, which we would
otherwise have to guess at. `$203A` reloads the stack pointer from `$03BF`, so
the call depth we interrupt does not matter and the `JSR` at `$2034` costs
nothing.

**All of it is now observed.** P15 warped from the key-wait loop twice and from
`$2E4E`, the key *fetcher* the loop calls, once; both worked, because `$203A`'s
`LDX $03BF / TXS` discards the interrupted call depth either way. Half the idle
PC samples fall in the fetcher, so a harness that refuses it fails about half
the times it is asked (P36). P16 wrote `07 07 01` to `$C04B` before a warp and
read it back unchanged afterwards, with `$49C0` flushed to match — so the
arrival square is written **before** the load and no second stop is needed.

**`$49E6` must be right before `$2034`.** Warping out of an overland area with
`$49E6` still 0 wedges the loader in an unrecoverable `INSERT SIDE # 3` loop:
re-attaching, attaching another image and poking `$49E6` after the load had
started all failed. The same warp from indoors worked first time.

### Where the party lands

Three cases, in order:

1. **The arriving script sets it** (areas 1, 16, 17, 22, 23, 28) — write nothing
   and let entry 4 do its job. This works under a warp: `$49F2` holds the
   departing id right through the load, so entry 4's
   `COMPARE [$49F2], <own id>` behaves as it does in play (P43). Where a script
   places the party unconditionally, the way `ECL15` does off the scratch byte
   `$4A02`, writing that byte after the zero fill suppresses the placement and
   the warp's own square is kept.
2. **We know a square another script uses** (the arrival column above) — write
   that. It is the game's own answer for that door.
3. **Neither** — pick a square from the target `GEO` read off the player's disk:
   the first square with at least one passable edge and, where the automapper
   has explored the area before, a square it has recorded the party standing on.
   `por/geo.py` already answers both questions and needs no emulator.

Keeping the party's current square is the one option to avoid: the maps do not
line up and (13,13) in the Slums is a wall in Sokol Keep.

---

## 4. Failure modes, and why it is off by default

| failure | what it looks like | guard |
|---|---|---|
| wrong disk in drive 8 | `LIBRARY` prints `INSERT SIDE # n, AND PRESS ANY KEY.` on row 24 and waits for ever | read `$6E12`'s disk and say so before warping; time the warp out and report. The text monitor's `attach` answers it — but the 1541 only notices a disk *change*, so the image has to be re-attached even when it is already in the drive |
| `$6E11 != 1` | `$2034` is some other overlay's code — an immediate crash | refuse; re-check at apply time, not only in the tooltip |
| PC mid-script or mid-load | the stack reset discards work in flight; the screen may be left half-drawn | refuse unless the PC is in the key-wait loop or its fetcher; refusing the fetcher alone made Warp To fail five times in seven |
| target == current area | nothing happens, silently, and `$4A00` is not cleared | refuse, with the reason |
| arrival square is a wall or off-map | not a crash — the party stands inside a wall and cannot move | choose the square from the map, never carry one over |
| **quest flags are inconsistent** | the arriving script assumes things the party never did | unavoidable, and the honest answer is to say it in the tooltip: a warp is not the same as playing there |
| the player saves after a warp | a save disk with that inconsistency baked in | debug mode must be pointed at a **copy**; the automapper never writes a disk and this does not change that |

`/home/donald/c64/Pool of Radiance Disks/` is read-only for this project and
warping does not change that: every byte here goes to RAM. The rule that matters
is the one above it — **attach a copy to the emulator**, because the game's own
save command will happily write a warped party out.

Off by default because it writes to a running machine on a control that is one
click from the map, and because a feature nobody in normal play needs should not
be on the screen at all.

### One hazard that is no longer a hazard

`(6,2)` in New Phlan does **not** wedge input. That claim was withdrawn in
`docs/50-experiments.md`, "There is no training-hall wedge, and it was never
(6,2)": stepping `(6,2) → (7,2)` is an ordinary encounter that takes about 25
seconds to load, the status line keeps reading `6,2` for the whole of it, and
the four runs that "died there" were four runs of one wrong assumption. The
real lesson for a warp harness is the timeout: **allow 30 seconds for an area
change**, not five.

---

## 5. What it unlocks

Every one of these needs a party standing somewhere it takes an evening of play
to reach.

* **`automap/area.py` against all 29 maps.** `ResidentGeo` matches `$0400` byte
  for byte against the disk copies; warping to each area in turn turns that into
  a 29-case test instead of one anecdote about New Phlan.
* **`Fingerprint.refused()`, which nothing calls.** `docs/50` notes that one
  refused step identifies New Phlan instantly where 111 positive steps are
  needed. A warp plus a scripted walk into a known wall produces that step on
  demand.
* ~~**The overland map.**~~ **Done.** A warp from area 23 to area 26 came up
  outdoors with `$6E1B` = `$1A`, `$49E6` going 1 → 0 by itself, the status line
  reading `OUTDOORS 21:35 0,0` and the command bar `1-8, RETURN OR BUTTON`. No
  arrival square is needed or wanted: outdoors `GDRIVE00` is not resident and
  the travel position is `$49C3`/`$49C4`, so writing `$C04B` overwrites somebody
  else's code.
* **Combat and the combat view**, by warping to a floor with a fixed patrol
  rather than waiting on a wandering-monster roll.
* **The commissions panel**, against `ECL08` (City Hall), where the ledger the
  panel reads is actually written.
* **`GEO1E`, `GEO1F`, `GEO20`** — the three maps that share a script with
  another and that no fingerprint has ever seen. They are now *named* —
  lizardman catacombs, Temple of Bane, Kuto's Well catacombs — but still unseen.

---

## 6. Verification

A warp worked if all four hold. The first three are memory reads and cost one
round trip together.

| check | address | expected |
|---|---|---|
| the script changed | `$6E1B & $7F` | the target id |
| the map changed | `$6E15 & $7F` (`$4BC2` in a save) | the target's `GEO` number |
| **the map is the right map** | `$0400`-`$07FF` | byte-identical to the disk copy — `ResidentGeo.identify()` |
| the party is somewhere sane | the game's own status line | a square that is walkable on that map |

The third is the one that matters and it already exists: an exact 1024-byte
match against the file, so a hit is certain and needs no fingerprinting.

Automated, the whole thing is one function:

```
warp(area) -> poll ResidentGeo.identify() every 200 ms for 30 s
           -> assert it equals the expected GEO name
           -> assert the status-line square is passable on that map
```

Unit tests need no emulator: `Warp.apply` returns the same `Outcome` the actions
return, with `writes` as `(address, bytes)` pairs, so the sequence above is
asserted against `MemoryTarget` and a recording stub for the PC. That is how
`tests/test_actions.py` already works.

---

## Open questions

Six of the seven questions this section carried have been run; what they found
is in `docs/50-experiments.md` under P15, P16, P17, P20 and P43, and is folded
into the sections above. Two remain, and one area has turned out to be closed to
a warp entirely.

1. **Is `$6DD5` really "a step was taken"?** **GUESS**, demoted. A store
   watchpoint caught exactly one write per keypress and always the same one:
   `$10EE`, `STA $6DD5` with A = 0 — the flag being *cleared* as the key is
   fetched. The other writer, `$0B05` (`LDA $B0 / STA $6DD5`, sitting between
   `JSR $C027` and `JSR $19CA` in the resident `DUNGEON`), **did not execute** on
   an ordinary forward step or on a step that fired a square script. **The two
   writers are not symmetrical** and the old wording — "written by `$0B05`/`$10EE`"
   — hid that: `$0B05` sets it from zero page `$B0`, `$10EE` clears it. So either
   `$0AF0`'s dispatch block belongs to a mover nobody has exercised, or the
   eighteen scripts that open with `COMPARE [$6DD5], 0 / IF= / EXIT` always take
   that `EXIT`. Finding the mover settles it.
2. **Does a warp to an area with no known arrival square land somewhere legal?**
   Areas 3, 4, 5, 9, 15, 20, 21 and 29 have never been tried with a square
   chosen from the `GEO`.

**One area a warp cannot enter: 11, the training hall.** `ECL0B`'s entry reads
`$6E82` — set from the *departing* square's attribute byte by
`AND 127, ATTR, [$6E82]` — and walks `$9800` from 10 to 18 against it to choose a
school. Warped in three times, once with `$6E82` forced to 10: every time `$6E1B`
went `$8B` → `$0B` → `$00` within eight seconds and the party was back in New
Phlan. The target reads state the departure was supposed to leave behind, which
is exactly the class of assumption `Warp`'s standing warning is about, and it is
what blocked the test-party work in `docs/119-test-party.md`.
