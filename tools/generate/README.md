# generate

Scripts that generate files from the code and the game's data: the compiled Qt forms, the generated docs, tables and licence file, the icon set, the Codex agent profiles, the fast-travel exit table and the class diagrams.

| file | purpose |
|---|---|
| `classdiagram.py` | Runs `pyreverse -o mmd` over a package or module and reports classes, edges and pixel size, against a detached worktree at `HEAD` by default (`--dirty` for the working tree). Needs `pylint` in a separate environment, which it prints the command for, and `@mermaid-js/mermaid-cli` for the pixel figure. |
| `classedges.py` | Lists which annotated attributes anywhere in a package are of a named class, the reading `pyreverse` turns into an aggregation edge, without needing `pylint`; `classedges.py Title goldbox` is an example. Counts fields, not parameters, and prints each annotation as written. |
| `gencodex.py` | **Generates** Codex agent profiles from the Claude agent definitions with platform-specific models and shared safety instructions. |
| `gendocs.py` | **Generates** `docs/20-character-record.md` from the field notes in `goldbox/layout.py`, so the documentation cannot drift from the code. Re-run after touching the layout. |
| `genexits.py` | **Generates** `automap/fasttravel.py`'s `EXIT_ROUTES` table from `tools/areas/eclexitkinds.py`'s per-exit analysis: one square for each area pair a scripted exit reaches, which of `DUNGEON`'s two dispatch points re-enters it there, and whether the route can start a fight. `--report PATH.md` also writes the exits it could not place and why. |
| `genicons.py` | **Generates** the platform icon files in `assets/` from `ui/appicon.py`, offscreen, making each size from the artist's smallest file no smaller than it (his PNG exports up to 500, his SVG above). `--check` asks whether `assets/` is current. |
| `genimports.py` | Reads the module-level import edges inside one package from the AST and **generates** the dependency graph `docs/117-save-conversion.md` carries. |
| `genitems.py` | **Generates** `docs/85-item-tables.md` by reading `ITEMNAMES` and `ITEMS` straight off a game disk, so none of the data enters the repository. |
| `genlevels.py` | **Generates** `docs/89-level-tables.md` from `goldbox/levels.py`. |
| `genlicenses.py` | **Generates** `THIRD_PARTY_LICENSES.md` from `ui/icons.py`, so the CC BY 3.0 attribution names exactly the game-icons.net glyphs that ship. `--check` fails if the committed file is out of date, which `tests/wish/test_licenses.py` runs. |
| `genmaps.py` | **Generates** `docs/88-map-files.md` from the GEO files on the game disks. Needs a set of disks: `POR_DISKS`, or a directory argument. |
| `genmemory.py` | **Generates** `docs/41-memory-regions.md` from `goldbox/memory.py`. |
| `genspells.py` | **Generates** `docs/86-spell-table.md` from `SPELLN00` on a game disk. |
| `gentemplates.py` | **Generates** `docs/87-item-templates.md`: every item record on the game disks, which are the records `wish` copies when a YAML entry names a `template`. |
| `genui.py` | Compiles `editor/character.ui` to `editor/ui_character.py`. The editor calls `ensure_current()` at startup, so it is rarely run by hand; `--check` regenerates into memory and fails if the committed file differs, which is what CI runs. |
