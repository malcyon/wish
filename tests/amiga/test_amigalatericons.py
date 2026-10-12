"""The Amiga Curse and Silver Blades combat figure, as the ICON screen draws it.

`goldbox/amiga_later_icons.py` holds the rules; the write-up is
`docs/199-amiga-combat-icons.md`, "The ICON screen".  The first group builds
its tiles, libraries, streams and executables here from the documented
layout and holds none of the games' bytes or colours.  The second reads the
player's own disks through `gamedisks.yaml` and skips when they are absent;
what it asserts are counts, ids and where a figure matches a capture of the
game's own ICON screen, which `scratch.cache_dir` holds and nothing commits.
"""

from __future__ import annotations

import functools
import struct

import pytest

from automap import gamedisks
from goldbox import amiga_hunks
from goldbox import amiga_later_icons as later
from tests.support.hunks import hunk_file

# ---------------------------------------------------------------------------
# Generated tiles
# ---------------------------------------------------------------------------


def _tile(rows, opaque=None, kind=1, pad=None):
    """A tile in the documented layout, written without the decoder.

    The header is rows, two zero offsets, the width in eights and the type;
    a type-1 tile's first plane is set where the pixel is see-through, and
    plane `1 + p` (`p` for type 0) holds bit `p` of the palette entry.
    """
    height, width = len(rows), len(rows[0])
    eights = width // 8
    plane = height * eights
    planes = bytearray((4 + kind) * plane)
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            mask = 0x80 >> (x % 8)
            at = y * eights + x // 8
            if kind and not (opaque is None or opaque[y][x]):
                planes[at] |= mask
            for p in range(4):
                if value >> p & 1:
                    planes[(kind + p) * plane + at] |= mask
    raw = struct.pack(">HHHBB", height, 0, 0, eights, kind) + bytes(planes)
    if pad is None:
        pad = len(raw) % 2
    return raw + (b"\0" if pad else b"")


#: Sixteen distinct entries then eight, reversed, and a row whose entries are
#: not their own bit-reversals: reading the planes in the wrong order maps 1
#: to 8, and reading a byte's bits the wrong way round mirrors each eight.
PATTERN = (tuple(range(16)) + tuple(range(8)),
           tuple(reversed(range(16))) + tuple(range(8, 16)),
           (1, 2, 4, 8, 3, 6, 12, 9) * 3)
HOLES = (tuple(x % 3 != 0 for x in range(24)),
         tuple(x < 12 for x in range(24)),
         (True,) * 24)


def test_a_generated_tile_decodes_to_its_entries_and_its_mask():
    tile = later.decode_tile(_tile(PATTERN, HOLES))
    assert (tile.height, tile.width) == (3, 24)
    assert tile.rows == PATTERN
    assert tile.opaque == HOLES


def test_a_tile_without_a_mask_plane_is_opaque_everywhere():
    tile = later.decode_tile(_tile(PATTERN, kind=0))
    assert tile.rows == PATTERN
    assert all(all(row) for row in tile.opaque)


def test_an_odd_tile_may_carry_one_pad_byte_and_no_more():
    rows = ((5,) * 8,)
    assert len(_tile(rows, pad=False)) % 2 == 1
    assert later.decode_tile(_tile(rows)).rows == rows
    with pytest.raises(later.LaterArtError):
        later.decode_tile(_tile(rows, pad=False))
    with pytest.raises(later.LaterArtError):
        later.decode_tile(_tile(rows, pad=True) + b"\0\0")


@pytest.mark.parametrize("raw", [b"", b"\0\3\0\0\0\0\3\2" + bytes(45),
                                 b"\0\0\0\0\0\0\3\1"])
def test_a_header_that_is_not_a_figure_tile_is_rejected(raw):
    with pytest.raises(later.LaterArtError):
        later.decode_tile(raw)


# ---------------------------------------------------------------------------
# Generated libraries and packed streams
# ---------------------------------------------------------------------------


def _glib(blocks, indexed, ids=None, method=0, body=None):
    """A `GLIB` tile library: header, `count + 1` offsets, the blocks.

    `body`, when given, replaces everything after the 16-byte header (a
    packed library's stream), and the header's size is still the unpacked
    size.
    """
    if indexed:
        index = struct.pack(">H", len(blocks)) + b"".join(
            struct.pack(">HH", art, n + 1) for n, art in enumerate(ids))
        blocks = [index, *blocks]
    table = 16 + 4 * (len(blocks) + 1)
    offsets = [table]
    for block in blocks:
        offsets.append(offsets[-1] + len(block))
    unpacked = (struct.pack(f">{len(offsets)}I", *offsets)
                + b"".join(blocks))
    header = (b"GLIB" + struct.pack(">IHBB", 16 + len(unpacked), len(blocks),
                                    method, 1 if indexed else 0) + b"TILE")
    return header + (unpacked if body is None else body), unpacked


def test_an_indexed_library_is_read_by_art_id():
    data, _ = _glib([b"one", b"two!"], indexed=True, ids=[153, 25])
    assert later.library(data) == {153: b"one", 25: b"two!"}


def test_an_unindexed_library_is_read_by_block_number():
    data, _ = _glib([b"zero", b"one"], indexed=False)
    assert later.library(data) == {0: b"zero", 1: b"one"}


def test_an_index_naming_a_block_the_library_lacks_is_rejected():
    data, _ = _glib([b"one"], indexed=True, ids=[7])
    damaged = bytearray(data)
    index_at = struct.unpack_from(">I", data, 16)[0]
    damaged[index_at + 4:index_at + 6] = b"\0\x09"
    with pytest.raises(later.LaterArtError):
        later.library(bytes(damaged))


#: Pseudo-random bytes, so a copy from the wrong place gives other bytes.
SOURCE = bytes((i * 37 + i // 7 + 11) % 256 for i in range(640))


def _stream():
    """A method-5 stream and the bytes it must unpack to, built by hand.

    Ten 64-byte literal runs (`110 0 1111`), then a short copy of 5 bytes
    from offset 130 after 2 literals, a long copy of 6 bytes from offset 600
    after 1 literal, a 3-byte literal run (`110 1 0011`), the end, then a
    second chunk of one 4-byte run.  The offsets use the control byte's
    bits and the following bytes' upper bits, so a wrong field moves the
    copy.
    """
    stream, want = bytearray(), bytearray()
    for run in range(10):
        stream += b"\xCF" + SOURCE[64 * run:64 * (run + 1)]
    want += SOURCE
    # Short: offset 130 = 0b1_0000010, length 5, literals "xy".
    stream += bytes([130 & 0x7F, (130 >> 7) << 5 | 2 << 3 | (5 - 3)]) + b"xy"
    want += b"xy"
    start = len(want) - 130 - 1
    want += want[start:start + 5]
    # Long: offset 600 = 0b1_001_011000, length 6, literal "z".
    stream += bytes([0x80 | 600 & 0x3F, (600 >> 6 & 7) << 5 | (6 - 3),
                     (600 >> 9) << 2 | 1]) + b"z"
    want += b"z"
    start = len(want) - 600 - 1
    want += want[start:start + 6]
    stream += b"\xD3abc" + b"\xE0"
    want += b"abc"
    stream += b"\xC0" + b"wxyz" + b"\xFF"
    want += b"wxyz"
    return bytes(stream), bytes(want)


def test_a_method_5_stream_unpacks_to_the_bytes_it_was_built_from():
    stream, want = _stream()
    assert later.unpack_method_5(stream) == want


def test_a_copy_reaching_before_the_output_is_an_error():
    with pytest.raises(later.LaterArtError):
        later.unpack_method_5(b"\xD0" + b"\x05\x02" + b"\xE0")


def test_a_cut_short_stream_is_an_error():
    stream, _want = _stream()
    for cut in (640, len(stream) - 1):
        with pytest.raises(later.LaterArtError):
            later.unpack_method_5(stream[:cut])


def test_a_packed_library_unpacks_to_its_header_s_size():
    blocks = [bytes(range(40)), bytes(range(40, 70))]
    _data, unpacked = _glib(blocks, indexed=False)
    stream = bytearray(b"\0\x01")
    for at in range(0, len(unpacked), 15):
        piece = unpacked[at:at + 15]
        stream += bytes([0xD0 | len(piece)]) + piece
    stream += b"\xE0"
    data, _ = _glib(blocks, indexed=False, method=5, body=bytes(stream))
    assert later.library(data) == {0: blocks[0], 1: blocks[1]}
    short = data[:-2] + b"\xE0"
    with pytest.raises(later.LaterArtError):
        later.library(short)


# ---------------------------------------------------------------------------
# Recolour and composite
# ---------------------------------------------------------------------------

#: A generated DOS-value-to-entry table: a permutation with no fixed point
#: but 0, so a recolour applied to DOS values rather than entries draws
#: other entries.
ENTRY = bytes([0, 5, 9, 14, 3, 11, 1, 12, 7, 15, 2, 6, 13, 4, 10, 8])
PARTS = bytes([1, 2, 3, 4, 6, 7])
#: The record's colours that change nothing: each part keeps its own value.
UNCHANGED = bytes([0x91, 0xA2, 0xB3, 0xC4, 0xE6, 0xF7])


def test_the_unchanged_colours_build_the_identity():
    assert later.recolour_table(UNCHANGED, ENTRY, PARTS) == tuple(range(16))


def test_a_nibble_recolours_the_part_s_entry_and_the_high_its_highlight():
    colours = bytes([0x5D, 0xA2, 0xB3, 0xC4, 0xE6, 0xF7])
    table = later.recolour_table(colours, ENTRY, PARTS)
    assert table[ENTRY[1]] == ENTRY[0xD]
    assert table[ENTRY[9]] == ENTRY[5]
    assert sum(1 for i in range(16) if table[i] != i) == 2


def _square(value, size=24, rows=24, holes=()):
    return tuple(tuple(None if (x, y) in holes else value
                       for x in range(size)) for y in range(rows))


def _as_tile(pose):
    rows = tuple(tuple(0 if v is None else v for v in row) for row in pose)
    opaque = tuple(tuple(v is not None for v in row) for row in pose)
    return later.Tile(len(rows), len(rows[0]), rows, opaque)


def _art(head_ready=3, head_action=5, body_ready=6, body_action=9):
    """Heads and bodies with one entry each, a head of 10 rows, and holes
    so both see-through cases occur."""
    head_holes = {(x, y) for x in range(24) for y in range(10) if x >= 12}
    body_holes = {(x, y) for x in range(24) for y in range(24) if x < 4}
    heads = {
        2: _as_tile(_square(head_ready, rows=10, holes=head_holes)),
        2 + later.ACTION: _as_tile(_square(head_action, rows=10,
                                           holes=head_holes)),
        2 + later.LARGE: _as_tile(_square(head_ready, rows=8,
                                          holes=head_holes)),
        2 + later.LARGE + later.ACTION: _as_tile(_square(head_action, rows=8,
                                                         holes=head_holes))}
    bodies = {}
    for base in (7, 7 + later.LARGE):
        bodies[base] = _as_tile(_square(body_ready, holes=body_holes))
        bodies[base + later.ACTION] = _as_tile(_square(body_action,
                                                       holes=body_holes))
    return heads, bodies


def test_the_head_covers_the_body_where_it_is_opaque_rather_than_or_ing():
    heads, bodies = _art(head_ready=3, body_ready=6)
    ready, _action = later.compose(heads, bodies, 2, 7, 1, UNCHANGED,
                                   ENTRY, PARTS)
    assert ready[0][5] == 3          # head over body: not 3 | 6 == 7
    assert ready[0][15] == 6         # the head is see-through here
    assert ready[12][5] == 6         # below the head
    assert ready[12][1] is None      # neither is drawn here
    assert ready[0][1] == 3          # the head alone


def test_each_pose_takes_its_own_head_and_body_and_size_2_the_large_ones():
    heads, bodies = _art()
    ready, action = later.compose(heads, bodies, 2, 7, 1, UNCHANGED,
                                  ENTRY, PARTS)
    assert (ready[0][5], action[0][5]) == (3, 5)
    assert (ready[20][5], action[20][5]) == (6, 9)
    assert (ready[9][5], action[9][5]) == (3, 5)
    big_ready, _ = later.compose(heads, bodies, 2, 7, 2, UNCHANGED,
                                 ENTRY, PARTS)
    assert big_ready[9][5] == 6      # the large head is two rows shorter


def test_the_record_s_colours_recolour_the_head_and_both_poses():
    heads, bodies = _art(head_ready=ENTRY[4], head_action=ENTRY[4],
                         body_ready=ENTRY[9], body_action=ENTRY[9])
    colours = bytes([0x21, 0xA2, 0xB3, 0xCB, 0xE6, 0xF7])
    ready, action = later.compose(heads, bodies, 2, 7, 1, colours,
                                  ENTRY, PARTS)
    for pose in (ready, action):
        assert pose[0][5] == ENTRY[0xB]
        assert pose[20][5] == ENTRY[2]


def test_a_missing_tile_is_an_error_not_a_blank_pose():
    heads, bodies = _art()
    with pytest.raises(later.LaterArtError):
        later.compose(heads, bodies, 3, 7, 1, UNCHANGED, ENTRY, PARTS)
    with pytest.raises(later.LaterArtError):
        later.compose(heads, bodies, 2, 8, 1, UNCHANGED, ENTRY, PARTS)


def test_the_box_shows_only_where_the_figure_is_see_through():
    box = _as_tile(_square(13))
    pose = _square(2, holes={(0, 0), (5, 7)})
    framed = later.on_frame(box, pose)
    assert framed[0][0] == framed[7][5] == 13
    assert framed[0][1] == 2
    hollow = _as_tile(_square(13, holes={(0, 0)}))
    with pytest.raises(later.LaterArtError):
        later.on_frame(hollow, pose)


# ---------------------------------------------------------------------------
# Colours, executables and disks
# ---------------------------------------------------------------------------


def test_a_palette_block_rounds_each_byte_to_a_nibble_as_the_setter_does():
    rgb = bytes([0, 8, 9, 25, 26, 255] + [17 * (i % 16) for i in range(42)])
    raw = struct.pack(">HHHBB", 0, 0, 0, 0, later.PALETTE_TYPE) + rgb
    palette = later.palette_block(raw)
    assert palette[0] == (0, 0, 17)
    assert palette[1] == (17, 34, 255)
    assert len(palette) == 16
    with pytest.raises(later.LaterArtError):
        later.palette_block(raw[:7] + b"\x01" + raw[8:])


def test_the_icon_palette_is_the_title_s_own_block():
    blocks = []
    for n in range(88):
        channel = n % 16
        blocks.append(struct.pack(">HHHBB", 0, 0, 0, 0, later.PALETTE_TYPE)
                      + bytes([17 * channel]) * 48)
    data, _ = _glib(blocks, indexed=False)
    assert later.icon_palette(data, "curse-of-the-azure-bonds")[0] == (
        17 * (87 % 16),) * 3
    assert later.icon_palette(data, "secret-of-the-silver-blades")[0] == (
        0, 0, 0)
    with pytest.raises(later.LaterArtError):
        later.icon_palette(data, "pool-of-radiance")


def _executable(targets=((0x20, 0x40),), entry=ENTRY):
    """A code and a data hunk; the code holds one copy of the recolour
    builder's instructions per `(entry, parts)` data offset pair, its `lea`
    displacements naming them."""
    data = bytearray(0x80)
    data[0x20:0x30] = entry
    data[0x40:0x46] = PARTS
    data[0x50:0x60] = entry

    def displacement(at):
        return struct.pack(">h", at - 0x7FFE)

    code = bytearray(b"\x4e\x71" * 8)
    for entry_at, parts_at in targets:
        code += (bytes.fromhex("0241000f41ec") + displacement(entry_at)
                 + bytes.fromhex("7000100243ec") + displacement(parts_at)
                 + b"\x4e\x71" * 2)
    code += b"\x4e\x75\x4e\x75"
    return hunk_file([(amiga_hunks.HUNK_CODE, bytes(code), []),
                      (amiga_hunks.HUNK_DATA, bytes(data), [])])


def test_the_recolour_tables_are_read_through_the_builder_s_own_leas():
    assert later.recolour_tables(_executable()) == (ENTRY, PARTS)
    # Two copies naming the same tables are one builder.
    assert later.recolour_tables(_executable(((0x20, 0x40),) * 2)) == (
        ENTRY, PARTS)


@pytest.mark.parametrize("program", [
    pytest.param(lambda: _executable(()), id="no builder"),
    pytest.param(lambda: _executable(((0x20, 0x40), (0x50, 0x40))),
                 id="two builders naming different tables"),
    pytest.param(lambda: _executable(entry=bytes(16)), id="not a permutation"),
    pytest.param(lambda: _executable(((0x7F0, 0x40),)),
                 id="a table outside the data hunk"),
    pytest.param(lambda: b"not a hunk file at all", id="not a hunk file"),
])
def test_an_executable_without_one_recolour_builder_has_no_tables(program):
    with pytest.raises(later.LaterArtError):
        later.recolour_tables(program())


class _Disk:
    """Enough of `AmigaDisk` for :func:`later.disk_files`."""

    def __init__(self, files):
        self.files = files

    def walk(self):
        return [(f"/{name}", None) for name in self.files]

    def read_file(self, path):
        return self.files[path.strip("/")]


def test_disk_1_is_the_one_with_the_executable_beside_its_drawer():
    darkness = _Disk({"Pools of Darkness": b"pod", "DISK1/ALWAYS.TLB": b"x",
                      "DISK1/COMSPR.TLB": b"x"})
    first = _Disk({"Secret": b"exe", "DISK1/ALWAYS.TLB": b"always",
                   "DISK1/COMSPR.TLB": b"comspr"})
    second = _Disk({"DISK2/CHEAD.TLB": b"head", "DISK2/CBODY.TLB": b"body"})
    found = later.disk_files("secret-of-the-silver-blades",
                             [darkness, second, first])
    assert found == {later.EXECUTABLE: b"exe", later.PALETTE_FILE: b"always",
                     later.FRAME_FILE: b"comspr", later.HEAD_FILE: b"head",
                     later.BODY_FILE: b"body"}
    with pytest.raises(later.LaterArtError):
        later.disk_files("secret-of-the-silver-blades", [darkness, second])
    with pytest.raises(later.LaterArtError):
        later.disk_files("curse-of-the-azure-bonds", [first, second])


# ---------------------------------------------------------------------------
# The player's disks
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _tool():
    from tools.icons import amigalatericons
    opened = amigalatericons.disks()
    arts = {title: amigalatericons.title_art(title, opened)
            for title in later.TITLES}
    return amigalatericons, opened, arts


def _measured(title):
    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    tool, opened, arts = _tool()
    if arts[title] is None:
        pytest.skip(f"not all of {title}'s Amiga disks are here")
    return tool, opened, arts[title]


@functools.lru_cache(maxsize=1)
def _records():
    return tuple(_tool()[0].records())


#: How many `(head, body, size, pose)` figures have pixels where head and
#: body are both opaque, and how many such pixels: there the Amiga draws the
#: head and DOS ORs the two values.  All are size 1.
OVERLAPS = {"curse-of-the-azure-bonds": (34, 40),
            "secret-of-the-silver-blades": (30, 36)}


@pytest.mark.parametrize("title", sorted(later.TITLES))
def test_some_small_figures_have_head_pixels_over_body_pixels(title):
    _tool_, _opened, art = _measured(title)
    figures = pixels = 0
    for size in (1, 2):
        for head in range(14):
            for body in range(32):
                for h_id, b_id in zip(later.block_ids(head, size),
                                      later.block_ids(body, size)):
                    h, b = art.heads[h_id], art.bodies[b_id]
                    n = sum(1 for y in range(h.height) for x in range(24)
                            if h.opaque[y][x] and b.opaque[y][x])
                    figures += bool(n)
                    pixels += n
    assert (figures, pixels) == OVERLAPS[title]


@pytest.mark.parametrize("title", sorted(later.TITLES))
def test_every_specimen_is_the_dos_figure_through_the_entry_table(title):
    """Apart from the plume highlight, DOS value 13, which the tiles hold
    as entry 0; ARIEL and STORMBRINGER are the two whose heads have it."""
    from goldbox import dos_icons
    from tools.icons.amigaicons import dos_directory
    _tool_, _opened, art = _measured(title)
    folder = dos_directory({"curse-of-the-azure-bonds": "CURSE",
                            "secret-of-the-silver-blades": "SECRET"}[title])
    if folder is None:
        pytest.skip("no DOS game folder; set $FR_ARCHIVES")
    heads = dos_icons.read_art((folder / "CHEAD.DAX").read_bytes())
    bodies = dos_icons.read_art((folder / "CBODY.DAX").read_bytes())
    plume, checked = {}, 0
    for char in _records():
        if char.deltas.dos.key != title:
            continue
        fields = (char.get("icon_head"), char.get("icon_body"),
                  char.get("size"), bytes(char.get("icon_colours")))
        amiga = art.poses(*fields)
        # Curse's rule: Silver Blades' DOS outline-to-black is DOS's own.
        expected = dos_icons.compose(heads, bodies, *fields,
                                     title="curse-of-the-azure-bonds")
        for a_pose, d_pose in zip(amiga, expected):
            for a_row, d_row in zip(a_pose, d_pose):
                for a, d in zip(a_row, d_row):
                    checked += 1
                    if a == (None if d is None else art.entry[d]):
                        continue
                    assert (d, a) == (13, 0)
                    plume[char.name] = plume.get(char.name, 0) + 1
    assert checked
    assert plume == ({"ARIEL": 10, "STORMBRINGER": 16}
                     if title == "curse-of-the-azure-bonds" else {})


def test_curse_s_icon_palette_is_block_0_with_black_and_grey_exchanged():
    _tool_, opened, art = _measured("curse-of-the-azure-bonds")
    files = later.disk_files("curse-of-the-azure-bonds", opened)
    default = later.palette_block(later.library(files[later.PALETTE_FILE])[0])
    assert (art.palette[0], art.palette[8]) == (default[8], default[0])
    assert art.palette[0] != art.palette[8]
    # The ICON routine's palette call names block 87 (0x57).
    assert files[later.EXECUTABLE][0x354AC:0x354B0] == bytes.fromhex(
        "3f3c0057")


def test_silver_blades_packed_library_holds_one_palette_block_0():
    _tool_, opened, _art = _measured("secret-of-the-silver-blades")
    files = later.disk_files("secret-of-the-silver-blades", opened)
    data = files[later.PALETTE_FILE]
    assert data[10] == 5
    palettes = [n for n, raw in later.library(data).items()
                if len(raw) > 7 and raw[7] & 0x0F == later.PALETTE_TYPE]
    assert palettes == [0]


@pytest.mark.parametrize("title", sorted(later.TITLES))
def test_the_boxes_are_opaque_24_pixel_squares(title):
    _tool_, _opened, art = _measured(title)
    for frame in art.frames:
        assert (frame.width, frame.height) == (24, 24)
        assert all(all(row) for row in frame.opaque)


#: The characters each title's capture run shoots, by title.  The runner
#: saves each crop as `<title>-<name>-icon-crop.png` in
#: `scratch.cache_dir("acceptance", "WISH-378", "later-shots")`.
CAPTURES = {"curse-of-the-azure-bonds": ("GALAIN", "HOLLAND", "IILANDA",
                                         "SUNDRA"),
            "secret-of-the-silver-blades": ("GUY DE VALOIS", "PAINE",
                                            "EPONA", "MALACHITE")}


@pytest.mark.parametrize("title,name", [(t, n) for t, names in
                                        sorted(CAPTURES.items())
                                        for n in names])
def test_the_composed_figure_is_the_game_s_own_pixel_for_pixel(title, name):
    from tools.registry import scratch
    tool, _opened, _art = _measured(title)
    slug = "-".join(name.lower().split())
    crop = scratch.cache_dir("acceptance", "WISH-378", "later-shots",
                             f"{title}-{slug}-icon-crop.png")
    if not crop.exists():
        pytest.skip(f"no ICON-screen capture of {name} here")
    found = tool.compare_capture(name, crop)
    if found is None:
        pytest.skip(f"no Amiga record called {name} here")
    rows = {"curse-of-the-azure-bonds": 2,
            "secret-of-the-silver-blades": 1}[title]
    ready, action = found["ready"][0], found["action"][0]
    assert len(ready) == len(action) == rows
    for (rx, ry), (ax, ay) in zip(ready, action):
        assert (ax - rx, ay - ry) == (72, 0)
