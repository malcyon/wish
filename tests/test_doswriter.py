"""The DOS writer: a neutral character becomes a 285-byte record (#26).

The other half of `tests/test_dosconvert.py`.  That module proves the DOS
*reader* understood the file by handing the bytes back; this one proves the
*writer* is the reader's inverse, in the only form that direction can have:

* **the round trip** -- a DOS record read into the neutral middle and written
  out again is byte-for-byte the original everywhere a byte *can* survive,
  and the mask of bytes that cannot is `por.dos.WRITE_UNSOURCED` -- the named
  live-heap and unattributed runs -- not whatever happened to differ;
* **nothing dropped silently** -- every neutral field has a disposition in
  the writer, every DOS layout field has a target, and every byte of both
  outputs has a provenance.

**The saves are Donald's, not the repository's** -- see `test_dossave.py`.
"""

from __future__ import annotations

import pytest
from test_dossave import _save_dir, needs_dos_saves
from test_neutral import _filled

from por import c64_codec, dos, dos_layout, neutral
from por import dos_savegame as sg
from por.layout import Confidence

# --- the tables, which need no save -----------------------------------------

def test_write_targets_tile_the_dos_layout():
    """The promise the brief for #26 makes explicit: a field added to
    `por/dos_layout.py` and forgotten by the writer fails here rather than
    passing in silence."""
    declared = {f.name for f in dos_layout.LAYOUT
                if not f.name.startswith("gap_")}
    assert declared - set(dos.WRITE_TARGETS) == set()
    assert set(dos.WRITE_TARGETS) - declared == set()


def test_read_targets_tile_the_c64_layout():
    """The C64 reader's layout-wide account, which #25 left to this issue: a
    field `por/layout.py` names and `c64_codec.read` neither reads nor names
    as dropped would be lost in silence on the way to DOS."""
    from por import layout
    known = {f.name for f in layout.LAYOUT if f.is_known}
    assert known - set(c64_codec.READ_TARGETS) == set()
    # region_220 is the combat icon, graded UNKNOWN in the layout for its
    # bytes but named by the reader as a deliberate drop.
    assert set(c64_codec.READ_TARGETS) - known == {"region_220"}


def test_every_neutral_field_has_a_write_disposition():
    """The writer's twin of `test_every_neutral_field_has_a_disposition_in_
    every_writer`: a name added to `por/neutral.py`'s FIELDS and never wired
    into the DOS writer is named here."""
    assert neutral.undeclared(neutral.FIELDS, dos.write_field_disposition()) \
        == (set(), set())
    assert dos.write_field_disposition() == neutral.disposition(
        dos.WRITE_DIRECT, dos.WRITE_TRANSFORMED, dos.WRITE_DROPPED,
        "the DOS record's")


def test_the_writer_and_reader_direct_tables_are_mirrors():
    """Every straight copy the reader makes, the writer makes back.  The two
    name the same neutral fields; only the roster spellings differ, and those
    on the C64 side, not this one."""
    read_neutral = {n for n, _ in dos.DIRECT}
    write_neutral = {n for n, _ in dos.WRITE_DIRECT}
    # The reader's DIRECT names DOS fields (its neutral names are the same
    # strings); turn_power crosses by rule on the way in and by copy back out.
    assert write_neutral - read_neutral == {"turn_power"}
    assert read_neutral - write_neutral == set()


# --- the item projection, both ways ------------------------------------------

def _synthetic_dos_item() -> bytes:
    """A 63-byte item with every shared field set to a distinct value."""
    raw = bytearray(63)
    raw[0x000] = 7
    raw[0x001:0x008] = b"7 Darts"          # the cache, never a source
    raw[0x02A:0x02E] = b"\x40\x1F\x22\x11"  # a live next pointer
    for n, (name, value) in enumerate((
            ("type_index", 33), ("name1", 48), ("name2", 162),
            ("name3", 208), ("plus", 0xFB), ("plus_save", 0xFE),
            ("readied", 1), ("hidden", 5), ("cursed", 1))):
        raw[dos_layout.ITEM_FIELDS_BY_NAME[name].offset] = value
    raw[0x037:0x039] = (2312).to_bytes(2, "little")   # weight
    raw[0x039] = 7                                     # quantity
    raw[0x03A:0x03C] = (1234).to_bytes(2, "little")   # value
    raw[0x03C], raw[0x03D], raw[0x03E] = 20, 3, 9
    return bytes(raw)


def test_item_from_c64_inverts_the_projection():
    """DOS -> C64 -> DOS keeps the whole 17-byte tail, unpacking the two
    packed bytes back into readied, hidden and cursed.  What does not come
    back is exactly the cache and the pointer, both left empty."""
    original = _synthetic_dos_item()
    back = dos.item_from_c64(dos.item_to_c64(original))
    assert back[0x02E:] == original[0x02E:]
    assert back[:0x02A] == bytes(0x02A)      # the rendered-line cache
    assert back[0x02A:0x02E] == bytes(4)     # the next pointer


def test_item_to_c64_inverts_item_from_c64():
    """The other way is exact: any legal sixteen-byte item survives."""
    sixteen = bytes((33, 48, 162, 208, 0xFB, 0xFE, 0x85, 0x80,
                     0x08, 0x09, 7, 0xD2, 0x04, 20, 3, 9))
    assert dos.item_to_c64(dos.item_from_c64(sixteen)) == sixteen


# --- the writer, on a synthetic character ------------------------------------

def test_a_filled_character_lands_field_for_field():
    """Every value the writer takes reads back off the DOS record through the
    DOS reader's own accessors."""
    char = _filled()
    rec, itm, rep = dos.write(char)
    assert len(rec) == dos_layout.RECORD_SIZE
    back = dos.DosCharacter(rec, items=[dos.DosItem(itm[i:i + 63])
                                        for i in range(0, len(itm), 63)])
    assert back.name == "ROUNDTRIP"
    for neutral_name, dos_name in dos.WRITE_DIRECT:
        assert back.get(dos_name) == char.get(neutral_name), dos_name
    assert back.spells_known == [1, 5, 55]
    assert back.spells_memorised == [44, 21, 3]
    assert back.class_levels == {"fighter": 7, "thief": 3}
    assert back.raw("spells_castable_cleric") == bytes((3, 2, 1))
    assert back.raw("spells_castable_magic_user") == bytes((4, 3, 2))
    assert back.get("size") == 2
    assert back.raw("attack_forms") == bytes(range(1, 9))
    assert back.raw("roster_tail") == bytes(range(9))
    assert back.get("item_count") == 1
    # `_filled`'s item is bytes(range(16)), which is not a *legal* C64 item:
    # +7 is cursed in bit 7 and nothing else, so its value 0x07 has no DOS
    # home and comes back 0.  Everything that means something survives.
    back_item = dos.item_to_c64(itm[:63])
    assert back_item[:7] == bytes(range(7))
    assert back_item[7] == 0
    assert back_item[8:] == bytes(range(8, 16))
    # The identity the DOS engine itself computes: money + weight x quantity.
    weight = 0x0908 * 10
    assert back.get("encumbrance") == \
        min(sum(back.money.values()) + weight, 0xFFFF)
    # And every byte of both outputs has a provenance.
    assert rep.total == dos_layout.RECORD_SIZE + len(itm)
    assert rep.unaccounted == []


def test_a_value_graded_unknown_is_not_written_to_dos():
    char = _filled()
    char.set("wisdom", 9, "somewhere", Confidence.UNKNOWN)
    rec, _, rep = dos.write(char)
    assert rec[dos_layout.FIELDS_BY_NAME["wisdom"].offset] == 0
    assert any("wisdom" in d and "UNKNOWN" in d for d in rep.dropped)


def test_a_class_with_no_dos_slot_is_reported():
    """The knight: the one class the C64 numbers and DOS does not.  Druid and
    monk go the other way -- DOS has their slots, so they carry."""
    char = _filled()
    char.set("levels", {"fighter": 7, "knight": 2, "druid": 4}, "made up")
    rec, _, rep = dos.write(char)
    assert any("knight" in w for w in rep.warnings)
    raw = rec[dos_layout.FIELDS_BY_NAME["class_levels"].span]
    assert raw[2] == 7      # fighter is class number 2
    assert raw[1] == 4      # druid has a DOS slot the C64 lacks
    assert 2 not in (raw[0], raw[3], raw[4], raw[5], raw[6], raw[7])


def test_a_name_too_long_for_dos_is_truncated_and_said():
    char = _filled()
    char.set("name", "ABCDEFGHIJKLMNOPQRST", "made up",
             Confidence.CONFIRMED, neutral.Provenance.RESHAPED)
    rec, _, rep = dos.write(char)
    assert rec[0] == 15
    assert rec[1:16] == b"ABCDEFGHIJKLMNO"
    assert any("truncated" in w for w in rep.warnings)


# --- the round trip, against real files --------------------------------------

def _unsourced_offsets() -> set[int]:
    """The bytes the writer says it cannot source, as offsets -- the round
    trip's mask comes from the writer's own account, not from the diff."""
    out: set[int] = set()
    for name, _ in dos.WRITE_UNSOURCED:
        f = dos_layout.FIELDS_BY_NAME[name]
        out.update(range(f.offset, f.end))
    return out


def _records():
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    out = [dos.read_character(p) for p in
           sorted(where.glob("*.SAV")) + sorted(where.glob("*.CHA"))
           if p.stat().st_size == dos_layout.RECORD_SIZE]
    if not out:
        pytest.skip("no DOS Pool of Radiance character records here")
    return out


ENC = dos_layout.FIELDS_BY_NAME["encumbrance"]


def _diff_against(char, rec: bytes) -> tuple[set[int], bool]:
    """`(offsets differing outside the mask and encumbrance, encumbrance
    differs)` for one written record against the original."""
    original = char.to_bytes()
    mask = _unsourced_offsets()
    differs = {i for i in range(len(original)) if original[i] != rec[i]}
    enc = bool(differs & set(range(ENC.offset, ENC.end)))
    return differs - mask - set(range(ENC.offset, ENC.end)), enc


@needs_dos_saves
def test_a_record_round_trips_through_the_neutral_middle():
    """DOS -> to_neutral -> write, against the original bytes.  Everything
    outside the writer's own unsourced list survives byte for byte, 24 of
    24; encumbrance is recomputed and matches wherever the original's own
    identity balanced (22 of 24 -- the two stale dart stacks)."""
    total = enc_misses = 0
    for char in _records():
        rec, itm, _ = dos.write(dos.to_neutral(char))
        outside, enc = _diff_against(char, rec)
        assert outside == set(), (char.name, sorted(hex(i) for i in outside))
        enc_misses += enc
        total += 1
        # The item tails are the original's, record for record.
        for n, item in enumerate(char.items):
            ours = itm[n * 63:(n + 1) * 63]
            assert ours[0x02E:] == item.to_bytes()[0x02E:], (char.name, n)
    assert total >= 24
    assert enc_misses <= 2, f"{enc_misses} encumbrance misses of {total}"


@needs_dos_saves
def test_a_record_round_trips_through_the_c64_record():
    """The architecture's whole claim, measured: DOS -> neutral -> **C64
    record** -> neutral -> DOS loses nothing the direct trip keeps.  The C64
    record is a sufficient interchange for everything the DOS writer can
    source."""
    total = 0
    for char in _records():
        c64_rec, _ = c64_codec.write(dos.to_neutral(char))
        back = c64_codec.read(c64_rec, source="round trip")
        rec, _, _ = dos.write(back)
        outside, _ = _diff_against(char, rec)
        assert outside == set(), (char.name, sorted(hex(i) for i in outside))
        total += 1
    assert total >= 24


@needs_dos_saves
def test_the_write_report_accounts_for_every_byte():
    for char in _records():
        _, _, rep = dos.write(dos.to_neutral(char))
        assert rep.unaccounted == [], (char.name, rep.unaccounted[:8])
        assert rep.dropped


# --- the roster path carries the stored encoding ------------------------------

def test_the_roster_path_speaks_the_stored_encoding():
    """`RosterBlock.armour_class` decodes the family's 60 - value bias; the
    neutral convention is the stored byte, which is what every record path
    carries.  The first live C64-to-DOS run showed AC 51 for an AC 9 fighter
    because the roster branch of `c64_codec.read` handed the decoded number
    through; this is that bug, pinned."""
    import pathlib

    from por.encoding import COMBAT_BIAS
    from por.savegame import SaveGame0, SaveGame1
    here = pathlib.Path(__file__).resolve().parent / "fixtures"
    sg = SaveGame0.from_prg((here / "savedgame0.bin").read_bytes())
    sg1 = SaveGame1.from_prg((here / "savedgame1.bin").read_bytes())
    slot = sg.characters[0]
    block = sg1.roster(slot.index)
    char = c64_codec.read(slot.record, roster=block)
    assert char.get("armour_class") == COMBAT_BIAS - block.armour_class
    assert char.get("thac0_current") == COMBAT_BIAS - block.thac0
    assert char.get("hp_current") == block.hit_points
    # The block's nine-byte combat tail comes too -- a slot record stops
    # short of it, and the first conversion wrote zeros into the DOS tail.
    assert char.get("roster_tail") == block.raw[0x10:0x19]
    # And through the DOS writer, the stored byte lands verbatim.
    rec, _, _ = dos.write(char)
    assert rec[dos_layout.FIELDS_BY_NAME["armour_class"].offset] == \
        COMBAT_BIAS - block.armour_class


# --- the whole save, C64 payloads to DOS files -------------------------------

def _fixture_payloads():
    import pathlib

    from por.savegame import SaveGame0, SaveGame1
    here = pathlib.Path(__file__).resolve().parent / "fixtures"
    sg = SaveGame0.from_prg((here / "savedgame0.bin").read_bytes())
    sg1 = SaveGame1.from_prg((here / "savedgame1.bin").read_bytes())
    return sg.to_bytes(), sg1.to_bytes()


@needs_dos_saves
def test_write_dos_save_writes_a_readable_party(tmp_path):
    save0, save1 = _fixture_payloads()
    report = dos.write_dos_save(save0, save1, _save_dir(), tmp_path, "A")
    party = dos.read_party(tmp_path, "A")
    assert [c.name for c in party] == ["BRUTUS"]
    # The fixture BRUTUS carries nothing, so he gets no `.ITM` at all -- see
    # `test_a_character_who_carries_nothing_gets_no_itm_file`.
    assert not (tmp_path / "CHRDATA1.ITM").exists()
    assert not (tmp_path / "CHRDATA1.SPC").exists()

    savgam = (tmp_path / "SAVGAMA.DAT").read_bytes()
    # The quest flags are the C64 bytes, widened to words.
    for addr in range(dos.FLAGS_FIRST, dos.FLAGS_LAST + 1):
        assert sg.word(savgam, addr) == save0[addr - dos.SAVE0_BASE], \
            hex(addr)
    # Both parties stand in area 0, so the square converts too.
    assert sg.area_id(savgam) == save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE]
    x, y, facing = sg.position(savgam)
    assert (x, y) == (save0[0x49C0 - 0x4900], save0[0x49C1 - 0x4900])
    # `sg.position` halves the facing back to the C64's 0-3; the stored
    # byte is the C64's doubled.
    assert facing == save0[0x49C2 - 0x4900]
    assert savgam[sg.POS_FACING] == save0[0x49C2 - 0x4900] * 2
    # #67: the clock and the party size are carried, not left the template's.
    for i in range(sg.CLOCK_DIGITS):
        assert sg.word(savgam, sg.CLOCK + i) == \
            save0[sg.CLOCK + i - dos.SAVE0_BASE], i
    assert sg.party_size(savgam) == len(party) == 1
    assert sg.word(savgam, sg.PARTY_SIZE) == len(party)
    assert any("the clock" in c for c in report.carried)
    assert any("party size" in c for c in report.carried)
    # #59: the engine loads the party from these names, so they name this
    # save's own files rather than the template's.
    assert sg.character_files(savgam) == [f"CHRDATA{n}" for n in range(1, 7)]


@needs_dos_saves
def test_write_dos_save_refuses_to_write_into_the_template(tmp_path):
    save0, save1 = _fixture_payloads()
    with pytest.raises(dos.DosRecordError):
        dos.write_dos_save(save0, save1, _save_dir(), _save_dir(), "A")
    assert not list(tmp_path.iterdir())


@needs_dos_saves
def test_a_party_of_six_writes_six_characters(tmp_path):
    import pathlib

    from por.savegame import SaveGame0
    here = pathlib.Path(__file__).resolve().parent / "fixtures"
    save0 = SaveGame0.from_prg(
        (here / "party6_savedgame0.bin").read_bytes()).to_bytes()
    report = dos.write_dos_save(save0, None, _save_dir(), tmp_path, "B")
    party = dos.read_party(tmp_path, "B")
    assert len(party) == 6
    assert party[0].name == "MALCYON"
    assert (tmp_path / "SAVGAMB.DAT").exists()
    savgam = (tmp_path / "SAVGAMB.DAT").read_bytes()
    assert sg.character_files(savgam) == [f"CHRDATB{n}" for n in range(1, 7)]
    assert sg.party_size(savgam) == 6
    # This C64 party stands in New Phlan and the template's slot B in Sokol
    # Keep, so the save is retargeted -- with the empty wallset triple the
    # C64 carries for New Phlan, which draws it correctly.
    assert sg.area_id(savgam) == save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE] == 0
    assert sg.wall_triple(savgam) == (sg.EMPTY,) * 3
    assert sg.position(savgam) == (save0[0x49C0 - 0x4900],
                                   save0[0x49C1 - 0x4900],
                                   save0[0x49C2 - 0x4900])
    assert any("retargeted" in c for c in report.carried)


# --- the retarget (#60) ------------------------------------------------------

def _c64_in_the_slums() -> bytes:
    """The six-character fixture, moved into the Slums.

    A C64 save standing somewhere the DOS templates do not, built rather than
    committed: the area id at `$49F2`, the map at `$49C5` and the three
    `WALLSET` cache slots, which is everything the conversion reads to decide
    where the party is.  The numbers are PORSAVE13's, off Donald's own disk.
    """
    import pathlib

    from por.savegame import SaveGame0
    here = pathlib.Path(__file__).resolve().parent / "fixtures"
    save0 = bytearray(SaveGame0.from_prg(
        (here / "party6_savedgame0.bin").read_bytes()).to_bytes())
    save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE] = 20
    save0[dos.CURRENT_GEO - dos.SAVE0_BASE] = 20
    at = dos.FILE_CACHE[0] - dos.SAVE0_BASE + dos.CACHE_WALLSET
    save0[at:at + dos.CACHE_WALLSET_PIECES] = bytes((2, 4, 1))
    return bytes(save0)


def _game_dir():
    """The DOS game directory, which is the save directory's parent."""
    return _save_dir().parent


@needs_dos_saves
def test_a_party_from_another_area_lands_in_its_own_area(tmp_path):
    """#60, the whole point: the party ends up where it stood.

    The template stands in New Phlan and this party in the Slums, and every
    write of `dos_savegame.RETARGET_WRITES` has to land or the game exits to
    DOS with `Unable to load geo in Load3DMap.`
    """
    from por import dos_savegame

    save0 = _c64_in_the_slums()
    report = dos.write_dos_save(save0, None, _save_dir(), tmp_path, "A")
    savgam = (tmp_path / "SAVGAMA.DAT").read_bytes()
    assert sg.area_id(savgam) == 20
    assert sg.word(savgam, sg.SCRIPT) == 20
    assert sg.dax_number(savgam) == 2 == sg.word(savgam, sg.DISK)
    assert sg.wall_triple(savgam) == (2, 4, 1)
    assert [sg.word(savgam, sg.WALLMAP + i) for i in range(3)] == [1, 2, 3]
    assert sg.position(savgam) == (save0[0x49C0 - 0x4900],
                                   save0[0x49C1 - 0x4900],
                                   save0[0x49C2 - 0x4900])
    # The buffer holds the Slums' own script, not New Phlan's, and the game
    # will not load the map without it.
    script = dos_savegame.dax_block((_game_dir() / "ECL2.DAX").read_bytes(), 20)
    body = script[dos_savegame.ECL_HEADER:]
    start = dos_savegame.ECL_BUFFER[0]
    assert savgam[start:start + len(body)] == body
    assert not report.warnings or not any(
        "stand on the template's square" in w for w in report.warnings)
    assert any("retargeted" in c for c in report.carried)


@needs_dos_saves
def test_a_retarget_with_no_game_directory_keeps_the_template_s_square(
        tmp_path):
    """The script has to come from the game's own files, and if they are not
    there the honest answer is the template's square and a line saying so."""
    save0 = _c64_in_the_slums()
    empty = tmp_path / "no-game"
    empty.mkdir()
    report = dos.write_dos_save(save0, None, _save_dir(), tmp_path, "A",
                                game=empty)
    savgam = (tmp_path / "SAVGAMA.DAT").read_bytes()
    template = (_save_dir() / "SAVGAMA.DAT").read_bytes()
    assert sg.area_id(savgam) == sg.area_id(template)
    assert sg.position(savgam) == sg.position(template)
    assert any("ECL2.DAX" in w for w in report.warnings)


@pytest.mark.parametrize("area, wanted", [
    (25, "wilderness"),          # the travel grid: no DOS specimen exists
    (3, "not supported"),        # dynamic_geo -- the script picks its map
    (8, "not supported"),        # Phlan City Hall loads no map at all
    (31, "not an area"),         # no such script on any disk
])
def test_an_area_with_no_legal_answer_is_named_rather_than_guessed(area,
                                                                   wanted):
    assert wanted in dos.retarget_reason(area)


def test_the_areas_with_a_legal_answer_are_not_refused():
    """New Phlan among them: the C64 loads no WALLSET there, and a retarget
    carrying an empty triple draws it identically -- `work/p60/run3` Z0."""
    for area in (0, 20, 21):
        assert dos.retarget_reason(area) is None


# --- the character who carries nothing (#62) ---------------------------------

def _item_region(rec: bytes) -> dict[str, bytes]:
    """The three fields the sheet's weapon, damage, THAC0 and encumbrance
    lines are computed from."""
    return {n: rec[dos_layout.FIELDS_BY_NAME[n].span]
            for n in ("item_count", "item_chain", "hands_used")}


def test_a_character_who_carries_nothing_matches_the_engines_own_record():
    """#62's byte question, answered by measurement rather than by argument.

    The engine's own save of a character who dropped every item in play
    (`work/p62/truth/CHRDATD1.SAV`, the diff in `docs/50-experiments.md`)
    holds `item_count` 0, the whole 56-byte `item_chain` NULL and
    `hands_used` 0 -- which is exactly what the writer already produces.  So
    no byte of the record is wrong for an empty character, and `hands_used`,
    the issue's prime suspect, is refuted: the engine writes 2 for a fighter
    holding a weapon and 0 for the same fighter once he is empty-handed.
    """
    char = _filled()
    char.set("inventory", [], "made up: a character carrying nothing")
    rec, itm, _ = dos.write(char)
    assert itm == b""
    assert _item_region(rec) == {"item_count": b"\x00",
                                 "item_chain": bytes(56),
                                 "hands_used": b"\x00"}


@needs_dos_saves
def test_a_character_who_carries_nothing_gets_no_itm_file(tmp_path):
    """#62: an empty `.ITM` is not how the engine says "no items".

    Handed a zero-length `CHRDATA1.ITM` beside a record whose item count is
    0, DOS Pool of Radiance builds a one-item chain out of whatever the heap
    held and draws it: `WEAPON 254 PASSS`, `DAMAGE 0D8-128`, `THAC0 148`,
    `ENCUMBRANCE 60540` -- and writes the phantom into a 63-byte `.ITM` on
    the next save.  With the *same 285 record bytes* and no file at all the
    sheet is clean and the resave writes none.  Six variants in one save
    slot separated on this and nothing else (`work/p62/`, run `v1`).
    """
    save0, save1 = _fixture_payloads()
    stale = tmp_path / "CHRDATA1.ITM"
    stale.write_bytes(b"\x00" * dos_layout.ITEM_SIZE)
    dos.write_dos_save(save0, save1, _save_dir(), tmp_path, "A")
    party = dos.read_party(tmp_path, "A")
    assert party[0].get("item_count") == 0
    # Not present, and not merely empty -- and a stale one from an earlier
    # write is removed, the way the stale `.SPC` already was.
    assert not stale.exists()
