# tools

Developer scripts, but the package ships anyway — the emulator harness, the
instance pool, the disassembly and dump helpers, the code generators, and
`tools.wish`/`tools.generate.genui`, which `wish` reaches into at runtime
(`tools.wish` is named explicitly in `wish.spec`'s `hiddenimports`, since it
is the body of the `wish export`/`wish import` subcommands and no static scan
sees the import that reaches it; `tools.generate.genui` is imported directly by
`wish/__main__.py`). Anything here may talk to a live emulator, an X server or
the player's own disks, which is exactly why none of it is in `goldbox/`,
`editor/` or `wish/`.

**The scratch directory's 95 Python files were swept on 2026-09-02** for
`#181 (Sweep the 95 Python files in scratch for tools nobody can find)` (title paraphrased, because the original names the deleted directory), asking of each whether somebody would otherwise write it
again. Nine said yes, and they became the six tools `combatshot.py`,
`d6502check.py`, `m68discheck.py`, `overlay.py`, `rostercard.py` and
`whatis.py` below -- six rather than nine because several files in one
directory were one tool between them. The other 86 were a run's output: an
emulator driver edited into its own successor, a measurement of one window, a
copy of a package file taken before a change.

**Those 86 were read again on 2026-09-03** for
`#199 (Promote the tools stranded in scratch into tools/)`, and six more said yes -- `bigfont.py`, `combatdiag.py`,
`libslots.py`, `menucheck.py`, `monitorchain.py` and `wallsmap.py` -- because
each one **checks a tool that ships**, or reads what one writes, and the first
pass had sorted them as "an issue's measurement" from their filenames. So the
sort that matters is *what does this point at*: a thing in `tools/` or in the
packages makes it a tool, and one row of one issue's evidence does not.

The scratch directory has since been deleted for good; scratch now lives under
the temp directory (`tools/registry/scratch.py`) and may vanish at any time.

The scripts are grouped by the game or job they serve, one directory each, and every directory has a README.md with a row for each script in it; the table below lists the directories in the order of the tree. What belongs to no one game or job stays at the top and has its rows here. Run a script from the repository root as `python tools/dos/dosbox.py`, or import it as `tools.dos.dosbox`. A row's file name is relative to its own README, and a mention of a file in another directory gives its `tools/` path.

## Directories

| directory | what is in it |
|---|---|
| [amiga](amiga/README.md) | Scripts for the Amiga ports: reading their disk images and executables, disassembling them, and driving them under FS-UAE and WinUAE. |
| [areas](areas/README.md) | Scripts for a game's areas: the area tables, the scripts that run in them, their maps, and the exits and fast-travel routes between them. |
| [c64](c64/README.md) | Scripts for the Commodore 64 titles: the VICE session and the drivers built on it, save and record checks, and the C64 Ultimate tools. |
| [convert](convert/README.md) | Scripts for File > Convert: running every conversion direction, hashing what each one writes, and drawing the dialog. |
| [curse_of_the_azure_bonds](curse_of_the_azure_bonds/README.md) | Scripts for Curse of the Azure Bonds: loading, driving and checking its saves. |
| [dos](dos/README.md) | Scripts for the DOS ports: DOSBox and the drivers built on it, overlay and record readers, and the save and party tools. |
| [generate](generate/README.md) | Scripts that generate files from the code and the game's data: the compiled Qt forms, the generated docs, tables and licence file, the icon set, the Codex agent profiles and the class diagrams. |
| [github](github/README.md) | Scripts that read GitHub issues so that a stranger's text is withheld: the trust check and the issue reader. |
| [gui](gui/README.md) | Scripts that draw or measure Wish's own windows, and the Windows guest scripts that run them. |
| [icons](icons/README.md) | Scripts for combat icons and portraits: the correspondence tables between the DOS and C64 art, and the tools that build, check and draw them. |
| [pool_of_radiance](pool_of_radiance/README.md) | Scripts for Pool of Radiance: driving fights and outdoor walks, and replaying a load failure. |
| [records](records/README.md) | Censuses and cross-checks over character records that span titles and ports, such as class combinations, fields and encumbrance. |
| [registry](registry/README.md) | Scripts that say where things are and who holds them: the game disks, the specimen tree and its backups, the emulator instance pool and the scratch directories. |
| [secret_of_the_silver_blades](secret_of_the_silver_blades/README.md) | Scripts for Secret of the Silver Blades: staging, loading, training and comparing its saves. |
| [suite](suite/README.md) | Scripts that run and check the test suite: the whole-suite run that gates a push, the generated test party, the rules check, the sys.path census and the pytest plugins that chase a flaky guard test. |

## Top level

What belongs to no one game or job: the body of `wish export` and `wish import`, the GitHub App client that files issues as `wish-agent[bot]`, and the desktop-entry installers.

| file | purpose |
|---|---|
| `__init__.py` | Binds the real `wish` package before any tool body runs, so that `from tools import anything` cannot leave a process with `tools/wish.py` in its place; the module's own docstring has the incident. |
| `install-desktop.sh` | Installs `wish.desktop` and the icons under `$HOME` so a Linux desktop finds them. Needed because Wayland has no protocol for a client-supplied window icon — the compositor matches the app id against an installed desktop file, and with none it shows a generic gear. |
| `installdesktop.py` | Puts Wish's desktop entry and its icon where a Linux desktop looks for them -- `~/.local/share/applications` and `~/.local/share/icons/hicolor` -- which is what makes Alt-Tab and the taskbar draw the pentagram instead of a generic gear. The desktop matches a window to a `.desktop` file by application id and then looks the icon up by **name**, so `setWindowIcon` alone cannot help it. A wheel ships both into `<prefix>/share`, which is on the search path for a `pip install --user` and not for a virtualenv or a `pipx` install, and this covers those: `wish` calls `ensure()` as it starts and installs on the first run that finds nothing. Writes `Exec` from `sys.prefix` so a virtualenv's launcher is named rather than a `wish` command that may not exist. `--check` says what is installed, `--remove` takes it back out, and `wish --install-desktop` is the same code from the command line (`#9 (Finish the packaging icons: .desktop, .icns and a README lockup)`). |
| `wish.py` | The implementation of `wish export` and `wish import` — a save disk to YAML and back. No longer a program of its own; `wish/__main__.py` dispatches to it. An existing disk is never modified: `import` always writes a new one. |
| `wishagent.py` | Speaks to GitHub as the `wish-agent` App rather than as Donald's own account, so an issue or comment an agent files is authored by `wish-agent[bot]`. Mints a short-lived JWT from the App's private key (`~/.config/wish-agent/private-key.pem` by default), exchanges it for an installation token narrowed to `issues: write` on this one repository, and calls the REST API directly with `urllib.request` -- never GraphQL, and never `gh issue`'s own sub-commands, which resolve labels through GraphQL where an installation token is accepted unevenly. `whoami`, `token`, `create`, `comment`, `close`, `label`, `edit` and `edit-comment` cover everything an agent needs to file and update an issue. `push-token` mints the second kind of token, `contents: write` and `workflows: write`, and `git-credential` is a git credential helper built on it: it answers git's request for `github.com` over HTTPS with the user `x-access-token` and a token minted for that request, so a machine can push as the App with no token stored by this tool. A push token is minted on every call and cached nowhere; the request is split on newlines only, and only `github.com` over `https` is answered. `docs/218-the-wish-agent-bot.md` has the setup, including resetting git's helper list. The private key is refused outright if it is group- or world-readable (skipped on Windows, where the mode bits do not mean this), the token is cached in the process and never written to disk, and every body is read from `--body-file` rather than a shell argument. |
