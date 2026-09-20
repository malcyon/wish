# c64

Tests for the C64 side: the driven-session code under `tools/c64/`, the memory map and screen readers, and the checks that read a C64 save.

| file | purpose |
|---|---|
| `test_arrivalscene.py` | Checks that `Session.begin_adventuring` plays through an arrival scene to the world bar, on a fake session driven by a script of bars. |
| `test_bamsweep.py` | Checks the byte-range comparison of `tools/c64/bamsweep.py` on buffers built here, and that its fixed table matches the documented layout. |
| `test_c64addprobe.py` | Checks that `tools/c64/c64addprobe.py` refuses a run with no save or no disks before it claims an emulator slot. |
| `test_c64nametable.py` | Checks the six places `GEN` touches the `+$C00` name table of a C64 save, the filename prefix it uses, and that Pool of Radiance has no such table. |
| `test_c64outdoor.py` | Checks that `outdoor_request` in `tools/c64/c64outdoor.py` builds a buffer that reads as a party set out on the requested travel window. |
| `test_c64status.py` | Checks that a character's status, out-of-play flag, combat side, quickfight bit, share and control byte cross between a DOS record and a C64 one in both directions. |
| `test_c64u.py` | Checks the arguments `tools/c64/c64u.py` builds and the rules it enforces through its runner seam, with no C64 Ultimate on the network. |
| `test_c64ucompare.py` | Checks the masks, exclusion list and counting `tools/c64/c64ucompare.py` uses to decide whether two memory dumps disagree. |
| `test_c64uhang.py` | Checks that the BASIC reproducer `tools/c64/c64uhang.py` builds tokenizes to the bytes a C64 makes and that its `.d64` round-trips. |
| `test_c64uload.py` | Checks the hang verdict of `tools/c64/c64uload.py`, which reads a moving jiffy clock and not a `$DD00` value. |
| `test_coldread.py` | Checks what Curse and Silver Blades say about themselves in their own disks: per-race trait seeds, item tables and cited overlay addresses. |
| `test_d6502.py` | Checks the 6502 disassembler against encodings assembled by hand from the published opcode table, with no disk needed. |
| `test_driver_logs.py` | Checks that the driven-run tools' `Log` keeps a first run's file, survives a dead console and tears its slot down on `SIGTERM`. |
| `test_dualclassagain_stage.py` | Checks that `dualclassagain c64` stages a title's disks with that title's own harness. |
| `test_inventorycheck.py` | Checks the item-list reader and the edit, add and remove steps of `tools/c64/inventorycheck.py` on Curse and Silver Blades. |
| `test_laterbattle.py` | Checks that the `--goto` tour of `ssb_fight` charges a leg the steps it really took against its budget. |
| `test_laterthac0.py` | Checks that `tools/c64/laterthac0.py` locates the THAC0 tables of the later DOS titles and that every record reproduces from them. |
| `test_memory.py` | Checks that the C64 memory map has sane, uniquely named regions that agree with the constants the decoders use and the save-file ranges. |
| `test_outdoor_boat.py` | Checks that the driver names a boat landing's question instead of pressing at it as if it were a wall. |
| `test_outdoordrive.py` | Checks that the session driver reads the travel grid's status line and walks a party there, on a fake session that records its keys. |
| `test_partysheets.py` | Checks that a driven session reaches and reads every character's sheet, on a fake screen that behaves as measured. |
| `test_pursecheck.py` | Checks the money-box reader and the seven-purse edit steps of `tools/c64/pursecheck.py` on Curse and Silver Blades. |
| `test_recordsweep.py` | Checks the hit-finding of `tools/c64/recordsweep.py`, direct and indirect, on bytes built here. |
| `test_savecheck.py` | Checks that `tools/c64/savecheck.py` counts the figures a fight draws against the fight the engine is running, on hand-built battles. |
| `test_savecheck_icon_bank.py` | Checks that the `--icon` glyph read of `tools/c64/savecheck.py` goes through the RAM bank and refuses a VICE without one. |
| `test_savecheck_log.py` | Checks that a failed `savecheck` run keeps its log and writes the traceback before the photograph. |
| `test_savecheck_move_subbar.py` | Checks that `answer_bars` and `save_game` leave the dungeon's move sub-bar instead of reporting a walk as stuck. |
| `test_savecheck_resave_order.py` | Checks that `tools/c64/savecheck.py` resaves after every walked move and not before them. |
| `test_savecheck_shapes.py` | Checks that the `--icon` read of `tools/c64/savecheck.py` matches a figure's glyphs against `CHARPIC00` slot by slot. |
| `test_savecheck_walk_routing.py` | Checks that a walked step in `tools/c64/savecheck.py` routes through whatever the game puts up next, with or without `--route`. |
| `test_saveprompt.py` | Checks that the Silver Blades and Curse drivers recognise both of each title's save-disk prompts. |
| `test_screenbank.py` | Checks that the screen reader in `automap/screen.py` finds the screen from the bank and `$D018` instead of assuming where it is. |
| `test_session.py` | Checks that the session driver's console cannot stop a drive when it goes away, and that a closed disk copy is retried. |
| `test_session_boot.py` | Checks that `Session.boot` dismisses VICE's own error dialog while it waits and says what the screen showed when a wait runs out, on a fake display and screen. |
| `test_session_indoors.py` | Checks that `Session.indoors()` and the live-square read use each title's own address, so a Curse or Silver Blades party in a dungeon reads as indoors. |
| `test_session_paths.py` | Checks that `Session` builds its disk, side and log paths with `os.path.join` and not a hardcoded `/`. |
| `test_session_sheet_bar.py` | Checks that `Session.character_sheet` reads the sheet of a character who owns nothing, and the Silver Blades sheet, on the bar the game draws. |
| `test_session_walk_movebar.py` | Checks that `Session.walk_one` sends a direction key straight at an already selected move sub-bar and does not report the step blocked. |
| `test_sheetexit.py` | Checks that one interpreter reads every Gold Box command bar and that a sheet is left with the key the bar names. |
| `test_sideprompt.py` | Checks that a disk prompt is classified as a disk prompt and answered with a disk, not treated as a `PRESS` continue bar. |
| `test_trainerspells.py` | Checks each class's trainer spell step in each title against that title's own overlay and against `goldbox/levelup.py`. |
| `test_traitsave.py` | Checks the editor's own write path for traits on a C64 save: the record offset arithmetic, the one-byte diff, what it refuses to write and writing over a read-only destination. |
| `test_walkrun.py` | Checks that `tools/c64/walkrun.py` claims and refuses pool slots as asked, against a fake `Session` that launches nothing. |
