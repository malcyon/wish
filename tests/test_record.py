from __future__ import annotations

"""Tests for the character-record decoding layer.

The specimen is ``tests/fixtures/brutus.chr``: a 582-byte PRG (2-byte load
address $6B00 + 580-byte record) holding a fighter named BRUTUS.
"""


import pathlib

import pytest

from goldbox import layout, petscii
from goldbox.record import (
    CharacterRecord,
    RecordSizeError,
    add_load_address,
    strip_load_address,
)

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "brutus.chr"


@pytest.fixture(scope="module")
def prg_bytes() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture
def record_bytes(prg_bytes: bytes) -> bytes:
    return strip_load_address(prg_bytes)


@pytest.fixture
def brutus(record_bytes: bytes) -> CharacterRecord:
    return CharacterRecord(record_bytes)


# ---------------------------------------------------------------------------
# 1. Decoding the specimen
# ---------------------------------------------------------------------------
def test_fixture_shape(prg_bytes: bytes) -> None:
    assert len(prg_bytes) == layout.PRG_SIZE == 582
    assert prg_bytes[0] | (prg_bytes[1] << 8) == layout.LOAD_ADDRESS == 0x6B00


def test_decodes_confirmed_fields(brutus: CharacterRecord) -> None:
    assert brutus.name == "BRUTUS"
    assert brutus.strength == 18
    assert brutus.intelligence == 16
    assert brutus.wisdom == 13
    assert brutus.dexterity == 14
    assert brutus.constitution == 16
    assert brutus.charisma == 13
    assert brutus.exceptional_strength == 98


def test_from_prg_matches_manual_strip(prg_bytes: bytes, record_bytes: bytes) -> None:
    assert CharacterRecord.from_prg(prg_bytes).to_bytes() == record_bytes


def test_generic_accessors_agree_with_attributes(brutus: CharacterRecord) -> None:
    assert brutus.get("strength") == brutus.strength
    assert brutus.get_raw("strength") == bytes([18])
    assert brutus.to_dict()["exceptional_strength"] == 98


# ---------------------------------------------------------------------------
# 2. Byte-exact round trip
# ---------------------------------------------------------------------------
def test_round_trip_is_byte_exact(record_bytes: bytes) -> None:
    assert CharacterRecord(record_bytes).to_bytes() == record_bytes


def test_prg_round_trip_is_byte_exact(prg_bytes: bytes) -> None:
    assert CharacterRecord.from_prg(prg_bytes).to_prg() == prg_bytes


def test_round_trip_survives_reading_every_field(record_bytes: bytes) -> None:
    rec = CharacterRecord(record_bytes)
    for field, _value in rec.fields():  # touch every byte through the layout
        assert len(rec.get_raw(field.name)) == field.size
    assert rec.to_bytes() == record_bytes


def test_round_trip_of_arbitrary_bytes() -> None:
    noise = bytes((i * 37 + 11) & 0xFF for i in range(layout.RECORD_SIZE))
    assert CharacterRecord(noise).to_bytes() == noise


# ---------------------------------------------------------------------------
# 3. Mutation touches only the field's own bytes  (the important one)
# ---------------------------------------------------------------------------
def _assert_only_field_changed(
    before: bytes, after: bytes, field_name: str, expected: bytes
) -> None:
    field = layout.field_by_name(field_name)
    assert len(after) == len(before) == layout.RECORD_SIZE
    assert after[field.span] == expected, f"{field_name} did not take the new value"
    for i in range(layout.RECORD_SIZE):
        if field.offset <= i < field.end:
            continue
        assert after[i] == before[i], (
            f"byte {i:#05x} changed from {before[i]:#04x} to {after[i]:#04x} "
            f"while writing {field_name!r}"
        )


@pytest.mark.parametrize(
    "field_name,value,expected",
    [
        ("strength", 17, bytes([17])),
        ("intelligence", 3, bytes([3])),
        ("wisdom", 255, bytes([255])),
        ("dexterity", 0, bytes([0])),
        ("constitution", 9, bytes([9])),
        ("charisma", 12, bytes([12])),
        ("exceptional_strength", 0, bytes([0])),
        ("exceptional_strength", 100, bytes([100])),
    ],
)
def test_setting_a_field_changes_only_that_field(
    record_bytes: bytes, field_name: str, value: int, expected: bytes
) -> None:
    rec = CharacterRecord(record_bytes)
    setattr(rec, field_name, value)
    _assert_only_field_changed(record_bytes, rec.to_bytes(), field_name, expected)


def test_setting_name_changes_only_the_name_field(record_bytes: bytes) -> None:
    rec = CharacterRecord(record_bytes)
    rec.name = "ALIAS"
    _assert_only_field_changed(
        record_bytes,
        rec.to_bytes(),
        "name",
        petscii.encode_record_name("ALIAS"),
    )
    assert rec.name == "ALIAS"


def test_setting_an_unknown_region_changes_only_that_region(
    record_bytes: bytes,
) -> None:
    rec = CharacterRecord(record_bytes)
    field = layout.field_by_name("region_220")
    payload = bytes([0x5A]) * field.size
    rec.set_raw("region_220", payload)
    _assert_only_field_changed(record_bytes, rec.to_bytes(), "region_220", payload)


def test_writing_the_same_value_is_a_no_op(record_bytes: bytes) -> None:
    rec = CharacterRecord(record_bytes)
    rec.strength = rec.strength
    rec.name = rec.name
    assert rec.to_bytes() == record_bytes


def test_diff_reports_exactly_the_changed_byte(record_bytes: bytes) -> None:
    rec = CharacterRecord(record_bytes)
    rec.charisma = 7
    assert rec.diff(record_bytes) == [(0x19, 7, 13)]


def test_out_of_range_field_value_rejected(brutus: CharacterRecord) -> None:
    with pytest.raises(ValueError):
        brutus.strength = 256
    with pytest.raises(ValueError):
        brutus.strength = -1
    with pytest.raises(ValueError):
        brutus.set_raw("attack_forms", b"\x00\x00")


# ---------------------------------------------------------------------------
# 4. Length validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("size", [0, 1, 579, 581, 582, 1024])
def test_wrong_length_raises(size: int) -> None:
    with pytest.raises(RecordSizeError):
        CharacterRecord(bytes(size))


def test_wrong_length_error_is_a_value_error() -> None:
    assert issubclass(RecordSizeError, ValueError)


def test_prg_length_hint_mentions_from_prg() -> None:
    with pytest.raises(RecordSizeError, match="from_prg"):
        CharacterRecord(bytes(layout.PRG_SIZE))


def test_strip_load_address_validates(prg_bytes: bytes) -> None:
    with pytest.raises(RecordSizeError):
        strip_load_address(prg_bytes[:-1])
    with pytest.raises(ValueError, match="load address"):
        strip_load_address(b"\x00\x00" + prg_bytes[2:])
    # the check can be waived deliberately
    assert len(strip_load_address(b"\x00\x00" + prg_bytes[2:], expected=None)) == 580


def test_add_load_address_validates(record_bytes: bytes) -> None:
    assert add_load_address(record_bytes)[:2] == b"\x00\x6b"
    with pytest.raises(RecordSizeError):
        add_load_address(record_bytes[:-1])


def test_unknown_field_name_raises(brutus: CharacterRecord) -> None:
    with pytest.raises(KeyError):
        brutus.get("class_")


# ---------------------------------------------------------------------------
# 5. Name encoding / decoding
# ---------------------------------------------------------------------------
def test_record_name_padding(record_bytes: bytes) -> None:
    raw = record_bytes[: petscii.RECORD_NAME_SIZE]
    assert raw == b"BRUTUS" + b"\x00" * 14
    assert petscii.decode_record_name(raw) == "BRUTUS"
    assert petscii.encode_record_name("BRUTUS") == raw


@pytest.mark.parametrize("name", ["", "A", "BRUTUS", "ABCDEFGHIJKLMNOPQRST"])
def test_record_name_round_trip(name: str) -> None:
    encoded = petscii.encode_record_name(name)
    assert len(encoded) == petscii.RECORD_NAME_SIZE
    assert petscii.decode_record_name(encoded) == name
    assert petscii.is_canonical_record_name(encoded)


def test_record_name_too_long_raises() -> None:
    with pytest.raises(ValueError):
        petscii.encode_record_name("A" * (petscii.RECORD_NAME_SIZE + 1))


def test_record_name_rejects_non_ascii() -> None:
    with pytest.raises(ValueError):
        petscii.encode_record_name("BRUTÖS")


def test_a_lowercase_record_name_is_folded_to_capitals() -> None:
    """`#290`: the C64 draws its text in the uppercase/graphics character
    set, where a lower-case letter's screen code lands in the symbol range --
    watched on the running machine, `Guy de Valois ` drew as
    `G59 $% V!,/)3`. `goldbox.dos.c64_name` folded this for the DOS-to-C64
    path only; this is the encoder every route into a C64 record's name
    field ends at, so the fold belongs here.
    """
    encoded = petscii.encode_record_name("Guy de Valois ")
    assert encoded == b"GUY DE VALOIS" + b"\x00" * 7


def test_a_record_name_fold_leaves_punctuation_and_digits_alone() -> None:
    """Only case and trailing blanks move; everything else crosses as is."""
    assert petscii.encode_record_name("O'malley") == \
        petscii.encode_record_name("O'MALLEY")
    assert petscii.encode_record_name("abc-123") == \
        petscii.encode_record_name("ABC-123")


def test_a_folded_record_name_is_not_canonical() -> None:
    """A raw field holding lower-case letters would be rewritten on the next
    save, so it does not round-trip through the text form unchanged."""
    raw = b"guy" + b"\x00" * 17
    assert petscii.decode_record_name(raw) == "guy"
    assert not petscii.is_canonical_record_name(raw)


def test_record_name_stops_at_first_nul() -> None:
    assert petscii.decode_record_name(b"AB\x00CD" + b"\x00" * 15) == "AB"
    # ...which is exactly why such a field is not canonical and must not be
    # rewritten from its text form.
    assert not petscii.is_canonical_record_name(b"AB\x00CD" + b"\x00" * 15)


def test_short_name_written_into_record_is_nul_padded(record_bytes: bytes) -> None:
    rec = CharacterRecord(record_bytes)
    rec.name = "AL"
    assert rec.get_raw("name") == b"AL" + b"\x00" * 18


def test_a_renamed_record_folds_a_lowercase_name(record_bytes: bytes) -> None:
    """`#290`'s editor route: `editor/window.py`'s rename field sets
    `record.name` directly, never going through `goldbox.c64_codec.write` --
    so the fold has to hold here too, not only for a freshly-converted
    record."""
    rec = CharacterRecord(record_bytes)
    rec.name = "guy"
    assert rec.name == "GUY"
    assert rec.get_raw("name") == b"GUY" + b"\x00" * 17


def test_directory_names_are_a_separate_convention() -> None:
    raw = petscii.encode_directory_name("POOL DATA")
    assert len(raw) == petscii.DIR_NAME_SIZE
    assert raw == b"POOL DATA" + b"\xa0" * 7
    assert petscii.decode_directory_name(raw) == "POOL DATA"


def test_directory_name_leading_control_byte_is_dropped() -> None:
    raw = petscii.encode_directory_name("SAVE", leading_control=True)
    assert raw[0] == petscii.DIR_NAME_CONTROL
    assert petscii.decode_directory_name(raw) == "SAVE"
    assert petscii.decode_directory_name(raw, keep_control=True).startswith(
        petscii.SUBSTITUTE
    )


def test_directory_name_shifted_letters_decode() -> None:
    assert petscii.decode_directory_name(bytes([0xC1, 0xC2]) + b"\xa0" * 14) == "AB"


def test_directory_name_too_long_raises() -> None:
    with pytest.raises(ValueError):
        petscii.encode_directory_name("X" * (petscii.DIR_NAME_SIZE + 1))


# ---------------------------------------------------------------------------
# Layout invariants
# ---------------------------------------------------------------------------
def test_layout_tiles_the_record_without_gaps_or_overlap() -> None:
    cursor = 0
    for f in layout.iter_fields():
        assert f.offset == cursor, f"{f.name} does not start where the last ended"
        assert f.size > 0
        cursor = f.end
    assert cursor == layout.RECORD_SIZE == 580


def test_layout_names_are_unique() -> None:
    names = [f.name for f in layout.iter_fields()]
    assert len(names) == len(set(names))


def test_confirmed_fields_have_attributes(brutus: CharacterRecord) -> None:
    for f in layout.fields_with_confidence(layout.Confidence.CONFIRMED):
        assert hasattr(brutus, f.name), f"{f.name} has no attribute"


def test_coverage_accounts_for_every_byte() -> None:
    cov = layout.coverage()
    assert cov.total == layout.RECORD_SIZE
    assert sum(cov.by_confidence.values()) == layout.RECORD_SIZE
    # Don't pin the exact count -- it grows as fields are confirmed, and a test
    # that fails on progress is just noise. Assert the invariants instead: the
    # table tiles the record, and the original 27 confirmed bytes (20-byte name
    # + 6 abilities + exceptional STR) never regress.
    assert cov.confirmed >= 27
    assert cov.known + cov.unknown == layout.RECORD_SIZE


def test_candidate_regions_are_non_zero_in_the_specimen(
    brutus: CharacterRecord,
) -> None:
    for f in layout.candidate_regions():
        assert any(brutus.get_raw(f.name)), (
            f"{f.name} is flagged as a candidate region but is all zero"
        )


def test_every_non_zero_byte_is_inside_a_declared_field(
    record_bytes: bytes,
) -> None:
    """No non-zero byte of the specimen falls in an auto-generated filler gap."""
    declared = set()
    for f in layout.iter_fields():
        if f.is_known or f.candidate:
            declared.update(range(f.offset, f.end))
    stray = [i for i, b in enumerate(record_bytes) if b and i not in declared]
    assert stray == [], f"undeclared non-zero bytes at {[hex(i) for i in stray]}"


def test_dump_mentions_known_fields_and_non_zero_unknowns(
    brutus: CharacterRecord,
) -> None:
    text = brutus.dump()
    assert "BRUTUS" in text
    assert "STR" in text
    assert "0x220" in text or "0x0220" in text
    assert "gap_" not in text  # all-zero gaps stay out of the way by default


def test_dump_can_show_everything(brutus: CharacterRecord) -> None:
    assert "gap_" in brutus.dump(show_zero_unknowns=True)


def test_format_helpers_run() -> None:
    assert "CONFIRMED" in layout.format_coverage()
    assert "strength" in layout.format_table()


def test_equality_and_blank() -> None:
    blank = CharacterRecord.blank()
    assert blank == bytes(layout.RECORD_SIZE)
    assert blank == CharacterRecord.blank()
    assert blank != CharacterRecord(bytes([1] + [0] * (layout.RECORD_SIZE - 1)))


def test_the_spellbook_stops_at_55_not_56():
    """Seven bytes hold ids 1-55. Id 56 is RESTORATION, a scroll spell, and its
    bit would land one byte past the field -- `spells_known` used to peek at
    0x07F and `spellbook_bytes([56])` used to raise IndexError."""
    import pytest

    from goldbox.spells import (
        LAST_SPELLBOOK_SPELL,
        SPELLBOOK_OFFSET,
        SPELLBOOK_SIZE,
        spellbook_bytes,
        spells_known,
    )

    assert LAST_SPELLBOOK_SPELL == SPELLBOOK_SIZE * 8 - 1 == 55
    book = spellbook_bytes([1, 55])
    assert len(book) == SPELLBOOK_SIZE
    record = bytes(SPELLBOOK_OFFSET) + book + bytes(400)
    assert spells_known(record) == [1, 55]

    with pytest.raises(ValueError, match="RESTORATION"):
        spellbook_bytes([56])


def test_reading_a_spellbook_never_touches_the_byte_after_it():
    """0x07F belongs to something else. Setting it must not invent a spell."""
    from goldbox.spells import SPELLBOOK_OFFSET, spells_known

    record = bytearray(600)
    record[SPELLBOOK_OFFSET + 7] = 0xFF
    assert spells_known(bytes(record)) == []


def test_a_slot_record_refuses_the_fields_it_does_not_carry():
    """The hazard this guards: a save slot holds 256 bytes, and 0x100-0x11F is
    the roster block kept in SAVEDGAME1. Reading armour_class from a slot used
    to answer 0, which through the roster's `60 - value` bias decodes as AC 60 --
    a plausible number and completely wrong. The record stores the biased byte,
    so 0 is not even a legal reading of it."""
    from goldbox.record import RECORD_SIZE, CharacterRecord, FieldNotStored

    full = CharacterRecord(bytes(RECORD_SIZE))
    assert full.stored_size == RECORD_SIZE
    assert full.is_stored("armour_class")
    full.get("armour_class")                        # allowed, whatever it says

    slot = CharacterRecord(bytes(RECORD_SIZE), stored_size=256)
    assert not slot.is_stored("armour_class")
    assert slot.is_stored("strength")
    with pytest.raises(FieldNotStored, match="past the 256 bytes"):
        slot.get("armour_class")
    slot.get("strength")                            # still fine


def test_is_stored_is_decided_by_the_end_of_the_field_not_its_start():
    """A field straddling the boundary is not stored either."""
    from goldbox.layout import field_by_name
    from goldbox.record import RECORD_SIZE, CharacterRecord

    hp = field_by_name("hp_current")                # 0x119, two bytes
    rec = CharacterRecord(bytes(RECORD_SIZE), stored_size=hp.offset + 1)
    assert not rec.is_stored("hp_current")


def test_the_biased_encodings_round_trip_and_refuse_nonsense():
    """A silent wrap here produces a plausible number -- 60 - (-5) is 65, an
    ordinary byte -- so the encoders raise instead."""
    import pytest

    from goldbox.encoding import (
        armour_bonus_byte,
        armour_bonus_value,
        combat_byte,
        combat_value,
        item_protection_ac,
    )

    for thac0 in (13, 20, 21):
        assert combat_value(combat_byte(thac0)) == thac0
    for bonus in (-2, 0, 1, 5):
        assert armour_bonus_value(armour_bonus_byte(bonus)) == bonus

    with pytest.raises(ValueError):
        combat_byte(-200)
    with pytest.raises(ValueError):
        armour_bonus_byte(300)

    assert item_protection_ac(0xB4) == 8      # leather
    assert item_protection_ac(0xB9) == 3      # plate
    # The nibble rule and the general one diverge here: $AF is AC 13 under
    # `60 - (byte & 0x7F)` and -3 under `12 - (byte & 0x0F)`.
    assert item_protection_ac(0xAF) == 13


# ---------------------------------------------------------------------------
# 8. Attacks and the experience award, read as a monster's statistics
# ---------------------------------------------------------------------------
def _armed(dice_a=(2, 1, 8, 0), dice_b=(0, 0, 0, 0)) -> CharacterRecord:
    """A record carrying one or two attack forms, as five parallel pairs."""
    raw = bytearray(layout.RECORD_SIZE)
    for form, (rate, dice, die, mod) in enumerate((dice_a, dice_b)):
        raw[0x0D9 + form] = rate
        raw[0x0DB + form] = dice
        raw[0x0DD + form] = die
        raw[0x0DF + form] = mod & 0xFF
    return CharacterRecord(bytes(raw))


def test_attacks_per_round_are_stored_doubled():
    """COMBAT $12EC adds the round's parity before halving, so an odd value is
    AD&D's 3/2 attacks per round and not a rounding error."""
    from goldbox import monster

    assert monster.attacks(_armed((2, 1, 8, 0)))[0].rate_text == "1"
    assert monster.attacks(_armed((3, 1, 8, 2)))[0].rate_text == "3/2"
    assert monster.attacks(_armed((8, 1, 4, 0)))[0].rate_text == "4"


def test_two_attack_forms_and_no_more():
    """LDA $6C13,Y / LDX $6C15,Y, a stride of 2. A troll's 2 x 1d4+4 and one
    2d6 is what the pair is for."""
    from goldbox import monster

    troll = monster.attacks(_armed((4, 1, 4, 4), (2, 2, 6, 0)))
    assert [a.text for a in troll] == ["2 attacks per round (1d4+4)",
                                       "1 attack per round (2d6)"]
    assert len(monster.attacks(_armed((2, 1, 2, 0)))) == 1


def test_a_negative_damage_modifier_is_signed():
    from goldbox import monster

    assert monster.attacks(_armed((2, 1, 6, -1)))[0].damage_text == "1d6-1"


def test_the_experience_award_is_base_plus_a_rate_per_hit_point():
    """POST.COM $09BB: a 16-bit base plus a per-hit-point rate times hp_max,
    which is how AD&D expresses an award."""
    from goldbox import monster

    raw = bytearray(layout.RECORD_SIZE)
    raw[0x0F7], raw[0x0F8], raw[0x0F9] = 0x2C, 0x01, 4        # 300 + 4/hp
    rec = CharacterRecord(bytes(raw))
    assert monster.experience_award(rec, hp_max=11) == 344


# ---------------------------------------------------------------------------
# npc_marker_is_consistent -- #229 (A dual-classed Curse character imports
# with a warning that its record is corrupt)
# ---------------------------------------------------------------------------
def test_a_dual_classed_record_is_not_reported_inconsistent():
    """0x0B9/0x0BA are dual_class_slot/dual_class_level, not fill residue --
    #224 (0x0B9 and 0x0BA are documented both as an NPC marker and as the
    dual-class slot). A Curse, Silver Blades or Gateway character who dual-
    classed is non-zero there and $00 at the other six NPC_MARKER_OFFSETS,
    which used to trip the warning as if the record had been corrupted."""
    rec = CharacterRecord.blank()
    rec.dual_class_slot = 3
    rec.dual_class_level = 5
    assert rec.npc_marker_is_consistent


def test_a_real_npc_is_still_recognised():
    """The six residue bytes reading $FF, with the flag bit set, is what a
    shipped NPC record looks like -- narrowing the set must not stop that
    from reading as consistent."""
    from goldbox.record import (
        NPC_FLAG_BIT,
        NPC_FLAG_OFFSET,
        NPC_MARKER,
        NPC_MARKER_OFFSETS,
    )

    raw = bytearray(layout.RECORD_SIZE)
    raw[NPC_FLAG_OFFSET] = NPC_FLAG_BIT
    for o in NPC_MARKER_OFFSETS:
        raw[o] = NPC_MARKER
    rec = CharacterRecord(bytes(raw))
    assert rec.is_npc
    assert rec.npc_marker_is_consistent


def test_the_six_residue_bytes_half_set_is_still_reported_inconsistent():
    """Removing the two dual-class bytes must narrow the check, not gut it:
    the remaining six half set is still nothing any real save has shown."""
    from goldbox.record import NPC_MARKER, NPC_MARKER_OFFSETS

    raw = bytearray(layout.RECORD_SIZE)
    raw[NPC_MARKER_OFFSETS[0]] = NPC_MARKER
    rec = CharacterRecord(bytes(raw))
    assert not rec.npc_marker_is_consistent
