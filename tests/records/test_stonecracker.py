"""StoneCracker 4.04 decrunching, `goldbox/stonecracker.py`.

The synthetic tests crunch their own bytes with a small encoder written here
from the format `goldbox.stonecracker`'s docstring describes, so every kind of
token, offset and relocation entry is decoded with no game data. The
disk-backed test decrunches the one crunched program the registry holds, the
`[a]` release of Amiga Pools of Darkness disk 1, and skips without it.
"""

from __future__ import annotations

import collections
import random
import struct

import pytest

from goldbox import amiga_hunks, stonecracker
from tests.support.hunks import hunk_file

LONG_WIDTH = 10                 # bits in a far offset, the trailer's first word
FAR = 0x220 + (1 << LONG_WIDTH) - 1


def _copy_length(o: int, off: int, data: bytes, limit: int) -> int:
    """How many bytes below `o` a copy from offset `off` reproduces."""
    n = 0
    while n < min(o, limit) and data[o - 1 - n] == data[o + off - n]:
        n += 1
    return n


def _crunch(data: bytes, gap: int = 0) -> tuple[bytes, collections.Counter]:
    """An `S404` stream decrunching to `data`, and the token kinds it used.

    Greedy, from the end of `data` backwards, as the decruncher writes. The
    bits are collected in the order the decruncher takes them, then stored as
    16-bit words backwards from the trailer, the first few in the trailer's
    part-used buffer.
    """
    bits: list[int] = []
    used: collections.Counter = collections.Counter()

    def put(value, n):
        bits.extend((value >> (n - 1 - i)) & 1 for i in range(n))

    def literals(run):
        while run:
            if len(run) >= 14:
                k = min(len(run), 45)
                put(0b1001, 4)
                put(0b1111, 4)
                put(k - 14, 5)
                for b in run[:k]:
                    put(b, 8)
                used["literal run"] += 1
            else:
                k = 1
                put(0, 1)
                put(run[0], 8)
                used["literal"] += 1
            run = run[k:]

    o = len(data)
    pending: list[int] = []
    while o > 0:
        best_n, best_off = 0, 0
        for off in range(0, min(len(data) - 1 - o, FAR) + 1):
            n = _copy_length(o, off, data, 600)
            if n > best_n:
                best_n, best_off = n, off
        if best_n < 2:
            pending.append(data[o - 1])
            o -= 1
            continue
        literals(pending)
        pending = []
        n = best_n
        if n <= 3:
            put(0b11, 2)
            put(n - 2, 1)
            used["copy 2-3"] += 1
        elif n <= 7:
            put(0b101, 3)
            put(n - 4, 2)
            used["copy 4-7"] += 1
        elif n <= 22:
            put(0b1001, 4)
            put(n - 8, 4)
            used["copy 8-22"] += 1
        else:
            put(0b1000, 4)
            rest = n - 23
            while rest >= 255:
                put(255, 8)
                rest -= 255
                used["copy 278 and over"] += 1
            put(rest, 8)
            used["copy 23 and over"] += 1
        if best_off < 0x20:
            put(0b01, 2)
            put(best_off, 5)
            used["offset 5 bits"] += 1
        elif best_off < 0x220:
            put(0b00, 2)
            put(best_off - 0x20, 9)
            used["offset 9 bits"] += 1
        else:
            put(1, 1)
            put(best_off - 0x220, LONG_WIDTH)
            used["offset far"] += 1
        o -= n
    literals(pending)

    left = len(bits) % 16
    first, rest = bits[:left], bits[left:]
    words = [int("".join(map(str, rest[i:i + 16])), 2) for i in range(0, len(rest), 16)]
    buffer = (int("".join(map(str, first)), 2) << (16 - left)) if left else 0
    body = b"".join(struct.pack(">H", w) for w in reversed(words))
    stream = (stonecracker.MAGIC + struct.pack(">III", gap, len(data), 4 + len(body))
              + body + struct.pack(">HHH", LONG_WIDTH, buffer, left))
    return stream, used


def _sample() -> bytes:
    """Bytes that need every token: noise, short and long repeats, a run of
    over 278 bytes, and a block repeated more than `0x220` bytes later."""
    rng = random.Random(404)
    noise = bytes(rng.randrange(256) for _ in range(60))
    block = bytes(rng.randrange(256) for _ in range(40))
    return (noise + b"ab" * 3 + b"xyz" * 9 + block + b"\x00" * 300
            + bytes(rng.randrange(256) for _ in range(700)) + block + noise[:9]
            + b"Q" * 5 + bytes(rng.randrange(256) for _ in range(20)))


def test_every_token_kind_decrunches_to_the_original_bytes():
    data = _sample()
    stream, used = _crunch(data)
    assert set(used) == {
        "literal", "literal run", "copy 2-3", "copy 4-7", "copy 8-22",
        "copy 23 and over", "copy 278 and over", "offset 5 bits",
        "offset 9 bits", "offset far"}
    assert stonecracker.decrunch(stream) == data


def test_a_stream_is_found_at_any_offset_and_its_header_read():
    stream, _ = _crunch(b"hello hello hello")
    blob = b"\x4e\x75" * 7 + stream
    head = stonecracker.header(blob, 14)
    assert (head.length, head.end) == (17, len(blob))
    assert stonecracker.decrunch(blob, 14) == b"hello hello hello"


def test_a_hand_assembled_stream_decrunches():
    # Decrunch order: literal "y", literal "x", copy 4 from offset 1 -- the
    # output is built from its last byte, so this spells "xyxyxy".
    bits = "0" + "01111001" + "0" + "01111000" + "101" + "00" + "01" + "00001"
    left = len(bits) % 16                       # 14 bits in the trailer buffer
    buffer = int(bits[:left], 2) << (16 - left)
    word = int(bits[left:].ljust(16, "0"), 2)
    stream = (b"S404" + struct.pack(">III", 0, 6, 6) + struct.pack(">H", word)
              + struct.pack(">HHH", 9, buffer, left))
    assert stonecracker.decrunch(stream) == b"xyxyxy"


@pytest.mark.parametrize("cut", [2, 6])
def test_a_stream_that_ends_early_raises(cut):
    stream, _ = _crunch(_sample())
    head = stonecracker.header(stream)
    short = (stream[:head.start] + stream[head.start + cut:head.trailer]
             + stream[head.trailer:])
    short = short[:12] + struct.pack(">I", head.packed - cut) + short[16:]
    with pytest.raises(stonecracker.StoneCrackerError):
        stonecracker.decrunch(short)


def test_a_copy_from_beyond_the_written_bytes_raises():
    # The first token is a copy, with nothing written yet to copy from.
    bits = "11" + "0" + "01" + "00000"
    stream = (b"S404" + struct.pack(">III", 0, 2, 4)
              + struct.pack(">HHH", 9, int(bits, 2) << (16 - len(bits)), len(bits)))
    with pytest.raises(stonecracker.StoneCrackerError, match="leaves the output"):
        stonecracker.decrunch(stream)


def test_a_header_whose_stream_runs_past_the_file_raises():
    stream, _ = _crunch(b"abcabcabc")
    with pytest.raises(stonecracker.StoneCrackerError):
        stonecracker.header(stream[:-2])
    with pytest.raises(stonecracker.StoneCrackerError):
        stonecracker.header(b"S403" + stream[4:])


def test_a_header_claiming_a_huge_length_raises_before_allocating():
    stream, _ = _crunch(b"abcabcabc")
    huge = stream[:8] + struct.pack(">I", 0xFFFFFFFF) + stream[12:]
    with pytest.raises(stonecracker.StoneCrackerError, match="decrunched bytes"):
        stonecracker.decrunch(huge)
    with pytest.raises(stonecracker.StoneCrackerError):
        stonecracker.header(huge)


# --- the decrunched executable layout ------------------------------------------

def _group(target: int, offsets: list[int], selector: int) -> bytes:
    width = {2: 3, 6: 2, 10: 1}[selector]
    out = struct.pack(">HHI", len(offsets), target, selector << 24 | offsets[0])
    for a, b in zip(offsets, offsets[1:]):
        out += (b - a).to_bytes(width, "big")
    return out + b"\x00" * (len(out) & 1)


CODE = bytes(range(64)) * 2                     # 128 bytes, 32 longs
DATA = b"DATA" * 5                              # 20 bytes in a 40-byte hunk


def _layout_bytes() -> bytes:
    """Three hunks: code with relocations in all three entry widths, data
    with one, and a hunk without contents; code asks for chip memory."""
    sizes = [len(CODE) // 4 | 1 << 30, 10, 6]
    out = struct.pack(">I", 2) + b"".join(struct.pack(">I", s) for s in sizes)
    out += struct.pack(">HH", 0x4000, len(CODE) // 4) + CODE
    out += b"\x00\x00"
    out += _group(1, [0, 4, 12], 10)              # one-byte entries, odd length
    out += _group(0, [16, 100], 6)                # two-byte entries
    out += _group(2, [20, 24], 2)                 # three-byte entries
    out += b"\x00\x00"                            # no more groups
    out += struct.pack(">HH", 0x4000, len(DATA) // 4) + DATA
    out += b"\x00\x00" + _group(0, [8], 10) + b"\x00\x00"
    out += struct.pack(">H", 0x8000)              # the hunk without contents
    return out + b"\xff\xff"


def test_the_layout_gives_each_hunk_its_size_contents_and_relocations():
    code, data, bss = stonecracker.segments(_layout_bytes())
    assert (code.contents, code.allocated, code.size >> 30) == (CODE, 128, 1)
    assert code.relocs == {1: [0, 4, 12], 0: [16, 100], 2: [20, 24]}
    assert (data.contents, data.allocated, data.relocs) == (DATA, 40, {0: [8]})
    assert (bss.contents, bss.allocated, bss.relocs) == (None, 24, {})


def test_the_rebuilt_hunk_file_reads_as_code_data_and_bss():
    program = stonecracker.hunk_file(stonecracker.segments(_layout_bytes()))
    hunks, relocs = amiga_hunks.parse(program)
    assert [(h.kind, h.size, h.allocated) for h in hunks] == [
        ("CODE", 128, 128), ("DATA", 20, 40), ("BSS", 24, 24)]
    assert program[hunks[0].file_offset:hunks[0].file_offset + 128] == CODE
    assert relocs == {(0, 0): 1, (0, 4): 1, (0, 12): 1, (0, 16): 0,
                      (0, 100): 0, (0, 20): 2, (0, 24): 2, (1, 8): 0}
    assert struct.unpack_from(">I", program, 20)[0] >> 30 == 1     # chip


def test_kinds_can_be_given_when_the_default_guess_is_wrong():
    hunks = stonecracker.segments(_layout_bytes())
    program = stonecracker.hunk_file(hunks, [amiga_hunks.HUNK_CODE] * 2
                                     + [amiga_hunks.HUNK_BSS])
    assert [h.kind for h in amiga_hunks.parse(program)[0]] == ["CODE", "CODE", "BSS"]


@pytest.mark.parametrize("damage, message", [
    (lambda b: b[:-2], "end marker"),
    (lambda b: b.replace(b"\x0a\x00\x00\x08", b"\x07\x00\x00\x08"), "width 7"),
    (lambda b: b[:4 + 12] + b"\x00\x00" + b[4 + 12:], "before any hunk"),
    (lambda b: b[:-2] + b"\x80\x00\xff\xff", "more than the 3"),
])
def test_a_layout_that_does_not_add_up_raises(damage, message):
    with pytest.raises(stonecracker.StoneCrackerError, match=message):
        stonecracker.segments(damage(_layout_bytes()))


def test_a_relocation_outside_its_hunk_raises():
    layout = _layout_bytes()
    # The data hunk's relocation at offset 8 of 20 bytes moves to 17.
    damaged = layout.replace(_group(0, [8], 10), _group(0, [17], 10))
    assert damaged != layout
    with pytest.raises(stonecracker.StoneCrackerError, match="outside hunk 1"):
        stonecracker.segments(damaged)


# --- a crunched executable ---------------------------------------------------

def _crunched_program() -> bytes:
    """A Hunk executable as StoneCracker lays one out: a small first hunk,
    then a code hunk holding a stand-in for the decrunch routine and the
    `S404` stream, padded to a long."""
    stream, _ = _crunch(_layout_bytes())
    body = b"\x4e\x71" * 10 + stream
    body += b"\x00" * (-len(body) % 4)
    return hunk_file([(amiga_hunks.HUNK_CODE, b"\x4e\x75\x00\x00", []),
                      (amiga_hunks.HUNK_CODE, body, [])])


def test_a_crunched_program_decrunches_to_its_hunk_file():
    program = _crunched_program()
    assert stonecracker.is_crunched(program)
    expected = stonecracker.hunk_file(stonecracker.segments(_layout_bytes()))
    assert stonecracker.uncrunch(program) == expected
    assert stonecracker.as_loaded(program) == expected


def test_an_uncrunched_program_is_left_as_it_is():
    program = stonecracker.hunk_file(stonecracker.segments(_layout_bytes()))
    assert not stonecracker.is_crunched(program)
    assert stonecracker.as_loaded(program) is program
    with pytest.raises(stonecracker.StoneCrackerError):
        stonecracker.uncrunch(program)


def test_the_magic_alone_does_not_make_a_program_crunched():
    program = hunk_file([(amiga_hunks.HUNK_CODE, b"\x4e\x75\x00\x00S404" + bytes(8), [])])
    assert not stonecracker.is_crunched(program)


# --- the player's own disks --------------------------------------------------

@pytest.fixture(scope="module")
def crunched_programs():
    """`{label: program}` for every crunched Amiga program file here."""
    from automap import gamedisks
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import amigasaves
    out: dict[str, bytes] = {}
    if not gamedisks.candidates("amiga"):
        return out
    for label, image in amigasaves.images():
        try:
            disk = AmigaDisk(bytearray(image))
            entries = list(disk.walk())
        except Exception:
            continue
        for path, _entry in entries:
            try:
                body = disk.read_file(path)
            except Exception:
                continue
            if body[:4] == struct.pack(">I", amiga_hunks.HUNK_HEADER) and \
                    stonecracker.is_crunched(body):
                out[f"{label}:{path}"] = body
    return out


def test_the_crunched_pools_of_darkness_program_decrunches_whole(crunched_programs):
    if not crunched_programs:
        pytest.skip("no StoneCracker-crunched Amiga program in the registry")
    for label, program in crunched_programs.items():
        head = stonecracker.find(program)
        layout = stonecracker.decrunch(program, head.at)
        assert len(layout) == head.length, label
        hunks = stonecracker.segments(layout)
        program_bytes = stonecracker.hunk_file(hunks)
        rebuilt, relocs = amiga_hunks.parse(program_bytes)
        assert [h.allocated for h in rebuilt] == [h.allocated for h in hunks]
        assert [h.kind for h in rebuilt] == ["CODE", "DATA", "BSS"], label
        # Every relocated long lands inside its target hunk, except SAS/C's
        # small-data base, `lea data+0x7FFE, a4`, which points past the
        # middle of the data hunk by design (the uncrunched builds have the
        # same one).
        outside = []
        for (source, at), target in relocs.items():
            value = struct.unpack_from(
                ">I", program_bytes, rebuilt[source].file_offset + at)[0]
            if value >= rebuilt[target].allocated:
                outside.append(value)
        assert outside == [0x7FFE], label
