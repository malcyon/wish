# tests

The test suite, one directory per game or job the way `tools/` is, with the shared helpers in `support/` and the fixtures in `fixtures/`.

## Directories

| directory | what is in it |
|---|---|
| [generate](generate/README.md) | Tests for the generators under `tools/generate/`, chiefly that each generated file is still what its generator writes today. |
| [github](github/README.md) | Tests for the scripts that read and write the public issue tracker without letting a stranger's text into an agent's context. |
| [gui](gui/README.md) | Tests for the scripts under `tools/gui/`, which photograph, measure and validate the window. |
| [hooks](hooks/README.md) | Tests for the scripts under `.claude/hooks/`: what each one refuses and what it lets through. |
| [registry](registry/README.md) | Tests for the machine-local registries: the game-disk registry, the emulator instance pool, scratch directories and the specimen store. |
