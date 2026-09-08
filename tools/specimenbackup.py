#!/usr/bin/env python3
"""How many copies of the specimen tree exist, and how to make one more.

`tools/specimens.py` answers "are these still the bytes we recorded".  This
answers the other question `#249 (Build a DOS party from creation and level it
ourselves, so DOS measurements rest on records we watched being written)` step
5 asks -- *somewhere durable to keep it* -- which is "how many places do these
bytes exist at all, and what happens to the evidence if this machine's home
directory goes".

Three commands, none of which decides where a copy should live:

    tools/specimenbackup.py audit                 # what already covers the tree
    tools/specimenbackup.py audit --tar SNAP.tar.zst
    tools/specimenbackup.py archive /somewhere/wish-specimens-2026-09-08.tar.gz
    tools/specimenbackup.py verify /somewhere/wish-specimens-2026-09-08.tar.gz

**`audit` matches on content, never on a filename.**  A specimen's bytes
routinely sit in the run directory they were copied out of under a different
name -- `work/issue249/ladder4/rung2/party/CHRDATC1.SAV` against
`~/wish-specimens/por-dos/WISH-SPEC-por-party-ladder-rung8/CHRDATC1.SAV` --
and a name match would also count a file that had been edited since.  So every
candidate is hashed and compared against the SHA-256 the specimen's own
`provenance.toml` records.

**A copy under `work/` is not a backup**, and the audit says so rather than
counting it as one: `work/` is gitignored, has been lost twice, and is a run's
output rather than storage (`.claude/rules/scratch.md`).  It is reported
because it is what an hourly snapshot of `work/` happens to carry, which is a
fact about how much of the tree could be reconstructed today -- not a fact
about where the tree should live.

**`archive` refuses a destination inside this repository**, `work/` included.
The game's data must never be committed, and an archive whose whole purpose is
to outlive the working tree has no business inside it.  It also refuses to run
at all when `specimens.check_specimens` reports a problem, because an archive
of a tree that no longer matches its manifests preserves the damage.

**`verify` reads the archive and nothing else** -- it never extracts, and it
compares each member against the live `provenance.toml`, so it answers "could
this archive put the evidence back" rather than "did tar exit zero".
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import shutil
import subprocess
import sys
import tarfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import specimens  # noqa: E402

#: Suffixes `audit --tar` and `verify` know how to stream.  `.zst` is here
#: because the hourly snapshot of `work/` on this machine is zstd, and reading
#: one through `zstd -dc` costs no temporary copy of 1.5 GB.
ZSTD_SUFFIXES = (".zst", ".zstd")


class Coverage:
    """One audit's answer: which recorded hashes were found somewhere else."""

    def __init__(self, wanted: dict[str, list[tuple[str, str]]]):
        #: hash -> [(specimen name, file name), ...]
        self.wanted = wanted
        #: hash -> where the second copy was seen
        self.found: dict[str, str] = {}

    def offer(self, digest: str, where: str) -> None:
        if digest in self.wanted and digest not in self.found:
            self.found[digest] = where

    @property
    def missing(self) -> list[str]:
        return [h for h in self.wanted if h not in self.found]

    def per_specimen(self) -> dict[str, tuple[int, int]]:
        """specimen name -> (files with a second copy, files recorded)."""
        out: dict[str, list[int]] = {}
        for digest, entries in self.wanted.items():
            for name, _fname in entries:
                row = out.setdefault(name, [0, 0])
                row[1] += 1
                if digest in self.found:
                    row[0] += 1
        return {k: (v[0], v[1]) for k, v in out.items()}


def recorded_hashes(root: pathlib.Path | None = None) -> dict[str, list[tuple[str, str]]]:
    """Every hash the tree's `provenance.toml` files record, to the specimens
    and file names carrying it.

    Keyed by hash rather than by path because two specimens sharing a byte-
    identical file -- a ladder rung whose `.SPC` never changed, say -- are one
    thing to find a second copy of, not two.
    """
    root = root or specimens.tree_root()
    wanted: dict[str, list[tuple[str, str]]] = {}
    for entry in specimens.list_specimens(root):
        if entry.get("_no_provenance"):
            continue
        name = entry.get("name", "?")
        for fname, digest in entry.get("sha256", {}).items():
            wanted.setdefault(digest, []).append((name, fname))
    return wanted


def _stream_tar(path: pathlib.Path):
    """A `tarfile` stream over a plain, gzipped or zstd-compressed archive.

    Returns `(tar, closer)`; the caller closes both.  zstd goes through the
    `zstd` binary because the `zstandard` module is not installed here, and a
    stream costs no temporary copy.
    """
    if path.suffix in ZSTD_SUFFIXES:
        if shutil.which("zstd") is None:
            raise RuntimeError(f"{path} needs zstd on the path to read")
        proc = subprocess.Popen(["zstd", "-dc", str(path)],
                                stdout=subprocess.PIPE)
        return tarfile.open(fileobj=proc.stdout, mode="r|"), proc
    return tarfile.open(path, mode="r|*"), None


def _close_tar(tar, proc) -> None:
    tar.close()
    if proc is not None:
        if proc.stdout is not None:
            proc.stdout.close()
        proc.wait()


def audit(root: pathlib.Path | None = None, *,
          directories: list[pathlib.Path] | None = None,
          archives: list[pathlib.Path] | None = None) -> Coverage:
    """Where else on this machine each specimen file's bytes exist.

    Every regular file under each directory, and every member of each archive,
    is hashed and offered to the coverage.  Nothing is written and nothing in
    the tree is touched.
    """
    root = root or specimens.tree_root()
    cov = Coverage(recorded_hashes(root))
    root = root.resolve()
    for directory in directories or []:
        for path in directory.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if root in path.resolve().parents:
                continue  # the tree is not a second copy of itself
            try:
                digest = specimens.sha256_file(path)
            except OSError:
                continue
            cov.offer(digest, str(path))
    for archive_path in archives or []:
        tar, proc = _stream_tar(archive_path)
        try:
            for member in tar:
                if not member.isfile():
                    continue
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                h = hashlib.sha256()
                while chunk := handle.read(1 << 20):
                    h.update(chunk)
                cov.offer(h.hexdigest(), f"{archive_path}::{member.name}")
        finally:
            _close_tar(tar, proc)
    return cov


def archive(dest: pathlib.Path, root: pathlib.Path | None = None) -> dict:
    """Write the whole tree to `dest`, and report what went in.

    Refuses a destination that exists, one inside this repository, and a tree
    that does not match its own manifests.
    """
    root = root or specimens.tree_root()
    if not root.is_dir():
        raise FileNotFoundError(f"no specimen tree at {root}")
    dest = dest.expanduser()
    if dest.exists():
        raise FileExistsError(f"{dest} exists; archives are never overwritten")
    resolved = dest.resolve() if dest.is_absolute() else (
        pathlib.Path.cwd() / dest).resolve()
    if REPO == resolved or REPO in resolved.parents:
        raise ValueError(
            f"{dest} is inside {REPO}; a copy of the specimen tree does not "
            "go in the repository, work/ included -- it holds the game's data "
            "and its whole purpose is to outlive this working tree")
    problems = specimens.check_specimens(root)
    if problems:
        raise ValueError("the tree does not match its manifests, so an "
                         "archive of it would preserve the damage:\n  "
                         + "\n  ".join(problems))
    files = sorted(p for p in root.rglob("*") if p.is_file())
    dest.parent.mkdir(parents=True, exist_ok=True)
    mode = "w:gz" if dest.suffix in (".gz", ".tgz") else "w"
    with tarfile.open(dest, mode) as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(root)))
    return {"dest": dest, "files": len(files),
            "specimens": len([e for e in specimens.list_specimens(root)
                              if not e.get("_no_provenance")]),
            "bytes": dest.stat().st_size}


def verify(archive_path: pathlib.Path,
           root: pathlib.Path | None = None) -> list[str]:
    """Check an archive against the live tree's manifests.

    Returns one line per problem: a recorded file the archive does not hold at
    the hash `provenance.toml` records.  An empty list means every specimen in
    the tree could be put back from this archive.
    """
    root = root or specimens.tree_root()
    inside: dict[str, str] = {}
    tar, proc = _stream_tar(archive_path)
    try:
        for member in tar:
            if not member.isfile():
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            h = hashlib.sha256()
            while chunk := handle.read(1 << 20):
                h.update(chunk)
            inside[member.name.lstrip("./")] = h.hexdigest()
    finally:
        _close_tar(tar, proc)
    problems = []
    for entry in specimens.list_specimens(root):
        if entry.get("_no_provenance"):
            continue
        name = entry.get("name", "?")
        base = entry["_provenance"].parent.relative_to(root)
        for fname, digest in entry.get("sha256", {}).items():
            arcname = str(base / fname)
            if arcname not in inside:
                problems.append(f"{name}: {arcname} is not in the archive")
            elif inside[arcname] != digest:
                problems.append(
                    f"{name}: {arcname} in the archive is not the recorded "
                    f"bytes -- {digest[:12]} recorded, {inside[arcname][:12]} "
                    "in the archive")
    return problems


# --- the command line -------------------------------------------------------


def cmd_audit(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root) if args.root else specimens.tree_root()
    directories = [pathlib.Path(d) for d in (args.into or [])]
    if not directories and not args.tar:
        directories = [REPO / "work"]
    archives = [pathlib.Path(a) for a in (args.tar or [])]
    cov = audit(root, directories=directories, archives=archives)
    where = ", ".join(str(d) for d in directories + archives)
    print(f"{len(cov.wanted)} distinct file contents recorded in {root}")
    print(f"{len(cov.found)} of them have a second copy in {where}")
    missing = cov.missing
    print(f"{len(missing)} exist nowhere but the tree itself")
    per = cov.per_specimen()
    short = {n: (f, t) for n, (f, t) in per.items() if f < t}
    if short:
        print("\nspecimens not wholly covered:")
        for name in sorted(short):
            found, total = short[name]
            print(f"  {name:<44} {found:>3} of {total:>3} files")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root) if args.root else specimens.tree_root()
    try:
        result = archive(pathlib.Path(args.dest), root)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{result['specimens']} specimen(s), {result['files']} file(s), "
          f"{result['bytes']} bytes -> {result['dest']}")
    print("check it with: tools/specimenbackup.py verify "
          f"{result['dest']}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root) if args.root else specimens.tree_root()
    problems = verify(pathlib.Path(args.archive), root)
    if problems:
        for line in problems:
            print(line)
        print(f"{len(problems)} problem(s)")
        return 1
    total = len([e for e in specimens.list_specimens(root)
                 if not e.get("_no_provenance")])
    print(f"every file of all {total} specimen(s) is in the archive at the "
          "hash its provenance records")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", help="the specimen tree "
                        "(default $WISH_SPECIMENS or ~/wish-specimens)")
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("audit", help="where else the tree's bytes exist")
    a.add_argument("--in", dest="into", action="append",
                   help="a directory to search (default: the repository's work/)")
    a.add_argument("--tar", action="append",
                   help="an archive to search; .zst is read through zstd")
    a.set_defaults(func=cmd_audit)

    b = sub.add_parser("archive", help="write the whole tree to one archive")
    b.add_argument("dest", help="destination, outside this repository")
    b.set_defaults(func=cmd_archive)

    c = sub.add_parser("verify", help="check an archive against the manifests")
    c.add_argument("archive")
    c.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
