"""`tools/dosslotwatch.py`'s staging, isolated from DOSBox-X.

`main()`'s copy loop puts `--save`'s `CHRDAT*` and `SAVGAM*.DAT` into the
staged session's `SAVE` directory with `tools.session.stage_writable`, not a
bare `shutil.copy` (`#495`): `--save` is often a read-only specimen, and a
bare copy would carry that mode onto the staged files, leaving the tool's own
`--patch` write-back a few lines later to die on a bare `PermissionError`.

None of this drives DOSBox-X.  `RawSession`, `claim_free` and `boot_settled`
are all replaced, so what runs is exactly the staging and the patch, and
nothing downstream of them -- `dosboxx.unavailable()` is bypassed for the same
reason: this test asserts nothing about the debugger build, only about the
copy loop that runs before anything DOSBox-X-shaped is touched.
"""

from __future__ import annotations

import pathlib
import stat
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import dosslotwatch  # noqa: E402


class _StopEarly(Exception):
    """Raised by the stand-in for `boot_settled`, so `main()` stops right
    after the staging and the `--patch` write-back and before anything that
    would need a real DOSBox-X."""


class _FakeSession:
    def __init__(self, save_dir: pathlib.Path):
        self.save_dir = save_dir

    def stage(self, fresh: bool = True) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeSlot:
    def __init__(self, root: pathlib.Path):
        self.n = 0
        self.dir = root
        self.display = ":99"

    def release(self) -> None:
        pass


class _FakeClaim:
    def __init__(self, root: pathlib.Path):
        self._root = root

    def __enter__(self) -> _FakeSlot:
        return _FakeSlot(self._root)

    def __exit__(self, *exc: object) -> bool:
        return False


@pytest.fixture
def source(tmp_path):
    """A read-only `--save` directory, the shape a `$WISH_SPECIMENS` save is:
    one `CHRDAT` record and the `SAVGAM` container."""
    d = tmp_path / "source"
    d.mkdir()
    (d / "CHRDATD1.SAV").write_bytes(bytes(0x200))
    (d / "SAVGAMD.DAT").write_bytes(b"a container")
    for p in d.iterdir():
        p.chmod(0o444)
    return d


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Every dependency `main()` reaches for before it needs a real
    DOSBox-X, replaced with a stand-in that runs no emulator."""
    save_dir = tmp_path / "slot" / "SAVE"
    save_dir.mkdir(parents=True)
    fake = _FakeSession(save_dir)
    monkeypatch.setattr(dosslotwatch.dosboxx, "unavailable", lambda: None)
    monkeypatch.setattr(dosslotwatch, "claim_free",
                        lambda note: _FakeClaim(tmp_path / "slot"))
    monkeypatch.setattr(dosslotwatch.dosbox, "find_game", lambda game: "dummy")
    monkeypatch.setattr(dosslotwatch, "RawSession",
                        lambda slot, game, exe=None: fake)
    monkeypatch.setattr(dosslotwatch, "boot_settled",
                        lambda s: (_ for _ in ()).throw(_StopEarly()))
    return save_dir


def test_the_staged_copies_are_writable_and_the_patch_lands(source, wired):
    with pytest.raises(_StopEarly):
        dosslotwatch.main([
            "--save", str(source), "--slot", "D",
            "--patch", "1:0x000=9", "--minutes", "0",
        ])

    chrdat = wired / "CHRDATD1.SAV"
    savgam = wired / "SAVGAMD.DAT"
    assert chrdat.stat().st_mode & stat.S_IWUSR
    assert savgam.stat().st_mode & stat.S_IWUSR
    # the --patch write-back after the copy actually landed
    assert chrdat.read_bytes()[0] == 9


def test_a_second_run_into_the_same_save_directory_does_not_raise(source, wired):
    with pytest.raises(_StopEarly):
        dosslotwatch.main([
            "--save", str(source), "--slot", "D",
            "--patch", "1:0x000=9", "--minutes", "0",
        ])

    with pytest.raises(_StopEarly):
        dosslotwatch.main([
            "--save", str(source), "--slot", "D",
            "--patch", "1:0x000=9", "--minutes", "0",
        ])
