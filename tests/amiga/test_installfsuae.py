"""`tools/amiga/installfsuae.py`, which unpacks a patched FS-UAE from a pinned npm tarball.

Nothing here reaches the network: the tarballs are built in `tmp_path` and
handed to the installer through its `fetch` argument, which is the seam that
takes the place of the download.  What matters is what a player would be hurt
by -- a tarball that is not the pinned one being unpacked, a member that writes
outside the target, files from outside `package/bin/fs-uae/` landing on disk,
a second run downloading 33 MB again, and `--into` naming a directory that
holds a person's own files.  `--into` is the directory to install *under*: the
install is `uae-dap-<version>` inside it, and nothing else there is touched.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import pathlib
import shlex
import sys
import tarfile
import urllib.request
import zlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import installfsuae  # noqa: E402

ROOT = installfsuae.MEMBER_ROOT

#: The installer only runs on Linux.  Windows has no 0o755 directory mode, no
#: exec bit, refuses to rename a directory onto another, and needs a privilege
#: to make a symlink.
posix_only = pytest.mark.skipif(sys.platform == "win32",
                                reason="POSIX modes, directory renames and symlinks")


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
    parent = tmp_path / "share"
    fetch, _ = fetcher(tmp_path, good_members())

    with pytest.raises(ValueError, match="SHA-256"):
        installfsuae.install(parent, fetch=fetch, expected="0" * 64)

    assert list(parent.iterdir()) == []


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
    parent = tmp_path / "share"

    with pytest.raises(ValueError, match="leave the target"):
        installfsuae.install(parent, fetch=fetch, expected=digest)

    assert not (tmp_path / "evil").exists()
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize("kind", [
    tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE,
])
def test_a_link_or_a_device_under_the_root_is_refused(tmp_path, kind):
    special = tarfile.TarInfo()
    special.type = kind
    if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
        special.linkname = "/etc/passwd"
    members = good_members()
    members[ROOT + "passwd"] = special
    tarball = tmp_path / "link.tgz"
    build(tarball, members)

    with pytest.raises(ValueError, match="link or a device"):
        installfsuae.extract(tarball, tmp_path / "into")

    assert not (tmp_path / "into").exists()


@posix_only
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
    parent = tmp_path / "share"
    into = installfsuae.install_dir(parent)
    fetch, digest = fetcher(tmp_path, good_members())

    first = installfsuae.install(parent, fetch=fetch, expected=digest)
    (into / "fs-uae.dat").write_bytes(b"edited by the player")
    capsys.readouterr()
    second = installfsuae.install(parent, fetch=fetch, expected=digest)

    assert first == second == into / installfsuae.BINARY
    assert len(fetch.calls) == 1
    assert "Already installed" in capsys.readouterr().out
    assert (into / "fs-uae.dat").read_bytes() == b"edited by the player"


def test_a_name_clash_mid_extraction_leaves_no_staging_directory(tmp_path):
    """A file `data` and a member `data/x`: the copy fails after some files are down."""
    tarball = tmp_path / "clash.tgz"
    build(tarball, {
        ROOT + installfsuae.BINARY: b"an executable",
        ROOT + "data": b"a file",
        ROOT + "data/x": b"under a file",
    })
    parent = tmp_path / "share"

    with pytest.raises(OSError):
        installfsuae.extract(tarball, installfsuae.install_dir(parent))

    assert list(parent.iterdir()) == []


@posix_only
def test_the_install_is_readable_by_everyone(tmp_path):
    """`mkdtemp` makes 0700, and the staging directory becomes the install."""
    tarball = tmp_path / "good.tgz"
    build(tarball, good_members())
    into = tmp_path / "into"

    installfsuae.extract(tarball, into)

    assert into.stat().st_mode & 0o777 == 0o755


# --- --into names a directory to install under, and only the install is replaced


def test_a_file_already_in_the_into_directory_survives_an_install(tmp_path):
    parent = tmp_path / "documents"
    parent.mkdir()
    (parent / "thesis.txt").write_bytes(b"years of work")
    (parent / "notes").mkdir()
    (parent / "notes" / "a.txt").write_bytes(b"more")
    fetch, digest = fetcher(tmp_path, good_members())

    binary = installfsuae.install(parent, fetch=fetch, expected=digest)

    assert binary == parent / f"uae-dap-{installfsuae.VERSION}" / installfsuae.BINARY
    assert binary.exists()
    assert (parent / "thesis.txt").read_bytes() == b"years of work"
    assert (parent / "notes" / "a.txt").read_bytes() == b"more"
    assert sorted(p.name for p in parent.iterdir()) == [
        "notes", "thesis.txt", f"uae-dap-{installfsuae.VERSION}"]


def test_a_versioned_directory_without_the_binary_is_refused_not_deleted(tmp_path):
    parent = tmp_path / "share"
    mine = installfsuae.install_dir(parent)
    mine.mkdir(parents=True)
    (mine / "precious.txt").write_bytes(b"not ours")
    fetch, digest = fetcher(tmp_path, good_members())

    with pytest.raises(ValueError, match="Refusing to replace"):
        installfsuae.install(parent, fetch=fetch, expected=digest)

    assert fetch.calls == []
    assert (mine / "precious.txt").read_bytes() == b"not ours"
    assert [p.name for p in parent.iterdir()] == [mine.name]


def test_extract_also_refuses_a_directory_without_the_binary(tmp_path):
    tarball = tmp_path / "good.tgz"
    build(tarball, good_members())
    into = tmp_path / "into"
    into.mkdir()
    (into / "precious.txt").write_bytes(b"not ours")

    with pytest.raises(ValueError, match="Refusing to replace"):
        installfsuae.extract(tarball, into)

    assert (into / "precious.txt").read_bytes() == b"not ours"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


@posix_only
def test_an_earlier_install_is_replaced_whole(tmp_path):
    tarball = tmp_path / "good.tgz"
    build(tarball, good_members())
    into = tmp_path / "into"
    (into / "stale").mkdir(parents=True)
    (into / installfsuae.BINARY).write_bytes(b"old")
    (into / "stale" / "left-over").write_bytes(b"from the old version")

    installfsuae.extract(tarball, into)

    assert (into / installfsuae.BINARY).read_bytes() == b"an executable"
    assert not (into / "stale").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["good.tgz", "into"]


def an_earlier_install(tmp_path):
    tarball = tmp_path / "good.tgz"
    build(tarball, good_members())
    into = tmp_path / "into"
    into.mkdir()
    (into / installfsuae.BINARY).write_bytes(b"old")
    (into / "kept").write_bytes(b"still here")
    return tarball, into


def assert_earlier_install_untouched(tmp_path, into):
    assert (into / installfsuae.BINARY).read_bytes() == b"old"
    assert (into / "kept").read_bytes() == b"still here"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["good.tgz", "into"]


# A Ctrl-C is a KeyboardInterrupt, which is not an Exception: the handlers must
# put the earlier install back for it as much as for a failed disk.
@posix_only
@pytest.mark.parametrize("error", [OSError("disk went away"), KeyboardInterrupt()])
def test_a_failed_replacement_puts_the_earlier_install_back(tmp_path, monkeypatch, error):
    tarball, into = an_earlier_install(tmp_path)
    real_rename = pathlib.Path.rename

    def rename(self, target):
        if self.name.startswith(".unpack-"):
            raise error
        return real_rename(self, target)

    monkeypatch.setattr(pathlib.Path, "rename", rename)

    with pytest.raises(type(error)):
        installfsuae.extract(tarball, into)

    assert_earlier_install_untouched(tmp_path, into)


@posix_only
@pytest.mark.parametrize("error", [OSError("disk went away"), KeyboardInterrupt()])
def test_a_failure_moving_the_earlier_install_aside_leaves_nothing_behind(
        tmp_path, monkeypatch, error):
    tarball, into = an_earlier_install(tmp_path)
    real_rename = pathlib.Path.rename

    def rename(self, target):
        if self == into:
            raise error
        return real_rename(self, target)

    monkeypatch.setattr(pathlib.Path, "rename", rename)

    with pytest.raises(type(error)):
        installfsuae.extract(tarball, into)

    assert_earlier_install_untouched(tmp_path, into)


@posix_only
def test_an_interrupt_just_after_the_earlier_install_moved_aside_puts_it_back(
        tmp_path, monkeypatch):
    """The move has happened when the Ctrl-C lands, so the aside directory is not empty."""
    tarball, into = an_earlier_install(tmp_path)
    real_rename = pathlib.Path.rename

    def rename(self, target):
        result = real_rename(self, target)
        if self == into:
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(pathlib.Path, "rename", rename)

    with pytest.raises(KeyboardInterrupt):
        installfsuae.extract(tarball, into)

    assert_earlier_install_untouched(tmp_path, into)


@posix_only
def test_a_broken_link_at_the_versioned_path_is_refused_and_named(tmp_path):
    parent = tmp_path / "share"
    parent.mkdir()
    link = installfsuae.install_dir(parent)
    link.symlink_to(tmp_path / "nowhere")
    fetch, digest = fetcher(tmp_path, good_members())

    with pytest.raises(ValueError, match="broken link") as raised:
        installfsuae.install(parent, fetch=fetch, expected=digest)

    assert str(link) in str(raised.value)
    assert fetch.calls == []
    assert link.is_symlink()
    assert [p.name for p in parent.iterdir()] == [link.name]


# --- what a download may be


class FakeOpener:
    """Stands in for a urllib opener: serves fixed bytes and records what it was asked."""

    def __init__(self, data: bytes = b""):
        self.data = data
        self.opened: list[str] = []

    def open(self, url, timeout=None):
        self.opened.append(url)
        return io.BytesIO(self.data)


@pytest.mark.parametrize("url", [
    "http://registry.npmjs.org/uae-dap/-/uae-dap-1.1.5.tgz",
    "ftp://registry.npmjs.org/uae-dap.tgz",
    "file:///etc/passwd",
    "/etc/passwd",
])
def test_a_download_that_is_not_https_is_refused_before_anything_is_opened(tmp_path, url):
    opener = FakeOpener(b"data")
    to = tmp_path / "out.tgz"

    with pytest.raises(ValueError, match="only https"):
        installfsuae.download(url, to, opener=opener)

    assert opener.opened == []
    assert not to.exists()


def test_a_download_larger_than_the_cap_is_refused_and_deleted(tmp_path):
    opener = FakeOpener(b"x" * 25)
    to = tmp_path / "out.tgz"

    with pytest.raises(ValueError, match="larger than 10 bytes"):
        installfsuae.download("https://example.org/a.tgz", to, opener=opener, limit=10)

    assert not to.exists()


class CountingReply:
    """A reply that hands out `supply` bytes and counts how many it has."""

    def __init__(self, supply: int):
        self.left = supply
        self.handed_out = 0

    def read(self, size=-1):
        size = self.left if size is None or size < 0 else min(size, self.left)
        self.left -= size
        self.handed_out += size
        return b"x" * size

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_download_over_the_cap_is_refused_before_the_whole_body_is_read(tmp_path):
    """A hostile mirror serving gigabytes must be cut off, not buffered and then judged."""
    block = 1 << 20  # `download` reads this much at a time
    limit = block - 1
    reply = CountingReply(4 * block)

    class Opener:
        def open(self, url, timeout=None):
            return reply

    to = tmp_path / "out.tgz"

    with pytest.raises(ValueError, match="larger than"):
        installfsuae.download("https://example.org/a.tgz", to, opener=Opener(), limit=limit)

    assert reply.handed_out <= block + limit
    assert not to.exists()


def test_a_download_with_no_opener_given_refuses_a_redirect_away_from_https(
        tmp_path, monkeypatch):
    real = urllib.request.build_opener
    built = []

    def spy(*handlers):
        built.append(real(*handlers))
        return FakeOpener(b"data")

    monkeypatch.setattr(urllib.request, "build_opener", spy)

    installfsuae.download("https://example.org/a.tgz", tmp_path / "out.tgz")

    assert any(isinstance(handler, installfsuae.HttpsOnlyRedirect)
               for handler in built[0].handlers)


def test_a_download_exactly_at_the_cap_is_kept(tmp_path):
    to = tmp_path / "out.tgz"

    installfsuae.download("https://example.org/a.tgz", to,
                         opener=FakeOpener(b"x" * 10), limit=10)

    assert to.read_bytes() == b"x" * 10


def test_the_default_cap_admits_the_pinned_tarball():
    assert installfsuae.MAX_BYTES >= 33_513_452


@pytest.mark.parametrize("target", [
    "http://mirror.example/a.tgz", "ftp://mirror.example/a.tgz", "file:///etc/passwd",
])
def test_a_redirect_to_anything_but_https_is_refused(target):
    handler = installfsuae.HttpsOnlyRedirect()
    request = urllib.request.Request("https://registry.npmjs.org/a.tgz")

    with pytest.raises(ValueError, match="only https"):
        handler.redirect_request(request, None, 302, "Found", {}, target)


def test_a_redirect_to_https_is_followed():
    handler = installfsuae.HttpsOnlyRedirect()
    request = urllib.request.Request("https://registry.npmjs.org/a.tgz")

    followed = handler.redirect_request(
        request, None, 302, "Found", {}, "https://cdn.example/a.tgz")

    assert followed.full_url == "https://cdn.example/a.tgz"


# --- main


@pytest.fixture
def linux_x86(monkeypatch):
    monkeypatch.setattr(installfsuae.sys, "platform", "linux")
    monkeypatch.setattr(installfsuae.platform, "machine", lambda: "x86_64")


def test_main_on_another_platform_exits_2_and_installs_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(installfsuae.sys, "platform", "win32")
    monkeypatch.setattr(installfsuae, "install", lambda *a, **k: pytest.fail("installed"))

    assert installfsuae.main(["--into", str(tmp_path)]) == 2

    assert "Only Linux on x86-64 is supported." in capsys.readouterr().err


@pytest.mark.parametrize("error", [
    OSError("no space left"),
    ValueError("SHA-256 differs"),
    tarfile.ReadError("not a gzip file"),
    EOFError("Compressed file ended before the end-of-stream marker was reached"),
    zlib.error("Error -3 while decompressing data"),
    http.client.IncompleteRead(b"abc", 10),
])
def test_main_reports_a_failed_install_as_one_line_and_exits_1(
        tmp_path, monkeypatch, capsys, linux_x86, error):
    def fail(parent):
        raise error

    monkeypatch.setattr(installfsuae, "install", fail)

    assert installfsuae.main(["--into", str(tmp_path)]) == 1

    err = capsys.readouterr().err
    assert err.startswith("Install failed: ")
    assert err.count("\n") == 1


def test_main_quotes_the_paths_it_prints_and_exits_0(tmp_path, monkeypatch, capsys, linux_x86):
    binary = tmp_path / "my games" / installfsuae.BINARY
    monkeypatch.setattr(installfsuae, "install", lambda parent: binary)

    assert installfsuae.main(["--into", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert f"FS-UAE: {binary}" in out
    assert f"LD_LIBRARY_PATH={shlex.quote(str(binary.parent))} " in out
    assert f"--fs-uae {shlex.quote(str(binary))} " in out
    assert "'" in out


def test_main_installs_under_the_into_directory(tmp_path, monkeypatch, capsys, linux_x86):
    seen = []
    monkeypatch.setattr(installfsuae, "install",
                        lambda parent: seen.append(parent) or parent / installfsuae.BINARY)

    installfsuae.main(["--into", str(tmp_path)])

    assert seen == [tmp_path.resolve()]
