#!/usr/bin/env python3
"""One registry for where the game disks and saves are (#212).

Before this there were seven searches in six files, most of them alive only
inside one test module -- so a tool could not ask the question a test already
knew the answer to, and `#211 (103 tests skip on the machine that has the game
files, and the game files are not why)` found four Amiga tests skipping
against disks that had been on the machine the whole time.

Three layers, highest precedence first:

1. `$POR_DISKS` and its siblings -- unchanged, and still highest. One-off runs
   and CI keep working exactly as they do today. Taken *whole*: scoping it to
   a subdirectory is the caller's business, not this module's.
2. `gamedisks.local.toml`, gitignored -- where somebody who clones this
   repository says where their own disks are, without editing a tracked file.
3. `gamedisks.toml`, committed -- the search list this project ships, one
   entry per game or dataset, each a list of candidate paths tried in order.

    tools/gamedisks.py            one row per entry: variable, layer, path,
                                  found -- turns "103 skipped" into a question
                                  anybody can answer in a second

Every path is `~`-expanded so the same file works on any machine; nothing here
is Linux-specific.

**This is ours, and `automap/paths.py` is the player's. They are separate on
purpose and must stay that way.** Donald, 2026-09-04: *"gamedisks.toml is for
our tests and our tools and our reverse-engineering. It's not for the end
user. It's not getting shipped in the release package."*

So the two lookups answer two different questions:

* `automap.paths.resolve_disks()` answers **where this player keeps their
  disks** -- the Game directory they set in Preferences, the folder beside the
  save they opened, the command-line flag. `wish/__main__.py`,
  `editor/files.py`, `automap/maps.py` and `automap/actions.py` all go through
  it, and `#22 (A disk folder setting per game, not one shared by all six)` is
  the ticket that gives it one answer per title.
* This module answers **where the seven games are on a machine running the
  test suite or a reverse-engineering tool**, so a specimen is never known
  only inside one test file again.

Nothing under `automap/`, `editor/`, `goldbox/`, `wish/` or `ui/` imports this
module, and nothing should. `gamedisks.toml` sits at the repository root with
no package-data entry, so it is not in a wheel at all: shipped code calling
`find()` would get a silent nothing on a player's machine, which is the worst
shape a lookup can fail in.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tomllib

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMITTED = REPO / "gamedisks.toml"
LOCAL = REPO / "gamedisks.local.toml"

ENV, GLOB, PATHS = "env", "glob", "paths"


def _load(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _committed() -> dict:
    """Re-read every call: this is a developer tool, not a hot path, and a
    cache would hide an edit to `gamedisks.toml` made mid-session."""
    return _load(COMMITTED)


def _local() -> dict:
    return _load(LOCAL)


def names() -> list[str]:
    """Every entry this project ships a search list for."""
    return list(_committed().keys())


def entry(name: str) -> dict:
    """The committed row for `name`, with `gamedisks.local.toml`'s own paths
    tried before the committed ones."""
    row = dict(_committed().get(name, {}))
    local_row = _local().get(name, {})
    if local_row:
        row[ENV] = local_row.get(ENV, row.get(ENV))
        row[GLOB] = local_row.get(GLOB, row.get(GLOB))
        row[PATHS] = list(local_row.get(PATHS, [])) + list(row.get(PATHS, []))
    return row


def candidates(name: str) -> list[pathlib.Path]:
    """Where to look for `name`'s data, highest precedence first.

    `$<env>` wins outright, taken as the one candidate -- as `automap.paths`
    already does for `$POR_DISKS`. With no environment variable, every path
    from `gamedisks.local.toml` comes before every path from `gamedisks.toml`,
    each `~`-expanded and de-duplicated in the order first seen.
    """
    row = entry(name)
    var = row.get(ENV)
    if var:
        value = os.environ.get(var)
        if value:
            return [pathlib.Path(value).expanduser()]
    seen: dict[pathlib.Path, None] = {}
    for raw in row.get(PATHS, []):
        seen.setdefault(pathlib.Path(raw).expanduser(), None)
    return list(seen)


def _matches(path: pathlib.Path, globs) -> bool:
    """Does this directory hold the data `name` names, going by its globs?

    No globs means the entry only names a directory, not a file inside it --
    `dos-archives` is like this, because every DOS Gold Box title writes its
    own file names underneath and there is no one pattern for all of them.
    """
    try:
        if not path.is_dir():
            return False
        if not globs:
            return True
        return any(next(path.glob(g), None) is not None for g in globs)
    except OSError:
        return False


def find(name: str) -> pathlib.Path | None:
    """The first candidate that actually holds `name`'s data, or None."""
    row = entry(name)
    for path in candidates(name):
        if _matches(path, row.get(GLOB)):
            return path
    return None


def report() -> list[tuple[str, str, str, str, bool]]:
    """One row per entry: name, variable, which layer answered, path, found.

    "Layer" is `$VAR` when the environment variable is what is set, the file
    name of whichever `.toml` supplied the winning path, or "none" when
    nothing resolves -- which is correct for `amiga-por-saves` and
    `pod-saves` until somebody plays far enough to export one (#211).
    """
    rows = []
    for name in names():
        row = entry(name)
        var = row.get(ENV, "")
        env_value = os.environ.get(var) if var else None
        if env_value:
            path, layer = pathlib.Path(env_value).expanduser(), f"${var}"
        else:
            local_paths = [pathlib.Path(p).expanduser()
                           for p in _local().get(name, {}).get(PATHS, [])]
            committed_paths = [pathlib.Path(p).expanduser()
                               for p in _committed().get(name, {})
                               .get(PATHS, [])]
            path, layer = None, "none"
            for candidate_path, candidate_layer in (
                    [(p, "gamedisks.local.toml") for p in local_paths]
                    + [(p, "gamedisks.toml") for p in committed_paths]):
                if _matches(candidate_path, row.get(GLOB)):
                    path, layer = candidate_path, candidate_layer
                    break
            if path is None:
                rest = local_paths + committed_paths
                path = rest[0] if rest else None
        found = path is not None and _matches(path, row.get(GLOB))
        rows.append((name, var, layer, str(path) if path else "-", found))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    rows = report()
    if not rows:
        print(f"no entries in {COMMITTED}")
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
