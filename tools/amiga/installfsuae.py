#!/usr/bin/env python3
"""Install the patched FS-UAE that `tools/amiga/fsuaegdb.py` drives, and print where it went.

    tools/amiga/installfsuae.py
    tools/amiga/installfsuae.py --into DIR

The patched emulator (`grahambates/fs-uae`, the GDB-remote build) has no release
of its own.  Its author ships a build inside the npm package `uae-dap`, and an
npm tarball is an ordinary gzipped tar at a fixed URL, so this fetches that one
file over HTTPS -- no Node -- checks it against the pinned SHA-256 below, and
unpacks only `package/bin/fs-uae/` into a per-user directory.  Linux on x86-64
only: that is the only build in the tarball that runs here.

A download whose digest differs is deleted and nothing is unpacked, and a tar
member that would land outside the target directory refuses the whole archive.
A second run with the binary already in place does nothing and says so.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import platform
import posixpath
import shutil
import sys
import tarfile
import tempfile
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from automap import paths  # noqa: E402

VERSION = "1.1.5"
URL = f"https://registry.npmjs.org/uae-dap/-/uae-dap-{VERSION}.tgz"

#: SHA-256 of that tarball (33,513,452 bytes), taken from one download; the
#: registry's own SHA-1 for it, `4f0a28cc...`, matched.  A new `VERSION` needs
#: this recomputed by hand -- it is the whole of what makes the download safe.
SHA256 = "2a229f77d7b27373e1a06949287b4995a0930355aa74e8953c39bfcc4caf4b94"

#: The only part of the tarball that is unpacked; the rest is the debug adapter.
MEMBER_ROOT = "package/bin/fs-uae/"
BINARY = "fs-uae-linux_x64"


def default_dir() -> pathlib.Path:
    """Beside Wish's own per-user data, in a directory named for the version."""
    return paths.data_dir() / "fs-uae" / f"uae-dap-{VERSION}"


def sha256_of(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_digest(path: pathlib.Path, expected: str = SHA256) -> None:
    """Delete `path` and raise if it is not the tarball that was pinned."""
    found = sha256_of(path)
    if found != expected:
        path.unlink()
        raise ValueError(f"SHA-256 is {found}, not the pinned {expected}; "
                         "the download was deleted")


def wanted_members(archive: tarfile.TarFile) -> list[tuple[tarfile.TarInfo, str]]:
    """The members under `MEMBER_ROOT`, each with its path below it.

    Every member is checked, wanted or not: a tarball with one that would leave
    the target directory is refused whole rather than trimmed.
    """
    wanted = []
    for member in archive.getmembers():
        name = posixpath.normpath(member.name)
        if name.startswith("/") or name == ".." or name.startswith("../"):
            raise ValueError(f"{member.name!r} would leave the target directory")
        if not (name + "/").startswith(MEMBER_ROOT):
            continue
        if not (member.isreg() or member.isdir()):
            raise ValueError(f"{member.name!r} is a link or a device, not a file")
        if name + "/" != MEMBER_ROOT:
            wanted.append((member, name[len(MEMBER_ROOT):]))
    return wanted


def extract(tarball: pathlib.Path, into: pathlib.Path) -> None:
    """Unpack `MEMBER_ROOT` of `tarball` into `into`, all or nothing."""
    with tarfile.open(tarball, "r:gz") as archive:
        wanted = wanted_members(archive)
        if not any(rel == BINARY for _, rel in wanted):
            raise ValueError(f"{MEMBER_ROOT}{BINARY} is not in the tarball")
        into.parent.mkdir(parents=True, exist_ok=True)
        staging = pathlib.Path(tempfile.mkdtemp(prefix=".unpack-", dir=into.parent))
        try:
            for member, rel in wanted:
                target = staging / rel
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("wb") as out:
                    shutil.copyfileobj(source, out)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
            if into.exists():
                shutil.rmtree(into)
            staging.rename(into)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def download(url: str, to: pathlib.Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as reply, to.open("wb") as out:
        shutil.copyfileobj(reply, out)


def install(into: pathlib.Path, fetch=download, url: str = URL,
            expected: str = SHA256) -> pathlib.Path:
    """Return the binary's path, fetching and unpacking only if it is not there."""
    binary = into / BINARY
    if binary.exists():
        print(f"Already installed: {binary}")
        return binary
    into.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".download-", suffix=".tgz", dir=into.parent)
    os.close(fd)
    tarball = pathlib.Path(name)
    try:
        print(f"Fetching {url}")
        fetch(url, tarball)
        check_digest(tarball, expected)
        extract(tarball, into)
    finally:
        tarball.unlink(missing_ok=True)
    return binary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--into", type=pathlib.Path, default=None,
                        help=f"where to unpack (default {default_dir()})")
    args = parser.parse_args(argv)
    if not (sys.platform.startswith("linux")
            and platform.machine() in ("x86_64", "AMD64")):
        print("Only Linux on x86-64 is supported.", file=sys.stderr)
        return 2
    try:
        binary = install((args.into or default_dir()).resolve())
    except (OSError, ValueError) as error:
        print(f"Install failed: {error}", file=sys.stderr)
        return 1
    print(f"FS-UAE: {binary}")
    # `fsuaegdb.py launch` passes its own environment on, and the binary has no
    # RPATH: on a machine without libSDL2_ttf it will not start without this.
    print(f"Use it with: LD_LIBRARY_PATH={binary.parent} "
          f"tools/amiga/fsuaegdb.py launch --fs-uae {binary} --out DIR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
