"""What both acceptance drivers record about a run: the commit it ran on and the directory its evidence goes in.

    from tools.registry import evidence

    git = evidence.git_state(REPO)                      # {"sha": ..., "dirty": [...]}
    out = evidence.default_out("661", "bless", git["sha"])

`dirty` lists tracked files that differ from HEAD; untracked files are not
counted. A directory that is not a repository gives the sha `"unknown"`.
"""
from __future__ import annotations

import pathlib
import subprocess

from tools.registry import scratch


def git_state(repo: pathlib.Path) -> dict:
    """The HEAD sha of `repo` and the tracked files that differ from it.

    Status is read NUL-separated so paths arrive unquoted; each entry is two
    status characters, a space and the path, and a rename or copy is followed
    by its old path, which is skipped so the new path is the one reported.
    """
    def git(*args: str) -> str:
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        return r.stdout if r.returncode == 0 else ""
    entries = git("status", "--porcelain", "-z", "--untracked-files=no").split("\0")
    dirty = []
    skip = False
    for entry in entries:
        if skip:
            skip = False
        elif entry:
            dirty.append(entry[3:])
            skip = entry[0] in "RC" or entry[1] in "RC"
    return {"sha": git("rev-parse", "HEAD").strip() or "unknown", "dirty": dirty}


def default_out(issue: str, run: str, sha: str) -> pathlib.Path:
    """`<cache>/acceptance/<issue>/<sha10>-<run>`, not created."""
    return scratch.cache_dir("acceptance", issue, f"{sha[:10]}-{run}")
