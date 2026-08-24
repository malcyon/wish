# tools

Developer scripts, not shipped — the emulator harness, the instance pool, the
disassembly and dump helpers, the code generators. Anything here may talk to a
live emulator, an X server or the player's own disks, which is exactly why none
of it is in `por/`, `editor/` or `wish/`.

| file | purpose |
|---|---|
| `__init__.py` | Empty. |
| `compare.py` | Loads every character specimen we have and reports, per record offset, how much the value varies — offsets that vary are candidate fields, and correlating that variation with attributes we already know is how the rest get identified. No emulator needed. |
| `diff.py` | Diffs two save disks and says what changed in game terms. The workhorse of the discovery phase: save, change exactly one thing in-game, save again, diff. Changed bytes resolve to slot plus record offset and are labelled with the layout field or flagged as an unknown region — the unknown hits are the interesting ones. |
| `dosbox.py` | A driven DOS Gold Box session: DOSBox on a private X display, unattended. Input is XTEST through `xdotool` aimed at a window nobody else owns (there is no window manager under a bare `Xvfb`, so `windowactivate` fails and the keystroke is lost); output is a 320x200 capture that is the VGA framebuffer pixel for pixel; ground truth is the save file DOS writes. |
| `drive.py` | Drives Pool of Radiance under VICE — the original binary-monitor client (still re-exported from `automap/vice.py`), key sending through XTEST on the nested display, and the surrounding discovery scaffolding. |
| `dump.py` | Annotated dump of a `.D64`, a save game or a `.chr` — disk directory, save summary, one character record, or a raw address range. |
| `gendocs.py` | **Generates** `docs/20-character-record.md` from the field notes in `por/layout.py`, so the documentation cannot drift from the code. Re-run after touching the layout. |
| `genimports.py` | Reads the module-level import edges inside one package out of the AST, and writes the dependency graph `docs/117-save-conversion.md` carries. **Generates** that graph rather than drawing it by hand, because the edge it exists to catch -- a codec importing another codec -- is exactly the one somebody adds without noticing. |
| `genicons.py` | **Generates** the platform icon files in `assets/` from `ui/appicon.py`, offscreen. Every size is rendered rather than scaled, because Windows picks the nearest entry and bilinearly scales it — a `.ico` holding only a 256 gives mush at the 16 px used in the title bar and Alt-Tab. `--check` asks whether `assets/` is in step. |
| `genitems.py` | **Generates** `docs/85-item-tables.md` by reading `ITEMNAMES` and `ITEMS` straight off a game disk, so the names carry no transcription errors and none of the data enters the repository. |
| `genlevels.py` | **Generates** `docs/89-level-tables.md` from `por/levels.py`. |
| `genmaps.py` | **Generates** `docs/88-map-files.md` from the GEO files on the game disks. Needs a set of disks — `POR_DISKS`, or a directory argument. |
| `genmemory.py` | **Generates** `docs/41-memory-regions.md` from `por/memory.py`. |
| `genspells.py` | **Generates** `docs/86-spell-table.md` from `SPELLN00` on a game disk. |
| `gentemplates.py` | **Generates** `docs/87-item-templates.md` — every item record on the game disks, which are the records `wish` copies when a YAML entry names a `template`. |
| `genui.py` | Compiles `editor/character.ui` to `editor/ui_character.py`. The editor calls `ensure_current()` at startup so this is rarely run by hand; `--check` regenerates into memory and fails if the committed file differs, which is what CI wants. |
| `geomap.py` | Renders GEO map files as text floor plans, optionally with a save's party marked. `--find` is the anchor problem: given where the party stands but not which map, it reports every GEO where that square exists and the party is not inside a wall, narrowing 29 files to a handful. |
| `iconsheet.py` | Renders every icon the program ships at the sizes it is actually seen at, through the same painting code the map and the roster use. Exists because a table of icon *names* is how `hat-wizard` got chosen and how it turned out to read as a shark's fin at 13 pixels. |
| `install-desktop.sh` | Installs `wish.desktop` and the icons under `$HOME` so a Linux desktop finds them. Needed because Wayland has no protocol for a client-supplied window icon — the compositor matches the app id against an installed desktop file, and with none it shows a generic gear. |
| `instance.py` | The VICE instance pool: six resources per slot (two monitor ports, a command port, an X display, a work directory and a private `vicerc`), held by one lease. The lease is an `fcntl.flock`, so the kernel frees a crashed run's slot with no cleanup script. Nothing here ever kills a process by name — teardown is `os.killpg` on the group *this slot* started. |
| `porcmd` | One-line shell client that sends a command to the running `session.py` driver on its command port and prints the reply. |
| `porlaunch.sh` | Launches VICE on its own X display with a disk autostarted. Everything that makes an instance distinct arrives through the environment (`POR_DISPLAY`, `POR_VICERC`, `MONFLAGS`, `PORFLAGS`, `POR_HEADLESS`) so `instance.py` can hand a slot its own copy of all of it. It kills nothing. |
| `rungame.sh` | Launches the game for a one-off experiment inside Xephyr with the binary monitor enabled and a per-experiment fliplist under `work/`. The nested X server is not cosmetic: with no window manager, VICE holds focus permanently, XTEST always lands on it, and keystrokes cannot leak into the user's real desktop. |
| `session.py` | A driven Pool of Radiance session — boot, copy protection, disk swapping. The swap is the thing that makes automation possible and it is not obvious: the fliplist is unreachable from automation, but the *text* monitor has `attach`, and both monitor servers can run at once. One long-lived process, because VICE serves one text-monitor connection per run and closing it deafens every monitor. |
| `show.py` | Prints everything currently readable from a save disk, with each field marked by how far it is trusted — CONFIRMED, PROBABLE or GUESS. |
| `toamiga.py` | Writes a C64 party out as Amiga *Pools of Darkness* `Save/NAME.pc` files, one per character, ready to drop into a disk 3 `Save` drawer. Goes through `por/neutral.py`'s `NeutralCharacter`, so it reads any of the six C64 titles; what cannot cross is printed rather than dropped quietly. The C64 disk is opened read-only. |
| `walkrun.py` | Unattended corpus building: boot, load a save, walk a route in the game's own letters, and save at every step. A move that does not change the party position is a **wall**, which is the whole point. Tears everything down at the end and screenshots if anything goes wrong. |
| `wish.py` | The implementation of `wish export` and `wish import` — a save disk to YAML and back. No longer a program of its own; `wish/__main__.py` dispatches to it. An existing disk is never modified: `import` always writes a new one. |
