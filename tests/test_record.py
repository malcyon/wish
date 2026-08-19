"""Tests for the character-record decoding layer.

The specimen is ``tests/fixtures/brutus.chr``: a 582-byte PRG (2-byte load
address $6B00 + 580-byte record) holding a fighter named BRUTUS.
"""

from __future__ import annotations

import pathlib

import pytest

from por import layout, petscii
from por.record import (
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
        brutus.set_raw("region_0d9", b"\x00\x00")


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


def test_record_name_stops_at_first_nul() -> None:
    assert petscii.decode_record_name(b"AB\x00CD" + b"\x00" * 15) == "AB"
    # ...which is exactly why such a field is not canonical and must not be
    # rewritten from its text form.
    assert not petscii.is_canonical_record_name(b"AB\x00CD" + b"\x00" * 15)


def test_short_name_written_into_record_is_nul_padded(record_bytes: bytes) -> None:
    rec = CharacterRecord(record_bytes)
    rec.name = "AL"
    assert rec.get_raw("name") == b"AL" + b"\x00" * 18


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
