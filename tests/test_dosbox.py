"""The DOSBox harness, and what driving it established about a DOS save.

Two kinds of test live here, and both skip rather than fail on a machine that
has neither the player's archives nor an emulator, which is what CI is.

* The parts of `tools/dosbox.py` that need nothing: the PPM decode, the
  colour-blind screen digest, and the instance lease.
* The **findings** — where the party's square, its facing and its area sit in
  `SAVGAM<slot>.DAT`. These are asserted against the player's own three saves
  and against the game's `GEO*.DAX` indexes, so they are measurements rather
  than a transcription of what the driven run happened to print.

Nothing is copied in. `docs/117-save-conversion.md` carries the reasoning.
"""

from __future__ import annotations

import functools
import os
import pathlib
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import dosbox  # noqa: E402

SAVGAM_SIZE = 13137


# --------------------------------------------------------------------------
# Finding the player's files
# --------------------------------------------------------------------------


def _candidates():
    env = os.environ.get("FR_ARCHIVES")
    if env:
        return [pathlib.Path(env)]
    home = pathlib.Path.home()
    return [
        home / "Downloads" / "fr-archives",
        home / "fr-archives",
        pathlib.Path(__file__).resolve().parent.parent / "work" / "fr-archives",
    ]


@functools.lru_cache(maxsize=1)
def _saves():
    """`{letter: bytes}` for every 13137-byte `SAVGAM?.DAT` of a played party."""
    best: tuple[int, dict[str, bytes]] = (0, {})
    for root in _candidates():
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("SAVGAM?.DAT"):
                found = {
                    p.stem[-1]: p.read_bytes()
                    for p in path.parent.glob("SAVGAM?.DAT")
                    if p.stat().st_size == SAVGAM_SIZE
                }
                if len(found) > best[0]:
                    best = (len(found), found)
        except OSError:
            continue
    return best[1]


@functools.lru_cache(maxsize=1)
def _geo_files():
    """`{area id: GEO file number}` read out of the game's `GEO*.DAX` indexes.

    The container is a `u16le` index size, then entries of `id:u8,
    offset:u32le, compressed:u16le, raw:u16le`.  Only the ids are wanted here.
    """
    try:
        game = dosbox.find_game()
    except FileNotFoundError:
        return {}
    out: dict[int, int] = {}
    for n in range(1, 9):
        path = game / f"GEO{n}.DAX"
        if not path.is_file():
            continue
        data = path.read_bytes()
        size = struct.unpack_from("<H", data, 0)[0]
        for i in range(size // 9):
            out[data[2 + 9 * i]] = n
    return out


@functools.lru_cache(maxsize=1)
def _itm_files():
    """Every `.ITM` in the archives: `{path: bytes}`, saved parties and shipped."""
    out: dict[str, bytes] = {}
    for root in _candidates():
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*.[iI][tT][mM]"):
                out[str(path)] = path.read_bytes()
        except OSError:
            continue
    return out


@functools.lru_cache(maxsize=1)
def _dos_item_templates():
    """Every distinct item record in the game's own `ITEM<n>.DAX` files."""
    try:
        game = dosbox.find_game()
    except FileNotFoundError:
        return ()
    seen: dict[bytes, bytes] = {}
    for n in range(1, 9):
        path = game / f"ITEM{n}.DAX"
        if not path.is_file():
            continue
        for _, block in dosbox.dax_blocks(path.read_bytes()):
            for record in dosbox.items(block):
                seen.setdefault(record[dosbox.ITEM_NEXT:], record)
    return tuple(seen.values())


def _need_items():
    files = _itm_files()
    if not files:
        pytest.skip("needs the DOS item files; set FR_ARCHIVES to the archives")
    return files


def _need_templates():
    templates = _dos_item_templates()
    if not templates:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES to the archives")
    return templates


def _need_saves():
    saves = _saves()
    if not saves:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    return saves


# --------------------------------------------------------------------------
# The pure parts of the harness
# --------------------------------------------------------------------------


def _ppm(pixels, width, height):
    return b"P6\n%d %d\n255\n" % (width, height) + bytes(pixels)


def test_a_binary_ppm_decodes_to_its_pixels():
    px = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    s = dosbox.Screen.from_ppm(_ppm(px, 2, 2))
    assert (s.width, s.height) == (2, 2)
    assert s.px == bytes(px)


def test_a_ppm_with_a_comment_decodes():
    body = b"P6\n# written by something\n1 1\n255\n" + bytes([9, 9, 9])
    assert dosbox.Screen.from_ppm(body).px == bytes([9, 9, 9])


def test_something_that_is_not_a_ppm_is_refused():
    with pytest.raises(ValueError):
        dosbox.Screen.from_ppm(b"\x89PNG\r\n")


def test_the_digest_covers_only_the_rectangle_it_was_given():
    a = dosbox.Screen.from_ppm(_ppm([0] * 12, 2, 2))
    b = dosbox.Screen.from_ppm(_ppm([0, 0, 0, 0, 0, 0, 0, 0, 0, 255, 0, 0], 2, 2))
    assert a.digest((0, 0, 2, 1)) == b.digest((0, 0, 2, 1))
    assert a.digest() != b.digest()


def test_the_ink_digest_ignores_a_recolour_and_not_a_reshape():
    """The command bar is white for a frame and green after; same glyphs.

    That is the whole reason `ink` exists: `digest` calls those two frames
    different screens, and a wait driven by it never finishes.
    """
    white = dosbox.Screen.from_ppm(_ppm([255, 255, 255, 0, 0, 0], 2, 1))
    green = dosbox.Screen.from_ppm(_ppm([85, 255, 85, 0, 0, 0], 2, 1))
    moved = dosbox.Screen.from_ppm(_ppm([0, 0, 0, 255, 255, 255], 2, 1))
    assert white.digest() != green.digest()
    assert white.ink() == green.ink()
    assert white.ink() != moved.ink()


#: The lease is an `flock`, which Windows has no equivalent of. Everything
#: else in this file -- the PPM decode, the digest, and the findings about a
#: DOS save -- is platform-independent and runs everywhere.
posix_only = pytest.mark.skipif(sys.platform == "win32",
                                reason="the instance lease is an flock")


@posix_only
def test_a_leased_slot_is_not_leased_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(dosbox, "INST", tmp_path / "inst")
    monkeypatch.setattr(dosbox, "SLOTS", 2)
    first = dosbox.claim("one")
    second = dosbox.claim("two")
    assert {first.n, second.n} == {0, 1}
    assert first.display != second.display
    with pytest.raises(dosbox.PoolFull):
        dosbox.claim("three")
    first.release()
    third = dosbox.claim("again")
    assert third.n == 0
    second.release()
    third.release()


@posix_only
def test_a_lease_is_dropped_when_the_process_holding_it_dies(tmp_path, monkeypatch):
    """The reason the lease is an flock and not a lock file with a pid in it."""
    monkeypatch.setattr(dosbox, "INST", tmp_path / "inst")
    monkeypatch.setattr(dosbox, "SLOTS", 1)
    repo = pathlib.Path(__file__).resolve().parent.parent
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "from tools import dosbox\n"
        "dosbox.INST = __import__('pathlib').Path(%r)\n"
        "dosbox.SLOTS = 1\n"
        "dosbox.claim('doomed')\n" % (str(repo), str(tmp_path / "inst"))
    )
    subprocess.run([sys.executable, "-c", script], check=True)
    slot = dosbox.claim("survivor")
    assert slot.n == 0
    slot.release()


def test_the_missing_tool_list_names_only_tools_this_module_uses():
    assert set(dosbox.missing_tools()) <= set(dosbox.TOOLS)


def test_a_session_refuses_to_stage_outside_work(tmp_path):
    """The assertion that keeps a copy from ever landing on the player's files."""
    slot = dosbox.Slot(n=0, dir=tmp_path, _fd=-1)
    session = dosbox.Session.__new__(dosbox.Session)
    session.dir = tmp_path
    session.stem = "POOLRAD"
    session.source = tmp_path
    session.exe = "START.EXE"
    session.cycles = 20000
    with pytest.raises(AssertionError):
        session.stage()
    slot.release()


def test_find_game_says_so_when_the_archives_are_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(dosbox, "ARCHIVES", tmp_path / "nowhere")
    with pytest.raises(FileNotFoundError):
        dosbox.find_game()


# --------------------------------------------------------------------------
# The findings, measured off the player's saves
# --------------------------------------------------------------------------


def test_every_save_is_the_size_the_format_says():
    for letter, data in _need_saves().items():
        assert len(data) == SAVGAM_SIZE, letter


def test_the_party_square_reads_as_a_legal_square():
    """16x16 maps, so both coordinates are 0..15 and the facing is 0, 2, 4, 6."""
    for letter, data in _need_saves().items():
        x, y, facing = dosbox.position(data)
        assert 0 <= x < 16, (letter, x)
        assert 0 <= y < 16, (letter, y)
        assert facing in dosbox.FACINGS, (letter, facing)


def test_the_area_id_is_one_the_c64_area_table_knows():
    """The numbering is the same on both ports, which is the finding."""
    from por.areas import AREAS_BY_ID

    for letter, data in _need_saves().items():
        assert dosbox.area_id(data) in AREAS_BY_ID, letter


def test_the_area_id_is_duplicated_at_the_second_entry():
    """`$49C5` and `$49F2` carry the same value in every save seen."""
    for letter, data in _need_saves().items():
        second = data[485] | data[486] << 8
        assert second == dosbox.area_id(data), letter


def test_the_header_byte_is_the_dax_file_that_holds_the_area():
    """Byte 0 is not the area: it is which `GEO<n>.DAX` the area lives in.

    Read straight off the containers, so it is the game's own index that says
    so rather than anything this project inferred.
    """
    saves = _need_saves()
    files = _geo_files()
    if not files:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES to the archives")
    for letter, data in saves.items():
        area = dosbox.area_id(data)
        assert files[area] == data[dosbox.AREA_FILE], (letter, area)


def test_the_header_byte_names_more_than_one_area_so_it_is_not_the_map():
    """The reason obstacle 2 needed the array entry and not just byte 0."""
    files = _geo_files()
    if not files:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES to the archives")
    counts: dict[int, int] = {}
    for n in files.values():
        counts[n] = counts.get(n, 0) + 1
    assert max(counts.values()) > 1


def test_the_c64_arrival_square_for_new_phlan_is_where_the_boat_lands():
    """A cross-port check that costs nothing and would catch a wrong offset.

    `por/areas.py` records New Phlan's arrival as (15, 1) facing west, measured
    on the C64.  Driving DOS and taking the boat back to Phlan puts the party
    at DOS (15, 1) facing 6 -- west, doubled.  The saved run is kept under
    `work/dosbox/p47/`, which is gitignored, so this skips without it.
    """
    from por.areas import AREAS_BY_ID

    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "work"
        / "dosbox"
        / "p47"
        / "09_postboat_phlan.dat"
    )
    if not path.is_file():
        pytest.skip("needs the driven capture in work/dosbox/p47")
    data = path.read_bytes()
    arrival = AREAS_BY_ID[dosbox.area_id(data)].arrival
    x, y, facing = dosbox.position(data)
    assert (x, y) == (arrival.x, arrival.y)
    assert facing == arrival.facing * 2


@pytest.mark.skipif(
    os.environ.get("WISH_DOSBOX_DRIVE") != "1",
    reason="set WISH_DOSBOX_DRIVE=1 to boot DOSBox; it takes about a minute",
)
def test_driving_the_game_one_step_moves_the_square_and_nothing_else():
    """The obstacle-2 experiment itself, opt-in because it drives an emulator."""
    if dosbox.missing_tools():
        pytest.skip("needs " + ", ".join(dosbox.missing_tools()))
    out = dosbox.one_step(load="A", before="C", after="D", turns=2)
    bx, by, _ = out["before"]
    ax, ay, af = out["after"]
    assert (ax, ay) != (bx, by) or af != out["before"][2]
    assert out["area_id"][0] == out["area_id"][1]
    assert dosbox.POS_X in out["changed_in_struct"] + out["changed_in_array"] or (
        dosbox.POS_Y in out["changed_in_struct"]
    )


# --------------------------------------------------------------------------
# The 63-byte item record, and its tail
# --------------------------------------------------------------------------


def test_every_item_file_is_a_whole_number_of_records():
    for path, data in _need_items().items():
        assert data and len(data) % dosbox.ITEM_SIZE == 0, path


def test_the_item_dax_blocks_are_whole_items():
    """The check that the container reader and the run-length coder are right:
    every block decodes to exactly its stated size and every size is items."""
    try:
        game = dosbox.find_game()
    except FileNotFoundError:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES to the archives")
    blocks = 0
    for n in range(1, 9):
        path = game / f"ITEM{n}.DAX"
        if not path.is_file():
            continue
        data = path.read_bytes()
        sizes = {bid: raw for bid, _, raw, _ in dosbox.dax_index(data)}
        for bid, block in dosbox.dax_blocks(data):
            assert len(block) == sizes[bid], (path.name, bid)
            assert len(block) % dosbox.ITEM_SIZE == 0, (path.name, bid)
            blocks += 1
    assert blocks > 40


def test_the_item_list_is_a_null_terminated_chain():
    """`0x02A`-`0x02D` is a far pointer to the next item, NULL on the last.

    Live heap state and nothing a converter wants, but reading it as one field
    is what keeps it out of the fields that do matter.
    """
    for path, data in _need_items().items():
        records = list(dosbox.items(data))
        for record in records[:-1]:
            assert any(record[dosbox.ITEM_NEXT:dosbox.ITEM_NEXT + 4]), path
        last = records[-1][dosbox.ITEM_NEXT:dosbox.ITEM_NEXT + 4]
        assert not any(last), path


def test_the_rendered_line_never_reaches_the_pointer():
    """The name is a Pascal string of at most 41 bytes, so `0x02A` is free."""
    for path, data in _need_items().items():
        for record in dosbox.items(data):
            assert record[dosbox.ITEM_TEXT] <= dosbox.ITEM_TEXT_MAX, path


def test_the_dos_item_type_table_is_the_c64_one():
    """`ITEMS` is 128 x 16 on both ports and 126 records are identical.

    This is what settles the class restrictions: they are byte +13 of *this*
    table, indexed by the item's `0x02E`, and there is nothing in the item
    record to convert.
    """
    from tests.gamedata import game_file

    try:
        game = dosbox.find_game()
    except FileNotFoundError:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES to the archives")
    dos = (game / "ITEMS").read_bytes()[2:]
    c64 = bytes(game_file("ITEMS"))
    assert len(dos) == len(c64) == 128 * 16
    same = sum(
        dos[i * 16:i * 16 + 16] == c64[i * 16:i * 16 + 16] for i in range(128)
    )
    assert same == 126
    differ = [i for i in range(128) if dos[i * 16:i * 16 + 16] != c64[i * 16:i * 16 + 16]]
    assert differ == [8, 9]                       # dagger and dart, in range only
    for i in differ:
        assert dos[i * 16 + 13] == c64[i * 16 + 13]      # the class flags agree


def test_the_dos_item_tail_projects_onto_the_c64_record():
    """157 of the C64's 163 distinct item records, byte for byte, from DOS.

    Every offset in `tools.dosbox.item_to_c64` rests on this: get the plus,
    the saving-throw bonus, the readied bit, the hidden-name mask, the cursed
    bit, the weight, the quantity, the cost or the three special bytes wrong
    and the count collapses.
    """
    from por.items import load_item_templates
    from tests.gamedata import game_disk

    c64 = set(load_item_templates(str(game_disk("POOL1"))).values())
    dos = {dosbox.item_to_c64(r) for r in _need_templates()}
    assert len(c64) == 163
    assert len(c64 & dos) == 157


def test_the_dos_name_words_are_the_c64_itemnames_indices():
    """`0x02F`-`0x031` index the C64's `ITEMNAMES`, so a name is a copy.

    Not a text match against the rendered line: the same three numbers mean
    the same three words on both ports, and every one the game ships resolves.
    """
    from por.items import load_item_names
    from tests.gamedata import game_disk

    names = load_item_names(str(game_disk("POOL1")))
    assert names[48] == "MAIL" and names[162] == "+1"
    used = set()
    for record in _need_templates():
        used.update(record[dosbox.ITEM_NAME1:dosbox.ITEM_NAME3 + 1])
    used.discard(0)
    assert used and used <= set(names)


def test_a_wand_carries_its_charges_in_the_first_special_byte():
    """`0x03C` is charges, and three wands of magic missiles prove the field.

    They are the same item -- type 79, the same three name words, effect 88 --
    differing in `0x03C` and in nothing else that names them.  The game's own
    use-item routine spends `count` first and then this byte, and destroys the
    item when it reaches zero (`work/coab/engine/ovr020.cs`).
    """
    wands = [
        r for r in _need_templates()
        if r[dosbox.ITEM_SPECIAL + 1] == 88 and r[dosbox.ITEM_TYPE] == 79
    ]
    assert len(wands) >= 3
    charges = {r[dosbox.ITEM_SPECIAL] for r in wands}
    assert len(charges) >= 3
    assert all(0 < c < 128 for c in charges)


def test_the_plus_is_signed_and_a_cursed_item_carries_a_negative_one():
    """`0x032` signed, `0x036` the curse -- the pair the C64 keeps at +4 and
    +7 bit 7.  A cursed necklace reads -5 in both `0x032` and `0x033`."""
    cursed = [r for r in _need_templates() if r[dosbox.ITEM_CURSED]]
    assert cursed
    for record in cursed:
        plus = record[dosbox.ITEM_PLUS]
        assert plus > 127, record[dosbox.ITEM_TEXT:]      # every curse is a minus
    necklaces = [
        r for r in cursed
        if r[dosbox.ITEM_PLUS] == 251 and r[dosbox.ITEM_PLUS_SAVE] == 251
    ]
    assert necklaces


def test_the_hidden_name_mask_hides_the_words_the_c64_mask_hides():
    """`0x035` bit 0 hides name 3, bit 1 name 2, bit 2 name 1.

    The invariant that fixes which bit is which: an unidentified item never
    shows its plus.  Read the bits the other way round and 83 of the shipped
    records leak a "+1" the party has not discovered yet; read this way, none
    does.  It is the C64's mask at +6 bits 0-2, same order.
    """
    from por.items import load_item_names
    from tests.gamedata import game_disk

    names = load_item_names(str(game_disk("POOL1")))
    grades = {i for i, text in names.items() if text[:1] in "+-"}
    assert len(grades) > 4

    masks = {r[dosbox.ITEM_HIDDEN] for r in _need_templates()}
    assert masks <= {0, 1, 2, 3, 4, 5, 6, 7}

    masked = 0
    for record in _need_templates():
        mask = record[dosbox.ITEM_HIDDEN]
        if not mask:
            continue
        masked += 1
        words = (record[dosbox.ITEM_NAME3], record[dosbox.ITEM_NAME2],
                 record[dosbox.ITEM_NAME1])
        visible = [w for i, w in enumerate(words) if not mask & 1 << i]
        assert not set(visible) & grades, record[dosbox.ITEM_TEXT:]
    assert masked > 50


def test_the_quantity_falls_when_the_party_fires_the_arrows():
    """`0x039` observed changing in the player's own two saves of one party.

    The stack of arrows +1 in the earlier save holds 18 and in the later one
    11; the rendered line still says 18, which is why the line is not a source
    of anything.
    """
    files = _need_items()
    pairs = {}
    for path, data in files.items():
        name = pathlib.Path(path).name.upper()
        if not name.startswith("CHRDAT") or len(name) != 12:
            continue
        pairs.setdefault(pathlib.Path(path).parent, {})[name[6:8]] = data
    for _, slots in pairs.items():
        a, b = slots.get("A2"), slots.get("B2")
        if not (a and b):
            continue
        ra = list(dosbox.items(a))
        rb = list(dosbox.items(b))
        if len(ra) != len(rb):
            continue
        for x, y in zip(ra, rb):
            if x[dosbox.ITEM_NEXT:] == y[dosbox.ITEM_NEXT:]:
                continue
            moved = [
                i for i in range(dosbox.ITEM_TYPE, dosbox.ITEM_SIZE) if x[i] != y[i]
            ]
            if moved == [dosbox.ITEM_QUANTITY]:
                assert x[dosbox.ITEM_QUANTITY] < y[dosbox.ITEM_QUANTITY]
                return
    pytest.skip("needs the player's own two saves of one party")
