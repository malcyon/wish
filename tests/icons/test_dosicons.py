"""`goldbox/dos_icons.py` and `goldbox/dos_pod_icons.py` compose a DOS combat
figure the way the loader does.

The synthetic tests build their own blocks, so they run anywhere.  The rest
read the player's DOS games and skip without them: every block decodes, Silver
Blades' re-drawn head comes from its own file, Donald's own Pool of Radiance
party composes, `tools/icons/dosicons.py` re-reads every rule the module
holds out of each title's `GAME.OVR` and `START.EXE`, and Pools of Darkness'
blocks hold part values and the archives' party composes over the box.  The
captured ICON screens of all four titles are compared pixel for pixel where
they are on this machine.
"""

from __future__ import annotations

import pathlib
import struct

import pytest

from goldbox import dos_icons as di
from goldbox import dos_pod_icons as dp

POOL, CURSE, SSB = ("pool-of-radiance", "curse-of-the-azure-bonds",
                    "secret-of-the-silver-blades")
#: A record whose six colour bytes leave every part value as it is stored.
SAME = bytes.fromhex("91a2b3c4e6f7")


# -- generated art -----------------------------------------------------------------
def image(rows: list[list[int]]) -> bytes:
    """An image block: the 17-byte header, then two pixels a byte."""
    height, width = len(rows), len(rows[0])
    out = bytearray([height, 0, width // 8] + [0] * 14)
    for row in rows:
        for x in range(0, width, 2):
            out.append(row[x] << 4 | row[x + 1])
    return bytes(out)


def blank(height: int = 24, value: int = 0) -> list[list[int]]:
    return [[value] * 24 for _ in range(height)]


def block(rows) -> di.ArtBlock:
    return di.decode_block(image(rows))


def dax(blocks: dict[int, bytes]) -> bytes:
    """A `.DAX` container holding `blocks`, each stored as literal runs."""
    index, data = bytearray(), bytearray()
    for bid, raw in blocks.items():
        packed = bytearray()
        for at in range(0, len(raw), 128):
            run = raw[at:at + 128]
            packed += bytes([len(run) - 1]) + run
        index += struct.pack("<BIHH", bid, len(data), len(raw), len(packed))
        data += packed
    return struct.pack("<H", len(index)) + bytes(index) + bytes(data)


def art_with(head_rows, body_rows, head_action=None, option=0, size=2):
    """Heads and bodies holding one option at `size`, both poses."""
    ready, action = di.block_ids(option, size)
    heads = {ready: block(head_rows),
             action: block(head_action if head_action else head_rows)}
    bodies = {ready: block(body_rows), action: block(body_rows)}
    return heads, bodies


# -- the block -----------------------------------------------------------------------
def test_a_block_reads_its_high_nibble_first():
    rows = di.decode_block(bytes([1, 0, 3] + [0] * 14) + bytes([0x12] * 12))
    assert rows.rows[0][:4] == (1, 2, 1, 2)
    assert (rows.height, rows.width) == (1, 24)


def test_a_block_renders_as_many_pixels_as_its_header_declares():
    """Rows from byte 0, two pixels a byte from `block[2] * 4` of them."""
    raw = bytes([2, 0, 3, 0] + [0] * 13) + bytes([0x12] * 24)
    pixels = di.block_pixels(raw)
    assert len(pixels) == 2
    assert pixels[0] == [1, 2] * 12


def test_a_block_whose_length_the_header_does_not_describe_is_named():
    with pytest.raises(di.DosArtError, match="make 41 bytes, not 40"):
        di.decode_block(bytes([2, 0, 3] + [0] * 14) + bytes(23))


def test_a_short_block_is_named_rather_than_read_into_truncated_rows():
    raw = bytes([2, 0, 3, 0] + [0] * 13) + bytes([0x12] * 23)
    with pytest.raises(di.DosArtError, match="shorter than"):
        di.block_pixels(raw)


# -- the composite ---------------------------------------------------------------------
def test_the_head_is_ored_into_the_body_not_drawn_over_it():
    """Body 1 under head 8 is 9, which neither overwriting order gives."""
    body, head = blank(), blank(10)
    body[0][0], head[0][0] = 1, 8
    heads, bodies = art_with(head, body)
    ready, _ = di.compose(heads, bodies, 0, 0, 2, SAME)
    assert ready[0][0] == 9


def test_the_head_lands_from_row_0():
    body, head = blank(), blank(8)
    head[0][3] = 4
    heads, bodies = art_with(head, body, size=1)
    ready, _ = di.compose(heads, bodies, 0, 0, 1, SAME)
    assert ready[0][3] == 4
    assert all(row[3] is None for row in ready[1:])


def test_a_pixel_only_the_head_holds_is_drawn():
    body, head = blank(), blank(10)
    head[5][7] = 12
    heads, bodies = art_with(head, body)
    ready, action = di.compose(heads, bodies, 0, 0, 2, SAME)
    assert ready[5][7] == action[5][7] == 12


def test_each_pose_takes_its_own_head_block():
    """The loader reads `id + 128` for the second pose of a head too."""
    body, head, head2 = blank(), blank(10), blank(10)
    head[0][0], head2[0][1] = 4, 4
    heads, bodies = art_with(head, body, head_action=head2)
    ready, action = di.compose(heads, bodies, 0, 0, 2, SAME)
    assert (ready[0][0], ready[0][1]) == (4, None)
    assert (action[0][0], action[0][1]) == (None, 4)


def test_size_two_reads_the_blocks_64_on():
    assert di.block_ids(5, 2) == (69, 197)
    assert di.block_ids(5, 1) == (5, 133)


def test_a_pixel_is_empty_only_where_head_and_body_both_store_0():
    body = blank()
    body[2][2] = 1
    heads, bodies = art_with(blank(10), body)
    ready, _ = di.compose(heads, bodies, 0, 0, 2, SAME)
    assert ready[2][2] == 1
    assert ready[2][3] is None


def test_a_colour_nibble_of_0_draws_colour_0_rather_than_the_background():
    body = blank()
    body[2][2], body[2][3] = 1, 9
    heads, bodies = art_with(blank(10), body)
    ready, _ = di.compose(heads, bodies, 0, 0, 2,
                          bytes.fromhex("07a2b3c4e6f7"))
    assert (ready[2][2], ready[2][3]) == (7, 0)


def test_the_recolour_table_pairs_each_byte_with_its_part():
    table = di.recolour_table(bytes.fromhex("070708c448f7"))
    assert table == (0, 7, 7, 8, 4, 5, 8, 7, 8, 0, 0, 0, 12, 13, 4, 15)


def test_silver_blades_turns_the_outline_to_0_and_the_other_two_do_not():
    body = blank()
    body[1][1] = 8
    heads, bodies = art_with(blank(10), body)
    for title, want in ((POOL, 8), (CURSE, 8), (SSB, 0)):
        ready, _ = di.compose(heads, bodies, 0, 0, 2, SAME, title)
        assert ready[1][1] == want, title


def test_the_list_helpers_or_pad_and_recolour():
    out = di.composite([[1, 0]], [[8, 4]], size=3)
    assert out == [[9, 4, 0], [0, 0, 0], [0, 0, 0]]
    assert di.recolour([[1, 9]], bytes.fromhex("27a2b3c4e6f7")) == [[7, 2]]


# -- the ICON screen --------------------------------------------------------------------
def test_pool_and_curse_show_colour_0_grey_and_8_black():
    for title in (POOL, CURSE):
        palette = di.icon_palette(title)
        assert palette[0] == (0x55, 0x55, 0x55)
        assert palette[8] == (0, 0, 0)
    assert di.icon_palette(SSB) == di.EGA


def test_each_title_draws_its_own_box_behind_the_action_pose():
    frames = (block(blank(24, 7)), block(blank(24, 15)))
    game = di.GameArt({}, {}, frames)
    assert di.frame_for(game, 0, POOL) is frames[0]
    assert di.frame_for(game, 1, POOL) is frames[1]
    assert di.frame_for(game, 1, CURSE) is frames[1]
    assert di.frame_for(game, 1, SSB) is frames[0]


def test_the_box_shows_where_the_figure_is_empty():
    pose = tuple(tuple(None if x else 3 for x in range(24))
                 for _ in range(24))
    drawn = di.on_frame(block(blank(24, 7)), pose)
    assert drawn[0][:2] == (3, 7)


def test_a_title_nobody_read_is_named():
    with pytest.raises(di.DosArtError, match="pools-of-darkness"):
        di.icon_palette("pools-of-darkness")


def test_a_game_folder_is_read_whatever_the_case_of_its_names(tmp_path):
    head, body, box = image(blank(10)), image(blank()), image(blank(24, 7))
    (tmp_path / "chead.dax").write_bytes(dax({64: head, 192: head}))
    (tmp_path / "CBODY.DAX").write_bytes(dax({64: body, 192: body}))
    (tmp_path / "Comspr.Dax").write_bytes(dax({25: box, 153: box}))
    game = di.read_game(tmp_path)
    assert sorted(game.heads) == [64, 192]
    assert game.frame[1].rows[0][0] == 7


def test_a_game_folder_without_the_box_is_named(tmp_path):
    raw = image(blank())
    for name in ("CHEAD.DAX", "CBODY.DAX"):
        (tmp_path / name).write_bytes(dax({0: raw}))
    (tmp_path / "COMSPR.DAX").write_bytes(dax({25: raw}))
    with pytest.raises(di.DosArtError, match="no block 153"):
        di.read_game(tmp_path)


# -- the player's own games -------------------------------------------------------------
def _archives() -> dict:
    """Each title's archive game folder, or skip."""
    dosicontitles = pytest.importorskip("tools.icons.dosicontitles")
    gamedisks = pytest.importorskip("automap.gamedisks")
    root = gamedisks.find("dos-archives")
    if root is None:
        pytest.skip("needs the DOS games; set $FR_ARCHIVES")
    try:
        return dosicontitles.find_folders(root, [POOL, CURSE, SSB])
    except SystemExit as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def folders():
    return _archives()


@pytest.mark.parametrize("title", [POOL, CURSE, SSB])
def test_every_figure_block_of_each_title_decodes(folders, title):
    game = di.read_game(folders[title])
    assert (len(game.heads), len(game.bodies)) == (56, 128)
    assert all(b.width == 24 for b in game.bodies.values())


def test_silver_blades_large_head_10_comes_from_its_own_file(folders):
    """Silver Blades adds a plume (values 5 and 13) to large head 10."""
    plume = {5, 13}
    drawn = {}
    for title in (POOL, SSB):
        game = di.read_game(folders[title])
        ready, action = di.compose(game.heads, game.bodies, 10, 0, 2, SAME,
                                   title)
        drawn[title] = {v for pose in (ready, action) for row in pose
                        for v in row}
    assert drawn[SSB] & plume
    assert not drawn[POOL] & plume


@pytest.mark.parametrize("title", [POOL, CURSE, SSB])
def test_the_code_says_what_the_module_holds(folders, title):
    pytest.importorskip("capstone")
    dosicons = pytest.importorskip("tools.icons.dosicons")
    assert dosicons.check(title, dosicons.readings(folders[title])) == []


def test_donalds_pool_party_composes_with_brutus_s_0_nibbles_drawn():
    gamedisks = pytest.importorskip("automap.gamedisks")
    from goldbox import dos_codec
    folder = gamedisks.find("por-dos-play")
    if folder is None:
        pytest.skip("needs Donald's DOS Pool of Radiance; set $POR_DOS_GAME")
    game = di.read_game(folder)
    records = sorted((folder / "SAVE").glob("CHRDATA?.SAV"))
    if len(records) != 6:
        pytest.skip("slot A of por-dos-play is not the six-member party")
    zeros = {}
    for path in records:
        char = dos_codec.read_character(path)
        poses = di.compose(game.heads, game.bodies, char.get("icon_head"),
                           char.get("icon_body"), char.get("size"),
                           bytes(char.get("icon_colours")))
        assert all(sum(v is not None for row in pose for v in row) > 50
                   for pose in poses), char.name
        zeros[char.name.strip()] = sum(v == 0 for row in poses[0]
                                       for v in row)
    if "BRUTUS" not in zeros:
        pytest.skip("slot A of por-dos-play has no BRUTUS")
    assert zeros["BRUTUS"] > 0


#: The ICON-screen runs, by title: Donald's own Pool party in slots A and J,
#: and the archives' Curse and Silver Blades parties with some colours and
#: options staged by `tools/dos/acceptance.py`.
CAPTURE_RUNS = {"dos-icon-pool-a": POOL, "dos-icon-pool-j": POOL,
                "dos-icon-curse": CURSE, "dos-icon-ssb": SSB}


def _captures():
    """`(run, title, result)` for every captured ICON screen here."""
    import json

    from tools.registry import scratch
    out = []
    for run, title in CAPTURE_RUNS.items():
        summary = scratch.cache_dir("acceptance", "WISH-378", run,
                                    "summary.json")
        if summary.exists():
            out += [(run, title, r) for r in json.loads(
                summary.read_text())["results"] if "icon" in r]
    return out


def test_every_captured_icon_screen_is_the_composed_figure(folders):
    """Each pose, OLD and NEW, pixel for pixel at :data:`PLACES`."""
    from tools.registry import scratch
    dosicons = pytest.importorskip("tools.icons.dosicons")
    captures = _captures()
    if not captures:
        pytest.skip("no DOS ICON-screen captures here")
    wrong = []
    for run, title, result in captures:
        record = result["record"]
        game = di.read_game(folders[title])
        palette = di.icon_palette(title)
        poses = di.compose(game.heads, game.bodies, record["icon_head"],
                           record["icon_body"], record["size"],
                           bytes.fromhex(record["icon_colours"]), title)
        screen = dosicons.capture_pixels(scratch.cache_dir(
            "acceptance", "WISH-378", run, "shots", result["icon"] + ".png"))
        for n, pose in enumerate(poses):
            drawn = di.on_frame(di.frame_for(game, n, title), pose)
            for which in ("old", "new"):
                x, y = di.PLACES[(which, n)]
                differ = sum(
                    screen[y + dy, x + dx] != (r << 16 | g << 8 | b)
                    for dy, row in enumerate(drawn)
                    for dx, (r, g, b) in enumerate(palette[v] for v in row))
                if differ:
                    wrong.append((run, result["name"], which, n, differ))
    assert wrong == []


# -- Pools of Darkness ------------------------------------------------------------------
#: Pools of Darkness keeps the archives' game folder name.
POD = "pools-of-darkness"


def pod_image(rows: list[list[int]], first: int = 0x60, count: int = 48,
              colours: bytes | None = None) -> bytes:
    """A VGA block: the header the reader takes, then one byte a pixel."""
    height, width = len(rows), len(rows[0])
    head = bytes([height, width // 8, 0, 0, 0, 0, 1, 0, first, count - 1])
    pal = colours if colours is not None else bytes(3 * count)
    out = head + pal + bytes(count // 2) + bytes(4)
    return out + bytes(v for row in rows for v in row)


def pod_blank(height: int = 24, value: int = dp.KEY) -> list[list[int]]:
    return [[value] * 24 for _ in range(height)]


def pod_block(rows) -> dp.PodBlock:
    return dp.decode_block(pod_image(rows))


def pod_art(head_rows, body_rows, body_action=None, head_id=0, body_id=0,
            size=2):
    """Heads and bodies holding one head and one body at `size`."""
    (head, ready), (_, action) = dp.block_ids(head_id, body_id, size)
    heads = {head: pod_block(head_rows)}
    bodies = {ready: pod_block(body_rows),
              action: pod_block(body_action or body_rows)}
    return heads, bodies


def test_a_pod_figure_block_has_the_182_byte_header():
    """48 palette entries of three bytes, 24 nibble bytes and four skipped."""
    raw = pod_image(pod_blank(10))
    assert len(raw) == 182 + 10 * 24
    assert dp.header_length(48, 0x60) == 182
    assert dp.header_length(32, 0x40) == 126


def test_a_pod_block_reads_one_byte_a_pixel():
    rows = pod_blank(2)
    rows[0][:3] = [0x12, 0x57, 3]
    block = dp.decode_block(pod_image(rows))
    assert block.rows[0][:3] == (0x12, 0x57, 3)
    assert (block.height, block.width, block.first) == (2, 24, 0x60)


def test_a_pod_block_keeps_its_palette_and_ega_nibbles():
    colours = bytes(range(6)) + bytes(3 * 30)
    raw = bytearray(pod_image(pod_blank(1), first=0x40, count=32,
                              colours=colours))
    raw[10 + 96] = 0x9A
    block = dp.decode_block(bytes(raw))
    assert block.colours[:2] == ((0, 1, 2), (3, 4, 5))
    assert block.ega[:2] == (9, 10)


def test_a_pod_block_whose_length_the_header_does_not_describe_is_named():
    with pytest.raises(dp.DosArtError, match="not 421"):
        dp.decode_block(pod_image(pod_blank(10))[:-1])


def test_the_pod_head_is_written_over_the_body_where_it_is_not_8():
    head, body = pod_blank(10), pod_blank(24, 1)
    head[0][0], head[0][1] = 0, 2
    ready, _ = dp.compose(*pod_art(head, body), 0, 0, 2, SAME)
    assert ready[0][:3] == (0, 2, 1)


def test_the_pod_head_lands_from_row_0():
    head, body = pod_blank(10), pod_blank()
    head[0][5] = 4
    ready, _ = dp.compose(*pod_art(head, body), 0, 0, 2, SAME)
    assert ready[0][5] == 4
    assert all(v is None for row in ready[1:] for v in row)


def test_both_pod_poses_share_the_head_and_take_their_own_body():
    head, body, action = pod_blank(10), pod_blank(), pod_blank()
    head[0][0], body[23][0], action[23][1] = 4, 1, 2
    heads, bodies = pod_art(head, body, action)
    assert list(heads) == [64]
    assert sorted(bodies) == [64, 192]
    ready, act = dp.compose(heads, bodies, 0, 0, 2, SAME)
    assert (ready[0][0], act[0][0]) == (4, 4)
    assert (ready[23][:2], act[23][:2]) == ((1, None), (None, 2))


def test_pod_size_one_reads_the_blocks_from_0():
    assert dp.block_ids(3, 7, 1) == ((3, 7), (3, 135))
    assert dp.block_ids(3, 7, 2) == ((67, 71), (67, 199))


def test_the_pod_recolour_takes_the_low_nibble_for_the_part():
    body = pod_blank()
    body[0][:2] = [1, 9]
    colours = bytes.fromhex("5aa2b3c4e6f7")
    ready, _ = dp.compose(*pod_art(pod_blank(10), body), 0, 0, 2, colours)
    assert ready[0][:2] == (0xA, 0x5)


def test_a_pod_pixel_is_see_through_wherever_it_ends_as_8():
    """Stored 8 is see-through; so is a part a colour nibble turns into 8."""
    body = pod_blank()
    body[0][:3] = [0, 1, 2]
    colours = bytes.fromhex("98a2b3c4e6f7")
    ready, _ = dp.compose(*pod_art(pod_blank(10), body), 0, 0, 2, colours)
    assert ready[0][:4] == (0, None, 2, None)


def test_the_pod_box_shows_only_where_the_figure_is_see_through():
    box = pod_block(pod_blank(24, 0x57))
    pose = tuple(tuple([4] + [None] * 23) for _ in range(24))
    drawn = dp.on_box(box, pose)
    assert drawn[0][:2] == (4, 0x57)


def test_a_pod_box_with_see_through_pixels_is_named():
    with pytest.raises(dp.DosArtError, match="see-through"):
        dp.on_box(pod_block(pod_blank()), ((None,) * 24,) * 24)


def test_the_pod_palette_is_ega_below_16_and_the_box_s_own_above():
    colours = bytes([0x2A, 0x15, 0x3F]) + bytes(3 * 31)
    box = dp.decode_block(pod_image(pod_blank(24, 0x40), first=0x40,
                                    count=32, colours=colours))
    palette = dp.icon_palette(dp.PodGameArt({}, {}, box))
    assert palette[0x40] == (0xAA, 0x55, 0xFF)
    assert [palette[i] for i in range(16)] == list(di.EGA)
    assert 0x60 not in palette


def test_a_pod_game_folder_is_read_whatever_the_case_of_its_names(tmp_path):
    head, body = pod_image(pod_blank(10)), pod_image(pod_blank())
    box = pod_image(pod_blank(24, 0x57), first=0x40, count=32)
    (tmp_path / "chead.dax").write_bytes(dax({64: head}))
    (tmp_path / "CBODY.DAX").write_bytes(dax({64: body, 192: body}))
    (tmp_path / "Comspr.Dax").write_bytes(dax({15: box}))
    game = dp.read_game(tmp_path)
    assert sorted(game.heads) == [64]
    assert game.box.rows[0][0] == 0x57


def test_a_pod_game_folder_without_the_box_is_named(tmp_path):
    raw = pod_image(pod_blank())
    for name in ("CHEAD.DAX", "CBODY.DAX", "COMSPR.DAX"):
        (tmp_path / name).write_bytes(dax({0: raw}))
    with pytest.raises(dp.DosArtError, match="no block 15"):
        dp.read_game(tmp_path)


@pytest.fixture(scope="module")
def pod_folder():
    dosicontitles = pytest.importorskip("tools.icons.dosicontitles")
    gamedisks = pytest.importorskip("automap.gamedisks")
    root = gamedisks.find("dos-archives")
    if root is None:
        pytest.skip("needs the DOS games; set $FR_ARCHIVES")
    try:
        return dosicontitles.find_folders(root, [POD])[POD]
    except SystemExit as exc:
        pytest.skip(str(exc))


def test_every_pod_figure_block_decodes_to_part_values(pod_folder):
    game = dp.read_game(pod_folder)
    assert sorted(game.heads) == [*range(14), *range(64, 78)]
    assert len(game.bodies) == 128
    blocks = [*game.heads.values(), *game.bodies.values()]
    assert all(b.width == 24 for b in blocks)
    assert {v for b in blocks for row in b.rows for v in row} <= set(range(16))
    assert not any(v == dp.KEY for row in game.box.rows for v in row)


def test_the_archives_pod_party_composes(pod_folder):
    from goldbox import dos_codec
    game = dp.read_game(pod_folder)
    records = sorted((pod_folder / "SAVE").glob("CHRDATA?.SAV"))
    if not records:
        pytest.skip("the archives' Pools of Darkness has no slot A party")
    palette = dp.icon_palette(game)
    for path in records:
        char = dos_codec.read_character(path)
        for pose in dp.compose(game.heads, game.bodies, char.get("icon_head"),
                               char.get("icon_body"), char.get("size"),
                               bytes(char.get("icon_colours"))):
            drawn = dp.on_box(game.box, pose)
            assert sum(v is not None for row in pose for v in row) > 50
            assert all(v in palette for row in drawn for v in row)


# -- Pools of Darkness against the game's ICON screen ------------------------------------
def pod_screen(game: dp.PodGameArt, fields: dict):
    """A 320x200 frame holding `fields`' figure at all four places."""
    numpy = pytest.importorskip("numpy")
    dospodicons = pytest.importorskip("tools.icons.dospodicons")
    screen = numpy.zeros((200, 320), dtype=numpy.int32)
    poses = dospodicons.drawn(game, fields)
    for (_, n), (x, y) in dp.PLACES.items():
        screen[y:y + dp.CELL, x:x + dp.CELL] = numpy.array(poses[n])
    return screen, poses


def pod_capture_art() -> tuple[dp.PodGameArt, dict]:
    head, body = pod_blank(10), pod_blank(24, 1)
    head[0][:2] = [2, 3]
    heads, bodies = pod_art(head, body)
    box = dp.decode_block(pod_image(pod_blank(24, 0x57), first=0x40,
                                    count=32))
    fields = {"icon_head": 0, "icon_body": 0, "size": 2,
              "icon_colours": SAME.hex()}
    return dp.PodGameArt(heads, bodies, box), fields


def test_a_pod_frame_holding_the_figure_passes_at_all_four_places():
    dospodicons = pytest.importorskip("tools.icons.dospodicons")
    game, fields = pod_capture_art()
    screen, poses = pod_screen(game, fields)
    lines = []
    assert dospodicons.check_frame(lines.append, "X", screen, poses) == 0
    assert lines[0].startswith("X: pass")


def test_one_pod_pixel_out_fails_its_place_and_no_other():
    dospodicons = pytest.importorskip("tools.icons.dospodicons")
    game, fields = pod_capture_art()
    screen, poses = pod_screen(game, fields)
    x, y = dp.PLACES[("new", 1)]
    screen[y + 23, x + 5] ^= 1
    assert dospodicons.differences(screen, poses) == {
        ("old", 0): 0, ("old", 1): 0, ("new", 0): 0, ("new", 1): 1}
    lines = []
    assert dospodicons.check_frame(lines.append, "X", screen, poses) == 1
    assert "FAIL" in lines[0]


def test_a_pod_stage_lays_its_bytes_over_the_save_s_and_checks_where_it_began():
    dospodicons = pytest.importorskip("tools.icons.dospodicons")
    fields = {"icon_head": 6, "icon_body": 31, "size": 2,
              "icon_colours": "f0f9f9c0a260"}
    stage = {"stage": "icon", "file": "CHRDATA6.SAV",
             "before": {"icon_head": "06", "icon_body": "1f",
                        "icon_colours": "f0f9f9c0a260"},
             "after": {"icon_head": "06", "icon_body": "1f",
                       "icon_colours": "98f9f9c0a260"}}
    out, problems = dospodicons.staged(fields, [stage], "CHRDATA6.SAV")
    assert out["icon_colours"] == "98f9f9c0a260" and problems == []
    assert dospodicons.staged(fields, [stage], "CHRDATA5.SAV") == (fields, [])
    other = dict(fields, icon_body=30)
    _, problems = dospodicons.staged(other, [stage], "CHRDATA6.SAV")
    assert len(problems) == 1 and "icon_body" in problems[0]


def pod_run(tmp_path, damage: str) -> tuple[pathlib.Path, pathlib.Path]:
    """A generated game folder and a one-step run with `damage` done to it."""
    import json
    game = tmp_path / "game"
    (game / "SAVE").mkdir(parents=True)
    head, body = pod_image(pod_blank(10)), pod_image(pod_blank(24, 1))
    box = pod_image(pod_blank(24, 0x57), first=0x40, count=32)
    (game / "CHEAD.DAX").write_bytes(dax({64: head}))
    (game / "CBODY.DAX").write_bytes(dax({64: body, 192: body}))
    (game / "COMSPR.DAX").write_bytes(dax({15: box}))
    record = bytearray(510)
    record[0], record[1:5] = 4, b"ABCD"
    record[0x19D], record[0x19E:0x1A4] = 2, SAME
    if damage != "record":
        (game / "SAVE" / "CHRDATA1.SAV").write_bytes(bytes(record))
    run = tmp_path / "run"
    (run / "shots").mkdir(parents=True)
    logged = {"file": "CHRDATA1.SAV", "icon_head": 0, "icon_body": 0,
              "size": 2, "icon_colours": SAME.hex()}
    summary = {"title": "darkness", "staged": [], "results": [
        {"name": "ABCD", "record": logged, "icon": "013-icon-1"}]}
    (run / "summary.json").write_text(
        "{" if damage == "summary" else json.dumps(summary))
    if damage == "frame":
        from PIL import Image
        Image.new("RGB", (100, 100)).save(run / "shots" / "013-icon-1.png")
    return game, run


@pytest.mark.parametrize("damage, named", [
    ("screenshot", "013-icon-1.png"), ("frame", "013-icon-1.png"),
    ("record", "CHRDATA1.SAV"), ("summary", "summary.json")])
def test_a_pod_run_it_cannot_read_fails_naming_the_file(tmp_path, capsys,
                                                         damage, named):
    """A missing or unreadable file is a failure line, not a traceback."""
    dospodicons = pytest.importorskip("tools.icons.dospodicons")
    game, run = pod_run(tmp_path, damage)
    assert dospodicons.main(["--game", str(game), "--run", str(run)]) == 1
    printed = capsys.readouterr().out
    assert named in printed
    assert "ABCD" in printed or damage == "summary"


#: The archives' Pools of Darkness party on its ICON screen: all six members
#: as the save holds them, and PAINE again with a body colour nibble of 8.
POD_RUNS = ("dos-icon-darkness", "dos-icon-darkness-seethrough")


def test_every_pod_icon_capture_is_the_composed_figure(pod_folder):
    """Each member's two poses, OLD and NEW, pixel for pixel."""
    import json

    from tools.registry import scratch
    dospodicons = pytest.importorskip("tools.icons.dospodicons")
    runs = [scratch.cache_dir("acceptance", "WISH-378", run)
            for run in POD_RUNS]
    runs = [run for run in runs if (run / "summary.json").exists()]
    if not runs:
        pytest.skip("no Pools of Darkness ICON-screen captures here")
    for run in runs:
        shots = [run / "shots" / f"{result['icon']}.png"
                 for result in json.loads((run / "summary.json").read_text())
                 ["results"] if "icon" in result]
        missing = [shot.name for shot in shots if not shot.is_file()]
        if missing:
            pytest.skip(f"{run.name} lacks {', '.join(missing)}")
    lines = []
    problems = sum(dospodicons.check_run(lines.append, pod_folder, None, run)
                   for run in runs)
    steps = sum("icon" in result for run in runs for result in json.loads(
        (run / "summary.json").read_text())["results"])
    assert problems == 0, lines
    assert sum(": pass (" in line for line in lines) == steps
