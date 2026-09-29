"""`Session.iec_stall_check`: the C64 stuck in the KERNAL talker turnaround.

The monitor is a fake that answers register lists, register reads, memory
reads and a drive PC write; the timing constants are shortened.
"""

import struct

import test_arrivalscene as base

from automap.actions import CMD_REGISTERS_AVAILABLE
from automap.vice import CMD_REGISTERS_GET, CMD_REGISTERS_SET

Session = base.Session
FakeScreen = base.FakeScreen

PC_ID, SP_ID = 3, 4
DRIVE_PC_ID = 7


class State:
    """What the fake machine holds; a test edits it between checks."""

    def __init__(self):
        self.c64_pc = 0xEDD6
        self.sp = 0xF0
        self.stack = 0xEDD8
        self.drive_pc = 0xEC12
        self.secondary = 0x60
        self.writes = []
        self.reads = 0
        #: A write of the drive PC moves the C64 here, or nowhere when None.
        self.write_frees_c64 = None


class FakeMonitor:
    def __init__(self, st):
        self.st = st

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def command(self, cmd, body=b""):
        st = self.st
        if cmd == CMD_REGISTERS_AVAILABLE:
            names = ([(PC_ID, b"PC"), (SP_ID, b"SP")] if body[0] == 0
                     else [(DRIVE_PC_ID, b"PC")])
            out = struct.pack("<H", len(names))
            for rid, name in names:
                out += bytes([3 + len(name), rid, 16, len(name)]) + name
            return out
        if cmd == CMD_REGISTERS_GET:
            regs = ([(PC_ID, st.c64_pc), (SP_ID, st.sp)] if body[0] == 0
                    else [(DRIVE_PC_ID, st.drive_pc)])
            out = struct.pack("<H", len(regs))
            for rid, val in regs:
                out += bytes([3, rid]) + struct.pack("<H", val)
            return out
        if cmd == CMD_REGISTERS_SET:
            space, count = struct.unpack("<BH", body[:3])
            size, rid, val = struct.unpack("<BBH", body[3:7])
            assert size == 3 and space == 1 and count == 1
            st.writes.append((space, rid, val))
            if st.write_frees_c64 is not None:
                st.c64_pc = st.write_frees_c64
            return b""
        raise AssertionError(cmd)

    def read(self, start, length, bank=0, side_effects=0):
        if start == 0xB9:
            return bytes([self.st.secondary])
        if start == 0x0101 + self.st.sp:
            return struct.pack("<H", self.st.stack)
        raise AssertionError(hex(start))


class Fake(Session):
    IEC_HOLD = 0.15
    IEC_EXPIRY = 0.6
    IEC_SAMPLE_GAP = 0.0

    def __init__(self):
        self.st = State()
        self.logged = []
        self.here = "/nowhere"
        self.mon_port = 1

    def mon(self, timeout=5.0):
        return FakeMonitor(self.st)

    def log(self, msg):
        self.logged.append(msg)

    def stall_capture(self, samples=6, gap=0.2):
        return "CAPTURE"

    def screen(self):
        return FakeScreen("")

    def handle_prompt(self, s=None):
        return False

    def _require_alive(self):
        pass


def look(sess, times):
    """Check *times* times, one hold apart; the answer of the last."""
    import time
    answer = False
    for _ in range(times):
        time.sleep(sess.IEC_HOLD + 0.03)
        answer = sess.iec_stall_check()
    return answer


def test_a_stall_seen_twice_a_hold_apart_is_nudged_once():
    sess = Fake()
    assert look(sess, 1) is False
    assert sess.st.writes == []
    assert look(sess, 1) is False
    assert sess.st.writes == [(1, DRIVE_PC_ID, 0xE8F1)]
    assert len(sess.logged) == 1


def test_a_stall_seen_on_one_check_only_is_not_nudged():
    sess = Fake()
    look(sess, 1)
    sess.st.c64_pc = 0x2E4E
    look(sess, 2)
    assert sess.st.writes == []


def test_the_return_from_the_debpia_wait_is_a_stall_inside_the_loop_body():
    sess = Fake()
    sess.st.c64_pc = 0xEEAC
    look(sess, 2)
    assert sess.st.writes == [(1, DRIVE_PC_ID, 0xE8F1)]


def test_an_isour_wait_is_not_a_stall():
    sess = Fake()
    sess.st.c64_pc = 0xEEAC
    sess.st.stack = 0xED5C
    look(sess, 3)
    assert sess.st.writes == []


def test_a_busy_drive_is_not_a_stall():
    sess = Fake()
    sess.st.drive_pc = 0xD59C
    look(sess, 3)
    assert sess.st.writes == []


def test_a_c64_outside_the_loop_is_not_a_stall():
    sess = Fake()
    sess.st.c64_pc = 0x2E4E
    look(sess, 3)
    assert sess.st.writes == []


def test_a_secondary_address_that_is_not_a_load_is_not_a_stall():
    sess = Fake()
    sess.st.secondary = 0xF0
    look(sess, 3)
    assert sess.st.writes == []


def test_a_persistent_stall_is_nudged_twice_then_fails_with_the_message():
    sess = Fake()
    assert look(sess, 4) is False
    assert len(sess.st.writes) == 2
    assert look(sess, 2) is True
    assert len(sess.st.writes) == 2
    assert "still waiting in the KERNAL talker turnaround" in sess.logged[-1]
    assert "CAPTURE" in sess.logged[-1]


def test_a_recovery_resets_the_nudge_count():
    sess = Fake()
    look(sess, 4)
    sess.st.c64_pc = 0x2E4E
    look(sess, 1)
    sess.st.c64_pc = 0xEDD6
    look(sess, 4)
    assert len(sess.st.writes) == 4


def test_a_wait_gives_up_at_once_on_a_persistent_stall():
    sess = Fake()
    assert sess.wait_for_world(timeout=30.0, interval=0.005) is False
    assert sess.wait_text("NEVER", timeout=30.0, interval=0.005) == (None, None)
    assert len(sess.st.writes) == 2


def test_a_nudge_that_frees_the_c64_ends_the_stall_and_the_wait_reaches_its_text():
    sess = Fake()
    sess.st.write_frees_c64 = 0x2E4E
    screens = [FakeScreen("")]
    sess.screen = lambda: screens[0] if not sess.st.writes else FakeScreen("HELLO")
    hit, _ = sess.wait_text("HELLO", timeout=30.0, interval=0.005)
    assert hit == "HELLO"
    assert len(sess.st.writes) == 1


def test_a_nudge_is_skipped_when_the_drive_left_its_idle_loop():
    sess = Fake()
    look(sess, 1)
    real = sess._iec_stalled
    sess._iec_stalled = lambda: (real(), setattr(sess.st, "drive_pc", 0xFE70))[0]
    look(sess, 1)
    assert sess.st.writes == []
    assert "skipped" in sess.logged[-1]
    sess.st.drive_pc = 0xEC12
    sess._iec_stalled = real
    look(sess, 1)
    assert sess.st.writes == [(1, DRIVE_PC_ID, 0xE8F1)]


def test_a_look_from_an_earlier_wait_does_not_count_towards_a_nudge():
    import time
    sess = Fake()
    look(sess, 1)
    time.sleep(sess.IEC_EXPIRY * 1.5)
    assert sess.iec_stall_check() is False
    assert sess.st.writes == []
    look(sess, 1)
    assert len(sess.st.writes) == 1


def test_a_nudge_that_is_always_skipped_gives_up_after_three():
    sess = Fake()
    sess._iec_stalled = lambda: True
    sess.st.drive_pc = 0xFE70
    assert look(sess, 3) is False
    assert look(sess, 1) is True
    assert sess.st.writes == []
    assert "giving up" in sess.logged[-1] and "CAPTURE" in sess.logged[-1]


def test_a_write_that_always_fails_gives_up_after_three():
    sess = Fake()

    def boom(*a):
        raise OSError("no monitor")
    sess._iec_nudge = boom
    assert look(sess, 4) is True
    assert "no monitor" in sess.logged[-1]


def test_a_counted_nudge_resets_the_failure_count():
    sess = Fake()
    look(sess, 1)
    sess._iec_failures = 2
    look(sess, 1)
    assert sess._iec_failures == 0
    assert len(sess.st.writes) == 1
