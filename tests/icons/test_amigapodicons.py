"""The Amiga Pools of Darkness combat figure, as the ICON screen draws it.

`goldbox/amiga_pod_icons.py` holds the screen and
`goldbox/amiga_later_icons.py` the tile and recolour rules it shares with
Curse and Silver Blades; the write-up is `docs/199-amiga-combat-icons.md`,
"Pools of Darkness".  The first group builds its tiles, libraries and
executables here from the documented layout and holds none of the game's
bytes or colours.  The second reads the player's own disks through
`gamedisks.yaml` and skips when they are absent; what it asserts are counts,
ids and where a figure matches a capture of the game's own ICON screen,
which `scratch.cache_dir` holds and nothing commits.
"""

from __future__ import annotations

import functools
import struct

import pytest

from automap import gamedisks
from goldbox import amiga_hunks
from goldbox import amiga_later_icons as later
from goldbox import amiga_pod_icons as pod
from tests.support.hunks import hunk_file

# ---------------------------------------------------------------------------
# Generated tiles
# ---------------------------------------------------------------------------


def _tile(rows, opaque=None, kind=0xE1):
    """A tile in the documented layout, written without the decoder.

    A type byte with `E` in its high nibble has five colour planes; a low
    nibble of 1 puts a mask plane first, set where the pixel is see-through.
    Plane `mask + p` holds bit `p` of the palette entry.
    """
    depth = 5 if kind & 0xF0 == 0xE0 else 4
    mask = kind & 0x0F
    height, width = len(rows), len(rows[0])
    eights = width // 8
    plane = height * eights
    planes = bytearray((depth + mask) * plane)
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            bit = 0x80 >> (x % 8)
            at = y * eights + x // 8
            if mask and not (opaque is None or opaque[y][x]):
                planes[at] |= bit
            for p in range(depth):
                if value >> p & 1:
                    planes[(mask + p) * plane + at] |= bit
    raw = struct.pack(">HHHBB", height, 0, 0, eights, kind) + bytes(planes)
    return raw + b"\0" * (len(raw) % 2)


#: Every entry 0 to 31 once, then 16 to 23 reversed, and a row whose entries
#: are not their own bit reversals: reading four planes loses 16, and
#: reading the planes in the wrong order maps 1 to 16.
PATTERN = (tuple(range(24)),
           tuple(range(24, 32)) + tuple(reversed(range(16, 24))) + (0,) * 8,
           (1, 2, 4, 8, 16, 3, 6, 12, 24, 17, 5, 10) * 2)
HOLES = (tuple(x % 3 != 0 for x in range(24)),
         tuple(x < 12 for x in range(24)),
         (True,) * 24)


def test_a_five_plane_tile_decodes_to_entries_up_to_31_and_its_mask():
    tile = later.decode_tile(_tile(PATTERN, HOLES))
    assert (tile.height, tile.width) == (3, 24)
    assert tile.rows == PATTERN
    assert tile.opaque == HOLES


def test_a_five_plane_tile_without_a_mask_is_opaque_everywhere():
    tile = later.decode_tile(_tile(PATTERN, kind=0xE0))
    assert tile.rows == PATTERN
    assert all(all(row) for row in tile.opaque)


def test_a_four_plane_type_byte_still_reads_four_planes():
    rows = tuple(tuple(v & 0x0F for v in row) for row in PATTERN)
    assert later.decode_tile(_tile(rows, HOLES, kind=0x01)).rows == rows
    # Five planes' bytes under a four-plane type byte is the wrong length.
    with pytest.raises(later.LaterArtError):
        later.decode_tile(bytes([0, 3, 0, 0, 0, 0, 3, 0x01])
                          + _tile(PATTERN, HOLES)[8:])


# ---------------------------------------------------------------------------
# Generated palettes, libraries and executables
# ---------------------------------------------------------------------------


def _palette(colours, kind=0xE8):
    return (struct.pack(">HHHBB", 0, 0, 0x100, 0, kind)
            + bytes(c for rgb in colours for c in rgb))


#: 32 colours, each channel a multiple of 17 so that it survives the
#: setter's `(byte + 8) // 17`, all different.
COLOURS = tuple((17 * (i % 16), 17 * (i // 16), 17 * ((7 * i) % 16))
                for i in range(32))


def test_a_deep_palette_block_holds_32_colours_and_a_plain_one_16():
    assert later.palette_block(_palette(COLOURS)) == COLOURS
    assert later.palette_block(_palette(COLOURS[:16], 0x08)) == COLOURS[:16]
    with pytest.raises(later.LaterArtError):
        later.palette_block(_palette(COLOURS[:16]))


def _glib(blocks, ids=None):
    """A stored `GLIB` tile library: indexed by `ids` when given."""
    if ids is not None:
        index = struct.pack(">H", len(blocks)) + b"".join(
            struct.pack(">HH", art, n + 1) for n, art in enumerate(ids))
        blocks = [index, *blocks]
    table = 16 + 4 * (len(blocks) + 1)
    offsets = [table]
    for block in blocks:
        offsets.append(offsets[-1] + len(block))
    body = struct.pack(f">{len(offsets)}I", *offsets) + b"".join(blocks)
    return (b"GLIB" + struct.pack(">IHBB", 16 + len(body), len(blocks), 0,
                                  0 if ids is None else 1) + b"TILE" + body)


#: A generated entry table: sixteen of the 32 entries, out of order and
#: half of them past 15, and the six recoloured part values.
ENTRY = bytes([0, 17, 5, 31, 25, 13, 19, 6, 4, 18, 11, 10, 28, 27, 9, 15])
PARTS = bytes([1, 2, 3, 4, 6, 7])


def _executable(entry=ENTRY, frame=False):
    """A code and a data hunk whose code holds the recolour builder's
    instructions, `lea` displacements naming the two tables; with `frame`,
    the German build's form, which reads its counter off the stack."""
    data = bytearray(0x80)
    data[0x20:0x30] = entry
    data[0x40:0x46] = PARTS

    def displacement(at):
        return struct.pack(">h", at - 0x7FFE)

    middle = (bytes.fromhex("7000102dffdf43ec") if frame
              else bytes.fromhex("7000100243ec"))
    code = (b"\x4e\x71" * 8 + bytes.fromhex("0241000f41ec")
            + displacement(0x20) + middle + displacement(0x40)
            + b"\x4e\x71" * 2 + b"\x4e\x75\x4e\x75")
    code += b"\x4e\x71" * (len(code) % 4 // 2)
    return hunk_file([(amiga_hunks.HUNK_CODE, bytes(code), []),
                      (amiga_hunks.HUNK_DATA, bytes(data), [])])


@pytest.mark.parametrize("frame", [False, True], ids=["English", "German"])
def test_a_32_colour_entry_table_is_read_through_the_builder(frame):
    found = later.recolour_tables(_executable(frame=frame), later.DEEP_COLOURS)
    assert found == (ENTRY, PARTS)


def test_a_table_past_16_entries_is_not_a_16_colour_title_s():
    with pytest.raises(later.LaterArtError):
        later.recolour_tables(_executable())
    with pytest.raises(later.LaterArtError):
        later.recolour_tables(_executable(entry=bytes(16)),
                              later.DEEP_COLOURS)
    with pytest.raises(later.LaterArtError):
        later.recolour_tables(_executable(entry=bytes([40]) + ENTRY[1:]),
                              later.DEEP_COLOURS)


def test_the_recolour_works_over_32_entries():
    colours = bytes([0x91, 0xA2, 0xB3, 0xC4, 0xE6, 0xF7])
    table = later.recolour_table(colours, ENTRY, PARTS, later.DEEP_COLOURS)
    assert len(table) == 32
    # The part 1 pair: entry[1] takes entry[low 1], entry[9] entry[high 9].
    assert table[ENTRY[1]] == ENTRY[1] and table[ENTRY[9]] == ENTRY[9]
    swapped = later.recolour_table(bytes([0x19]) + colours[1:], ENTRY,
                                   PARTS, later.DEEP_COLOURS)
    assert (swapped[ENTRY[1]], swapped[ENTRY[9]]) == (ENTRY[9], ENTRY[1])
    # Entries no part names stay as they are, past 15 too.
    assert table[ENTRY[13]] == ENTRY[13] == 27
    assert table[30] == 30


def _filled(value, height=24, holes=()):
    rows = tuple(tuple(value for _ in range(24)) for _ in range(height))
    opaque = tuple(tuple((y, x) not in holes for x in range(24))
                   for y in range(height))
    return later.decode_tile(_tile(rows, opaque))


def _art():
    """Heads 2 and 66 (8 rows), bodies 7, 135, 71 and 199, each one
    entry, the head's last row see-through at x 0."""
    heads = {2: _filled(ENTRY[4], 8, {(7, 0)}),
             66: _filled(ENTRY[12], 10)}
    bodies = {7: _filled(ENTRY[1], holes={(0, 1), (20, 5)}),
              7 + 128: _filled(ENTRY[2], holes={(23, 23)}),
              71: _filled(ENTRY[3]), 71 + 128: _filled(ENTRY[11])}
    return heads, bodies


def test_one_head_serves_both_poses_and_covers_each_body():
    heads, bodies = _art()
    colours = bytes([0x91, 0xA2, 0xB3, 0xC4, 0xE6, 0xF7])
    ready, action = later.compose(heads, bodies, 2, 7, 1, colours, ENTRY,
                                  PARTS, None, later.DEEP_COLOURS, 0)
    assert ready[0][0] == action[0][0] == ENTRY[4]
    # Where the head is see-through the body shows; under it, the body is
    # covered even where it is see-through.
    assert ready[7][0] == ENTRY[1] and action[7][0] == ENTRY[2]
    assert ready[0][1] == ENTRY[4]
    assert ready[20][5] is None and action[23][23] is None
    assert ready[20][6] == ENTRY[1] and action[20][5] == ENTRY[2]
    big, big_action = later.compose(heads, bodies, 2, 7, 2, colours, ENTRY,
                                    PARTS, None, later.DEEP_COLOURS, 0)
    assert big[0][0] == big_action[0][0] == ENTRY[12]
    assert (big[12][0], big_action[12][0]) == (ENTRY[3], ENTRY[11])
    # Curse's rule asks for head 130, which this CHEAD.TLB has not got.
    with pytest.raises(later.LaterArtError, match="no art 130"):
        later.compose(heads, bodies, 2, 7, 1, colours, ENTRY, PARTS, None,
                      later.DEEP_COLOURS)


class _Disk:
    """Enough of `AmigaDisk` for :func:`pod.disk_files`."""

    def __init__(self, files):
        self.files = files

    def walk(self):
        return [(f"/{name}", None) for name in self.files]

    def read_file(self, path):
        return self.files[path.strip("/")]


def _disks(frames=(15, 16), palette_kind=0xE8):
    box = _tile(tuple(tuple([ENTRY[6]] * 24) for _ in range(24)), kind=0xE0)
    other = _tile(tuple(tuple([ENTRY[7]] * 24) for _ in range(24)),
                  kind=0xE0)
    comspr = _glib([other, *[box] * len(frames)], (25, *frames))
    always = _glib([_palette(COLOURS if palette_kind == 0xE8
                             else COLOURS[:16], palette_kind)])
    heads, bodies = _art()
    first = _Disk({"Pools of Darkness": _executable(),
                   "DISK1/COMSPR.TLB": comspr, "DISK1/ALWAYS.TLB": always})
    third = _Disk({
        "Disk3/CHEAD.TLB": _glib([_tile(((ENTRY[4],) * 24,) * 8)], [2]),
        "Disk3/CBODY.TLB": _glib([_tile(((ENTRY[1],) * 24,) * 24)] * 2,
                                 [7, 135])})
    return first, third


def test_the_art_comes_off_disk_1_and_disk_3_whatever_their_case():
    first, third = _disks()
    files = pod.disk_files([third, first])
    assert set(files) == {later.EXECUTABLE, later.FRAME_FILE,
                          later.PALETTE_FILE, later.HEAD_FILE,
                          later.BODY_FILE}
    art = pod.read_art(files)
    assert art.palette == COLOURS
    assert (art.entry, art.parts) == (ENTRY, PARTS)
    assert [f.rows[0][0] for f in art.frames] == [ENTRY[6], ENTRY[6]]
    ready, action = art.drawn(2, 7, 1, bytes([0x91, 0xA2, 0xB3, 0xC4,
                                              0xE6, 0xF7]))
    assert ready[0][0] == action[0][0] == COLOURS[ENTRY[4]]
    assert ready[23][0] == COLOURS[ENTRY[1]]
    with pytest.raises(later.LaterArtMissing, match="CHEAD.TLB"):
        pod.disk_files([first])
    with pytest.raises(later.LaterArtMissing, match="executable"):
        pod.disk_files([third])


def test_a_missing_box_or_a_16_colour_palette_is_not_drawn():
    first, third = _disks(frames=(15,))
    with pytest.raises(later.LaterArtError, match="no art 16"):
        pod.read_art(pod.disk_files([first, third]))
    first, third = _disks(palette_kind=0x08)
    with pytest.raises(later.LaterArtError, match="16 colours"):
        pod.read_art(pod.disk_files([first, third]))


# ---------------------------------------------------------------------------
# The player's disks
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _tool():
    from tools.icons import amigapodicons
    opened = amigapodicons.disks()
    return amigapodicons, opened, amigapodicons.art(opened)


def _measured():
    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    tool, opened, art = _tool()
    if art is None:
        pytest.skip("not all of Pools of Darkness's Amiga disks are here")
    return tool, opened, art


def test_every_figure_tile_is_five_planes_and_a_mask_at_the_loader_s_ids():
    _tool_, _opened, art = _measured()
    small = set(range(14))
    assert set(art.heads) == small | {i + 64 for i in small}
    poses = set(range(32)) | set(range(64, 96))
    assert set(art.bodies) == poses | {i + 128 for i in poses}
    for tile in (*art.heads.values(), *art.bodies.values()):
        assert tile.width == 24
        assert {v for row in tile.rows for v in row} <= set(art.entry)
    assert {t.height for t in art.heads.values()} == {8, 10}
    assert any(v > 15 for t in art.bodies.values() for row in t.rows
               for v in row)


def test_the_tiles_are_dos_s_blocks_through_the_entry_table_but_for_three_values():
    """110 of 156 tiles equal DOS's block of the same id pixel for pixel;
    the other 46 differ only where DOS holds 4 in a body (the tile holds
    entry 27, DOS value 13's), 13 in a head (entry 25, value 4's) or 15 in
    a head (entry 0)."""
    from goldbox import dos_pod_icons
    from tools.icons import dosicons
    tool, _opened, art = _measured()
    try:
        dos = dos_pod_icons.read_game(
            dosicons.game_folder("pools-of-darkness", None))
    except (OSError, ValueError, KeyError, SystemExit):
        pytest.skip("no DOS Pools of Darkness folder; set $FR_ARCHIVES")
    found = tool.dos_differences(art, dos)
    assert found["equal"] == 110
    assert len(found["tiles"]) == 46
    assert dict(found["pairs"]) == {("body", 4, art.entry[13]): 149,
                                    ("head", 13, art.entry[4]): 23,
                                    ("head", 15, art.entry[0]): 8}


def test_the_boxes_are_opaque_24_pixel_squares_and_the_palette_has_32():
    _tool_, _opened, art = _measured()
    for frame in art.frames:
        assert (frame.width, frame.height) == (24, 24)
        assert all(all(row) for row in frame.opaque)
    assert art.frames[0].rows != art.frames[1].rows
    assert len(art.palette) == 32
    assert art.parts == bytes([1, 2, 3, 4, 6, 7])


def test_every_character_here_composes_over_the_boxes():
    tool, opened, art = _measured()
    records = tool.records(opened)
    if not records:
        pytest.skip("no Amiga Pools of Darkness characters on these disks")
    palette = set(art.palette)
    for record in records:
        for pose in art.drawn(*record.fields):
            assert {rgb for row in pose for rgb in row} <= palette


#: The members of the pinned disk 3's slot B, which the capture run loads,
#: and where the runner saves each crop:
#: `scratch.cache_dir("acceptance", "WISH-378", "apod-shots",
#: "pools-of-darkness-<name>-icon-crop.png")`.
CAPTURES = ("saint eric", "WALLY LEWIS", "jimmi hendrixs", "DONALD DUCK",
            "goofey", "rev emery")


@pytest.mark.parametrize("name", CAPTURES)
def test_the_composed_figure_is_the_game_s_own_pixel_for_pixel(name):
    from tools.registry import scratch
    tool, opened, art = _measured()
    slug = "-".join(name.lower().split())
    crop = scratch.cache_dir("acceptance", "WISH-378", "apod-shots",
                             f"pools-of-darkness-{slug}-icon-crop.png")
    if not crop.exists():
        pytest.skip(f"no ICON-screen capture of {name} here")
    record = tool.find_record(name, tool.records(opened))
    if record is None:
        pytest.skip(f"no Amiga record called {name} here")
    found = tool.compare_capture(record, crop, art)
    ready, action = found["ready"][0], found["action"][0]
    assert len(ready) == len(action) == 1
    assert tool.placed_apart(ready, action)


def test_the_places_are_one_row_72_pixels_apart():
    from tools.icons import amigapodicons as tool
    assert pod.PLACES == ((32, 56), (104, 56))
    assert tool.placed_apart([(61, 72)], [(5, 5), (133, 72)])
    assert not tool.placed_apart([(61, 72)], [(133, 73), (61, 72)])
    assert not tool.placed_apart([], [(133, 72)])


@pytest.mark.parametrize("contents", [None, b"not a disk image",
                                      bytes(901120)],
                         ids=["missing", "short", "blank"])
def test_a_capture_against_an_unreadable_disk_3_says_so_and_fails(
        tmp_path, contents):
    """`--disk3` naming a file that is not there or not a readable disk is
    one line and exit 1, not a traceback."""
    from tools.icons import amigapodicons as tool
    disk3 = tmp_path / "disk3.adf"
    if contents is not None:
        disk3.write_bytes(contents)
    printed = []
    assert tool.report_capture(printed.append, "goofey",
                               tmp_path / "crop.png", disk3, "B") == 1
    assert len(printed) == 1 and printed[0].startswith(f"{disk3}: ")
