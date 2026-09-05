# Fast travel for more than one game — plan

Donald: *"I think the Fast Travel options in the automapper are Pool of
Radiance specific, aren't they? … It may need a new tab bar for each game we
support."*

They are. But the dialog is the last problem, not the first.

## 0. The four answers, up front

| question | answer | grade |
|---|---|---|
| Is the area table per-title? | **No.** `goldbox/areas.py:AREAS` is thirty Pool of Radiance `ECL` scripts with `POOL`-disk numbers in them. What P10/P24 made per-title was `GEO_NAMES` — map file → name — and nothing else | CONFIRMED, read |
| What do we have for Curse and Silver Blades? | **Silver Blades has a table**: twenty-two areas, seventeen maps, the disk side for every one, twelve arrival squares, no names -- `goldbox.areas.AREAS_SILVER_BLADES`, built by `tools/areatable.py` off its own six sides for `#20 (Build an area table for Silver Blades)`. Curse has decoded `GEO` files and the same reader waiting on it | CONFIRMED that the rows are what the scripts say; PROBABLE that the game does what they say, because no warp has landed |
| What do we have for Pools of Darkness? | **The C64 never got it.** `docs/124` §1: the four-game run ends on the Amiga precisely because of this, and `goldbox/games.py` has six titles and PoD is not one of them | CONFIRMED |
| Does the fasttravel mechanism transfer? | **Yes.** `NEWECL` is the same routine in Curse and in Silver Blades, and four driven warps landed a Curse party in four different areas. §6 | CONFIRMED for Curse, PROBABLE for Silver Blades |

So the honest shape of the feature today is **one title with a list and two
with an empty one**, and the work that matters is building the tables, not
building the tab bar.

## 1. What is already per-title, exactly

`goldbox/games.py` carries six frozen `Game` descriptors — Pool of Radiance, Curse,
Silver Blades, Champions of Krynn, Death Knights of Krynn, Gateway to the
Savage Frontier — with save geometry, race and class tables, item-name load
address and disk glob. Nothing in it touches areas.

`goldbox/areas.py` splits in two:

* **`AREAS`** — thirty `Area` rows, each an `ECL` id, a `POOL` disk 1–8, its
  `GEO`s, an arrival square and a confidence. Pool of Radiance only, and not
  parameterised. `automap/actions.area_rows()` returns it whole and
  `wish/preferences.py` builds the tick table straight off it.
* **`GEO_NAMES`** — `{title: {geo: name}}`, with `CURSE_OF_THE_AZURE_BONDS`
  present and **empty** on purpose, because `GEO15` is Sokol Keep in one game
  and somewhere else in the other. `area_name` degrades to `"area 21"` for an
  unknown title rather than lying.

The title reaches that table already: `AutomapState.title` is set from the open
save's `Game`, failing that from whichever title's disks are in the disks
folder (`automap.__main__.titles_in`), failing that `games.DEFAULT` — so the
map's labels are per-title today and the fast-travel dropdown is not.

**P10 "one area table, keyed by title" is retired**, and reading it as "the
areas are per-title" is the trap. What it delivered was the names table.

## 2. What exists for the other titles

| | Pool of Radiance | Curse | Silver Blades | Pools of Darkness |
|---|---|---|---|---|
| C64 release | yes | yes | yes | **none** |
| `GEO` files decoded | 29 | 16, reciprocity ≥ 0.935 | 17, wall-art reciprocity 1.000 | — |
| map ids | dense `GEO00`–`GEO1F` | sparse, chapter-grouped `01 03 04 / 10 11 15 / …` | sparse `$10`–`$62`; **high nibble is the disk side** | — |
| area names | 29 of 30 | **none** | **none** | — |
| `ECL` ids and area→map relation | fully decoded | ids read, 23 scripts | **fully decoded**, 22 scripts, `tools/areatable.py` | — |
| which disk carries which script | yes, `Area.disk` | read, not tabled | yes, `Area.disk`, corroborated 29 of 29 against the scripts' own disk writes | — |
| arrival squares | 16 harvested, `landing_square` for the rest | 12 read, not tabled | 12 read, all from the arriving script's entry 4 | — |
| live automapper run | shipping | done, `docs/120` tier 4 | done, `docs/121` phase 5 | — |

Sources: `docs/120-curse-testing.md` §§2, 4; `docs/121-silver-blades.md` §§1,
5; `docs/124-amiga-port.md` §1.

**There is no table to tick for Curse or Silver Blades.** Naming Curse's
sixteen maps needs somebody who has played it; relating maps to `ECL` ids and
finding arrival squares needs the `ECL` decode, which `docs/120` prices at
weeks and which nothing else in the project depends on.

**Silver Blades' table is built** -- `#20 (Build an area table for Silver
Blades)`, and §8 below has what it says and the four Pool of Radiance rules it
breaks. The name column is still blank. Curse's twenty-three scripts read the
same way with the same tool and nobody has tabled them.

## 3. Where the title comes from, and what happens with no game running

**There is always a title.** `WishWindow.map.state.title` is never None: it
falls back through the open save, the disks folder, and `games.DEFAULT`. It is
also sticky — pointing the disks preference at a folder with no recognisable
images leaves the last title in place rather than clearing it.

So the answer to "what does the dialog do with no game running" is: **the same
thing the map already does**, which is show the title the automapper is
labelling with. No second rule, no "all titles" mode, no disabled tab. The
automapper is not driving a game most of the time it is open — it draws maps
off the disks folder with nothing attached — so "no game running" is the normal
case, not an edge one, and it already has an answer.

Two consequences worth writing down:

* The running game is **checked against memory** now, and a machine that
  disagrees takes the per-title controls off -- `#21 (The running game is
  guessed from a preference, so both title safeguards can fail open)`. Not
  *identified* --
  validated. The observable is the one the automapper already had: the game
  leaves the `GEO` it is drawing at `$0400`, and `ResidentGeo.verdict` asks
  only "is this one of the maps we hold?" Three answers, and only the middle
  one does anything: `OURS`, `NOT_OURS` — a Gold Box map that is none of ours —
  and `UNKNOWN`, which is a page that is not a map at all and is the ordinary
  state at the title screen, mid-load and in combat.

  Asking *which* title it is would need every title's disks and would fail
  **open** on the titles whose disks are nowhere, which for most players is
  most of them. Asking whether it is ours needs only the disks we already have
  and fails **closed**. GRADE: CONFIRMED, and it needed no new address —
  `$0400` was already trusted and already read every tenth poll.
* The dropdown must use the **automapper's** title, never a selector's. If the
  Preferences selector lets a player look at Curse's list while the automapper
  is on Pool of Radiance, the dropdown still offers Pool of Radiance. Anything
  else fasttravels a party with another game's ids.

## 4. The dialog: a selector, not a tab bar

**Recommended: one table, with a game selector above it, and the selector only
appears when a second title has an area table.** Reasons, in order of weight:

1. **Tabs inside tabs.** Preferences already has `General` and `Fast travel` across
   the top (`docs/130` §14, and that tab bar exists because Donald asked for
   it). A second bar inside the second tab is two levels of the same control
   doing two different jobs, and the inner one wraps or scrolls on the display
   sizes that made §14 necessary in the first place.
2. **Six titles, not four.** `goldbox/games.py` already knows six, three of which
   (Champions, Death Knights, Gateway) are as C64-real as Silver Blades. A
   selector costs one row whatever the count; a tab bar is sized by it.
3. **Only one list is ever actionable.** The tab bar's implicit promise is that
   the tabs are peers you switch between. They are not: exactly one of them
   drives the dropdown, and it is chosen by the automapper, not by the player's
   click. A selector that *defaults to the automapper's title* says that
   correctly; a tab bar invites the player to think clicking a tab changes
   something.
4. **Three tabs, two empty, is a broken-looking feature.** With a selector the
   empty case is one sentence in the body — *"No areas are known for Curse of
   the Azure Bonds yet."* — under a control that is obviously showing you
   something else.

Rejected: **one table with a game column**. Sixty-odd rows across titles, of
which the player can only usefully act on one title's, and the sort order stops
being "by name" — which is the order `docs/130` chose deliberately.

**Do the table last.** With one title's data the current dialog is already
correct: one table, the running title's areas. The selector is an addition, not
a rewrite, and it should land in the same change as the second area table so
that it never ships with one entry in it.

## 5. The storage shape, and the migration

`Settings.fast_travel_targets` is `list[int] | None` — area ids, and an id
means nothing without a title. It has to become:

```
fast_travel_targets: dict[str, list[int]] | None
```

keyed by **`Game.key`** (`"pool-of-radiance"`, `"curse-of-the-azure-bonds"`),
not by `Game.title`. `games.py` already calls `key` "stable identifier, written
into the YAML"; a title is display text and is the wrong thing to put in a file
a player hand-edits.

The three `None` rules survive per title, one level down:

| state | means | gets |
|---|---|---|
| field is `None` | nobody has ticked anything, ever | Pool of Radiance's three; every other title, nothing |
| key absent from the dict | never chosen **for that title** | that title's default, which is `()` for all but Pool of Radiance |
| key present, `[]` | unticked everything for that title | `[]`, kept |
| anything else | a hand-edited mess | read as "not chosen", exactly as now |

`DEFAULT_FAST_TRAVEL_TARGETS = (0, 20, 21)` is a Pool of Radiance fact and
should say so — it belongs beside the per-title table it defaults, keyed the
same way.

**The migration is not `RENAMED`.** `RENAMED` maps an old *key* to a new one;
this is a change of *value shape* under the same key, and `Settings.load` needs
one extra step:

* a `list` under `fast_travel_targets` is Pool of Radiance's, because Pool of
  Radiance is the only title that ever had one → `{"pool-of-radiance": [...]}`;
* `fasttravel_areas` still feeds in through `RENAMED` first, so a config from before
  2026-08 migrates twice in one read and comes out right;
* the file is written in the new shape only, so the migration finishes rather
  than living in the file forever — the same rule `RENAMED`'s comment sets.

Donald's own config has ticks in it and takes this path. GRADE: CONFIRMED that
it works, once written — `Settings.load` already filters unknown keys and
already treats a malformed value as "not chosen", so an older build reading a
new file sees a dict where it wants a list, falls into `chosen_areas`'s
`isinstance` guard, and offers its own three. Ticks lost on a downgrade,
nothing crashes. That is the same one-way cost `RENAMED` already accepted.

`chosen_areas()` / `set_chosen_areas()` grow a game-key parameter. Three
callers: `FastTravelBar.chosen_rows`, `PreferencesDialog._travel_tab`, and
`WishWindow.set_fast_travel_targets`.

## 6. Does the fasttravel mechanism transfer?

**Yes.** This section used to say the overlay half was UNKNOWN and that one
emulator session would settle it. That session happened —
`#19 (Can Curse be fast-travelled at all, or is the mechanism Pool of
Radiance's alone?)` — so the UNKNOWN row is gone rather than annotated, and
the answer is below.

`docs/117` established that **the `ECL` bytecode is one artefact across
*ports*** — DOS, C64, Amiga of the same title. That is not the claim this
needed, and the claim it needed is now measured directly across *titles*.

**`NEWECL` is the same routine in all three C64 titles.** Curse's handler is
`DUNGEON $21BA` and Silver Blades' is `$20E6`, against Pool of Radiance's
`$2011`; disassembled, Curse's is instruction for instruction identical bar
three relocations, and Silver Blades' differs by one added store. Nothing was
found by name or by an offset carried over — `tools/newecl.py` locates the
script VM by its **self-modifying dispatch**, a `JSR` whose own operand bytes
two `STA`s elsewhere write, and takes entry `$20` of the tables it builds.
Every one of Pool of Radiance's documented addresses comes back out of that
procedure exactly, including the two windows that were measured from 400 PC
samples in the running machine.

| what | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| live party triple | `$C04B`–`$C04D` | same, **unrelocated** | same, unrelocated |
| came-from | `$49F2` | `$4BF2` | `$4BF2` |
| 32-byte scratch wipe | `$4A00` | `$4C00` | `$4C00`, **and `$4BFB`** |
| cache slot | `$6E1B` | `$7F1B` | `$7F1B` |
| mode flag / disk | `$6E11` / `$6E12` | `$7F11` / `$7F12` | `$7F11` / `$7F12` |
| indoors flag | `$49E6` | `$4BE6` | `$4BE6` |
| `NEWECL` handler | `$2011` | `$21BA` | `$20E6` |
| **tail, where a fast travel enters** | `$2034` | `$21DD` | `$210C` |
| key-wait window | `$10C2`–`$10EC` | `$101D`–`$1056` | `$1050`–`$1089` |
| key fetcher | `LIBRARY $2E4E`–`$2E6B` | `LIBRARY $2FD7`–`$2FF8` | `LIBRARY $4101`–`$4123` |
| opcodes in the VM | 62 | 65 | 66 |

The payload-relative row is no longer a prediction: `$49F2`→`$4BF2` and
`$4A00`→`$4C00` are the operands `NEWECL` itself uses, which is the +`$0200`
`save_load_address` predicted. **GRADE: CONFIRMED**, from the bytecode.

**And a Curse party was fast-travelled, four times.** Areas `$03`, `$04` and
`$10` from area `$01`, on a pooled VICE instance: the map at `$0400` matched
the target `GEO` byte for byte off the disk each time, the arriving script's
own text appeared, and the party then turned and walked one key at a time.
One of the trips crossed a disk, so `$7F12` is the disk byte end to end and
Curse's numbering is 1-based over its six sides. **GRADE: CONFIRMED**, in the
running machine. `tools/cursewarp.py` is the driver.

Two differences that are not relocations, and neither can be assumed away:

* **Silver Blades' `NEWECL` zeroes `$4BFB` as well as the 32 bytes.** Six
  writes, not five. What that byte holds is unread.
* **Curse's key-wait loop has a block Pool of Radiance has nothing at**,
  `$102E`–`$103A`, gated on the indoors flag and calling `GDRIVE00 $C003`. So
  the claim that warping out of the travel grid wedges the loader — Pool of
  Radiance's, and unrecoverable — must be tested in Curse rather than carried
  across. `tools/cursewarp.py` refuses it without `--force`.

The disk column of a Curse area table is still a separate measurement, but a
smaller one than this section used to say: the number is the side that carries
that area's `ECL`, and four of the sixteen are now measured by warping to them
and seeing which map loaded.

## 7. Ordered tasks, smallest first

| # | task | unblocked by |
|---|---|---|
| 1 | **Done.** **Say the dropdown is Pool of Radiance's.** When `AutomapState.title` is not Pool of Radiance, the Fast Travel row offers nothing and says why — *"No areas are known for Curse of the Azure Bonds."* — with the button disabled, the way `NOTHING_TICKED` already does. It must never fall back to Pool of Radiance's ids | nothing. This is the only change that is a **correctness** fix rather than a feature: today a Curse session gets Pool of Radiance's areas, and fasttraveling on them writes Pool of Radiance disk numbers and `ECL` ids into a Curse machine |
| 2 | **Done.** **Key the setting by game.** `fast_travel_targets` becomes `{game key: [ids]}`, with the list-to-dict migration in `Settings.load` and the per-title default table. No visible change | nothing. Do it before any second table exists, so no config is ever written in a shape that has to be migrated twice |
| 3 | **Label the tick table with the title**, and build its rows from a per-title area table looked up by key — a table that has one entry today. Still one table, still no selector | task 2 |
| 4 | **Done.** **Measure whether Curse can fasttravel at all.** Answered yes, both ways: `NEWECL` read off Curse's own `DUNGEON`, and four driven warps. §6 | — |
| 5 | **Done, bar the measurement.** **Build Silver Blades' area table.** `goldbox.areas.AREAS_SILVER_BLADES`, twenty-two rows, every one PROBABLE. §8. What is left is a driven warp to make a row CONFIRMED, and the names | task 3 for somewhere to put it. Task 4 no longer gates it: §6 has Silver Blades' handler and tail as well |
| 6 | **Name Curse's sixteen maps.** Needs somebody who has played it, or the `ECL` decode. This is the item with no engineering answer | a human |
| 7 | **The game selector in Preferences.** One row above the table, defaulting to the automapper's title, with the empty-title sentence in the body | a second real table — task 5 |
| 8 | **Done.** **Check the running game against memory**, so attaching to a title the disks folder does not name stops being a silent mislabel | nothing depends on it; it is what makes every one of the above fail closed rather than open |

**Task 8 is done** -- `#21 (The running game is guessed from a preference, so
both title safeguards can fail open)` -- as validation rather than
identification.
`Automapper._check_resident` reads the block at `$0400` it was already reading
and asks `ResidentGeo.verdict` whether it is one of the believed title's own
maps. A Gold Box map that is none of them means the disks the window is set up
for are not the game that is running, and then: the Level up button goes, the
Fast Travel row and every live-action button lose the emulator, the mapper
records nothing, and the Messages panel says *"ERROR: Wrong game disk loaded.
Disabling functionality to protect from corruption."* It names neither game
because it cannot — the check validates one title, it does not identify the
other — so which title was believed goes to the debug log instead.

Two contradictions in a row are needed before anything comes off, and only a
positive match on one of our own maps lifts it. "Cannot tell" never lifts it
and never causes it.

**What makes 1024 bytes a map** is three measured clauses in
`automap/area.py`: barrier reciprocity ≥ 0.93, at least 20 shared edges walled
from both sides, and at least half of those agreeing about which wall it is.
Measured against every 1024-byte page of every non-`GEO` file on the Pool of
Radiance and Curse disks — 19130 blocks at 64-byte steps — it admits **none**,
and it admits 32 of the 38 real maps. The six it turns away read as `UNKNOWN`,
which refuses nothing. `tests/test_wronggame.py` re-measures both directions
off the player's own disks.

**And a map may drift from its disk copy by up to `NEAR_ENOUGH` = 128 bytes**
and still be that map, because the running game is allowed to write into the
block it is drawing and an exact test would then disable the controls in front
of a player who has done nothing wrong. The two closest *distinct* maps in the
two titles differ in 379 of 1024 bytes, so there is a factor of three between
the tolerance and any chance of confusing one map with another.

**Tasks 1 and 2 are done** -- `#14 (Fast Travel offers Pool of Radiance's
areas in a Curse session)`. `goldbox.areas.areas_for_title` is the refusal:
it hands back `AREAS` for Pool of Radiance and `()` for every other title, and
`FastTravelBar`, `automap.actions.area_rows` and the Preferences table all go through
it. `Settings.fast_travel_targets` is `{game key: [ids]}`, with the bare-list
migration in `Settings.load` and `DEFAULT_FAST_TRAVEL_BY_GAME` holding the
per-title default -- Pool of Radiance's three, and nothing for the other five.
The title is the **automapper's**, not the open save's: `WishWindow.map_game`,
because the map always has one and a save need not be open.

Pools of Darkness appears nowhere in this list. It has no C64 release, so there
is nothing for a C64 automapper to attach to; the Pools of Darkness work in
this project is `docs/124`, which is about carrying a party into the **Amiga**
version.

## 8. Silver Blades' table, and the four rules it breaks

Built for `#20 (Build an area table for Silver Blades)` by `tools/areatable.py`,
which reads any title's `ECL` scripts through the opcode tables it takes out of
that title's own `DUNGEON`. Pool of Radiance is the control: the same tool
reproduces `AREAS`' map column, its disk column and fourteen of its sixteen
arrival squares, and reaches the 98.04% of script bytes `tools/eclwalk.py`
already reached.

**Twenty-two areas on six sides**: `$04`, `$10`-`$11`, `$20`-`$22`,
`$30`-`$34`, `$40`-`$42`, `$44`, `$50`-`$52`, `$60`-`$63`. `ECL64` and `ECL65`
are on all six sides and are not areas -- their first four bytes do not decode
as the opening `GOTO` every script has. **Scripts run at `$8000`**, against
Pool of Radiance's `$9900`, derived from the scripts themselves rather than
assumed: one page boundary puts all five entry targets inside every script.

Four things do not carry over, and each would put wrong data in the table:

| | Pool of Radiance | Silver Blades |
|---|---|---|
| an area's map | `LOADFILES`' first operand is the script's own id, 29 of 29 | false in five of twenty-two: `ECL04`→`GEO10`, `ECL30`→`GEO31`, `ECL33`→`GEO31`, `ECL34`→`GEO32`, `ECL63`→`GEO62` |
| a mapless area | 3 areas issue no `LOADFILES` and show no map | `ECL31` and `ECL32` issue none and still show one: `ECL30` loads `GEO30` for them on the way in |
| where an arrival square comes from | mostly the **departing** script, before its `NEWECL` | all twelve from the **arriving** script's own entry 4; exactly one `NEWECL` in the title writes a square, and it contradicts the arriving script |
| whether a square is a constant | it is | often computed: `ECL21` fetches it through `GETTABLE`, `ECL34` and `ECL51` branch on the came-from area `$4BF2`, `ECL34` adds 3 to whatever `$C04B` holds |

And one that is not a rule but a shape nothing else in the project has:
**`ECL30` is a twelve-option menu serving four areas**, and it records which
option was chosen in `[$4C69]`, which `ECL31`'s entry 4 reads back. A fast
travel into `$31` or `$32` that does not set `[$4C69]` arrives on a level
nobody chose.

### The sixth write, and the byte that hides the coordinates

Silver Blades' `NEWECL` zeroes `$4BFB` as well as the 32 scratch bytes, where
Pool of Radiance's and Curse's do not -- `#19 (Can Curse be fast-travelled at
all, or is the mechanism Pool of Radiance's alone?)`. Measured, that matters in
**four areas of twenty-two**: eighteen scripts set the byte again in their own
entry 4, exactly once each, with a constant -- eleven write 1 and seven write
0 -- and `ECL11`, `ECL44`, `ECL61` and `ECL62` never touch it.

**`$4BFB` is the flag that suppresses the party's coordinates on the status
line.** `DUNGEON $0A0E` is `LDA $4BFB / BNE` over the block that loads the
square for printing, and `$09C0` is `LDA #$FF / LDX $4BFB / BEQ / AND #$F7`,
dropping one bit of the command mask. Pool of Radiance has both routines at
`$09B5` and `$0A0E` on `$49FB`; Curse has them at `$09B0` and `$0A05` on
`$4BFB`. That settles what `#19 (Can Curse be fast-travelled at all, or is the
mechanism Pool of Radiance's alone?)` recorded and could not explain -- Curse's
area `$03` drew `E 3:44` with no coordinates where area `$01` drew
`N 3:41 4,4`: Curse's `ECL03` entry 4 writes `SAVE 1, [$4BFB]` and `ECL01`
never touches the byte. CONFIRMED, from the routine's instructions and a
reading taken in the running machine.

So **a driver must read `$C04B`-`$C04D` and never the status line** in the
eleven Silver Blades areas that set the flag. `tools/ssbwarp.py` does.

### And clearing it is the one behavioural change between the two engines

Propagated over each title's own area graph, with each script's entry-4 write
as the transfer function:

| | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| `NEWECL` zeroes the byte | no | no | **yes** |
| areas reachable from the start | 25 | 22 | 21 |
| **areas whose flag depends on the route taken** | 0 | **11** | **0** |

**Eleven Curse areas can be entered with the flag either set or clear** --
`$02`, `$10`, `$11`, `$12`, `$20`, `$23`, `$40`, `$42`, `$43`, `$50`, `$51`,
none of which writes the byte itself. So the coordinates on Curse's status
line come and go by route: leave the Tilverton sewers (`ECL03`, which sets the
flag) into area `$02` and it draws none; arrive in `$02` from area `$01` and it
does. **Silver Blades has none of that, because its `NEWECL` clears the byte**
-- which is what the sixth write is for.

GRADE for the Curse row: **CONFIRMED from the bytecode**, `DUNGEON $0A0E` and
the eight scripts' own `SAVE` statements, and consistent with the two screens
`#19 (Can Curse be fast-travelled at all, or is the mechanism Pool of
Radiance's alone?)` measured. Not yet reproduced by walking a party into area
`$02` from both directions, which is the experiment that would settle it in the
running game, and it is worth an entry in `goldbox-bugs.md` when somebody has.

**The Pool of Radiance column is a lower bound rather than a proof.** Nine of
its scripts write `$49FB` outside entry 4 -- `ECL02`, `ECL0A`, `ECL12`,
`ECL14`, `ECL15` and `ECL1D` write both 0 and 1, `ECL19`, `ECL1A` and `ECL1B`
write 0 and 255 -- and the propagation reads only the entry-4 write. Curse and
Silver Blades have no such script, so their two columns are exact.

### Why `areas_for_title` still answers nothing for the title

The rows exist and Fast Travel is offered none of them, deliberately.
`automap/actions.py` writes `$6E12`, `$6E1B`, `$49F2`, the wipe at `$4A00` and
the tail `$2034`, and every one of those is a different number in Silver
Blades -- §6 has them. Offering the rows before those move would fast-travel a
party by writing into whatever Silver Blades keeps at Pool of Radiance's
addresses. `goldbox.areas.areas_for` is the accessor for anything that only
reads; `areas_for_title` stays the gate, and task 3 above is what opens it.
