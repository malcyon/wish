# amiga

Tests for the Amiga port: its filesystem, saved-game and character-record readers and writers, the tools under `tools/amiga/`, and the emulator routes in `automap/amiga.py`.

| file | purpose |
|---|---|
| `test_amiga.py` | Checks the Amiga character record against the offsets the character sheet drew, on probe records built here and on the `.pc` files of the player's own disks. |
| `test_amiga68k.py` | Checks `tools/amiga/amiga68k.py`'s jump-table resolution, PC-relative reference search and reloc annotation on Hunk executables built here. |
| `test_amiga_adf.py` | Checks that `goldbox.amiga_adf` reads every real disk clean and formats, writes and re-reads a blank one. |
| `test_amiga_savegame.py` | Checks the later-title Amiga saved-game reader, writer and fresh disk. |
| `test_amigaabilitypaircross.py` | Checks that a crossed Amiga Curse or Silver Blades ability pair keeps its permanent and in-force halves apart through `to_neutral_later`. |
| `test_amigabackstab.py` | Pins what `tools/amiga/amigabackstab.py` reads out of each Amiga title's own executable, and that erasing a step of the regain arithmetic is refused. |
| `test_amigabladesjournal.py` | Checks how `tools/amiga/amigabladesjournal.py` fits the game's character grid inside a desktop capture and rescales it, on synthetic frames. |
| `test_amigacontainercheck.py` | Checks the parts of `tools/amiga/amigacontainercheck.py` that decide what it says, on synthetic input, and that its two readers share no code. |
| `test_amigacursewheel.py` | Checks `tools/amiga/amigacursewheel.py`'s whole-number rescale of a WinUAE capture and that a machine without the private tables is told so. |
| `test_amigadrive.py` | Checks `tools/amiga/amigadrive.py`'s key table and the two settings a party walks on, through the command line the driver would send. |
| `test_amigaindexedrefs.py` | Checks `tools/amiga/amigaindexedrefs.py`'s `d8(An,Xn)` indexed-site search and its `lea` base-within-reach search, on hand-built instructions in a synthetic hunk. |
| `test_amigaglobal.py` | Checks `tools/amiga/amigaglobal.py` finds a global's references and a routine's callers on an executable built here. |
| `test_amigaicons.py` | Checks the Amiga Curse and Silver Blades combat-icon art against DOS's own, off the player's disks. |
| `test_amigalaterproof.py` | Checks the party ordering and the mask of engine-recomputed bytes in `tools/amiga/amigalaterproof.py`. |
| `test_amigalaterslot.py` | Checks `tools/amiga/amigalaterslot.py` writes the name, count word and chain head the game's loader reads, on synthetic disks. |
| `test_amigalaterwindow.py` | Checks that an Amiga Curse or Silver Blades record's unnamed `field_83_87` bytes survive to Amiga and to DOS, on records built here and on the player's disks. |
| `test_amigalaterwrite.py` | Checks that the Amiga Curse and Silver Blades writer is the inverse of the reader, by round trip and against the engine's own re-saves. |
| `test_amiganamespaces.py` | Pins where `tools/amiga/amiganamespaces.py` finds each Amiga title's name-stripping routine and whether it reaches a record, checks its Pool of Radiance model against the names the running game saved, and checks every engine resave on the disks against the model. |
| `test_amiganodefields.py` | Checks `tools/amiga/amiganodefields.py` reports each effect-node byte the two later executables name and the byte nothing reaches. |
| `test_amigapipe.py` | Checks `automap.amiga.WinuaePipe` against a fake that answers the way the real guest was measured answering. |
| `test_amigaporsavegame.py` | Checks that the Amiga Pool of Radiance saved game is built from the source save, from the player's disks and specimens. |
| `test_amigaporsavegamecorpus.py` | Checks the Amiga Pool of Radiance container's region boundaries against every saved game on the machine. |
| `test_amigaporspacewarning.py` | Checks that `write_por` warns a player when a character's name will lose its space on the Amiga's first save. |
| `test_amigasavedisk.py` | Checks a `POOLSAVE` save disk formatted from nothing and the filename the game builds on it. |
| `test_amigasavegame.py` | Checks the Amiga saved-game map in `goldbox.amiga_savegame`, on synthetic saves and on the player's own. |
| `test_amigashots.py` | Checks that `tools/amiga/amigashots.py` finds the emulator's screen inside a grab of the whole guest desktop, on desktops built here. |
| `test_amigasplit.py` | Checks that the Amiga codec is one module per title and that no title module reaches another at import time. |
| `test_amigatarget.py` | Checks `automap/amiga.py`'s WinUAE-backed `Target`, driven through a fake guest. |
| `test_amigazerowords.py` | Checks that `tools/amiga/amigazerowords.py` runs without crashing against the player's specimens. |
| `test_fsuaegdb.py` | Checks `automap.amiga.FsuaeGdb` against a fake socket that answers the way the patched FS-UAE's GDB server does. |
| `test_installfsuae.py` | Checks that `tools/amiga/installfsuae.py` refuses a tarball with the wrong digest, a member that escapes or a non-https download, unpacks only `package/bin/fs-uae/`, never deletes what `--into` already holds, and does nothing on a second run, on tarballs built here with no network. |
| `test_m68dis.py` | Checks the 68000 disassembler on hand-assembled encodings, including a word that is not an instruction. |
| `test_podamiga.py` | Checks reading an Amiga Pools of Darkness `.pc` back to a neutral record and the DOS route around it. |
| `test_podsavegame.py` | Checks the Amiga Pools of Darkness saved-game map: a container built here round-trips, every slot on the player's disks parses and rebuilds byte for byte, the square block is DOS's field order with one more byte, DOS's own strides fail on the same files, and the tool reads through `goldbox/amiga_savegame.py`'s container map. |
| `test_porslot.py` | Checks that `tools/amiga/porslot.py` reads an Amiga save slot straight off the disk, from the player's own image. |
| `test_winvmsettle.py` | Checks when `tools/amiga/winvmsettle.py` decides a guest screen has settled, what it keeps when it never does, and what it says with no screen. |
