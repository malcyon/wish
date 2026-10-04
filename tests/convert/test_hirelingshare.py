"""A Pool of Radiance hireling's treasure share, between the C64 and DOS or the Amiga.

#743.  The Training Hall's hirelings and the Valhingen Graveyard companion
arrive with a share byte of `$FF` or `$84`, the byte in their `MON` record,
and both ports ship the same byte.  Every engine skips a companion whose raw
byte is zero and otherwise adds `byte & mask` parts to the split:

    C64 POST.COM $194F   LDA $6BFA / BEQ out / AND #$03
    DOS GAME.OVR 0x0068A7 mov al, es:[di+85h] / and al, 7   (0x0069B6 cmp 0)
    Amiga /program 0x02DA38 and.b $86(a3), d0 with d0 = 7  (0x02DB08 cmpi 0)

So a C64 byte gives `raw & 3` parts and DOS or the Amiga `raw & 7`, and the
raw zero test decides whether the companion is named as taking his share.
A converted companion must give the same number of parts and the same zero
test: C64 `$FF` (three parts) is DOS `$FB`, and C64 `$84` (no parts, still
named) is DOS `$80`.

The synthetic tests build records from zeroes and run in CI; the last ones
read the shipped `MON<hex>` templates off the player's C64 disks and skip
without them.
"""

from __future__ import annotations

import gamedata
import pytest

from goldbox import amiga_por, c64_codec, dos_codec, dos_port, neutral
from goldbox.record import RECORD_SIZE, CharacterRecord

F83 = dos_port.FIELDS_BY_NAME["field_83_87"]
DOS_CONTROL = F83.offset + 1
DOS_SHARE = F83.offset + 2
AMIGA_SHARE = amiga_por.amiga_por_offset(DOS_SHARE)

#: A joined companion's control byte: bit 7 and morale 99, halved, which is
#: what `ADDNPC 24, 99` makes of the Valhingen Graveyard companion.
JOINED = 0x80 | (99 >> 1)

#: The shipped companions whose share has bit 2 set: `MON<hex>` file, share.
BIT_2_COMPANIONS = {"MON18": 0xFF, "MON6D": 0x84, "MON6E": 0xFF,
                    "MON6F": 0xFF, "MON70": 0xFF, "MON7A": 0xFF}


def _parts(raw: int, mask: int) -> tuple[bool, int]:
    """What an engine does with a companion's byte: named, and his parts."""
    return raw != 0, raw & mask


def _c64_companion(share: int, name: bytes = b"HIRELING") -> CharacterRecord:
    rec = CharacterRecord.blank()
    rec.set("name", name)
    rec.set("flags_0b8", JOINED)
    rec.set("treasure_share", share)
    return rec


def _to_dos(rec: CharacterRecord):
    return dos_codec.write(c64_codec.read(rec, game="pool-of-radiance"))


def _to_amiga(rec: CharacterRecord):
    return amiga_por.write_por(c64_codec.read(rec, game="pool-of-radiance"))


def _share_lines(rep) -> list[str]:
    return [line for line in list(rep.dropped) + list(rep.losses)
            if "share" in line or "field_83_87" in line]


# --- synthetic, every C64 byte ----------------------------------------------

@pytest.mark.parametrize("share", range(256))
def test_every_c64_share_splits_the_same_on_dos(share):
    """All 256 C64 bytes: DOS names the companion exactly when the C64 did
    and gives him the parts the C64 gave.  Before the fix, the 128 with bit
    2 set raised `ValueError`."""
    out, _itm, _spc, rep = _to_dos(_c64_companion(share))
    assert out[DOS_CONTROL] == JOINED
    assert _parts(out[DOS_SHARE], 7) == _parts(share, 3)
    assert _share_lines(rep) == []


@pytest.mark.parametrize("share", (0x84, 0xFF, 0x04, 0x07))
def test_a_bit_2_c64_share_splits_the_same_on_the_amiga(share):
    record, _itm, _spc, rep = _to_amiga(_c64_companion(share))
    assert _parts(record[AMIGA_SHARE], 7) == _parts(share, 3)
    assert _share_lines(rep) == []


@pytest.mark.parametrize("share,expected", ((0xFF, 0xFB), (0x84, 0x80),
                                            (0x04, 0x08), (0x03, 0x03),
                                            (0x00, 0x00)))
def test_the_dos_byte_keeps_every_bit_but_the_one_dos_reads_as_a_part(
        share, expected):
    """Bit 2 is a part on DOS and nothing on the C64, so it alone is
    cleared; `$04` alone would then be zero, which DOS would not name, so it
    becomes `$08`."""
    out, _itm, _spc, _rep = _to_dos(_c64_companion(share))
    assert out[DOS_SHARE] == expected


@pytest.mark.parametrize("share", (0x84, 0xFF, 0x04))
def test_a_converted_share_comes_back_to_the_c64_splitting_the_same(share):
    """C64 to DOS to C64, and C64 to the Amiga to the C64: the byte that
    returns gives the C64 split the source gave."""
    out, _itm, _spc, _rep = _to_dos(_c64_companion(share))
    back, _rep = c64_codec.write(
        dos_codec.to_neutral(dos_codec.DosCharacter(bytes(out))))
    assert back.get("flags_0b8") == JOINED
    assert _parts(back.get("treasure_share"), 3) == _parts(share, 3)

    record, itm, spc, _rep = _to_amiga(_c64_companion(share))
    amiga = amiga_por.por_character(bytes(record), itm, spc)
    back, _rep = c64_codec.write(amiga_por.to_neutral(amiga))
    assert _parts(back.get("treasure_share"), 3) == _parts(share, 3)


def test_a_dos_or_amiga_share_without_bit_2_is_written_unchanged():
    """The direction the fix leaves alone: 0 to 3, and the bytes a C64
    source becomes, cross to the C64 raw."""
    for share in (0, 1, 2, 3, 0x80, 0xFB, 0x08):
        raw = bytearray(dos_port.RECORD_SIZE)
        raw[DOS_CONTROL] = JOINED
        raw[DOS_SHARE] = share
        rec, _rep = c64_codec.write(
            dos_codec.to_neutral(dos_codec.DosCharacter(bytes(raw))))
        assert rec.get("treasure_share") == share


# --- the shipped templates -------------------------------------------------

def _mon(name: str) -> CharacterRecord:
    """A C64 `MON<hex>` template as a record, joined as `ADDNPC` joins it."""
    body = gamedata.game_file(name)
    assert len(body) <= RECORD_SIZE, (name, len(body))
    rec = CharacterRecord.from_bytes(bytes(body) + bytes(RECORD_SIZE - len(body)))
    assert rec.get("flags_0b8") & 0x80, name
    return rec


@pytest.mark.parametrize("name,share", sorted(BIT_2_COMPANIONS.items()))
def test_a_shipped_hireling_converts_from_the_c64_to_dos_and_the_amiga(
        name, share):
    """The Training Hall's five and the Valhingen Graveyard companion, off
    the player's disks.  Before the fix each raised `ValueError treasure
    share ... has bit 2 set`."""
    rec = _mon(name)
    assert rec.get("treasure_share") == share

    out, _itm, _spc, rep = _to_dos(rec)
    assert _parts(out[DOS_SHARE], 7) == _parts(share, 3), name
    assert _share_lines(rep) == [], name

    record, _itm, _spc, rep = _to_amiga(_mon(name))
    assert _parts(record[AMIGA_SHARE], 7) == _parts(share, 3), name
    assert _share_lines(rep) == [], name

    back, _rep = c64_codec.write(
        dos_codec.to_neutral(dos_codec.DosCharacter(bytes(out))))
    assert _parts(back.get("treasure_share"), 3) == _parts(share, 3), name


@pytest.mark.parametrize("share", (0x84, 0xFF, 0x04, 0x07, 0x03))
def test_the_amiga_writer_gives_the_byte_the_dos_writer_gives(share):
    """`amiga_por.write_por` delegates to `dos_codec.write`, so both ports
    take the share `dos_codec.dos_share_from_c64` makes of the C64 byte."""
    dos, _itm, _spc, _rep = _to_dos(_c64_companion(share))
    amiga, _itm, _spc, _rep = _to_amiga(_c64_companion(share))
    assert dos[DOS_SHARE] == amiga[AMIGA_SHARE] == \
        dos_codec.dos_share_from_c64(share)


def _player(share: int) -> CharacterRecord:
    rec = CharacterRecord.blank()
    rec.set("name", b"HERO")
    rec.set("treasure_share", share)
    return rec


@pytest.mark.parametrize("share", (0x04, 0x84, 0xFF))
def test_a_c64_player_characters_share_with_bit_2_is_still_blocked(share):
    """His byte in that slot is not a share, so nothing says what to clear."""
    rec = _player(share)
    assert not rec.get("flags_0b8") & 0x80
    with pytest.raises(ValueError, match="bit 2 set"):
        _to_dos(rec)
    with pytest.raises(ValueError, match="bit 2 set"):
        _to_amiga(_player(share))


@pytest.mark.parametrize("game", ("curse-of-the-azure-bonds",
                                  "secret-of-the-silver-blades"))
@pytest.mark.parametrize("share", (0x04, 0x84, 0xFF))
def test_a_c64_companions_share_with_bit_2_is_still_blocked_outside_pool(
        game, share):
    """Only Pool of Radiance's DOS and Amiga masks are measured."""
    rec = _c64_companion(share)
    with pytest.raises(ValueError, match="bit 2 set"):
        dos_codec.write(c64_codec.read(rec, game=game))


# --- DOS or the Amiga to the C64 --------------------------------------------

def _dos_companion(share: int) -> dos_codec.DosCharacter:
    raw = bytearray(dos_port.RECORD_SIZE)
    raw[DOS_CONTROL] = JOINED
    raw[DOS_SHARE] = share
    return dos_codec.DosCharacter(bytes(raw))


def _dos_to_c64(share: int):
    return c64_codec.write(dos_codec.to_neutral(_dos_companion(share)))


@pytest.mark.parametrize("share", range(256))
def test_every_dos_share_converts_to_the_c64_with_its_parts_capped_at_three(
        share):
    """All 256 DOS bytes: named exactly when DOS named him, and the C64 gives
    him the parts DOS gave, or 3 where DOS gave more.  Before the fix the 128
    with bit 2 set raised `ValueError`."""
    rec, _rep = _dos_to_c64(share)
    written = rec.get("treasure_share")
    assert (written != 0) == (share != 0)
    assert written & 3 == min(share & 7, 3)


@pytest.mark.parametrize("share,expected", ((0xFF, 0xFF), (0x84, 0x87),
                                            (0x04, 0x07), (0x05, 0x07),
                                            (0x03, 0x03), (0x01, 0x01)))
def test_the_c64_byte_for_a_dos_share(share, expected):
    assert dos_codec.c64_share_from_dos(share) == expected
    rec, _rep = _dos_to_c64(share)
    assert rec.get("treasure_share") == expected


@pytest.mark.parametrize("share,parts,written", ((0xFF, 7, 0xFF),
                                                 (0x84, 4, 0x87),
                                                 (0x05, 5, 0x07)))
def test_the_parts_the_c64_cannot_give_are_on_the_warnings_not_the_losses(
        share, parts, written):
    """A loss would make Save As block the party; the warning is what a
    caller can read."""
    _rec, rep = _dos_to_c64(share)
    lines = [w for w in rep.warnings if "treasure_share" in w]
    assert len(lines) == 1
    assert f"{parts} parts" in lines[0] and f"{written:#04x}" in lines[0]
    assert not [w for w in rep.losses if "treasure_share" in w]


@pytest.mark.parametrize("share", (0, 1, 2, 3, 0x80, 0xF8))
def test_a_dos_share_within_the_c64s_parts_reports_nothing(share):
    _rec, rep = _dos_to_c64(share)
    assert not [w for w in rep.warnings if "treasure_share" in w]


@pytest.mark.parametrize("share", (0x84, 0xFF, 0x05))
def test_an_amiga_hireling_converts_to_the_c64_the_same_way(share):
    record, itm, spc, _rep = _to_amiga(_c64_companion(0x03))
    raw = bytearray(record)
    raw[AMIGA_SHARE] = share
    amiga = amiga_por.por_character(bytes(raw), itm, spc)
    rec, rep = c64_codec.write(amiga_por.to_neutral(amiga))
    assert rec.get("treasure_share") == dos_codec.c64_share_from_dos(share)
    assert [w for w in rep.warnings if "treasure_share" in w]


@pytest.mark.parametrize("share", (0x04, 0x84, 0xFF))
def test_a_dos_player_characters_share_with_bit_2_is_still_blocked(share):
    raw = bytearray(dos_port.RECORD_SIZE)
    raw[DOS_CONTROL], raw[DOS_SHARE] = 0x01, share
    with pytest.raises(ValueError, match="bit 2 set"):
        c64_codec.write(dos_codec.to_neutral(dos_codec.DosCharacter(bytes(raw))))


@pytest.mark.parametrize("share", (0x04, 0x84, 0xFF))
def test_a_dos_zombie_with_a_bit_2_share_is_still_blocked(share):
    """Animate Dead's zombie is a player character to the C64, so its byte
    is not a companion's share."""
    raw = bytearray(dos_port.RECORD_SIZE)
    raw[DOS_CONTROL], raw[DOS_SHARE] = c64_codec.DOS_PC_TAKEN_OVER, share
    raw[dos_port.FIELDS_BY_NAME["field_10c_10f"].offset] = \
        neutral.STATUS_NAMES.index("animated")
    char = dos_codec.to_neutral(dos_codec.DosCharacter(bytes(raw)))
    assert char.get("status") == "animated"
    with pytest.raises(ValueError, match="bit 2 set"):
        c64_codec.write(char)
