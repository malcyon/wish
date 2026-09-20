# tests

The test suite, one directory per game or job the way `tools/` is, with the shared helpers in `support/` and the fixtures in `fixtures/`.

## Directories

| directory | what is in it |
|---|---|
| [amiga](amiga/README.md) | Tests for the Amiga port: its filesystem, saved-game and character-record readers and writers, the tools under `tools/amiga/`, and the emulator routes in `automap/amiga.py`. |
| [areas](areas/README.md) | Tests for areas, maps and travel: the area tables, the map geometry and world map, Fast Travel, and the tools under `tools/areas/`. |
| [automap](automap/README.md) | Tests for the live automapper in `automap/`: its map model and geometry, the party and combat views, the combat log, the panels and the live actions, run against a `MemoryTarget` with no emulator. |
| [c64](c64/README.md) | Tests for the C64 side: the driven-session code under `tools/c64/`, the memory map and screen readers, and the checks that read a C64 save. |
| [convert](convert/README.md) | Tests for converting a character or a save between ports and titles: the neutral record, each port's codec, and the conversion tools and window code. |
| [curse_of_the_azure_bonds](curse_of_the_azure_bonds/README.md) | Tests for Curse of the Azure Bonds: its C64 disks, saves, tables and level-up rules, and the tools under `tools/curse_of_the_azure_bonds/`. |
| [dos](dos/README.md) | Tests for the DOS port: the DOS saved game and character record, the DOS record writers, and the tools under `tools/dos/` that drive and read DOSBox. |
| [editor](editor/README.md) | Tests for the character editor in `editor/`, its binding and window, and how it behaves for each title. |
| [generate](generate/README.md) | Tests for the generators under `tools/generate/`, chiefly that each generated file is still what its generator writes today. |
| [github](github/README.md) | Tests for the scripts that read and write the public issue tracker without letting a stranger's text into an agent's context. |
| [gui](gui/README.md) | Tests for the scripts under `tools/gui/`, which photograph, measure and validate the window. |
| [hooks](hooks/README.md) | Tests for the scripts under `.claude/hooks/`: what each one refuses and what it lets through. |
| [icons](icons/README.md) | Tests for combat icons and portraits: the option tables that compose a figure, the tables that convert one between ports, and the tools that draw and measure them. |
| [pool_of_radiance](pool_of_radiance/README.md) | Tests for Pool of Radiance: its fight driver, the messages and icons it draws, and the tools under `tools/pool_of_radiance/`. |
| [records](records/README.md) | Tests for the character record and the tables and rules around it: field layouts, derived values, level tables, per-title tables and the census tools. |
| [registry](registry/README.md) | Tests for the machine-local registries: the game-disk registry, the emulator instance pool, scratch directories and the specimen store. |
| [saves](saves/README.md) | Tests for the save containers and their readers: the D64 disk image, the C64 container, the saved-game and world-state models, and the YAML form of a save. |
| [secret_of_the_silver_blades](secret_of_the_silver_blades/README.md) | Tests for Secret of the Silver Blades: its C64 disks, saves, tables and level-up rules, and the tools under `tools/secret_of_the_silver_blades/`. |
| [suite](suite/README.md) | Tests for the suite's own tooling under `tools/suite/` and the guards that keep the repository itself in order. |
| [wish](wish/README.md) | Tests for the application in `wish/`: the window, preferences, game folders, the debug log, packaging, the icons and what they credit. |

## Beside the directories

| path | what is in it |
|---|---|
| `support/` | The helpers that several test files share, one module each, imported as `from support.<module> import ...` from any depth. |
| `fixtures/` | The small committed input files that some tests read. |
| `conftest.py` | The one conftest: a single `QApplication` for the session, offscreen Qt, isolated configuration and the between-test guards. |
| `gamedata.py` | Reads game data off the player's own disks at run time and composes the synthetic saves, arenas and maps, so none of the game is committed. |
| `iconcodes.py` | The set of icon codes the game's ICON menu can make, computed once per process and shared. |
