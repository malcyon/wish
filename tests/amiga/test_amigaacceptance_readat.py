"""`--read-at`: a guarded step's memory range is read, recorded and never written."""

from __future__ import annotations

import argparse
import json

import pytest

from tests.amiga.test_amigaacceptance_accept import (  # noqa: F401
    AcceptGuest,
    MapGuard,
    _accept,
    readings,
)
from tests.amiga.test_amigaacceptance_measure import (  # noqa: F401
    ScreenGuest,
    _measure,
    clock,
)
from tests.amiga.test_amigaacceptance_resume import (
    BackGuest,
    _resume,
    _stopped,
)
from tests.amiga.test_amigaacceptance_snapshot import FakePipe
from tools.amiga import acceptance
from tools.amiga.amigatarget import A4_BIAS
from tools.amiga.winuaesession import RouteError

BASE = 0x40000


class ReadOnlyGuestMemory:
    """Has `read` and `locate` only, so any write attempt is an AttributeError."""

    def __init__(self, guest):
        self.guest, self.reads = guest, []

    def locate(self):
        return BASE

    def read(self, address, length):
        self.reads.append((address, length, len(self.guest.calls)))
        return bytes([0xFF] * length)


def test_parse_forms():
    assert acceptance.parse_read_at("vault:a4-0x151E:64") == acceptance.ReadAt("vault", "a4", -0x151E, 64)
    assert acceptance.parse_read_at("3:base+10:4") == acceptance.ReadAt("3", "base", 0x10, 4)
    assert acceptance.parse_read_at("3:0xC0DE:2") == acceptance.ReadAt("3", "abs", 0xC0DE, 2)
    for bad in ("3:0xC0DE", "3:a4:2", "3:a5+1:2", "3:0x10:0", "3:0x10:99999", ":0x10:2"):
        with pytest.raises(RouteError):
            acceptance.parse_read_at(bad)


def test_accept_reads_after_the_named_step_and_records_it(tmp_path, clock, readings):  # noqa: F811
    guest = AcceptGuest(clock)
    memory = ReadOnlyGuestMemory(guest)
    spec = acceptance.parse_read_at("4:a4-0x151E:64")
    _, result = _accept(tmp_path, clock, guest=guest, reads=(spec,), reader=memory)
    assert result["error"] == ""
    assert memory.reads == [(BASE + A4_BIAS - 0x151E, 64, memory.reads[0][2])]
    row = result["memory_reads"][0]
    assert (row["step"], row["address"], row["length"], row["set_bits"]) == (
        4, BASE + A4_BIAS - 0x151E, 64, 512)
    # Four keys went out before the read; the fifth had not.
    assert [c[0] for c in guest.calls[:memory.reads[0][2]]].count("press") == 4
    assert any(e.get("memory_read") for e in result["events"])
    assert json.loads((tmp_path / "recon1" / "summary.json").read_text())["memory_reads"] == [row]


def test_a_read_of_a_step_the_route_never_reaches_fails_the_run(tmp_path, clock, readings):  # noqa: F811
    guest = AcceptGuest(clock)
    _, result = _accept(tmp_path, clock, guest=guest, reader=ReadOnlyGuestMemory(guest),
                        reads=(acceptance.parse_read_at("99:0x100:4"),))
    assert "never reached" in result["error"]
    assert result["success"] is False


def test_measure_reads_by_state_name(tmp_path, clock):  # noqa: F811
    guest = ScreenGuest(clock)
    memory = ReadOnlyGuestMemory(guest)
    result = _measure(tmp_path, guest, reads=(acceptance.parse_read_at("sheet:0x100:8"),),
                      reader=memory)
    assert result["error"] == ""
    # A state name matches every step in that state.
    assert {(r["state"], r["address"]) for r in result["memory_reads"]} == {("sheet", 0x100)}
    assert len(result["memory_reads"]) == len(memory.reads) >= 1


def test_a_default_run_reads_nothing(tmp_path, clock, readings):  # noqa: F811
    _, result = _accept(tmp_path, clock)
    assert result["memory_reads"] == []


def test_reads_need_a_reader_and_a_route_that_walks(tmp_path, clock, readings):  # noqa: F811
    spec = acceptance.parse_read_at("1:0x100:4")
    with pytest.raises(RouteError, match="memory reader"):
        _accept(tmp_path, clock, reads=(spec,))
    with pytest.raises(RouteError, match="accept or measure"):
        _accept(tmp_path, clock, reads=(spec,), reader=object(), reload=True)


@pytest.mark.parametrize("command", ["accept", "measure"])
@pytest.mark.parametrize("bad, message", [
    ("nonsense", "wants STEP:ADDR:LEN"),
    ("3:0x10", "wants STEP:ADDR:LEN"),
    (":0x10:2", "wants STEP:ADDR:LEN"),
    ("3:a5+1:2", "address 'a5+1'"),
    ("3:a4:2", "address 'a4'"),
    ("3:0x10:0", "length '0'"),
    ("3:0x10:4097", "length '4097'"),
    ("3:0x10:x", "length 'x'"),
])
def test_the_command_line_rejects_a_bad_read_at(command, bad, message, capsys):
    with pytest.raises(SystemExit) as stop:
        acceptance.main([command, "--title", "ssb", "--read-at", bad])
    assert stop.value.code == 2
    assert message in capsys.readouterr().err


def test_read_options_build_a_reader_from_the_parsed_options(monkeypatch):
    from automap import amiga

    made = []
    monkeypatch.setattr(amiga, "WinuaePipe", lambda holder: made.append(holder) or "pipe")
    monkeypatch.setattr(amiga, "AmigaTarget", lambda pipe, machine: ("target", pipe, machine))
    specs = [acceptance.parse_read_at("1:0x10:2"), acceptance.parse_read_at("vault:a4-8:4")]
    got = acceptance._read_options(argparse.Namespace(read_at=specs, title="ssb"), "lane1")
    assert got["reads"] == tuple(specs) and got["reader"][:2] == ("target", "pipe")
    assert made == ["lane1"]
    assert acceptance._read_options(argparse.Namespace(read_at=None, title="ssb"), "lane1") == {}


def test_a_read_on_a_step_with_no_guard_says_so(tmp_path, clock):  # noqa: F811
    guest = ScreenGuest(clock)
    result = _measure(tmp_path, guest, reads=(acceptance.parse_read_at("sheet:0x100:8"),),
                      reader=ReadOnlyGuestMemory(guest), guard=None)
    assert result["memory_reads"] and all(r["guarded"] is False for r in result["memory_reads"])


def test_a_guarded_read_says_it_was_guarded(tmp_path, clock, readings):  # noqa: F811
    guest = AcceptGuest(clock)
    _, result = _accept(tmp_path, clock, guest=guest, reader=ReadOnlyGuestMemory(guest),
                        reads=(acceptance.parse_read_at("4:0x100:4"),))
    assert [r["guarded"] for r in result["memory_reads"]] == [True]


def test_a_restored_walk_leg_numbers_its_reads_and_marks_the_last_final(
        tmp_path, clock, readings):  # noqa: F811
    guest = AcceptGuest(clock)
    fake = FakePipe(guest)
    guest.snapshot, guest.restore = fake.snapshot, fake.restore

    def world(path):
        restores = sum(1 for call in fake.calls if call[0] == "restore")
        return not (path.stem == "13-world" and restores < 1)

    _, result = _accept(tmp_path, clock, guest=guest, guard=MapGuard(on={"world": world}),
                        walk_retry=1, reader=ReadOnlyGuestMemory(guest),
                        reads=(acceptance.parse_read_at("12:0x100:4"),))
    assert result["error"] == ""
    rows = result["memory_reads"]
    assert [(r["step"], r["attempt"], r["final"]) for r in rows] == [(12, 1, False), (12, 2, True)]


def test_a_resume_does_not_fail_a_read_aimed_before_its_step(tmp_path, clock):  # noqa: F811
    stopped, first = _stopped(tmp_path, clock)
    guest = BackGuest(clock, stopped)
    _, result = _resume(tmp_path, clock, stopped, first, guest=guest, reader=ReadOnlyGuestMemory(guest),
                        reads=(acceptance.parse_read_at("3:0x100:4"),
                               acceptance.parse_read_at("9:0x100:4")))
    assert result["error"] == "" and result["success"] is True, result
    assert result["reads_skipped_by_resume"] == ["3:0x100:4"]
    assert [r["step"] for r in result["memory_reads"]] == [9]
    # A step the resumed route does not have is still an error.
    (tmp_path / "again").mkdir()
    stopped, first = _stopped(tmp_path / "again", clock)
    guest = BackGuest(clock, stopped)
    _, result = _resume(tmp_path / "again", clock, stopped, first, guest=guest,
                        reader=ReadOnlyGuestMemory(guest),
                        reads=(acceptance.parse_read_at("99:0x100:4"),))
    assert "never reached" in result["error"]
