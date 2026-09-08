"""`tools/fasttravelrun.py`'s judgement logic, against a fake monitor rather
than a live emulator.

The tool itself drives a real pool slot end to end -- boot, load a save,
`BEGIN ADVENTURING`, the production `automap.actions.FastTravel().run()`
through a real `automap.target.ViceTarget`, and a live prompt loop -- and
none of that can be exercised here without putting a window on the
maintainer's screen, which this repository's rule forbids. What can be
tested is everything that decides whether a run's own verdict means
anything: `name()`'s byte decoding, `party()`/`area_of()`'s reads against a
fake monitor, and `verdict()`, which is pure and is the part that actually
says pass or fail. The precedent is `tests/test_exitreentry.py`'s own
docstring, word for word on why the split falls where it does.
"""
from __future__ import annotations

import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import fasttravelrun as FT  # noqa: E402


class FakeMonitor:
    """`Session.mon()`'s binary-monitor interface, backed by a flat buffer."""

    def __init__(self):
        self.mem = bytearray(0x10000)

    def read(self, addr: int, length: int) -> bytes:
        return bytes(self.mem[addr:addr + length])

    def write(self, addr: int, data) -> None:
        data = bytes(data)
        self.mem[addr:addr + len(data)] = data


class FakeSession:
    def __init__(self, monitor: FakeMonitor):
        self._m = monitor
        self.screens: list[str] = []

    def mon(self, timeout: float = 5):
        return contextlib.nullcontext(self._m)


def make() -> tuple[FakeSession, FakeMonitor]:
    m = FakeMonitor()
    return FakeSession(m), m


def put_name(m: FakeMonitor, slot: int, text: str, status: int = 1) -> None:
    m.write(FT.SLOT_RECORD + slot * 0x100, text.encode("ascii") + b"\x00")
    m.write(FT.SLOT_ROSTER + slot * 0x20, bytes([status]))


# ---------------------------------------------------------------------------
# name() -- the raw-bytes decoder
# ---------------------------------------------------------------------------

def test_name_reads_up_to_the_first_null():
    assert FT.name(b"PRINCESS FATIMA\x00\x00\x00") == "PRINCESS FATIMA"


def test_name_is_empty_for_a_zeroed_slot():
    assert FT.name(b"\x00" * 16) == "<empty>"


def test_name_is_empty_for_an_empty_buffer():
    assert FT.name(b"") == "<empty>"


def test_name_replaces_unprintable_bytes_with_a_dot():
    assert FT.name(bytes([0x41, 0x01, 0x42, 0x00])) == "A.B"


# ---------------------------------------------------------------------------
# party() / area_of() -- reads against a fake monitor
# ---------------------------------------------------------------------------

def test_party_reads_all_eight_slots_by_name_and_status():
    sess, m = make()
    put_name(m, 3, "PRINCESS FATIMA", status=1)
    rows = FT.party(sess)
    assert len(rows) == FT.SLOTS
    assert rows[3] == {"slot": 3, "name": "PRINCESS FATIMA", "status": 1}
    assert rows[0] == {"slot": 0, "name": "<empty>", "status": 0}


def test_area_of_masks_off_the_top_bit():
    """`$6E1B` carries a flag in bit 7 alongside the area id -- the same
    mask `automap.actions.FastTravel.current_area` applies."""
    sess, m = make()
    m.write(FT.AREA_BYTE, bytes([27 | 0x80]))
    assert FT.area_of(sess) == 27


# ---------------------------------------------------------------------------
# has_member()
# ---------------------------------------------------------------------------

def test_has_member_true_when_the_name_contains_the_substring():
    rows = [{"slot": 3, "name": "PRINCESS FATIMA", "status": 1}]
    assert FT.has_member(rows, "FATIMA") is True


def test_has_member_false_when_absent():
    rows = [{"slot": 3, "name": "XAVIER", "status": 1}]
    assert FT.has_member(rows, "FATIMA") is False


def test_has_member_ignores_empty_slots():
    rows = [{"slot": 3, "name": "<empty>", "status": 0}]
    assert FT.has_member(rows, "<empty>") is False


# ---------------------------------------------------------------------------
# verdict() -- the pure judgement, and what proves it a judgement
# ---------------------------------------------------------------------------

WITH_FATIMA = [{"slot": 3, "name": "PRINCESS FATIMA", "status": 1}]
WITHOUT_FATIMA = [{"slot": 3, "name": "<empty>", "status": 0}]
NO_FATIMA_EVER = [{"slot": 3, "name": "XAVIER", "status": 1}]


def test_verdict_passes_when_the_member_is_dropped_on_landing():
    ok, message = FT.verdict(WITH_FATIMA, WITHOUT_FATIMA, 13, 27, 13, 27,
                              "FATIMA")
    assert ok is True
    assert "dropped" in message


def test_verdict_fails_when_the_member_is_still_there():
    """The regression case #207 is about: the handler was skipped, so the
    party still carries the member after the warp."""
    ok, message = FT.verdict(WITH_FATIMA, WITH_FATIMA, 13, 27, 13, 27,
                              "FATIMA")
    assert ok is False
    assert "did not drop" in message


def test_verdict_fails_when_the_save_was_not_staged_in_the_expected_area():
    ok, message = FT.verdict(WITH_FATIMA, WITHOUT_FATIMA, 5, 27, 13, 27,
                              "FATIMA")
    assert ok is False
    assert "is not in area 13" in message


def test_verdict_fails_when_the_warp_did_not_land():
    ok, message = FT.verdict(WITH_FATIMA, WITH_FATIMA, 13, 13, 13, 27,
                              "FATIMA")
    assert ok is False
    assert "did not land in area 27" in message


def test_verdict_fails_when_the_member_was_never_there():
    """A mistyped `--member`, not a finding -- and it is checked before the
    "still there" case, so a typo is never misreported as the regression."""
    ok, message = FT.verdict(NO_FATIMA_EVER, NO_FATIMA_EVER, 13, 27, 13, 27,
                              "FATIMA")
    assert ok is False
    assert "was not in the party to begin with" in message
