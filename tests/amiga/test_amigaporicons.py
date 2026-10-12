"""The Amiga Pool of Radiance combat-figure art, and its loader's rules.

`goldbox/amiga_por_icons.py` decodes `/chead.dax` and `/cbody.dax`; the
write-up is `docs/240-amiga-pool-combat-figure.md`.  The first group builds
its blocks, figures and executable here from the documented layout and holds
none of the game's bytes or colours.  The second reads the player's own disks
through `gamedisks.yaml` and skips when they are absent; what it asserts are
counts, ids, offsets and where a figure matches a capture of the game's own
ICON screen, which `scratch.cache_dir` holds and nothing commits.
"""

from __future__ import annotations

import functools
import hashlib

import pytest

from automap import gamedisks
from goldbox import amiga_hunks
from goldbox import amiga_por_icons as art
from tests.support.hunks import hunk_file

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


def _header(height, eights, plane):
    return b"".join(v.to_bytes(2, "big")
                    for v in (height, eights, 0, 0, 1, plane))


@pytest.mark.parametrize("damage", ["short", "long", "rows", "no header",
                                    "no width", "narrow rows"])
def test_a_header_that_does_not_describe_its_bytes_is_rejected(damage):
    raw = bytearray(_encode(PATTERN))
    if damage == "short":
        raw = raw[:-1]
    elif damage == "long":
        raw += b"\0"
    elif damage == "rows":
        raw[1] = 5
    elif damage == "no header":
        raw = raw[:11]
    elif damage == "no width":
        raw = bytearray(_header(3, 0, 12) + bytes(48))
    else:
        # Two bytes a row cannot hold the 24 pixels the header asks for.
        raw = bytearray(_header(3, 3, 6) + bytes(24))
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


def _block(rows):
    return art.ArtBlock(len(rows), len(rows[0]),
                        tuple(tuple(r) for r in rows))


def _art(head_ids=(3, 67), body_ids=(5, 133, 69, 197)):
    """Generated heads and bodies, 8 wide; a head is 2 rows, a body 4.

    Each head draws value 1 in column `id % 8` of row 0; each body draws 9
    in column `id % 8` of row 3, 6 in column 0 of row 1 and 12 in its last
    column of row 2.  So which block a pose used, and whether the head went
    in, can be read off the pixels.
    """
    heads = {}
    for hid in head_ids:
        rows = [[0] * 8 for _ in range(2)]
        rows[0][hid % 8] = 1
        heads[hid] = _block(rows)
    bodies = {}
    for bid in body_ids:
        rows = [[0] * 8 for _ in range(4)]
        rows[3][bid % 8] = 9
        rows[1][0] = 6
        rows[2][7] = 12
        bodies[bid] = _block(rows)
    return heads, bodies


def test_a_pose_is_its_body_with_the_head_ored_in_from_row_0():
    heads, bodies = _art()
    ready, action = art.compose(heads, bodies, 3, 5, 1, art.SOURCE_PAIRS)
    assert ready[0][3] == 1 and ready[3][5] == 9
    assert action[0][3] == 1 and action[3][133 % 8] == 9
    assert ready[1][0] == 6 and ready[2][7] == 12


def test_size_2_takes_the_large_blocks_for_both_poses():
    heads, bodies = _art()
    ready, action = art.compose(heads, bodies, 3, 5, 2, art.SOURCE_PAIRS)
    assert ready[0][67 % 8] == 1 and ready[3][69 % 8] == 9
    assert action[3][197 % 8] == 9


def test_overlapping_head_and_body_values_are_ored():
    heads = {0: _block([[3, 0], [0, 0]])}
    bodies = {0: _block([[4, 0], [0, 0], [0, 0]]),
              128: _block([[0, 0], [0, 0], [0, 0]])}
    ready, _ = art.compose(heads, bodies, 0, 0, 0, art.SOURCE_PAIRS)
    assert ready[0][0] == 7


def test_the_record_colours_recolour_both_poses_and_leave_12_alone():
    heads, bodies = _art()
    colours = bytes([0x4C]) + art.SOURCE_PAIRS[1:3] + bytes([0x7D]) \
        + art.SOURCE_PAIRS[4:]
    ready, action = art.compose(heads, bodies, 3, 5, 1, colours)
    for pose in (ready, action):
        assert pose[0][3] == 4          # head value 1 -> the pair 19's high
        assert pose[1][0] == 13         # body 6 -> the pair 76's low
        assert pose[2][7] == 12         # no pair holds 12
    assert ready[3][5] == 12            # body 9 -> the pair 19's low


def test_empty_pixels_stay_empty_and_a_zero_nibble_draws_colour_0():
    heads, bodies = _art()
    colours = bytes([0x10]) + art.SOURCE_PAIRS[1:]
    ready, _ = art.compose(heads, bodies, 3, 5, 1, colours)
    assert ready[0][0] is None and ready[3][0] is None
    assert ready[3][5] == 0


def test_a_missing_block_is_an_error_not_a_blank_pose():
    heads, bodies = _art()
    with pytest.raises(art.PorArtError):
        art.compose(heads, bodies, 4, 5, 1, art.SOURCE_PAIRS)
    with pytest.raises(art.PorArtError):
        art.compose(heads, bodies, 3, 6, 1, art.SOURCE_PAIRS)


def test_the_box_shows_through_only_where_the_pose_is_empty():
    frame = _block([[15, 15], [13, 4]])
    assert art.on_frame(frame, ((None, 2), (0, None))) == ((15, 2), (0, 4))
    with pytest.raises(art.PorArtError):
        art.on_frame(frame, ((None,),))


#: The installed table's sixteen `(red, green, blue)` nibbles.  No entry has
#: two equal channels, so a swapped red and blue, or a nibble read from the
#: wrong place, gives another colour.
_CHANNELS = tuple((i, (5 * i + 3) % 16, (11 * i + 6) % 16) for i in range(16))


def _program(bar=art.ICON_MENU_BAR):
    """A two-hunk executable whose ICON menu installs the second table.

    CODE: the menu loads `bar`'s address, calls a stub to a routine that
    loads a table without copying it, then a stub to a setter that does copy.
    DATA: the bar, the installed table, and a table nothing installs.
    """
    def word(n):
        return n.to_bytes(2, "big")

    def long(n):
        return n.to_bytes(4, "big")

    nop = word(0x4E71)
    code = bytearray(nop * 0x48)
    code[0x00:0x06] = word(0x41F9) + long(0x00)          # lea bar, a0
    code[0x08:0x0C] = word(0x4EBA) + word(0x20 - 0x0A)   # jsr decoy stub
    code[0x0C:0x10] = word(0x4EBA) + word(0x26 - 0x0E)   # jsr setter stub
    code[0x10:0x12] = word(0x4E75)
    code[0x20:0x26] = word(0x4EF9) + long(0x40)          # jmp decoy
    code[0x26:0x2C] = word(0x4EF9) + long(0x60)          # jmp setter
    code[0x40:0x46] = word(0x41F9) + long(0x40)          # lea other, a0
    code[0x46:0x48] = word(0x4E75)
    code[0x60:0x64] = bytes.fromhex("4E55FFE0")          # link a5, #-32
    code[0x64:0x6A] = word(0x41F9) + long(0x20)          # lea table, a0
    code[0x6A:0x76] = bytes.fromhex("43EDFFE0 7007 22D8 51C8FFFC")
    code[0x76:0x7A] = bytes.fromhex("4E5D4E75")
    data = bytearray(0x60)
    data[0:len(bar)] = bar
    for i in range(16):
        red, green, blue = _CHANNELS[i]
        data[0x20 + 2 * i:0x22 + 2 * i] = word(red << 8 | green << 4 | blue)
        data[0x40 + 2 * i:0x42 + 2 * i] = word(0xF00)
    return hunk_file([
        (amiga_hunks.HUNK_CODE, bytes(code),
         [(1, [0x02, 0x42, 0x66]), (0, [0x22, 0x28])]),
        (amiga_hunks.HUNK_DATA, bytes(data), []),
    ])


def test_the_palette_is_the_table_the_icon_menu_installs():
    program = _program()
    palette = art.icon_palette(program)
    assert [rgb[0] for rgb in palette] == [17 * r for r, _g, _b in _CHANNELS]
    assert [rgb[1] for rgb in palette] == [17 * g for _r, g, _b in _CHANNELS]
    assert [rgb[2] for rgb in palette] == [17 * b for _r, _g, b in _CHANNELS]
    lea, call, setter, table = art.icon_palette_chain(program)
    assert program[lea:lea + 2] == b"\x41\xf9"
    assert program[call:call + 2] == b"\x4e\xba"
    assert program[setter:setter + 4] == bytes.fromhex("4E55FFE0")
    assert program[table:table + 2] == (_CHANNELS[0][1] << 4
                                        | _CHANNELS[0][2]).to_bytes(2, "big")


def test_an_executable_without_the_icon_menu_has_no_icon_palette():
    with pytest.raises(art.PorArtError):
        art.icon_palette(_program(bar=b"Parts colour-1 colour-2 Size Exit"))
    with pytest.raises(art.PorArtError):
        art.icon_palette(b"not a hunk file at all")


@pytest.mark.parametrize("length", [4, 10, 20, 40])
def test_a_truncated_executable_has_no_icon_palette(length):
    with pytest.raises(art.PorArtError):
        art.icon_palette(_program()[:length])


def test_a_pose_larger_than_the_screen_or_empty_cannot_be_looked_for():
    import numpy

    from tools.icons import amigaporicons
    screen = numpy.zeros((10, 10), dtype=numpy.int32)
    pose = (((0, 0, 0),) * 24,) * 24
    with pytest.raises(amigaporicons.CaptureError):
        amigaporicons.find_pose(screen, pose)
    with pytest.raises(amigaporicons.CaptureError):
        amigaporicons.find_pose(screen, ())
    with pytest.raises(amigaporicons.CaptureError):
        amigaporicons.find_pose(screen, ((),))


def test_a_pose_is_found_where_it_is_drawn():
    import numpy

    from tools.icons import amigaporicons
    screen = numpy.zeros((6, 7), dtype=numpy.int32)
    screen[2, 3] = 0x112233
    places, fewest = amigaporicons.find_pose(screen, (((0x11, 0x22, 0x33),),))
    assert (places, fewest) == ([(3, 2)], 0)


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


def _program_of_record(tool):
    code = tool.program()
    if code is None:
        pytest.skip("no Amiga Pool /program here")
    if hashlib.sha256(code).hexdigest() != tool.PROGRAM_SHA256:
        pytest.skip("not the /program build the offsets were read from")
    return code


def test_the_icon_menu_installs_the_table_at_0x03b260():
    tool, _amiga, _dos = _measured()
    code = _program_of_record(tool)
    assert art.icon_palette_chain(code) == (0x019C64, 0x019C96, 0x03499E,
                                            0x03B260)


def test_the_icon_box_is_comspr_block_12():
    _tool, amiga, _dos = _measured()
    frame = amiga["frame"][art.FRAME_BLOCK]
    assert (frame.width, frame.height) == (24, 24)


#: Where each pose is in a capture, in Amiga pixels.  The ICON screen draws
#: the figure twice, the one the character has (top row) and the one being
#: edited (bottom row); nothing was edited, so both rows hold it.
CAPTURE_PLACES = {"ready": [(59, 73), (59, 121)],
                  "action": [(131, 73), (131, 121)]}


@pytest.mark.parametrize("name", ["GARWAN", "STONEBEARD", "LAURANN"])
def test_the_composed_figure_is_the_game_s_own_pixel_for_pixel(name):
    """LAURANN is the control: nothing was derived from her capture."""
    from tools.registry import scratch
    tool, _amiga, _dos = _measured()
    _program_of_record(tool)
    crop = scratch.cache_dir("acceptance", "WISH-378", "shots",
                             f"{name.lower()}-icon-crop.png")
    if not crop.exists():
        pytest.skip(f"no ICON-screen capture of {name} here")
    found = tool.compare_capture(name, crop)
    if found is None:
        pytest.skip(f"no Amiga Pool record called {name} here")
    assert {pose: places for pose, (places, _fewest) in found.items()} \
        == CAPTURE_PLACES


def test_the_preparer_reads_the_tables_the_module_holds():
    tool, _amiga, _dos = _measured()
    found = tool.find_files(("program",))
    if found is not None and hashlib.sha256(found[1]["program"]).hexdigest(
            ) != tool.PROGRAM_SHA256:
        pytest.skip("not the /program build the offsets were read from")
    if found is None:
        pytest.skip("no Amiga Pool /program here")
    lines = []
    assert tool.report_code(lines.append) == 0, lines


# ---------------------------------------------------------------------------
# The exact-drawing table the conversions use
# ---------------------------------------------------------------------------


def test_the_exact_drawing_table_is_one_to_one_and_inverts():
    assert set(art.SAME_DRAWING) == {
        (kind, size) for kind in ("head", "body") for size in (1, 2)}
    for (kind, size), rows in art.SAME_DRAWING.items():
        assert len(set(rows.values())) == len(rows), (kind, size)
        for amiga, dos in rows.items():
            assert art.dos_option(kind, amiga, size) == dos
            assert art.amiga_option(kind, dos, size) == amiga
    assert art.dos_option("head", 10, 2) == 8
    assert art.dos_option("head", 0, 1) is None
    assert art.amiga_option("body", 3, 2) is None
    for size in (0, 3, None):
        assert art.dos_option("head", 10, size) is None
        assert art.amiga_option("head", 8, size) is None


def test_the_exact_drawing_table_is_what_the_disks_measure():
    """Fails if a row is wrong against the art."""
    tool, amiga, dos = _measured()
    for kind in ("head", "body"):
        for size in (1, 2):
            rows = tool.option_table(amiga, dos, kind, size)
            measured = {option: same for option, same, _n, _p in rows
                        if same is not None}
            assert measured == art.SAME_DRAWING[kind, size], (kind, size)


def test_every_option_maps_to_a_drawing_in_both_directions():
    """An option has an identical drawing (0 pixels) or a nearest one, never
    neither, and a nearest one is not also an identical one."""
    for kind, limit in (("head", 14), ("body", 32)):
        for size in (1, 2):
            for option in range(limit):
                for lookup, other in ((art.dos_drawing, art.dos_option),
                                      (art.amiga_drawing, art.amiga_option)):
                    number, pixels = lookup(kind, option, size)
                    assert 0 <= number < limit
                    assert (pixels == 0) == (
                        other(kind, option, size) is not None)
    assert art.dos_drawing("body", 30, 2) == (20, 63)
    assert art.dos_drawing("head", 10, 2) == (8, 0)
    assert art.amiga_drawing("body", 24, 2) == (11, 64)
    for size in (0, 3, None):
        assert art.dos_drawing("head", 10, size) is None
        assert art.amiga_drawing("head", 8, size) is None


def test_the_nearest_tables_are_what_the_disks_measure():
    """Fails if a row, a pixel count or a tie-break is wrong against the art."""
    tool, amiga, dos = _measured()
    to_dos, to_amiga = tool.nearest_tables(amiga, dos)
    assert to_dos == art.NEAREST_DOS
    assert to_amiga == art.NEAREST_AMIGA
