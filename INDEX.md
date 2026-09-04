# Index

What each directory in this repository is for.

| directory | purpose |
|---|---|
| [`goldbox/`](goldbox/README.md) | The game's formats, decoded — character records, save games, maps, items, spells. No Qt, no emulator, no transport. |
| [`editor/`](editor/README.md) | The character editor GUI. Opens a `.D64` and writes it back; imports nothing from `automap/`, so it works with no emulator anywhere. |
| [`automap/`](automap/README.md) | The live automapper: everything that knows about a running machine — the VICE client, the map state, the rendering geometry, the window. |
| [`wish/`](wish/README.md) | The application that wraps the other two — the tabbed window, preferences, the debug log, the backend session, the CLI entry point. |
| [`ui/`](ui/README.md) | Shared widget-level helpers both GUIs use: the app icon, icon painting, the Font Awesome set. |
| [`tools/`](tools/README.md) | Developer scripts, but ships anyway — the emulator harness, the instance pool, the disassembly and dump helpers, the code generators, and `tools.wish`/`tools.genui`, which `wish` reaches into at runtime. |
| `tests/` | The test suite, plus `gamedata.py`, which reads game data off the player's own disks so none of it is committed. |
| `docs/` | The knowledge base: numbered documents recording what is known and how it was established. Outlives every issue that cites it. |
| `packaging/` | The PyInstaller entry script and the Windows console-borrowing shim. |
| `assets/` | Shipped non-code files — the application icons and the `.desktop` entry. |
| `images/` | The screenshots the README links. |
| `designer` | A launcher for Qt Designer, opening `wish/window.ui`, the unified layout (`docs/146-unified-ui.md`) — `editor/character.ui` is gone, absorbed into it. |
| `.claude/agents/` | The subagent definitions -- each one a model, a tool list and a system prompt for a kind of work this project keeps handing out. |
| `.claude/rules/` | The working standards, split out of `CLAUDE.md` under `#208 (Split CLAUDE.md into .claude/rules, so 21,800 tokens do not load before every task)`. A file carrying `paths:` frontmatter loads only when a file it names is read; one without loads at launch. Subagents do **not** inherit these, which is why the prohibitions stayed in `CLAUDE.md`. |
| `.agents/rules/` | The same twelve files, as symlinks. Antigravity reads `AGENTS.md` and `.agents/rules/`; Claude Code reads `CLAUDE.md` and `.claude/rules/`. They are the same bytes, so there is one copy to keep true. `AGENTS.md` at the top level is a symlink to `CLAUDE.md` for the same reason. |
| `.gemini/` | One file, `settings.json`, telling Gemini CLI to read `CLAUDE.md` as its context file -- it takes a list of filenames, so it needs no symlink at all. Nothing else; `.gemini/agents/` was deleted, having been read by neither tool. |
| `.claude/` (the rest) | Local state -- agent memory, machine settings. Gitignored; `agents/`, `rules/`, `hooks/` and `settings.json` are the tracked exceptions. |
| `work/` | Scratch: disk images, dumps, analysis runs. **Gitignored**, and where anything derived from the game lives so it never enters the repository. |
| `build/` | PyInstaller's intermediate output. Gitignored. |
| `dist/` | The frozen build — `wish` and `_internal/`. Gitignored. |

## API Documentation

https://wish-goldbox.readthedocs.io/en/latest/

## The split that is a rule, not tidiness

`goldbox/` stays transport-free, `editor/` stays emulator-free, and everything that
talks to VICE lives in `automap/`. That is what keeps the editor a file tool
that runs with no emulator installed, and it is why the automapper is its own
package rather than part of the editor.
