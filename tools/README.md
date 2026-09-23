# tools

Scripts that may drive a live emulator, an X server or the player's own disks, one directory per game or job with a README row for each script; run one from the repository root as `python tools/dos/dosbox.py` or import it as `tools.dos.dosbox`.

## Directories

| directory | what is in it |
|---|---|
| [amiga](amiga/README.md) | Scripts for the Amiga ports: reading their disk images and executables, disassembling them, and driving them under FS-UAE and WinUAE. |
| [areas](areas/README.md) | Scripts for a game's areas: the area tables, the scripts that run in them, their maps, and the exits and fast-travel routes between them. |
| [c64](c64/README.md) | Scripts for the Commodore 64 titles: the VICE session and the drivers built on it, save and record checks, and the C64 Ultimate tools. |
| [convert](convert/README.md) | Scripts for File > Convert: running every conversion direction, hashing what each one writes, and drawing the dialog. |
| [curse_of_the_azure_bonds](curse_of_the_azure_bonds/README.md) | Scripts for Curse of the Azure Bonds: loading, driving and checking its saves. |
| [dos](dos/README.md) | Scripts for the DOS ports: DOSBox and the drivers built on it, overlay and record readers, and the save and party tools. |
| [generate](generate/README.md) | Scripts that generate files from the code and the game's data: the compiled Qt forms, the generated docs, tables and licence file, the icon set, the Codex agent profiles, the fast-travel exit table and the class diagrams. |
| [github](github/README.md) | Scripts that read GitHub issues so that a stranger's text is withheld: the trust check and the issue reader. |
| [gui](gui/README.md) | Scripts that draw or measure Wish's own windows, and the Windows guest scripts that run them. |
| [icons](icons/README.md) | Scripts for combat icons and portraits: the correspondence tables between the DOS and C64 art, and the tools that build, check and draw them. |
| [pool_of_radiance](pool_of_radiance/README.md) | Scripts for Pool of Radiance: driving fights and outdoor walks, and replaying a load failure. |
| [records](records/README.md) | Censuses and cross-checks over character records that span titles and ports, such as class combinations, fields and encumbrance. |
| [registry](registry/README.md) | Scripts that say where things are and who holds them: the game disks, the specimen tree and its backups, the emulator instance pool and the scratch directories. |
| [secret_of_the_silver_blades](secret_of_the_silver_blades/README.md) | Scripts for Secret of the Silver Blades: staging, loading, training and comparing its saves. |
| [suite](suite/README.md) | Scripts that run and check the test suite: the on-request whole-suite diagnostic run, the generated test party, the rules check, the sys.path census and the diagnostic pytest plugins, loaded on demand with `-p` rather than wired into `pyproject.toml` or `tests/conftest.py`, that measure and reproduce the race behind a flaky conftest guard test. |

## Top level

What belongs to no one game or job: the body of `wish export` and `wish import`, the GitHub App client that files issues as `wish-agent[bot]`, and the desktop-entry installers.

| file | purpose |
|---|---|
| `__init__.py` | Binds the real `wish` package before any tool body runs, so `from tools import anything` cannot leave a process with `tools/wish.py` in its place; its docstring has the incident. |
| `wish.py` | The body of `wish export` and `wish import`, a save disk to YAML and back, dispatched from `wish/__main__.py` and named in `wish.spec`'s `hiddenimports` because no static scan sees that import; `import` always writes a new disk. |
| `wishagent.py` | Speaks to GitHub as the `wish-agent` App so issues and comments are authored by `wish-agent[bot]`, through the REST API with an installation token narrowed to `issues: write`; `git-credential` lets git push as the App; refuses a group- or world-readable key, reads every body from `--body-file`; `docs/218-the-wish-agent-bot.md`. |
