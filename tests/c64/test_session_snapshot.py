"""`Session.snapshot`, `restore` and `walk_with_retry` against a fake monitor.

The fake records the binary-monitor commands and writes the snapshot file the
way VICE does, so the tests check what is put on the wire and what the driver
does with the answer.  What VICE keeps of the machine is only provable on a
pool slot.
"""

import struct

import pytest
from conftest import load_tools_module

S = load_tools_module("session")


class FakeMonitor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def command(self, cmd, body=b""):
        self.log.append((cmd, body))
        if cmd == S.CMD_DUMP:
            name = body[3:3 + body[2]].decode()
            open(name, "wb").write(b"vsf")
        return b""


class Fake(S.Session):
    """A `Session` whose monitor is the fake and whose walk is scripted:
    `legs` is one entry per attempt, the move at which an encounter starts
    (or None for a clean leg)."""

    def __init__(self, tmp_path, legs=()):
        self.here = str(tmp_path)
        self.attached = "/slot/SIDE1.D64"
        self.wire = []
        self.legs = list(legs)
        self.restores = 0
        self.combat = False
        self.menu = None
        self.walk_encounter_started = False
        self.walk_stop_screen = None
        self.walked = []
        self.lines = []
        self.attaches = []

    def attach(self, path, unit=8, settle=None):
        self.attaches.append(path)
        self.attached = path

    def mon(self, timeout=5.0):
        return FakeMonitor(self.wire)

    def log(self, *a):
        self.lines.append(" ".join(str(x) for x in a))

    def restore(self, name):
        self.restores += 1
        super().restore(name)

    def walk_one(self, move, hold=0.15, gap=0.30, encounters=False, **kw):
        assert encounters, "a leg that retries on encounters must ask for them"
        self.walked.append(move)
        self.walk_encounter_started = (
            bool(self.legs) and self.legs[0] == move)
        if self.walk_encounter_started:
            self.legs.pop(0)
        return True

    def in_combat(self):
        return self.combat

    def screen(self):
        return self.menu


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(S.time, "sleep", lambda s: None)


def test_snapshot_dumps_machine_and_drive_under_the_run_directory(tmp_path):
    s = Fake(tmp_path)
    path = s.snapshot("before-leg")
    assert path == str(tmp_path / "snapshots" / "before-leg.vsf")
    cmd, body = s.wire[0]
    assert cmd == S.CMD_DUMP
    roms, disks, n = struct.unpack("<BBB", body[:3])
    assert (roms, disks) == (0, 1)
    assert body[3:3 + n].decode() == path


@pytest.mark.parametrize("name", ["../x", "a/b", "", "a b", "x.vsf"])
def test_a_snapshot_name_is_a_word_and_not_a_path(tmp_path, name):
    with pytest.raises(ValueError):
        Fake(tmp_path).snapshot(name)


def test_restore_undumps_the_file_and_puts_the_attached_disk_back(tmp_path):
    s = Fake(tmp_path)
    s.snapshot("a")
    s.attached = "/slot/SIDE3.D64"
    s.restore("a")
    cmd, body = s.wire[-1]
    assert cmd == S.CMD_UNDUMP
    assert body[1:1 + body[0]].decode() == s.snapshot_path("a")
    assert s.attaches == ["/slot/SIDE1.D64"]
    assert s.attached == "/slot/SIDE1.D64"


def test_restore_without_a_swap_leaves_the_drive_alone(tmp_path):
    s = Fake(tmp_path)
    s.snapshot("a")
    s.restore("a")
    assert s.attaches == []


def test_restore_of_a_name_never_saved_says_so_and_sends_nothing(tmp_path):
    s = Fake(tmp_path)
    with pytest.raises(FileNotFoundError):
        s.restore("never")
    assert s.wire == []


def test_a_clean_leg_takes_one_snapshot_and_no_restore(tmp_path):
    s = Fake(tmp_path, legs=[])
    assert s.walk_with_retry("ii") is True
    assert s.walked == ["I", "I"]
    assert s.restores == 0 and s.walk_retries == 0


def test_an_encounter_restores_and_walks_the_leg_again(tmp_path):
    s = Fake(tmp_path, legs=["J"])
    assert s.walk_with_retry("iji") is True
    assert s.walked == ["I", "J", "I", "J", "I"]
    assert s.restores == 1 and s.walk_retries == 1
    assert any("restoring" in line for line in s.lines)


def test_combat_after_a_move_is_an_encounter_too(tmp_path):
    s = Fake(tmp_path)
    flips = iter([True, False, False])
    s.in_combat = lambda: next(flips)
    assert s.walk_with_retry("i") is True
    assert s.restores == 1


def test_a_screen_walk_one_stopped_at_is_an_encounter(tmp_path):
    s = Fake(tmp_path)
    real = s.walk_one

    def stopping(move, hold=0.15, gap=0.30, encounters=False):
        real(move, hold, gap, encounters=encounters)
        s.walk_stop_screen = ["row"] * 25 if not s.restores else None
        return False

    s.walk_one = stopping
    assert s.walk_with_retry("i") is True
    assert s.restores == 1


def test_retries_run_out_with_the_machine_restored_and_the_reason_set(tmp_path):
    s = Fake(tmp_path, legs=["I"] * 3)
    assert s.walk_with_retry("i", retries=2) is False
    assert s.restores == 3 and s.walk_retries == 3
    assert "3 attempts" in s.walk_refused


def test_a_walk_one_without_the_encounters_option_still_retries(tmp_path):
    """Curse's `walk_one` has no `encounters`; its encounters show on the mode
    byte and on row 24."""
    class Row24:
        def row(self, r):
            return "COMBAT WAIT FLEE ADVANCE" if r == 24 else ""

    s = Fake(tmp_path)
    seen = []

    def curse_walk_one(move, hold=0.15, gap=0.30, tries=4):
        seen.append(move)
        met = len(seen) == 1
        s.menu = Row24() if met else None
        return not met

    s.walk_one = curse_walk_one
    assert s.walk_with_retry("i") is True
    assert seen == ["I", "I"] and s.restores == 1


def test_a_stale_stop_screen_from_an_earlier_move_is_not_this_moves(tmp_path):
    s = Fake(tmp_path)
    s.walk_stop_screen = ["old"] * 25
    assert s.walk_with_retry("i") is True
    assert s.restores == 0
