"""Converting a DOS Secret of the Silver Blades save into a C64 one (#193).

The twin of `tests/test_curseconvert.py`, and it exists as a second file
because the two titles' containers are not the same container: three header
rows change hands, the name table may be keyed the other way round, and the
flag page ends five bytes further on.

Four faults these tests were written against, each watched in the running
game on VICE pool slots 0 and 1 on 2026-09-05 before it was fixed:

* **a name with a lower-case letter drew as punctuation.**  The C64 draws in
  the uppercase/graphics character set, where the screen code for a byte in
  `$61`-`$7A` is that byte less `$40`.  Silver Blades' own DOS pregen is
  named `Guy de Valois ` and converted byte for byte his name drew, in the
  party panel and at the head of his sheet, as `G59 $% V!,/)3`.
* **a ranger arrived as a paladin.**  DOS gives the two classes one bit
  between them and the C64 gives the ranger a bit of its own, and
  `class_bits` was copied straight across.
* **a 67-byte Silver Blades item was refused** by `item_to_c64`, which
  demanded 63.
* **five bytes of the quest-flag page were zeroed**, because the window
  stopped where Pool of Radiance's wallset triple begins and this title keeps
  its wall triples somewhere else.

**Where the specimens come from.**  The synthetic records are built from
`goldbox/dos_layout.py`'s own table, so they belong to us and run anywhere.
The tests that read a save the *game* wrote are marked and skip without it:
`work/curse/SSB-*` holds the DOS sessions of `#113` and `#222`, and
`work/193/run1/` the C64 saves this ticket's own VICE session produced.
`work/` is gitignored, so CI runs the synthetic half only.
"""

from __future__ import annotations

import pathlib

import gamedata
import pytest
from test_neutral import _filled

from goldbox import c64_codec, c64_save, dos, dos_layout, games, savegame
from goldbox import dos_savegame as sg
from goldbox.d64 import D64, split_load_address

SSB = dos_layout.SECRET_OF_THE_SILVER_BLADES
SSB_GAME = games.SECRET_OF_THE_SILVER_BLADES
CURSE_GAME = games.CURSE_OF_THE_AZURE_BONDS
WORK = pathlib.Path(__file__).resolve().parent.parent / "work"
DOS_SESSION = WORK / "curse" / "SSB-D-paine-memorised"
DOS_SLOT = "D"

#: DOS level-array slots, `goldbox.dos.CLASS_LEVEL_SLOTS`: 3 paladin, 4 ranger.
PALADIN, RANGER = 3, 4


@pytest.fixture
def converts_ssb(monkeypatch):
    """Put Silver Blades on `CONVERTS` for one test.

    `goldbox.dos.CONVERTS` does not carry this title yet: the refusal stands
    until a converted party has been read off the running game and the three
    wires `#193` step 4 names are in.  This fixture comes out with it.
    """
    if SSB not in dos.CONVERTS:
        monkeypatch.setattr(dos, "CONVERTS", dos.CONVERTS + (SSB,))


def _dos_record(shape, **values) -> bytes:
    """A `shape`'s own size of DOS record with the named fields set.

    Built from `goldbox/dos_layout.py`'s own table rather than sliced out of
    anybody's save, so it carries no game data and needs no disks.
    """
    rec = bytearray(shape.record_size)
    table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
    for name, value in values.items():
        f = table[name]
        raw = bytes([value] * f.size) if isinstance(value, int) else value
        assert len(raw) == f.size, name
        rec[f.span] = raw
    return bytes(rec)


def ssb_record(**values) -> bytes:
    """A 439-byte Silver Blades record with the named fields set."""
    return _dos_record(SSB, **values)


def levels(**by_slot) -> bytes:
    """A seven-byte `class_levels` array with the named slots filled."""
    out = bytearray(7)
    for slot, level in by_slot.items():
        out[int(slot)] = level
    return bytes(out)


# --- the name: capitals, because the C64 has no lower case -------------------
def test_a_lowercase_name_is_folded_to_capitals():
    """`Guy de Valois ` must not reach the C64 record as it stands.

    Without the fold the party panel read `G59 $% V!,/)3`, watched on the
    running machine -- `u` is screen code `5`, `y` is `9`, `d` is `$`.
    """
    assert dos.c64_name("Guy de Valois ") == "GUY DE VALOIS"


def test_a_converted_record_carries_the_folded_name(converts_ssb):
    raw = bytearray(ssb_record(name_length=14))
    table = dos_layout.FIELDS_BY_NAME_FOR[SSB.key]
    at = table["name_text"].offset
    raw[at:at + 14] = b"Guy de Valois "
    rec, _ = dos.to_c64_record(dos.DosCharacter(bytes(raw)))
    assert rec.get("name") == "GUY DE VALOIS"
    assert rec.to_bytes()[:20] == b"GUY DE VALOIS" + bytes(7)


def test_only_the_case_and_the_trailing_blanks_move():
    """Everything else about a name crosses untouched, punctuation included."""
    assert dos.c64_name("O'MALLEY") == "O'MALLEY"
    assert dos.c64_name("ABC-123") == "ABC-123"


# --- the class mask: DOS gives paladin and ranger one bit --------------------
def test_a_dos_ranger_converts_to_the_c64_ranger_bit(converts_ssb):
    """`class_bits` `$40` with a ranger's levels must become `$80`.

    The C64 twin of this title's own shipped ranger reads `$80`; copying the
    DOS byte put him on the C64 as a paladin holding a ranger's levels, which
    is a combination no C64 save of either title holds -- and the sheet read
    `PALADIN`.
    """
    ranger = dos.DosCharacter(ssb_record(
        class_bits=0x40, char_class=4, class_levels=levels(**{str(RANGER): 8})))
    rec, _ = dos.to_c64_record(ranger)
    assert rec.get("class_bits") == 0x80
    assert rec.get("level_ranger") == 8
    assert rec.get("level_paladin") == 0


def test_a_dos_paladin_keeps_bit_six(converts_ssb):
    paladin = dos.DosCharacter(ssb_record(
        class_bits=0x40, char_class=3,
        class_levels=levels(**{str(PALADIN): 8})))
    rec, _ = dos.to_c64_record(paladin)
    assert rec.get("class_bits") == 0x40
    assert rec.get("level_paladin") == 8


def test_every_other_class_bit_is_the_records_own(converts_ssb):
    """Only bit 6 is reread; a stored mask that disagrees with the level
    array for some other reason is left as the record has it."""
    odd = dos.DosCharacter(ssb_record(class_bits=0x08, char_class=14,
                                      class_levels=levels(**{"2": 7, "6": 8})))
    assert dos.neutral_class_bits(odd) == 0x08


def test_the_ranger_bit_folds_back_onto_dos_bit_six():
    assert dos.dos_class_bits(0x80) == 0x40
    assert dos.dos_class_bits(0x40) == 0x40
    assert dos.dos_class_bits(0x0C) == 0x0C
    #: A record that somehow holds both keeps the one bit DOS has for them.
    assert dos.dos_class_bits(0xC0) == 0x40


def test_a_ranger_round_trips_through_the_c64_record(converts_ssb):
    """DOS `$40` -> C64 `$80` -> DOS `$40`, which is what makes the change
    safe: no DOS record's own byte moves.

    The return leg is read at **Silver Blades' own** `class_bits` offset:
    since #299 the writer builds the record of the title the character is
    from, so a Silver Blades character comes back as 439 bytes rather than
    Pool of Radiance's 285.  The fold itself is the same one whichever title
    the record is for.
    """
    ranger = dos.DosCharacter(ssb_record(
        class_bits=0x40, char_class=4,
        class_levels=levels(**{str(RANGER): 8})))
    rec, _ = dos.to_c64_record(ranger)
    back = c64_codec.read(rec, game=SSB_GAME)
    assert back.fields["class_bits"].value == 0x80
    out, _itm, _spc, _report = dos.write(back)
    assert len(out) == dos_layout.SECRET_OF_THE_SILVER_BLADES.record_size
    at = dos_layout.FIELDS_BY_NAME_FOR[
        dos_layout.SECRET_OF_THE_SILVER_BLADES.key]["class_bits"].offset
    assert out[at] == 0x40


# --- infravision: the C64 field is computed, and the race table is per title -
def test_a_silver_blades_human_has_no_infravision(converts_ssb):
    """`race=6` is Silver Blades' human -- and the half-orc's slot in Pool of
    Radiance's numbering, `#287`'s bug: every converted human read 6 at
    `0x0D5` where all six shipped C64 records read 0."""
    human = dos.DosCharacter(ssb_record(race=6))
    rec, _ = dos.to_c64_record(human)
    assert rec.get("infravision") == 0


def test_a_silver_blades_dwarf_has_infravision(converts_ssb):
    """`race=3` is Silver Blades' dwarf -- Pool of Radiance's gnome slot."""
    dwarf = dos.DosCharacter(ssb_record(race=3))
    rec, _ = dos.to_c64_record(dwarf)
    assert rec.get("infravision") == 6


def test_a_pool_of_radiance_human_still_has_no_infravision():
    """The title this table was built from must not move: `race=7` is human
    in Pool of Radiance's own numbering."""
    human = dos.DosCharacter(_dos_record(dos_layout.POOL_OF_RADIANCE, race=7))
    rec, _ = dos.to_c64_record(human)
    assert rec.get("infravision") == 0


def test_a_pool_of_radiance_dwarf_still_has_infravision():
    dwarf = dos.DosCharacter(_dos_record(dos_layout.POOL_OF_RADIANCE, race=1))
    rec, _ = dos.to_c64_record(dwarf)
    assert rec.get("infravision") == 6


def test_a_curse_human_still_has_no_infravision():
    """Curse shares Pool of Radiance's race numbering (`race=7` human)."""
    human = dos.DosCharacter(_dos_record(dos_layout.CURSE_OF_THE_AZURE_BONDS,
                                         race=7))
    rec, _ = dos.to_c64_record(human)
    assert rec.get("infravision") == 0


def test_a_curse_dwarf_still_has_infravision():
    dwarf = dos.DosCharacter(_dos_record(dos_layout.CURSE_OF_THE_AZURE_BONDS,
                                         race=1))
    rec, _ = dos.to_c64_record(dwarf)
    assert rec.get("infravision") == 6


# --- innate combat effects, going back to DOS: keyed by race name too --------
# `RACE_COMBAT_EFFECTS` is `dos.write`'s twin of `INFRAVISION` above: a C64
# record carries no trait id for a dwarf's constitution bonus or a gnome's, so
# the DOS `.SPC` file the writer builds has to derive them from the race byte,
# the same way the C64 record's own infravision byte is derived.  It used to
# be keyed by Pool of Radiance's race numbers and applied to every title
# (#293, A converted Silver Blades dwarf, elf or gnome gets another race's
# innate combat effect, because RACE_COMBAT_EFFECTS is keyed by Pool of
# Radiance's race numbers): Silver Blades' race 1 is the elf and its 3 the
# dwarf, so a converted Silver Blades elf was handed the dwarf's 90, 97, 26
# and 47, a converted dwarf the gnome's 97, 18, 47 and 48, and a converted
# gnome -- race 4, no entry at all -- nothing.
def _spc_ids(spc: bytes) -> list[int]:
    """The effect ids of a `.SPC` payload, one per nine-byte record."""
    assert len(spc) % dos.EFFECT_SIZE == 0
    return [spc[n] for n in range(0, len(spc), dos.EFFECT_SIZE)]


def test_a_silver_blades_elf_carries_his_own_effect_not_the_dwarfs():
    """`race=1` is Silver Blades' elf -- Pool of Radiance's dwarf slot.
    `goldbox/traits.py`'s `NAMES_SILVER_BLADES` seed table gives this title's
    elf 95 alone, not the dwarf's 90, 97, 26 and 47."""
    char = _filled(game=games.SECRET_OF_THE_SILVER_BLADES)
    char.set("race", 1, "made up: elf")
    char.set("innate_effects", [], "made up: nothing in the trait slots")
    _, _, spc, _ = dos.write(char)
    assert _spc_ids(spc) == [95]


def test_a_silver_blades_dwarf_carries_his_own_effects_not_the_gnomes():
    """`race=3` is Silver Blades' dwarf -- Pool of Radiance's gnome slot, so a
    converted dwarf used to be handed 97, 18, 47 and 48."""
    char = _filled(game=games.SECRET_OF_THE_SILVER_BLADES)
    char.set("race", 3, "made up: dwarf")
    char.set("innate_effects", [], "made up: nothing in the trait slots")
    _, _, spc, _ = dos.write(char)
    assert _spc_ids(spc) == [26, 47]


def test_a_silver_blades_gnome_carries_his_own_effects():
    """`race=4` had no entry at all in the old, Pool-of-Radiance-numbered
    table, so a converted Silver Blades gnome carried nothing."""
    char = _filled(game=games.SECRET_OF_THE_SILVER_BLADES)
    char.set("race", 4, "made up: gnome")
    char.set("innate_effects", [], "made up: nothing in the trait slots")
    _, _, spc, _ = dos.write(char)
    assert _spc_ids(spc) == [48, 7]


def test_a_silver_blades_half_elf_and_halfling_carry_their_own_effect():
    for race, expect in ((2, [18]), (5, [92])):
        char = _filled(game=games.SECRET_OF_THE_SILVER_BLADES)
        char.set("race", race, "made up")
        char.set("innate_effects", [], "made up: nothing in the trait slots")
        _, _, spc, _ = dos.write(char)
        assert _spc_ids(spc) == expect, race


def test_a_silver_blades_human_carries_no_innate_effect():
    char = _filled(game=games.SECRET_OF_THE_SILVER_BLADES)
    char.set("race", 6, "made up: human")
    char.set("innate_effects", [], "made up: nothing in the trait slots")
    _, _, spc, _ = dos.write(char)
    assert spc == b""


def test_a_pool_of_radiance_dwarf_is_unmoved_by_the_silver_blades_split():
    """The table this project measured from must not move: Pool of Radiance's
    own race 1, still the dwarf, still carries all four."""
    char = _filled()                        # game=None, race 1, dwarf
    char.set("innate_effects", [], "made up: nothing in the trait slots")
    _, _, spc, _ = dos.write(char)
    assert _spc_ids(spc) == [90, 97, 26, 47]


def test_a_curse_dwarf_still_carries_his_four():
    """Curse shares Pool of Radiance's race numbering (`race=1` dwarf) and
    its table, the way it does for infravision above."""
    char = _filled(game=games.CURSE_OF_THE_AZURE_BONDS)
    char.set("innate_effects", [], "made up: nothing in the trait slots")
    _, _, spc, _ = dos.write(char)
    assert _spc_ids(spc) == [90, 97, 26, 47]


# --- the item record: 67 bytes in this title alone ---------------------------
def test_a_sixty_seven_byte_item_converts():
    """`item_to_c64` demanded 63 and refused every Silver Blades item."""
    item = bytearray(SSB.item_size)
    table = dos_layout.ITEM_FIELDS_BY_NAME
    item[table["type_index"].offset] = 39
    item[table["quantity"].offset] = 30
    out = dos.item_to_c64(bytes(item))
    assert len(out) == c64_codec.ITEM_SIZE
    assert out[0] == 39


def test_an_item_whose_four_extra_bytes_are_used_is_refused():
    """Nothing is attributed to `0x03F`-`0x042`; they read zero in 48 of 48
    driven records, so a non-zero one is a byte with nowhere to go."""
    item = bytearray(SSB.item_size)
    item[dos.ITEM_TAIL[0]] = 1
    with pytest.raises(dos.DosRecordError) as e:
        dos.item_to_c64(bytes(item))
    assert "0x03F" in str(e.value)


def test_pool_of_radiances_sixty_three_still_converts():
    assert len(dos.item_to_c64(bytes(dos_layout.ITEM_SIZE))) == 16


# --- the container -----------------------------------------------------------
def test_the_container_is_curses_geometry_under_a_different_name():
    ssb = c64_save.container_for(SSB_GAME)
    curse = c64_save.container_for(CURSE_GAME)
    for field in ("slot_area", "party_slots", "record_pages", "name_table",
                  "item_area", "item_pages", "icon_table", "picture_buffer",
                  "roster_offset", "cache", "cache_bit7", "disk_hint"):
        assert getattr(ssb, field) == getattr(curse, field), field
    assert ssb.payload_size == 0x1D00
    assert ssb.game.save_file == b"SAVEDBASH"


def test_the_disk_hint_is_plus_ee_and_not_pool_of_radiances_plus_ea():
    """`CAMP $0C65` writes `$7F12` into `$4BEE` on the save path and
    `GEN $228E` reads it back on the load path; `$4BEA` is `DUNGEON $0B0E`'s
    own scratch here."""
    assert c64_save.container_for(SSB_GAME).disk_hint == 0xEE


def test_the_cache_needs_bit_seven_because_the_loader_does_not_set_it():
    """`GEN $2424` is `LDA $4DC0,X / STA $7F13,X` with no `ORA`."""
    assert c64_save.container_for(SSB_GAME).cache_bit7 is True


def test_the_flag_window_runs_to_the_end_of_the_page():
    """Seventeen of this title's twenty-two scripts name `$4CFD`, which is
    the same word index as Pool of Radiance's wallmap, and the C64 engine's
    own resave wrote `$FF` there over a zero the conversion had written."""
    first, size = c64_save.container_for(SSB_GAME).quest_flags
    assert (first, first + size - 1) == (0x120, 0x1FF)
    #: Pool of Radiance stops short, because `+$1FA` and `+$1FD` are its own
    #: wallset and wallmap triples.
    first, size = c64_save.container_for(games.POOL_OF_RADIANCE).quest_flags
    assert (first, first + size - 1) == (0x120, 0x1F8)


def test_the_name_table_is_keyed_the_other_way_round_from_curses():
    ssb = c64_save.container_for(SSB_GAME)
    curse = c64_save.container_for(CURSE_GAME)
    assert curse.names_in_marching_order is False
    assert ssb.names_in_marching_order is True
    #: Six characters: slot 5 is the head of the party, so it is entry 0.
    assert [ssb.name_index(slot, 6) for slot in range(6)] == [5, 4, 3, 2, 1, 0]
    assert [curse.name_index(slot, 6) for slot in range(6)] == [0, 1, 2, 3, 4, 5]


def test_the_shipped_save_is_what_the_marching_order_reading_rests_on():
    """The claim in one line, so a future reader can see what would refute it.

    Entry 0 of the shipped `SAVEDBASH`'s table is the character in slot 5.
    """
    ssb = c64_save.container_for(SSB_GAME)
    assert ssb.name(ssb.name_index(5, 6)) == ssb.name_table


# --- the whole save, off a DOS session this project drove --------------------
needs_dos_session = pytest.mark.skipif(
    not (DOS_SESSION / f"SAVGAM{DOS_SLOT}.DAT").is_file(),
    reason="no driven DOS Silver Blades session under work/curse/")


@needs_dos_session
def test_a_whole_save_is_written_with_nothing_left_to_the_payload(converts_ssb):
    save0, save1, report = dos.new_save(DOS_SESSION, DOS_SLOT, bytes(36),
                                        animate=None, game=SSB_GAME)
    assert report.unwritten == []
    assert len(save0) == 0x1D00
    assert save1 == bytearray()


@needs_dos_session
def test_the_payload_reads_back_as_the_dos_party(converts_ssb):
    save0, _save1, _r = dos.new_save(DOS_SESSION, DOS_SLOT, bytes(36),
                                     animate=None, game=SSB_GAME)
    payload = bytes(save0)
    savgam = (DOS_SESSION / f"SAVGAM{DOS_SLOT}.DAT").read_bytes()
    shape = sg.save_shape_for(SSB_GAME.key)
    x, y, facing = sg.position(savgam, shape)
    assert (payload[0xC0], payload[0xC1], payload[0xC2]) == (x, y, facing)
    assert payload[0xC5] == sg.geo_block(savgam)
    assert payload[0xF2] == sg.current_area(savgam)
    assert payload[0xE6] == 1
    save = savegame.SaveGame0(payload, SSB_GAME)
    names = [s.record.get("name") for s in save.slots if s.occupied]
    assert names == ["MORGAINE", "DOMINIC", "MALACHITE", "EPONA", "PAINE",
                     "GUY DE VALOIS"]


@needs_dos_session
def test_the_name_table_reads_in_marching_order(converts_ssb):
    save0, _s1, _r = dos.new_save(DOS_SESSION, DOS_SLOT, bytes(36),
                                  animate=None, game=SSB_GAME)
    table = [bytes(save0[0xC00 + i * 16:0xC00 + i * 16 + 16]).split(b"\0")[0]
             for i in range(6)]
    assert table[0] == b"GUY DE VALOIS"
    assert table[5] == b"MORGAINE"


@needs_dos_session
def test_the_twelve_items_land_on_the_head_of_the_party(converts_ssb):
    """The head of the party is slot 5, and he is the only one carrying
    anything.  Read off the running game as twelve named lines."""
    save0, _s1, _r = dos.new_save(DOS_SESSION, DOS_SLOT, bytes(36),
                                  animate=None, game=SSB_GAME)
    page = bytes(save0[0x1000 + 5 * 0x100:0x1000 + 6 * 0x100])
    filled = sum(1 for n in range(16) if any(page[n * 16:(n + 1) * 16]))
    assert filled == 12
    for slot in range(5):
        other = bytes(save0[0x1000 + slot * 0x100:0x1000 + (slot + 1) * 0x100])
        assert not any(other)


def test_no_dos_derived_or_constant_field_reaches_the_import_pane():
    """#324 (The import pane tells a player nine fields could not be
    converted that the C64 recomputes for itself): converting
    `WISH-SPEC-ssb-234-party-pair` slot D through `editor.dosimport.rehearse`
    shows no line for item bookkeeping, heap state, the running-effects
    link, which hand holds a weapon or the constant bytes at `field_83_87`
    -- the same guard as `tests/test_dosconvert.py`'s Pool of Radiance
    version and `tests/test_curseconvert.py`'s Curse one.  `icon` and
    `animate` are dummy bytes, as they are throughout this file's own DOS
    tests: the pane's content does not depend on the player's own disks.
    """
    from editor.dosimport import GameFiles, rehearse

    folder = gamedata.specimen("ssb-234-party-pair")
    files = GameFiles(icon=bytes(36), animate=bytes(852), portraits=None)
    conversion = rehearse(folder, "D", files)
    keywords = ("item list", "internal game state", "running-effects list",
               "which hand is holding", "five bytes that make no difference")
    for line in conversion.report.dropped:
        lowered = line.lower()
        for keyword in keywords:
            assert keyword not in lowered, line


def test_a_silver_blades_conversion_needs_no_creation_tables():
    """`#131`: `new_save` refuses a conversion without the creation menu's
    tables wherever the destination draws a sheet portrait, and Silver
    Blades draws none (#300, `draws_sheet_portrait`), so `portraits=None`
    converts here exactly as before -- the control for the Pool of Radiance
    refusal in `tests/test_dosconvert.py`."""
    from editor.dosimport import GameFiles, rehearse

    folder = gamedata.specimen("ssb-234-party-pair")
    files = GameFiles(icon=bytes(36), animate=bytes(852), portraits=None)
    conversion = rehearse(folder, "D", files)
    assert conversion.report.unwritten == []
    assert conversion.game.key == SSB_GAME.key


def test_a_converted_party_shows_no_portrait_or_identity_drop_line():
    """#329 (A converted Curse or Silver Blades party still shows two
    portrait drop lines, though #300 proved neither title's sheet draws a
    face), plus #258's identity byte (docs/170-c64-identity-pair.md), written
    for all three titles now rather than reported as dropped.

    `WISH-SPEC-ssb-234-party-pair` slot D through `editor.dosimport.rehearse`
    showed three lines before this pair of fixes -- two portrait, one
    identity -- and shows none now."""
    from editor.dosimport import GameFiles, rehearse

    folder = gamedata.specimen("ssb-234-party-pair")
    files = GameFiles(icon=bytes(36), animate=bytes(852), portraits=None)
    conversion = rehearse(folder, "D", files)
    assert conversion.report.dropped == []


# --- the engine's own rewrite, from this ticket's VICE session ---------------
#: The specimen tree first, because `work/` is gitignored and a save the
#: engine wrote is the one thing here that cannot be regenerated without an
#: emulator session -- `.claude/rules/testing.md`, "a specimen dies with the
#: emulator slot that made it".
def _engine_save() -> "pathlib.Path | None":
    import os
    tree = pathlib.Path(os.environ.get("WISH_SPECIMENS",
                                       pathlib.Path.home() / "wish-specimens"))
    for candidate in (tree / "por-c64" / "WISH-SPEC-ssb-d-converted-resave.D64",
                      WORK / "193" / "run2" / "engine-resave.D64",
                      WORK / "193" / "run1" / "engine-resave.D64"):
        if candidate.is_file():
            return candidate
    return None


ENGINE = _engine_save()
needs_engine_save = pytest.mark.skipif(
    ENGINE is None,
    reason="no engine-written Silver Blades save in the specimen tree or "
           "under work/193/")


@needs_engine_save
def test_the_engine_leaves_the_spell_slot_array_zero():
    """The second leg of `spell_slots=False` for this title.

    A reference census over its 347 files finds `$7CEE`-`$7CF3` named twenty
    times and not once in a code file; this is the other reading -- six
    records the C64 engine itself wrote back, including a cleric 8 and a
    magic-user 9 who have memorised nothing and would have every slot free.
    """
    _load, payload = split_load_address(
        D64(ENGINE.read_bytes()).read_file(SSB_GAME.save_file))
    save = savegame.SaveGame0(bytes(payload), SSB_GAME)
    filled = [s.record_bytes[0x0EE:0x0F4] for s in save.slots if s.occupied]
    assert len(filled) == 6
    assert all(not any(f) for f in filled)


# --- the combat figure, through Silver Blades' own option tables (#330) ------
#
# The twin of `tests/test_curseconvert.py`'s section, and it exists because
# `IconParts.dos_icon` takes no title while the correspondence table it reads
# was built from Pool of Radiance's art -- `#330 (A converted Curse or Silver
# Blades figure is composed through Pool of Radiance's icon table, which
# nobody has checked transfers)`.
#
# Silver Blades numbers its art the same way: 182 of the 184 `CHEAD.DAX` and
# `CBODY.DAX` blocks are byte-identical to Pool of Radiance's at the same
# ids, its ICON menu wraps at the same 13 and 31, and its own importer copies
# a Curse record's icon bytes straight across.  Two options it re-drew --
# head 10 at size 2 and body 11 at size 1 -- are art differences inside a
# numbering that did not move, and `tests/test_iconparts.py` is where those
# two are pinned.

#: The six colour pairs 42 of the 54 shipped DOS records across the four
#: titles carry.
DEFAULT_ICON_COLOURS = bytes.fromhex("91a2b3c4e6f7")


@pytest.fixture(scope="module")
def ssb_parts():
    """Silver Blades' own `SPELLE64` and `SPELLN64`, off one Silver side.

    Both files off the *same* disk, because `IconParts` fits the load address
    out of the editor overlay's own pointer table and this title puts the
    parts file at `$8E00`.
    """
    gamedisks = pytest.importorskip("tools.gamedisks")

    from goldbox.iconparts import IconParts

    where = gamedisks.find("secret-of-the-silver-blades")
    if where is None or not where.is_dir():
        pytest.skip("needs the Silver Blades disks; set $SSB_DISKS")
    for path in sorted(pathlib.Path(where).glob("*.[dD]64")):
        try:
            disk = D64.open(path)
        except Exception:
            continue
        if disk.find(b"SPELLE64") and disk.find(b"SPELLN64"):
            return IconParts.load(disk)
    pytest.skip("no Silver Blades side here carries SPELLE64 and SPELLN64")


@pytest.fixture(scope="module")
def ssb_reachable(ssb_parts):
    """Every shape one weapon and then one head reaches, all four size pairs.

    An icon outside it is eighteen `CHARPIC00` screen codes no menu produces,
    and the engine draws them anyway -- which is why this is the assertion.
    """
    from goldbox.iconparts import SPACE

    blank = bytes([SPACE] * 18)
    out = set()
    for weapon_size in ("small", "large"):
        for w in range(ssb_parts.count(weapon_size, "weapon")):
            shape = ssb_parts.apply(blank, weapon_size, "weapon", w)
            for head_size in ("small", "large"):
                for h in range(ssb_parts.count(head_size, "head")):
                    out.add(ssb_parts.apply(shape, head_size, "head", h))
    return out


def _ssb_figure(parts, head, body, size):
    """One record's own combat figure, by the path `convert_save` takes."""
    char = dos.DosCharacter(ssb_record(
        icon_head=head, icon_body=body, size=size,
        icon_colours=DEFAULT_ICON_COLOURS))
    icon = dos._icon_for(char, parts)
    rec, _report = dos.to_c64_record(char, icon=icon)
    return icon, rec.get_raw("region_220")


def test_a_silver_blades_record_composes_a_figure_its_own_menus_can_make(
        converts_ssb, ssb_parts, ssb_reachable):
    icon, written = _ssb_figure(ssb_parts, head=5, body=24, size=2)
    assert written == icon, "the composed figure has to reach the record"
    assert len(icon) == 36
    assert icon[:18] in ssb_reachable
    per_class = ssb_parts.part_colours(icon[18:], icon[:18])
    assert ssb_parts.colours_for(icon[:18], per_class, icon[18:]) == icon[18:]


def test_two_silver_blades_characters_with_different_records_differ(
        converts_ssb, ssb_parts):
    """What a player sees when this is wrong: six identical men on the combat
    floor, which is what `#130 (A converted DOS party arrives with six
    identical combat figures, not its own)` was."""
    knight, _ = _ssb_figure(ssb_parts, head=5, body=24, size=2)
    dwarf, _ = _ssb_figure(ssb_parts, head=13, body=3, size=1)
    assert knight != dwarf
    assert knight != ssb_parts.default_icon()
    assert dwarf != ssb_parts.default_icon()


def test_every_figure_a_silver_blades_player_can_choose_composes(
        converts_ssb, ssb_parts, ssb_reachable):
    """All 896 of them: this title's `GAME.OVR` wraps the head at 13 and the
    body at 31 at its own record displacements 0x153 and 0x154."""
    for size in (1, 2):
        for head in range(14):
            for body in range(32):
                icon, _ = _ssb_figure(ssb_parts, head, body, size)
                assert icon[:18] in ssb_reachable, (head, body, size)


# --- #301: a party that has not set out is refused, not guessed --------------

def test_a_silver_blades_party_that_has_not_set_out_is_refused_not_guessed():
    """Silver Blades' container stages no script, so `$4FE1` is the reading
    -- 0 in both never-adventured containers here and 255 in all five
    played ones -- and its first area is UNMEASURED, so `areas.STARTS` has
    no row and the conversion refuses rather than sending the party to
    whichever area looks likeliest (#301).  The sentence the player reads
    is Donald's own, 2026-09-06, and names no title on purpose: it reads
    the same whichever title is refused, so nothing is interpolated into
    it."""
    shape = sg.SAVE_SECRET_OF_THE_SILVER_BLADES
    assert shape.script_buffer is None
    savgam = bytearray(shape.size)
    sg.put_word(savgam, sg.INDOORS, 1, shape)
    sg.put_position(savgam, 7, 13, 0, shape)
    assert dos.never_adventured(bytes(savgam))
    cont = c64_save.container_for(SSB_GAME)
    with pytest.raises(dos.NotSetOutError) as raised:
        dos.apply_file_cache(bytearray(cont.payload_size), bytes(savgam), cont)
    assert raised.value.player_message == (
        "This save has never been played yet. Wish does not yet support "
        "converting these saves.")
    assert raised.value.player_message == dos.NOT_SET_OUT_UNPLACED
    assert "NOT APPROVED" not in raised.value.player_message
    assert "$" not in raised.value.player_message
    with pytest.raises(dos.NotSetOutError):
        dos.apply_position(bytearray(cont.payload_size), bytes(savgam), shape)

    # The same container one keypress later -- `$4FE1` written, a real area
    # -- is a party in the world and is placed where it stands.
    sg.put_word(savgam, dos.LATER_BEGUN_WORD, 255, shape)
    sg.put_word(savgam, sg.SCRIPT, 0x10, shape)
    sg.put_word(savgam, sg.AREA, 0x10, shape)
    assert not dos.never_adventured(bytes(savgam))
    save0 = bytearray(cont.payload_size)
    dos.apply_file_cache(save0, bytes(savgam), cont)
    assert save0[cont.current_script] == 0x10
    assert save0[cont.disk_hint] == 1


def _shipped_silver_blades_save():
    from test_dossave import _game_dirs
    folder = _game_dirs().get("SECRET")
    return None if folder is None else folder / "SAVGAMA.DAT"


@pytest.mark.skipif(_shipped_silver_blades_save() is None,
                    reason="needs the archives' Silver Blades saves")
def test_the_archives_shipped_silver_blades_party_is_one_that_has_not_set_out():
    """The two saved games the archives ship for this title are both in this
    state -- area 0, `7,13` facing north, `$4FE1` = 0 -- so the first Silver
    Blades save a player reaches for is one the import refuses until the
    title's start is measured.  A found save with no chain of custody, read
    here only to show what the refusal says about it."""
    savgam = _shipped_silver_blades_save().read_bytes()
    assert sg.current_area(savgam) == 0
    assert dos.never_adventured(savgam)
    cont = c64_save.container_for(SSB_GAME)
    with pytest.raises(dos.NotSetOutError):
        dos.apply_file_cache(bytearray(cont.payload_size), savgam, cont)
