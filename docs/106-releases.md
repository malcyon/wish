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

**Not done:** the About box. `wish/about.py` holds the dialog and an
`install(window)` that adds Help > About, but nothing calls it — wiring it needs
two lines in `wish/window.py`, which was being edited by another agent at the
time.

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

The Linux folder is about 156 MB before compression, three quarters of it Qt.

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

1. `dist`: `python -m build`, then a check that the wheel's version is the tag
   with the `v` stripped.
2. `frozen`: Ubuntu and Windows, each building `wish.spec` on its own runner
   because PyInstaller does not cross-compile. `pip install -e .` first, because
   that is what writes `wish/_version.py` from the tag.
3. `publish`: gathers both, writes `SHA256SUMS`, and hands the lot to
   `softprops/action-gh-release` with `generate_release_notes`.

## 4. The PyInstaller spec

`wish.spec`, one folder rather than one file: a one-file build unpacks itself to
a temporary directory at every start, which for a Qt application is a visible
pause and buys nothing a `.tar.gz` does not.

`packaging/wish_main.py` is the entry script, because a frozen build starts from
a script and the relative imports in `wish/__main__.py` only work inside the
package.

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
