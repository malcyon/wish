"""`cursecheck.py --resave` keeps only a save the game finished writing.

The disks here are synthetic: a blank image carrying a `SAVEAZURE` built
from `goldbox.c64_save`'s own offsets, with the party's square set by hand,
and its directory entry marked open the way a 1541 leaves it mid-write.
"""
from __future__ import annotations

import pathlib

import pytest

from goldbox import c64_port, c64_save
from goldbox.d64 import D64
from tools.c64 import session
from tools.curse_of_the_azure_bonds import cursecheck

CURSE = next(g for g in c64_port.GAMES if g.key == "curse-of-the-azure-bonds")
#: The payload length of the Curse saves the game writes.
PAYLOAD = 7424


def _save(path: pathlib.Path, square: tuple[int, int, int], *,
          open_entry: bool) -> None:
    payload = bytearray(PAYLOAD)
    at = c64_save.container_for(CURSE).position
    payload[at:at + 3] = bytes(square)
    disk = D64.blank(b"SAVE")
    disk.write_file(CURSE.save_file, bytes((0x00, 0x40)) + bytes(payload))
    raw = bytearray(disk.to_bytes())
    if open_entry:
        raw[disk.entry(CURSE.save_file).offset] &= 0x7F
    path.write_bytes(raw)


def _close(path: pathlib.Path) -> None:
    disk = D64.open(path)
    raw = bytearray(disk.to_bytes())
    raw[disk.entry(CURSE.save_file).offset] |= 0x80
    path.write_bytes(raw)


class _Screen:
    def __init__(self, row24: str):
        self._row24 = row24

    def row(self, n: int) -> str:
        return self._row24 if n == 24 else ""

    def text(self) -> str:
        return self._row24


class _Session:
    """Hands out row 24 from a list, one per read; the last one repeats."""

    def __init__(self, rows, on_attach=None):
        self.rows = list(rows)
        self.reads = 0
        self.attached = []
        self.on_attach = on_attach

    def screen(self):
        row = self.rows[min(self.reads, len(self.rows) - 1)]
        self.reads += 1
        return _Screen(row)

    def handle_prompt(self, s=None) -> bool:
        return False

    def attach(self, path: str) -> None:
        self.attached.append(path)
        if self.on_attach:
            self.on_attach(pathlib.Path(path))


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


CAMP = "CAMP:SAVE VIEW MAGIC REST ALTER FIX EXIT"


def test_the_write_is_not_over_while_saving_game_is_on_screen():
    """WISH-411's run copied with `SAVING GAME...` still on row 24."""
    clock = _Clock()
    sess = _Session(["SAVING GAME..."] * 20 + [CAMP])
    got = cursecheck.wait_write_end(sess, 300, clock=clock, sleep=clock.sleep)
    assert got["ended"] is True
    assert sess.reads == 22                  # 20 writing, then the bar twice
    assert got["row24"] == CAMP


def test_a_write_that_never_ends_is_reported_not_waited_out():
    clock = _Clock()
    sess = _Session(["SAVING GAME..."])
    got = cursecheck.wait_write_end(sess, 30, clock=clock, sleep=clock.sleep)
    assert got["ended"] is False
    assert got["row24"] == "SAVING GAME..."


def test_one_camp_bar_frame_is_not_the_end_of_the_write():
    """The bar has to be there on two reads with no SAVING GAME between."""
    clock = _Clock()
    sess = _Session([CAMP, "SAVING GAME...", CAMP, CAMP])
    got = cursecheck.wait_write_end(sess, 300, clock=clock, sleep=clock.sleep)
    assert got["ended"] is True
    assert sess.reads == 4


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(session.time, "sleep", lambda s: None)


def test_an_open_saveazure_is_copied_once_the_reattach_closes_it(tmp_path, no_wait):
    """The drive's held track reaches the image on an attach of the same disk."""
    disk, kept = tmp_path / "SIDE0.D64", tmp_path / "RESAVE.d64"
    _save(disk, (4, 12, 1), open_entry=False)
    before = cursecheck.saved_place(disk)
    _save(disk, (6, 12, 1), open_entry=True)
    sess = _Session([CAMP], on_attach=_close)
    logged = []
    got = cursecheck.keep_resave(sess, disk, kept, [6, 12, 1],
                                 lambda **kw: logged.append(kw), before=before,
                                 attempts=2, backoff=0)
    assert sess.attached == [str(disk)]
    assert got["reattached"] is True
    assert got["verified"] is True
    assert D64.open(kept).entry(CURSE.save_file).is_closed
    assert logged and "SAVEAZURE" in logged[0]["why"]


def test_a_saveazure_that_stays_open_is_not_kept(tmp_path, no_wait):
    disk, kept = tmp_path / "SIDE0.D64", tmp_path / "RESAVE.d64"
    _save(disk, (6, 12, 1), open_entry=True)
    sess = _Session([CAMP])
    with pytest.raises(RuntimeError, match="SAVEAZURE"):
        cursecheck.keep_resave(sess, disk, kept, [6, 12, 1], lambda **kw: None,
                               attempts=2, backoff=0)
    assert not kept.exists()


def test_a_closed_disk_holding_the_square_before_the_walk_is_not_verified(
        tmp_path, no_wait):
    """The raw copy WISH-411 kept read 4,12: the save from before the walk."""
    disk, kept = tmp_path / "SIDE0.D64", tmp_path / "RESAVE.d64"
    _save(disk, (4, 12, 1), open_entry=False)
    before = cursecheck.saved_place(disk)
    got = cursecheck.keep_resave(_Session([CAMP]), disk, kept, [6, 12, 1],
                                 lambda **kw: None, before=before,
                                 attempts=2, backoff=0)
    assert got["reattached"] is False
    assert got["verified"] is False
    assert got["payload_changed"] is False
    assert got["place"]["x"] == 4


def test_a_closed_disk_holding_where_the_party_stood_is_verified(tmp_path, no_wait):
    disk, kept = tmp_path / "SIDE0.D64", tmp_path / "RESAVE.d64"
    _save(disk, (4, 12, 1), open_entry=False)
    before = cursecheck.saved_place(disk)
    _save(disk, (6, 12, 1), open_entry=False)
    got = cursecheck.keep_resave(_Session([CAMP]), disk, kept, [6, 12, 1],
                                 lambda **kw: None, before=before,
                                 attempts=2, backoff=0)
    assert got["verified"] is True
    assert got["payload_changed"] is True
    assert (got["place"]["x"], got["place"]["y"]) == (6, 12)


def test_an_unread_live_square_does_not_verify(tmp_path, no_wait):
    disk, kept = tmp_path / "SIDE0.D64", tmp_path / "RESAVE.d64"
    _save(disk, (6, 12, 1), open_entry=False)
    got = cursecheck.keep_resave(_Session([CAMP]), disk, kept, [],
                                 lambda **kw: None, attempts=2, backoff=0)
    assert got["verified"] is False


def test_an_unwalked_resave_whose_payload_did_not_change_is_not_verified(
        tmp_path, no_wait):
    """With no walk the old save already holds the live square, so the square
    alone would pass the file the game was meant to replace."""
    disk, kept = tmp_path / "SIDE0.D64", tmp_path / "RESAVE.d64"
    _save(disk, (4, 12, 1), open_entry=False)
    before = cursecheck.saved_place(disk)
    got = cursecheck.keep_resave(_Session([CAMP]), disk, kept, [4, 12, 1],
                                 lambda **kw: None, before=before,
                                 attempts=2, backoff=0)
    assert got["payload_changed"] is False
    assert got["verified"] is False


def test_a_resave_with_no_earlier_payload_to_compare_is_not_verified(
        tmp_path, no_wait):
    disk, kept = tmp_path / "SIDE0.D64", tmp_path / "RESAVE.d64"
    _save(disk, (6, 12, 1), open_entry=False)
    got = cursecheck.keep_resave(_Session([CAMP]), disk, kept, [6, 12, 1],
                                 lambda **kw: None, attempts=2, backoff=0)
    assert got["payload_changed"] is None
    assert got["verified"] is False


def test_a_file_that_is_no_disk_image_raises_the_resave_error(tmp_path):
    bad = tmp_path / "SIDE0.D64"
    bad.write_bytes(b"not a disk")
    with pytest.raises(RuntimeError, match="could not read the save"):
        cursecheck.saved_place(bad)


def test_a_save_too_short_to_hold_a_place_raises_the_resave_error(tmp_path):
    short = tmp_path / "SIDE0.D64"
    disk = D64.blank(b"SAVE")
    disk.write_file(CURSE.save_file, bytes((0x00, 0x40)) + bytes(16))
    disk.save(short)
    with pytest.raises(RuntimeError, match="could not read the save"):
        cursecheck.saved_place(short)


def test_a_kept_disk_that_cannot_be_read_raises_the_resave_error(
        tmp_path, no_wait):
    """`run` logs a RuntimeError from `keep_resave` as the resave failure."""
    disk, kept = tmp_path / "SIDE0.D64", tmp_path / "RESAVE.d64"
    image = D64.blank(b"SAVE")
    image.write_file(CURSE.save_file, bytes((0x00, 0x40)) + bytes(16))
    image.save(disk)
    with pytest.raises(RuntimeError, match="could not read the save"):
        cursecheck.keep_resave(_Session([CAMP]), disk, kept, [6, 12, 1],
                               lambda **kw: None, attempts=2, backoff=0)
