# Destination-game acceptance runs for the conversion tickets

A conversion ticket closes only when a save that used to fail converts on the
reviewed, pushed SHA with CI green, loads in the destination game, and the
state the ticket is about is read back out of that game with the player's
behaviour preserved. Nine open tickets have pushed code and no such run. This
page is the plan for those runs: the three drivers they share, what each
platform can already read, the order that unblocks the most tickets, who
builds what, and how the evidence is kept. Each ticket's runs are named once
here and by that name afterwards.

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
   `editor.saveplan.prepare_save_as` and `publish` (Save As), or
   `tools/convert/convertrun.py --no-play` for File > Convert. The output
   bytes, the SHA, and the conversion's `dropped` and `losses` lists (both
   empty) go in the log. A run made from output that was not produced this
   way tests the writer, not the program.
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
line, the evidence path and the reading, and the issue is then closed by hand
after `gh issue view N --json state`.

## 2. What each platform can read today

| platform | emulator and pool | keys | screen | memory | files the engine writes | title protocols in the tree |
|---|---|---|---|---|---|---|
| C64 | VICE through `tools/registry/instance.py` (`claim`, displays `:10`-`:25`) | `Session.select_bar`, `select_row`, KERNAL buffer | **text**, `Session.screen_text()` and `screen()` row by row | binary monitor: peeks, non-stopping exec checkpoints (`tools/c64/effectdrive.py checkpoint_hits`), watchpoints (`livewatch.py`) | the save disk, copied out closed (`por.copy_closed_disk`) or repaired (`curseload.close_splat`) | Pool `Session` (load, walk, fight, `save_game`); Curse `curserun.CurseSession` + `curseload`, `cursecheck.py`, `laterbattle.py`; Silver Blades `ssbwarp.SSBSession`, `ssbresavewalk.py`, `laterbattle.py` |
| DOS | DOSBox 0.74 through `tools/dos/dosbox.py` (`claim`, displays `:50`-`:65`) | `xdotool` keysyms | **pixels only**: 320x200 PNG, `Screen.digest`/`ink`/`glyphs` for equality, `highlight_row`; no text | none | `SAVE/` after `ENCAMP > SAVE`: records, `.ITM`/`.STF`, `.SPC`/`.FX`/`.SFX`, `SAVGAM<slot>.DAT` | Pool `PoolOfRadiance` (menu, load, move, camp save, fight); Curse `dossheetread.py` (load, sheets, walk, engine save), `Camp.memorize`, `curseregain.py` (train, camp save); Silver Blades `ssbimport.py Driver` (party menu, intro, encamp, rest by days, camp save, sheet), `dossheetread.py --move-mode` |
| DOS, debugger | DOSBox-X debug build through `tools/dos/dosboxx.py` (`claim`, displays `:90`-`:105`); `dosboxx.unavailable()` is `None` on this machine | the same | the same, halved from 640x400 | `read`/`write` any linear address, `watch` (one byte, on change), `brk` (fires silently, `wait_halt` probes), `regs` through `EV`; `dosspcexpiry.read_party` reads Pool's effect chains node by node off the heap | the same | `PoolOfRadiance` runs unchanged on `XSession`; the later titles' chain heads (Curse record `0x0F2`, Silver Blades `0x0FB`) are read but no tool follows them yet |
| Amiga | WinUAE in the Windows VM, one lane (`winuae.ps1 claim -Holder`), reachable from this VM (`winvm status`) | `tools/amiga/amigadrive.py keys`, `winvmsettle.py` between keys | **pixels**: `winvm shot`, `amigashots.py` crop | `winuaepipe.py` / `automap.amiga.WinuaePipe`: `m` and `S`-to-file reads while the machine runs; `automap/amiga.py` locates the data hunk and the party | the `.adf`, copied back with `winvm get`, read by `amiga_savegame`, `porslotdiff.py`, `amigalaterproof.py diff` | Pool `docs/182` §7 (twenty keys); Curse and Silver Blades `docs/203` "Reproducing it", with `amigacursewheel.py` and `amigabladesjournal.py` (both under `/usr/bin/python3`); `amigacampsave.py` (repeated camp saves, Silver Blades) |
| Amiga, FS-UAE | stock `fs-uae` in a VICE-pool slot (`instance.py claim --game amiga-por`), `tools/amiga/fsuaepor.py serve` | `fsuaepor.py keys` | pixels, `fsuaepor.py shot` | none; the GDB build `installfsuae.py` fetches is not installed here | the staged `.adf` in the run directory, `fsuaepor.py names` | Pool of Radiance and Pools of Darkness only: Curse stops at the code wheel, Silver Blades has never been driven |

Three consequences for the plan:

* **DOS has no screen text, so a DOS reading is a file or a memory read, and
  a screenshot is corroboration.** The file reader is the strongest: the
  engine's own `ENCAMP > SAVE` writes the effect nodes, the item chain, the
  clock and the record, and every one of those has a decoder in `goldbox/`
  or `tools/dos/` (`dos_codec.read_party` and `to_neutral`,
  `ssbimport.effect_nodes`, `dosscrollbundle.walk`,
  `world_state.from_dos` for the clock). The DOSBox-X memory read is needed
  only where the ticket asks what happens *during* play: a handler firing
  in a fight, a chain ageing between two saves. A screenshot of the ITEMS
  list or Magic > Display is read by the agent that took it (the Read tool
  shows a PNG) and reported as an observation, with the PNG kept.
* **The C64 reads everything**, and its gap is coverage: `effectdrive.py`
  stages rows and rests in Pool only, no driver reads the camp list of
  spells in effect, and the later titles' fights are `laterbattle.py`'s.
* **The Amiga's driver of record is WinUAE**, because it runs all three
  titles, answers both copy-protection prompts, and reads memory through
  the pipe. FS-UAE is a second seat for Pool of Radiance only. Two things
  no Amiga tool can do yet: reach a second party member's sheet in Pool of
  Radiance (`docs/182` §6), and open Magic > Display; both are screen
  sequences to be read before a run needs them.

## 3. The three drivers, and the one fix that comes first

Each ticket's check is a source, a boot, a step list and a reading. The
sources, boots and readings already exist per platform; what does not exist
is one driver per platform that takes a Wish-written save, a title, and a
step list, and prints what it read. Building four drivers per ticket is how
the opening-scene runs spent three rounds; one per platform is the shared
harness.

### D0. `tools/c64/openingscene.py` answers the Silver Blades treasure bar (`junior-dev`, first)

The opening-scene runs stall at `GO BACK LEAVE TREASURE`, the prompt the
game puts up after `EXIT` at `VIEW TAKE POOL SHARE EXIT`, because
`opening_step` has no case for it (three runs, all ending there). Add the
case: row 24 holding both `GO BACK` and `LEAVE TREASURE` gives `leave`, and
`answer_bar` calls `sess.select_bar("LEAVE TREASURE")`, with the same
unchanged-row-24 fallback the `exit` case has. One test row in
`test_opening_step_reads_each_bar`, seen red first. Leaving the treasure is
what `ssbwarp.enter_world` also does, and it forgoes the starting equipment
and money a player would take; the run compares experience, which the
treasure does not touch, and both the game's own save and Wish's get the
same treatment. Owns `tools/c64/openingscene.py` and
`tests/c64/test_openingscene.py`; runs those tests, `ruff` and
`genui.py --check`.

### D1. `tools/dos/dosacceptance.py`: load a Wish-written DOS save and read it back (`reverse-engineering` builds, `junior-dev` extends)

One entry point over `tools/dos/dosbox.py` and, with `--debug`,
`tools/dos/dosboxx.py`:

    dosacceptance.py --title pool|curse|ssb --save DIR --slot A \
        --steps load sheets 'rest 5m' 'save D' read --out DIR

It stages the whole save the way `dossheetread.install_whole` does, boots,
and runs the steps in order, writing `run.jsonl`, a PNG per step and
`summary.json`. Steps, and where each comes from:

| step | does | exists in |
|---|---|---|
| `load` | title menu, `LOAD SAVED GAME`, the slot | `PoolOfRadiance.to_main_menu`, `load_game`; `dossheetread --load-keys` |
| `sheets`, `sheet N` | `VIEW` every member or member N, one PNG each | `dossheetread` (all three titles, `--pick-*` for Silver Blades) |
| `items N` | member N's ITEMS list, one PNG | new: the key from the sheet is read from the sheet's own bar |
| `begin` | `BEGIN ADVENTURING` through the intro to the world bar | `ssbimport.Driver.intro` (Silver Blades); Pool and Curse need their intro bars digested |
| `walk N` | N steps, turning at walls | `dossheetread.walk` |
| `camp` | `ENCAMP` | `PoolOfRadiance.save_game`'s first half; `ssbimport.Driver.encamp` |
| `rest 5m`, `rest 8h`, `rest 8d` | camp `REST` for minutes, hours or days | `ssbimport.Driver.rest` (days, Silver Blades); Pool's and Curse's rest menus have no digests yet |
| `display` | camp `MAGIC > DISPLAY`, one PNG per page | new: the Magic menu is `Cast Memorize Scribe Display Rest Exit` (Part D read (d) of the Detect Magic runs' ticket); `Camp.memorize` reaches `MAGIC` in Curse |
| `train N` | the hall's `TRAIN CHARACTER` for roster line N | `dostrain.py` (Pool, steps the party into the hall), `curseregain.py` (Curse, `0xD51` poked, trains at the party menu); Silver Blades is gated on the same word and needs its keys read |
| `save X` | camp `SAVE` to slot X, believed when the file changes | `PoolOfRadiance.save_game`, `ssbimport.Driver.camp_save`, `curseregain` |
| `read` | copy `SAVE/` out; decode records, items, effect nodes and the clock into `summary.json` | `dos_codec.read_party` + `to_neutral`, `dosscrollbundle.walk`, `ssbimport.effect_nodes`, `world_state.from_dos` |
| `chain` (`--debug`) | each member's effect chain off the heap, with the clock | `dosspcexpiry.read_party` (Pool head `0x07F`); Curse `0x0F2` and Silver Blades `0x0FB` to add |
| `break ADDR NAME` (`--debug`) | a code breakpoint at a `GAME.OVR` file offset, located in memory by its bytes; on each halt, log the registers, run on | `dosboxx.brk`, `wait_halt`, `regs`, `locate` |
| `fight 1` | one round: `QUICK` per member, answering the fight's bars | `dosfightrun.fight` (Pool); the later titles' fight bars are undigested |

**The smallest first driver** is D1 for Pool of Radiance with `load`, `camp`,
`rest Nm`, `save X` and `read`, and no `--debug`. It is the Bless runs' DOS
run whole. Pool's camp bar and save are already digested, so the only new
screen is `REST`'s minutes entry. Then the same five steps for Curse and
Silver Blades (rest and save; `ssbimport` has Silver Blades' rest by days
and its save), which is the cure-disease runs' two clock runs and the Bless
runs' later-title runs. `items`, `display` and `--debug` come third.

The first build goes to `reverse-engineering` because every new step is a
screen nobody has digested and the digest is read off the game's own
capture; `docs/149-driving-a-dos-fight.md` is the method. Each later step is
one `junior-dev` change with a test on composed digests, once its screens
are read. The builder owns `tools/dos/dosacceptance.py`,
`tests/dos/test_dosacceptance.py` and one row in `tools/dos/README.md`, and
changes nothing in the modules it imports.

### D2. `c64acceptance.py`, a planned driver in the C64 subdirectory of the tools directory: stage, boot, read the screen and the machine (`reverse-engineering` builds, `junior-dev` extends)

    c64acceptance.py --title pool|curse|ssb --save X.D64 \
        --stage-row 63=05:FF:0A:03 --stage-trait 0:9=38 \
        --steps load camp-list 'items 2' 'fight 1' 'save' --out DIR

Staging writes into a **copy** under the slot's own directory, through
`goldbox.effects.write_effect` on the save payload (the four arrays sit at
the same payload offsets in all three titles, `docs/226`) and
`traitdrive.stage_traits` for the ten trait slots, so a stage is the same
bytes a test stages. The session is the title's own (`Session`,
`CurseSession`, `SSBSession`), the load its own loader
(`Session.load_save`, `curseload.load_saved_game`, `ssbwarp.load_party`).

| step | does | exists in |
|---|---|---|
| `load` | boot and load, header logged | the three sessions; `openingscene.py` does this for the later titles |
| `camp-list` | `ENCAMP`, the list of spells in effect for each member, as screen text | new: `CAMP $16C3` (Pool) prints it; the keys are read off the camp bar |
| `view N`, `items N` | the sheet and ITEMS list of member N, as screen text | `savecheck.sheets` (Pool), `cursecheck.py`, `ssbresavewalk.py` |
| `ready N ITEM` | `VIEW > ITEMS > READY` on one item, then the ten trait slots read from `$6BAD` / `$7CAD` | new; the addresses are in the trait-slot runs' Stage 3b read |
| `rest 5m` | `ENCAMP > REST` | `effectdrive.rest` (Pool); the later titles' rest menus to read |
| `fight 1` | walk into a fight, one round, with non-stopping checkpoints armed at `--checkpoint ADDR` and their counts logged | `Session.fight` and the Slums ambush (Pool), `laterbattle.py` (Curse at Tilverton's tavern, Silver Blades by waiting), `effectdrive.checkpoint_hits` |
| `peek ADDR N` | N bytes of memory | `Session.mon` |
| `save` | `ENCAMP > SAVE`, the disk copied out closed or repaired, the payload decoded | `Session.save_game`, `por.copy_closed_disk`, `curseload.close_splat`, `goldbox.savegame` |

The first build is the Pool of Radiance half with `load`, `camp-list`,
`items N` and `save`, which is the Detect Magic runs' C64 run; `fight 1`
with checkpoints is the Prayer runs' Curse run and comes second, on
`laterbattle.py`. `reverse-engineering` builds it for the same reason as D1
(the camp list and the later titles' camp bars are unread screens); it owns
`c64acceptance.py` (planned, not yet built, in the C64 subdirectory of the tools directory), `tests/c64/test_c64acceptance.py` and a
README row.

### D3. `amigaacceptance.py`, a planned driver in the Amiga subdirectory of the tools directory: WinUAE, from the converted `.adf` to the engine's resave (`reverse-engineering` builds)

    amigaacceptance.py --holder wish661 --title pool|curse|ssb --adf X.adf \
        --slot B --steps load 'view 1' 'items 1' display 'save D' fetch read

It copies the `.adf` to the guest (`winvm scp`), starts WinUAE with
`goldbox-a500.uae` and the disk in `floppy0`, answers the code wheel or the
journal, loads the slot, runs the steps with `winvmsettle.py` between keys
and `amigashots.py`'s crop on every capture, has the engine save to another
slot, fetches the image back and decodes it (`amiga_savegame`,
`porslotdiff.py`, `amigalaterproof.py diff`). A `mem` step reads the party's
effect chains through the pipe once `automap/amiga.py`'s machine table has
the chain head for the title. The lane is claimed by the run and released in
`finally`; the VM's own audio is muted rather than the emulator's
(`.claude/rules/emulator.md`). Two screen reads come before any run needs
them: how Pool of Radiance reaches a second member's sheet, and the Magic >
Display keys per title. Owns `amigaacceptance.py` (planned, not yet built, in the Amiga subdirectory of the tools directory), its test file
and a README row.

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
| run 2, C64 Curse | `WISH-SPEC-curse-234-party-dualclassed` with `31 0A 00 05 00` written into every member's `.SPC`; Save As C64 gives `(63, 49, $FF, $0A, $03)`; D2 Curse: `load`, `camp-list`, `fight 1 --checkpoint $225D` (the equal-side branch, `COMBAT $226D`-`$2272`). Accepts: PRAYER in every member's camp list and the checkpoint count rises on a party member's attack. Refutes: no PRAYER, or a count of zero through a round with a party attack |
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
| the 121-scroll limit | a Silver Blades Amiga save with 121 joined scrolls across the party, D3 `items` per member. Optional: it turns a PROBABLE refusal into a measured limit, and the chooser it would need is interface work outside these runs |

### The opening-scene runs

| | |
|---|---|
| C64 | after D0, `openingscene.py --title ssb --save <SSBA.D64 regenerated at the SHA> --wait 600`; accepts on the prologue, Priam, the 2,500 share and the world bar at 3,3 facing south, with the experience rows showing +2,750 for the single-classed members against the game's own run |
| DOS | the Amiga `savgamA.sav` converted to DOS (Part 1's output); D1 Curse and Silver Blades: `load`, `begin`; accepts on the same intro screens the archives' own `SAVGAMA.DAT` shows in a control run of the same steps |
| Amiga | the DOS `SAVGAMA.DAT` converted to Amiga; D3 Curse and Silver Blades: `load`, `begin`; accepts on the opening playing, against the shipped `savgamA.sav` as the control |

### The trait-slot runs

| | |
|---|---|
| the first check | no emulator: a copy of a Pool C64 save with one character wearing readied gauntlets (power `$83`, `+14` = 38) and 38 in a trait slot, through `prepare_save_as` to DOS and to Amiga; the report's refusal or not is logged |
| reachability | D2 Pool: the same character with the gauntlets in his pack un-readied and no 38 in a slot, `ready N gauntlets`, then the ten slots read from `$6BAD`. Accepts the branch as reachable: 38 appears in a slot. Refutes: it does not (the strength handler writes elsewhere), and the branch is then classified from that reading |
| conversion | if reachable, Save As DOS of the readied state; D1 Pool: `load`, `sheet N`, `read`. Accepts: the sheet's strength equals the C64 sheet's, and the resaved `.SPC` holds the strength node `26 00 00 vv 01` with `vv` the strength before the item (`docs/230` (c)); un-readying in a second step restores it |

### The Save As matrix

The design's acceptance asks for one load of each Save As output in its own
game. The runs above already load a Save As output in every cell:

| destination | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| C64 | the Detect Magic runs | the Prayer runs, run 2 | the joined-scroll runs |
| DOS | the Bless runs | the cure-disease runs, run 1 | the joined-scroll runs |
| Amiga | the Prayer runs, run 3 | the opening-scene runs | the joined-scroll runs |

So the matrix's runs are these, plus a `walk 2` and engine save in each D1
and D3 run, which every row already includes. The one build it needs first
is B5 from the stage 4 plan on its ticket: `tools/convert/convertrun.py`
calling `saveplan.prepare_save_as` and `publish` instead of
`EditorBinding.convert`, so that the disks these runs boot are Save As's
rehearsed bytes and not a second run of the writer. `junior-dev`, tests in
`tests/convert/test_convertrun.py`.

## 5. Order

1. **D0**, then the opening-scene runs' Silver Blades run. One classifier
   row and one boot; it closes the C64 half of a ticket that has had three
   rounds.
2. **D1 Pool: load, camp, rest, save, read.** Then the Bless runs' DOS run.
3. **D1 Curse and Silver Blades: rest, save, train.** Then the cure-disease
   runs' two clock runs and crash run, the Bless runs' later-title runs, and
   the opening-scene runs' DOS runs.
4. **D1 `items`, `display`, `--debug`.** Then the Detect Magic runs' DOS
   runs and the Prayer runs 1 and 1b.
5. **B5**, so the disks the remaining runs boot come from Save As.
6. **D2 Pool: load, camp-list, items, save; then fight with checkpoints.**
   Then the Detect Magic runs' C64 runs, the Prayer runs' run 2, and the
   trait-slot runs.
7. **D1 `join`, D2 Silver Blades items.** Then the joined-scroll specimen
   and its C64 half.
8. **D3.** Then the joined-scroll runs' Amiga half, the opening-scene runs'
   Amiga runs, the Prayer runs' run 3, the Bless runs' Amiga run, and the
   Save As matrix is complete.

Steps 2 and 6 can run in parallel: D1 and D2 share no file and use different
pools. D3 starts after the two Amiga screen reads it needs, which can run
alongside step 2.

## 6. Slots and evidence

| pool | claim | one agent, one slot |
|---|---|---|
| VICE, and FS-UAE | `tools/registry/instance.py claim --game <por\|curse\|ssb\|amiga-por> --note <issue>`; the drivers claim their own | sixteen slots, `:10`-`:25`; `status` shows all sixteen clean at the time of writing |
| DOSBox | `tools.dos.dosbox.claim(note)` inside the driver | sixteen, `:50`-`:65` |
| DOSBox-X | `tools.dos.dosboxx.claim(note)` | sixteen, `:90`-`:105` |
| WinUAE | `winuae.ps1 claim -Holder <issue-run>` through `winvm ssh`; released in `finally` | one lane for the whole project; no two Amiga runs at once |

Every emulator is headless and silent (`POR_HEADLESS=1`, `porlaunch.sh`'s
`+sound`; the VM's audio device muted for WinUAE). `pactl` is not installed
on the agent VM, so the silence check there is that the VM's own device is
muted, checked through `winvm ssh` before the boot.

Evidence goes under `~/.cache/wish/acceptance/<issue>/<sha>-<run>/` through
`tools/registry/scratch.cache_dir("acceptance", issue, run)`: `run.jsonl`,
`summary.json`, the converted save as booted, every PNG, and the engine's
resave. The scratchpad and the temp directory are not used, because the
flatpak VICE cannot read the temp directory and the scratchpad does not
outlive the session. An engine-written save a test will read goes to
`$WISH_SPECIMENS` with `specimens.py add` and its provenance before
teardown. Nothing under `~/.cache/wish` is committed, and no game bytes are
quoted in the closing comment beyond the node or field values the reading
names.

## 7. Who does what

| work | agent | why |
|---|---|---|
| D0 | `junior-dev` | one classifier row named above, with its test |
| D1, D2, D3 first builds | `reverse-engineering` | each has screens nobody has digested or read, and the digest comes off the game's own capture |
| each later step of D1, D2, D3 | `junior-dev` | the screen is read by then; the step is a port of a named routine |
| B5 | `junior-dev` | named on the Save As matrix's ticket |
| every run in section 4 | `emulator-runner` | a finished driver, a step list, a named reading, one boot, a budget; it reports observations and interprets nothing |
| the two Amiga screen reads (a second member's sheet in Pool, Magic > Display keys) and the DOS `items`, `display`, `rest` and `join` bars | `reverse-engineering` | screens read for a driver, not measurements |
| reading a run's result against a ticket and closing it | the root, after the finding is on the issue | the ticket's own plan says what accepts |

An `emulator-runner` handed a driver that cannot do a step hands the run back
with the evidence so far and what the driver would have to do; that is the
escape hatch, and it is where a new step gets its screen read.

## 8. For Donald

Nothing here waits on a decision of his. Three things he will be told once
the runs have been made, each in player terms and none a choice:

* the DOS range on Prayer's penalty to monsters, once the Prayer runs' run
  1b is in;
* whether C64 Pool's combat Prayer favours the monsters (the polarity run
  named in Part D read (b) of the Detect Magic runs' ticket), which decides
  only which side a converted row favours;
* what the Silver Blades opening gives a converted party that leaves the
  starting treasure, once the opening-scene runs resave.

The joined-scroll chooser and the tooltip for a greyed field are interface
text and stay where their tickets left them; no run above depends on either.
