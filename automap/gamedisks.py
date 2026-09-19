#!/usr/bin/env python3
"""One registry for where the game disks and saves are (#212).

Before this there were seven searches in six files, most of them alive only
inside one test module -- so a tool could not ask the question a test already
knew the answer to, and `#211 (103 tests skip on the machine that has the game
files, and the game files are not why)` found four Amiga tests skipping
against disks that had been on the machine the whole time.

Two layers, highest precedence first:

1. `$POR_DISKS` and its siblings -- unchanged, and still highest. One-off runs
   and CI keep working exactly as they do today, with or without a
   `gamedisks.yaml`: the variable's name is read from the example when the
   machine has no file. Taken *whole*: scoping it to a subdirectory is the
   caller's business, not this module's.
2. `gamedisks.yaml`, gitignored and the only file this module reads -- one
   machine's own list of where its data is, one entry per game or dataset,
   each a list of candidate paths tried in order. `gamedisks.yaml.example` is
   committed and is the whole registry: every entry, its variable, its glob and
   the comment saying what the dataset is. Somebody who clones this repository
   copies the example to `gamedisks.yaml` and edits the paths. With the example
   but no `gamedisks.yaml` the loader stops with a one-line message saying so,
   rather than quietly finding nothing; with neither file, as on a player's
   machine, it has no entries and finds nothing without raising.

    python -m automap.gamedisks            one row per entry: variable, layer, path,
                                  found -- turns "103 skipped" into a question
                                  anybody can answer in a second

Every path is `~`-expanded so the same file works on any machine; nothing here
is Linux-specific.

**This is the registry of where the test suite and the reverse-engineering
tools find their data; it is not where the player's disks are.**
`automap.paths.resolve_disks()` answers that -- the Game directory the player
set in Preferences, the folder beside the save they opened, the command-line
flag. `automap.paths.disk_candidates()` asks this module for a title's
candidates after `$POR_DISKS` and before its home-folder guesses, and a
missing `gamedisks.yaml`, a missing entry or a missing `yaml` module leaves
the home-folder guesses as they were.

`gamedisks.yaml` sits at the repository root with no package-data entry, so a
wheel does not carry it: shipped code calling `find()` on a player's machine
gets nothing, and must treat that as "not registered" rather than as an error.
This module imports nothing from `tools/`.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = REPO / "gamedisks.yaml"
EXAMPLE = REPO / "gamedisks.yaml.example"

ENV, GLOB, PATHS = "env", "glob", "paths"


class RegistryError(SystemExit):
    """The registry cannot be used. A `SystemExit`, so a tool that asks it stops
    with the one line and no traceback."""


class RegistryMissing(RegistryError):
    """`gamedisks.yaml` is not there."""


def _load(path: pathlib.Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
    except yaml.YAMLError as err:
        first = str(err).splitlines()[0] if str(err) else "not valid YAML"
        raise RegistryError(f"{path.name} is not valid YAML ({first}); compare "
                            f"it with {EXAMPLE.name}") from None
    if not isinstance(loaded, dict):
        raise RegistryError(f"{path.name} must be a mapping of entry names to "
                            f"entries; compare it with {EXAMPLE.name}")
    return loaded


def _example() -> dict:
    """The committed example's entries; none where the checkout has no example,
    which is every installed copy: neither file ships in a wheel."""
    return _load(EXAMPLE) if EXAMPLE.is_file() else {}


def _registry() -> dict:
    """Re-read every call: this is a developer tool, not a hot path, and a
    cache would hide an edit to `gamedisks.yaml` made mid-session.

    With neither `gamedisks.yaml` nor the example there is nothing to copy and
    nothing to look up, so the registry is empty rather than a stop."""
    if not REGISTRY.is_file() and not EXAMPLE.is_file():
        return {}
    if not REGISTRY.is_file():
        raise RegistryMissing(
            f"{REGISTRY.name} is missing: copy {EXAMPLE.name} to "
            f"{REGISTRY.name} and edit the paths")
    return _load(REGISTRY)


def _as_list(value) -> list[str]:
    """A hand-edited `paths: /one/path` is one path, not a list of letters."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if v is not None]


def _row(name: str) -> dict:
    """`name`'s row from this machine's `gamedisks.yaml`, stopping with the one
    line when there is none. A machine whose file was copied before the entry
    existed gets the example's row, so a new entry works without an edit."""
    machine = _registry()
    return dict(machine.get(name) or _example().get(name) or {})


def _env_value(name: str) -> str | None:
    """`$<env>` for `name`, when it is set -- known from the machine's row, or
    from the committed example's when the machine has no row for it, so a
    one-off run with `$POR_DISKS` set works on a checkout that has not copied
    the example yet."""
    row = None
    if REGISTRY.is_file():
        row = _load(REGISTRY).get(name)
    var = (row or {}).get(ENV) or (
        _example().get(name) or {}).get(ENV)
    return os.environ.get(var) if var else None


def _globs(name: str) -> list[str]:
    row = None
    if REGISTRY.is_file():
        row = _load(REGISTRY).get(name)
    if row is None:
        row = _example().get(name)
    return _as_list((row or {}).get(GLOB))


def names() -> list[str]:
    """Every entry this machine's registry has a search list for."""
    return list(_registry().keys())


def entry(name: str) -> dict:
    """The registry row for `name`, or an empty one."""
    return _row(name)


def candidates(name: str) -> list[pathlib.Path]:
    """Where to look for `name`'s data, highest precedence first.

    `$<env>` wins outright, taken as the one candidate -- as `automap.paths`
    already does for `$POR_DISKS`, and even where there is no `gamedisks.yaml`.
    With no environment variable, every path from `gamedisks.yaml`, each
    `~`-expanded and de-duplicated in the order first seen.
    """
    value = _env_value(name)
    if value:
        return [pathlib.Path(value).expanduser()]
    seen: dict[pathlib.Path, None] = {}
    for raw in _as_list(_row(name).get(PATHS)):
        seen.setdefault(pathlib.Path(raw).expanduser(), None)
    return list(seen)


def _matches(path: pathlib.Path, globs) -> bool:
    """Does this directory hold the data `name` names, going by its globs?

    No globs means the entry only names a directory, not a file inside it --
    `dos-archives` is like this, because every DOS Gold Box title writes its
    own file names underneath and there is no one pattern for all of them.
    Such an entry is found only when the directory holds something: an empty
    one is a place somebody made and never filled, and answering "found" for it
    turned a skip into a `SystemExit` ("no CHEAD.DAX under .../dos-archives").
    """
    try:
        if not path.is_dir():
            return False
        if not globs:
            return next(path.iterdir(), None) is not None
        return any(next(path.glob(g), None) is not None for g in globs)
    except OSError:
        return False


def find(name: str) -> pathlib.Path | None:
    """The first candidate that actually holds `name`'s data, or None."""
    globs = _globs(name)
    for path in candidates(name):
        if _matches(path, globs):
            return path
    return None


def where(name: str) -> pathlib.Path:
    """`find(name)`, or the first place it would be looked for.

    For a module that needs *a* path at import time and reports a missing
    directory itself, naming the place to put it. Never `None`, never an
    `IndexError` for an entry with no paths."""
    return (find(name) or next(iter(candidates(name)), None)
            or pathlib.Path("/data/agent-disks") / name)


def report() -> list[tuple[str, str, str, str, bool]]:
    """One row per entry: name, variable, which layer answered, path, found.

    "Layer" is `$VAR` when the environment variable is what is set,
    `gamedisks.yaml` when one of its paths answered, or "none" when nothing
    resolves -- which is correct for an entry whose data nobody has made yet.
    """
    rows = []
    for name in names():
        row = entry(name)
        var = row.get(ENV, "")
        env_value = os.environ.get(var) if var else None
        if env_value:
            path, layer = pathlib.Path(env_value).expanduser(), f"${var}"
        else:
            listed = candidates(name)
            path, layer = None, "none"
            for candidate_path in listed:
                if _matches(candidate_path, _globs(name)):
                    path, layer = candidate_path, REGISTRY.name
                    break
            if path is None and listed:
                path = listed[0]
        found = path is not None and _matches(path, _globs(name))
        rows.append((name, var, layer, str(path) if path else "-", found))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    rows = report()
    if not rows:
        print(f"no entries in {REGISTRY}")
        return 1
    name_w = max(len(r[0]) for r in rows)
    var_w = max(len(r[1]) for r in rows)
    layer_w = max(len(r[2]) for r in rows)
    for name, var, layer, path, found in rows:
        mark = "found" if found else "missing"
        print(f"{name.ljust(name_w)}  {var.ljust(var_w)}  "
              f"{layer.ljust(layer_w)}  {mark:<7}  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
