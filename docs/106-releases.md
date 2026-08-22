# Versioning, packaging and CI

**Status: built.** Versioning, three workflows and a PyInstaller spec are in the
tree. No tag has been pushed yet, so no release page exists.

---

## 1. Versioning

The version is the git tag, via `hatch-vcs`. `pyproject.toml` declares
`dynamic = ["version"]`; a tag `v0.2.0` builds as `0.2.0`, and an untagged
commit gets `0.0.1.devN+g<sha>`, which cannot be mistaken for a release.

Only `v*` tags count. The repository carries `purge-backup-2026` and two other
backup tags, and without a match pattern setuptools-scm read that one as version
2027, so `[tool.hatch.version].raw-options` pins both `tag_regex` and
`git_describe_command` to `v[0-9]*`.

`wish.__version__` looks in three places in order: `wish/_version.py`, written
by the hatch-vcs build hook and `.gitignore`d, which is what a frozen build
reads; the installed metadata; and `0.0.0+unknown` for a source checkout that
was never built. `wish --version` and `wish-cli --version` print it.

The window says the same number under **Help > About wish** — `wish/about.py`,
installed from `wish/window.py`.

## 2. What a release contains

| audience | artefact |
|---|---|
| people with Python | the wheel, or `pip install` from the sdist |
| everyone else | a one-folder PyInstaller build |

Linux gets `wish-<version>-linux-x86_64.tar.gz`, Windows
`wish-<version>-windows-x86_64.zip`. Not an AppImage, not an MSI, not a signed
exe: a certificate costs money and SmartScreen warns anyway, so the zip is
honest about what it is. macOS is "run it from source" until somebody with a Mac
wants to own an unsigned `.app`.

**The Linux tarball carries `wish-cli` beside `wish`; the Windows zip carries
`wish.exe` alone** — Donald: "Windows users don't need a cli. They're point and
click heroes." `wish.spec` spells that as `SHIP_CLI = sys.platform != "win32"`.

The Linux folder is about 157 MB before compression, three quarters of it Qt.
`wish-cli` costs 1.8 MB of that: both executables come out of one `COLLECT`, so
the folder holds one copy of Qt and one of libpython, and the console build
imports no Qt at all — `por`, PyYAML and `automap.paths`, and `ldd` on it names
no Qt library. `wish.spec` checks that rather than excluding `PyQt6`: an
exclude would turn a stray GUI import into a `ModuleNotFoundError` on a user's
machine, where the check stops the build.

`SHA256SUMS` covers everything on the release page.

## 3. CI

Three workflows in `.github/workflows/`.

**`test.yml`** — push and pull request.

* job `pytest`: Ubuntu and Windows against Python 3.12 and 3.13, `pip install -e
  ".[dev,gui]"`, `pytest -q` under `QT_QPA_PLATFORM=offscreen`. Ubuntu installs
  `libegl1 libgl1 libxkbcommon-x11-0 libdbus-1-3 libglib2.0-0` first: the PyQt6
  wheel carries Qt but not the libraries Qt links against. Python 3.14 is left
  out deliberately — the PyQt6 wheels are `abi3`/cp310 so it would work, but it
  buys no coverage.
* job `generated`: `tools/genui.py --check`, then `tools/gendocs.py` and
  `tools/genmemory.py` followed by `git diff --exit-code -- docs/`. Neither
  generator has a `--check` flag and the diff is the same test without adding
  one.

**The tests that need the player's disks skip on CI, and that is the expected
result** — `CLAUDE.md` forbids committing the data that would make them run. It
was 27 when this was planned and is 30 now; the number moves as tests are added.
Locally, with disks, the same suite runs them.

`tools/genui.py --check` compares the generated code *without* pyuic6's header,
which carries the absolute path of the `.ui` and the PyQt6 version and so
differs on every machine. The drift worth catching is in the widgets.

**`lint.yml`** — ruff only, config in `pyproject.toml`.

`select = ["E4", "E7", "E9", "F", "I"]`: pyflakes, the pycodestyle rules that
are actual errors, and import ordering. Deliberately **not** `E501` —
`por/layout.py` is the field documentation and its notes are meant to be read,
not wrapped to 88 columns; enabling it wanted 60 rewraps across files whose
prose is the point. `editor/ui_character.py` is excluded outright: pyuic6 writes
it.

Nothing else is on yet. `ruff format` and mypy on `por/` remain the next
candidates; bandit and vulture stay off for the reasons the old plan gave — a
tool that reads files and opens sockets trips bandit constantly, and the
deliberately unused format constants that document the file layout are exactly
what vulture flags.

**`release.yml`** — on a `v*` tag.

1. `tests`: `uses: ./.github/workflows/test.yml`, the whole suite on both
   platforms, and everything below `needs` it. A red `test.yml` used not to
   stop a tag. `test.yml` gained `workflow_call:` for this rather than a second
   copy of the matrix.
2. `dist`: `python -m build`, then a check that the wheel's version is the tag
   with the `v` stripped.
3. `frozen`: Ubuntu and Windows, each building `wish.spec` on its own runner
   because PyInstaller does not cross-compile. `pip install -e .` first, because
   that is what writes `wish/_version.py` from the tag. Three smoke checks on
   the artefact, all asserting on **output** rather than an exit code, because
   the Windows build exits 0 in silence when its streams are broken:
   `--version` prints exactly `wish <tag>`; a mistyped option puts argparse's
   "unrecognized arguments" on stderr, which is the same path every diagnostic
   travels and needs no display; and `wish-cli` reports the same version on
   Linux while `wish-cli.exe` is absent on Windows.
4. `publish`: gathers both, writes `SHA256SUMS`, and hands the lot to
   `softprops/action-gh-release` with `generate_release_notes`.

## 4. The PyInstaller spec

`wish.spec`, one folder rather than one file: a one-file build unpacks itself to
a temporary directory at every start, which for a Qt application is a visible
pause and buys nothing a `.tar.gz` does not.

`packaging/wish_main.py` is the entry script, because a frozen build starts from
a script and the relative imports in `wish/__main__.py` only work inside the
package. `packaging/wish_cli_main.py` is the same indirection for `wish-cli`,
whose `Analysis` excludes `PyQt6`, `editor` and `automap` so the build fails
loudly if the CLI ever grows a GUI import. Both `EXE`s go into the one
`COLLECT`; two `COLLECT`s would mean two copies of Qt.

**Stdout on Windows.** The window is built `console=False`, and since
PyInstaller 5.7 that means `sys.stdout` and `sys.stderr` are `None` rather than
sinks, to match `pythonw.exe` — so `wish.exe --version` printed nothing and
every diagnostic, the "no game disks … so the map tab will be empty" line
included, was swallowed.
`packaging/wish_main.py` now repairs the streams before anything writes, in
this order: the handle the shell inherited to us, which is a redirect or a CI
pipe and means that file and nothing else; then
`AttachConsole(ATTACH_PARENT_PROCESS)` and `CONOUT$`, the terminal the user
typed into; then `os.devnull`, which is silence but not the `AttributeError`
inside argparse that used to be a traceback box. The order matters: borrowing
the console first would send a redirected run to the terminal and leave the
file empty. A double-click from Explorer still gets devnull — there is no
console to borrow and nothing inherited.
`tests/test_packaging.py` covers the choice; the Windows half of it is
**unverified**, because nothing here runs Windows.

**No data files.** `editor/character.ui` is compiled ahead of time into
`editor/ui_character.py`, and `wish/__main__.py` now skips the Designer
recompile when `tools.genui` is not importable — which it is not in a frozen
build, and which used to be an unconditional `ImportError` in an installed wheel
too. Settings and map notes live in the user's own directories
(`automap/paths.py`), never beside the executable.

`pyproject.toml` also gained `tools` to the wheel's package list: `wish-cli` is
declared as `tools.wish:main` and the window imports `tools.genui`, so without
it both entry points were broken in an installed wheel.

## Verification

| claim | how it stands |
|---|---|
| a tagged build reports the tag | verified — a throwaway clone tagged `v0.1.0` built `por_tools-0.1.0` |
| an untagged build does not claim to be a release | verified — `0.0.1.dev49+g…` |
| the Linux frozen build runs | verified — `wish --version` and the window both start from `dist/wish/wish` |
| the Linux tarball carries both executables | verified — `wish` 2.2 MB and `wish-cli` 1.7 MB beside one `_internal/`. The folder went 162.8 → 164.7 MB and the `.tar.gz` 61.2 → 62.9 MB: +1.1%, not the +100% a second Qt would have cost |
| the frozen `wish-cli` round-trips a save disk | verified — export and re-import of a `PORSAVE*.D64` came back byte-identical |
| the Windows zip ships no `wish-cli.exe` | **unverified as a build**; the spec's platform split is unit-tested in `tests/test_packaging.py` |
| `wish.exe --version` reaches a Windows terminal | **unverified.** `AttachConsole`/`CONOUT$` is standard practice and the fallbacks are tested on Linux, but nothing here runs Windows. A GUI-subsystem process returns the prompt before it prints, so the version may land under it |
| the Windows zip runs with no Python | **unverified.** There is no Windows machine here |
| the Linux build runs on another distribution | **unverified** |
| CI is green on a checkout with no game disks | **unverified as a whole**; locally, disks hidden, 539 pass and 30 skip |
| a release page carries every artefact | **unverified** — no tag has been pushed |

Two known failures waiting for CI, neither of them the packaging's:

* `docs/41-memory-regions.md` has four combat rows that `por/memory.py` does not
  generate, so the `generated` job fails until those regions are added to
  `por/memory.py` — which is exactly what that check is for.
* the suite segfaults about one run in three, in `findChild` inside
  `EditorWindow.__init__`. It bisects to `tests/test_debuglog.py`: with that file
  ignored, six consecutive runs are clean; with it, three runs in nine crashed.
  A red `test.yml` on a rerun-clean commit is that, not flaky infrastructure.
