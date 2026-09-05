"""Carrying the identity draw across a conversion.

#258 (The C64 side of 0x0AB is unnamed, so the conversion drops it with no
issue behind it): DOS keeps this at 0x0AB and Pool of Radiance's C64 GEN
draws the same value at 0x0E6-0x0E7, one call to the random generator per
byte, and nothing on either port ever reads it back once written.  Its only
job is breaking a tie when two characters share a name -- DOS's ADD CHARACTER
TO PARTY checks the name and this byte both, and the C64's checks the name
alone, so the C64 never needed a byte of its own but has one anyway.

None of these tests needs a save on disk: every record here is built from
zeroes with one field changed, which is what makes them run with no game
disks present.
"""

from __future__ import annotations

from goldbox import c64_codec, dos, dos_layout, neutral
from goldbox.record import CharacterRecord

IDENT = dos_layout.FIELDS_BY_NAME["unnamed_0ab"]


def _dos_record(identity: int = 0x42) -> dos.DosCharacter:
    """A Pool of Radiance record that is zero but for the identity byte."""
    raw = bytearray(dos_layout.RECORD_SIZE)
    raw[IDENT.offset] = identity
    return dos.DosCharacter(bytes(raw))


def _c64_record(identity: int | None = None, second: int = 0) -> CharacterRecord:
    rec = CharacterRecord(bytes(CharacterRecord.SIZE))
    if identity is not None:
        rec.set_raw("identity_pair", bytes([identity, second]))
    return rec


# --- DOS to the C64 ----------------------------------------------------------

def test_the_dos_identity_byte_crosses_into_the_c64_identity_pair():
    """DOS 0x0AB, whole, into the first byte of the C64's identity_pair --
    the mechanism #258's specification names."""
    char = _dos_record(0x42)
    rec, rep = c64_codec.write(dos.to_neutral(char))
    assert rec.get_raw("identity_pair") == b"\x42\x00"
    assert "identity_pair" in rep.sources[0x0E6]


def test_the_second_byte_of_the_pair_is_always_zero():
    """The C64 draws two bytes and nothing reads either one back; DOS has
    only ever had one, so the second is written zero rather than guessed."""
    for identity in (0x00, 0x01, 0xFF):
        rec, _ = c64_codec.write(dos.to_neutral(_dos_record(identity)))
        assert rec.get_raw("identity_pair")[1] == 0


def test_the_identity_pair_no_longer_shows_as_dropped():
    """The whole point of naming C64 record 0x0E6: `unnamed_0ab` comes off
    the drop list entirely, both in the table and in what a real conversion
    reports."""
    assert "unnamed_0ab" not in dict(dos.DROPPED)
    assert "unnamed_0ab" not in dos.DROPPED_PLAYER_TEXT
    rec, report = dos.to_c64_record(_dos_record(0x99))
    assert not [d for d in report.dropped if "identity" in d.lower()]
    assert rec.get_raw("identity_pair") == b"\x99\x00"


# --- the C64 back to the neutral record --------------------------------------

def test_the_c64_identity_pair_reads_back_as_neutral_unnamed_0ab():
    out = c64_codec.read(_c64_record(0x57, 0xD1), game="pool-of-radiance")
    assert out.get("unnamed_0ab") == 0x57


def test_curse_and_silver_blades_have_no_identity_pair_to_read():
    """Neither title's GEN draws the pair, so a record of either shape gives
    the reader nothing to carry -- even when the bytes happen to be
    non-zero, which they never are in a shipped save (#258's own census: 6
    of 6 Curse records and 4 of 4 Silver Blades ones read `00 00`)."""
    for game in ("curse-of-the-azure-bonds", "secret-of-the-silver-blades"):
        out = c64_codec.read(_c64_record(0x57, 0xD1), game=game)
        assert "unnamed_0ab" not in out


# --- and back to DOS ----------------------------------------------------------

def test_a_pool_of_radiance_c64_record_gives_dos_the_pair_back():
    """The other half of the round trip: a value that came from the C64's
    own identity pair is written straight to DOS 0x0AB, not digested."""
    out = c64_codec.read(_c64_record(0x57, 0xD1), game="pool-of-radiance")
    rec, _, _, rep = dos.write(out)
    assert rec[IDENT.offset] == 0x57
    assert "0x57" in rep.sources[IDENT.offset]
    assert "identity pair" in rep.sources[IDENT.offset]


def test_a_curse_or_silver_blades_source_still_gets_the_digest():
    """No C64 identity pair means no supplied value, so the digest #216
    built for exactly this situation is what DOS still gets -- distinct
    across two records that otherwise differ."""
    from goldbox.neutral import NeutralCharacter

    one = c64_codec.read(_c64_record(None), game="curse-of-the-azure-bonds")
    two = c64_codec.read(_c64_record(None), game="curse-of-the-azure-bonds")
    assert isinstance(one, NeutralCharacter)
    one.set("experience", 1, "made up")
    two.set("experience", 2, "made up")
    first, _, _, _ = dos.write(one)
    second, _, _, _ = dos.write(two)
    assert first[IDENT.offset] != second[IDENT.offset]


def test_a_dos_record_round_trips_its_own_identity_through_the_c64():
    """The whole carry in one pass: DOS 0x0AB, to the C64's identity_pair,
    and back to the same DOS byte -- the exact defect #258 describes,
    fixed."""
    char = _dos_record(0x99)
    c64, _ = c64_codec.write(dos.to_neutral(char))
    assert c64.get_raw("identity_pair")[0] == 0x99
    rec, _, _, _ = dos.write(c64_codec.read(c64, game="pool-of-radiance"))
    assert rec[IDENT.offset] == 0x99


def test_a_pure_dos_round_trip_still_derives_the_digest():
    """The one direction this issue does not change: a DOS source's own
    0x0AB is not the value #216's digest replaced it with going the other
    way.  Two otherwise-identical records differing only at 0x0AB convert to
    the *same* DOS byte, because the digest excludes that offset -- the
    passthrough this test would catch is one that copied the original
    byte instead."""
    one, _, _, _ = dos.write(dos.to_neutral(_dos_record(0x11)))
    two, _, _, _ = dos.write(dos.to_neutral(_dos_record(0x22)))
    assert one[IDENT.offset] == two[IDENT.offset]
    assert one[IDENT.offset] == dos.identity_byte(one)


# --- the vocabulary and the tables agree -------------------------------------

def test_the_neutral_field_is_declared():
    assert "unnamed_0ab" in neutral.FIELDS
