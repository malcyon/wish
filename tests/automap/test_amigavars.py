"""`automap/amigavars.py`: each variable range resolves to the right address of a fake data base."""

import pytest

from automap import amigavars

BASE = 0x10000


class Memory:
    """Byte-addressed fake memory behind a data base at BASE."""

    data_base = BASE

    def __init__(self):
        self.mem = {}
        self.reads = []

    def put(self, addr, data):
        for i, b in enumerate(data):
            self.mem[addr + i] = b

    def read(self, addr, length):
        self.reads.append((addr, length))
        return bytes(self.mem.get(addr + i, 0) for i in range(length))


def make(pointers):
    m = Memory()
    for offset, table in pointers.items():
        m.put(BASE + offset, table.to_bytes(4, "big"))
    return m


POD = {0x57AC: 0x40000, 0x6EA6: 0x50000}
CURSE = {0x3D00: 0x40000, 0x588A: 0x50000, 0x3DBE: 0x60000, 0x5006: 0x70000}


def test_pods_low_range_is_a_byte_at_the_pointer_plus_n():
    m = make(POD)
    m.put(0x40000 + 0x25E, b"\x02")
    got = amigavars.read_variable(m, "pools-of-darkness", 0x25E)
    assert (got.address, got.value, got.unreadable) == (0x4025E, 2, None)


def test_pods_script_range_is_a_byte_at_the_pointer_plus_the_address():
    m = make(POD)
    m.put(0x50000 + 0x8123, b"\x07")
    got = amigavars.read_variable(m, "pools-of-darkness", 0x8123)
    assert (got.address, got.value) == (0x58123, 7)


def test_pods_member_record_range_is_reported_not_readable():
    m = make(POD)
    got = amigavars.read_variable(m, "pools-of-darkness", 0x401)
    assert got.value is None and "not readable" in got.unreadable
    assert m.reads == []


@pytest.mark.parametrize("var,pointer,origin", [
    (0x4B10, 0x40000, 0x4B00), (0x7A03, 0x50000, 0x7A00), (0x7C05, 0x60000, 0x7C00)])
def test_curse_word_ranges_are_big_endian_at_twice_the_offset(var, pointer, origin):
    m = make(CURSE)
    m.put(pointer + 2 * (var - origin), b"\x01\x2C")
    got = amigavars.read_variable(m, "curse-of-the-azure-bonds", var)
    assert (got.address, got.value, got.size) == (pointer + 2 * (var - origin), 0x12C, 2)


def test_curse_script_bytes_are_at_the_pointer_plus_the_address():
    m = make(CURSE)
    m.put(0x70000 + 0x8010, b"\x09")
    got = amigavars.read_variable(m, "curse-of-the-azure-bonds", 0x8010)
    assert (got.address, got.value) == (0x78010, 9)


def test_an_unmapped_variable_and_an_unmapped_title_are_reported():
    m = make(POD)
    assert "no range" in amigavars.read_variable(m, "pools-of-darkness", 0x4B00).unreadable
    assert "no variable map" in amigavars.read_variable(m, "pool-of-radiance", 1).unreadable


def test_parse_takes_hex_with_or_without_a_prefix():
    assert amigavars.parse_list("$4B10, 0x25e,8000") == [0x4B10, 0x25E, 0x8000]
