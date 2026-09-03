# Versioning, packaging and CI

**Status: built and released.** Versioning, three workflows and a PyInstaller
spec are in the tree. `v0.1.0`, `v0.1.1` and `v0.1.2` have been tagged and
pushed, each with its own GitHub release page and PyPI upload.

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
reads; the installed metadata, asked for by the **distribution** name
`wish-goldbox`; and `0.0.0+unknown` for a source checkout that was never built.
`wish --version` prints it.

That metadata lookup has been stale twice — a leftover `por-tools` after the
first rename put `wish unknown` at the top of every debug log. `wish/debuglog.py`
now takes `wish.__version__` rather than asking metadata itself, and
`tests/test_packaging.py` checks the one remaining lookup against
`pyproject.toml`.

The window says the same number under **Help > About Wish** — `wish/about.py`,
installed from `wish/window.py`.

## 2. What a release contains

| audience | artefact |
|---|---|
| people with Python | the wheel, or PyPI — §5 |
| everyone else | a one-folder PyInstaller build |

The wheel is `wish_goldbox-<version>-py3-none-any.whl` and the sdist beside it
`wish_goldbox-<version>.tar.gz`: the distribution is **`wish-goldbox`**, and the
build backend spells the hyphen as an underscore in file names. Only the wheel
reaches the release page.

Linux gets `wish-<version>-linux-x86_64.tar.gz`, Windows
`wish-<version>-windows-x86_64.zip`. Not an AppImage, not an MSI, not a signed
exe: a certificate costs money and SmartScreen warns anyway, so the zip is
honest about what it is. macOS is "run it from source" until somebody with a Mac
wants to own an unsigned `.app`.

**Both archives carry one executable, and it is the same one.** `wish-cli`
shipped beside `wish` on Linux until [129-one-binary.md](129-one-binary.md)
folded it in as `wish export` and `wish import`; there is no platform
conditional left in `wish.spec` and nothing for a build to lose or to gain.

The Linux folder is about 157 MB before compression, three quarters of it Qt.
Dropping the second executable took it from 164.7 to 163.1 MB and the `.tar.gz`
from 62.9 to 61.3 MB.

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
`goldbox/layout.py` is the field documentation and its notes are meant to be read,
not wrapped to 88 columns; enabling it wanted 60 rewraps across files whose
prose is the point. `editor/ui_character.py` is excluded outright: pyuic6 writes
it.

Nothing else is on yet. `ruff format` and mypy on `goldbox/` remain the next
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
   with the `v` stripped. Both artefacts are uploaded, because `pypi` below
   wants the sdist; the release page's gather step takes the wheel, the `.zip`
   and only `*-x86_64.tar.gz`, so the sdist never lands on it.
3. `frozen`: Ubuntu and Windows, each building `wish.spec` on its own runner
   because PyInstaller does not cross-compile. `pip install -e .` first, because
   that is what writes `wish/_version.py` from the tag. Three smoke checks on
   the artefact, all asserting on **output** rather than an exit code, because
   the Windows build exits 0 in silence when its streams are broken:
   `--version` prints exactly `wish <tag>`; a mistyped option puts argparse's
   "unrecognized arguments" on stderr, which is the same path every diagnostic
   travels and needs no display; and, on both platforms, `dist/wish/` holds
   exactly one file beside `_internal/` and `wish export --help` prints its
   usage — which is the only check that reaches `tools.wish`, a hidden import
   PyInstaller's scan cannot find on its own.
4. `publish`: gathers the three shipped files, writes `SHA256SUMS`, and hands
   the lot to `softprops/action-gh-release` with `generate_release_notes`.
5. `pypi`: after `publish`, uploads the wheel and the sdist. §5.

## 4. The PyInstaller spec

`wish.spec`, one folder rather than one file: a one-file build unpacks itself to
a temporary directory at every start, which for a Qt application is a visible
pause and buys nothing a `.tar.gz` does not.

`packaging/wish_main.py` is the entry script, because a frozen build starts from
a script and the relative imports in `wish/__main__.py` only work inside the
package. It is the only one: `packaging/wish_cli_main.py` went with `wish-cli`.

One `Analysis`, one `EXE`, one `COLLECT`. `tools.wish` is named as a hidden
import because the subcommands reach it through an import inside `main()` that
no static scan follows, and `collect_submodules("tools")` is deliberately not
used — the rest of that directory is discovery scaffolding.

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

`pyproject.toml` also gained `tools` to the wheel's package list: `tools.wish`
is the body of the subcommands and the window imports `tools.genui`, so without
it both were broken in an installed wheel.

## 5. PyPI

**`pip install wish-goldbox` installs a command called `wish`.** The
distribution is `wish-goldbox` because `wish` on PyPI belongs to an unrelated
package from 2013. There is exactly one entry point, `wish`; `wish-cli`,
`wish-editor` and `wish-automap` were dropped in
[129-one-binary.md](129-one-binary.md).

Both the wheel and the sdist go to PyPI. The release page carries the wheel and
the two frozen builds and **no sdist of ours**: GitHub attaches its own "Source
code (zip)" and "Source code (tar.gz)" to every tag and neither can be renamed,
so ours would be a third source-looking download with a name close enough to
confuse. PyPI has no such problem and wants an sdist, so that is where it goes.

Publishing is **Trusted Publishing**, not a stored token: the `pypi` job mints a
short-lived OIDC token from the workflow itself, so there is no API token in the
repository to leak or to rotate. PyPI matches on the repository, the workflow
file name and the environment name — hence `environment: pypi` and
`permissions: id-token: write` in the job, and `pypa/gh-action-pypi-publish`
with no `password`. The publisher has to be registered on PyPI once before the
first tag, or the upload fails on an unrecognised token.

It runs on `v*` tags only and `needs: [publish]`, so a failed upload cannot
leave a half-made release page behind it.

## Verification

| claim | how it stands |
|---|---|
| a tagged build reports the tag | verified — a throwaway clone tagged `v0.1.0` built `wish-0.1.0` |
| an untagged build does not claim to be a release | verified — `0.0.1.dev49+g…` |
| the Linux frozen build runs | verified — `wish --version` and the window both start from `dist/wish/wish` |
| the Linux tarball carries exactly one executable | verified — `wish`, 2.29 MB, beside one `_internal/`. The folder is 163.1 MB and the `.tar.gz` 61.3 MB, back to what they were before `wish-cli` was added |
| the frozen `wish export` round-trips a save disk | verified — export and re-import of a `PORSAVE*.D64` came back byte-identical, `dist/wish/wish` on 2026-08-22 |
| the Windows zip carries the same one executable | **unverified as a build**; asserted in CI on both platforms and unit-tested in `tests/test_packaging.py` |
| `wish export` prints on Windows | **unverified, and nothing depends on it.** The build is windowed, so the subcommands' output goes through the console-borrowing path below — see [129-one-binary.md](129-one-binary.md) |
| `wish.exe --version` reaches a Windows terminal | **unverified.** `AttachConsole`/`CONOUT$` is standard practice and the fallbacks are tested on Linux, but nothing here runs Windows. A GUI-subsystem process returns the prompt before it prints, so the version may land under it |
| the Windows zip runs with no Python | **unverified.** There is no Windows machine here |
| the Linux build runs on another distribution | **unverified** |
| CI is green on a checkout with no game disks | **unverified as a whole**; locally, disks hidden, 539 pass and 30 skip |
| a release page carries every artefact | verified — `v0.1.2`'s GitHub release carries `SHA256SUMS`, the Linux tarball, the Windows zip and the wheel |
| the wheel and sdist come out named `wish_goldbox-*` | verified — `python3 -m build` on 2026-08-22 produced `wish_goldbox-0.0.1.dev173+gba225aeab.d20260822-py3-none-any.whl` and the matching `.tar.gz` |
| Trusted Publishing uploads to PyPI | verified — `wish-goldbox` on PyPI carries `0.1.0`, `0.1.1` and `0.1.2` |

Two known failures waiting for CI, neither of them the packaging's:

* `docs/41-memory-regions.md` has four combat rows that `goldbox/memory.py` does not
  generate, so the `generated` job fails until those regions are added to
  `goldbox/memory.py` — which is exactly what that check is for.
* the suite segfaults about one run in three, in `findChild` inside
  `EditorWindow.__init__`. It bisects to `tests/test_debuglog.py`: with that file
  ignored, six consecutive runs are clean; with it, three runs in nine crashed.
  A red `test.yml` on a rerun-clean commit is that, not flaky infrastructure.
