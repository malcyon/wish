# Fast travel for more than one game — plan

Donald: *"I think the Fast Travel options in the automapper are Pool of
Radiance specific, aren't they? … It may need a new tab bar for each game we
support."*

They are. But the dialog is the last problem, not the first.

## 0. The four answers, up front

| question | answer | grade |
|---|---|---|
| Is the area table per-title? | **No.** `por/areas.py:AREAS` is thirty Pool of Radiance `ECL` scripts with `POOL`-disk numbers in them. What P10/P24 made per-title was `GEO_NAMES` — map file → name — and nothing else | CONFIRMED, read |
| What do we have for Curse and Silver Blades? | Decoded `GEO` files and nothing else. No area ids, no names, no disks, no arrival squares, no `ECL` decode | CONFIRMED |
| What do we have for Pools of Darkness? | **The C64 never got it.** `docs/124` §1: the four-game run ends on the Amiga precisely because of this, and `por/games.py` has six titles and PoD is not one of them | CONFIRMED |
| Does the warp mechanism transfer? | The five writes are three different kinds of address and they grade differently. §5 | mixed |

So the honest shape of the feature today is **one title with a list and two
with an empty one**, and the work that matters is building the tables, not
building the tab bar.

## 1. What is already per-title, exactly

`por/games.py` carries six frozen `Game` descriptors — Pool of Radiance, Curse,
Silver Blades, Champions of Krynn, Death Knights of Krynn, Gateway to the
Savage Frontier — with save geometry, race and class tables, item-name load
address and disk glob. Nothing in it touches areas.

`por/areas.py` splits in two:

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
| `ECL` ids and area→map relation | fully decoded | **not decoded** | **not decoded** | — |
| which disk carries which script | yes, `Area.disk` | no | derivable from the id's high nibble (`docs/121`, "a new regularity") | — |
| arrival squares | 16 harvested, `landing_square` for the rest | none | none | — |
| live automapper run | shipping | done, `docs/120` tier 4 | done, `docs/121` phase 5 | — |

Sources: `docs/120-curse-testing.md` §§2, 4; `docs/121-silver-blades.md` §§1,
5; `docs/124-amiga-port.md` §1.

**There is no table to tick for Curse or Silver Blades.** Naming Curse's
sixteen maps needs somebody who has played it; relating maps to `ECL` ids and
finding arrival squares needs the `ECL` decode, which `docs/120` prices at
weeks and which nothing else in the project depends on.

Silver Blades is the cheaper of the two: the id's high nibble gives the disk
side for free, so its table can be built with the map column and the disk
column filled and the name column blank, which is already enough for a
dropdown that says `GEO32` and warps.

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
  disagrees takes the per-title controls off (#21). Not *identified* —
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
  else warps a party with another game's ids.

## 4. The dialog: a selector, not a tab bar

**Recommended: one table, with a game selector above it, and the selector only
appears when a second title has an area table.** Reasons, in order of weight:

1. **Tabs inside tabs.** Preferences already has `General` and `Fast travel` across
   the top (`docs/130` §14, and that tab bar exists because Donald asked for
   it). A second bar inside the second tab is two levels of the same control
   doing two different jobs, and the inner one wraps or scrolls on the display
   sizes that made §14 necessary in the first place.
2. **Six titles, not four.** `por/games.py` already knows six, three of which
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
* `warp_areas` still feeds in through `RENAMED` first, so a config from before
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
callers: `WarpBar.chosen_rows`, `PreferencesDialog._travel_tab`, and
`WishWindow.set_fast_travel_targets`.

## 6. Does the warp mechanism transfer?

`docs/117` established that **the `ECL` bytecode is one artefact across
*ports*** — DOS, C64, Amiga of the same title. That is not the claim needed
here. Across *titles*, the five writes fall into three classes:

| what | Pool of Radiance | other titles | grade |
|---|---|---|---|
| the live party triple `$C04B`–`$C04D` | measured | **measured in Curse and in Silver Blades, unchanged** (`docs/120` §4, `docs/121` §5) | CONFIRMED for three titles |
| payload-relative bytes — `$49F2` came-from (payload `+$0F2`), `$4A00` scratch (`+$100`) | measured | should move with `Game.save_load_address`: `$4900` → `$4B00` for Curse and Silver Blades, so `$4BF2` and `$4C00`. The one payload address actually re-measured, the area byte, did exactly this: `$4BC2` → `$4DC2` | PROBABLE |
| loader and overlay addresses — `$6E11` resident-overlay flag, `$6E12` disk, `$6E1B` cache slot, the `NEWECL` tail `$2034`, the key-wait window `$10C2`–`$10EC`, `$2E4E`–`$2E6B` | measured | the **loader's page is now read**: `LINKER` in Curse and Silver Blades is resident at `$2D00` and dispatches on `$7F11`, with the disk byte at `$7F12` and the cache from `$7F13` — the same `+1`/`+2` layout Pool of Radiance has at `$6E11`–`$6E13` (#29). The rest are `DUNGEON`'s and `LIBRARY`'s own code and remain **UNKNOWN** | CONFIRMED for the flag in both; UNKNOWN for the rest |
| the opcode: `$20` is `NEWECL` | CONFIRMED | Curse's DOS opcode table has `20 1 NEWECL`, and Pools of Darkness's independently produced listing agrees on fourteen opcodes (`work/reports/forum-sweep-2.md` §1) | PROBABLE for Curse, and it is the *opcode*, not the handler's address |

**The first experiment is therefore not a UI question.** Half of it is now
answered: Curse's resident-overlay flag is `$7F11` and its disk byte `$7F12`,
read out of `LINKER`'s own first six bytes (#29). What is still open is whether
there is a `NEWECL` handler whose tail can be entered, and where the key-wait
loop is. One emulator session with the disassembler answers whether fast travel
is possible for Curse at all.
Until it does, a Curse tab is an empty tab whatever the data says.

Also note that `Warp` writes the `POOL` disk number to `$6E12`, and *Curse's
disks are not numbered like Pool of Radiance's.* Even with the addresses, the
disk column of a Curse area table is a separate measurement.

## 7. Ordered tasks, smallest first

| # | task | unblocked by |
|---|---|---|
| 1 | **Done.** **Say the dropdown is Pool of Radiance's.** When `AutomapState.title` is not Pool of Radiance, the Fast Travel row offers nothing and says why — *"No areas are known for Curse of the Azure Bonds."* — with the button disabled, the way `NOTHING_TICKED` already does. It must never fall back to Pool of Radiance's ids | nothing. This is the only change that is a **correctness** fix rather than a feature: today a Curse session gets Pool of Radiance's areas, and warping on them writes Pool of Radiance disk numbers and `ECL` ids into a Curse machine |
| 2 | **Done.** **Key the setting by game.** `fast_travel_targets` becomes `{game key: [ids]}`, with the list-to-dict migration in `Settings.load` and the per-title default table. No visible change | nothing. Do it before any second table exists, so no config is ever written in a shape that has to be migrated twice |
| 3 | **Label the tick table with the title**, and build its rows from a per-title area table looked up by key — a table that has one entry today. Still one table, still no selector | task 2 |
| 4 | **Measure whether Curse can warp at all.** The flag is done — `$7F11`, #29. What is left in that session: a `NEWECL` handler and its tail, the key-wait window, and whether the payload-relative writes land where §6 predicts | an emulator slot, and a Curse disk set — both present |
| 5 | **Build Silver Blades' area table.** The cheap one: 17 maps, disk side free from the id's high nibble, names blank. Enough for a dropdown that says `GEO32` | task 3 for somewhere to put it; task 4's answer for whether it can be acted on |
| 6 | **Name Curse's sixteen maps.** Needs somebody who has played it, or the `ECL` decode. This is the item with no engineering answer | a human |
| 7 | **The game selector in Preferences.** One row above the table, defaulting to the automapper's title, with the empty-title sentence in the body | a second real table — task 5 |
| 8 | **Done.** **Check the running game against memory**, so attaching to a title the disks folder does not name stops being a silent mislabel | nothing depends on it; it is what makes every one of the above fail closed rather than open |

**Task 8 is done** (#21), as validation rather than identification.
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

**Tasks 1 and 2 are done** (#14). `por.areas.areas_for_title` is the refusal:
it hands back `AREAS` for Pool of Radiance and `()` for every other title, and
`WarpBar`, `automap.actions.area_rows` and the Preferences table all go through
it. `Settings.fast_travel_targets` is `{game key: [ids]}`, with the bare-list
migration in `Settings.load` and `DEFAULT_FAST_TRAVEL_BY_GAME` holding the
per-title default -- Pool of Radiance's three, and nothing for the other five.
The title is the **automapper's**, not the open save's: `WishWindow.map_game`,
because the map always has one and a save need not be open.

Pools of Darkness appears nowhere in this list. It has no C64 release, so there
is nothing for a C64 automapper to attach to; the Pools of Darkness work in
this project is `docs/124`, which is about carrying a party into the **Amiga**
version.
