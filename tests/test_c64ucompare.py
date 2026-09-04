"""`tools/c64ucompare.py` without a C64 Ultimate and without an emulator.

Everything under test here is the part that decides whether two readings
*disagree*: the masks, the measured exclusion list, and the arithmetic that
turns two directories of `.bin` files into a count.  A wrong answer in any of
them is a false disagreement between hardware and VICE, which is the one
outcome this tool exists to avoid reporting by accident.

Nothing here opens a socket or claims a pool slot: `take()` reads through a
callable, so a dictionary of bytes stands in for both machines.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import c64ucompare  # noqa: E402


class FakeMachine:
    """A machine that is a flat 64K of bytes, plus optional moving addresses.

    `moving` is a set of addresses whose value increments on every read, which
    is what a raster counter or a jiffy clock does to a reading taken without
    a pause.
    """

    def __init__(self, fill=0x00, moving=()):
        self.mem = bytearray([fill]) * 0x10000
        self.moving = set(moving)
        self.ticks = 0
        # A VIC pointed at $CC00 with the screen in bank 3, in text mode --
        # what `screen_address` and `is_bitmap` read.
        self.mem[0xD011] = 0x1B
        self.mem[0xD018] = 0x35
        self.mem[0xDD00] = 0x10

    def poke(self, addr, data):
        self.mem[addr:addr + len(data)] = data

    def read(self, addr, length):
        self.ticks += 1
        out = bytearray(self.mem[addr:addr + length])
        for moved in self.moving:
            if addr <= moved < addr + length:
                out[moved - addr] = (self.mem[moved] + self.ticks) & 0xFF
        return bytes(out)


def status_row(text):
    """`text` as screen codes, padded to a 40-column row."""
    out = bytearray()
    for ch in text.ljust(40)[:40]:
        out.append(ord(ch) - 64 if "A" <= ch <= "Z" else ord(ch))
    return bytes(out)


def machine_in_the_slums(fill=0x00, moving=()):
    m = FakeMachine(fill, moving)
    m.poke(0xCC00 + 14 * 40, status_row("E 11:50 10,8"))
    return m


def test_the_screen_address_is_computed_on_each_machine(tmp_path):
    """Not copied from the other reading: the VIC moves it to $CC00."""
    m = machine_in_the_slums()
    record = c64ucompare.take(m.read, tmp_path / "a", "test")
    assert record["screen_address"] == 0xCC00
    assert record["party_fix"]["source"] == "status"
    assert (record["party_fix"]["x"], record["party_fix"]["y"]) == (10, 8)


def test_two_identical_machines_differ_in_nothing(tmp_path):
    a = machine_in_the_slums()
    b = machine_in_the_slums()
    c64ucompare.take(a.read, tmp_path / "a", "one")
    c64ucompare.take(b.read, tmp_path / "b", "two")
    report = c64ucompare.compare(tmp_path / "a", tmp_path / "b")
    assert report["bytes_differing"] == 0
    assert report["bytes_compared"] > 20000


def test_one_changed_byte_is_reported_with_its_address(tmp_path):
    a = machine_in_the_slums()
    b = machine_in_the_slums()
    b.poke(0x4901, b"\x7f")
    c64ucompare.take(a.read, tmp_path / "a", "one")
    c64ucompare.take(b.read, tmp_path / "b", "two")
    report = c64ucompare.compare(tmp_path / "a", tmp_path / "b")
    assert report["bytes_differing"] == 1
    save = next(r for r in report["regions"] if r["name"] == "save-image")
    assert save["bytes"] == [[0x4901, 0x00, 0x7F]]


def test_a_moving_address_measured_twice_is_excluded(tmp_path):
    """The whole reason the hardware reading is taken twice.

    `$D012` moves on a machine that cannot be paused.  Without `--stable` it
    is a difference; with it, it is a known moving part and the comparison is
    clean.
    """
    a = machine_in_the_slums(moving={0xD012})
    b = machine_in_the_slums()
    c64ucompare.take(a.read, tmp_path / "a", "hardware")
    c64ucompare.take(a.read, tmp_path / "a2", "hardware again")
    c64ucompare.take(b.read, tmp_path / "b", "vice")

    without = c64ucompare.compare(tmp_path / "a", tmp_path / "b")
    assert 0xD012 in [addr for r in without["regions"] for addr, _, _ in r["bytes"]]

    with_stable = c64ucompare.compare(tmp_path / "a", tmp_path / "b",
                                      stable=tmp_path / "a2")
    assert with_stable["bytes_differing"] == 0
    vic = next(r for r in with_stable["regions"] if r["name"] == "vic")
    assert vic["excluded_as_moving"] == 1
    assert with_stable["bytes_compared"] == without["bytes_compared"] - 1


@pytest.mark.parametrize("addr,hardware,vice", [
    (0xD020, 0xF0, 0x00),      # border colour: four bits wide
    (0xD02E, 0xF5, 0x05),      # sprite 7 colour
    (0xD800, 0xA9, 0x09),      # colour RAM: the top nybble is the last bus value
    (0xDBE7, 0x39, 0x09),
])
def test_a_colour_register_is_compared_four_bits_wide(addr, hardware, vice):
    """`$D020` reads `F0` on hardware where VICE gives `00`.

    Comparing those two raw is a difference that is entirely ours: the upper
    four bits are not implemented and float.
    """
    assert c64ucompare.mask_byte(addr, hardware) == \
        c64ucompare.mask_byte(addr, vice)


def test_d011_keeps_the_bit_party_fix_reads_and_drops_the_raster_bit():
    """Bit 7 is raster bit 8 and moves; bit 5 says bitmap and must not."""
    assert c64ucompare.mask_byte(0xD011, 0x1B) == \
        c64ucompare.mask_byte(0xD011, 0x9B)
    assert c64ucompare.mask_byte(0xD011, 0x1B) != \
        c64ucompare.mask_byte(0xD011, 0x3B)


def test_an_ordinary_address_is_not_masked_at_all():
    assert c64ucompare.mask_byte(0x4900, 0xFF) == 0xFF
    assert c64ucompare.mask_byte(0xD018, 0x35) == 0x35


def test_every_region_is_named_once_and_declares_what_it_expects():
    names = [r[0] for r in c64ucompare.REGIONS]
    assert len(names) == len(set(names))
    assert {r[3] for r in c64ucompare.REGIONS} <= {"same", "state", "moving"}
    # The automapper's own two poll blocks are what a hardware reading has to
    # be comparable with, so both have to be in the manifest.
    starts = {r[1]: r[2] for r in c64ucompare.REGIONS}
    assert starts[0x4900] == 0x1C00
    assert starts[0x8300] == 0x0100
