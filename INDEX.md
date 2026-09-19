# Index

What each directory in this repository is for; the API documentation is at https://wish-goldbox.readthedocs.io/en/latest/.

| directory | purpose |
|---|---|
| [`goldbox/`](goldbox/README.md) | The game's formats, decoded — character records, save games, maps, items, spells — with no Qt, no emulator and no transport. |
| [`editor/`](editor/README.md) | The character editor GUI, which opens a `.D64` and writes it back and imports nothing from `automap/`, so it works with no emulator anywhere. |
| [`automap/`](automap/README.md) | The live automapper: everything that knows about a running machine — the VICE client, the map state, the rendering geometry, the window. |
| [`wish/`](wish/README.md) | The application that wraps the other two — the tabbed window, preferences, the debug log, the backend session, the CLI entry point. |
| [`ui/`](ui/README.md) | Shared widget-level helpers both GUIs use: the app icon, icon painting, the icon path data. |
| [`tools/`](tools/README.md) | Developer scripts that ship anyway — the emulator harness, the instance pool, the disassembly and dump helpers, the code generators, and `tools.wish`/`tools.generate.genui`, which `wish` reaches into at runtime. |
| `tests/` | The test suite, plus `gamedata.py`, which reads game data off the player's own disks so none of it is committed. |
| `livetests/` | The tests that start an emulator or talk to a device, which the normal pytest run never collects. |
| `docs/` | The knowledge base: numbered documents recording what is known and how it was established. |
| [`packaging/`](packaging/README.md) | The PyInstaller entry script, the Windows console-borrowing shim, and the `.icns` generator. |
| [`ansible/`](ansible/README.md) | The playbooks that build the agent sandbox: the isolated libvirt network and its filter, the Ubuntu guest the agents run in, and the Windows guest that runs WinUAE; one machine's own values live in a gitignored `inventory.yml`. |
| `assets/` | Shipped non-code files — the application icons, the `.desktop` entry, and the artist's own logo files under `assets/logo/`. |
| `images/` | The screenshots the README links. |
| `designer` | A launcher for Qt Designer that opens `wish/window.ui`, the unified layout (`docs/146-unified-ui.md`). |
| `.claude/agents/` | Source subagent definitions — each supplies Claude Code's model, tool list and prompt, and `tools/generate/gencodex.py` generates the Codex profiles from them. |
| `.codex/agents/` | Generated project subagent profiles for Codex; do not edit them by hand, run `tools/generate/gencodex.py`. |
| `.claude/rules/` | The working standards split out of `CLAUDE.md`; a file with `paths:` frontmatter loads only when a file it names is read, and one without loads at launch for the main window and every subagent. |
| `.agents/rules/` | The same files as `.claude/rules/`, as symlinks, for tools that read `AGENTS.md` and `.agents/rules/`; `AGENTS.md` holds the rules themselves and `CLAUDE.md` imports it and adds only what is true of Claude Code alone. |
| `.agents/skills/` | Skills Codex and Antigravity read; `caveman` is shared with Claude Code by symlink from `.claude/skills/`, and `orchestrate` here is Codex's own copy of `.claude/skills/orchestrate/`, allowed to differ from it. |
| `.gemini/` | One file, `settings.json`, telling Gemini CLI to read `AGENTS.md` as its context file. |
| `.claude/` (the rest) | Local state — agent memory, machine settings; gitignored, except `agents/`, `rules/`, `hooks/` and `settings.json`. |
| `<temp>/wish/` | Not in the repository: where a tool's runs write (`tools/registry/scratch.py`), under the machine's temp directory, where it may vanish at any time and where anything derived from the game stays so it never enters the repository. |
| `build/` | PyInstaller's intermediate output. Gitignored. |
| `dist/` | The frozen build — `wish` and `_internal/`. Gitignored. |
