# One binary — plan

**Status: planned, not started. Do it before the first `v*` tag**, because
after that the CLI's spelling is something somebody depends on and before it is
free. Donald: *"It should be one binary. It is fine to change the cli
interface, as long as our docs get updated. No one has muscle memory for the
cli. It is just me right now."*

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
file genuinely named `export` is reachable as `./export`.

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
| `README.md` | **Donald's. Report the wording, do not edit it.** |
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

1. `wish --version`, `wish export`, `wish import` and `wish --tab editor` all
   work from a wheel installed in a throwaway venv.
2. The frozen Linux build contains **exactly one** executable, and
   `wish export` round-trips a save disk byte-identically — the same assertion
   `122` §3 already makes of `wish-cli`.
3. CI asserts the single executable on both platforms.
4. On Windows, double-clicking `wish.exe` opens the window and **no console**.
   That is the one that matters. Whether `wish --version` also prints in a
   `cmd` window is worth noting when Donald is there anyway, but nothing
   depends on it.
