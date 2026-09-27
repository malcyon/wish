"""`save_confirmed` reads the disk back rather than trusting `save_game()`'s
return value alone (#696).

`Session.save_game()` (`tools/c64/session.py`) can return `True` even when
its own final wait for the camp bar to return after the write times out --
it only logs a warning in that case. `menucheck.py`'s `SAVE GAME` check used
to report `saved` straight off that return value, so a save whose directory
entry never actually closed would still print PASS. `save_confirmed` closes
that gap the way `copy_closed_disk`'s other callers already do: read the
disk back and fail if its directory shows an entry still open.
"""

from conftest import load_tools_module

from goldbox.d64 import D64

menucheck = load_tools_module("menucheck")


def _open_save(path):
    """A disk whose directory entry the drive never closed."""
    disk = D64.blank(b"SAVE")
    disk.write_file(b"SAVEDGAME0", bytes(range(256)))
    entry = disk.entry(b"SAVEDGAME0")
    raw = bytearray(disk.to_bytes())
    raw[entry.offset] &= 0x7f
    path.write_bytes(raw)


def _closed_save(path):
    """A disk whose directory entry the drive did close."""
    disk = D64.blank(b"SAVE")
    disk.write_file(b"SAVEDGAME0", bytes(range(256)))
    disk.save(path)


class FakeSession:
    def __init__(self, save_disk):
        self.save_disk = str(save_disk)


def test_save_confirmed_fails_when_the_directory_entry_never_closed(
        tmp_path, monkeypatch):
    """The scenario #696 names: `save_game()` would still return `True` here
    under the old code, because its final `select_bar('EXIT')` wait timing
    out only logs a warning -- this is what has to catch it instead.

    The disk never closes, so `copy_closed_disk` exhausts its 8 default
    retries; monkeypatching its `time.sleep` keeps that real failure path
    without paying its ~1.75s of real backoff.
    """
    disk = tmp_path / "SIDE0.D64"
    _open_save(disk)
    sess = FakeSession(disk)
    monkeypatch.setattr(menucheck.S.time, "sleep", lambda seconds: None)

    ok, why = menucheck.save_confirmed(sess)

    assert ok is False
    assert "SAVEDGAME0" in why


def test_save_confirmed_passes_when_the_directory_entry_closed(
        tmp_path, monkeypatch):
    disk = tmp_path / "SIDE0.D64"
    _closed_save(disk)
    sess = FakeSession(disk)
    monkeypatch.setattr(menucheck.S.time, "sleep", lambda seconds: None)

    ok, why = menucheck.save_confirmed(sess)

    assert ok is True
    assert why == ""
