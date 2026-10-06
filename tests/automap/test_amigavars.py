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
    assert "no variable map" in amigavars.read_variable(m, "secret-of-the-silver-blades", 1).unreadable


POOL = {0x98: 0x40000, 0x9C: 0x50000, 0xA0: 0x60000, 0xA4: 0x70000}


@pytest.mark.parametrize("var,pointer,origin", [
    (0x4A5D, 0x40000, 0x4900), (0x4AB5, 0x40000, 0x4900), (0x4A7C, 0x40000, 0x4900),
    (0x4AB7, 0x40000, 0x4900), (0x6E82, 0x50000, 0x6B00), (0x9812, 0x60000, 0x9700)])
def test_pool_word_ranges_are_big_endian_at_twice_the_offset(var, pointer, origin):
    m = make(POOL)
    address = pointer + 2 * (var - origin)
    m.put(address, b"\x00\x28")
    got = amigavars.read_variable(m, "pool-of-radiance", var)
    assert (got.address, got.value, got.size) == (address, 0x28, 2)


def test_pool_staged_words_sit_at_their_known_offsets_from_the_first_table():
    m = make(POOL)
    for var, offset in ((0x4A5D, 0x2BA), (0x4AB5, 0x36A), (0x4A7C, 0x2F8), (0x4AB7, 0x36E)):
        assert amigavars.read_variable(m, "pool-of-radiance", var).address == 0x40000 + offset
    assert amigavars.read_variable(m, "pool-of-radiance", 0x6E82).address == 0x50000 + 0x704


def test_pool_script_buffer_is_a_byte_at_the_pointer_plus_the_offset():
    m = make(POOL)
    m.put(0x70000 + 0x10, b"\x09")
    got = amigavars.read_variable(m, "pool-of-radiance", 0x9910)
    assert (got.address, got.value, got.size) == (0x70010, 9, 1)


def test_pool_record_table_reading_carries_its_note_and_others_do_not():
    m = make(POOL)
    assert "member records" in amigavars.read_variable(m, "pool-of-radiance", 0x6E82).note
    assert amigavars.read_variable(m, "pool-of-radiance", 0x4A5D).note is None


def test_parse_takes_hex_with_or_without_a_prefix():
    assert amigavars.parse_list("$4B10, 0x25e,8000") == [0x4B10, 0x25E, 0x8000]


def test_curse_member_range_reading_carries_its_note_and_others_do_not():
    m = make(CURSE)
    assert "current member" in amigavars.read_variable(m, "curse-of-the-azure-bonds", 0x7C00).note
    assert amigavars.read_variable(m, "curse-of-the-azure-bonds", 0x4B00).note is None
    assert "current member" in amigavars.read_variable(
        m, "curse-of-the-azure-bonds", 0x7C00).as_log()["note"]
