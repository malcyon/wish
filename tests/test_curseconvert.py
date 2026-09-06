"""Converting a DOS Curse of the Azure Bonds save into a C64 one (#192).

Two halves, and they fail differently.

**The record**, `goldbox/dos.py`'s `to_neutral` and `goldbox/c64_codec.py`'s
`write`: Curse keeps every ability twice, keeps 69 memorised spells where Pool
of Radiance keeps 81, keeps the class a dual-classed human left, and keeps no
free-spell-slot array at all.  Each of those is a byte the conversion either
carries or reports, and the tests below watch it do one or the other.

**The container**, `goldbox/c64_save.py` and `convert_save`: Curse writes one
7424-byte `SAVEAZURE` with eight character pages, a table of the party's names
where Pool of Radiance's ninth page would be, eight item pages, a page of map
memory and the roster inside the payload -- against Pool of Radiance's two
files and twelve pages.

**Where the specimens come from.**  The synthetic records here are built from
`goldbox/dos_layout.py`'s own table, so they belong to us and run anywhere.
The two tests that read a C64 save the *game* wrote are marked and skip
without it: `work/issue32/specimens/` holds three C64 Curse saves an agent
drove the game to write for `#32`.  The tests that read a *played DOS*
session use `gamedata.specimen("curse-131-four-items-readied")`, under
`$WISH_SPECIMENS` (`~/wish-specimens/` by default) rather than `work/curse/`,
which held the `#113`/`#234` sessions these once read and has been lost
twice (`#333`, Six DOS Curse conversion tests skip because their specimen
lived under work/, which has been lost twice).
"""

from __future__ import annotations

import pathlib

import gamedata
import pytest

from goldbox import c64_codec, c64_save, dos, dos_layout, games, savegame
from goldbox import dos_savegame as sg
from goldbox.d64 import D64, split_load_address

CURSE = dos_layout.CURSE_OF_THE_AZURE_BONDS
CURSE_GAME = games.CURSE_OF_THE_AZURE_BONDS
WORK = pathlib.Path(__file__).resolve().parent.parent / "work"
SPECIMENS = WORK / "issue32" / "specimens"


# --- helpers ----------------------------------------------------------------
def curse_record(**values) -> bytes:
    """A 422-byte Curse record with the named fields set.

    Built from `goldbox/dos_layout.py`'s own table rather than sliced out of
    anybody's save, so it carries no game data and needs no disks.  A value
    that is an `int` fills every byte of a field that is wider than one, which
    is what an ability pair holds in all 406 pairs measured.
    """
    rec = bytearray(CURSE.record_size)
    table = dos_layout.FIELDS_BY_NAME_FOR[CURSE.key]
    for name, value in values.items():
        f = table[name]
        raw = bytes([value] * f.size) if isinstance(value, int) else value
        assert len(raw) == f.size, name
        rec[f.span] = raw
    return bytes(rec)


def neutral_curse(**values):
    return dos.to_neutral(dos.DosCharacter(curse_record(**values)))


# --- the record: the abilities are a pair -----------------------------------
def test_both_copies_of_every_ability_reach_the_c64_record():
    """Curse keeps each ability twice and the C64 record keeps it twice too.

    Without the carry the second copy is written as seven zeroes -- which is
    right for Pool of Radiance, whose engine never reads `0x065`, and is a
    character with no abilities at all in Curse, whose `GEN $1E9C` copies
    `0x065` *forward* into `0x014`.
    """
    n = neutral_curse(strength=18, intelligence=15, wisdom=9, dexterity=13,
                      constitution=16, charisma=11, exceptional_strength=76)
    rec, _ = c64_codec.write(n)
    raw = rec.to_bytes()
    want = bytes((18, 15, 9, 13, 16, 11, 76))
    assert raw[0x014:0x01B] == want
    assert raw[0x065:0x06C] == want


def test_the_two_bytes_of_a_pair_stay_apart():
    """The pair is equal in every record on this machine and the conversion
    does not rely on that: given two different bytes it carries both, the
    first to `0x014` and the second to `0x065`.

    Which of the two the engine treats as current is UNKNOWN -- no specimen
    can say, since none has them different -- so this pins that neither is
    thrown away, not which way round they go.
    """
    n = neutral_curse(strength=b"\x0c\x12")
    assert n.get("strength") == 0x0C
    assert n.get("abilities_second")["strength"] == 0x12
    raw = c64_codec.write(n)[0].to_bytes()
    assert raw[0x014] == 0x0C
    assert raw[0x065] == 0x12


def test_a_pool_of_radiance_character_still_writes_the_ability_copy_as_zero():
    """Pool of Radiance's `0x065` is part of its memorised list, not a second
    ability array, and no Pool of Radiance specimen has ever held anything
    there."""
    from goldbox.neutral import NeutralCharacter
    n = NeutralCharacter("DOS", game="pool-of-radiance")
    n.set("strength", 18, "test")
    raw = c64_codec.write(n)[0].to_bytes()
    assert raw[0x065:0x06C] == bytes(7)


# --- the record: the memorised list -----------------------------------------
def test_the_memorised_list_is_the_titles_own_width():
    """81 slots in Pool of Radiance and 69 in Curse, each ending exactly where
    `thac0_base` at `0x071` begins.

    Both are read off that title's own `CAMP`, which walks the list at five
    sites and counts down from `#$50` in Pool of Radiance and `#$44` in Curse.
    `goldbox/layout.py` declares sixteen and `docs/117-save-conversion.md`
    used to say twenty-one; neither is either title's number.
    """
    assert c64_codec.span_of(c64_codec.POOL_OF_RADIANCE_RECORD.memorised) \
        == (0x020, 81)
    assert c64_codec.span_of(c64_codec.CURSE_RECORD.memorised) == (0x020, 69)
    # Pool of Radiance's runs to `thac0_base`; Curse's stops twelve bytes
    # short of it, and those twelve are the ability block at `0x065`.
    assert sum(c64_codec.span_of(c64_codec.POOL_OF_RADIANCE_RECORD.memorised)) \
        == 0x071
    assert sum(c64_codec.span_of(c64_codec.CURSE_RECORD.memorised)) == 0x065


def test_a_curse_caster_keeps_more_than_sixteen_memorised_spells():
    """The C64 writer truncated the list to sixteen with no warning, which is
    Pool of Radiance's width and nobody's field width.

    Twenty is not a number any Curse record on this machine reaches -- the
    widest list anybody has is seven, because the corpus is capped at level 5
    -- so this is the synthetic case that would otherwise wait for a cleric 7
    with wisdom 18.
    """
    ids = list(range(1, 21))
    book = bytearray(CURSE.sizes["spells_memorised"])
    book[-len(ids):] = ids                    # DOS fills from the end
    n = neutral_curse(spells_memorised=bytes(book))
    assert n.get("spells_memorised") == ids[::-1]
    raw = c64_codec.write(n)[0].to_bytes()
    assert list(raw[0x020:0x020 + len(ids)]) == ids[::-1]
    assert raw[0x020 + len(ids):0x065] == bytes(69 - len(ids))


# --- the record: the dual class ---------------------------------------------
def test_a_dual_classed_curse_character_carries_the_class_it_left():
    """A cleric 1 who was a paladin 5 arrives as a cleric 1 who was a paladin
    5: the C64 keeps the pair at `0x0B9`/`0x0BA`, indexed by the slot in its
    own level array, where DOS keeps a whole second level array.

    Slot 6 is `level_paladin`, and `dual_class_level` is the pair's sentinel
    -- zero there means "not dual-classed" whatever the slot byte holds.
    """
    n = neutral_curse(class_levels=bytes((1, 0, 0, 0, 0, 0, 0, 0)),
                      former_class_levels=bytes((0, 0, 0, 5, 0, 0, 0, 0)))
    assert n.get("former_levels")["paladin"] == 5
    raw = c64_codec.write(n)[0].to_bytes()
    assert raw[0x0B9] == 6
    assert raw[0x0BA] == 5


def test_a_character_who_left_no_class_leaves_the_pair_alone():
    raw = c64_codec.write(neutral_curse())[0].to_bytes()
    assert raw[0x0B9:0x0BB] == bytes(2)


def test_two_former_classes_are_reported_rather_than_half_written():
    """The C64 has room for one class trained out of.  Two is a state no
    engine-written record holds and the conversion says so rather than
    picking one."""
    n = neutral_curse(former_class_levels=bytes((3, 0, 4, 0, 0, 0, 0, 0)))
    rec, rep = c64_codec.write(n)
    assert rec.to_bytes()[0x0B9:0x0BB] == bytes(2)
    assert any("only one class trained out of" in d for d in rep.dropped)


# --- the record: the spell slots Curse does not store -----------------------
def test_curse_reports_the_spell_slots_its_c64_record_cannot_hold():
    """`0x0EE`-`0x0F3` has 32 code references in Pool of Radiance and none in
    Curse over 411 files, and all six records of the engine-written Curse save
    read zero there -- including a level-5 cleric with nothing memorised, who
    would have every slot free.  So the array is not written.

    **Not a drop line any more (#324).**  #192 step 3 watched the memorise
    screen enforce this ceiling with nothing in the converted save supplying
    it, so nothing here is a loss a player would notice; `write` records it
    as a note over the six bytes instead of a line in `rep.dropped`.
    """
    n = neutral_curse(spells_castable_cleric=bytes((2, 2, 1, 0, 0)))
    rec, rep = c64_codec.write(n)
    assert rec.to_bytes()[0x0EE:0x0F4] == bytes(6)
    assert not any("still cast today" in d for d in rep.dropped)
    assert rep.sources[0x0EE] == c64_codec.NO_SPELL_SLOTS
    assert rep.sources[0x0F3] == c64_codec.NO_SPELL_SLOTS


def test_pool_of_radiance_still_writes_its_spell_slots():
    from goldbox.neutral import NeutralCharacter
    n = NeutralCharacter("DOS", game="pool-of-radiance")
    n.set("spells_castable", {"cleric": (2, 1, 0), "magic-user": (3, 0, 0)},
          "test")
    raw = c64_codec.write(n)[0].to_bytes()
    assert raw[0x0EE:0x0F1] == bytes((0x23, 0x10, 0x00))


# --- the tables -------------------------------------------------------------
@pytest.mark.parametrize("shape", dos_layout.SHAPES,
                         ids=[s.key for s in dos_layout.SHAPES])
def test_every_declared_field_has_a_disposition_in_every_title(shape):
    """The disposition is asked per title, because the four tables are not the
    same table: Curse and Silver Blades declare fields Pool of Radiance has
    never heard of, and Pools of Darkness is missing nine of its."""
    declared = {f.name for f in dos_layout.LAYOUTS[shape.key]
                if not f.name.startswith("gap_")}
    table = dos.field_disposition(shape)
    assert declared - set(table) == set()
    assert set(table) - declared == set()


def test_the_conversion_no_longer_refuses_curse():
    """`#192 (Convert a Curse of the Azure Bonds DOS save into a C64 one,
    which the importer refuses today)` step 3 loaded a converted Curse save
    in the running game and read the sheet, so step 4 puts Curse on
    `CONVERTS` for real.

    **This used to end by asserting Silver Blades was still refused.** It was
    proven the same way on 2026-09-05 -- `#193 (Convert a Secret of the
    Silver Blades DOS save into a C64 one, which the importer refuses
    today)` -- and joined `CONVERTS` with it, so the remaining title that
    never converts is Pools of Darkness, which has no C64 port at all."""
    assert CURSE in dos.CONVERTS
    dos.to_neutral(dos.DosCharacter(curse_record()))     # does not raise
    pod = next(s for s in dos_layout.SHAPES
               if s.key == "pools-of-darkness")
    assert pod not in dos.CONVERTS
    with pytest.raises(dos.WrongTitleError):
        dos.to_neutral(dos.DosCharacter(bytes(pod.record_size)))


def test_a_curse_address_is_not_a_variable_address():
    """`$4C20` is a Curse quest flag and `$4A20` is Pool of Radiance's, and
    they are the same word of the same array.

    `word_offset` cannot tell them apart -- `$4C20` is inside Pool of
    Radiance's guard, so it raises nothing and answers 1024 bytes out -- which
    is why the module keeps naming words by Pool of Radiance's address and
    `pool_address` is what converts.
    """
    shape = sg.save_shape_for(CURSE.key)
    assert shape.var_base == 0x4B00
    assert sg.pool_address(0x4C20, shape) == 0x4A20
    assert sg.word_offset(0x4C20, shape) - sg.word_offset(0x4A20, shape) == 1024


# --- the container ----------------------------------------------------------
def test_the_pool_of_radiance_container_is_the_geometry_dos_py_had():
    """The table did not move anything while it was being written down."""
    c = c64_save.POOL_OF_RADIANCE
    assert c.slot_area == dos.SLOT_AREA - dos.SAVE0_BASE
    assert c.item_area == dos.ITEM_AREA - dos.SAVE0_BASE
    assert c.icon_table == dos.ICON_TABLE - dos.SAVE0_BASE
    assert c.cache == (dos.FILE_CACHE[0] - dos.SAVE0_BASE, dos.FILE_CACHE[1])
    assert c.disk_hint == dos.DISK_HINT - dos.SAVE0_BASE
    assert c.record_pages == dos.SLOT_TOTAL
    assert c.party_slots == dos.SLOT_COUNT
    assert not c.roster_in_payload and c.name_table is None
    assert [(a + dos.SAVE0_BASE, n) for a, n, _ in c.zeroed] \
        == list(dos.HEADER_ZEROED)


def test_the_curse_container_is_one_file_with_a_name_table():
    c = c64_save.CURSE_OF_THE_AZURE_BONDS
    assert c.payload_size == 0x1D00
    assert (c.record_pages, c.item_pages) == (8, 8)
    assert c.name_table == 0xC00 and c.roster_offset == 0x1C00
    assert c.picture_buffer == (0x1800, 0x400)
    assert c.cache_bit7 and c.disk_hint == 0xEE
    assert c64_save.container_for(CURSE_GAME) is c
    assert c64_save.container_for(None) is c64_save.POOL_OF_RADIANCE
    with pytest.raises(KeyError):
        c64_save.container_for("champions-of-krynn")


def test_the_flag_window_runs_to_the_end_of_the_page():
    """The twin of `tests/test_ssbconvert.py`'s test of the same name (#289).

    `$4CFE` and `$4CFF` -- the same word indices as Pool of Radiance's
    wallset and wallmap triples -- are named by `ECL04` sixteen times and by
    four scripts respectively, and Curse keeps its own wall triples in the
    twelve unnamed bytes of the square block instead (#253), so nothing
    stops its flag page short of the end.
    """
    first, size = c64_save.container_for(CURSE_GAME).quest_flags
    assert (first, first + size - 1) == (0x120, 0x1FF)
    #: Pool of Radiance stops short, because `+$1FA` and `+$1FD` are its own
    #: wallset and wallmap triples.
    first, size = c64_save.container_for(games.POOL_OF_RADIANCE).quest_flags
    assert (first, first + size - 1) == (0x120, 0x1F8)


def test_the_last_flag_word_reaches_the_c64_payload():
    """A synthetic DOS Curse save with a word set at `$4AFE` -- the last flag
    word before Pool of Radiance's window stops, and inside Curse's own
    window -- reaches the C64 payload at `+$1FE` (#289).

    `$4AFE` is a Pool of Radiance address; `sg.pool_address(0x4CFE, shape)`
    is what a Curse script would call it, and the two name the same word
    (`test_a_curse_address_is_not_a_variable_address` above).
    """
    shape = sg.save_shape_for(CURSE.key)
    savgam = bytearray(shape.size)
    off = sg.word_offset(0x4AFE, shape)
    savgam[off], savgam[off + 1] = 0xFF, 0x00
    save0 = bytearray(c64_save.CURSE_OF_THE_AZURE_BONDS.payload_size)
    window = c64_save.CURSE_OF_THE_AZURE_BONDS.quest_flags
    dos.apply_quest_flags(save0, bytes(savgam), shape, window)
    assert save0[0x1FE] == 0xFF


# --- the container, against a save the game itself wrote --------------------
def _engine_written():
    path = SPECIMENS / "D-curse-party-with-items.D64"
    if not path.exists():
        pytest.skip(f"no engine-written Curse save at {path}; #32 makes one")
    return split_load_address(D64.open(path).read_file("SAVEAZURE"))[1]


def test_the_name_table_is_in_slot_order():
    """A table in the wrong order is a party whose names do not match their
    sheets.  The shipped Silver Blades save has them the other way round,
    which is why this is asserted rather than assumed for Curse.

    Six characters, and name *n* is the name in the record at slot *n*.
    """
    payload = _engine_written()
    c = c64_save.CURSE_OF_THE_AZURE_BONDS
    for slot in range(6):
        record = payload[c.slot(slot):c.slot(slot) + 16]
        table = payload[c.name(slot):c.name(slot) + 16]
        assert record.split(b"\0")[0] == table.split(b"\0")[0]
        assert record.split(b"\0")[0]


def test_the_engine_written_save_agrees_with_the_container():
    """Every geometry claim in the Curse row, read off a save the game wrote:
    the cache carries bit 7, the disk hint is `+$EE`, `+$EA` is unused, the
    roster is inside the payload and the ability copies are equal."""
    payload = _engine_written()
    c = c64_save.CURSE_OF_THE_AZURE_BONDS
    assert len(payload) == c.payload_size
    at, slots = c.cache
    filled = [b for b in payload[at:at + slots] if b != 0xFF]
    assert filled and all(b & 0x80 for b in filled)
    assert payload[c.disk_hint] == 2          # the party is in area 1, side 2
    assert payload[0xEA] == 0                 # Pool of Radiance's byte, unused
    for slot in range(6):
        block = payload[c.roster_offset + slot * c.roster_stride:][:0x20]
        assert block[0] and block[0x0D] == slot
        record = payload[c.slot(slot):c.slot(slot) + 0x100]
        assert record[0x014:0x020] == record[0x065:0x071]


# --- the container, written from a DOS save ---------------------------------
#: The shipped slot A party, driven out of the Windlord's Inn to Weaponers of
#: Cormyr in Tilverton and saved to slot I -- MATHEW carrying a battle axe
#: (readied), a two-handed sword, ten arrows and leather armour, so this is
#: also the first specimen these item assertions have ever run against
#: (`H-square-5-13` carried no items at all).
_DOS_SLOT = "I"


def _dos_save():
    return gamedata.specimen("curse-131-four-items-readied")


def test_no_dos_derived_or_constant_field_reaches_the_import_pane():
    """#324 (The import pane tells a player nine fields could not be
    converted that the C64 recomputes for itself): converting the `#131`
    specimen through `editor.dosimport.rehearse` shows no line for item
    bookkeeping, heap state, the running-effects link, which hand holds a
    weapon or the constant bytes at `field_83_87` -- the same guard as
    `tests/test_dosconvert.py`'s Pool of Radiance version, on Curse's own
    container.  `icon` and `animate` are dummy bytes here, exactly as
    `test_a_curse_save_is_written_whole` uses them: the pane's content does
    not depend on the player's own disks, only the byte-for-byte write does.
    """
    from editor.dosimport import GameFiles, rehearse

    files = GameFiles(icon=bytes(36), animate=bytes(852), portraits=None)
    conversion = rehearse(_dos_save(), _DOS_SLOT, files)
    keywords = ("item list", "internal game state", "running-effects list",
               "which hand is holding", "five bytes that make no difference")
    for line in conversion.report.dropped:
        lowered = line.lower()
        for keyword in keywords:
            assert keyword not in lowered, line


def test_a_converted_party_shows_no_portrait_or_identity_drop_line():
    """#329 (A converted Curse or Silver Blades party still shows two
    portrait drop lines, though #300 proved neither title's sheet draws a
    face), plus #258's identity byte (docs/170-c64-identity-pair.md), written
    for all three titles now rather than reported as dropped.

    The `#131` specimen through `editor.dosimport.rehearse` showed three
    lines before this pair of fixes -- two portrait, one identity -- and
    shows none now, the same measurement `tests/test_ssbconvert.py` takes on
    Silver Blades."""
    from editor.dosimport import GameFiles, rehearse

    files = GameFiles(icon=bytes(36), animate=bytes(852), portraits=None)
    conversion = rehearse(_dos_save(), _DOS_SLOT, files)
    assert conversion.report.dropped == []


def test_a_curse_save_is_written_whole():
    """`new_save` refuses a byte with no source, so this passing at all is the
    claim: 7424 bytes, none of them inherited and none left zero by accident.

    The party is `#131`'s specimen, standing on (3,12) in Tilverton with the
    clock at 0:06, and every one of those reads back through the project's
    own `SaveGame0`.
    """
    save0, save1, report = dos.new_save(
        _dos_save(), _DOS_SLOT, icon=bytes(36), animate=bytes(852),
        game=CURSE_GAME)
    assert len(save0) == 0x1D00 and not save1
    assert report.unwritten == []
    assert len(report.sources) == report.total == 0x1D00

    read = savegame.SaveGame0.from_bytes(bytes(save0), CURSE_GAME)
    assert read.area == 1 and read.area_file == "GEO01"
    assert (read.party.x, read.party.y) == (3, 12)
    assert read.party.clock_text.endswith("0:06")
    assert [s.index for s in read.characters] == [0, 1, 2, 3, 4, 5]

    c = c64_save.CURSE_OF_THE_AZURE_BONDS
    for slot in range(6):
        name = save0[c.slot(slot):c.slot(slot) + 20].split(b"\0")[0]
        assert save0[c.name(slot):c.name(slot) + 16].split(b"\0")[0] == name
    assert save0[c.name(6):0x1000] == bytes(0x1000 - c.name(6))


def test_the_written_cache_names_the_area_with_bit_seven_set():
    """Curse ORs bit 7 on the **save** path and copies raw on load, the
    reverse of Pool of Radiance, so a converted save has to set it itself."""
    save0, _, _ = dos.new_save(_dos_save(), _DOS_SLOT, icon=bytes(36),
                               animate=bytes(852), game=CURSE_GAME)
    at, slots = c64_save.CURSE_OF_THE_AZURE_BONDS.cache
    cache = list(save0[at:at + slots])
    assert cache[dos.CACHE_GEO] == 0x80 | 1        # GEO01
    assert cache[dos.CACHE_ECL] == 0x80 | 1        # ECL01
    assert cache[dos.CACHE_ANIMATE] == 0x80 | 0    # ANIMATE00
    assert [b for n, b in enumerate(cache)
            if n not in (dos.CACHE_GEO, dos.CACHE_ECL, dos.CACHE_ANIMATE)] \
        == [0xFF] * (slots - 3)
    assert save0[c64_save.CURSE_OF_THE_AZURE_BONDS.disk_hint] == 2
    assert save0[0xEA] == 0


def test_the_script_scratch_is_copied_and_the_picture_buffer_is_not():
    """`DUNGEON $21BA` clears `+$100`-`+$11F` only when the script id changes,
    so a save taken inside an area holds live scratch -- the DOS save's own
    thirty-two words cross rather than being zeroed.

    The region at `+$1800` is the other way, and **the reason written here
    used to be wrong**: it said an engine-written save of a party that has not
    walked yet holds zero there.  It does not.  That region is `ANIMATE00`'s
    picture buffer and an engine-written Curse save holds 526 non-zero bytes
    in it, a frame of the camp scene the game was drawing when it saved
    (`docs/181-curse-picture-buffer.md`).  Wish writes zero because nothing in
    a DOS save corresponds to it and the engine rebuilds it before it draws,
    which is a measured zero rather than an inherited one.
    """
    folder = _dos_save()
    save0, _, _ = dos.new_save(folder, _DOS_SLOT, icon=bytes(36),
                               animate=bytes(852), game=CURSE_GAME)
    savgam = (folder / f"SAVGAM{_DOS_SLOT}.DAT").read_bytes()
    shape = sg.save_shape_for(len(savgam))
    want = bytes(sg.word(savgam, 0x4A00 + i, shape) & 0xFF for i in range(0x20))
    assert bytes(save0[0x100:0x120]) == want
    assert any(want)                     # the copy is not a copy of nothing
    at, size = c64_save.CURSE_OF_THE_AZURE_BONDS.picture_buffer
    assert bytes(save0[at:at + size]) == bytes(size)


def test_the_disk_carries_one_file():
    """Pool of Radiance writes `SAVEDGAME0` and `SAVEDGAME1`; every later
    title writes one file, and `save_disk` no longer writes a roster file for
    a title that has no roster file."""
    save0, save1, _ = dos.new_save(_dos_save(), _DOS_SLOT, icon=bytes(36),
                                   animate=bytes(852), game=CURSE_GAME)
    disk = dos.save_disk(bytes(save0), bytes(save1), CURSE_GAME)
    assert [e.display_name for e in disk.directory()] == ["SAVEAZURE"]
    load, payload = split_load_address(disk.read_file(b"SAVEAZURE"))
    assert load == 0x4B00 and payload == bytes(save0)


# --- the combat figure, through Curse's own option tables (#330) -------------
#
# `#130 (A converted DOS party arrives with six identical combat figures, not
# its own)` made each character's figure his own, composed by
# `IconParts.dos_icon` out of `icon_head` and `icon_body`.  That call takes no
# title, and the correspondence table it reads was built from Pool of
# Radiance's art -- so `#330 (A converted Curse or Silver Blades figure is
# composed through Pool of Radiance's icon table, which nobody has checked
# transfers)` asked whether Curse numbers its own art the same way.  It does:
# `CHEAD.DAX` and `CBODY.DAX` are byte-identical between the two titles over
# all 184 blocks, and Curse's own importer copies a Pool of Radiance record's
# icon bytes straight into its own.
#
# These run a Curse record through the same call `convert_save` makes,
# because every other DOS test in this file passes `icon=bytes(36)` and so
# never touches the composition at all.

#: The six colour pairs 42 of the 54 shipped DOS records across the four
#: titles carry, so the figure below is coloured the way most are.
DEFAULT_ICON_COLOURS = bytes.fromhex("91a2b3c4e6f7")


@pytest.fixture(scope="module")
def curse_parts():
    """Curse's own `SPELLE64` and `SPELLN64`, off one Curse side.

    Both files off the *same* disk: `IconParts` fits the load address from
    the editor's own pointer table, and Curse puts the parts file at `$8E00`
    where Pool of Radiance puts it at `$A700`.
    """
    import gamedata

    from goldbox.iconparts import IconParts

    for disk in gamedata.curse_disks():
        if disk.find(b"SPELLE64") and disk.find(b"SPELLN64"):
            return IconParts.load(disk)
    pytest.skip("no Curse side here carries SPELLE64 and SPELLN64")


@pytest.fixture(scope="module")
def curse_reachable(curse_parts):
    """Every shape one weapon and then one head reaches, all four size pairs.

    An icon outside this set is eighteen `CHARPIC00` screen codes in an order
    no menu produces, and the engine draws it without complaint -- which is
    why membership is the assertion rather than "it looks like a figure".
    """
    from goldbox.iconparts import SPACE

    blank = bytes([SPACE] * 18)
    out = set()
    for weapon_size in ("small", "large"):
        for w in range(curse_parts.count(weapon_size, "weapon")):
            shape = curse_parts.apply(blank, weapon_size, "weapon", w)
            for head_size in ("small", "large"):
                for h in range(curse_parts.count(head_size, "head")):
                    out.add(curse_parts.apply(shape, head_size, "head", h))
    return out


def _curse_figure(parts, head, body, size):
    """One Curse record's own combat figure, by the path `convert_save` takes."""
    char = dos.DosCharacter(curse_record(
        icon_head=head, icon_body=body, size=size,
        icon_colours=DEFAULT_ICON_COLOURS))
    icon = dos._icon_for(char, parts)
    rec, _report = dos.to_c64_record(char, icon=icon)
    return icon, rec.get_raw("region_220")


def test_a_curse_record_composes_a_figure_curses_own_menus_can_make(
        curse_parts, curse_reachable):
    """The whole point of `#330`, on a Curse record and Curse's own tables.

    A row naming an option Curse does not have would raise here, and a shape
    the ICON menu cannot reach would fail the membership test -- neither of
    which the `icon=bytes(36)` the rest of this file passes would ever show.
    """
    icon, written = _curse_figure(curse_parts, head=5, body=17, size=2)
    assert written == icon, "the composed figure has to reach the record"
    assert len(icon) == 36
    assert icon[:18] in curse_reachable
    # The colour half obeys the engine's own rule at `$B2F0`: every cell of a
    # part carries that part's single colour, with bit 3 from the glyph.
    per_class = curse_parts.part_colours(icon[18:], icon[:18])
    assert curse_parts.colours_for(icon[:18], per_class, icon[18:]) == icon[18:]


def test_two_curse_characters_with_different_records_get_different_figures(
        curse_parts):
    """What a player sees when this is wrong: a party of identical men.

    Before `#130` every converted character got one composed default, and
    the DOS-side gate `#330` considered would put Curse back there.
    """
    archer, _ = _curse_figure(curse_parts, head=5, body=17, size=2)
    dwarf, _ = _curse_figure(curse_parts, head=13, body=3, size=1)
    assert archer != dwarf
    assert archer != curse_parts.default_icon()
    assert dwarf != curse_parts.default_icon()


def test_every_figure_a_curse_player_can_choose_composes(
        curse_parts, curse_reachable):
    """All 896: Curse's ICON menu wraps the head at 13 and the body at 31,
    both sizes, and `GAME.OVR` holds those constants at Curse's own record
    displacements 0x141 and 0x142."""
    for size in (1, 2):
        for head in range(14):
            for body in range(32):
                icon, _ = _curse_figure(curse_parts, head, body, size)
                assert icon[:18] in curse_reachable, (head, body, size)
