"""Where a tool writes what it produces, and where what must outlive a reboot goes.

    from tools.registry import scratch

    out = scratch.scratch_dir("dosbox", "shots")   # <tmp>/wish/dosbox/shots
    scratch.ensure(out)                            # only when about to write
    keep = scratch.cache_dir("testrun")            # ~/.cache/wish/testrun

Scratch is under `tempfile.gettempdir()`, in one directory per tool named for
the tool, never for a ticket. It may vanish at any time -- a reboot, a tmp
cleaner, somebody's `rm -rf` -- and a tool must work again from nothing when it
does. Anything worth keeping is committed, or is game data and lives where
`gamedisks.yaml` says.

The cache is for the few things that have to survive a reboot: the record an
on-request `tools/suite/suiterun.py` diagnostic leaves, which nothing requires
or reads, and nothing that a person would want to read later.  The emulator instance pool is there too, for a different reason:
the flatpak VICE sees `$HOME` and has a private `/tmp`, so a disk staged under
the temp directory is one it cannot open.

Neither function creates anything. A tool makes its output directory with
`ensure` at the point it is about to write, so `--help`, a refused argument and
a dry run leave the disk as they found it.
"""
from __future__ import annotations

import pathlib
import tempfile

#: The one directory under the temp directory that every tool's scratch is in,
#: so it is a single thing to find and to remove.
ROOT_NAME = "wish"


def _plain(name: str) -> str:
    """A single path segment, so a caller cannot climb out of its own directory."""
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"not a plain directory name: {name!r}")
    return name


def scratch_dir(tool: str, *parts: str) -> pathlib.Path:
    """`<tmp>/wish/<tool>/<parts...>`. Not created."""
    return pathlib.Path(tempfile.gettempdir(), ROOT_NAME, _plain(tool),
                        *[_plain(p) for p in parts])


def cache_dir(*parts: str) -> pathlib.Path:
    """`~/.cache/wish/<parts...>`. Not created."""
    return pathlib.Path.home().joinpath(".cache", ROOT_NAME,
                                        *[_plain(p) for p in parts])


def ensure(path: pathlib.Path | str) -> pathlib.Path:
    """Create `path` and its parents if they are missing; return it.

    Call it immediately before the first write, not at start-up.
    """
    path = pathlib.Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
