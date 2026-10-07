"""`--read-at`: a guarded step's memory range is read, recorded and never written."""

from __future__ import annotations

import argparse
import json

import pytest

from tests.amiga.test_amigaacceptance_accept import (  # noqa: F401
    AcceptGuest,
    _accept,
    readings,
)
from tests.amiga.test_amigaacceptance_measure import (  # noqa: F401
    ScreenGuest,
    _measure,
    clock,
)
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


def test_the_option_is_on_accept_and_measure_and_rejects_a_bad_value(capsys):
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-at", action="append", type=acceptance._read_at_arg)
    assert parser.parse_args(["--read-at", "1:0x10:2"]).read_at == [acceptance.parse_read_at("1:0x10:2")]
    with pytest.raises(SystemExit):
        parser.parse_args(["--read-at", "nonsense"])
    source = open(acceptance.__file__).read()
    assert source.count('"--read-at", action="append"') == 2
