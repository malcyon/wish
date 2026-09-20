# tests

The test suite, one directory per game or job the way `tools/` is, with the shared helpers in `support/` and the fixtures in `fixtures/`.

## Directories

| directory | what is in it |
|---|---|
| [generate](generate/README.md) | Tests for the generators under `tools/generate/`, chiefly that each generated file is still what its generator writes today. |
| [github](github/README.md) | Tests for the scripts that read and write the public issue tracker without letting a stranger's text into an agent's context. |
| [gui](gui/README.md) | Tests for the scripts under `tools/gui/`, which photograph, measure and validate the window. |
| [hooks](hooks/README.md) | Tests for the scripts under `.claude/hooks/`: what each one refuses and what it lets through. |
| [icons](icons/README.md) | Tests for combat icons and portraits: the option tables that compose a figure, the tables that convert one between ports, and the tools that draw and measure them. |
| [records](records/README.md) | Tests for the character record and the tables and rules around it: field layouts, derived values, level tables, per-title tables and the census tools. |
| [registry](registry/README.md) | Tests for the machine-local registries: the game-disk registry, the emulator instance pool, scratch directories and the specimen store. |
| [saves](saves/README.md) | Tests for the save containers and their readers: the D64 disk image, the C64 container, the saved-game and world-state models, and the YAML form of a save. |
| [suite](suite/README.md) | Tests for the suite's own tooling under `tools/suite/` and the guards that keep the repository itself in order. |
