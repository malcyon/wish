# amiga

Tests for the Amiga port: its filesystem, saved-game and character-record readers and writers, the tools under `tools/amiga/`, and the emulator routes in `automap/amiga.py`.

| file | purpose |
|---|---|
| `test_amiga.py` | Checks the Amiga character record against the offsets the character sheet drew, on probe records built here and on the `.pc` files of the player's own disks. |
| `test_amiga68k.py` | Checks `tools/amiga/amiga68k.py`'s jump-table resolution, PC-relative reference search and reloc annotation on Hunk executables built here. |
| `test_amiga_adf.py` | Checks that `goldbox.amiga_adf` reads every real disk clean and formats, writes and re-reads a blank one. |
| `test_amiga_savegame.py` | Checks the later-title Amiga saved-game reader, writer and fresh disk. |
| `test_amigaabilitypaircross.py` | Checks that a crossed Amiga Curse or Silver Blades ability pair keeps its permanent and in-force halves apart through `to_neutral_later`. |
| `test_amigaacceptance.py` | Checks that a failed WinUAE save probe leaves the published disk unchanged, keeps both fetched ADFs and its last screen, settles a capture on the emulator's crop, and that the lane session, the screen guards and the title description import without the runner. |
| `test_amigaacceptance_accept.py` | Checks the WinUAE probe's accept route, guards, interstitials, verdicts and evidence, and that SIGTERM still stops, fetches and releases. |
| `test_amigaacceptance_guest.py` | Checks that `run_recon` gives the same result events through a WinUAE-style and an FS-UAE-style lane, sends snapshot and restore steps through the guest, and that `--emulator` picks the lane and drops the audio-proof requirement for FS-UAE. |
| `test_amigaacceptance_journal.py` | Checks that a failing journal answerer subprocess puts its exit code and the last lines of its stderr, bounded, in the driver's `RouteError`. |
| `test_amigaacceptance_measure.py` | Checks the WinUAE probe's capture-only mode, per-state minimum waits, guard polling and configurable route with a fake clock and guest. |
| `test_amigaacceptance_poolrest.py` | Checks Pool of Radiance's camp `rest DURATION` and `display` steps, the after slot F a camp run that presses `D` saves to, and a fake camp run that lists the effects, rests and reads them gone from the game's saves. |
| `test_amigaacceptance_ssbsubstitute.py` | Checks that Silver Blades' `prepare --substitute` stages another tool's slot as C with its own letter recorded, blocks a slot that does not decode or a first member with nothing, and that its accept run skips the JOIN party's inventory check. |
| `test_amigaacceptance_staged.py` | Checks that the Silver Blades route accepts staged changes only in the four effect arrays of its pinned JOIN save, requires game disk 1 for its Save As output, and records active rows in the preparation manifest. |
| `test_amigaacceptance_stageplace.py` | Checks that `prepare --published-disk-one --stage-place` writes only the party square into working DF0's slot, records it in the manifest, and blocks bad values, outdoor, unset-out and unknown saves before any run folder exists. |
| `test_amigaacceptance_title.py` | Checks that the WinUAE probe runs a title description on synthetic ADFs and a fake guest, and blocks a description that could press a save key, swap DF0 or write after an unguarded screen. |
| `test_amigaacceptance_titles.py` | Checks the Pool of Radiance, Curse of the Azure Bonds and Pools of Darkness routes, including their keys, walk verdicts, preparation pins, imports and the cases where the CLI stops, plus exact published disk-one route letters and report validation. |
| `test_amigabackstab.py` | Pins what `tools/amiga/amigabackstab.py` reads out of each Amiga title's own executable, and that erasing a step of the regain arithmetic is blocked. |
| `test_amigabladesjournal.py` | Checks how `tools/amiga/amigabladesjournal.py` fits the game's character grid inside a desktop capture and rescales it, on synthetic frames. |
| `test_amigacanonical.py` | Checks that `screens.canonical` cuts FS-UAE's and WinUAE's own screenshots and any other exact replicated frame to the 720x568 crop, blocks a frame that is not exact, and leaves every kept WinUAE example crop unchanged with each guard rule still matching its example, and matches WinUAE's own Pool and Silver Blades frames against their rules. |
| `test_amigacontainercheck.py` | Checks the parts of `tools/amiga/amigacontainercheck.py` that decide what it says, on synthetic input, and that its two readers share no code. |
| `test_amigacursewheel.py` | Checks `tools/amiga/amigacursewheel.py`'s whole-number rescale of a WinUAE capture and that a machine without the private tables is told so. |
| `test_amigadrive.py` | Checks `tools/amiga/amigadrive.py`'s keys as Amiga raw codes, its pipe screenshot (frame written unchanged, guest failure line, 999-shot limit) and the settings a party walks on, through the command line the driver would send. |
| `test_amigaglobal.py` | Checks `tools/amiga/amigaglobal.py` finds a global's references and a routine's callers on an executable built here. |
| `test_amigaicons.py` | Checks the Amiga Curse and Silver Blades combat-icon art against DOS's own, off the player's disks. |
| `test_amigaindexedrefs.py` | Checks `tools/amiga/amigaindexedrefs.py`'s `d8(An,Xn)` indexed-site search and its `lea` base-within-reach search, on hand-built instructions in a synthetic hunk. |
| `test_amigajournalgates.py` | Checks the Silver Blades journal preflight against a fake private reader and that the grid fit ignores green text outside the emulator window, on built images. |
| `test_amigakeys.py` | Checks that every key the FS-UAE drivers send is in `tools/amiga/amigakeys.py` once, and its raw codes against the Amiga Hardware Reference Manual and WinUAE's `keyboard.h`. |
| `test_amigalaterproof.py` | Checks the party ordering and the mask of engine-recomputed bytes in `tools/amiga/amigalaterproof.py`. |
| `test_amigalaterslot.py` | Checks `tools/amiga/amigalaterslot.py` writes the name, count word and chain head the game's loader reads, on synthetic disks. |
| `test_amigalaterwindow.py` | Checks that an Amiga Curse or Silver Blades record's unnamed `field_83_87` bytes survive to Amiga and to DOS, on records built here and on the player's disks. |
| `test_amigalaterwrite.py` | Checks that the Amiga Curse and Silver Blades writer is the inverse of the reader, by round trip and against the engine's own re-saves. |
| `test_amiganamespaces.py` | Pins where `tools/amiga/amiganamespaces.py` finds each Amiga title's name-stripping routine and whether it reaches a record, checks its Pool of Radiance model against the names the running game saved, and checks every engine resave on the disks against the model. |
| `test_amiganodefields.py` | Checks `tools/amiga/amiganodefields.py` reports each effect-node byte the two later executables name and the byte nothing reaches. |
| `test_amigaparty.py` | Checks `automap/amigaparty.py` walks each title's party list and its item and effect lists in synthetic memory, keeps a fight's monsters out of the party, and stops on a looping, odd, stray or endless list. |
| `test_amigapipe.py` | Checks `automap.amiga.WinuaePipe` against a fake that answers the way the real guest was measured answering. |
| `test_amigapool.py` | Checks `AmigaTarget.fix` on Pool of Radiance's travel grid over synthetic memory built from the row's own fields, and the automapper following it. |
| `test_amigaporquickfight.py` | Pins Amiga Pool of Radiance's quickfight byte at record `0x111`, DOS `0x10F` under the shift map, through the reader and writer on records built here. |
| `test_amigaporsavegame.py` | Checks that the Amiga Pool of Radiance saved game is built from the source save, from the player's disks and specimens. |
| `test_amigaporsavegameboundaries.py` | Checks the Amiga Pool of Radiance container's region boundaries against every saved game on the machine. |
| `test_amigaporspacewarning.py` | Checks that `write_por` warns a player when a character's name will lose its space on the Amiga's first save. |
| `test_amigaroutepool.py` | Checks that the Pool route's one step leaves the start square by an open edge, from the square's own walls, and that the manifest records and re-checks the choice. |
| `test_amigasavedisk.py` | Checks a `POOLSAVE` save disk formatted from nothing and the filename the game builds on it. |
| `test_amigasavegame.py` | Checks the Amiga saved-game map in `goldbox.amiga_savegame`, on synthetic saves and on the player's own. |
| `test_amigashots.py` | Checks that `tools/amiga/amigashots.py` finds the emulator's screen inside an archived grab of the whole guest desktop, on desktops built here. |
| `test_amigasplit.py` | Checks that the Amiga codec is one module per title and that no title module reaches another at import time. |
| `test_amigastaging.py` | Checks that `tools/amiga/staging.py` leaves a scratch Silver Blades boot ADF hides only its own save drawer or gains one slot file, preserves every file, and blocks unsafe output paths or replacement, using synthetic and registered disks. |
| `test_amigaareascript.py` | Checks that `goldbox.amiga_savegame.area_script` looks an area up in block 0 of the Amiga Curse `ECL.GLB` and blocks a table that does not fit the file, using generated containers and the registered Curse disks. |
| `test_amigatarget.py` | Checks `automap/amiga.py`'s WinUAE-backed `Target`, driven through a fake guest. |
| `test_amigatrip.py` | Checks `automap/amigatrip.py` on a fake machine: each title's statement bytes against the live trips, the RAWKEY message, the write order, the tier from a made-up script length, the world-menu check, putting back a trip that did not fire, and zeroing leftover statements, plus the script ends the live trips read, off the player's disks. |
| `test_amigaworldmap.py` | Checks that Amiga Curse's Dalelands map turns the fix into a world-map fix with its node and destination, holds it while the party leaves, and gives the usual fix in a town, from states read on FS-UAE. |
| `test_amigazerowords.py` | Checks that `tools/amiga/amigazerowords.py` runs without crashing against the player's specimens. |
| `test_fsuaegdb.py` | Checks `automap.amiga.FsuaeGdb` against a fake socket that answers the way the patched FS-UAE's GDB server does. |
| `test_fsuaegdbclick.py` | Checks that `fsuaegdb.py wish` lists the window's buttons, presses one with its answer and spell, and picks a drop-down entry, and that each reports a closed window, a disabled control or a bad argument in its own row. |
| `test_fsuaesession.py` | Checks `tools/amiga/fsuaesession.py` with the pool, processes and xdotool faked: the slot lease, the launch command line with a third drive and a swap list, the first-key wait, stop before fetching a disk, the screenshot cut, and a disk change that needs a log line. |
| `test_guardmaps.py` | Checks crop ownership, cross-title collisions and guard-map commands on synthetic screenshots, including atomic replacement failure cleanup. |
| `test_installfsuae.py` | Checks that `tools/amiga/installfsuae.py` blocks a tarball with the wrong digest, a member that escapes or a non-https download, unpacks only `package/bin/fs-uae/`, never deletes what `--into` already holds, and does nothing on a second run, on tarballs built here with no network. |
| `test_m68dis.py` | Checks the 68000 disassembler on hand-assembled encodings, including a word that is not an instruction. |
| `test_noencounters_winuae.py` | Checks the WinUAE `no_encounters` switch against a fake debugger pipe on synthetic memory, for every title: `on` changes each gate and records it, `keys` writes it again before every key after a reload, `off` puts every original back, a save key is blocked while the switch is on or a change is still recorded, and a killed run's changes are put back from the state file. |
| `test_podamiga.py` | Checks reading an Amiga Pools of Darkness `.pc` back to a neutral record and the DOS route around it. |
| `test_podderived.py` | Checks that `write_pod` reports `attack_level` and the portrait pair as derived or constant, never dropped, and that an unmeasured `armour_class_base` or portrait byte is reported as a loss rather than written over. |
| `test_podsavegame.py` | Checks the Amiga Pools of Darkness saved-game map: a container built here round-trips, every slot on the player's disks parses and rebuilds byte for byte, the square block is DOS's field order with one more byte, DOS's own strides fail on the same files, and the tool reads through `goldbox/amiga_savegame.py`'s container map. |
| `test_porslot.py` | Checks that `tools/amiga/porslot.py` reads an Amiga save slot straight off the disk, from the player's own image. |
| `test_savegamelosses.py` | Checks that a character's name cut to fit an Amiga Curse or Silver Blades save reaches the save-level report's `losses`, so `editor.saveplan` blocks the save rather than cutting the name silently. |
| `test_tripspace.py` | Checks `tools/amiga/tripspace.py`'s script lengths, tiers, skip-switch reading and script walk on containers, switches and scripts built here. |
| `test_winuaeps1.py` | Checks `tools/amiga/winuae.ps1`'s lane files, snapshot, `shot`, `press` and `debugger` verbs from the script's text: each lane's own ini and screenshot folder, the pipe chosen by its server pid, a screenshot read only if it is new and reset afterwards, a key released in a `finally`, the debugger entered over the pipe, no `key` or `front` verb and no focus helper, the device-name pattern matches Python's, a failed marker write stops before the old snapshot is replaced, and a failed move back names the backup folder. |
| `test_winuaesession.py` | Checks that `WinGuest` takes screenshots and presses keys through `winuae.ps1 shot` and `press` with Amiga raw codes, blocks other frame sizes and emulator keys, and that no run driver names a desktop grab. |
| `test_winvmguest.py` | Checks `tools/amiga/winvmguest.py`'s ssh and scp command lines and the options none may lose, the PowerShell it encodes, the screenshot and the WinUAE lane read back from Windows' output, and the lifecycle commands it blocks, without a Windows guest. |
