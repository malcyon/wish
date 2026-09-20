#!/usr/bin/env python3
"""Install the patched FS-UAE that `tools/amiga/fsuaegdb.py` drives, and print where it went.

    tools/amiga/installfsuae.py
    tools/amiga/installfsuae.py --into DIR

The patched emulator (`grahambates/fs-uae`, the GDB-remote build) has no release
of its own.  Its author ships a build inside the npm package `uae-dap`, and an
npm tarball is an ordinary gzipped tar at a fixed URL, so this fetches that one
file over HTTPS -- no Node -- checks it against the pinned SHA-256 below, and
unpacks only `package/bin/fs-uae/` into `uae-dap-<version>` under the directory
`--into` names (default: a per-user one).  Linux on x86-64 only: that is the
only build in the tarball that runs here.

A download whose digest differs is deleted and nothing is unpacked, and a tar
member that would land outside the target directory refuses the whole archive.
Only a directory this script made is ever replaced: nothing else under `--into`
is touched, and a `uae-dap-<version>` that does not hold the binary is refused.
A second run with the binary already in place does nothing and says so.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import os
import pathlib
import platform
import posixpath
import shlex
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from automap import paths  # noqa: E402

VERSION = "1.1.5"
URL = f"https://registry.npmjs.org/uae-dap/-/uae-dap-{VERSION}.tgz"

#: SHA-256 of that tarball (33,513,452 bytes), taken from one download; the
#: registry's own SHA-1 for it, `4f0a28cc...`, matched.  A new `VERSION` needs
#: this recomputed by hand -- it is the whole of what makes the download safe.
SHA256 = "2a229f77d7b27373e1a06949287b4995a0930355aa74e8953c39bfcc4caf4b94"

#: Size of that tarball, and the most `download` accepts: a hostile mirror
#: cannot fill the disk, and a re-pack a little larger still gets through to
#: the digest check.
PINNED_SIZE = 33_513_452
MAX_BYTES = PINNED_SIZE + (1 << 20)

#: The only part of the tarball that is unpacked; the rest is the debug adapter.
MEMBER_ROOT = "package/bin/fs-uae/"
BINARY = "fs-uae-linux_x64"


def default_dir() -> pathlib.Path:
    """The directory installs go under by default, beside Wish's own per-user data."""
    return paths.data_dir() / "fs-uae"


def install_dir(parent: pathlib.Path) -> pathlib.Path:
    """The one directory under `parent` that this script creates and may replace."""
    return parent / f"uae-dap-{VERSION}"


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


def check_replaceable(into: pathlib.Path) -> None:
    """Refuse an existing `into` that does not hold the binary.

    Whatever else is there was not put there by this script, and `--into`
    can name any directory a person has.
    """
    if into.is_symlink() and not into.exists():
        raise ValueError(f"Refusing to replace {into}: it is a broken link")
    if into.exists() and not (into / BINARY).exists():
        raise ValueError(f"Refusing to replace {into}: it does not contain "
                         f"{BINARY}, so this script did not create it")


def replace_dir(staging: pathlib.Path, into: pathlib.Path) -> None:
    """Put `staging` at `into`; an old `into` is moved aside first and restored on failure."""
    if not into.exists():
        staging.rename(into)
        return
    aside = pathlib.Path(tempfile.mkdtemp(prefix=".replaced-", dir=into.parent))
    try:
        into.rename(aside)
    except BaseException:
        # An interrupt can land after the move has happened, so `aside` may
        # hold the install rather than nothing.
        if into.exists():
            aside.rmdir()
        else:
            aside.rename(into)
        raise
    try:
        staging.rename(into)
    except BaseException:
        aside.rename(into)
        raise
    shutil.rmtree(aside, ignore_errors=True)


def extract(tarball: pathlib.Path, into: pathlib.Path) -> None:
    """Unpack `MEMBER_ROOT` of `tarball` as the directory `into`, all or nothing."""
    with tarfile.open(tarball, "r:gz") as archive:
        wanted = wanted_members(archive)
        if not any(rel == BINARY for _, rel in wanted):
            raise ValueError(f"{MEMBER_ROOT}{BINARY} is not in the tarball")
        check_replaceable(into)
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
            # mkdtemp makes it 0700, and it is about to become the install.
            staging.chmod(0o755)
            replace_dir(staging, into)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def require_https(url: str) -> None:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError(f"Refusing {url}: only https is allowed")


class HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to another https URL, never down to http, ftp or file."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, to: pathlib.Path, opener=None, limit: int = MAX_BYTES) -> None:
    """Fetch `url` to `to` over https, refusing more than `limit` bytes."""
    require_https(url)
    opener = opener or urllib.request.build_opener(HttpsOnlyRedirect)
    total = 0
    try:
        with opener.open(url, timeout=60) as reply, to.open("wb") as out:
            for block in iter(lambda: reply.read(1 << 20), b""):
                total += len(block)
                if total > limit:
                    raise ValueError(f"The download is larger than {limit} bytes; "
                                     "it was deleted")
                out.write(block)
    except BaseException:
        to.unlink(missing_ok=True)
        raise


def install(parent: pathlib.Path, fetch=download, url: str = URL,
            expected: str = SHA256) -> pathlib.Path:
    """Return the binary's path, fetching and unpacking only if it is not there.

    The install is `install_dir(parent)`; `parent` itself is never modified
    beyond that one directory and the temporary files this removes again.
    """
    into = install_dir(parent)
    binary = into / BINARY
    if binary.exists():
        print(f"Already installed: {binary}")
        return binary
    check_replaceable(into)
    parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".download-", suffix=".tgz", dir=parent)
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
                        help=f"the directory to install under (default {default_dir()})")
    args = parser.parse_args(argv)
    if not (sys.platform.startswith("linux")
            and platform.machine() in ("x86_64", "AMD64")):
        print("Only Linux on x86-64 is supported.", file=sys.stderr)
        return 2
    try:
        binary = install((args.into or default_dir()).resolve())
    except (OSError, ValueError, tarfile.TarError, EOFError, zlib.error,
            http.client.IncompleteRead) as error:
        print(f"Install failed: {error}", file=sys.stderr)
        return 1
    print(f"FS-UAE: {binary}")
    # `fsuaegdb.py launch` passes its own environment on, and the binary has no
    # RPATH: on a machine without libSDL2_ttf it will not start without this.
    print(f"Use it with: LD_LIBRARY_PATH={shlex.quote(str(binary.parent))} "
          f"tools/amiga/fsuaegdb.py launch --fs-uae {shlex.quote(str(binary))} "
          "--out DIR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
