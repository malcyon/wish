# Versioning, packaging and CI — plan

**Status: planned, not started.** Versioning has to land before packaging: an
artefact nobody can name is an artefact nobody can report a bug against.

---

## 1. Versioning

**Semantic versioning, single source, derived from the tag.**

`pyproject.toml` currently hardcodes `version = "0.1.0"`, which will drift from
the tag the moment anyone forgets. Use `hatch-vcs` (this project already builds
with hatchling): the version comes from the git tag, and a build from an
untagged commit gets a development version automatically.

* `wish.__version__` is what the About box and the debug log report.
* Tags are `v0.2.0`. The tag is the release trigger.
* Start at **0.x**, and say plainly in the README that the save format work is
  still moving. 1.0 means the editor's field set is stable, not that the
  reverse engineering is finished.

## 2. What a release contains

Two ways to run it, as decided:

| audience | artefact |
|---|---|
| people with Python | `pip install` from the tagged source, or the wheel |
| everyone else | a self-contained build from PyInstaller |

**Formats, and the recommendation:**

* **Linux — a `.tar.gz` of a PyInstaller one-folder build.** Not an AppImage to
  begin with: it is more machinery than a project this size needs, and the
  audience is people who already own a C64 emulator.
* **Windows — a `.zip`, not an installer.** An `.msi` or a signed `.exe` costs a
  code-signing certificate, and without one Windows SmartScreen warns anyway. A
  zip the user unpacks is honest about what it is. Revisit if people ask.
* **macOS — later, or never.** An unsigned `.app` is actively hostile to open
  on modern macOS. Say "run it from source" until somebody with a Mac wants to
  own that.
* **The wheel and the sdist**, attached to the release and optionally pushed to
  PyPI.

Every artefact carries the version in its filename. Attach a `SHA256SUMS` file.

## 3. CI

**GitHub Actions**, three workflows:

**`test.yml`** — on every push and pull request. A matrix of Ubuntu and Windows
against the supported Python versions. Installs the `dev` and `gui` extras, runs
`pytest`. **The 27 tests that need the game's disks skip there, and that is
expected** — `tests/gamedata.py` skips cleanly when no disks are found, and
`tests/test_repository_contents.py` makes sure none are ever committed to make
them run. Run the real ones locally.

PyQt needs a display on Linux: either `QT_QPA_PLATFORM=offscreen` or run the job
under `xvfb-run`. The test suite already runs offscreen.

**`lint.yml`** — the linters below.

**`release.yml`** — on a `v*` tag. Builds the wheel and sdist, then the
PyInstaller artefacts on each platform's own runner (PyInstaller does not
cross-compile), checksums them, and creates the GitHub release with the notes
from the tag. `softprops/action-gh-release` does the last step in a few lines.

## 4. Linters worth having

Ordered by value for this codebase:

| tool | why here |
|---|---|
| **ruff** | one fast tool covering pyflakes, pycodestyle, isort, pyupgrade and more. Start with its defaults plus the import rules; the codebase is already close to them |
| **ruff format** | or `black`. Pick one and stop discussing it |
| **mypy** | the record and layout code is full of `int \| None` and typed dataclasses, which is where a type checker earns its keep. Start non-strict on `por/` only |

Two more worth a thought and probably a no for now: **bandit** (a
reverse-engineering tool that reads files and opens sockets will trip it
constantly) and **vulture** (dead-code detection would flag the deliberately
unused format constants that document the file layout).

**Add `tools/gendocs.py --check`, `tools/genui.py --check` and
`tools/genmemory.py` to CI.** The generated docs and the compiled `.ui` drifting
from their sources is a failure this project can actually have, and it is
already checkable.

## 5. Order of work

1. Version from the tag; `wish --version`; About box.
2. `test.yml`, because everything else is worth less without it.
3. `lint.yml`, with ruff only, and fix what it finds in one commit.
4. PyInstaller spec, working locally on Linux first.
5. `release.yml` and a `v0.1.0` tag as a dry run.
6. mypy on `por/`, once the rest is quiet.

## Verification

* A tagged build reports the tag as its version, and an untagged one does not
  claim to be a release.
* The Windows zip runs on a machine with no Python.
* The Linux build runs on a distribution other than the one that built it.
* CI is green on a checkout with no game disks, with 27 skips and no failures.
* A release page carries every artefact, its checksums, and notes.
