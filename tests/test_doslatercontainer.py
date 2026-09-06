"""The DOS saved-game *container* for Curse of the Azure Bonds and Secret of
the Silver Blades, built from nothing (#299).

`tests/test_doslatertitles.py` proves the 422- and 439-byte records; this
file proves the `SAVGAM<slot>.DAT` around them, which is what the DOS engine
loads a party from.  Two kinds of test:

* **synthetic**, on zeroed buffers of each shape, for the writers in
  `goldbox.dos_savegame` -- no game data involved;
* **specimen-backed**, converting the two engine-written C64 saves in
  `~/wish-specimens/por-c64` with the DOS archives' own `ECL<n>.DAX` files,
  which skip without either.  No record or container bytes are pasted here.

Sample sizes, so the claims are countable: two C64 disks (one per title),
six Curse and six Silver Blades DOS containers censused for the "every live
word is written or declared" gate.
"""
from __future__ import annotations

import pathlib

import pytest
from gamedata import specimen_root

from goldbox import areas, dos, dos_layout
from goldbox import dos_savegame as sg
from goldbox.d64 import D64
from goldbox.savegame import load_save

CURSE = sg.SAVE_CURSE_OF_THE_AZURE_BONDS
SSB = sg.SAVE_SECRET_OF_THE_SILVER_BLADES
POOL = sg.SAVE_POOL_OF_RADIANCE
LATER = (CURSE, SSB)

#: The two C64 saves the C64 engine itself wrote after loading a converted
#: party (`#192`, `#193`), and the DOS directory each converts against.
SOURCES = {
    CURSE: ("curse-dual-classed", "CURSE"),
    SSB: ("ssb-d-engine-resave", "SECRET"),
}


# --- helpers -----------------------------------------------------------------

def _c64_disk(name: str) -> pathlib.Path:
    root = specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = list((root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    return found[0]


def _game_dir(stem: str) -> pathlib.Path:
    from tools import dosbox
    try:
        return dosbox.find_game(stem)
    except FileNotFoundError as e:
        pytest.skip(str(e))


def _payloads(shape):
    name, _stem = SOURCES[shape]
    game, sg0, sg1 = load_save(D64.open(str(_c64_disk(name))))
    return game, sg0.to_bytes(), sg1.to_bytes()


def _built(shape, tmp_path, slot="D"):
    """A whole DOS save of this title from its C64 specimen, and its report."""
    game, save0, save1 = _payloads(shape)
    report = dos.new_dos_save(save0, save1, tmp_path, slot,
                              _game_dir(SOURCES[shape][1]), title=game)
    return game, save0, report, (tmp_path / f"SAVGAM{slot}.DAT").read_bytes()


def _later_containers(shape):
    """Every engine-written container of this title in the specimen tree,
    as `(name, bytes)`, hand-built ones excluded by provenance."""
    root = specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    out = []
    for path in sorted((root / "por-dos").glob("WISH-SPEC-*/SAVGAM?.DAT")):
        data = path.read_bytes()
        if len(data) == shape.size:
            out.append((f"{path.parent.name}/{path.name}", data))
    return out


# --- the writers, on synthetic buffers --------------------------------------

@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_the_wall_block_round_trips_inside_the_square_block(shape):
    """The twelve bytes are two interleaved `u16[1..3]` arrays, set then
    map, in the order each engine's writer emits them (#253, #299)."""
    save = bytearray(shape.size)
    sg.put_wall_block(save, (21, sg.EMPTY, sg.EMPTY), shape)
    assert sg.wall_block(save, shape) == ((21, sg.EMPTY, sg.EMPTY),
                                          (1, sg.EMPTY, sg.EMPTY))
    # The bytes, as a played Silver Blades container holds them.
    at = shape.wall_block
    assert save[at:at + 12] == bytes.fromhex("15 00 01 00 ff ff ff ff ff ff "
                                             "ff ff")
    sg.put_wall_block(save, (1, 2, 3), shape)
    assert sg.wall_block(save, shape) == ((1, 2, 3), (1, 2, 3))
    # And it lands inside the square block, after the mode byte and before
    # the party-size byte.
    assert at == shape.mode + 1
    assert at + 12 == shape.party_size_byte


def test_pool_of_radiance_has_no_wall_block():
    with pytest.raises(sg.DosSaveError):
        sg.wall_block(bytes(POOL.size))
    with pytest.raises(sg.DosSaveError):
        sg.put_wall_block(bytearray(POOL.size), (1, 2, 3))


@pytest.mark.parametrize("shape", sg.SAVE_SHAPES[:3], ids=lambda s: s.key)
def test_the_party_size_and_names_land_at_the_shapes_own_offsets(shape):
    save = bytearray(shape.size)
    sg.put_party_size(save, 4, shape)
    sg.put_character_files(save, "j", shape)
    assert sg.party_size(save) == 4
    assert sg.word(save, sg.PARTY_SIZE) == 4
    assert save[shape.party_size_byte] == 4
    assert sg.character_files(save) == [f"CHRDATJ{n}" for n in range(1, 7)]
    # The size byte is the byte before the table, whatever the title.
    assert shape.party_size_byte == shape.party_table - 1


@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_a_later_titles_retarget_writes_the_block_and_not_the_flag_page(
        shape):
    """`$4AFD` is a quest flag in the later titles (255 in every played
    Silver Blades container and on its C64 disk), so a retarget that wrote
    Pool of Radiance's wallmap there would overwrite one."""
    save = bytearray(shape.size)
    script = b"\x88\x13" + bytes(range(1, 40))
    sg.retarget(save, area=0x10, dax=1, wallset=(21, sg.EMPTY, sg.EMPTY),
                script=script if shape.script_bytes else None, shape=shape)
    assert sg.word(save, sg.WALLMAP) == 0
    assert all(sg.word(save, sg.WALLSET + i) == 0 for i in range(3))
    assert sg.wall_block(save) == ((21, sg.EMPTY, sg.EMPTY),
                                   (1, sg.EMPTY, sg.EMPTY))
    assert save[0] == 1 and sg.word(save, sg.DISK) == 1
    assert sg.current_area(save) == 0x10 and sg.geo_block(save) == 0x10
    if shape.script_bytes:
        start, _end = shape.script_buffer
        assert save[start:start + 39] == script[2:]
    else:
        with pytest.raises(sg.DosSaveError):
            sg.retarget(save, area=0x10, dax=1, wallset=(21, 0, 0),
                        script=script, shape=shape)


@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_the_later_tail_is_written_zero_and_pool_of_radiances_is_not(shape):
    later = bytearray(shape.size)
    later[shape.tail_scratch:shape.party_size_byte] = b"\xaa" * (
        shape.party_size_byte - shape.tail_scratch)
    sg.put_tail_state(later, indoors=True, shape=shape)
    assert later[shape.tail_scratch:shape.tail_scratch + 2] == b"\0\0"
    assert later[shape.previous_mode] == 0 and later[shape.mode] == 0
    # The block after them is untouched.
    assert later[shape.wall_block] == 0xAA
    pool = bytearray(POOL.size)
    sg.put_tail_state(pool, indoors=True)
    assert pool[sg.TAIL_CONSTANT_BYTE] == sg.TAIL_CONSTANT
    assert pool[sg.VIEW_MODE_BYTE] == sg.VIEW_MODE_INDOORS


def test_a_7424_byte_payload_is_refused_without_a_title():
    """Curse and Silver Blades are the same size on the C64 and different
    files on DOS, so guessing would build a save the wrong engine loads."""
    with pytest.raises(dos.DosRecordError) as e:
        dos.c64_title(bytes(7424))
    assert "Curse of the Azure Bonds" in str(e.value)
    assert "Secret of the Silver Blades" in str(e.value)
    assert dos.c64_title(bytes(7168)).key == "pool-of-radiance"
    assert dos.c64_title(bytes(7424), "curse-of-the-azure-bonds").key == \
        "curse-of-the-azure-bonds"
    with pytest.raises(dos.DosRecordError):
        dos.c64_title(bytes(7168), "curse-of-the-azure-bonds")


@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_the_per_title_account_names_addresses_once_each(shape):
    """A table that names the same word twice, or one outside the array, is
    a table whose count is wrong -- the same check `tests/test_doswriter.py`
    makes of Pool of Radiance's."""
    seen = set()
    for address, words, why in dos.savgam_unsourced(shape):
        assert why.strip(), hex(address)
        for a in range(address, address + words):
            assert sg.VAR_BASE <= a <= sg.VAR_LAST, hex(a)
            assert a not in seen, hex(a)
            seen.add(a)
    for address, value, why in dos.savgam_constants(shape):
        assert why.strip() and 0 <= value <= 0xFFFF
        assert sg.VAR_BASE <= address <= sg.VAR_LAST, hex(address)
        assert address not in seen, hex(address)
        seen.add(address)
    # The two later titles do not share Pool of Radiance's constants: Silver
    # Blades holds `$506D` and `$50F6` at zero in every container.
    if shape is SSB:
        assert 0x506D not in seen and 0x50F6 not in seen


# --- the DAX number, from the DOS files -------------------------------------

@pytest.mark.parametrize("stem, title, area, want", [
    ("POOLRAD", areas.POOL_OF_RADIANCE, 0x00, 3),
    ("CURSE", areas.CURSE_OF_THE_AZURE_BONDS, 0x01, 2),
    ("SECRET", areas.SECRET_OF_THE_SILVER_BLADES, 0x10, 1),
    ("SECRET", areas.SECRET_OF_THE_SILVER_BLADES, 0x40, 2),
    ("SECRET", areas.SECRET_OF_THE_SILVER_BLADES, 0x60, 3),
])
def test_the_dax_number_is_the_dos_file_that_holds_the_block(
        stem, title, area, want):
    """Silver Blades packs six C64 sides into three DOS containers, so its
    area table's side is not the container number: area `$40` is on C64
    side 4 and in `ECL2.DAX` (#299)."""
    assert dos.dos_dax_number(_game_dir(stem), area) == want


def test_the_area_tables_side_is_the_dax_number_for_two_titles_and_not_the_third():
    """Measured file by file: every Pool of Radiance and Curse row with a
    block agrees with its table; 21 of Silver Blades' 22 rows do not, and
    the one that does is on side 1.  The table is not "fixed" to match --
    its column is the side the C64 loader asks for, and that is right."""
    for stem, title in (("POOLRAD", areas.POOL_OF_RADIANCE),
                        ("CURSE", areas.CURSE_OF_THE_AZURE_BONDS)):
        game = _game_dir(stem)
        checked = 0
        for row in areas.areas_for(title):
            n = dos.dos_dax_number(game, row.id)
            if n is None:
                continue
            assert n == row.disk, (stem, hex(row.id), n, row.disk)
            checked += 1
        assert checked >= 24, (stem, checked)
    game = _game_dir("SECRET")
    differs = [row.id for row in areas.areas_for(
        areas.SECRET_OF_THE_SILVER_BLADES)
        if dos.dos_dax_number(game, row.id) not in (None, row.disk)]
    assert len(differs) == 20, [hex(i) for i in differs]


def test_a_missing_block_is_none_rather_than_a_guess(tmp_path):
    assert dos.dos_dax_number(tmp_path, 1) is None
    assert dos.dos_dax_number(None, 1) is None
    assert dos.dos_dax_number(_game_dir("CURSE"), 0x1E) is None


# --- a whole save from nothing, per title -----------------------------------

@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_a_whole_save_from_nothing_is_the_titles_own_size_and_accounted(
        shape, tmp_path):
    """`save_shape_for` sizes the buffer -- 5469 for Silver Blades, 13149 for
    Curse -- and every byte has a source.  Before #299 the writer built
    13137 bytes whatever it was handed, and refused a 7424-byte payload."""
    _game, _save0, report, savgam = _built(shape, tmp_path)
    assert len(savgam) == shape.size
    assert report.unwritten == []
    assert len(report.sources) == report.total == shape.size
    assert sg.save_shape_for(len(savgam)) is shape


@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_the_written_container_reads_back_as_the_party_we_put_in(
        shape, tmp_path):
    from goldbox import c64_save
    game, save0, _report, savgam = _built(shape, tmp_path)
    c = c64_save.container_for(game)
    assert sg.character_files(savgam) == [f"CHRDATD{n}" for n in range(1, 7)]
    assert sg.party_size(savgam) == 6
    assert sg.current_area(savgam) == save0[c.current_script]
    assert sg.geo_block(savgam) == save0[c.current_geo]
    x, y, facing = save0[c.position:c.position + 3]
    assert sg.position(savgam) == (x, y, facing)
    assert savgam[shape.pos_facing] == facing * sg.FACING_SCALE
    for i in range(sg.CLOCK_DIGITS):
        assert sg.word(savgam, sg.CLOCK + i) == save0[c.clock + i], i
    # The wall block is the C64 cache's slots 15-17, bit 7 masked, with the
    # index map beside it; the variable-array triples stay zero.
    wallset, wallmap = sg.wall_block(savgam)
    assert wallset == dos.c64_wall_triple(save0, c)
    assert wallmap == sg.wall_map(wallset)
    assert all(sg.word(savgam, sg.WALLSET + i) == 0 for i in range(3))
    # The whole flag page, to `$4AFF`, and the three per-area bytes.
    first, size = c.quest_flags
    for i in range(size):
        assert sg.word(savgam, sg.VAR_BASE + first + i) == save0[first + i]
    for i in range(3):
        assert sg.word(savgam, 0x49E7 + i) == save0[0xE7 + i]
    # The engine's own initialiser values, and the party the DOS reader sees.
    assert sg.word(savgam, dos.LATER_MODE_WORD) == 4
    assert sg.word(savgam, dos.LATER_FLAGS_WORD) == 3
    party = dos.read_party(tmp_path, "D")
    assert len(party) == 6
    assert {p.shape.key for p in party} == {shape.key}


def test_a_curse_save_stages_its_areas_own_script(tmp_path):
    """The same assertion Pool of Radiance's
    `test_a_retarget_writes_the_place_and_stages_the_script` makes: the
    buffer is `ECL<n>.DAX` block *area* from byte 2 on, then zero."""
    _game, save0, _report, savgam = _built(CURSE, tmp_path)
    area = sg.current_area(savgam)
    dax = savgam[0]
    assert dax == sg.word(savgam, sg.DISK) == \
        areas.area_in(area, areas.CURSE_OF_THE_AZURE_BONDS).disk
    block = sg.dax_block((_game_dir("CURSE") / f"ECL{dax}.DAX").read_bytes(),
                         area)
    start, end = CURSE.script_buffer
    body = block[sg.ECL_HEADER:]
    assert savgam[start:start + len(body)] == body
    assert not any(savgam[start + len(body):end])


def test_a_silver_blades_save_stages_no_script_and_names_the_dax(tmp_path):
    _game, _save0, report, savgam = _built(SSB, tmp_path)
    assert SSB.script_buffer is None
    assert savgam[0] == sg.word(savgam, sg.DISK) == \
        dos.dos_dax_number(_game_dir("SECRET"), sg.current_area(savgam))
    assert any("not staged" in line for line in report.converted)


@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_the_gate_can_fail_for_the_later_titles_too(shape, tmp_path,
                                                    monkeypatch):
    """With the zero account taken away `new_dos_save` refuses rather than
    handing back a file whose zeroes nobody stands behind."""
    game, save0, save1 = _payloads(shape)
    monkeypatch.setattr(dos, "savgam_zeroes", lambda *a, **k: None)
    with pytest.raises(dos.DosRecordError) as e:
        dos.new_dos_save(save0, save1, tmp_path, "D",
                         _game_dir(SOURCES[shape][1]), title=game)
    assert "no source" in str(e.value)
    assert not (tmp_path / "SAVGAMD.DAT").exists()


@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_a_character_carrying_nothing_gets_no_item_file_in_the_titles_suffix(
        shape, tmp_path):
    """`#62`'s trap on the later suffixes: a zero-length item file is how
    the engine says "one item, from whatever the heap held", so a character
    with nothing gets no `.SWG`/`.STF` at all."""
    _game, _save0, _report, _savgam = _built(shape, tmp_path)
    record_shape = dos_layout.SHAPES_BY_KEY[shape.key]
    table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
    empty = carrying = 0
    for n in range(1, 7):
        rec = (tmp_path / f"CHRDATD{n}.SAV").read_bytes()
        count = rec[table["item_count"].offset]
        sibling = tmp_path / f"CHRDATD{n}{record_shape.item_suffix}"
        if count == 0:
            assert not sibling.exists(), sibling
            empty += 1
        else:
            assert sibling.stat().st_size == count * record_shape.item_size
            carrying += 1
    assert empty >= 1, "no empty-handed character to test the trap on"
    if shape is SSB:
        assert carrying == 1  # Guy de Valois' twelve, and nobody else's


@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_a_stale_slot_in_the_titles_suffixes_is_cleared(shape, tmp_path):
    game, save0, save1 = _payloads(shape)
    record_shape = dos_layout.SHAPES_BY_KEY[shape.key]
    for n in range(1, 7):
        for suffix in (".SAV", record_shape.item_suffix,
                       record_shape.effect_suffix):
            (tmp_path / f"CHRDATD{n}{suffix}").write_bytes(b"stale")
    (tmp_path / "MINE.TXT").write_bytes(b"the user's")
    dos.new_dos_save(save0, save1, tmp_path, "D",
                     _game_dir(SOURCES[shape][1]), title=game)
    assert (tmp_path / "MINE.TXT").read_bytes() == b"the user's"
    for path in tmp_path.glob("CHRDATD*"):
        assert path.read_bytes() != b"stale", path


def test_a_later_title_needs_the_game_directory(tmp_path):
    """Silver Blades stages no script, but the DOS `ECL` files are still
    where the container number comes from (`dos_dax_number`)."""
    game, save0, save1 = _payloads(SSB)
    with pytest.raises(dos.DosRecordError) as e:
        dos.write_dos_save(save0, save1, None, tmp_path, "D", title=game)
    assert "game directory" in str(e.value)
    assert not (tmp_path / "SAVGAMD.DAT").exists()


# --- the census gate: every live word of every engine container -------------

@pytest.mark.parametrize("shape", LATER, ids=lambda s: s.key)
def test_every_nonzero_word_a_later_titles_container_holds_is_written_or_declared(
        shape):
    """A field the engine writes that this conversion neither sources nor
    names would be written zero in silence -- the same gate
    `tests/test_doswriter.py` keeps for Pool of Radiance, over every
    engine-written Curse or Silver Blades container in the specimen tree.
    """
    from goldbox import c64_save
    c = c64_save.container_for(shape.key)
    written = set(range(sg.VAR_BASE + c.quest_flags[0],
                        sg.VAR_BASE + c.quest_flags[0] + c.quest_flags[1]))
    written |= set(dos.SHARED_SCRATCH)
    written |= {sg.VAR_BASE + dos.LATER_HEADER_COPIED[0] + i
                for i in range(dos.LATER_HEADER_COPIED[1])}
    written |= set(range(sg.CLOCK, sg.CLOCK + sg.CLOCK_DIGITS))
    written |= {sg.AREA, sg.SCRIPT, sg.DISK, sg.INDOORS, sg.PARTY_SIZE,
                sg.TRAVEL_X, sg.TRAVEL_Y}
    written |= {a for a, _, _ in dos.savgam_constants(shape)}
    declared = {a + i for a, n, _ in dos.savgam_unsourced(shape)
                for i in range(n)}
    containers = _later_containers(shape)
    assert len(containers) >= 2, f"only {len(containers)} {shape.title} " \
                                 f"containers in the specimen tree"
    for name, data in containers:
        for addr in range(sg.VAR_BASE, sg.VAR_LAST + 1):
            v = sg.word(data, addr)
            if v and addr not in written | declared:
                raise AssertionError(
                    f"{name} holds {v} at ${addr:04X}, which the conversion "
                    f"neither writes nor declares")
