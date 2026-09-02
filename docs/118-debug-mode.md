# A debug mode, and Fast Travel

**Status: built, driven, and no longer a debug feature.**
`automap/actions.py` implements `FastTravel` and `FastTravel Back` on `newecl_writes()`, the
sequence below has been run against the running game (`docs/50-experiments.md`,
P15 through P43), and P20 measured where a trip lands in every area that had no
arrival square. That measurement is what the debug gate was waiting for, so the
row is now shown to every user and is labelled **Fast Travel**.

**`FastTravel` in the code, "Fast Travel" on the screen.** `NEWECL` is the game's own
name for the mechanism and the classes, the action id and the settings keys keep
it; only the labels changed. This document keeps both names for the same reason.

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
| `$2019`-`$2023` | evaluate the operand; skip everything if it is `$FF` or equals the current id | **fasttraveling to the area you are already in is a no-op** |
| `$2025`-`$2027` | `$6E1B = new \| $80` | the ECL slot of the loaded-files cache, bit 7 = "reload me" |
| `$202A`-`$2032` | zero `$4A00`-`$4A1F` — `LDX #$1F / LDA #$00 / STA $4A00,X / DEX / BPL`, the store itself at `$202E` | the origin of the scratch/persistent split |
| `$2034`-`$203E` | `JSR $1A3C`, `INC $6DDD`, `LDX $03BF / TXS`, `JMP $0809` | flush the position, reset the stack, restart `DUNGEON` |

`$1A3C` is `if $49E6 then copy $C04B..$C04D into $49C0..$49C2` — so the save's
party position is written from the live one at exactly this moment, which is why
`$49C0` "lags a move".

**Every `DUNGEON` address here is a run-time address, and `DUNGEON` does not run
where its PRG header says.** The header carries `$1000`; the file is loaded and
executed at `$0800`, so a file offset maps to an address as `offset + $07FE` and
anything computed from the header comes out `$800` too high. Three independent
checks: the file opens with a jump table whose first entry is `JMP $0809`, the
restart target; `$1A3C` disassembles to the `$49E6` position copy above; and
`$09F7` is `LDA $49C9 / JSR / LDA #':' / JSR / LDA $49C8 / JSR / LDA $49C7`, the
clock printer. CONFIRMED. A stale `$282E` for the scratch wipe was this mistake
— `$202E + $800` — and run-time `$282E` is a `BEQ` in an unrelated table search.

The restart re-enters `DUNGEON` at `$0809`, which loads whatever in
`$6E13`-`$6E2B` carries bit 7 and then calls the new script's **entry 4**, the
area-initialisation entry (CONFIRMED; the write-up, `work/reports/ecl-opcodes.md`, is lost). Entry 4
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
| A fasttravel can be performed from outside by making those writes and setting PC to `$2034` | **CONFIRMED** — `docs/50-experiments.md` P15, twice: Slums → New Phlan, `ResidentGeo.identify()` returning an exact `GEO00` match, and the party then walked |
| The loader prompts for a disk when `$6E12` names one that is not in the drive | **CONFIRMED** — P17: POOL2 in the drive, `$6E12` = 3, and the game printed `INSERT SIDE # 3, AND PRESS ANY KEY.` and waited |
| `$6DD5` is "a step was taken" | **wrong, and retired.** It is zero after an ordinary step — see open question 1 |
| `$6DD5` is the count the routine at `$10EC` returns, and the exit scripts run only while it is non-zero | **PROBABLE** — `$10EE` clears it, `$1115 INC $6DD5` is the only site that raises it, and an execution checkpoint on that `INC` did not fire on an ordinary step |

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
`0 N, 1 E, 2 S, 3 W`. Sokol Keep's is the one that came from an arriving script
rather than a departing one: `ECL15 $9A92` writes `mapDir` 0, `mapX` 8, `mapY`
14 behind the scratch flag `$4A02` and then prints the boat message, and P20
watched it place a fasttraveled-in party. Fourteen areas still have none.

| id | `ECL` | `GEO` | disk | name | arrival | confidence |
|---|---|---|---|---|---|---|
| 0 | `00` | `00` | POOL3 | New Phlan | 15,1 W | CONFIRMED |
| 1 | `01` | `01` | POOL6 | Buccaneer Base | 8,0 S | CONFIRMED |
| 2 | `02` | `02` | POOL4 | Cadorna Textile House | 0,4 W | CONFIRMED |
| 3 | `03` | `03` | POOL5 | Valjevo Castle, North-West and South-East | — | PROBABLE |
| 4 | `04` | `04` | POOL5 | Valjevo Castle, North-East | — | PROBABLE |
| 5 | `05` | `05` | POOL5 | Valjevo Castle, the Hedge Maze | — | PROBABLE |
| 6 | `06` | `06` | POOL5 | Valjevo Castle, South-West | 4,15 N | PROBABLE |
| 7 | `07` | `07` | POOL5 | Valjevo Castle, the Inner Tower | 5,7 | PROBABLE |
| 8 | `08` | — | POOL3 | Phlan City Hall | — | CONFIRMED |
| 9 | `09` | `09` | POOL2 | Stojanow Gate | — | CONFIRMED |
| 10 | `0A` | `0A` | POOL4 | Valhingen Graveyard | 0,4 W | CONFIRMED |
| 11 | `0B` | — | POOL3 | The Training Hall | — | CONFIRMED |
| 13 | `0D` | `0D` | POOL8 | The Kobold Caves | 6,15 N | CONFIRMED |
| 14 | `0E` | `0E` | POOL3 | Kovel Mansion | 4,0 S | CONFIRMED |
| 15 | `0F` | `0F` | POOL2 | Mendor's Library | — | CONFIRMED |
| 16 | `10` | `10`, `1E` | POOL8 | The Lizardman Keep | 8,14 N | CONFIRMED |
| 17 | `11` | `11` | POOL7 | The Nomad Camp | 1,14 E | CONFIRMED |
| 18 | `12` | `12` | POOL1 | Podol Plaza | 0,4 W | CONFIRMED |
| 19 | `13` | — | POOL6 | Cave of Diogenes (the silver dragon's lair) | — | CONFIRMED |
| 20 | `14` | `14` | POOL2 | The Slums | — | CONFIRMED |
| 21 | `15` | `15` | POOL4 | Sokol Keep | 8,14 N | CONFIRMED |
| 22 | `16` | `16` | POOL7 | Yarash's Pyramid | 15,7 E | CONFIRMED |
| 23 | `17` | `17` | POOL7 | Yarash's Pyramid, Lower | 15,0 S | PROBABLE |
| 24 | `18` | `18`, `1F` | POOL1 | the Wealthy Area (`GEO1F` is the Temple of Bane) | 15,4 W | CONFIRMED |
| 25 | `19` | `19` + `SQRDATA04` | POOL6 | Wilderness, West Window | — (overland 14,29 †) | CONFIRMED |
| 26 | `1A` | `1A` + `SQRDATA05` | POOL7 | Wilderness, Middle Window | — (overland 7,29 †) | CONFIRMED |
| 27 | `1B` | `1B` + `SQRDATA06` | POOL8 | Wilderness, East Window | — (overland 9,29 †) | CONFIRMED |
| 28 | `1C` | `1C` | POOL6 | Zhentil Keep Outpost | 7,0 S | CONFIRMED |
| 29 | `1D` | `1D`, `20` | POOL8 | Kuto's Well (and its catacombs) | — | CONFIRMED |
| 30 | `1E` | — | POOL1 | The Attract-Mode Demo (**not fasttravelable**) | — | CONFIRMED |

Names come from `docs/88-map-files.md` (nine city blocks matched by wall
geometry), the wilderness site list and the quest flags (write-ups lost —
`work/reports/world-map.md` and `work/reports/quest-flags.md`), and — for
the nine rows the first three could not name — the DOS area tables in
`docs/128-guide-and-scripting.md` and `docs/126-forum-findings.md`.

**The five POOL5 areas are named, at PROBABLE.** The DOS guide's script list
gives 3 north-west and south-east, 4 north-east, 5 the hedge maze, 6 south-west
and 7 the inner tower; a forum area list built from `GEO` record numbers gives
3 north-west, 4 north-east, 5 south-east, 6 south-west and 7 upper level. The
two disagree at 5 and 7 and the likeliest reason is that they index different
things — one scripts, one maps — but nobody has checked. They are PROBABLE
until fasttraveling to each in turn matches `$0400` against the disk `GEO`
(`ResidentGeo`) and the floor plan is read against the compass names.

**Names are title-cased, leading article included**, because they are titles
in a dropdown: "The Slums", not "the Slums". The table used to write proper
names in capitals and descriptions in lower case, and the seam showed.

`GEO05` being the hedge maze is corroborated from our side:
[`../goldbox-bugs.md`](../goldbox-bugs.md) bug 4 identified it as a hedge maze
from 126 half-encounter-rate squares laid out along corridors and courtyards,
before any outside source was consulted.

**Area 11 is the training hall, not the arena.** Three independent lines: our
own `ECL0B` prints `THE ROOM IS FILLED WITH DUELING PAIRS.` and
`WE TRAIN ONLY <class> HERE. DO YOU WANT TO TRAIN?` at `$A0DD`, the DOS guide
names script 11 *Civilized Area (Training Hall)*, and a forum area list names
`ECL3` record 11 *Training Hall*. It has no map of its own -- the schools are
New Phlan's own squares, so `ECL0B` reuses `GEO00`. `goldbox/areas.py` was
corrected to match.

**The doubled maps belong to their neighbours.** DOS numbers maps and scripts in
one space and three maps have no script of their own: `GEO1E` (30) is the
lizardman keep's catacombs, `GEO1F` (31) the Temple of Bane inside the Wealthy
Area, and `GEO20` (32) Kuto's Well's catacombs. That is also why there is no DOS
script 30 — and the C64 put its attract-mode demo in the slot the original
numbering left free (`docs/50-experiments.md`, P20).

Fifteen areas have no known arrival square. For those the fasttravel supplies one
itself — see below — and the dropdown says so.

**† The "arrival" column is `$C04B`, and stays `—` for 25-27 on purpose --
that address is not `GDRIVE00`'s square outdoors.** The overland square in
parentheses is a different thing, `Area.overland`, written to `$49C3`/`$49C4`
instead: 26's (7,29) is the WEST-boat landing a party has been watched
standing on, 27's (9,29) is the EAST-boat landing named the same way but
never watched live, and 25's (14,29) is PROBABLE -- argued from the crossing
column and the other two windows' row, not measured, because no script names
an (x, y) in that window at all. `#178 (Fast Travel to the wilderness leaves
the party on whatever overland square it last stood on)`.

---

## 1. Where debug mode lives

**An environment variable, `WISH_DEBUG=1`, with `--debug` as an alias that sets
it — and the debug log turns it on.** `wish/debugmode.py` owns the flag:
`enabled()` reads the variable, `enable()` and `disable()` set and clear it, and
nothing else in the application touches `os.environ` for this.

The variable is the storage because one consumer is an unattended harness that
cannot click, and because `wish`, `wish-editor` and `wish-automap` are three
entry points launched from a desktop file; one variable covers all of them.

**The debug log is the switch a user gets.** `debuglog.start()` calls
`enable()` and `debuglog.stop()` calls `disable()`, so ticking Debug log in
File > Preferences is the whole of it and nobody is told to export anything.
This section used to argue the opposite — *"a logging setting that survives a
restart is one you forget is on"* — and that argument lost twice over: the log
is a remembered `Settings` field now, mitigated by `[logging]` in the title bar
and a red marker in the status bar, and Donald asked for one switch rather than
two.

**The row is no longer a launch-time decision, because it is no longer a
decision.** `AutomapWindow` used to read the flag once when it was built, which
meant the row wanted `WISH_DEBUG=1` or `--debug` on the command line: in the
`wish` window the map is built before the remembered settings are applied, so a
checkbox ticked mid-session came too late. It is built unconditionally now, in
both entry points, and there is no flag left to be applied late.

**What debug mode gates today: nothing.** The FastTravel row was the only thing it
ever gated. What remains of it is the flag itself — `--debug`, the variable, and
the line `note()` puts in the debug log and the About box — and the debug log
still turns it on and off. It is kept wired for the next control that needs a
gate: a raw-poke box and a "run script entry" control are the candidates, and
the same research makes them almost free (`$6E47`/`$6E48` is the VM's PC and
`$1581` is its fetch loop).

A line still goes in the debug log for each trip attempted, with the addresses
written — the log's privacy claims are unaffected, these are our own writes —
but that is the log's doing and not the flag's.

Nothing about the editor changes. Nothing about the save-file path changes.

---

## 2. The Fast Travel control

A row under the map, beside `ActionBar`, in the map's own column — the same
argument that put the actions there: it acts on what is drawn above it.

* **`QComboBox`**, sorted by name, holding the areas the player ticked in
  Preferences (§2.1) — three of them on a fresh config. Each row is the area's
  **name and nothing else** — `New Phlan`, not `New Phlan — GEO00, POOL3`. The
  map files and the disk are the item's tooltip, where a curious reader still
  reaches them and nobody else has to read past them. **Area 30 is not one of
  the entries**: `ECL1E` is the attract-mode demo, travelling there ends the
  session (§4), and a control that lists a session-ending choice and then
  argues about it is worse than one that does not list it. `FastTravel.legality`
  refuses it as well, which is what protects a caller that did not come through
  the dropdown.
* **`Fast Travel` button**, disabled with the reason in its tooltip, exactly as
  `ActionBar` does it: no emulator, not `ViceTarget`, `$6E11 != 1`, or the
  selected area is the current one.
* **`Travel Back`**, which restores the id and square captured before the last
  trip. One button, and it turns a trip from a one-way journey into a probe.
* **The warning is the Fast Travel button's own tooltip** — *"Fast travel to
  areas you haven't been to is dangerous and can break the game."*, Donald's
  wording, shown while the button is usable and replaced by the refusal while
  it is not. There was a `circle-info` help button at the end of the row with
  `FastTravel.HELP` under it; Donald had it out in 2026-08 — *"Remove the info icon
  with the tooltip altogether"* — so the row is four widgets and a message
  line. The same sentence is a framed amber box in Preferences ▸ Fast travel,
  because a tooltip is only read by somebody who already suspects there is
  something to read.
* **A message line** under the row, empty until something is clicked: what the
  trip did, and then **`Arrived: The Kobold Caves`** when the map lands —
  the area's name, the same one the status line under the map shows, and
  `Arrived.` where the map has no name we can give. The `GEO` file that matched
  at `$0400` goes to the debug log instead.

### 2.1 The player chooses which areas are offered

Donald asked first for the dropdown to list only the areas the party had
already been to — safer, and a purer play experience. It was built that way and
then thrown out, by the same person and for the right reason:

> I don't think we can trust our visited-areas record. The player might visit
> areas while the automapper isn't open. It isn't useful to us.

**The game keeps no such list**, which is why the filter had to infer one:
thirty area scripts walked from their area-initialisation entry point, and
exactly one writes a persistent flag merely because the party arrived — `ECL00
$B06E SAVE 1, [$4AC5]`, first entry to New Phlan, which is where every game
starts and is therefore 1 on every played save. Everything else in
`$4A20`-`$4AF8` records a scene, a fight or a search. The per-area table is
under "Does the save know where the party has been" in
[`50-experiments.md`](50-experiments.md).

So wish's own map files were the only record there was, and they only ever knew
what the automapper happened to watch. A record that is silently missing half a
campaign is worse than no record, because it looks like an answer.

**What replaced it is a setting.** `Settings.fast_travel_targets` is a list of
area ids, ticked in a table in Preferences ▸ Fast travel, and the dropdown is
exactly what is ticked. Four rules:

| | |
|---|---|
| a fresh config gets three | New Phlan, The Slums and Sokol Keep — ids 0, 20 and 21. `fast_travel_targets` is `null` until somebody ticks something (`fasttravel_areas` in a file written before 2026-08, read by `config.RENAMED`), which is what tells a fresh config from a player who unticked everything |
| an empty choice is kept | unticking everything leaves the dropdown empty, and it says `No areas ticked — Preferences ▸ Fast travel` with the button disabled and the same reason in its tooltip. The player asked for that; a control that quietly refilled itself would be lying |
| area 30 is not in the table | ticked or unticked. `Area.fasttravelable` is what says so, asked rather than the id written down a second time |
| it narrows what is offered, never what is legal | `FastTravel.legality` and the arrival-square logic are untouched |

Every fasttravelable area has a name, and area 30 — the only one without — is also
the only unfasttravelable one, so nothing has to decide what to call a nameless row.

**No confirmation, and no disk line.** Both were there until Donald tested the
feature: a dialog in front of every trip, and a row of small print naming the
`POOL` disk the area lives on. The game asks for the disk it wants itself —
`LIBRARY` prints `INSERT SIDE # n, AND PRESS ANY KEY.` and carries on once the
disk is there, exactly as it does when a player walks through the same door —
so warning first told the player only what the game was about to, and the
question the dialog asked was the one the game asks again a second later. The
`$6E12` reader stays: `Travel Back` records the disk it has to restore.

The area table is data, not UI: **`goldbox/areas.py`**, a frozen dataclass per area
carrying id, `ECL`, `GEO`s, disk, name, confidence and arrival square.
**The table above is not generated from it** -- `grep 118 tools/gendocs.py`
finds nothing, and only `goldbox/layout.py` is generated into `docs/20-character-record.md`
that way -- so a row changed in one place has to be changed by hand in the
other; corrected here while fixing `#178 (Fast Travel to the wilderness
leaves the party on whatever overland square it last stood on)`, whose rows
25-27 were edited by hand.
`automap/state.py`'s `AREA_NAMES` becomes a view over it, so there is one table
and not two.

---

## 3. What a fasttravel writes

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

**All of it is now observed.** P15 fasttraveled from the key-wait loop twice and from
`$2E4E`, the key *fetcher* the loop calls, once; both worked, because `$203A`'s
`LDX $03BF / TXS` discards the interrupted call depth either way. Half the idle
PC samples fall in the fetcher, so a harness that refuses it fails about half
the times it is asked (P36). P16 wrote `07 07 01` to `$C04B` before a fasttravel and
read it back unchanged afterwards, with `$49C0` flushed to match — so the
arrival square is written **before** the load and no second stop is needed.

**`$49E6` must be right before `$2034`.** FastTraveling out of an overland area with
`$49E6` still 0 wedges the loader in an unrecoverable `INSERT SIDE # 3` loop:
re-attaching, attaching another image and poking `$49E6` after the load had
started all failed. The same fasttravel from indoors worked first time.

### Where the party lands

Four cases, in order:

1. **The arriving script sets it** (areas 1, 16, 17, 22, 23, 28) — write nothing
   and let entry 4 do its job. This works under a fasttravel: `$49F2` holds the
   departing id right through the load, so entry 4's
   `COMPARE [$49F2], <own id>` behaves as it does in play (P43). Where a script
   places the party unconditionally, the way `ECL15` does off the scratch byte
   `$4A02`, writing that byte after the zero fill suppresses the placement and
   the fasttravel's own square is kept.
2. **We know a square another script uses** (the arrival column above) — write
   that. It is the game's own answer for that door.
3. **Neither** — pick a square from the target `GEO` read off the player's disk,
   with **`goldbox.areas.landing_square`**: the map's largest connected component,
   a square off the outer ring within it, facing an open edge.

   That rule replaced "the first square with at least one passable edge", and
   P20 is why. Measured, the old rule came to **`(0, 0)`, on every map in the
   game**, because the corner always has an edge. Nothing landed off-map or in
   solid rock, but on four maps `(0, 0)` is a walled-off pocket — 16 squares in
   `GEO1A`, 30 in `GEO19`, 32 in `GEO05`, 48 in `GEO1B` — and a party put there
   can walk without being able to leave. Staying off the rim matters for its own
   reason: the edge squares are where the game's own exits live, so a party that
   starts on one is a keypress from leaving the area it was just fasttraveled into.
   The pocket sizes are asserted in `tests/test_p20.py`'s `POCKETS`.
4. **Two kinds of area get no `$C04B` square even though they have a `GEO`:**

   * the **three overland** areas (25-27). Outdoors the position is
     `$49C3`/`$49C4`, not `$C04B`-`$C04D` -- `$C04B` is not `GDRIVE00`'s
     square there. This used to say every script entering one writes
     `[$4A18]`/`[$4A19]`, "the world-map cell"; that is wrong on both counts
     -- those bytes are scratch, zeroed by every `NEWECL`, and the only
     writers are `ECL19`/`ECL1A`/`ECL1B` on the way into their own cave,
     copying that cave's *indoor* arrival square into `$C04B`, not a
     world-map cell at all. No arriving script places an outdoor party
     (`docs/140-loaded-files-cache.md`); until
     `#178 (Fast Travel to the wilderness leaves the party on whatever
     overland square it last stood on)`, nothing else did either, which is
     why the table above marks `$C04B` `—` for these three and carries the
     overland square separately;
   * the **two `dynamic_geo`** areas (3 and 5), which choose their map at run
     time with `GETTABLE ..., mapDir`. FastTraveled into, area 3 loaded `GEO05` and
     area 5 loaded `GEO04` — neither the map the table names — so a square off
     `Area.geos[0]` is a square off a map the game was never going to show.
     Write none and let the arriving script place the party, which it does.
     Until somebody reads what `mapDir` picks, there is nothing better to do.

Keeping the party's current square is the one option to avoid: the maps do not
line up and (13,13) in the Slums is a wall in Sokol Keep.

---

## 4. Failure modes, and what each one is guarded by

| failure | what it looks like | guard |
|---|---|---|
| wrong disk in drive 8 | `LIBRARY` prints `INSERT SIDE # n, AND PRESS ANY KEY.` on row 24 and waits — the same prompt a player gets walking through the door, and it carries on once the disk is there | **the game's own prompt is the guard.** wish says nothing beforehand (§2) and times the trip out and reports. The text monitor's `attach` answers it — but the 1541 only notices a disk *change*, so the image has to be re-attached even when it is already in the drive |
| `$6E11 != 1` | `$2034` is some other overlay's code — an immediate crash | refuse; re-check at apply time, not only in the tooltip |
| PC mid-script or mid-load | the stack reset discards work in flight; the screen may be left half-drawn | refuse unless the PC is in the key-wait loop or its fetcher; refusing the fetcher alone made the button fail five times in seven |
| target == current area | nothing happens, silently, and `$4A00` is not cleared | refuse, with the reason |
| arrival square is a wall or off-map | **has never happened.** Fifteen fasttravels put the party on `(0, 0)` and it was inside the grid and had an open edge every time | choose the square from the map, never carry one over |
| arrival square is in a **pocket** of the map | the party can walk, and cannot get out: `(0, 0)` is walled off from the bulk of `GEO05`, `GEO19`, `GEO1A` and `GEO1B` | **fixed**: the square comes from the map's largest connected component, off the outer ring — `goldbox.areas.landing_square` |
| **area 30** | the attract-mode demo: `$C04B`-`$C04D` read `254, 127, 16`, no map is resident, no status line and no command bar appear, and the PC never returns to the key-wait loop, so nothing can be fasttraveled out again — the session is over | **fixed**: not offered in the dropdown, and refused by `FastTravel.legality` for a caller that did not come through it |
| a script's own **menu** is up | the next fasttravel is refused, because the PC is in the script's handler and not in the key-wait loop. The Cave of Diogenes is the one that does it on arrival — the silver dragon asks `WHAT WILL YOU SAY IS YOUR REASON FOR BEING HERE?` and waits — and it cost P20 four probes. Not a defect: waiting does not clear it | dismiss the menu, then fasttravel. Anything that fasttravels repeatedly has to clear the arriving script's **menus**, not only its messages |
| **quest flags are inconsistent** | the arriving script assumes things the party never did | unavoidable, and the honest answer is to say it under the row's help icon: a fasttravel is not the same as playing there |
| the player saves after a fasttravel | a save disk with that inconsistency baked in | debug mode must be pointed at a **copy**; the automapper never writes a disk and this does not change that |

`/home/donald/c64/Pool of Radiance Disks/` is read-only for this project and
fasttraveling does not change that: every byte here goes to RAM. The rule that matters
is the one above it — **attach a copy to the emulator**, because the game's own
save command will happily write a fasttraveled party out.

It was off by default for as long as nobody had measured where a trip lands.
P20 did: nothing landed off the map, inside a
wall or in a crash, the one area that was not a place is now unreachable, and
the pocket the old rule could drop a party into is gone. What is left is a
consequence that cannot be guarded against at all — the arriving script assumes
quest flags the party never set — and the answer to that is the help icon and a
copy of the save disk, not a hidden control.

### One hazard that is no longer a hazard

`(6,2)` in New Phlan does **not** wedge input. That claim was withdrawn in
`docs/50-experiments.md`, "There is no training-hall wedge, and it was never
(6,2)": stepping `(6,2) → (7,2)` is an ordinary encounter that takes about 25
seconds to load, the status line keeps reading `6,2` for the whole of it, and
the four runs that "died there" were four runs of one wrong assumption. The
real lesson for a fasttravel harness is the timeout: **allow 30 seconds for an area
change**, not five.

---

## 5. What it unlocks

Every one of these needs a party standing somewhere it takes an evening of play
to reach.

* **`automap/area.py` against all 29 maps.** `ResidentGeo` matches `$0400` byte
  for byte against the disk copies; fasttraveling to each area in turn turns that into
  a 29-case test instead of one anecdote about New Phlan.
* **`Fingerprint.refused()`, which nothing calls.** `docs/50` notes that one
  refused step identifies New Phlan instantly where 111 positive steps are
  needed. A fasttravel plus a scripted walk into a known wall produces that step on
  demand.
* ~~**The overland map.**~~ **Done.** A fasttravel from area 23 to area 26 came up
  outdoors with `$6E1B` = `$1A`, `$49E6` going 1 → 0 by itself, the status line
  reading `OUTDOORS 21:35 0,0` and the command bar `1-8, RETURN OR BUTTON`. No
  arrival square is needed or wanted: outdoors `GDRIVE00` is not resident and
  the travel position is `$49C3`/`$49C4`, so writing `$C04B` overwrites somebody
  else's code.
* **Combat and the combat view**, by fasttraveling to a floor with a fixed patrol
  rather than waiting on a wandering-monster roll.
* **The Quest Log**, against `ECL08` (City Hall), where the ledger the
  panel reads is actually written.
* **`GEO1E`, `GEO1F`, `GEO20`** — the three maps that share a script with
  another and that no fingerprint has ever seen. They are now *named* —
  lizardman catacombs, Temple of Bane, Kuto's Well catacombs — but still unseen.

---

## 6. Verification

A fasttravel worked if all four hold. The first three are memory reads and cost one
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
fasttravel(area) -> poll ResidentGeo.identify() every 200 ms for 30 s
           -> assert it equals the expected GEO name
           -> assert the status-line square is passable on that map
```

Unit tests need no emulator: `FastTravel.apply` returns the same `Outcome` the actions
return, with `writes` as `(address, bytes)` pairs, so the sequence above is
asserted against `MemoryTarget` and a recording stub for the PC. That is how
`tests/test_actions.py` already works.

---

## Open questions

Every question this section carried has now been run; what they found is in
`docs/50-experiments.md` under P15, P16, P17, P20 and P43, and is folded into
the sections above. Both entries below are answers rather than questions, and
**two areas have turned out to be closed to a fasttravel** — 11, which bounces, and
30, which is not a place.

1. **Is `$6DD5` really "a step was taken"? No — and the mover has been found.**
   It is not `$0B05`, which still has never executed. It is **`$1115`, an
   `INC $6DD5`**, and it lives inside the routine that `$10EC` starts — the same
   routine whose first act is to clear the byte:

   ```
   $10EC  LDA #$00 / STA $6DD5      ; clear on entry
   $10F1  LDA $C04E / BEQ +7 / JSR $0843
   $1111  CMP #$10 / BCC +3 / INC $6DD5 / DEX / BPL ...
   $111B  LDA $6DD5 / RTS           ; the count is the return value
   ```

   So `$6DD5` is not a flag at all: it is a **count**, of however many entries
   of whatever the loop walks come out at `$10` or more, and the routine hands
   it back in A. That is why the eighteen scripts open with
   `COMPARE [$6DD5], 0 / IF= / EXIT` — `IF=` runs the instruction after it, so
   the script gives up when the count is zero and does its work when it is not.

   Measured, on a converted save in New Phlan and the Slums:

   * an **execution checkpoint on `$1115`** did not fire at all across an
     ordinary forward step, while `$111E` — the `RTS` — fired once with `A = 0`.
     Reading the byte afterwards could never have told "never set" from "set and
     cleared again"; the checkpoint can, and it says never set.
   * a **store watchpoint** across the step that walked out of New Phlan and
     into the Slums caught exactly two writes: `$10EE` with 0, then `$1115`
     leaving 1. The exit script ran and the area changed.
   * six ordinary and refused steps read 0 afterwards; both boundary crossings
     read 1.

   **PROBABLE**, and what would promote it is naming the table: `X` counts it
   down, `$0843` is called first when `$C04E` is non-zero, and nobody has read
   either. The old label is retired — a byte that is zero after an ordinary step
   is not "a step was taken".
2. **Does a fasttravel to an area with no known arrival square land somewhere legal?
   Answered: mostly, and the exceptions are worth fixing.** All fifteen were
   fasttraveled into with the square `FastTravel` itself picks —
   nothing landed off the map or inside a wall and nothing crashed. The table
   of all fifteen was in `work/reports/p20-arrivals.md`, which is lost. Three
   findings came out of it:

   * the fallback picked **`(0, 0)` on every map**, and on `GEO05`, `GEO19`,
     `GEO1A` and `GEO1B` that corner is a walled-off pocket;
   * **area 30 should not be fasttravelable at all.** `ECL1E` is the attract-mode
     demo: the party square reads `254, 127, 16`, no map is resident, and the
     program counter never comes back to the key-wait loop, so no further fasttravel
     can be made;
   * **area 21 does have an arrival square** and it is in the bytecode:
     `ECL15 $9A92` writes `mapDir` 0, `mapX` 8, `mapY` 14 behind the scratch
     flag `$4A02`, then prints the boat message. Watched happening, twice.

   Two smaller things the run pinned down: areas 3 and 5 load `GEO05` and
   `GEO04` respectively, not the maps the table names, and a fasttravel cannot be
   started while a script's own menu is up — the Cave of Diogenes' parlay cost
   four probes.

   **All five recommendations are now in the code.** Area 30 is out of the
   dropdown and refused by `FastTravel.legality`; the fallback is
   `goldbox.areas.landing_square`; the overland and `dynamic_geo` areas get no
   square; area 21 carries `Arrival(8, 14, 0)`. §3 above is the current rule.

**One area a fasttravel cannot enter: 11, the training hall.** `ECL0B`'s entry reads
`$6E82` — set from the *departing* square's attribute byte by
`AND 127, ATTR, [$6E82]` — and walks `$9800` from 10 to 18 against it to choose a
school. FastTraveled in three times, once with `$6E82` forced to 10: every time `$6E1B`
went `$8B` → `$0B` → `$00` within eight seconds and the party was back in New
Phlan. The target reads state the departure was supposed to leave behind, which
is exactly the class of assumption `FastTravel`'s standing warning is about, and it is
what blocked the test-party work in `docs/119-test-party.md`.
