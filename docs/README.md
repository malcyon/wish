# Knowledge base

Reverse-engineering notes for Pool of Radiance (Commodore 64), supporting the
`goldbox/` library, the `wish` editor and the automapper.

| document | contents |
|---|---|
| [00-overview.md](00-overview.md) | the game's disks, how a session boots, overlay structure |
| [10-disk-format.md](10-disk-format.md) | 1541 D64 container: geometry, directory, sector chains, safe in-place writes |
| [20-character-record.md](20-character-record.md) | **generated** field table for the 580-byte record, with confidence levels |
| [30-savegame-layout.md](30-savegame-layout.md) | `SAVEDGAME0`/`SAVEDGAME1`, the `$100`×8 slot layout, the party header, the icon table and the roster blocks |
| [40-memory-map.md](40-memory-map.md) | live addresses and the game's own race/class/alignment/item tables |
| [41-memory-regions.md](41-memory-regions.md) | **generated** every named address, from `goldbox/memory.py` |
| [50-experiments.md](50-experiments.md) | append-only experiment log, including the failures |
| [60-goldbox-field-checklist.md](60-goldbox-field-checklist.md) | research pass: what fields *ought* to exist, and which online claims are unreliable |
| [70-driving-the-game.md](70-driving-the-game.md) | how to automate the game under VICE, and what does not work |
| [80-fields-wanted.md](80-fields-wanted.md) | the target field list for the editor, and what is known about each |
| [85-item-tables.md](85-item-tables.md) | **generated** word table and item-type table, read off a game disk |
| [86-spell-table.md](86-spell-table.md) | **generated** spell id -> name table, read off a game disk |
| [87-item-templates.md](87-item-templates.md) | **generated** every item on the game disks, for use as `template:` |
| [88-map-files.md](88-map-files.md) | **generated** the `GEO` map format and an inventory of all 29 files |
| [89-level-tables.md](89-level-tables.md) | **generated** experience thresholds, THAC0, hit dice and spells per class |
| [90-specimens.md](90-specimens.md) | every character record we have, with independently-known attributes |
| [95-wish-cli.md](95-wish-cli.md) | the `wish` save editor: usage, safety properties, what can be edited |
| [101-combat-view.md](101-combat-view.md) | the combat map, inside the automapper — **built**, on the automapper tab |
| [100-live-view.md](100-live-view.md) | a live read-only view of the running game — **built**, on the automapper tab |
| [99-one-window.md](99-one-window.md) | the `wish` window: the editor and the automapper in two tabs, one live connection, and the backend registry |
| [98-automap-notes.md](98-automap-notes.md) | typed note-taking on the automap — built |
| [97-editor.md](97-editor.md) | the PyQt6 character editor: the `.ui` form, the read-only rules, and the icon editor |
| [96-live-memory-automapper.md](96-live-memory-automapper.md) | the live automapper in `automap/`: how it reads a running game, draws the map and shows the party |
| [102-live-actions.md](102-live-actions.md) | buttons that change the running game — built |
| [103-quest-log-panel.md](103-quest-log-panel.md) | the Quest Log panel, drawn from the council's ledger at `$4AA6` — built |
| [104-debug-log.md](104-debug-log.md) | an opt-in local log for bug reports — built |
| [105-content-audit.md](105-content-audit.md) | what the repository must not carry, and the findings from the 2026-08-20 audit — all fixed, kept as the record |
| [106-releases.md](106-releases.md) | versioning, PyInstaller packaging and GitHub Actions — built, no tag pushed yet |
| [107-roster-and-notes.md](107-roster-and-notes.md) | the automapper's roster cards, note tooltips and the icons — built |
| [108-purge-history.md](108-purge-history.md) | removing the game's files from the git history — planned |
| [109-icon-choices.md](109-icon-choices.md) | which icon was chosen for each role, and where icons earn their place — chosen and wired |
| [110-combat-log.md](110-combat-log.md) | capturing the game's combat messages before it paints over them |
| [111-map-shading.md](111-map-shading.md) | darker walls and Dyson-style hatching |
| [112-test-harness.md](112-test-harness.md) | two fixed test-harness faults: the suite opening real windows, and an intermittent findChild segfault |
| [114-party-strength.md](114-party-strength.md) | what makes a random encounter bigger, term by term |
| [113-world-map.md](113-world-map.md) | the overland travel map, which is the combat engine on other data |
| [115-review-the-scripts.md](115-review-the-scripts.md) | the ECL script reading, closed undone on 2026-08-31: what the decode had reached, what a rebuilt decoder would have to match, and the one item on its list that needs no decoder |
| [116-second-game.md](116-second-game.md) | Curse of the Azure Bonds: the same 580-byte record, what differs, and the import routine that proves it |
| [117-save-conversion.md](117-save-conversion.md) | converting characters between the DOS and C64 versions — the converter is written and `File > Import`/`Export` are wired, behind `WISH_EXPERIMENTAL_DOS_IMPORT`/`WISH_EXPERIMENTAL_EXPORT` |
| [118-debug-mode.md](118-debug-mode.md) | `WISH_DEBUG=1`, Fast Travel, and what an area change actually is — built |
| [119-test-party.md](119-test-party.md) | getting a levelled, varied party for the specimens still wanted |
| [120-curse-testing.md](120-curse-testing.md) | testing the second game |
| [121-silver-blades.md](121-silver-blades.md) | Secret of the Silver Blades, the third title |
| [122-release-testing.md](122-release-testing.md) | what a release has to pass before it goes out |
| [123-parallel-sessions.md](123-parallel-sessions.md) | running several agents in one tree without collisions |
| [124-amiga-port.md](124-amiga-port.md) | porting a C64 party into Amiga Pools of Darkness: the `.pc` record, decoded by writing one and reading the sheet |
| [125-bug-notes.md](125-bug-notes.md) | the bugs no player sees, our own misreadings, and the community rumours |
| [126-forum-findings.md](126-forum-findings.md) | what the Gold Box forums have that we do not — playtester mode, DOS area tables, tooling |
| [127-community-formats.md](127-community-formats.md) | the community format spreadsheets: saving throws solved, the DOS record against ours |
| [128-guide-and-scripting.md](128-guide-and-scripting.md) | the DOS guide and the Unlimited Adventures files: the GBVM address list, the area names, the ECL semantics |
| [129-one-binary.md](129-one-binary.md) | folding `wish-cli` into the one `wish` executable — built |
| [130-preferences.md](130-preferences.md) | `File > Preferences…` (`Ctrl+,`): where the game disks are, which live backend, the debug log — built |
| [131-fastloader.md](131-fastloader.md) | whether answering the fastloader prompt Y or N changes anything — measured; it does not |
| [132-logo.md](132-logo.md) | the app icon: game-icons.net's `pointy-hat` (Lorc), generated from `ui/icons.py` — `hat-wizard` was the original stand-in and is superseded, `#167 (Replace the remaining Font Awesome icons with game-icons.net ones)` — built and wired |
| [133-active-effects.md](133-active-effects.md) | editing active effects: the `SAVEDGAME0` arrays distinct from the record's traits, and what the UI to edit them would need — planned |
| [134-commissions.md](134-commissions.md) | the council's ledger, its progress markers, the offer board and the byte two scripts share |
| [135-levelling.md](135-levelling.md) | what the training hall writes, routine by routine, and the button that does it without walking there |
| [136-condition-badges.md](136-condition-badges.md) | the nine condition badges — drawn on a roster card for a spell that landed on one character and on the automapper's bottom strip for one that landed on the whole party — which effect ids each covers, and what all ten game-icons.net glyphs measure at 13 px, including the one that draws nothing there |
| [137-wilderness-automap.md](137-wilderness-automap.md) | why the automapper is blank outdoors, and what to draw the terrain with |
| [138-multiple-games.md](138-multiple-games.md) | fast travel for more than one Gold Box title: what is per-title today, what data the other games have, and the dialog |
| [139-per-title-validation.md](139-per-title-validation.md) | every shipped feature against every title we claim: what is verified, what refuses, what does not work |
| [140-loaded-files-cache.md](140-loaded-files-cache.md) | the 25-slot loaded-files cache at `$4BC0`: which file kind each slot names, where each loads, and the two entries a converted save actually needs |
| [141-dos-savegame.md](141-dos-savegame.md) | the 13137-byte DOS `SAVGAM?.DAT` mapped: header byte, sparse VM word array, the ECL text buffer (live on load — write 7 of the recipe for moving a save to a new area), square and party size, and the recipe for writing a save that survives `Load3DMap` in its new area. Also the container in the other three titles, including Pools of Darkness' 1364-byte `SAVGAM?.PTY` — a **byte-wide** ECL variable array, variable *N* at file offset *N*−1, read out of the writer in `GAME.OVR` — and the character record's combat tail, `0x10C`-`0x10F`, which is the status, an active flag, a hostility flag and the quickfight flag rather than the constant it was taken for |
| [142-dosbox-x-debugger.md](142-dosbox-x-debugger.md) | the DOS side's answer to VICE's binary monitor: a DOSBox-X built with the debugger, driven unattended over a pty, the memory reads, watchpoints and breakpoints it does and does not give, and the harness `tools/dosboxx.py` that hides its four traps |
| [143-winuae-debugger.md](143-winuae-debugger.md) | the Amiga side's answer: WinUAE's console debugger driven from Linux over the Windows VM, why stock WinUAE has no GDB server however much uae-dap suggests it does, `S`-to-a-file as the read path, the built-in trainer search as the way to find a live address, and what a `WinuaeTarget` would cost |
| [144-decoding-a-new-title.md](144-decoding-a-new-title.md) | the method for a title nobody here has opened: which Pool of Radiance facts may be assumed and which must be re-measured, the order of attack cheapest first, the recipe for finding live data whose addresses are unknown, the confidence discipline, and the twenty-step checklist |
| [145-dos-decode-kit.md](145-dos-decode-kit.md) | a stranger's MIT-licensed DOS reverse-engineering kit read against our tables: the ECL bytecode proven to be the same bytes on both ports, the `88 13` header word, the GEO door slice, the DOS byte they misread as a class group, and the `GAME.OVR` overlay map we do not have |
| [146-unified-ui.md](146-unified-ui.md) | the plan for one `wish/window.ui` holding the whole application layout, so Qt Designer shows the window a user sees: what gets inlined and pre-created at maximum capacity, what stays a separate dialog, and the standalone entry points it drops |
| [147-combat-rolls.md](147-combat-rolls.md) | what the game rolls when somebody attacks: the generator, the d20 at `$2B10` with 20 stored as 100, the number to beat at `$A4F0` and the damage at `$A4F8`, all readable by ordinary polling, plus the five readings that do not work |
| [148-d6502.md](148-d6502.md) | making `tools/d6502.py` trustworthy: the `$F6` table bug it shipped with (`INC $nn,X` printed as `SBC $nn,X`), fixed under a hand-built regression suite, plus the capstone sweeps that prove nothing else disagrees and the check that the bug never touched `docs/147-combat-rolls.md` |
| [149-driving-a-dos-fight.md](149-driving-a-dos-fight.md) | answering an encounter and finishing a fight under DOSBox with no debugger and nothing reading a word off the screen: what `QUICK` really does (one keypress per combatant, not one per fight), the nine screens a fight puts up and the digest each is known by, and the four things that are not true here -- `ink` reads every combat bar the same because the paper is grey, no bar in a fight has a fixed digest because they all have variants, the picture never holds still so `settle()` must not be called, and the command bar does not change when a turn passes |
| [150-departing-prologues.md](150-departing-prologues.md) | what a fast travel skips when it enters `NEWECL` at `$2034`: all seventy-nine exits in the thirty area scripts, read statement by statement, and the addresses each prologue writes graded against what `newecl_writes` puts right. Most of it is the party's own journey and skipping it is correct; three entries are not, and one -- `SAVE 255, [$6DC9]` -- is settled here as costing nothing |
| [151-quest-flags.md](151-quest-flags.md) | **Generated.** Every reference the thirty area scripts make to `$4A00`-`$4AF8`, the page the game records what the party has done on: which script writes each byte, what values it writes, how many instructions read it, and whether a printed speech sits in the block that writes it. 179 of the 217 persistent bytes are named and 1415 operand references counted, which is what `goldbox-bugs.md`'s dead-flag entries rest on. `tools/eclflags.py doc` rebuilds it; the lost `work/reports/quest-flags.md` is what it replaces |
| [152-commodore-manuals.md](152-commodore-manuals.md) | The three original Commodore manuals on this machine -- the C64 User's Guide, the Programmer's Reference Guide and the 1541 Disk Drive User's Guide: edition and printing off each title page, which of the three has a text layer, the section and page for everything they are the authority for, the PDF-to-printed page offsets, and the one place a path to them is written down. They are not in the repository and must never be. |
| [160-why-these-rules.md](160-why-these-rules.md) | The incidents behind this project's working rules, moved here when `CLAUDE.md` was split under `#208 (Split CLAUDE.md into .claude/rules, so 21,800 tokens do not load before every task)` so the rules could be stated briefly without losing the reason they exist. Eighteen headings matching the rule files: what was done, what it cost, when, and Donald's own words where they settled it. Read it when a rule looks arbitrary -- most of them were paid for. |
| [161-c64-ultimate.md](161-c64-ultimate.md) | The C64 Ultimate on Donald's desk as a second, independent reading of the machine: what the device and its `c64u` CLI are, and the four hardware behaviours that decide how a dump off it is read -- DMA follows the CPU's current banking so a dump cannot say which bank state it was taken in, `$00`/`$01` read the RAM under the 6510 processor port so banking cannot be set over DMA at all, VIC colour registers read back with their unused top bits set (`$D020` is `FE`, not `0E`), and a DMA write persists only where nothing else drives the address. Everything needing the machine itself -- the read rate, whether `sendkey` can drive the game, whether the Ultimate agrees with VICE on any structure -- is listed as UNKNOWN with the experiment that would settle it. `tools/c64u.py` is the wrapper; the debug stream is blocked on an Ethernet cable. |
| [162-spc-permanence.md](162-spc-permanence.md) | What the DOS engine itself uses to decide a `.SPC` effect record is permanent: the sixteen-bit duration at bytes 1-2 and nothing else, read out of `GAME.OVR`'s expiry routine and confirmed under DOSBox-X. `add_affect`'s five arguments name the record's bytes (byte 4 is a flag, not payload), every call site is tabulated by the shape it writes -- racial `00 00 FF 00`, item-granted `00 00 0C 00`, strength item `00 00 vv 01`, a cast spell's real minutes -- and the three Amiga item specimens match those shapes byte for byte. Carries the provenance test that falls out of it: a `00 00 FF 00` record with an id outside the twelve the engine writes that way was not written by the engine, which is how SILAS's Detect Magic is shown to be an editor's work rather than a counter-example. |
| [163-dos-vm-address-map.md](163-dos-vm-address-map.md) | The DOS saved game's 5120-byte variable array is the ECL VM's memory at the VM's own addresses -- `$4900`-`$4CFF`, then `$6B00`-`$6EFF`, then `$9700`-`$98FF` -- read out of the VM's address classifier in `GAME.OVR`, which is what places every word `141-dos-savegame.md` could not name. Settles `#218 (Three live regions of the DOS saved game are named but not understood)`'s three regions: `$6DD2`/`$6DD3` are the rest-interruption interval and chance each area script writes on ENCAMP and the rest loop reads; `$6E7A`-`$6E7C` are the overland script's loop registers, with the whole band table reproduced from nine bytes of `ECL1A`; file bytes 12804-12805 are `$C04E`/`$C04F`, the wall ahead and the square's attribute out of the `GEO` planes. Both writes watched under DOSBox-X, the DOS-vs-C64 two-byte patch in the Slums script that makes the DOS Slums check a rest at all, and the leads not chased. |
| [164-ssb-spell-slot-block.md](164-ssb-spell-slot-block.md) | Silver Blades' 28-byte spell-slot block is `array[0..3, 1..7]` indexed by the spell table's class byte; class 2 is vacant in this title, so `0x140`-`0x146` is zeroed by the engine and never added to. Read out of `GAME.OVR` for `#222 (Silver Blades' fourth spell-slot array is zero in every state anybody can create)`, with the same block read on Curse, Gateway, Pools of Darkness and Treasures for comparison. |
| [169-dos-combat-side.md](169-dos-combat-side.md) | DOS character-record `0x10E` is the combat side -- 0 the party's, 1 the enemy's -- read out of `GAME.OVR` and the resident `START.EXE` for `#235 (Two unattributed DOS byte ranges in the combat tail are dropped converting to C64, and nobody knows what they hold)`: the per-side count at `ds:0x6814`, the victory test, the target picker, the `Attack Ally:` betrayal rule, Animate Dead, and the party-panel colour that draws a side-1 name yellow, checked in the running game. Carries the DOS engine's own script-field accessor, which reads and writes C64 record `0x10C` as `0x81` hostile / `0x80` quickfight / `0` over DOS `0x10E` and `0x10F` -- the conversion table for the last byte of the combat tail -- and the C64 save sweep that agrees with it. |
| [170-c64-identity-pair.md](170-c64-identity-pair.md) | The C64 side of the DOS identity byte: record `0x0E6`-`0x0E7` is drawn from the generator by `GEN` at creation and read by nothing in 589 files, the add screen refuses a duplicate by name alone (`GEN $1897`), and Curse and Silver Blades never write the pair -- so DOS `0x0AB` has a home at `0x0E6` and a C64 Pool of Radiance record can give it back. Also where `0x0E3` was found to be the strength-adjustment flag (`#277 (A DOS character converted to the C64 loses the strength bonus to hit and damage, because 0x0E3 is written zero)`). `#258 (The C64 side of 0x0AB is unnamed, so the conversion drops it with no issue behind it)` |
| [171-c64-trait-slots.md](171-c64-trait-slots.md) | What a C64 trait slot is and what the engine does with an id in one, read out of Pool of Radiance's overlays and watched under VICE for `#252 (Does a C64 trait slot apply an item-granted effect id, or only the ones its own READY routine wrote?)`: one byte of persisted state meaning "has effect N", with no owner, duration or provenance, applied wherever `LIBRARY $4027` is asked -- which is the twenty combat check lists under the I/O area at `$DB7A` that a literal census could not see, the surprise check, and any script. READY writes the id and nothing else; load never re-derives a slot from a readied item; 61 is on the spell-damage and saving-throw lists and its handler zeroes fire-spell damage, while the C64's own Ring of Fire Resistance template grants nothing. Ends with what `#232 (An item-granted effect is dropped on the way through the neutral record, with no report)`'s C64 writer has to write: the id in a free slot, and `+14`/`+15` on the converted item so the engine revokes and re-grants it itself. |
| [172-curse-trainer.md](172-curse-trainer.md) | Curse of the Azure Bonds' trainer, driven and watched for `#18 (Measure Curse's trainer so Level Up works there)`: five level-ups in one VICE session, each diffed across the character record, and 75 derived fields reproduced out of `goldbox/levels.py` and `goldbox/levelup.py` with no mismatches. Carries the C64 hall gate `$7EA8` and the menu mask at `GEN $12AF` that DOS keeps at `SAVGAM+0xD51`, the six differences from Pool of Radiance -- one press raises **every** ready class at 1000 gp each, `UNABLE TO ADVANCE` rather than `LOW EXPERIENCE OR WRONG CLASS`, a refused training costs nothing, the paladin's turning level, `GEN $2515` handing a paladin trait 45 and a ranger trait 134 at every recompute, and no spell capacity ever written -- the dwarf whose stored saving throws move `GEN $0F19` from PROBABLE to CONFIRMED, and the first dual-classed Curse character anybody has, written by `HUMAN CHANGE CLASS` and diffed byte for byte. |
| [173-carrying-limits.md](173-carrying-limits.md) | How many items one character can hold, per port and per title, for `#52 (File ▸ Import and File ▸ Export for every direction the library supports)`'s decision 13: **sixteen everywhere**, enforced by one routine that appears in all eight DOS and Amiga executables -- it recounts the item chain, compares `item_count` against 15, and shares its refusal flag with the weight test, so the player is told only `Overloaded`. Carries the per-title offsets, the two commands that disappear at sixteen rather than refusing (`HALVE`, and a gem's `Keep`), Pools of Darkness's exemption for an item already carried, and the engine-written boundary watched under DOSBox -- fifteen accepts, sixteen refuses, and the refusing character is the lighter of the two. Also that the ceiling is on **acquisition only**: a `.ITM` an editor lengthened to twenty loads, draws across two pages and saves back intact. |
| [174-combat-figures-in-the-running-game.md](174-combat-figures-in-the-running-game.md) | How a party's combat figures are read off the running C64 and compared against the eighteen screen codes a save holds, for `#184 (A converted combat icon's colours are proven in the game and its shapes are not)`: the engine renumbers each combatant into its own run of nine codes in a combat character set at `$D000`, which is RAM under I/O and needs the monitor's `ram` bank, and the bitmaps it copies there are `CHARPIC00`'s for the icon's own codes. Carries the window geometry, the reason `$A0` is not the reversed space here, the mirror rule for a figure facing the other way -- multicolour cells reverse in pixel pairs, hi-res cells bit by bit -- and the 405 readings of one fight in which every party figure named exactly one of 32 candidates. Ends with the one thing unproven: an icon's second nine codes have never been on the screen. |
| [175-silver-blades-save-conversion.md](175-silver-blades-save-conversion.md) | What a DOS-to-C64 Secret of the Silver Blades conversion writes and where the two ports disagree, for `#193 (Convert a Secret of the Silver Blades DOS save into a C64 one, which the importer refuses today)`: the container is Curse of the Azure Bonds' under the name `SAVEDBASH`, with three header rows changing hands, a quest-flag page that runs five bytes further because this title keeps its wall triples elsewhere, and a name table that may be keyed by marching order rather than by slot. Carries the four faults the running game found -- a lower-case DOS name drawing as `G59 $% V!,/)3` because the C64 has no lower case, a DOS ranger arriving as a paladin because the two share bit 6 on DOS and not on the C64, a 67-byte item the converter refused, and five flag bytes zeroed -- the twelve items read back by name off the `ITEMS` screen, and the memorise screen offering a magic-user 9 exactly four first-level slots out of six presses, which is what makes the missing slot array a field the destination derives. Ends with the three things still wrong, including a converted human arriving with sixty feet of infravision. |
| [176-changing-class-twice.md](176-changing-class-twice.md) | Whether a Gold Box character can change class more than once, for `#256 (The neutral record has nowhere to put a dual-classed character's former levels)`: **no**, in all four ports asked, and each refuses by reading the field the first change wrote -- the C64's `LDA $7CBA / BNE` at Curse `GEN $2393` and Silver Blades `GEN $1F88`, answering `UNABLE TO CHANGE CLASS.`; DOS Curse dropping the menu line for the selected character at `GAME.OVR 0x20243`; DOS Silver Blades keeping the line and refusing inside the command at `0x3CDAF`. Carries the six-character DOS Curse sweep in which the line is missing for the one dual-classed human and the one elf and present for the other four, the Silver Blades pair one action apart where PAINE gets a class list before and nothing after, the single store to `$7CBA` in each C64 title and the regain routine `GEN $20A3` that does not clear it, and the census of 62 DOS records with a former array in which none holds two. Ends with the C64 replay that could not be run, and why. |
| [177-a-load-that-goes-wrong.md](177-a-load-that-goes-wrong.md) | What was measured when Pool of Radiance stops on Donald's C64 Ultimate, for `#286 (Pool of Radiance on the C64 Ultimate sometimes hangs on a disk load)`, and what it does **not** say -- four candidates stay live, and one machine cannot separate a firmware defect from a fault in that machine. The reproduction is the opening demo rather than his walk to a stable: boot `POOL1.D64`, answer `Y`, touch nothing, and it stopped three times in three runs in six to ten minutes each, once frozen with an interrupt asserted and never acknowledged and twice dropped out to a BASIC warm start with `READY.` printed into the game's own screen buffer. Carries the test that tells a hang from a load -- six seconds of legitimate quiet against eighty of silence -- the `$DD00` readings idle, loading and hung, the proof that neither hang put a bad byte anywhere looked at, the loaded-files cache naming three different places in the game, and the chain from a Short Bow +1 through `ITEMFILE29` and `ECL14`'s `TREASURE` operands to `GEO14` squares (5,2) and (6,2). Ends with the loop nobody could name, and why no route on the device can name it. |

`20-character-record.md` is generated — run `python3 tools/gendocs.py` after
changing `goldbox/layout.py`. `85-item-tables.md` and `86-spell-table.md` are generated too — run
`python3 tools/genitems.py`, `python3 tools/genspells.py`,
`python3 tools/gentemplates.py` and `python3 tools/genmaps.py`, which need a
game disk. Everything else is
written by hand.


## How the code is laid out

Split along the **packaging** boundary, so a build takes the app without
dragging in throwaway discovery scripts.

| package | what it is |
|---|---|
| `goldbox/` | the file formats: D64, the 580-byte character record, the save games, the item and spell tables. **Transport-free** — no sockets, nothing that knows a machine is running |
| `editor/` | the PyQt6 character editor, over `goldbox/` alone |
| `automap/` | everything that reads a *running* machine, quarantined here so the first decision below is structural rather than a convention |
| `wish/` | the one window: two tabs, the single shared live connection, the backend registry, and `File > Preferences…`. See [99-one-window.md](99-one-window.md) and [130-preferences.md](130-preferences.md) |
| `ui/` | drawing code both the editor and the map need, owned by neither |
| `designer` | a launcher script for Qt Designer, opening `wish/window.ui` |
| `packaging/` | the PyInstaller entry points and the Windows console-stream repair |
| `tools/` | discovery scripts — dumps, diffs, generators, experiment runners. `tools.wish` is the body of the `wish export`/`wish import` subcommands and `tools.genui` runs at window startup, so the package ships even though the rest of it is scaffolding; [129-one-binary.md](129-one-binary.md) is the CLI folded into `wish` itself |
| `work/` | scratch disk copies — `.gitignore`d, and where every disk image belongs |

**Two decisions shape all of it, and both still hold.**

1. **The editor is a file tool with zero emulator dependency.** It opens a
   `.D64`, edits the save, writes it back, and never talks to VICE. `editor/`
   imports nothing from `automap/`, `goldbox/` stays transport-free, and the whole
   file path works on a machine with no emulator on it.
   `tests/test_wish.py` asserts both halves: the editor tab is never handed the
   live target, and no file under `editor/` mentions `automap`.
2. **Live memory is a discovery technique, not something the editor promises.**
   A watchpoint on "whatever stores to the strength byte" beats reading
   disassembly, so the project reads the running game heavily while reverse
   engineering. That grew into the automapper, which *is* a shipped feature —
   and it lives in `automap/` precisely so the first decision survives it.

`goldbox/layout.py` is the single source of truth for the record: a declarative
table, every field carrying `CONFIRMED` / `PROBABLE` / `GUESS`, asserting at
import that all 580 bytes belong to exactly one entry.
[20-character-record.md](20-character-record.md) is generated from it, so the
documentation cannot drift from the code — and it has **exactly one owner at a
time**, because several agents appending to it independently would fragment the
schema and reintroduce the drift it exists to prevent.

## Where things stand

**Settled**

* D64 container read/write, including byte-exact in-place rewrites.
* `SAVEDGAME0` is a verbatim image of `$4900`–`$64FF`: a party header, a
  combat-icon table at `$4BE0`, **12 character slots of `$100`** at `$4D00`, and
  an item area from `$5900`. Slots 0–7 are the party and 8–11 are used only in
  combat; the roster and the icon table both count **eight**, and the game
  itself refuses a seventh *player* character — so the rule is at most six
  player characters and at most eight in total, the remaining two being
  NPC-only.
* `SAVEDGAME1` opens with **eight 32-byte roster blocks** filling `$8300`–`$83FF`
  exactly. They hold the derived combat numbers the character record does not:
  armour class, THAC0, current hit points, movement and the damage bonus.
  Three bytes at `+0x03`–`+0x05` are still unread.
* **The two files divide three ways, not two:** `SAVEDGAME0` holds the twelve
  character slots *and* a header carrying the party's place in the world;
  `SAVEDGAME1` opens with the roster of derived combat values. Base values live
  in the record, current ones in the roster — THAC0, movement, hit points and
  armour class each exist in both. See
  [30-savegame-layout.md](30-savegame-layout.md).
* **The party's position** — x, y and facing in the `SAVEDGAME0` header, with
  the previous square and the game clock beside them.
* **The page at `$5500`** — **slot 8**, the first of the four slots combat uses.
  After a fight it holds the monster, byte-identical to its `MON*` file bar two
  derived bytes. It was long read as a scratch "staging page"; it is not
  scratch.
* **Spells** — the spellbook at `0x078`–`0x07E` (what a character knows) and the
  memorised list at `0x020` (what is prepared), both readable by name.
* **Most of the record is still unread.** The current count lives in
  [20-character-record.md](20-character-record.md), which is generated from
  `goldbox/layout.py` — a number retyped here goes stale the moment a field is
  named, and has. Name, six abilities,
  exceptional strength, race, class, class bitmask, sex, alignment, age, five
  saving throws, movement, infravision, thief skills, hit points, all seven
  money types, experience, character level, per-class levels, the portrait
  head and body, the size flag, and the memorised spell list.
* **Inventory format** — 16-byte item records, verified against the AD&D 1st
  edition price and weight tables. Names are three word indices into the game's
  own table; cost is 16-bit; byte `+4` is the magic bonus; byte `+0` indexes a
  second table, `ITEMS`, holding damage, armour class, hands, range and class
  usage. Items can be edited, added and removed.
* **Combat icons** — 18 screen codes plus 18 colours, independently editable.
* **The game accepts externally edited saves.** Thirteen fields were changed at
  once and every one appeared in the game. No checksum, no validation.

**Working tool**

`tools/wish.py` exports a party to YAML and imports an edited YAML onto a new
disk, losslessly. See [95-wish-cli.md](95-wish-cli.md).

**What the tool can now do**

`wish` reads and writes both save files. The `SAVEDGAME1` roster blocks are
editable, so armour class, THAC0, current hit points, movement and the damage
bonus can all be changed — as can character level, which is kept in step with
the per-class array, and the class code, which is kept in step with the class
bitmask.

**The roster blocks are now proven writable.** MALCYON's armour class and current
hit points were edited to 1 and 11 — a two-byte change to `SAVEDGAME1`, with
`SAVEDGAME0` byte-identical — and the game showed `AC 1` and `HITPOINTS 11` on
both the party list and the character sheet, then wrote the same bytes back when
it saved. So the game reads that cache and does not recompute over it.

**The caveat that still stands:** everything *else* found since the thirteen-field
edit is written on the strength of reading it correctly, which is not the same as
having been written back and confirmed in game.

**Open**

* **The level-drain pair as a specimen** — `0x0A1`/`0x0A2` are read and named
  from the drain and restoration routines, but no character of ours has been
  drained in play.
* **Roster `+0x03`–`+0x05`** — read as per-level spell counts, retracted when
  one save contradicted it, and since found to agree with two saves *level by
  level* while the contradicting page turns out to be a stale cache. Still
  unknown, but for a better reason than before.
* **How the C64 applies racial modifiers to thief skills.** The progression
  table is the DOS one and a dwarf thief matches base plus the published dwarf
  row in all eight columns; a gnome, a halfling and a half-elf do not, and no
  dexterity adjustment reconciles them. The C64's own modifier table, wherever
  it is on the disks, would settle it in one read.
  See [127-community-formats.md](127-community-formats.md).
* **Whether `spells_memorised` is 21 bytes rather than 16.** DOS allots 21 and
  21 is the C64 ceiling; the most anybody has used is 13, so nothing we hold
  contradicts either width.
* **Whether `0x100` is a status enum.** Four sources now disagree about it and
  the newest weakens rather than strengthens the case; `roster_in_use` stays
  PROBABLE. One specimen reading other than 1 settles it.
* **The save path itself has never been disassembled.** `LOAD/SAVE` is on the
  disk and the tooling for reading it is proven; nothing has ever needed it,
  because a save is a verbatim memory image and diffing two of them answers
  more than the routine would.
* Most of each record remains unidentified; see
  [20-character-record.md](20-character-record.md) for how much.
  `SAVEDGAME1` past its first page is not open at all — it is resident code
  and a graphics buffer, not save data.

**Closed since this list was written**

* **Character traits** are `0x0AD`–`0x0B6`, ten trait slots holding codes from
  the same namespace as the save's active effects — but not that list
  seeded per race — which is also what `0x0AD` is.
* **Item byte `+5`** is a signed saving-throw bonus. Every byte of the 16 is
  read.
* **`0x0A0` is the current level**, with drain state in its own pair at
  `0x0A1`/`0x0A2`; there is no "highest level attained".
* **`0x073` and `0x0EB` are different fields**, proved by building a save where
  they disagree: `0x073` is what the sheet prints, `0x0EB` is what the game ANDs
  against an item's class-usage byte.
* **The saving throws are derived by a known rule** — the class table row for
  the character's level, best number in each column across every class held,
  minus the constitution bonus for a dwarf, gnome or halfling. 78 of 79 records
  satisfy it exactly.

**No longer abandoned**

Both of these were written off and both now work; see
[70-driving-the-game.md](70-driving-the-game.md).

* **Watchpoints via the VICE monitor** — they do work, and they settled the
  character-creation question in one run. The trick is to keep the connection
  open and `resume()` rather than close it: VICE re-enters the monitor on the
  connection that was live when it stopped.
* **Driving the game to create characters** — solved. The name prompt rejects
  any byte `>= $5B` and `xdotool` was sending capitals as Shift+letter, i.e.
  `$D7` for `W`. Type lowercase.
* **Disk swapping**, which blocked every experiment needing the game to read a
  disk we built — solved through VICE's *text* monitor `attach` command.
* **The roster blocks are writable.** An edited armour class and hit-point
  total appeared on the character sheet and survived a save, so the caveat
  above about `SAVEDGAME1` never having been written back is now discharged for
  the combat block.

## Two outside sources worth knowing about

Neither is one of our own controlled experiments, and both earned their place:

* **`npc_party.d64`** — a save found online with three PCs and five NPCs at
  levels 4 to 8. Better described as genuine play with one edited field than as
  "hacked": five of its eight records are the game's own `MON*` files and the
  one value that cannot have come from play is MAD MAN's saturated `$FFFFFF`
  experience. It bounded the roster at one page, settled character level, and
  seven of its eight records satisfy a saving-throw rule derived without them.
  See [90-specimens.md](90-specimens.md).
* **`poolce.d64`** — a listable 1989 BASIC character editor. Every offset it
  pokes matches ours, it carries the item name table and 162 complete item
  records, and the things its author could *not* find corroborate our layout.
| [178-turning-undead.md](178-turning-undead.md) | Where each port keeps a cleric's power to turn undead, and why a converted one arrived on the C64 unable to use it, for `#288 (A converted cleric or paladin arrives on the C64 unable to turn undead, because DOS keeps no turning byte and nothing computes one)`. The C64 gates the word `TURN` on record `0x0A4`: `COMBAT $09D9 LDA $6BA4 / BNE`, and the branch not taken clears bit 5 of the bar's command mask, which is the sixth of the eight words at `$1344` -- so a cleric holding zero is not offered the command at all, watched on one save with one byte changed. DOS keeps no such byte: `GAME.OVR:0x139CD` bands the cleric level out of `class_levels[0]` when Turn is pressed and reads `0x076` off the **target** as the matrix row, which is why DOS `0x076` turns out to be the C64's `turn_class` and not its `turn_power` -- corroborated by eleven undead monster records carrying the published AD&D rows. Carries Silver Blades' turning routine at `GEN $13A5`, one of `#89 (Silver Blades' trainer grants spells from a table, and goldbox/levelup.py offers them from a menu)`'s unread trainer inputs, and the census of 210 C64 records in which the only 23 disagreements are parties this project converted. |
| [179-loading-a-curse-save.md](179-loading-a-curse-save.md) | What Curse of the Azure Bonds' `LOAD SAVED GAME` does and the three separate faults that were making it refuse in a pooled session, all of which printed the same `UNABLE TO LOAD SAVED GAME.` (`#291 (A Curse save disk will not load through the game's own front end in a pooled session, so no C64 Curse party can be got in)`): `LIBRARY $3159` is a KERNAL `LOAD` with its name pointer self-modified into `$319F`, and `$401E` hands back the drive's own error number, so `$03F1` names the fault. 62 -- the save-disk prompt is drawn and taken by a second Return that `Session.select_bar`'s XTEST press left in the KERNAL buffer, proved by execute counts on `GEN $183A` and `$1F48`. 74 -- `Session.attach` did its waiting inside a monitor connection, which stops the machine, so the emulated drive never settled. 60 -- two of the five Curse specimens hold `SAVEAZURE` as an unclosed `*PRG`, type `$02` with no block count, and the drive refuses to open one. Carries the once-per-boot prompt gate at `GEN $182D`/`$03B4`, why a refusal leaves the question up rather than the menu, and the sequence that gets a party in. |
| [180-writing-a-later-dos-record.md](180-writing-a-later-dos-record.md) | What it took to make `goldbox.dos.write` build Curse of the Azure Bonds' 422-byte record and Secret of the Silver Blades' 439-byte one (`#299 (goldbox.dos.write builds only Pool of Radiance's record, so nothing can be converted to DOS for the later titles)`), which it did not before: it built 285 bytes whatever it was handed, so a C64 Curse party came back as six Pool of Radiance records that no Curse game could load. Holds the per-title width table -- ability pairs, a 100- and a 117-spell book, seven class-level slots in Silver Blades, five and seven spell-slot levels, and the 67-byte `.STF` item stride `#113 (Play DOS Curse far enough to save a party with items)` measured -- the round-trip counts (32 of 32 Curse, 39 of 44 Silver Blades, the five being MALACHITE's treasure-share byte), and the loop that puts the C64 engine in the middle of the measurement. Names `paladin_cures` from the Curse decompilation and from 8 paladins against 71 other characters across four record shapes, and says what is still missing: the container. `SAVGAM<slot>.DAT` is written for Pool of Radiance and for no other title, so the records are right and the DOS game cannot yet be pointed at them. |
| [181-curse-picture-buffer.md](181-curse-picture-buffer.md) | What the 1024 bytes at `+$1800` of a Curse `SAVEAZURE` are, for `#283 (What Curse keeps in the area map region at +$1800 is unread, and a conversion writes zeroes there)`: not map memory but `ANIMATE00`'s picture buffer at `$6300`, the decoded glyphs and colours of the picture in the view window at whatever animation frame it had reached when `ENCAMP > SAVE` took `$4B00`-`$67FF` in one KERNAL `SAVE`. Both engine-written specimens match a decoded frame of `PIC1D`, the camp scene, byte for byte (frames 1 and 3, so the 23 bytes they differ in are the fire flickering, not the walk), and all four Silver Blades specimens match `PIC3B` frame 0. Carries the decoder read out of `$6931`-`$6B09` and the `PIC` format it implies, the loader table showing nothing loads at `$6300` in Curse, a driven session in which nothing read the region before the engine's own zero-fill at `$6971` (so a conversion's zeroes are a measured zero), and the side finding that `CAMP` uses the roster page as scratch and rebuilds it before the save. |
| [182-amiga-por-in-the-running-game.md](182-amiga-por-in-the-running-game.md) | What Amiga Pool of Radiance does with character files our own code wrote, from four WinUAE runs on 2026-09-05 for `#105 (Write an Amiga Pool of Radiance character, not just a Pools of Darkness one)`. Settles the writer's last open question: the **ITEMS screen composes an item's row from `name1`, `readied` and the rest even though the node's 42-byte display line is entirely NUL**, and then writes the render back into it -- two nodes that went in NUL came out holding `Flail \0lail \0` and `Banded Mail \0Mail \0`, the current render followed by the tail of a longer earlier one, which is the exact structure the game's own shipped nodes have. Also: a six-character C64 party and a DOS character with items both loaded and drawn, a character owning nothing offered no ITEMS entry rather than a corrupt one, the engine's own re-save differing in 57 bytes of 1728 and every one of them a live pointer or a field it derives, `#191 (A converted dwarf loses his constitution bonus to saving throws)`'s dwarf effect records surviving intact, and the engine writing a name back without its space. |
| [183-the-two-rings-of-fire-resistance.md](183-the-two-rings-of-fire-resistance.md) | Why `#285 (The C64's Ring of Fire Resistance grants nothing, and Wish should repair it on conversion and on an editor save)` was filed against the game and belongs to us. Pool of Radiance's C64 disks carry **five** Ring of Fire Resistance records and four of them grant effect 61 -- `ITEMFILE1D` on POOL4, which DOS `ITEM4.DAX` block 29 matches byte for byte, and three readied on monsters in `MON32` and `MON56`. The fifth, in `ITEMFILE17` on POOL3, has `+14` and `+15` zeroed, and `load_item_templates` kept the first record it met for a name with POOL3 sorting first, so every reading of "the shipped template" -- and every ring the editor handed out -- was the dead one. Carries the census of all five records, `ECL65`'s power table showing `$81` and `$80` reaching the same grant handler, the emulator run in which three READY presses on the flattened ring move no byte at all, the 163-against-352 port comparison in which exactly two names disagree about granting (the other being LONG SWORD +2, whose working copy carries an alignment lock), and the `TREASURE` census that says no area script names `ITEMFILE17`. |
| [185-a-party-that-has-not-set-out.md](185-a-party-that-has-not-set-out.md) | Why a Curse of the Azure Bonds save can hold area 0 when Curse has no area 0, for `#301 (A DOS Curse save standing in area 0 is refused by the import, because no row of the area table names area 0)`. A player who forms a party and picks `SAVE CURRENT GAME` before `BEGIN ADVENTURING` writes one, and the two saved games the DOS archives ship are exactly that. No `ECL00` on any of the six C64 sides, no block 0 in `ECL1.DAX`-`ECL6.DAX` or `GEO2.DAX`-`GEO6.DAX`: 0 is the initialiser's value, not a place. The differential is one keypress -- area and map 0 to 1, facing north to east, the script buffer 12 non-zero bytes of 7700 to 7222 -- and the C64 holds the same 0 at its own party menu in nine boots. A C64 save that *names* area 0 sends the loader after `GEO00` (`$B7`/`$BB` at the disk prompt) with side 2 already in the drive, so converting the word through unchanged makes a save the player cannot start. Two negative results in eight boots: an all-`$FF` cache crashes `BEGIN ADVENTURING` whatever the area, and the disk-prompt patch that first looked responsible is not -- the same disk crashed with no patch at all. |
| [189-effect-97-from-the-code.md](189-effect-97-from-the-code.md) | What DOS Pool of Radiance's innate effect 97 is, read out of `GAME.OVR` for `#247 (Nobody knows whether innate effect 97 is racial or the constitution bonus)`: creation writes it on the race byte alone (`0x1A127`), and the handler it dispatches to (`0x112E5`, via the start-up-filled table at `ds:0x6828`) reads the character's constitution when a saving throw is rolled and adds `constitution * 2 // 7` on the wands and spell columns, 90 doing the same on the paralysis/poison/death column. So writing 97 from a race table cannot hand out a bonus nobody rolled. Names the C64-direction mirror of `#191 (A converted dwarf loses his constitution bonus to saving throws)`, filed as `#311 (A DOS dwarf, gnome or halfling converted to the C64 loses his constitution bonus to saving throws, because the C64 keeps it inside the five stored bytes)`. |
