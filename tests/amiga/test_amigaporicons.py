"""The Amiga Pool of Radiance combat-figure art, and its loader's rules.

`goldbox/amiga_por_icons.py` decodes `/chead.dax` and `/cbody.dax`; the
write-up is `docs/240-amiga-pool-combat-figure.md`.  The first group builds
its blocks here from the documented layout and holds none of the game's
bytes.  The second reads the player's own disks through `gamedisks.yaml` and
skips when they are absent; what it asserts are counts and ids.
"""

from __future__ import annotations

import functools

import pytest

from automap import gamedisks
from goldbox import amiga_por_icons as art

# ---------------------------------------------------------------------------
# Generated blocks
# ---------------------------------------------------------------------------


def _encode(rows, stride=4):
    """A block in the documented layout, written without the decoder.

    Plane `p` holds bit `p` of each value, a row is `stride` bytes with the
    leftmost pixel in the top bit, and the planes follow one another.
    """
    height, width = len(rows), len(rows[0])
    plane = height * stride
    header = b"".join(v.to_bytes(2, "big")
                      for v in (height, width // 8, 0, 0, 1, plane))
    planes = bytearray(4 * plane)
    for p in range(4):
        for y, row in enumerate(rows):
            for x, value in enumerate(row):
                if value >> p & 1:
                    planes[p * plane + y * stride + x // 8] |= 0x80 >> (x % 8)
    return header + bytes(planes)


#: Sixteen distinct values left to right, then reversed, then a row whose
#: values are not their own bit-reversals: swapping the plane order maps 1 to
#: 8, and reading a byte's bits the wrong way round mirrors each eight.
PATTERN = (tuple(range(16)) + tuple(range(8)),
           tuple(reversed(range(16))) + tuple(range(8, 16)),
           (1, 2, 4, 8, 3, 6, 12, 9) * 3)


def test_a_generated_block_decodes_to_the_values_it_was_built_from():
    block = art.decode_block(_encode(PATTERN))
    assert (block.height, block.width) == (3, 24)
    assert block.rows == PATTERN


def test_the_unused_eight_pixels_of_each_row_are_not_drawn():
    raw = bytearray(_encode(PATTERN))
    plane = 3 * 4
    for p in range(4):
        for y in range(3):
            raw[12 + p * plane + y * 4 + 3] = 0xFF
    assert art.decode_block(bytes(raw)).rows == PATTERN


@pytest.mark.parametrize("damage", ["short", "long", "rows"])
def test_a_header_that_does_not_describe_its_bytes_is_rejected(damage):
    raw = bytearray(_encode(PATTERN))
    if damage == "short":
        raw = raw[:-1]
    elif damage == "long":
        raw += b"\0"
    else:
        raw[1] = 5
    with pytest.raises(art.PorArtError):
        art.decode_block(bytes(raw))


@pytest.mark.parametrize("kind, option, size, ids", [
    ("head", 5, 1, (5, 5)),
    ("head", 10, 2, (74, 74)),
    ("body", 5, 1, (5, 133)),
    ("body", 30, 2, (94, 222)),
])
def test_the_loader_adds_64_for_size_2_and_128_for_a_body_action_pose(
        kind, option, size, ids):
    assert art.block_ids(kind, option, size) == ids


def test_the_source_pairs_draw_the_art_unchanged():
    assert art.recolour_table(art.SOURCE_PAIRS) == tuple(range(16))


def test_each_nibble_replaces_the_value_in_the_same_nibble_of_its_pair():
    """Body pair `19`: a colour byte `4C` sends 1 to 4 and 9 to 12."""
    colours = bytes([0x4C]) + art.SOURCE_PAIRS[1:]
    table = art.recolour_table(colours)
    assert (table[1], table[9]) == (4, 12)
    assert [table[v] for v in range(16) if v not in (1, 9)] == [
        v for v in range(16) if v not in (1, 9)]


# ---------------------------------------------------------------------------
# The player's disks
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _both():
    from tools.icons import amigaporicons
    return amigaporicons, amigaporicons.amiga_art(), amigaporicons.dos_art()


def _measured():
    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    tool, amiga, dos = _both()
    if amiga is None:
        pytest.skip("no Amiga disk holds chead.dax and cbody.dax")
    if dos is None:
        pytest.skip("no DOS POOLRAD directory; set $FR_ARCHIVES")
    return tool, amiga, dos


def test_the_libraries_hold_the_blocks_the_loader_asks_for():
    _tool, amiga, _dos = _measured()
    assert sorted(amiga["head"]) == [*range(14), *range(64, 78)]
    assert sorted(amiga["body"]) == [*range(32), *range(64, 96),
                                     *range(128, 160), *range(192, 224)]
    for size in (1, 2):
        for option in range(14):
            assert set(art.block_ids("head", option, size)) <= set(
                amiga["head"])
        for option in range(32):
            assert set(art.block_ids("body", option, size)) <= set(
                amiga["body"])


def test_every_block_is_24_wide_and_heads_lose_two_rows_at_size_2():
    _tool, amiga, _dos = _measured()
    assert {(b.width, b.height) for i, b in amiga["head"].items()
            if i < 64} == {(24, 10)}
    assert {(b.width, b.height) for i, b in amiga["head"].items()
            if i >= 64} == {(24, 8)}
    assert {(b.width, b.height) for b in amiga["body"].values()} == {(24, 24)}


def test_50_bodies_and_11_heads_are_dos_blocks_pixel_for_pixel():
    """Fails if the plane order, the bit order or the value table is wrong."""
    tool, amiga, dos = _measured()
    measured = tool.counts(tool.classify(amiga, dos))
    assert measured["body"] == (50, 10, 78)
    assert measured["head"] == (11, 4, 17)


def test_most_amiga_options_with_a_dos_drawing_have_another_number():
    """GARWAN's large head 10 is DOS head 8, not DOS head 10."""
    tool, amiga, dos = _measured()
    found = {}
    for kind in ("head", "body"):
        for size in (1, 2):
            rows = tool.option_table(amiga, dos, kind, size)
            found[kind, size] = (
                sum(1 for _o, same, _n, _p in rows if same is not None),
                sum(1 for o, same, _n, _p in rows if same not in (None, o)))
    assert found == {("head", 1): (0, 0), ("head", 2): (11, 7),
                     ("body", 1): (5, 4), ("body", 2): (10, 7)}
    large_heads = tool.option_table(amiga, dos, "head", 2)
    assert large_heads[10][1] == 8


def test_the_preparer_reads_the_tables_the_module_holds():
    tool, _amiga, _dos = _measured()
    found = tool.find_files(("program",))
    if found is None:
        pytest.skip("no Amiga Pool /program here")
    lines = []
    assert tool.report_code(lines.append) == 0, lines
