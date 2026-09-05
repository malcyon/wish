from __future__ import annotations

"""The DOS writer: a neutral character becomes a 285-byte record (#26).

The other half of `tests/test_dosconvert.py`.  That module proves the DOS
*reader* understood the file by handing the bytes back; this one proves the
*writer* is the reader's inverse, in the only form that direction can have:

* **the round trip** -- a DOS record read into the neutral middle and written
  out again is byte-for-byte the original everywhere a byte *can* survive,
  and the mask of bytes that cannot is `goldbox.dos.WRITE_UNSOURCED` -- the named
  live-heap and unattributed runs -- not whatever happened to differ;
* **nothing dropped silently** -- every neutral field has a disposition in
  the writer, every DOS layout field has a target, and every byte of both
  outputs has a provenance.

**The saves are Donald's, not the repository's** -- see `test_dossave.py`.
"""


import pytest
from test_dossave import _save_dir, needs_dos_saves
from test_neutral import _filled

from goldbox import c64_codec, dos, dos_layout, neutral
from goldbox import dos_savegame as sg
from goldbox.layout import Confidence

# --- the tables, which need no save -----------------------------------------

def test_write_targets_tile_the_dos_layout():
    """The promise the brief for #26 makes explicit: a field added to
    `goldbox/dos_layout.py` and forgotten by the writer fails here rather than
    passing in silence."""
    declared = {f.name for f in dos_layout.LAYOUT
                if not f.name.startswith("gap_")}
    assert declared - set(dos.WRITE_TARGETS) == set()
    assert set(dos.WRITE_TARGETS) - declared == set()


def test_read_targets_tile_the_c64_layout():
    """The C64 reader's layout-wide account, which #25 left to this issue: a
    field `goldbox/layout.py` names and `c64_codec.read` neither reads nor names
    as dropped would be lost in silence on the way to DOS."""
    from goldbox import layout
    known = {f.name for f in layout.LAYOUT if f.is_known}
    assert known - set(c64_codec.READ_TARGETS) == set()
    # region_220 is the combat icon, graded UNKNOWN in the layout for its
    # bytes but named by the reader as a deliberate drop.
    assert set(c64_codec.READ_TARGETS) - known == {"region_220"}


def test_every_neutral_field_has_a_write_disposition():
    """The writer's twin of `test_every_neutral_field_has_a_disposition_in_
    every_writer`: a name added to `goldbox/neutral.py`'s FIELDS and never wired
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


# --- the .SPC file: a permanent effect INNATE_EFFECTS turns away ------------
#
# #232 (An item-granted effect is dropped on the way through the neutral
# record, with no report): a `.SPC` node outside `INNATE_EFFECTS` and at
# duration zero is a ring, a girdle or a cloak the character is still
# wearing, and `granted_effects` carries the whole nine bytes of it, because
# the id alone cannot say what the ring is worth.  The engine's own test for
# "has this run out" is the duration word and nothing else
# (`docs/162-spc-permanence.md`), so a node with rounds left is a spell
# counting down and needs no report at all -- Donald, 2026-08-27.

def _dos_record(effects) -> dos.DosCharacter:
    """An all-zero 285-byte Pool of Radiance record carrying only the given
    `.SPC` nodes -- synthetic bytes, not a slice of a save."""
    return dos.DosCharacter(bytes(dos_layout.RECORD_SIZE), effects=effects)


def _effect(effect_id: int, duration: int = 0, value: int = 0xFF) -> bytes:
    """One nine-byte `.SPC` node: the id, a little-endian `u16` duration at
    byte 1, one payload byte, one more, and a NULL next pointer."""
    return (bytes((effect_id,)) + duration.to_bytes(2, "little")
            + bytes((value, 0)) + dos.EFFECT_NEXT_NULL)


def test_a_permanent_item_granted_effect_is_carried_whole():
    """A Ring of Fire Resistance, id 61, at duration zero -- the shape the
    engine wrote in front of `tools/dosspcexpiry.py` and the shape CONJURER
    carries on the Amiga -- reaches `granted_effects` with all five of its
    meaning-bearing bytes, and comes back out of the writer as the same
    record.

    The id alone would not do it: 12 is what the ring is worth, and a writer
    that put `INNATE_PAYLOAD` there instead would write `0xFF`.
    """
    node = _effect(61, duration=0, value=12)
    char = _dos_record([node])
    out = dos.to_neutral(char)
    assert [bytes(g) for g in out.get("granted_effects")] == [node]
    _rec, _itm, spc, _rep = dos.write(out)
    assert spc == node


def test_a_strength_items_own_flag_byte_survives_the_write():
    """ADDERLY's girdle: `26 00 00 5C 01`.  Byte 4 is the flag the engine
    reads when the girdle comes off -- `add_affect`'s fifth argument, not
    payload -- and byte 3 is the strength it replaced.  A writer that filled
    both from `INNATE_PAYLOAD` would write `FF 00` and leave the character
    with the girdle's strength for good.
    """
    node = bytes((38, 0, 0, 0x5C, 0x01)) + dos.EFFECT_NEXT_NULL
    _rec, _itm, spc, _rep = dos.write(dos.to_neutral(_dos_record([node])))
    assert spc == node
    assert spc[1:5] != dos.INNATE_PAYLOAD


def test_the_innate_records_come_first_and_the_granted_ones_after():
    """Both kinds in one file, each written its own way.

    The engine finds a node by walking the chain for an id and rebuilds the
    chain from the file's length, so the order is ours to choose; what must
    not happen is one kind being written with the other's four bytes.
    """
    innate = _effect(18, duration=0, value=0xFF)
    ring = _effect(61, duration=0, value=12)
    _rec, _itm, spc, _rep = dos.write(
        dos.to_neutral(_dos_record([ring, innate])))
    assert spc == innate + ring


def test_a_record_with_only_innate_ids_sets_no_granted_field():
    """A racial id -- 18, the gnome's own THAC0 bonus -- is carried in
    `innate_effects`, and the field that would make a writer explain itself
    is not set at all, so no player is told about a loss that did not
    happen."""
    char = _dos_record([_effect(18, duration=0, value=0xFF)])
    out = dos.to_neutral(char)
    assert "granted_effects" not in out
    # Compared against the same record with no `.SPC` at all rather than
    # against a phrase: "not carried" is a phrase other drop lines use for
    # their own reasons, and this test is about what the effect adds.
    assert out.dropped == dos.to_neutral(_dos_record([])).dropped


def test_a_running_spell_is_neither_carried_nor_reported():
    """Donald's 2026-08-27 ruling: a spell with rounds left was going to
    expire anyway, so it is not carried across and not put in front of the
    player either.  The engine counts a nonzero duration down and removes the
    node on the step that reaches it, so this one was on its way out.
    """
    char = _dos_record([_effect(61, duration=2, value=1)])   # BLESS's shape
    out = dos.to_neutral(char)
    assert "granted_effects" not in out
    bare = dos.to_neutral(_dos_record([]))
    assert out.dropped == bare.dropped
    _rec, rep = c64_codec.write(out)
    assert rep.dropped == c64_codec.write(bare)[1].dropped


def test_the_c64_names_the_granted_effect_it_cannot_carry():
    """The one destination that still loses a ring's effect says so, in the
    words a player reads: what the character had, and why this record has no
    room for it.

    No effect id, no file offset, no issue number -- Donald's wording,
    2026-09-04, and `tests/test_dosconvert.py`'s two developer-detail guards
    are what hold the line for the whole report.
    """
    char = _dos_record([_effect(61, duration=0, value=12)])
    _rec, rep = c64_codec.write(dos.to_neutral(char))
    lines = [d for d in rep.dropped if "Ring of Fire Resistance" in d]
    assert len(lines) == 1, rep.dropped
    assert "ten trait slots" in lines[0], lines[0]
    # The id is the player's business to never see, and `capitalize()` would
    # have rendered the effect's own name as "ring of fire resistance".
    assert "61" not in lines[0], lines[0]
    assert "ring of fire" not in lines[0], lines[0]


# --- the writer, on a synthetic character ------------------------------------

def test_a_filled_character_lands_field_for_field():
    """Every value the writer takes reads back off the DOS record through the
    DOS reader's own accessors."""
    char = _filled()
    rec, itm, _spc, rep = dos.write(char)
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
    # `_filled` carries innate effects 18 and 47 and is race 1, so a `.SPC`
    # goes beside the record: nine bytes each, id + INNATE_PAYLOAD + a NULL
    # next pointer.  90, 97 and 26 come first because a dwarf's four innate
    # ids are derived from the race byte, and 47 is already carried.
    assert _spc == b"".join(bytes((e,)) + dos.INNATE_PAYLOAD + bytes(4)
                            for e in (90, 97, 26, 18, 47))
    # And every byte of all three outputs has a provenance.
    assert rep.total == dos_layout.RECORD_SIZE + len(itm) + len(_spc)
    assert rep.unaccounted == []


def _spc_ids(spc: bytes) -> list[int]:
    """The effect ids of a `.SPC` payload, one per nine-byte record."""
    assert len(spc) % dos.EFFECT_SIZE == 0
    return [spc[n] for n in range(0, len(spc), dos.EFFECT_SIZE)]


def test_a_converted_dwarf_carries_his_constitution_bonus_to_saves():
    """#191 (A converted dwarf loses his constitution bonus to saving throws).

    The five saving-throw bytes a conversion copies are not where the DOS
    engine reads the bonus from: it recomputes all five on load out of class,
    level and the character's `.SPC` records, so a dwarf written with 26 and
    47 alone arrives three worse in every column and stays that way.  90 and
    97 have to be in the file, as the engine's own dwarf has them.
    """
    char = _filled()                        # race 1, and carrying 18 and 47
    char.set("innate_effects", [], "made up: nothing in the trait slots")
    _, _, spc, _ = dos.write(char)
    assert _spc_ids(spc) == [90, 97, 26, 47]
    # THRENDER GRONE's own file, record for record: the id, the four bytes
    # every innate specimen holds, and a NULL next pointer the loader relinks.
    assert spc == b"".join(bytes((e,)) + dos.INNATE_PAYLOAD
                           + dos.EFFECT_NEXT_NULL
                           for e in (90, 97, 26, 47))


def test_a_converted_halfling_carries_the_two_records_his_own_kind_has():
    """The halfling is the second sturdy race with a DOS specimen: PHINEAS
    carries 90 and 97 and nothing else, where the dwarf beside him carries 26
    and 47 as well.  So a converted halfling gets the constitution records
    without the dwarf's bonuses against orcs and giants."""
    char = _filled()
    char.set("race", 5, "made up: halfling")
    char.set("innate_effects", [], "made up: nothing in the trait slots")
    _, _, spc, _ = dos.write(char)
    assert _spc_ids(spc) == [90, 97]


def test_a_converted_gnome_carries_his_four_innate_records():
    """#84 (Roll a gnome in DOS and read the two innate effect ids nobody has
    seen) measured the engine writing 97, 18, 47 and 48 for a gnome, so a
    converted gnome gets the same four rather than being reported as lost."""
    char = _filled()
    char.set("race", 3, "made up: gnome")
    char.set("innate_effects", [], "made up: nothing in the trait slots")
    _, _, spc, _ = dos.write(char)
    assert _spc_ids(spc) == [97, 18, 47, 48]


def test_a_race_with_no_innate_effects_gets_no_spc_file():
    """A human carries nothing and the writer invents nothing for him: the
    three races the constitution bonus does not reach are the control on the
    two that do."""
    for race in (2, 4, 7):              # elf, half-elf, human
        char = _filled()
        char.set("race", race, "made up")
        char.set("innate_effects", [], "made up: nothing in the trait slots")
        _, _, spc, _ = dos.write(char)
        assert spc == b"", race


def _item_granted_specimen():
    """The engine-written DOS record of a readied magical item, or None.

    `$WISH_SPECIMENS`' `por-item-granted`: THRENDER GRONE's flail was given
    effect byte 61 and power byte `0x80` in a staged copy of the shipped
    party, readied through the game's own `VIEW > ITEMS > READY`, and the
    party saved to slot D **by the game**, which is what wrote the `.SPC`.
    `tools/dosspcexpiry.py ready` regenerates it in about five minutes.

    Staging the item's two bytes and then reading what the engine computed
    from them is the experiment `.claude/rules/testing.md` calls valid: the
    engine does not care how a byte got into its input.  What is being read
    back is the engine's own output.
    """
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from tools import specimens

    for entry in specimens.list_specimens():
        if entry.get("name") == "por-item-granted":
            for path in entry["_files"]:
                if path.name.endswith(".SAV"):
                    return path
    return None


def test_the_engines_own_item_granted_record_survives_the_round_trip():
    """The one DOS record anybody has that a ring's effect was written into
    by the game itself.

    Its `.SPC` is six nodes: four racial, a `BLESS` at two minutes, and
    `3D 00 00 0C 00 00 00 00 00` -- effect 61 at duration zero, the value
    `0x0C` and the removal flag clear.  The writer must hand back the four
    racial records and the ring, drop the `BLESS`, and put `0x0C` rather than
    `INNATE_PAYLOAD`'s `0xFF` in the ring's value byte.
    """
    path = _item_granted_specimen()
    if path is None:
        pytest.skip("no por-item-granted specimen; "
                    "tools/dosspcexpiry.py ready makes one")
    char = dos.read_character(path)
    nodes = [bytes(e) for e in char.effects]
    ring = [e for e in nodes if e[0] == 61]
    assert len(ring) == 1 and ring[0][:5] == bytes((61, 0, 0, 0x0C, 0)), nodes

    out = dos.to_neutral(char)
    assert [bytes(g) for g in out.get("granted_effects")] == \
        [ring[0][:5] + dos.EFFECT_NEXT_NULL]
    _rec, _itm, spc, _rep = dos.write(out)
    written = [spc[i:i + 9] for i in range(0, len(spc), 9)]
    assert [w[0] for w in written] == [90, 97, 26, 47, 61], written
    assert written[-1] == ring[0][:5] + dos.EFFECT_NEXT_NULL
    # The BLESS had two minutes left and is neither written nor reported.
    assert 1 not in [w[0] for w in written]
    # Compared against the same record with the running node taken out, so
    # the claim is "the BLESS adds nothing a player reads" rather than "no
    # line anywhere uses the words not carried", which other fields do.
    kept = [n for n in nodes if int.from_bytes(n[1:3], "little") == 0]
    without = dos.DosCharacter(bytes(char), effects=kept)
    assert _rep.dropped == dos.write(dos.to_neutral(without))[3].dropped


def test_a_value_graded_unknown_is_not_written_to_dos():
    char = _filled()
    char.set("wisdom", 9, "somewhere", Confidence.UNKNOWN)
    rec, _, _, rep = dos.write(char)
    assert rec[dos_layout.FIELDS_BY_NAME["wisdom"].offset] == 0
    assert any("wisdom" in d and "UNKNOWN" in d for d in rep.dropped)


def test_a_class_with_no_dos_slot_is_reported():
    """The knight: the one class the C64 numbers and DOS does not.  Druid and
    monk go the other way -- DOS has their slots, so they carry."""
    char = _filled()
    char.set("levels", {"fighter": 7, "knight": 2, "druid": 4}, "made up")
    rec, _, _, rep = dos.write(char)
    assert any("knight" in w for w in rep.warnings)
    raw = rec[dos_layout.FIELDS_BY_NAME["class_levels"].span]
    assert raw[2] == 7      # fighter is class number 2
    assert raw[1] == 4      # druid has a DOS slot the C64 lacks
    assert 2 not in (raw[0], raw[3], raw[4], raw[5], raw[6], raw[7])


def test_a_name_too_long_for_dos_is_truncated_and_said():
    char = _filled()
    char.set("name", "ABCDEFGHIJKLMNOPQRST", "made up",
             Confidence.CONFIRMED, neutral.Provenance.RESHAPED)
    rec, _, _, rep = dos.write(char)
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
    # A measured default is not carried either: it is what a *newly made*
    # character has, and a played one's own value differs -- 12 of the 24
    # specimens here for `icon_colours` (#112).
    for name, _, _, _ in dos.WRITE_DEFAULTS:
        f = dos_layout.FIELDS_BY_NAME[name]
        out.update(range(f.offset, f.end))
    # Nor is a byte derived from the rest of the record: `unnamed_0ab` is the
    # identity the engine draws at random, and a converted record gets a
    # digest of its own bytes rather than the source's draw (#216).
    for name, _ in dos.WRITE_DERIVED:
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


# --- the sheet portrait (#57) ------------------------------------------------
#
# The pair at 0x0BB is a **menu position** where the C64 record holds the
# art's own id, and the fourteen-and-twelve table that joins them is in both
# ports' binaries (`goldbox/portraits.py`).  These tests are what keep the
# writer from going back to zero, which is a character with no face on its
# sheet.

PORTRAIT_FIELDS = ("portrait_head", "portrait_body")


def _portrait_offsets() -> set[int]:
    out: set[int] = set()
    for name in PORTRAIT_FIELDS:
        f = dos_layout.FIELDS_BY_NAME[name]
        out.update(range(f.offset, f.end))
    return out


def _portrait_tables():
    """The creation menu out of the game directory the DOS saves sit in.

    `None` when the saves are somewhere else -- Steam redirects them out of
    the game folder -- in which case the portrait pair stays masked and the
    round trip says nothing about it, which is the honest outcome rather than
    a skip of the whole test.
    """
    from goldbox import portraits

    where = _save_dir()
    if where is None:
        return None
    for root in (where, *where.parents):
        if (root / "START.EXE").exists() and list(root.glob("HEAD[0-9].DAX")):
            try:
                return portraits.tables_from_dos(root)
            except portraits.PortraitError:
                return None
    return None


@needs_dos_saves
def test_the_portrait_pair_round_trips_when_the_menu_can_be_read():
    """DOS position -> C64 art id -> DOS position, unmasked, on every record.

    The round trip above masks `portrait_head` and `portrait_body`, because
    they are what a conversion with no game directory still writes as zero.
    This one takes the mask off and asserts the bytes themselves: 24 of 24
    come back identical, and the id in the middle is a real `HEAD<xx>` the
    C64 would load.
    """
    tables = _portrait_tables()
    if tables is None:
        pytest.skip("the DOS saves here are not beside the game's own files")
    total = 0
    for char in _records():
        original = char.to_bytes()
        neutral_char = dos.to_neutral(char, portraits=tables)
        rec, _, _, _ = dos.write(neutral_char, portraits=tables)
        for name in PORTRAIT_FIELDS:
            f = dos_layout.FIELDS_BY_NAME[name]
            assert rec[f.offset] == original[f.offset], (char.name, name)
            assert rec[f.offset] != 0, (char.name, name)
        assert neutral_char.get("portrait_head") in tables.heads
        assert neutral_char.get("portrait_body") in tables.bodies
        total += 1
    assert total >= 24


@needs_dos_saves
def test_the_portrait_is_the_only_thing_the_menu_tables_change():
    """Handing the writer the tables must not move any other byte.

    Cheap, and it is the check that would have caught a lookup wired to the
    wrong field: everything outside the pair is identical with and without
    them.

    `unnamed_0ab` moves too and has to: it is a digest of the other 284
    bytes, so a record that now carries a face is a different character to
    the engine's "already in the party" test than the faceless one (#216).
    """
    tables = _portrait_tables()
    if tables is None:
        pytest.skip("the DOS saves here are not beside the game's own files")
    identity = dos_layout.FIELDS_BY_NAME["unnamed_0ab"]
    pair = _portrait_offsets() | set(range(identity.offset, identity.end))
    for char in _records():
        without, _, _, _ = dos.write(dos.to_neutral(char))
        with_them, _, _, _ = dos.write(dos.to_neutral(char, portraits=tables),
                                       portraits=tables)
        differ = {i for i in range(len(without)) if without[i] != with_them[i]}
        assert differ <= pair, (char.name, sorted(hex(i) for i in differ))


@needs_dos_saves
def test_without_the_menu_tables_the_portrait_is_zero_and_reported():
    """The state #57 found, kept reachable and kept loud.

    A conversion that cannot read the game's own tables leaves the pair zero
    -- a sheet with no face -- and says so, rather than writing a position
    that would draw somebody else's.

    The line itself is `goldbox.dos.to_neutral`'s -- carried through from the
    read side rather than composed again here -- and since
    #244 (Every DROPPED entry's composed line carries a raw hex file offset
    in front of the player, not only the two #235 fixed) it reads in plain
    English rather than as the field's own identifier, so this checks
    `DROPPED_PLAYER_TEXT` rather than the name.
    """
    char = _records()[0]
    rec, _, _, rep = dos.write(dos.to_neutral(char))
    for name in PORTRAIT_FIELDS:
        f = dos_layout.FIELDS_BY_NAME[name]
        assert rec[f.offset] == 0, name
    text = " ".join(rep.dropped)
    assert dos.DROPPED_PLAYER_TEXT["portrait_head"] in text
    assert dos.DROPPED_PLAYER_TEXT["portrait_body"] in text


@needs_dos_saves
def test_a_portrait_outside_the_menu_is_reported_rather_than_substituted():
    """No nearest match and no default -- the standard the rest of the
    conversion is held to.

    `$67` is a real C64 `HEAD67`, and it is not one of the fourteen the
    creation menu offers, so the DOS record has no position for it.  The byte
    stays zero and the loss is named with the id in it, which is what tells
    a player which face went missing.
    """
    tables = _portrait_tables()
    if tables is None:
        pytest.skip("the DOS saves here are not beside the game's own files")
    outside = 0x67
    assert outside not in tables.heads
    char = dos.to_neutral(_records()[0], portraits=tables)
    char.set("portrait_head", outside, "made up: an NPC's own portrait")
    rec, _, _, rep = dos.write(char, portraits=tables)
    f = dos_layout.FIELDS_BY_NAME["portrait_head"]
    assert rec[f.offset] == 0
    assert any("HEAD67" in d for d in rep.dropped), rep.dropped


@needs_dos_saves
def test_a_converted_party_arrives_with_its_own_faces(tmp_path):
    """The whole of #57 from the outside: C64 save in, DOS records out.

    Every character's `portrait_head` is the position of *its own* C64
    `HEAD<xx>` in the creation menu, not zero and not one figure for
    everybody -- which is what the player sees the moment the character sheet
    opens.
    """
    from goldbox import c64_codec, portraits
    from goldbox.savegame import SaveGame0

    tables = _portrait_tables()
    if tables is None:
        pytest.skip("the DOS saves here are not beside the game's own files")
    save0, save1 = _fixture_payloads()
    dos.new_dos_save(save0, save1, tmp_path, "A", _game_dir())

    wanted = []
    for slot in SaveGame0.from_bytes(save0).characters:
        c64 = c64_codec.read(slot.record, source="fixture")
        wanted.append((tables.head_position(c64.get("portrait_head")),
                       tables.body_position(c64.get("portrait_body"))))
    wanted.reverse()          # DOS lists the party from the other end (#101)

    head = dos_layout.FIELDS_BY_NAME["portrait_head"].offset
    body = dos_layout.FIELDS_BY_NAME["portrait_body"].offset
    seen = 0
    for n, (want_head, want_body) in enumerate(wanted, start=1):
        rec = (tmp_path / f"CHRDATA{n}.SAV").read_bytes()
        assert (rec[head], rec[body]) == (want_head, want_body)
        assert rec[head] and rec[body]
        assert 1 <= rec[head] <= portraits.HEAD_COUNT
        assert 1 <= rec[body] <= portraits.BODY_COUNT
        seen += 1
    assert seen == len(wanted) >= 1


@needs_dos_saves
def test_the_saved_game_carries_the_word_the_portrait_needs(tmp_path):
    """Right records are not enough: `$49FF` has to be nonzero as well.

    Measured in DOSBox with `tools/portraitshot.py`, and it is the reason a
    converted party stayed faceless after the records were right: the same
    six records draw their portraits on the engine's own saved game and
    nothing at all on a from-nothing one, and the difference bisects to this
    one word.  Zero, no portrait; 3, the portrait; 1, the portrait.

    Asserted as the value in the file rather than as a table lookup -- a
    table entry that the writer stops reading would pass the lookup.
    """
    save0, save1 = _fixture_payloads()
    dos.new_dos_save(save0, save1, tmp_path, "A", _game_dir())
    savgam = (tmp_path / "SAVGAMA.DAT").read_bytes()
    assert sg.word(savgam, 0x49FF) == 3
    assert 0x49FF not in {a for a, _, _ in dos.SAVGAM_UNSOURCED}


@needs_dos_saves
def test_a_conversion_with_no_game_directory_says_the_faces_went(tmp_path):
    """`write_dos_save` without a game directory cannot read the menu, so it
    reports the loss on the save's own report rather than leaving a party
    silently faceless.

    Both halves are asserted, because they reach the player through different
    lists: the warning says why once, and the per-character drop names the
    `HEAD<xx>` that went.  `editor/exports.py`'s `losses` reads both.
    """
    save0, save1 = _fixture_payloads()
    report = dos.write_dos_save(save0, save1, _save_dir(), tmp_path, "A")
    assert any("portrait" in w for w in report.warnings), report.warnings
    assert any("portrait_head" in d for d in report.dropped), report.dropped
    head = dos_layout.FIELDS_BY_NAME["portrait_head"].offset
    assert (tmp_path / "CHRDATA1.SAV").read_bytes()[head] == 0


@needs_dos_saves
def test_the_written_icon_colours_are_not_zero():
    """A DOS combat icon whose six colour pairs are zero paints all six parts
    EGA 8, dark grey -- which is the combat floor's own colour, so the
    character is ~64 black outline pixels on a background of exactly its own
    shade and reads as not being there at all (#112, measured in three
    fights; the shipped default draws a person).

    The engine does not put them back: `docs/117-save-conversion.md` records
    a hand-built save loaded, re-saved from inside the game, and the game
    writing our zeros straight back.
    """
    f = dos_layout.FIELDS_BY_NAME["icon_colours"]
    for char in _records():
        rec, _, _, _ = dos.write(dos.to_neutral(char))
        assert rec[f.offset:f.end] != bytes(f.size), char.name


def test_field_10c_10f_status_active_and_quickfight_are_a_default_not_a_constant():
    """#235 (Two unattributed DOS byte ranges in the combat tail are dropped
    converting to C64, and nobody knows what they hold): the census found the
    engine writing `00 01 00 01` after a fight and `04 00 00 00` for a
    character at zero hit points, so `00 01 00 00` is not "the one value all
    specimens hold" that `WRITE_CONSTANTS`' own docstring promises -- it is
    what a freshly made character carries, the same shape as `icon_colours`.

    **Two of the four bytes are carried now and two are not**, and this is
    what pins the split. A record staged at status Unconscious with the
    active flag clear (`0x10C` = 4, `0x10D` = 0 -- the pair the engine itself
    wrote for a character it knocked out) comes back with both, because
    `to_neutral` reads them and the writer puts them back. `0x10E` is still
    UNKNOWN and `0x10F` is the quickfight flag with no named C64 field to
    have come from, so those two stay at the default and the note says so.

    Reverting `field_10c_10f` to `WRITE_CONSTANTS` still fails this: its
    provenance note there reads "in all 24 DOS specimens" and says nothing
    about status, active or quickfight, or that half the field is not
    carried. `tests/test_c64status.py` is where the carry itself is tested.
    """
    assert "field_10c_10f" not in {n for n, _, _ in dos.WRITE_CONSTANTS}
    assert "field_10c_10f" in {n for n, _, _, _ in dos.WRITE_DEFAULTS}

    f = dos_layout.FIELDS_BY_NAME["field_10c_10f"]
    raw = bytearray(dos_layout.RECORD_SIZE)
    raw[f.offset:f.end] = b"\x04\x00\x00\x00"          # status: Unconscious
    char = dos.DosCharacter(bytes(raw))
    rec, _, _, rep = dos.write(dos.to_neutral(char))
    assert rec[f.offset:f.end] == b"\x04\x00\x00\x00"
    note = rep.sources[f.offset]
    assert "Not carried" in note
    assert "unconscious" in note and "quickfight" in note

    # And a character the source says nothing about still gets the
    # fresh-character default across all four.
    bare = dos.write(neutral.NeutralCharacter("test"))[0]
    assert bare[f.offset:f.end] == b"\x00\x01\x00\x00"


def test_field_83_87_is_still_the_one_value_every_specimen_holds():
    """The other half of #235 (Two unattributed DOS byte ranges in the combat
    tail are dropped converting to C64, and nobody knows what they hold): the
    census took the corpus from 24 records to 101 and `field_83_87` never
    moved, so it stays a `WRITE_CONSTANTS` entry rather than following
    `field_10c_10f` into `WRITE_DEFAULTS` -- the note names the new count so
    the two claims are not confused."""
    consts = {n: (data, why) for n, data, why in dos.WRITE_CONSTANTS}
    assert "field_83_87" in consts
    data, why = consts["field_83_87"]
    assert data == b"\x00\x00\x01\x00\x00"
    assert "101 of 101" in why
    assert "field_83_87" not in {n for n, _, _, _ in dos.WRITE_DEFAULTS}


def test_two_characters_of_the_same_name_get_different_identity_bytes():
    """The whole of `#216 (Every converted DOS character carries the same
    identity byte at 0x0AB)`, pinned where the round trip cannot pin it.

    The engine's "is this character already in the party" test is the name
    **and** this byte, so two converted characters sharing a name were the
    same character to it and the second was silently refused -- no message,
    the entry starred as though added, the roster simply not gaining a line.
    Measured in a driven DOSBox session by `tools/dosaddchar.py`.

    `unnamed_0ab` is in `WRITE_DERIVED`, so every round-trip comparison masks
    it out.  That is correct and it means **no round-trip test can catch this
    coming back**: `identity_byte` reverted to `return 0` would restore the
    bug with the whole suite green.  This is the test that goes red instead.
    Needs no DOS save -- two neutral characters differing only in name.
    """
    f = dos_layout.FIELDS_BY_NAME["unnamed_0ab"]
    one, two = _filled(), _filled()
    made_up = "made up: two characters a player named the same thing"
    one.set("name", "DUPLICO", made_up)
    two.set("name", "DUPLICO", made_up)
    two.set("experience", one.get("experience") + 1, made_up)
    assert one.get("name") == two.get("name")
    first, _, _, _ = dos.write(one)
    second, _, _, _ = dos.write(two)
    assert first[f.offset:f.end] != second[f.offset:f.end]


def test_the_identity_byte_is_the_same_on_a_second_write():
    """A random draw would fail this, and that is why it is not one.

    Every acceptance check in this project converts a save twice and compares
    the bytes, so a byte that changed between two runs of the same conversion
    would make each of those checks fail for a reason that is not a defect.
    A digest of the other 284 bytes gives the distinctness the engine needs
    without giving up that comparison (#216).
    """
    f = dos_layout.FIELDS_BY_NAME["unnamed_0ab"]
    char = _filled()
    first, _, _, _ = dos.write(char)
    second, _, _, _ = dos.write(char)
    assert first[f.offset:f.end] == second[f.offset:f.end]


@needs_dos_saves
def test_every_shipped_record_writes_the_identity_its_own_bytes_derive():
    """On the real specimens, and distinct within each party.

    The sibling of `test_the_written_icon_colours_are_not_zero`, and asserted
    the same way: what the written byte **is**, not what a comparison masks
    out (#216).

    Deliberately not `rec[f.offset] == dos.identity_byte(rec)`, which reads
    like a stronger check and is a circular one -- `identity_byte` reverted
    to `return 0` writes 0 and recomputes 0, and the assertion passes while
    the bug is back. Nonzero and distinct are properties of the answer rather
    than of the function that produced it, and the engine needs exactly those
    two: a party of six converted characters has to be six characters to the
    "already in the party" test.

    **Distinct within a party, which is the only scope the engine compares
    in.** Across all 24 shipped records two pairs collide -- SILAS with
    RHIANNON and BRUTUS with BROTHER SEAN -- and both pairs are in different
    parties, which the "already in the party" test never puts side by side.
    Asserting global distinctness would be asserting something the fix does
    not claim and does not need.
    """
    f = dos_layout.FIELDS_BY_NAME["unnamed_0ab"]
    where = _save_dir()
    parties: dict[str, dict[int, list[str]]] = {}
    for path in sorted(where.glob("CHRDAT*.SAV")):
        if path.stat().st_size != dos_layout.RECORD_SIZE:
            continue
        char = dos.read_character(path)
        rec, _, _, _ = dos.write(dos.to_neutral(char))
        assert rec[f.offset] != 0, path.name
        # `CHRDAT<slot><n>.SAV`: the slot letter is the party.
        parties.setdefault(path.name[6], {}).setdefault(
            rec[f.offset], []).append(char.name)
    assert parties, "no CHRDAT records to check"
    for slot, seen in sorted(parties.items()):
        clash = {v: n for v, n in seen.items() if len(n) > 1}
        assert not clash, f"party {slot}: {clash}"


@needs_dos_saves
def test_a_record_round_trips_through_the_neutral_middle():
    """DOS -> to_neutral -> write, against the original bytes.  Everything
    outside the writer's own unsourced list survives byte for byte, 24 of
    24; encumbrance is recomputed and matches wherever the original's own
    identity balanced (22 of 24 -- the two stale dart stacks).

    **The `.SPC` file is now every node the engine would not expire**, innate
    and granted alike, and only a node with rounds left is left behind: 2 of
    the 24 records carry a granted node and both come back byte for byte.
    Before #232 (An item-granted effect is dropped on the way through the
    neutral record, with no report) the assertion here was the innate records
    alone.
    """
    total = enc_misses = granted = 0
    for char in _records():
        rec, itm, spc, _ = dos.write(dos.to_neutral(char))
        outside, enc = _diff_against(char, rec)
        assert outside == set(), (char.name, sorted(hex(i) for i in outside))
        enc_misses += enc
        total += 1
        # The item tails are the original's, record for record.
        for n, item in enumerate(char.items):
            ours = itm[n * 63:(n + 1) * 63]
            assert ours[0x02E:] == item.to_bytes()[0x02E:], (char.name, n)
        # The `.SPC` is the original's permanent records with the next
        # pointers NULLed -- which is also the claim that every innate record
        # in the player's own saves carries `INNATE_PAYLOAD` in bytes 1-4.
        innate = [e for e in char.effects if e[0] in dos.INNATE_EFFECTS]
        kept = [e for e in char.effects
                if e[0] not in dos.INNATE_EFFECTS
                and int.from_bytes(e[1:3], "little") == 0]
        granted += bool(kept)
        assert spc == b"".join(e[:5] + bytes(4) for e in innate + kept), \
            char.name
        for e in innate:
            assert e[1:5] == dos.INNATE_PAYLOAD, (char.name, e.hex())
    assert total >= 24
    assert enc_misses <= 2, f"{enc_misses} encumbrance misses of {total}"
    assert granted, "no record here carries a permanent non-innate effect"


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
        rec, _, _, _ = dos.write(back)
        outside, _ = _diff_against(char, rec)
        assert outside == set(), (char.name, sorted(hex(i) for i in outside))
        total += 1
    assert total >= 24


@needs_dos_saves
def test_the_write_report_accounts_for_every_byte():
    for char in _records():
        _, _, _, rep = dos.write(dos.to_neutral(char))
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

    from goldbox.encoding import COMBAT_BIAS
    from goldbox.savegame import SaveGame0, SaveGame1
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
    rec, _, _, _ = dos.write(char)
    assert rec[dos_layout.FIELDS_BY_NAME["armour_class"].offset] == \
        COMBAT_BIAS - block.armour_class


# --- the whole save, C64 payloads to DOS files -------------------------------

def _fixture_payloads():
    import pathlib

    from goldbox.savegame import SaveGame0, SaveGame1
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

    from goldbox.savegame import SaveGame0
    here = pathlib.Path(__file__).resolve().parent / "fixtures"
    save0 = SaveGame0.from_prg(
        (here / "party6_savedgame0.bin").read_bytes()).to_bytes()
    report = dos.write_dos_save(save0, None, _save_dir(), tmp_path, "B")
    party = dos.read_party(tmp_path, "B")
    assert len(party) == 6
    # **The file order is the reverse of the C64 slot order** (#101): the C64
    # lists the party from the highest slot down and DOS from `CHRDATB1` up,
    # so MALCYON in slot 0 is the C64's *last* and has to be DOS's last too.
    from goldbox.savegame import SaveGame0 as _SG0
    slots = [s.record.name for s in _SG0.from_bytes(save0).slots if s.occupied]
    assert slots == ["MALCYON", "LADY KATHERINE", "ROLAND", "SILAS",
                     "MAGNUS", "BRUTUS"]
    assert [c.name for c in party] == slots[::-1]
    assert [c.get("party_order") for c in party] == [0, 1, 2, 3, 4, 5]
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
    assert any(c.startswith("the place: area") for c in report.carried)


@needs_dos_saves
def test_the_racial_bonuses_arrive_as_a_spc_file(tmp_path):
    """#61: an elf's sleep resistance is not a spell buff and is carried.

    DOS does not re-derive these from race and constitution -- measured under
    DOSBox-X, `docs/117-save-conversion.md` -- so without the file the elf
    arrives with nothing.  The party of six has an elf, a half-elf and a
    dwarf; the three humans have no innate effect and so get no file at all,
    which is the state the engine's own save writes.

    The dwarf is the case the C64 record cannot answer on its own: it holds no
    trait id for him at all, because the C64 works his bonus against orcs out
    when the blow lands and keeps his constitution bonus to saving throws
    inside the five stored saves.  `RACE_COMBAT_EFFECTS` is where all four of
    his come from.
    """
    import pathlib

    from goldbox.savegame import SaveGame0
    here = pathlib.Path(__file__).resolve().parent / "fixtures"
    save0 = SaveGame0.from_prg(
        (here / "party6_savedgame0.bin").read_bytes()).to_bytes()
    dos.write_dos_save(save0, None, _save_dir(), tmp_path, "B")

    party = dos.read_party(tmp_path, "B")
    # The party arrives reversed (#101), so the elf and the half-elf are the
    # last two files rather than the first two. Keyed by name so the test is
    # about the effects rather than about the ordering.
    by_name = {c.name: c for c in party}
    assert [c.name for c in party][-2:] == ["LADY KATHERINE", "MALCYON"]
    assert by_name["MALCYON"].effect_ids == [107]   # elf sleep/charm resistance
    assert by_name["LADY KATHERINE"].effect_ids == [124]      # the half-elf's
    elf = party.index(by_name["MALCYON"]) + 1
    assert (tmp_path / f"CHRDATB{elf}.SPC").read_bytes() == \
        bytes((107,)) + dos.INNATE_PAYLOAD + dos.EFFECT_NEXT_NULL
    # MAGNUS the dwarf: 90 and 97 for the constitution bonus to saving throws,
    # 26 against orcs and 47 against giants, all four from the race byte.  The
    # C64 spends the constitution bonus inside the five saving-throw bytes,
    # but the DOS engine recomputes those on load and reads the bonus out of
    # these records instead -- #191 (A converted dwarf loses his constitution
    # bonus to saving throws).
    assert by_name["MAGNUS"].effect_ids == [90, 97, 26, 47]
    # The three humans carry nothing, and an empty file is not how the engine
    # says so.
    for who in ("BRUTUS", "SILAS", "ROLAND"):
        assert by_name[who].effect_ids == []
        n = party.index(by_name[who]) + 1
        assert not (tmp_path / f"CHRDATB{n}.SPC").exists()


@needs_dos_saves
def test_a_second_conversion_replaces_the_slot_rather_than_overlaying_it(
        tmp_path):
    """#68: a party of one into a folder that held six is a party of one.

    The engine loads the party from the six `CHRDAT<slot><n>` filenames in
    `SAVGAM<slot>.DAT` (#59), so a leftover `CHRDATB2`-`6` is not inert: it is
    five strangers marching with the converted character.
    """
    import pathlib

    from goldbox.savegame import SaveGame0
    here = pathlib.Path(__file__).resolve().parent / "fixtures"
    six = SaveGame0.from_prg(
        (here / "party6_savedgame0.bin").read_bytes()).to_bytes()
    dos.write_dos_save(six, None, _save_dir(), tmp_path, "B")
    assert len(dos.read_party(tmp_path, "B")) == 6

    save0, save1 = _fixture_payloads()
    report = dos.write_dos_save(save0, save1, _save_dir(), tmp_path, "B")
    assert [c.name for c in dos.read_party(tmp_path, "B")] == ["BRUTUS"]
    for n in range(2, 7):
        for suffix in (".SAV", ".ITM", ".SPC"):
            assert not (tmp_path / f"CHRDATB{n}{suffix}").exists()
    assert any("removed" in c for c in report.carried)


@needs_dos_saves
def test_clearing_a_slot_leaves_the_other_slots_and_the_user_s_files(tmp_path):
    """Only the eighteen names the engine reads for this slot are removed."""
    save0, save1 = _fixture_payloads()
    keep = {
        tmp_path / "CHRDATA1.SAV": b"another slot",
        tmp_path / "SAVGAMA.DAT": b"another slot's save",
        tmp_path / "CHRDATB7.SAV": b"not a name the engine reads",
        tmp_path / "notes.txt": b"the user's own file",
    }
    for path, body in keep.items():
        path.write_bytes(body)
    dos.write_dos_save(save0, save1, _save_dir(), tmp_path, "B")
    for path, body in keep.items():
        assert path.read_bytes() == body, path.name


@needs_dos_saves
def test_a_conversion_that_cannot_read_its_template_clears_nothing(tmp_path):
    """The slot survives a failure: nothing in `out` is touched until the
    template's `SAVGAM<slot>.DAT` has been read."""
    import pathlib

    from goldbox.savegame import SaveGame0
    here = pathlib.Path(__file__).resolve().parent / "fixtures"
    six = SaveGame0.from_prg(
        (here / "party6_savedgame0.bin").read_bytes()).to_bytes()
    dos.write_dos_save(six, None, _save_dir(), tmp_path, "B")

    empty = tmp_path / "no-template"
    empty.mkdir()
    save0, save1 = _fixture_payloads()
    with pytest.raises(FileNotFoundError):
        dos.write_dos_save(save0, save1, empty, tmp_path, "B")
    assert len(dos.read_party(tmp_path, "B")) == 6


# --- the retarget (#60) ------------------------------------------------------

def _c64_in_the_slums() -> bytes:
    """The six-character fixture, moved into the Slums.

    A C64 save standing somewhere the DOS templates do not, built rather than
    committed: the area id at `$49F2`, the map at `$49C5` and the three
    `WALLSET` cache slots, which is everything the conversion reads to decide
    where the party is.  The numbers are PORSAVE13's, off Donald's own disk.
    """
    import pathlib

    from goldbox.savegame import SaveGame0
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
    from goldbox import dos_savegame

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
    assert any(c.startswith("the place: area") for c in report.carried)


@needs_dos_saves
def test_a_conversion_with_no_game_files_refuses_rather_than_borrowing_an_area(
        tmp_path):
    """With no `ECL<n>.DAX` the party's own area cannot be staged, and the
    only other answer is the area somebody else's save was made in.

    This used to leave the party on the template's square with a warning, and
    a warning is not enough: the file loads, the party is standing somewhere
    it has never been, and nothing about the run says so.  Donald's ruling in
    the other direction, 2026-08-27, is the same question -- *"We should
    never attempt to write a save file if we don't have the game disks and we
    need them.  That would mean making up data, which we will not do."*
    """
    save0 = _c64_in_the_slums()
    empty = tmp_path / "no-game"
    empty.mkdir()
    with pytest.raises(dos.DosRecordError) as e:
        dos.write_dos_save(save0, None, _save_dir(), tmp_path / "out", "A",
                           game=empty)
    assert "ECL2.DAX" in str(e.value)
    # And nothing was written, so a slot the conversion refuses is a slot the
    # previous conversion left alone.
    assert not (tmp_path / "out" / "SAVGAMA.DAT").exists()


@pytest.mark.parametrize("area, wanted", [
    (3, "not supported"),        # dynamic_geo -- the script picks its map
    (8, "not supported"),        # Phlan City Hall loads no map at all
    (31, "not an area"),         # no such script on any disk
])
def test_an_area_with_no_legal_answer_is_named_rather_than_guessed(area,
                                                                   wanted):
    assert wanted in dos.retarget_reason(area)


def test_the_areas_with_a_legal_answer_are_not_refused():
    """New Phlan among them: the C64 loads no WALLSET there, and a retarget
    carrying an empty triple draws it identically -- `work/p60/run3` Z0.

    The three travel windows joined the list in #190, once an outdoor DOS
    retarget had been driven; `tests/test_dosoutdoorwrite.py` is where the
    outdoor write path is held to what an engine-written overland save holds.
    """
    for area in (0, 20, 21, 25, 26, 27):
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
    rec, itm, _, _ = dos.write(char)
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

# --- what the clear may and may not reach ------------------------------------


@pytest.mark.parametrize("slot", ["../../evil", "AB", "", "1", "a/b", "."])
def test_a_slot_that_is_not_one_letter_is_refused(slot, tmp_path):
    """`slot` is interpolated into the paths this function unlinks.

    `pathlib`'s `/` splits an embedded separator into components, so
    `out / "CHRDAT../../../x1"` resolves outside `out` and the clear would
    delete a file that is nobody's business. The engine's own slots are a
    single letter, so the check costs nothing -- and it closes the
    case-mismatch with it, since the save is written with `slot.upper()`
    while the files on disk take `slot` verbatim.
    """
    save0, save1 = _fixture_payloads()
    with pytest.raises(dos.DosRecordError) as caught:
        dos.write_dos_save(save0, save1, tmp_path, tmp_path / "out", slot)
    assert "single letter" in str(caught.value)


@needs_dos_saves
def test_a_character_that_cannot_be_written_leaves_the_slot_alone(
        tmp_path, monkeypatch):
    """The clear runs for the whole slot; the writes run per character.

    So a `write()` that raises partway through the party used to leave
    characters 1..N-1 replaced, N..6 deleted, and `SAVGAM<slot>.DAT` still
    naming all six -- a save pointing at files that are not there, which is
    #68's fault reached through the write path instead of the leftover path.
    Everything is converted before anything is unlinked.
    """
    save0, save1 = _fixture_payloads()
    dos.write_dos_save(save0, save1, _save_dir(), tmp_path, "A")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert before, "the first conversion must have written something"

    def boom(char, portraits=None):
        raise dos.DosRecordError("this character will not encode")

    monkeypatch.setattr(dos, "write", boom)
    with pytest.raises(dos.DosRecordError):
        dos.write_dos_save(save0, save1, _save_dir(), tmp_path, "A")
    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert after == before


@needs_dos_saves
def test_the_script_scratch_is_the_c64s_and_not_the_templates(tmp_path):
    """`$49EB` and `$4A00`-`$4A1F` convert the way the quest flags do (#59).

    Both are CONFIRMED the same field on both ports in
    `docs/141-dos-savegame.md`, and before this they were inherited: the DOS
    save came up holding whichever party's script scratch the template
    directory belonged to. The values here are a sentinel no real save holds,
    so the test says nothing about what the words mean -- only where they
    came from.
    """
    save0, save1 = _fixture_payloads()
    save0 = bytearray(save0)
    before = {a: sg.word((_save_dir() / "SAVGAMA.DAT").read_bytes(), a)
              for a in dos.SHARED_SCRATCH}
    for n, addr in enumerate(dos.SHARED_SCRATCH):
        save0[addr - dos.SAVE0_BASE] = (n * 7 + 3) & 0xFF
    dos.write_dos_save(bytes(save0), save1, _save_dir(), tmp_path, "A")
    savgam = (tmp_path / "SAVGAMA.DAT").read_bytes()
    for n, addr in enumerate(dos.SHARED_SCRATCH):
        assert sg.word(savgam, addr) == (n * 7 + 3) & 0xFF, hex(addr)
    # And the template did not already hold them, so this cannot pass by
    # accident: at least one address moved.
    assert any(sg.word(savgam, a) != before[a] for a in dos.SHARED_SCRATCH)
    assert len(dos.SHARED_SCRATCH) == 33     # $49EB plus the 32-word window


# --- the whole saved game, from nothing (#26) --------------------------------
#
# `write_dos_save` used to copy an existing `SAVGAM<slot>.DAT` and rewrite the
# fields it could source, so every byte nobody had decoded kept a value
# belonging to **a different party in a different place**.  These are the
# tests of the other shape: 13137 zero bytes, and every one of them written
# from the C64 party, written to a measured constant, or written zero with the
# reason it is nobody's.  The proof that the zeroes are survivable is not here
# -- it is `tools/dosnewsave.py`, whose party loads, walks, changes area and
# is saved back by the engine's own ENCAMP > SAVE.


@needs_dos_saves
def test_a_saved_game_built_from_nothing_accounts_for_every_byte(tmp_path):
    """`unwritten` empty is what "no template" means, checkably."""
    save0, save1 = _fixture_payloads()
    report = dos.new_dos_save(save0, save1, tmp_path, "A", _game_dir())
    assert report.unwritten == []
    assert len(report.sources) == report.total == sg.SAVGAM_SIZE
    savgam = (tmp_path / "SAVGAMA.DAT").read_bytes()
    # And it is the party's own save rather than a plausible-looking one.
    assert sg.character_files(savgam) == [f"CHRDATA{n}" for n in range(1, 7)]
    assert sg.party_size(savgam) == 1
    assert sg.area_id(savgam) == save0[dos.CURRENT_SCRIPT - dos.SAVE0_BASE]
    for i in range(sg.CLOCK_DIGITS):
        assert sg.word(savgam, sg.CLOCK + i) == \
            save0[sg.CLOCK + i - dos.SAVE0_BASE], i


@needs_dos_saves
def test_a_saved_game_built_on_a_template_counts_what_it_took_from_it(
        tmp_path):
    """The template path still exists for an experiment, and it says how much
    of the file is somebody else's -- which is the number this issue is
    about.  A template that supplied a byte in silence is what the count
    exists to prevent."""
    save0, save1 = _fixture_payloads()
    report = dos.write_dos_save(save0, save1, _save_dir(), tmp_path, "A",
                                game=_game_dir())
    assert report.unwritten, "a template save is not written byte for byte"
    # `sources` covers every offset after the backfill loop, so
    # `len(unwritten) == SAVGAM_SIZE - (len(sources) - len(unwritten))`
    # reduces to `len(sources) == SAVGAM_SIZE` and is true whatever the
    # template supplied. It was asserted here until 2026-09-02 and tested
    # nothing. What does the work is comparing the two paths: the same party
    # written from nothing owes a stranger no bytes at all.
    assert len(report.sources) == sg.SAVGAM_SIZE
    scratch = tmp_path / "nothing"
    fresh = dos.new_dos_save(save0, save1, scratch, "A", _game_dir())
    assert not fresh.unwritten
    assert len(report.unwritten) > len(fresh.unwritten), (
        "converting onto a template took no more from it than converting "
        "from nothing did, which cannot be true while the template path "
        "exists at all")
    # Every one of them is a variable or a tail byte, addressed the way a
    # reader of `docs/141-dos-savegame.md` would look it up.
    assert report.address(report.unwritten[0]).startswith(("$", "byte "))


@needs_dos_saves
def test_new_dos_save_refuses_a_byte_it_did_not_write(tmp_path, monkeypatch):
    """The gate has to be able to fail, or it is not a gate.

    With the zero account taken away the same conversion leaves 4854 bytes
    with no source, and `new_dos_save` refuses rather than handing back a
    file whose zeroes nobody stands behind.
    """
    save0, save1 = _fixture_payloads()
    monkeypatch.setattr(dos, "savgam_zeroes", lambda savgam, report: None)
    with pytest.raises(dos.DosRecordError) as e:
        dos.new_dos_save(save0, save1, tmp_path, "A", _game_dir())
    assert "no source" in str(e.value)


@needs_dos_saves
def test_a_refused_conversion_leaves_the_directory_exactly_as_it_found_it(
        tmp_path, monkeypatch):
    """A refusal that has already written the file it refuses is not a
    refusal.

    `new_dos_save` can only know the count at the end, so it used to clear the
    slot, write all seven files, and raise afterwards -- leaving the caller
    with precisely the save the refusal exists to prevent, and nothing about
    the directory saying so. The previous party's files were gone too.
    """
    save0, save1 = _fixture_payloads()
    out = tmp_path / "out"
    out.mkdir()
    # A previous conversion's slot, which a refusal must not disturb either.
    keep = out / "CHRDATA1.SAV"
    keep.write_bytes(b"the party that was already here")
    before = sorted(p.name for p in out.iterdir())

    monkeypatch.setattr(dos, "savgam_zeroes", lambda savgam, report: None)
    with pytest.raises(dos.DosRecordError):
        dos.new_dos_save(save0, save1, out, "A", _game_dir())

    assert not (out / "SAVGAMA.DAT").exists(), \
        "the saved game it refused was written anyway"
    assert sorted(p.name for p in out.iterdir()) == before, \
        "the refusal changed the directory"
    assert keep.read_bytes() == b"the party that was already here", \
        "the refusal cleared the slot it refused to replace"


@needs_dos_saves
def test_every_nonzero_word_a_real_saved_game_holds_is_written_or_declared():
    """A field the engine writes that this conversion neither sources nor
    names is the failure this test exists for: it would be written zero in
    silence, and a zero nobody decided on is indistinguishable in the file
    from one that was measured.

    Measured over every genuine Pool of Radiance container in the player's
    own DOS save directory.
    """
    written = set(range(dos.FLAGS_FIRST, dos.FLAGS_LAST + 1))
    written |= set(dos.SHARED_SCRATCH)
    written |= set(range(sg.CLOCK, sg.CLOCK + sg.CLOCK_DIGITS))
    written |= {sg.AREA, sg.SCRIPT, sg.DISK, sg.INDOORS, sg.PARTY_SIZE,
                sg.TRAVEL_X, sg.TRAVEL_Y}
    written |= set(range(sg.WALLSET, sg.WALLSET + 3))
    written |= set(range(sg.WALLMAP, sg.WALLMAP + 3))
    written |= {a for a, _, _ in sg.SAVGAM_CONSTANTS}
    written |= {a for a, _, _ in dos.SAVGAM_MEASURED}
    declared = {a + i for a, n, _ in dos.SAVGAM_UNSOURCED for i in range(n)}

    saves = sorted(_save_dir().glob("SAVGAM?.DAT"))
    assert saves, "the save directory holds no SAVGAM<slot>.DAT"
    seen = 0
    for path in saves:
        data = path.read_bytes()
        if len(data) != sg.SAVGAM_SIZE:
            continue
        seen += 1
        for addr in range(sg.VAR_BASE, sg.VAR_LAST + 1):
            if sg.word(data, addr) and addr not in written | declared:
                raise AssertionError(
                    f"{path.name} holds {sg.word(data, addr)} at ${addr:04X}, "
                    f"which the conversion neither writes nor declares")
    assert seen >= 2, f"only {seen} Pool of Radiance containers were read"


def test_the_unsourced_words_are_addresses_and_do_not_overlap():
    """A table that names the same word twice, or one outside the array, is a
    table whose count is wrong -- and the count is the claim."""
    seen = set()
    for address, words, why in dos.SAVGAM_UNSOURCED:
        assert why.strip(), hex(address)
        for a in range(address, address + words):
            assert sg.VAR_BASE <= a <= sg.VAR_LAST, hex(a)
            assert a not in seen, hex(a)
            seen.add(a)
    # 508 bytes of variables carry a stated reason for their zero, and 274
    # more are the character table's heap scratch and the menu text after it.
    # Only 178 of the 508 have ever been seen holding anything in a container
    # on this machine -- the rest is the message buffer's own tail, declared
    # whole because it is one buffer and not 217 findings, and $507A-$507C,
    # which #59 named live off specimens that no longer exist.
    #
    # It was 510 until #57: `$49FF` left this table for `SAVGAM_MEASURED`,
    # because zero there is what stopped the sheet portrait being drawn at
    # all, so it is a word the conversion writes rather than one it cannot
    # source.
    assert 2 * len(seen) == 508
    assert (sg.PARTY_ENTRIES * (sg.PARTY_ENTRY - sg.PARTY_NAME_LEN)
            + sg.UI_SCRATCH) == 274
