# Index

What each directory in this repository is for.

| directory | purpose |
|---|---|
| [`por/`](por/README.md) | The game's formats, decoded — character records, save games, maps, items, spells. No Qt, no emulator, no transport. |
| [`editor/`](editor/README.md) | The character editor GUI. Opens a `.D64` and writes it back; imports nothing from `automap/`, so it works with no emulator anywhere. |
| [`automap/`](automap/README.md) | The live automapper: everything that knows about a running machine — the VICE client, the map state, the rendering geometry, the window. |
| [`wish/`](wish/README.md) | The application that wraps the other two — the tabbed window, preferences, the debug log, the backend session, the CLI entry point. |
| [`ui/`](ui/README.md) | Shared widget-level helpers both GUIs use: the app icon, icon painting, the Font Awesome set. |
| [`tools/`](tools/README.md) | Developer scripts, not shipped — the emulator harness, the instance pool, the disassembly and dump helpers, the code generators. |
| `tests/` | The test suite, plus `gamedata.py`, which reads game data off the player's own disks so none of it is committed. |
| `docs/` | The knowledge base: numbered documents recording what is known and how it was established. Outlives every issue that cites it. |
| `packaging/` | The PyInstaller entry script and the Windows console-borrowing shim. |
| `assets/` | Shipped non-code files — the application icons and the `.desktop` entry. |
| `images/` | The screenshots the README links. |
| `designer/` | A launcher for Qt Designer, for editing `editor/character.ui`. |
| `skills/` | The `goldbox` skill — the decoding checklist an agent loads when working on this project. |
| `work/` | Scratch: disk images, dumps, analysis runs. **Gitignored**, and where anything derived from the game lives so it never enters the repository. |
| `build/` | PyInstaller's intermediate output. Gitignored. |
| `dist/` | The frozen build — `wish` and `_internal/`. Gitignored. |

## API Documentation

https://wish-goldbox.readthedocs.io/en/latest/

## The split that is a rule, not tidiness

`por/` stays transport-free, `editor/` stays emulator-free, and everything that
talks to VICE lives in `automap/`. That is what keeps the editor a file tool
that runs with no emulator installed, and it is why the automapper is its own
package rather than part of the editor.
