"""`tools/amiga/installfsuae.py`, which unpacks a patched FS-UAE from a pinned npm tarball.

Nothing here reaches the network: the tarballs are built in `tmp_path` and
handed to the installer through its `fetch` argument, which is the seam that
takes the place of the download.  What matters is what a player would be hurt
by -- a tarball that is not the pinned one being unpacked, a member that writes
outside the target, files from outside `package/bin/fs-uae/` landing on disk,
and a second run downloading 33 MB again.
"""

from __future__ import annotations

import hashlib
import io
import pathlib
import sys
import tarfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import installfsuae  # noqa: E402

ROOT = installfsuae.MEMBER_ROOT


def build(path: pathlib.Path, members: dict[str, bytes | tarfile.TarInfo]) -> str:
    """Write a gzipped tar of name -> content and return its SHA-256."""
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members.items():
            if isinstance(content, tarfile.TarInfo):
                content.name = name
                archive.addfile(content)
                continue
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755 if name.endswith(installfsuae.BINARY) else 0o644
            archive.addfile(info, io.BytesIO(content))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def good_members() -> dict:
    return {
        "package/package.json": b"{}",
        "package/out/main.js": b"// the debug adapter",
        ROOT + installfsuae.BINARY: b"an executable",
        ROOT + "fs-uae.dat": b"data",
        ROOT + "data/fsemu": b"nested",
        "package/bin/fs-uae-elsewhere/other": b"a sibling that must not come",
    }


def fetcher(scratch: pathlib.Path, members: dict):
    """A `fetch` that writes one fixed tarball and counts how often it is asked.

    Returns it with that tarball's digest.  The bytes are built once because a
    gzip header carries the time, so two builds of the same members differ.
    """
    made = scratch / "served.tgz"
    digest = build(made, members)
    calls = []

    def fetch(url, to):
        calls.append(url)
        to.write_bytes(made.read_bytes())

    fetch.calls = calls
    return fetch, digest


def listing(root: pathlib.Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_the_pinned_digest_is_a_sha256():
    assert len(installfsuae.SHA256) == 64
    int(installfsuae.SHA256, 16)


def test_a_tarball_with_the_pinned_digest_is_accepted(tmp_path):
    tarball = tmp_path / "good.tgz"
    digest = build(tarball, good_members())

    installfsuae.check_digest(tarball, digest)

    assert tarball.exists()


def test_a_tarball_with_another_digest_is_refused_and_deleted(tmp_path):
    tarball = tmp_path / "bad.tgz"
    digest = build(tarball, good_members())
    tarball.write_bytes(tarball.read_bytes() + b"\0")

    with pytest.raises(ValueError, match="SHA-256"):
        installfsuae.check_digest(tarball, digest)

    assert not tarball.exists()


def test_a_download_that_fails_the_digest_unpacks_nothing_and_leaves_nothing(tmp_path):
    into = tmp_path / "share" / "fs-uae"
    fetch, _ = fetcher(tmp_path, good_members())

    with pytest.raises(ValueError, match="SHA-256"):
        installfsuae.install(into, fetch=fetch, expected="0" * 64)

    assert not into.exists()
    assert list((tmp_path / "share").iterdir()) == []


@pytest.mark.parametrize("name", [
    "../evil",
    "/etc/evil",
    ROOT + "../../../../evil",
    "package/../../evil",
])
def test_a_member_that_would_escape_refuses_the_whole_archive(tmp_path, name):
    members = good_members()
    members[name] = b"escaped"
    fetch, digest = fetcher(tmp_path, members)
    into = tmp_path / "share" / "fs-uae"

    with pytest.raises(ValueError, match="leave the target"):
        installfsuae.install(into, fetch=fetch, expected=digest)

    assert not into.exists()
    assert not (tmp_path / "evil").exists()
    assert list((tmp_path / "share").iterdir()) == []


def test_a_link_under_the_root_is_refused(tmp_path):
    link = tarfile.TarInfo()
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    members = good_members()
    members[ROOT + "passwd"] = link
    tarball = tmp_path / "link.tgz"
    build(tarball, members)

    with pytest.raises(ValueError, match="link"):
        installfsuae.extract(tarball, tmp_path / "into")

    assert not (tmp_path / "into").exists()


def test_only_the_emulator_directory_is_unpacked(tmp_path):
    tarball = tmp_path / "good.tgz"
    build(tarball, good_members())
    into = tmp_path / "into"

    installfsuae.extract(tarball, into)

    assert listing(into) == {installfsuae.BINARY, "fs-uae.dat", "data/fsemu"}
    assert (into / installfsuae.BINARY).stat().st_mode & 0o111
    assert not (into / "fs-uae.dat").stat().st_mode & 0o111


def test_a_tarball_with_no_linux_binary_is_refused(tmp_path):
    tarball = tmp_path / "other.tgz"
    build(tarball, {ROOT + "fs-uae-darwin_x64": b"a mac binary"})

    with pytest.raises(ValueError, match=installfsuae.BINARY):
        installfsuae.extract(tarball, tmp_path / "into")

    assert not (tmp_path / "into").exists()


def test_a_second_run_downloads_nothing_and_says_so(tmp_path, capsys):
    into = tmp_path / "share" / "fs-uae"
    fetch, digest = fetcher(tmp_path, good_members())

    first = installfsuae.install(into, fetch=fetch, expected=digest)
    (into / "fs-uae.dat").write_bytes(b"edited by the player")
    capsys.readouterr()
    second = installfsuae.install(into, fetch=fetch, expected=digest)

    assert first == second == into / installfsuae.BINARY
    assert len(fetch.calls) == 1
    assert "Already installed" in capsys.readouterr().out
    assert (into / "fs-uae.dat").read_bytes() == b"edited by the player"
