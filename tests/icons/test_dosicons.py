"""`goldbox/dos_icons.py` composes a DOS combat figure the way the loader does.

The synthetic tests build their own blocks, so they run anywhere.  The rest
read the player's DOS games and skip without them: every block decodes, Silver
Blades' re-drawn head comes from its own file, Donald's own Pool of Radiance
party composes, and `tools/icons/dosicons.py` re-reads every rule the module
holds out of each title's `GAME.OVR` and `START.EXE`.
"""

from __future__ import annotations

import struct

import pytest

from goldbox import dos_icons as di

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
