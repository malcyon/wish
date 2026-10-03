# Destination-game acceptance runs for the conversion tickets

A conversion ticket closes only when a save that used to fail converts on the
reviewed, pushed SHA with CI green, loads in the destination game, and the
state the ticket is about is read back out of that game with the player's
behaviour preserved. Nine open tickets have pushed code and no such run. This
page is the plan for those runs: the three drivers they share (three
platforms, eleven title routes), what each platform can already read, the
foundation run that comes before any ticket's boot, who builds what, and how
the evidence is kept. Each ticket's runs are named once here and by that name
afterwards.

| run name | ticket |
|---|---|
| the Bless runs | #661 (A C64 party under a running spell loses it on the way to DOS or the Amiga with no line anywhere, because the C64 reader reads only the paladin's rows out of the effect arrays) |
| the Detect Magic runs | #666 (A C64 party under a camp Prayer loses it on the way to DOS or the Amiga, because nothing converts the save's party-wide effect rows) and #668 (A DOS Pool of Radiance party under Detect Magic reaches the C64 with a row the game never reads, because the converted row belongs to one character and the C64 asks only for a party-wide one) |
| the Prayer runs | #667 (A DOS party under Prayer, the strength and charisma spells, Mirror Image or an effect with no C64 spell row is still refused when saved as a C64 save, because only the ordinary caster-level spells convert) |
| the cure-disease runs | #649 (Converting a dual-classed DOS Curse of the Azure Bonds character to C64 loses his leftover paladin cure-disease use) |
| the joined-scroll runs | #432 (A joined scroll in a DOS Silver Blades save shifts everything after it out of the character's pack) |
| the opening-scene runs | #653 (Converting an Amiga Curse or Silver Blades party that has not yet set out to the C64 or DOS lands it already adventuring, so the opening experience award never happens) |
| the trait-slot runs | #621 (A C64 character carrying an effect in a trait slot cannot be saved as a DOS or Amiga save, because the writer keeps only the eight ids the game's own importer keeps) |
| the Save As matrix | #511 (Open a DOS save folder and an Amiga save disk in the Character Editor, so editing a DOS character does not mean two conversions) |

## 1. What one acceptance run consists of

Every run below has the same five parts, and a finding that lacks one is not
acceptance evidence.

1. **The source.** The save the ticket names, or a copy of one with the
   ticket's state staged into it before the boot. Staging is an input, so it
   is written before the emulator starts and never after the load
   (`.claude/rules/testing.md`, "Poke a field before the boot"). A stage is
   named in bytes in the run's log.
2. **The conversion, through the editor's own route at the SHA under test.**
   `editor.saveplan.prepare_save_as` and `publish` (Save As), which
   `tools/convert/saveasdrive.py` calls for the developer tools:
   `tools/convert/convertrun.py` (`--no-play` writes the conversion and stops
   before the emulator) and `acceptance.py --fixture-row` both go through
   it. File > Convert exists only behind `WISH_EXPERIMENTAL_POD_CONVERT` and is
   the route of the Pools of Darkness Amiga-to-DOS conversion alone
   (`acceptance.py --amiga-slot`). The output bytes, the SHA, and the
   conversion's `dropped` and `losses` lists (both empty) go in the log. A run
   made from output that was not produced this way tests the writer, not the
   program.
3. **The load, in the destination game, on a pooled slot, headless and
   silent.** One boot per run. A second boot that ends at the same step is
   the end of the run (`.claude/agents/emulator-runner.md`).
4. **The reading**, by whichever of three readers the platform has (section
   2): the engine's own save written back and decoded, memory read while the
   game runs, or the screen. Each ticket's row in section 4 says which
   reading accepts and which refutes, before the run starts.
5. **The evidence**, kept under `~/.cache/wish/acceptance/<issue>/<sha>-<run>/`
   and never committed: `run.jsonl`, `summary.json`, every screenshot, and
   the engine's own resave. An engine-written save that later tests will need
   goes into `$WISH_SPECIMENS` through `tools/registry/specimens.py add`
   before the slot is torn down. `/mnt/disks/cited` is read-only from the
   agent VM, so nothing goes there.

The comment that closes the ticket names the SHA, the CI run id, the command
line, the evidence path and the reading. After acceptance and exact-SHA CI,
use an explained project-scoped Plane update to Completed and verify its state UUID
with `planeread --json` and live metadata. This replaces the earlier GitHub
closure command because Donald made Plane the default register. A disabled
update is reported as an unavailable transition; the ticket remains unfinished.

## 2. What each platform can read today

| platform | emulator and pool | keys | screen | memory | files the engine writes | title protocols in the tree |
|---|---|---|---|---|---|---|
| C64 | VICE through `tools/registry/instance.py` (`claim`, displays `:10`-`:25`) | `Session.select_bar`, `select_row`, KERNAL buffer | **text**, `Session.screen_text()` and `screen()` row by row | binary monitor: peeks, non-stopping exec checkpoints (`Monitor.checkpoint_hits` in `automap/vice.py`), watchpoints (`livewatch.py`) | the save disk, copied out closed (`por.copy_closed_disk`) or repaired (`curseload.close_splat`) | Pool `Session` (load, walk, fight, `save_game`); Curse `curserun.CurseSession` + `curseload`, `cursecheck.py`, `laterbattle.py`; Silver Blades `ssbsession.SSBSession`, `ssbresavewalk.py`, `laterbattle.py`; all three run under `tools/c64/acceptance.py` |
| DOS | DOSBox 0.74 through `tools/dos/dosbox.py` (`claim`, displays `:50`-`:65`) | `xdotool` keysyms | **pixels only**: 320x200 PNG, `Screen.digest`/`ink`/`glyphs` for equality, `highlight_row`; no text; the status line's `x,y` token, read cell by cell from x 136 (`screens.status_square`) | none | `SAVE/` after `ENCAMP > SAVE`: records, `.ITM`/`.STF`, `.SPC`/`.FX`/`.SFX`, `SAVGAM<slot>.DAT` (Pools of Darkness `SAVGAM<slot>.PTY` with `VAULT<slot>.DAT`) | Pool `PoolOfRadiance` (menu, load, move, camp save, fight); Curse `dossheetread.py` (load, sheets, walk, engine save), `Camp.memorize`, `curseregain.py` (train, camp save); Silver Blades `route_silver_blades.py Route` (party menu, intro) and `ssbimport.py Driver` (encamp, rest by days, camp save, sheet), `dossheetread.py --move-mode`; Pools of Darkness `dospod.py` (its journal answer and party-menu knowledge); all four run under `tools/dos/acceptance.py` |
| DOS, debugger | DOSBox-X debug build through `tools/dos/dosboxx.py` (`claim`, displays `:90`-`:105`); `dosboxx.unavailable()` is `None` on this machine | the same | the same, halved from 640x400 | `read`/`write` any linear address, `watch` (one byte, on change), `brk` (fires silently, `wait_halt` probes), `regs` through `EV`; `dosspcexpiry.read_party` reads Pool's effect chains node by node off the heap | the same | `PoolOfRadiance` runs unchanged on `XSession`; the later titles' chain heads (Curse record `0x0F2`, Silver Blades `0x0FB`) are read but no tool reads their nodes yet |
| Amiga | WinUAE in the Windows VM, one lane (`winuae.ps1 claim -Holder`), reachable from this VM (`winvm status`) | `tools/amiga/amigadrive.py keys`; the foundation drivers press a key once the previous screen has matched its guard, and `winvmsettle.py` waits between keys by hand | **pixels**: `winvm shot` cropped to the emulator window by `amigashots.py`; a state is one static pixel box (`PixelGuards`) and a sheet's or menu's identity is a name box | `winuaepipe.py` / `automap.amiga.WinuaePipe`: `m` and `S`-to-file reads while the machine runs; `automap/amiga.py` locates the data hunk and the party | the `.adf`, copied back with `winvm get` and read by `amiga_savegame` (`read_por_slot`, `read_slot`, `pod_read_slot`) | Pool `acceptance.py --title pool` (by hand: `docs/182` §7, twenty keys); Curse `--title curse` (by hand: `docs/203` "Reproducing it"); Silver Blades `acceptance.py accept --title ssb`, its journal answered by `amigabladesjournal.py` under `/usr/bin/python3`; Pools of Darkness `--title darkness` and its reload `--title darkness-reload` (section 5) |
| Amiga, FS-UAE | stock `fs-uae` in a VICE-pool slot (`instance.py claim --game amiga-por`), `tools/amiga/fsuaepor.py serve` | `fsuaepor.py keys` | pixels, `fsuaepor.py shot` | none; the GDB build `installfsuae.py` fetches is not installed here | the staged `.adf` in the run directory, `fsuaepor.py names` | Pool of Radiance and Pools of Darkness only. Under it Pools of Darkness reached the party panel and `ADD CHARACTER > POOLS` (`docs/124` §2.4) and never loaded a saved game, and a disk changes at runtime only through its F12 menu, by hand. Curse stops at the code wheel and Silver Blades has never been driven |

Each Amiga run mounts its own disks, and the game reads its saves from only
some of them:

| title | DF0 | DF1 | DF2 | save letters |
|---|---|---|---|---|
| Pool of Radiance | Disk 1 | Disk 2 | The specimen's `POOLSAVE` disk (`nr_floppies=3`, `floppy2type=0`) | Loaded A; control C; after D; B kept |
| Curse | A working copy of the specimen, a whole disk A with slots A, B and C in `/SAVE` | Disk B | None | Loaded B; control D, saved at the party menu before `BEGIN ADVENTURING`; after F, saved from camp; A and C kept |
| Silver Blades | A copy of disk 1 carrying the prepared slot C (`staging.stage_embedded_boot_disk`) | Disk B, the game's second disk | None | Control B, saved at the party menu before `BEGIN ADVENTURING`; after D, saved from camp; A and C kept |
| Pools of Darkness | Disk 1 | Disk 3, the save disk, mounted from the start | None; disk 2 is staged on the VM as a spare and inserted into DF0 at the game's `INSERT DISK 2` prompt | Loaded B; control F; after G; A, C, D and E kept |

Silver Blades boots from a copy of disk 1 carrying the slot because the game
never reads a standalone save disk (`SECRETSAVE`, or Curse's `AZURESAVE`) while
its own disk A is in DF0, which is the defect of #677 (Save As to the Amiga
puts a Curse or Silver Blades party on a separate save disk that the game never
reads while its own disk A is in DF0). Pools of Darkness has disk 3 in DF1 from the first frame
because the route was written before a runtime floppy insert
(`WinuaePipe.insert_floppy`, which `run_recon` still offers as an `insert`
step) could be told from a refused one: WinUAE's pipe answers `404` to every
`CFG floppy<N> <path>` setter whether it applied or not, so the earlier `404`
receipt proved nothing (`docs/143-winuae-debugger.md` section 4.2). Pool of
Radiance's `POOLSAVE` in DF2 is unchanged.

The first keys are per title. The Silver Blades version screen's `PLAY DEMO
QUIT` bar takes `P`; one `RET` at it was followed by the story intro and the
credits, an attract loop that never holds still, so no route presses `RET`
there, and the credits are left with `ESC`. Curse's cracker intro is left with
`ESC`, the first reaching the copy-protection screen and the second backing
out of it to the party menu, with nothing typed. Pool of Radiance's first
screen takes `RET`. Pools of Darkness gets `P` at its title screen, which the
game leaves for its demo if nobody answers.

Consequences for the plan:

* **DOS has no screen text, so a DOS reading is a file, a status token or a
  memory read, and a screenshot is corroboration.** The file reader is the
  strongest: the engine's own `ENCAMP > SAVE` writes the effect nodes, the item
  chain, the clock and the record, and every one of those has a decoder in
  `goldbox/` or `tools/dos/` (`dos_codec.read_party` and `to_neutral`,
  `ssbimport.effect_nodes`, `dosscrollbundle.walk`, `world_state.from_dos` for
  the clock). The DOSBox-X memory read is needed only where the ticket asks
  what happens *during* play: a handler firing in a fight, a chain ageing
  between two saves. A screenshot of the ITEMS list or Magic > Display is read
  by the agent that took it (the Read tool shows a PNG) and reported as an
  observation, with the PNG kept.
* **The status token judges a step in DOS.** The `x,y` square that opens the
  status line is read from x 136 up to the first blank cell, so the clock and
  the facing letter after it never enter the value; a picture digest cannot
  judge a step, because the clock ticks on a bump and a line drawn for the
  first time differs from a blank one. All four titles start the token at x 136
  (`STATUS_COLUMNS`). Silver Blades and Pools of Darkness walk in a move mode
  (`m` enters it, `e` leaves it in Silver Blades and `Escape` in Pools of
  Darkness); Pool and Curse step at the map bar and have none.
* **The C64 reads everything**, and its gap is coverage by title:
  `acceptance.py` runs `fight` on Pool, Curse and Silver Blades, but `cast`
  and `cure` are Curse's alone.
* **The Amiga's driver of record is WinUAE**, because it runs four titles end
  to end, leaves Curse's code wheel with
  `ESC`, answers Silver Blades' journal question through a private helper, and
  reads memory through the pipe. FS-UAE is a second seat for Pool of Radiance,
  and for Pools of Darkness up to its party panel. Four things no Amiga tool does yet: reach a second party member's sheet
  in Pool of Radiance (`docs/182` §6), open Magic > Display, judge a step while
  the game runs (a move is judged only from the game-written saves, control slot
  against after slot, read from the fetched image), and read the party's square
  through the pipe on a driver's path (`automap.amiga`'s `party_x` layout field
  is used by `amigatarget.py fix` and by no driver). The first two are screen
  sequences to be read before a run needs them.

## 3. The three drivers, as built

Each ticket's check is a source, a boot, a step list and a reading. One driver
per platform takes a Wish-written save and a title and prints what it read;
building four drivers per ticket is how the opening-scene runs spent three
rounds. The three platforms give eleven title routes: four titles under
DOSBox, three under VICE and four under WinUAE. The DOS and C64 drivers take a
step list. The Amiga drivers take a route with pixel guards, because a key
pressed while a disk loads is swallowed with no sign, so each key waits for a
screen the guard map recognises.

### D0. `tools/c64/openingscene.py` answers the Silver Blades treasure bar

The opening-scene runs used to stall at `GO BACK LEAVE TREASURE`, the prompt
the game puts up after `EXIT` at `VIEW TAKE POOL SHARE EXIT`, because
`opening_step` had no case for it. It now reads row 24 holding both `GO BACK`
and `LEAVE TREASURE` as `leave`, and `answer_bar` selects `LEAVE TREASURE`,
with the same unchanged-row-24 fallback the `exit` case has. Leaving the treasure is what `ssbsession.enter_world` also does, and it
forgoes the starting equipment and money a player would take; the run compares
experience, which the treasure does not touch, and both the game's own save and
Wish's get the same treatment.

### D1. `tools/dos/acceptance.py`: load a Wish-written DOS save and read it back

The driver was named `dosacceptance.py` before it moved to `acceptance.py`; the mapping is in [docs/236](236-requirements-for-adding-a-new-platform.md#old-to-new), so older evidence can be found by either name.

One entry point over `tools/dos/dosbox.py` for four titles, Pools of Darkness
included (its journal question and party-menu knowledge are `dospod.py`'s):

    acceptance.py --title curse --save DIR --from-slot B --slot B \
        --steps load 'view 2' begin 'walk MI' camp 'save D' read \
        --issue N --run NAME

It stages the whole save the way `dossheetread.install_whole` does, boots,
and runs the steps in order, writing `run.jsonl`, a PNG per step and
`summary.json`. `--fixture-row` builds the source through Save As DOS instead
of taking `--save`, and `--amiga-slot` does the same for a Pools of Darkness
Amiga slot. There is no `--debug` and no DOSBox-X step. Steps, and the titles
each is built for:

| step | does | titles |
|---|---|---|
| `load` | title menu, `LOAD SAVED GAME`, the slot; Pool lands on the map and the others at the party menu; Pools of Darkness asks `LOAD FROM WHERE? POOLS SECRET EXIT` first and gets `P` | All four |
| `begin` | `BEGIN ADVENTURING` through Silver Blades' intro bars and Pools of Darkness' journal question and `YES NO` bars to the map | Curse, Silver Blades, Pools of Darkness |
| `view N` | At the party menu before `begin`: roster line N's sheet, believed only by its name against the roster line, then back to the party menu; Pools of Darkness also pages `ITEMS` | Curse, Silver Blades, Pools of Darkness |
| `sheet N` | Member N's sheet: from the map in Pool, from camp with the roster line highlighted by `Down` in Pools of Darkness | Pool, Pools of Darkness |
| `items N` | Member N's `ITEMS` list, page by page with `NEXT`, from camp | Pools of Darkness |
| `halve N I`, `join N I` | `ITEMS` row I of member N, `h` or `j` pressed once, the rows counted before and after | Pools of Darkness |
| `walk MI`, `walk I`, `walk 1` | One square, judged by the status token and never by the clock beside it or a picture digest, and by the place decoded from the game-written save. `MI` is two turns and a step at the map bar; `I` is one forward step with no turns; `1` presses `m`, steps turning past a wall, and leaves move mode | `MI` in Pool and Curse; `I` in Pool only; `1` in Silver Blades and Pools of Darkness |
| `turn N` | The control: N right turns (1 to 4), each reading the square, which a turn must leave alone; a run with `turn` and no `walk` fails unless `read` shows the saved place unchanged and prints "did not move" | All four |
| `camp` | `ENCAMP`; records the camp bar | All four |
| `rest 5m`, `rest 1h30m`, `rest 8d` | Camp `REST` for that long; Pools of Darkness' rest menu is read from `GAME.EXE` and is PROBABLE until a run reaches it | All four |
| `display` | Camp `MAGIC > DISPLAY`: every page of the list of spells in effect read as text with the title's own font, returning each member's name and effect names; Pool also requires six member rows | Pool, Curse, Silver Blades |
| `cast N SPELL [T]` | Camp `MAGIC > CAST` for roster line N, which is highlighted with `End` in Pool and Curse and `Down` in Silver Blades; the spell list is read as text, and SPELL is reached by moving the highlight down (`End` in Pool and Curse, `Down` in Silver Blades). A spell memorised twice shows as one row with a count, such as `STRENGTH (2)`, in Curse and Silver Blades. A target, T, is picked with the roster's key and `SELECT` (`Return` in Pool, `s` in Curse and Silver Blades). The cast is believed when the list comes back one SPELL shorter, or, for the caster's only row, when `CAST` opens nothing; any other screen stops the run | Pool, Curse, Silver Blades; Pools of Darkness is refused |
| `train N` | The party menu's `TRAIN CHARACTER` for roster line N | Curse |
| `save X` | Camp `SAVE` to slot X and decline the quit, or `SAVE CURRENT GAME` at the party menu; believed when the file changes | All four |
| `read` | Copies `SAVE/` out and decodes every node, the clock, the place and each character's experience, installed slot against each saved one | All four |
| `shot NAME`, `press KEY` | One PNG, or one key and a PNG; only `press`, `shot` and `read` may come after a `press` | All four |

**Not built:** the DOSBox-X steps `chain`, `break ADDR NAME` and `--debug`, and
`fight`. `docs/149-driving-a-dos-fight.md` is the method for the fight, and
the Prayer runs' DOS runs 1 and 1b wait on `--debug`, `break` and `fight`.

### D2. `tools/c64/acceptance.py`: stage, boot, read the screen and the machine

    acceptance.py --title pool|curse|ssb --save X.D64 \
        --stage-row 63=05:FF:0A:03 --stage-trait 0:9=38 \
        --steps load camp-list 'items 2' 'fight 120' 'save' --out DIR

`fight 120` is long enough for the fight to end, which `save` needs; a short
`fight` before a `save` stops the run at the fight.

Staging writes into a **copy** under the slot's own directory, through
`goldbox.effects.write_effect` on the save payload (the four arrays sit at
the same payload offsets in all three titles, `docs/226`) and
`traitdrive.stage_traits` for the ten trait slots, so a stage is the same
bytes a test stages. The session is the title's own (`Session`,
`CurseSession`, `SSBSession`), the load its own loader
(`Session.load_save`, `curseload.load_saved_game`, `ssbsession.load_party`).

| step | does | titles |
|---|---|---|
| `load` | Boot and load, header logged; arms every `--checkpoint` | Pool, Curse, Silver Blades |
| `camp-list [WHO]` | `ENCAMP > MAGIC > DISPLAY`, the spells each name is affected by, as screen text | Measured in Pool; the later titles carry the same strings |
| `view WHO` | The sheet as text, opened in the order the panel draws the party (the save's marching order; whether a reorder made in the game changes the panel's order is unmeasured); Curse and Silver Blades believe it by the member's name on row 1 | Pool, Curse, Silver Blades |
| `items WHO` | The sheet and the ITEMS list as text with each item's Detect Magic mark | Measured in Pool; Curse and Silver Blades inherit its routine |
| `rest 5m` | `ENCAMP > REST` | Measured in Pool (`route_pool.rest`); Curse and Silver Blades inherit its routine |
| `walk MOVES` | I forward, J left, K right, M turns about and tries the edge behind the original facing -- one square back keeping that facing where it carries no wall art, one square back turned about through an open door, and no move, turned about, against a solid wall; each move judged by the square before and after, which is the status line in Pool and the live triple `$C04B`-`$C04D` in Curse and Silver Blades, whose status line lags a step. A run with a walk fails unless a `save` after it shows the asked result | Pool, Curse, Silver Blades |
| `fight [SECONDS]` | Walk into a fight and fight it for at most SECONDS. A fight still going when they end, or one the party loses, fails the step, because a later step cannot run from either; the checkpoint counts read at that moment are kept as `lost_reading` in `summary.json`. Non-stopping checkpoints are counted after every step | Pool, Curse |
| `cast`, `cure` | `ENCAMP > MAGIC > CAST` and `ENCAMP > VIEW > CURE`, the target's row before and after | Curse |
| `peek ADDR N` | N bytes of memory | All three |
| `save` | The game's own `ENCAMP > SAVE`, the disk copied out closed and decoded, and the place read through `world_state.from_c64` against the staged one (`place_changed`, `facing_changed`) | All three |

The `save` step has two rules in Curse and Silver Blades: a `SAVING GAME` on
row 24 while the driver waits for the `SAVE GAME` bar is the game having chosen
the save, and neither session presses Return for `PROMPT_HOLD` (eight seconds)
after answering a disk prompt, because a Return in the half second after the
prompt chooses the `SAVE GAME` bar.

Pool's `save` has no such progress text to wait on: `Session.save_game` settles
a fixed fourteen seconds for the write, and the game's `SAVING GAME` text has
not been measured for Pool's camp save. The driver then waits for a camp or
world bar, which can come back before the write ends, so the guard is
`copy_closed_disk`, called with `attempts=30, backoff=1.0`: it copies the disk
and fails closed unless every non-empty directory entry is closed. The three
Pool foundation boots each produced a saved disk that this check accepted.

### D3. `tools/amiga/acceptance.py`: WinUAE, from prepared disks to the game's two saves

The design is a route with pixel guards and a manifest. A title is described
once as an `AmigaTitle` (`route.py`): the disks per drive, the keys
and the state each must reach, which steps write a save (a control letter
before the walk and an after letter) and which letters must stay untouched,
the interstitial screens to answer while waiting, and each state's minimum
wait. `run_recon` claims the lane, starts WinUAE with `goldbox-a500.uae` and
the described drives, presses one key, and waits until the guard map's pixel
box for the expected state matches the emulator crop. An unknown screen, a
failed capture or a spent deadline stops the run with a failed verdict. The
route gets `--deadline` less min(300, deadline/2), which is kept for cleanup, and
a lane call cut short by it that then times out is reported as the route time
running out. A state with no guard is settled by two equal captures, listed as `unguarded`, and the
run does not pass. It fetches the disks back, refuses if a registered disk or a
kept slot changed, decodes the control and after slots, and prints one verdict
line for each ("slot C: did not move", "slot D: moved 1 square from area 0
9,13 facing 0 to area 0 9,14 facing 2"). The lane is claimed by the run and
released in `finally`. Before the claim and again before the emulator starts,
the run refuses unless the `winuaemute.ps1` readback passed as `--audio-proof`
is under five minutes old.

| title | driver | what its `prepare` does |
|---|---|---|
| Silver Blades | `acceptance.py prepare\|measure\|accept --title ssb` | Publishes the pinned C64 JOIN party through Save As Amiga, stages DF0 as a copy of disk 1 carrying that slot and DF1 as a copy of disk B, and writes `prepare.json` with every input's SHA-256. `accept` needs `--guards`, `--identity` and `--journal-python /usr/bin/python3`, and its preflight loads the private reader's digit templates before the lane is claimed |
| Pool, Curse, Pools of Darkness | `acceptance.py prepare\|measure\|accept --title pool\|curse\|darkness`, and `reload --title darkness-reload` | Copies the title's registered disks and specimen into a run folder, refusing on any hash difference or a save letter the run writes that already exists (Pools of Darkness has no specimen beforehand: disk 3 is the save disk). `prepare --title darkness-reload` takes `--disk3`, `--disk3-sha256` and `--accept-summary`: the game-written disk 3 an accept run fetched, its SHA-256 and that run's summary; `reload` loads slot G from it, checks the place on screen and writes nothing. `measure --title darkness-unstarted` loads disk 3's own slot A, a party that has not set out, and presses through the journal and the screens after it; it only measures, so `accept` and `reload` refuse it. `accept --preserve-specimen` registers a successful published or substituted run's fetched save disk before the lane is released; a substituted run also takes `--specimen-issue "#N (title)"` |

Use `guardmaps.py add`, `export` and `check` for guard maps. The file `tools/amiga/staging.py` is a DF0 staging helper (`stage_boot_disk` hides
a boot disk's `SAVE` drawer; `stage_embedded_boot_disk` writes a slot into it),
not a driver. Section 4's Amiga steps (`display`, `fight 1`, `items`, `mem`) name
what a run must read; the acceptance command does not yet have them, and each needs its screen
read first (section 7).

## 4. The runs, per ticket

Every row: the source and its staging, the conversion, the driver and steps,
the reading that accepts, the reading that refutes. All conversions are made
at the pushed SHA the closing comment will name. The C64 fixture party is
`tests/fixtures/savedgame0.bin` and `savedgame1.bin` as a disk through
`dos_codec.save_disk`, the way `tests/convert/test_runningeffects.py`'s
`_dos_plan` builds one; the Curse and Silver Blades C64 sources are
`WISH-SPEC-curse-h-engine-resave` and `WISH-SPEC-ssb-d-engine-resave`.

### The Bless runs

| | |
|---|---|
| source | the fixture party with `write_effect(p, 63, 1, 0, $2F, $01)`: Bless on slot 0 with 47 minutes left at clock 0. A two-minute Bless would expire inside the rest and prove nothing |
| conversion | Save As DOS; the `.SPC` holds `01 2F 00 01 00` |
| driver | D1 Pool: `load`, `camp`, `rest 5m`, `save D`, `read` |
| accepts | BRUTUS's node in the resaved `.SPC` is id 1 with 42 minutes (47 less the 5 rested), data `01` |
| refutes | no node, or 47 unchanged (the engine did not age it), or a node the engine rewrote to another form |
| then | Curse and Silver Blades with `Effect(63, 17, 2, $02, $0B)` (Shield) staged into the later-title specimens, the same steps; the Amiga through D3 Pool with `mem` once the chain head is in the table |

### The Detect Magic runs

| | |
|---|---|
| source, C64 to DOS | the fixture party with `write_effect(p, 63, 5, $FF, $0A, $03)`, and the same row staged into the two later-title specimens; the party must hold a magic item, so the control copy of each save is read first with `c64sheet.py` to name one |
| conversion | Save As DOS; one `05 0A 00 03 00` node on the lowest occupied member |
| driver | D1 per title: `load`, `items N` for a member **other** than the one holding the node, `save D`, `read`; then, for the never-expiring case, the same with duration `$00` staged and `rest 8h` before the save |
| accepts | the ITEMS PNG shows the magic item marked for that member (the DOS marker is read off the game's own capture of a DOS-born party under Detect Magic taken in the same run, as the control); the resaved `.SPC` holds the node with minutes reduced by the walk, or `05 00 00 03 00` untouched after the eight hours |
| refutes | the item unmarked for a member who does not hold the node; the permanent record aged or gone |
| source, DOS to C64 | `SAVGAMJ.DAT` of `por-dos-play` with one member's `.SPC` given `05 0A 00 03 00` by `dos_codec` (an input), and the Curse and Silver Blades archive saves the same way |
| conversion | Save As C64; slot 63 = `(5, $FF, $0A, $03)` |
| driver | D2 per title: `load`, `items 2` (a member with a magic item), and the same run on a control copy whose slot 63 is zero |
| accepts | the ITEMS text differs between the two runs exactly where a magic item is listed (`LIBRARY $4086` sets `$6DD9`; the visible mark is what the control shows) |
| refutes | identical ITEMS text with and without the row |

### The Prayer runs

| | |
|---|---|
| run 1, DOS Pool | the fixture party with `(63, 35, $FF, $0A, $03)`; Save As DOS; D1 `--debug`: `load`, `camp`, `display`, `break 0xF861 id35`, `fight 1`. Accepts: every member's Display page shows Prayer, and the id-35 breakpoint never halts. Refutes: a member without Prayer, or a halt |
| run 1b, DOS Pool | `(63, 49, $FF, $0A, $43)`; Save As DOS gives `31 0A 00 03 00`; D1 `--debug`: `break 0xFF30 bonus`, `break 0xFF48 penalty`, `fight 1`; at each halt the driver reads the asking combatant's side byte `0x10E` through the record pointer the handler holds (`0xFF28`-`0xFF2D`, the builder reads which register) and logs it. Accepts: every halt at `bonus` has side 0 and every halt at `penalty` side 1. Refutes: a party member at `penalty` |
| run 1c, DOS Pool combat | the same fixture party (`3F=23:FF:0A:03`, the id-35 positive; `3F=31:FF:0A:43`, the id-49 control), Save As DOS, `load 'prayer-watch 35'` or `load 'prayer-watch 49'` (`tools/dos/acceptance.py`, DOSBox-X): the handler table, the stub's far jump and the four routines are read live, and each halt is logged. Accepts the control: a `helper` halt for a side-0 attacker after a party attack. The positive says nothing where its `conclusive` is false or no party attack was logged. Refutes nothing on a zero count alone |
| run 2, C64 Curse | `WISH-SPEC-curse-234-party-dualclassed` with `31 0A 00 05 00` written into every member's `.SPC`; Save As C64 gives `(63, 49, $FF, $0A, $03)`; D2 Curse: `load`, `camp-list`, `fight 1 --checkpoint $225D` (the equal-side branch, `COMBAT $226D`-`$2272`); the one-second fight ends the run `lost` on its budget by design, and the evidence is the count recorded in `lost_reading`. Accepts: PRAYER in every member's camp list and the checkpoint count in `lost_reading` rises on a party member's attack. Refutes: no PRAYER, or a count of zero through a round with a party attack |
| run 2b, C64 Pool | the same with `31 0A 00 05 00` on one member; the camp list is expected **not** to name it (Pool's `ECL65` has no row for 49); a list that does name it refutes the plan's reading and nothing else |
| run 3, Amiga Pool | D3 with the same converted party: `display`, then `fight 1` reading nothing but the screen; accepts on Prayer under every member. This run waits on the Display keys read |

### The cure-disease runs

| | |
|---|---|
| run 1, the clock | `WISH-SPEC-curse-131-dualclassed-in-area-1` staged as `curseregain.py` stages it (`0xD51`, experience); D1 Curse: `load`, `save B`, `train 1`, `save C`, `read`; `read` gives the clock of `SAVGAMB` and `SAVGAMC` through `world_state.from_dos`. The same for Silver Blades on the archives' `SAVGAMA.DAT` once D1's Silver Blades `train` keys are read. Accepts the unreachability claim: one training moves the clock by 1,680 minutes or more in both titles, and the loss line for "cures spent with a node running" comes off with the two numbers cited. Refutes: less than 1,680 in either, and the conversion of that state stays open work |
| run 2, the crash | a DOS Curse paladin who cured (a running 141 node, 10,080 minutes, written into his `.SPC`) and then changed class (the record staged the way `curseregain.py` stages the change); D1 Curse: `load`, `begin`, `camp`, `rest 8d`. Accepts the finding: the run ends in the game's runtime error (PNG of the message, DOSBox's exit logged) before the rest completes. Refutes: the rest ends normally and the record afterwards holds a byte the handler wrote. Either result goes to `docs/234`; the crash goes to `goldbox-bugs.md` as the game's own, CONFIRMED |

### The joined-scroll runs

| | |
|---|---|
| specimen | none exists, so the run makes one: a Silver Blades DOS save with two `Mage Scroll` items written into one mage's `.STF` (an input), D1 Silver Blades: `load`, `items N`, `join` (a new step: the ITEMS bar's `JOIN`, keys read off the screen), `save D`, `read`. Accepts: `dosscrollbundle.walk` shows one bundle of two in the resaved `.STF`, `item_count` counts the head, and the pack after it is intact. Added to `$WISH_SPECIMENS` as the engine-written joined-scroll save |
| to the C64 | Save As C64 from that specimen; D2 Silver Blades: `load`, `items N`, `save`. Accepts: ITEMS lists both scrolls separately with their spells, and the resaved record holds two scroll slots |
| to the Amiga | Save As Amiga; D3 Silver Blades: `load`, `items N`, `save D`, `fetch`, `read`. Accepts: the ITEMS capture shows the joined scroll once, and `amiga_later` reads the resave back with the bundle and its two sub-nodes, the pack after it intact |
| back to DOS | the Amiga resave converted back; D1 `load`, `items N`, `save`, `read` gives the same bundle |
| the 121-scroll limit | a Silver Blades Amiga save with 121 joined scrolls across the party, D3 `items` per member. Optional: it turns a PROBABLE stop into a measured limit, and the chooser it would need is interface work outside these runs |

### The opening-scene runs

| | |
|---|---|
| C64 | after D0, `openingscene.py --title ssb --save <SSBA.D64 regenerated at the SHA> --wait 600`; accepts on the prologue, Priam, the 2,500 share and the world bar at 3,3 facing south, with the experience rows showing +2,750 for the single-classed members against the game's own run |
| DOS | the Amiga `savgamA.sav` converted to DOS (Part 1's output); D1 Curse and Silver Blades: `load`, `begin`; accepts on the same intro screens the archives' own `SAVGAMA.DAT` shows in a control run of the same steps |
| Amiga | the DOS `SAVGAMA.DAT` converted to Amiga; D3 Curse and Silver Blades: `load`, `begin`; accepts on the opening playing, against the shipped `savgamA.sav` as the control |

### The trait-slot runs

| | |
|---|---|
| the first check | no emulator: a copy of a Pool C64 save with one character wearing readied gauntlets (power `$83`, `+14` = 38) and 38 in a trait slot, through `prepare_save_as` to DOS and to Amiga; the report's stopping or not is logged |
| reachability | D2 Pool: the same character with the gauntlets in his pack un-readied and no 38 in a slot, `ready N gauntlets`, then the ten slots read from `$6BAD`. Accepts the branch as reachable: 38 appears in a slot. Refutes: it does not (the strength handler writes elsewhere), and the branch is then classified from that reading |
| conversion | if reachable, Save As DOS of the readied state; D1 Pool: `load`, `sheet N`, `read`. Accepts: the sheet's strength equals the C64 sheet's, and the resaved `.SPC` holds the strength node `26 00 00 vv 01` with `vv` the strength before the item (`docs/230` (c)); un-readying in a second step restores it |

### The Save As matrix

The design's acceptance asks for one load of each Save As output in its own
game. There are twenty directed same-title routes: three titles with six
directions each, and Pools of Darkness between DOS and the Amiga. Each route's
proof is one run of its destination pair's foundation command (section 5) on
the Save As output of the named source specimen, at a pushed SHA with CI green,
through `editor.saveplan.prepare_save_as` and `publish` or
`tools/convert/saveasdrive.py`. Two controls apply to every route. The move
control is the pair's own (section 5). The identity control names a field that
differs between the converted party and any party the destination could have
loaded instead (the bundled slot on an Amiga disk 1, the shipped `SAVGAMA` of
the archives, the specimen's own earlier slot), read from the game-written
save, so a run that loaded the wrong slot fails it. The open ticket that owns
each route's proof is named in the coverage plan on #679 (Make one repeatable
load, inspect, move, save and verify run reliable on each destination
platform, so conversion tickets reuse it).

| # | route | conversion in Wish | proof supplied by | source specimen |
|---|---|---|---|---|
| 1 | Pool, C64 to DOS | `C64ToDos`; Save As DOS | DOS Pool | The committed fixture `tests/fixtures/savedgame0.bin` and `savedgame1.bin` as a disk, or `WISH-SPEC-por-52-dialog-converted-resave` |
| 2 | Pool, C64 to Amiga | `C64ToAmiga`; Save As Amiga with disk 2 | Amiga Pool | `WISH-SPEC-por-52-dialog-converted-resave` |
| 3 | Pool, DOS to C64 | `DosToC64`; Save As C64 with the player's `POOL` sides | C64 Pool | `WISH-SPEC-por-party-l1-intown` slot E |
| 4 | Pool, DOS to Amiga | `DosToAmiga`; Save As Amiga with disk 2 | Amiga Pool | `WISH-SPEC-por-party-l1-intown` slot E |
| 5 | Pool, Amiga to C64 | `AmigaToC64`; Save As C64 | C64 Pool | `WISH-SPEC-por-amiga-slums-resave` |
| 6 | Pool, Amiga to DOS | `AmigaToDos`; Save As DOS | DOS Pool | `WISH-SPEC-por-amiga-slums-resave` |
| 7 | Curse, C64 to DOS | `C64ToDos`; Save As DOS | DOS Curse | `WISH-SPEC-curse-h-engine-resave` |
| 8 | Curse, C64 to Amiga | `C64ToAmiga`; Save As Amiga | Amiga Curse | `WISH-SPEC-curse-party-with-items` |
| 9 | Curse, DOS to C64 | `DosToC64`; Save As C64 | C64 Curse | `WISH-SPEC-curse-131-dualclassed-in-area-1` |
| 10 | Curse, DOS to Amiga | `DosToAmiga`; Save As Amiga | Amiga Curse | `WISH-SPEC-curse-234-party-dualclassed` slot D |
| 11 | Curse, Amiga to C64 | `AmigaToC64`; Save As C64 | C64 Curse | `WISH-SPEC-coab-amiga-resave` |
| 12 | Curse, Amiga to DOS | `AmigaToDos`; Save As DOS | DOS Curse | `WISH-SPEC-coab-amiga-resave` |
| 13 | Silver Blades, C64 to DOS | `C64ToDos`; Save As DOS | DOS Silver Blades | `WISH-SPEC-ssb-joined-arrow-c64-672` |
| 14 | Silver Blades, C64 to Amiga | `C64ToAmiga`; Save As Amiga | Amiga Silver Blades | `WISH-SPEC-ssb-joined-arrow-c64-672` |
| 15 | Silver Blades, DOS to C64 | `DosToC64`; Save As C64 | C64 Silver Blades | `WISH-SPEC-ssb-299-whole-engine-resave`, or `WISH-SPEC-ssb-joined-arrow-dos-672` slot D |
| 16 | Silver Blades, DOS to Amiga | `DosToAmiga`; Save As Amiga | Amiga Silver Blades | `WISH-SPEC-ssb-joined-arrow-dos-672` slot D |
| 17 | Silver Blades, Amiga to C64 | `AmigaToC64`; Save As C64 | C64 Silver Blades | `WISH-SPEC-ssb-amiga-moved` |
| 18 | Silver Blades, Amiga to DOS | `AmigaToDos`; Save As DOS | DOS Silver Blades | `WISH-SPEC-ssb-amiga-moved` |
| 19 | Pools of Darkness, Amiga to DOS | `PodAmigaToDos` behind `WISH_EXPERIMENTAL_POD_CONVERT`: File > Convert, or `acceptance.py --amiga-slot` | DOS Pools of Darkness | `SavGamB.pty` on the registry's `(SSI)(Disk 3 of 3)[a].adf`, a played save found on a disk image, so an input and not a measurement |
| 20 | Pools of Darkness, DOS to Amiga | None: the `.pc` writer (`amiga_pod.write_pod`) exists, and the saved-game writer, its detection and the direction do not | Amiga Pools of Darkness, foundation proven (section 5) | `WISH-SPEC-p175-diff1` once a route exists |

Routes 8, 10, 14 and 16 (Curse and Silver Blades to the Amiga) needed
#677 (Save As to the Amiga puts a Curse or Silver Blades party on a separate
save disk that the game never reads while its own disk A is in DF0): Save As
now writes a copy of the player's disk 1 with the slot in its `SAVE` drawer, and
all four routes have been proven live on that output.

## 5. Order: the foundation runs, then the conversion runs

A platform's foundation run comes first. A conversion ticket's boot runs only
on a pair whose foundation run has passed with its control, and `docs/236`
("Foundation gate") lists what the platform needs before conversion work
depends on it. The foundation runs load a party, open a sheet, move it, save
through the game's own controls and read the game-written save back; they do
not connect the live automapper, which the gate also requires, and only Amiga
Pools of Darkness reloads the game-written save (its reload boots, below), so
"proven" below means those five steps with a control. D0 is
built, and the developer tools publish through Save As
(`tools/convert/saveasdrive.py`).

### The proof rule

A pair is proven when two consecutive boots at one clean pushed SHA, with CI
green for that SHA, print identical verdict lines and a control reports that
the party did not move. Both boots use the same specimen and command, and each
control exits 0 with its own verdict line; a boot lost to a wandering monster or a white title screen is rerun at
the same SHA, and the two passing boots must still be consecutive.

| platform | the walk | the control |
|---|---|---|
| DOS | `walk MI` (Pool, Curse), `walk I` (Pool only: one forward step, no turns) or `walk 1` (Silver Blades, Pools of Darkness), judged by the status token and by the place in the game-written save | `turn N` in place of the walk: `read` prints "did not move" |
| C64 | `walk KI` (Pool) or `walk JI` (Curse, Silver Blades): a turn, then a step; the place is decoded from the game's own resave | `walk K` or `walk J` alone: the party turns, the saved square is unchanged (`place_changed` false) |
| Amiga | The route's two saves around a walk: the control slot before it, the after slot after it, both decoded from the fetched disk | The control slot: "did not move" |

### The eleven pairs

Evidence is under `~/.cache/wish/acceptance/679/` (Amiga Silver Blades'
under `672/`), each run named `<sha>-<run>`. All eleven pairs are proven, each at a
SHA whose lint and test jobs passed.

| pair | status | SHA | runs | specimen registered from the game's save |
|---|---|---|---|---|
| DOS Pool of Radiance | Proven | `5b586acc35` | `found-dospool-a`, `-b`, `-control` | `WISH-SPEC-dos-pool-foundation-walked` |
| DOS Curse of the Azure Bonds | Proven | `5f3b09ec77` | `found-curse-a`, `-b`, `-control` | `WISH-SPEC-dos-curse-foundation-walked` |
| DOS Secret of the Silver Blades | Proven | `5f3b09ec77` | `found-ssb-a`, `-b`, `-control` | `WISH-SPEC-dos-ssb-foundation-walked` |
| DOS Pools of Darkness | Proven | `79aa61820e` | `found-pod-a`, `-b2`, `-control` | `WISH-SPEC-dos-pod-foundation-walked` |
| C64 Pool of Radiance | Proven | `a0b1be90f1` | `found-por-a`, `-b`, `-control` | `WISH-SPEC-por-679-c64-walked-resave` |
| C64 Curse of the Azure Bonds | Proven | `14c1ee21a4` | `found-curse-a`, `-b`, `-control` | `WISH-SPEC-curse-party-with-items-walked` |
| C64 Secret of the Silver Blades | Proven | `f9008e1592` | `found-ssb-a`, `-b`, `-control` | `WISH-SPEC-ssb-d-engine-resave-walked-foundation` |
| Amiga Pool of Radiance | Proven | `5fcbfccc65` | `amiga-pool-accept2b`, `-accept3b` | `WISH-SPEC-amiga-pool-foundation-walked` |
| Amiga Curse of the Azure Bonds | Proven | `400d2381cd` | `amiga-curse-accept2`, `-accept3` | `WISH-SPEC-amiga-curse-foundation-walked` |
| Amiga Secret of the Silver Blades | Proven | `400d2381cd` | `amiga-accept2`, `-accept3` | `WISH-SPEC-amiga-ssb-foundation-walked` |
| Amiga Pools of Darkness | Proven | accept `6b17ee420c`, reload `d2a23aa478` | `amiga-darkness-accept-A`, `-B` (accept), `amiga-darkness-reload-A`, `-B` | `WISH-SPEC-amiga-pod-foundation-walked` |

The commands and what they printed, the same in both boots of each pair:

| pair | command | verdict lines | control |
|---|---|---|---|
| DOS Pool | `acceptance.py --title pool --fixture-row 3F=01:00:2F:01 --slot A --steps load 'sheet 1' 'walk MI' camp 'save D' read --issue 679 --deadline 420` | Moved from 0,4 to 1,4, area 0 facing 1; the effect on BRUTUS 47 to 46 minutes | `'turn 2'`: did not move, area 0 at 0,4 |
| DOS Curse | `--title curse --save WISH-SPEC-curse-632-wish-converted-resave --from-slot B --slot B --steps load 'view 2' begin 'walk MI' camp 'save D' read` | Moved from 5,13 to 6,13, area 1 facing 1; six characters, no node lost | `'turn 2'`: did not move, area 1 at 5,13 |
| DOS Silver Blades | `--title ssb --save WISH-SPEC-ssb-299-whole-engine-resave --from-slot D --slot D --steps load 'view 2' begin 'walk 1' camp 'save E' read` | Moved from 3,3 to 3,4, area 16 facing 2 | `'turn 4'`: did not move, area 16 at 3,3 |
| DOS Pools of Darkness | `--title darkness --amiga-disk '(SSI)(Disk 3 of 3)[a].adf' --amiga-slot SavGamB.pty --steps load 'view 4' begin 'walk 1' camp 'save D' 'items 4' read --deadline 360` | Moved from 1,2 to 2,2, map 2 facing 1; the sheet names DONALD DUCK | `'turn 4'`: did not move, map 2 at 1,2 |
| C64 Pool | `acceptance.py --title pool --save WISH-SPEC-por-52-dialog-converted-resave.D64 --steps load 'view 1' 'walk KI' 'view 1' save --max-seconds 1500` | Facing 3 to 0, then 0,4 to 0,3; `place_changed` true | `'walk K'`: 0,4 facing 0, `place_changed` false |
| C64 Curse | `--title curse --steps load 'view 1' 'walk JI' 'view 1' save` on `WISH-SPEC-curse-party-with-items.D64` | 4,4 facing 0 to 4,4 facing 3, then 3,4; `place_changed` true | `'walk J'`: 4,4 facing 3, `place_changed` false |
| C64 Silver Blades | `--title ssb --steps load 'view 2' 'walk JI' 'view 2' save` on `WISH-SPEC-ssb-d-engine-resave-walked.D64` | 3,5 facing 2 to 3,5 facing 1, then 4,5; `place_changed` true | `'walk J'`: 3,5 facing 1, `place_changed` false |
| Amiga Pool | `acceptance.py accept --title pool --manifest … --guards … --identity … --audio-proof … --attempt …` | Slot D moved 1 square from area 0 9,13 facing 0 to 9,14 facing 2, and matches the game's own save after the same walk | Slot C: did not move |
| Amiga Curse | `acceptance.py accept --title curse`, the same arguments | Slot F moved 2 squares from 4,4 to 4,2, and matches the game's own save after the same walk | Slot D: did not move |
| Amiga Pools of Darkness | `acceptance.py accept --title darkness --manifest … --guards … --identity … --audio-proof … --attempt acceptA` (and `acceptB`) | Slot G moved 1 square from 1,2 to 2,2, map 2 facing 1 | Slot F: did not move |
| Amiga Silver Blades | `acceptance.py accept --title ssb --manifest … --guards … --identity … --journal-python /usr/bin/python3 --audio-proof …` | Slot D moved 2 squares from 3,5 to 3,7, facing 2 | Slot B: did not move |

The sources: DOS Pool boots the committed C64 fixture party converted by Save
As DOS with one staged Bless row. DOS Curse and Silver Blades boot the
registered engine-written and converted DOS saves named above, and DOS Pools
of Darkness boots `SavGamB.pty` on the registry's `(SSI)(Disk 3 of 3)[a].adf`
converted through the Convert window's route, a played save found on a disk
image, so an input and not a measurement. The C64 titles boot registered C64
saves. The Amiga runs boot the registered specimen (Pool
`WISH-SPEC-por-52-c64toamiga-walk-resave`, Curse
`WISH-SPEC-curse-c64toamiga-slotb-walked-saved-c`), for Pools of Darkness the
registered disk 3 (the save disk, no specimen) with disk 1 in DF0, or, for Silver Blades, the
pinned C64 JOIN party `WISH-SPEC-ssb-joined-arrow-c64-672` published through
Save As Amiga. All of it is read-only, and each run's disks are hash-checked
before and after.

DOS Silver Blades was run again after the run's deadline began bounding the
route helpers it borrows. At `6e377388d6b230e6c8c585d3a93fa1fac5cf1cea` the
command in the table, with `--deadline 420` under `timeout -k 30 720`, moved
the party from 3,3 to 3,4, area 16 facing 2, in 33 s; the control (`'turn 4'`
in place of `'walk 1'`) did not move, area 16 at 3,3, in 39 s. Every step
reported done and the deadline was named in neither output. The specimen is
`WISH-SPEC-ssb-299-whole-engine-resave` under `/mnt/specimens/por-dos/`.
Evidence is `~/.cache/wish/acceptance/683/6e377388d6-run` (the control's
summary; the walk run's own summary was overwritten by the control in the same
directory) and `~/.cache/wish/acceptance/683/6e377388d6-console/` (`walk.log`,
`control.log`).

**What differs per title** is in sections 2 and 3: the status token column and
move modes (DOS), the walk letters, panel order and save sequence (C64), and
the disks and first keys (Amiga). Three Amiga save details belong here. Curse's
after slot is F because E is the game's own exit key on the sheet and at camp,
and its save presses no Return after the letter and answers `N` at `EXIT GAME`.
Pool's save asks `QUIT TO WORKBENCH YES NO` (`quit_prompt`) after each letter,
answered `N`. Silver Blades takes no Return after the camp save's letter,
answers `N` at `EXIT GAME`, and answers its journal question through the
private helper under `/usr/bin/python3`.

**The Amiga silence proof.** Only one WinUAE lane exists, so no two Amiga runs
overlap. Each run passes `--audio-proof`, the JSON `winuaemute.ps1` prints
after muting the guest's default playback endpoint and reading the mute back,
and the driver refuses a readback older than five minutes.

**Amiga Pools of Darkness is proven, by two accept boots and two reload boots.**
The route mounts disk 1 in DF0 and disk 3 in DF1 from the first frame and presses
`P L P B`; at the game's `INSERT DISK 2` prompt the driver inserts disk 2 into
DF0 and presses `SPACE`, then `SPACE V E` loads the party, opens the sheet and
returns to the party menu. Save letter `F` is the control, saved there. `B`
begins the adventure; the journal question screen is answered with one
throwaway letter `X` and `RET`; `NP8` steps once; `E` opens camp and `S` and
letter `G` save. `N` answers the game's `QUIT GAME?` question. The letters are
`F` and `G` because the picker offers `A` to `H` and `A` to `E` are the save
disk's own slots: the route loads `B` and keeps `A`, `C`, `D` and `E` unchanged
(`tools/amiga/route_darkness.py`, `DARKNESS`).

The accept boots ran at `6b17ee420c95dbf57e08ffdd1d6b1ef1bab7f2d7`
(`~/.cache/wish/acceptance/679/6b17ee420c-amiga-darkness-accept-A/acceptA/` and
`-accept-B/acceptB/`, with `guards.json` in `amiga-darkness-guards-11/` and the
identity map in `amiga-darkness-guards-7/`). Both succeeded with identical
reads, control digest and after digest: the control reads `slot F: did not move`,
the after save `slot G: moved 1 square from 1,2 to 2,2`, slots A, C, D and E and
disks 1 and 2 are unchanged. Slots F and G are byte-equal across the two boots
and registered as `WISH-SPEC-amiga-pod-foundation-walked`.

The reload boots ran at `d2a23aa478cb608b3b66635889cfbc077d9afb81`
(`~/.cache/wish/acceptance/679/d2a23aa478-amiga-darkness-reload-A/reloadA/` and
`-reload-B/reloadB/`; guards in `amiga-darkness-guards-12/`, identity in
`amiga-darkness-guards-11/`). Each loads slot G from the disk 3 that one accept
boot fetched, through `acceptance.py reload --title darkness-reload`, which
writes nothing. Both succeeded with identical verdicts: `slot G: reloaded at
area 2 2,2 facing 1` and `slot F: area 2 1,2 facing 1 is not on the screen`;
disks 1 to 3 and every kept slot are unchanged. The reload command is
`acceptance.py reload --title darkness-reload --manifest … --guards … --identity … --audio-proof … --attempt reloadA` (and `reloadB`). The accept boots used `amiga-darkness-guards-11/guards.json` with the identity map from `amiga-darkness-guards-7/`, the reload boots `amiga-darkness-guards-12/guards.json` with that of `amiga-darkness-guards-11/`; the run summaries do not record these paths, so they come from the launch commands the runner was given, and the identity file is byte-identical in guards 7, 11 and 12.

A DF0 insert is proven possible. At
`6e377388d6b230e6c8c585d3a93fa1fac5cf1cea`, `tools/amiga/amigadrivecheck.py` on
generated disks (no game) swapped DF0 from A to B and back to A, each applied
in about 2.4 s, confirmed by the `CFG floppy0` query and by `DBG c` polling the
drive from `ro` to `rw`, with DF1 unchanged. The controls (another holder's
claim, another holder's path, a file never staged, the same path twice) all
left both drives unchanged. Evidence:
`~/.cache/wish/acceptance/679/6e377388d6-amiga-drivecheck/summary.json`; the
command contract is `docs/143-winuae-debugger.md` section 4.2.

The foundation gate stays in front of every conversion ticket's boot on a
platform: a run in section 4 boots only on a pair whose row above says Proven,
and every pair now says Proven.

### The native C64 Pool run

The C64 Pool pair above boots a save Wish converted. This row boots the six
characters the game's own CREATE NEW CHARACTER screens wrote
(`WISH-SPEC-por-c64-party-l1-intown`, `docs/90-specimens.md`), so the run loads
a save we watched being written and it adds a reload.

| pair | status | SHA | runs | specimen registered from the game's save |
|---|---|---|---|---|
| C64 Pool of Radiance, native party | Proven | `e47999730a` | `found-por-native-a`, `-b`, `-control`, and one reload | `WISH-SPEC-por-c64-foundation-walked` |

| pair | command | verdict lines | control |
|---|---|---|---|
| C64 Pool, native party | `acceptance.py --title pool --save WISH-SPEC-por-c64-party-l1-intown.D64 --steps load 'view 1' 'walk KI' 'view 1' save --max-seconds 1500` | Facing 3 to 0, then 0,4 to 0,3; `place_changed` true | `'walk K'`: 0,4 facing 0, `place_changed` false |

The party arrives at 0,4 facing west (3). `GEO00` at 0,4 has open ground to
the north and east, a wall to the south and a door barrier to the west, so `K`
is a right turn to face north and `I` steps to 0,3. Runs `a` and `b` read the
same at every step and `acceptance.py --compare` reports no difference; their
saved disks are byte-identical, with all six records unchanged, the clock at
(0,3,0) and VICEHEL the member `view 1` shows before and after. The control
turned to face north and did not move.

The reload boots the registered walked specimen with `--steps load 'view 1'`
and reads 0,3 facing north, the walked square and facing. The C64 driver
prints no verdict lines, so the verdict is each step's position reading in
`summary.json`. Evidence is under `~/.cache/wish/acceptance/722/`, each run
named `e47999730a-found-por-native-<run>`.

## 6. Slots and evidence

| pool | claim | one agent, one slot |
|---|---|---|
| VICE, and FS-UAE | `tools/registry/instance.py claim --game <por\|curse\|ssb\|amiga-por> --note <issue>`; the drivers claim their own | sixteen slots, `:10`-`:25` |
| DOSBox | `tools.dos.dosbox.claim(note)` inside the driver | sixteen, `:50`-`:65` |
| DOSBox-X | `tools.dos.dosboxx.claim(note)` | sixteen, `:90`-`:105` |
| WinUAE | `winuae.ps1 claim -Holder <issue-run>` through `winvm ssh`; released in `finally` | one lane for the whole project; no two Amiga runs at once |

Every emulator is headless and silent, and the evidence differs by platform.
VICE (`POR_HEADLESS=1`, `launch.sh`'s `+sound`) and DOSBox (the pooled
configuration disables the mixer, Sound Blaster and PC speaker) rest on the
host's `virsh dumpxml agent-vm`: no sound device and an audio backend of `none`
(`docs/233`), so a missing guest `pactl` blocks nothing. WinUAE's is the JSON
readback `winuaemute.ps1` prints after muting the guest's default playback
endpoint, taken through `winvm ssh` immediately before the boot and passed as
`--audio-proof`; the driver refuses one older than five minutes
(`.claude/rules/emulator.md`).

## 7. Who does what

| work | agent | why |
|---|---|---|
| The unbuilt steps of D1 (`fight`, `chain`, `break`, `--debug`) and the first build of each later D2 step | `reverse-engineering` | Each has screens or breakpoints nobody has digested, and the digest comes off the game's own capture |
| Each later step of D1 and D2 | `junior-dev` | The screen is read by then; the step is a port of a named routine |
| A route repair, or the guards and identity map for a new Amiga title or state | `reverse-engineering` | A screen the route does not match is read off the crops of a measuring boot, with no boot of its own |
| The two Amiga screen reads (a second member's sheet in Pool, Magic > Display keys) | `reverse-engineering` | Screens read for a driver, not measurements |
| The foundation runs (section 5) and every run in section 4 | `emulator-runner` | A finished driver command, a named reading, one boot per attempt and a budget; it reports observations and interprets nothing |
| Reading a run's result against a ticket and closing it | The root, after the finding is on the issue | The ticket's own plan says what accepts |

An `emulator-runner` handed a driver that cannot do a step hands the run back
with the evidence so far and what the driver would have to do; that is the
escape hatch, and it is where a new step gets its screen read.

## 8. For Donald

No decision waits on him. The label and picker title of Save As's disk 1 row
(#677 (Save As to the Amiga puts a Curse or Silver Blades party on a separate
save disk that the game never reads while its own disk A is in DF0)) were
approved and built, and the Amiga Curse and Silver Blades runs on Wish's own
output have passed.

Three things he will be told once the runs have been made, each in player
terms and none a choice:

* the DOS range on Prayer's penalty to monsters, once the Prayer runs' run
  1b is in;
* whether C64 Pool's combat Prayer favours the monsters (the polarity run
  named in Part D read (b) of the Detect Magic runs' ticket), which decides
  only which side a converted row favours;
* what the Silver Blades opening gives a converted party that leaves the
  starting treasure, once the opening-scene runs resave.

The joined-scroll chooser and the tooltip for a greyed field are interface
text and stay where their tickets left them; no run above depends on either.
