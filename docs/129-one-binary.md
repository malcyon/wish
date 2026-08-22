# One binary

**Status: built, 2026-08-22.** Done before the first `v*` tag, because after
that the CLI's spelling is something somebody depends on and before it is free.
Donald: *"It should be one binary. It is fine to change the cli interface, as
long as our docs get updated. No one has muscle memory for the cli. It is just
me right now."*

## Why there were two

Not for any reason that survives inspection.

Windows makes a program declare which of two kinds it is, and PyInstaller has
to pick one per executable:

| kind | what Windows does |
|---|---|
| **console** | a terminal program. Printed output reaches the terminal it was started from — but double-clicking it opens a console window |
| **windowed** | a GUI program. No console window ever appears, and it has nowhere to print to |

On Linux and macOS the distinction does not exist. So on Windows a GUI and a
CLI genuinely are two different builds — but
[`122-release-testing.md`](122-release-testing.md) records the decision that
**Windows ships no CLI at all**, so the two executables only ever coexist on
Linux, where the setting means nothing. The split there is inherited from a
constraint that does not apply to it.

The second argument, and the one that started this: `wish --help` does not
mention `export`, because `export` is in another program. Somebody looking for
it looks in the obvious place first and does not find it.

## Windows stays windowed

Settled, and not in tension with anything: **the Windows build never opens a
console.** Donald — *"the Windows build should not open a console."*

The merge does mean Windows carries the `export` and `import` subcommands where
today it carries no CLI at all. Whether their output reaches a `cmd` window
depends on the console-borrowing trick in `packaging/wish_main.py`, which is
still unproven. That is a **limitation, not a blocker**: nobody is expected to
use the CLI on Windows, and the version is in Help > About either way. If it
turns out not to work, the subcommands are simply quiet there and everything
else is unaffected.

## The interface

| now | after |
|---|---|
| `wish` | unchanged — the window, map tab |
| `wish SAVE.D64` | unchanged |
| `wish --tab editor`, `--svg`, `--forget`, `--area`, `--disks`, `--interval`, `--debug` | unchanged |
| `wish-cli --export SAVE.D64 --output party.yaml` | `wish export SAVE.D64 -o party.yaml` |
| `wish-cli --import party.yaml --output NEW.D64` | `wish import party.yaml -o NEW.D64` |
| `wish-cli --dry-run` | `wish import … --dry-run` |
| `wish-editor`, `wish-automap` | **dropped** — `wish --tab editor` is the same thing and one entry point is the point |

`--game-disk`, `--original-save` and the rest keep their spellings inside the
subcommands they belong to.

**Resolving `wish export` against a file called `export`.** The first argument
is a subcommand if it exactly matches one of the subcommand names, and a save
disk otherwise. That is five lines in `wish/__main__.py`, ahead of the parser,
and it is the same shape as the `--debug` strip that already lives there. A
file genuinely named `export` is reachable as `./export`, and
`tests/test_packaging.py` opens one to prove it.

## What changes

| file | change |
|---|---|
| `pyproject.toml` | `[project.scripts]` keeps `wish` only; three entry points go |
| `wish/__main__.py` | dispatch on the first argument; subparsers for `export` and `import` |
| `tools/wish.py` | its `main()` becomes the body of those subcommands rather than its own program |
| `wish.spec` | `SHIP_CLI` and the whole second `Analysis` go; one `EXE`, one `COLLECT` |
| `packaging/wish_cli_main.py` | deleted |
| `.github/workflows/release.yml` | the "CLI ships on Linux and only on Linux" step becomes "there is exactly one executable"; add a `wish export` smoke test |
| `docs/95-wish-cli.md` | every example respelled; the file is about a command that no longer exists under that name |
| `docs/97-editor.md`, `docs/106-releases.md`, `docs/122-release-testing.md` | artefact contents and command examples |
| `README.md` | **Donald's. Not edited** — and as it turned out it needed nothing; see the end of this file. |
| `tests/test_packaging.py` | the platform-split assertions become single-binary assertions |

## What it buys

* One executable to explain, on both platforms, instead of a rule about which
  platform gets what.
* A smaller Linux tarball — `wish-cli` is 1.66 MB of a 63 MB archive, and its
  share of `_internal` goes too.
* The Windows CLI, as a side effect, where its output reaches a terminal.
* One fewer place for `wish.spec` to be platform-conditional, which is where
  the last packaging bug lived.

## Verification

Done on 2026-08-22, on Linux, against `wish_goldbox-0.0.1.dev188+…`.

1. **The wheel in a throwaway venv.** One console script, `wish`. `wish
   --version`, `wish export --help`, `wish import --help` all print; the
   `wish-cli`, `wish-editor` and `wish-automap` names are gone.
2. **The frozen build.** `dist/wish/` holds `wish` (2.29 MB) and `_internal/`
   and nothing else. `wish --version` and `wish export --help` both print, and
   `wish export` → `wish import` on a copied `PORSAVE13.D64` came back
   **byte-identical** (`sha256` equal). The folder is 163.1 MB and the `.tar.gz`
   61.3 MB, against 164.7 MB and 62.9 MB with `wish-cli` beside it — back to
   what they were before the CLI was added.
3. **The resolution rule.** A file called `export` copied into a directory
   exports through `wish export ./export`, and `wish export` with no argument is
   still the subcommand. Both are asserted in `tests/test_packaging.py`.
4. **CI** asserts, on Linux *and* Windows, that `dist/wish/` holds exactly one
   file beside `_internal/` and that `wish export --help` prints its usage. The
   second is the only check that reaches `tools.wish`, which is a hidden import
   because the subcommands reach it from inside `main()`.
5. **On Windows, double-clicking `wish.exe` opens the window and no console.**
   Still unverified — no Windows machine here — and unchanged by this work: the
   `EXE` is still `console=False`. Whether `wish export` prints in a `cmd`
   window is likewise unverified and nothing depends on it.

## What is left

* **`README.md` is Donald's and needed nothing.** It never named `wish-cli`,
  `wish-editor` or `wish-automap`, and it says nothing about the platforms
  shipping different things — the only command it gives is `wish`, twice, and
  `wish --tab map`, all still correct. What it *could* gain, if Donald wants it,
  is the two lines it has never had:

  ```sh
  wish export PORSAVE.D64 -o party.yaml     # the party as YAML
  wish import party.yaml  -o NEW.D64        # onto a new disk; the original is never touched
  ```

  The "Character Editor" section describes the window and not the command line,
  which was defensible while the command line was a separate program and is the
  thing the merge was meant to fix.
* **`docs/97-editor.md`, `docs/99-one-window.md`, `docs/102-live-actions.md`,
  `docs/117-save-conversion.md`, `docs/118-debug-mode.md`,
  `docs/123-parallel-sessions.md`, `docs/130-preferences.md`, `docs/README.md`
  and `docs/TASKS.md`** still name `wish-cli`, `wish-editor` or `wish-automap`.
  `docs/50-experiments.md` does too and should not be corrected: it is a record
  of what was run at the time.
* **`wish/debugmode.py`** and **`editor/binding.py`** each carry a comment
  naming the old entry points.
