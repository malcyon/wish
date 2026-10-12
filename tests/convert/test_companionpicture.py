"""A later-title companion's combat picture across every port.

Curse, Silver Blades and Pools of Darkness keep, at the byte Pool of
Radiance uses as the identity draw (`unnamed_0ab`), a companion's combat
picture: the party loader of each reads it as a `CPIC` block id for any
member whose control byte is 0x80 or above.  Amiga Curse stops loading the
save when the id is not in its `CPIC.TLB`, so a conversion has to keep the
companion's own byte through every route.  The C64 Curse engine never reads
the C64 place a conversion puts it, `0x0E6`, and fills it with `$FF` in
every `MON` file.
"""

from __future__ import annotations

import dataclasses

import pytest
from gamedata import specimen

from goldbox import amiga_later, amiga_savegame, c64_codec, dos_codec, dos_port
from goldbox.amiga_adf import AmigaDisk
from goldbox.record import CharacterRecord

CURSE = dos_port.CURSE_OF_THE_AZURE_BONDS
PICTURE = dos_port.FIELDS_BY_NAME_FOR[CURSE.key]["unnamed_0ab"]
#: The Amiga Curse record's place for the same byte, the one its loader reads.
AMIGA_PICTURE = 0x127
#: WORG's monster id, a block of DOS `CPIC1.DAX` and of Amiga `CPIC.TLB`.
WORG = 0x57


def _evoker() -> amiga_later.AmigaCharacter:
    """EVOKER, the zombie companion the Amiga's own ADD CHARACTER wrote."""
    where = specimen("wish-plane-303-curse-evoker-add", "amiga")
    slot = amiga_savegame.read_slot(AmigaDisk.open(str(where / "fetched-save.adf")),
                                    "D", "curse-of-the-azure-bonds")
    return next(m for m in slot.characters if m.raw[0xF7] >= 0x80)


def _with_picture(char, picture: int | None):
    if picture is None:
        return char
    raw = bytearray(char.raw)
    raw[AMIGA_PICTURE] = picture
    return dataclasses.replace(char, raw=bytes(raw))


def _via_dos(char) -> int:
    rec, _, _, _ = dos_codec.write(amiga_later.to_neutral_later(char),
                                   deltas=CURSE)
    back, _ = amiga_later.write_later(
        dos_codec.to_neutral(dos_codec.DosCharacter(rec)), CURSE.key)
    return back.raw[AMIGA_PICTURE]


def _via_c64(char) -> int:
    neutral = amiga_later.to_neutral_later(char)
    rec, _ = c64_codec.write(neutral)
    back, _ = amiga_later.write_later(c64_codec.read(rec, game=neutral.game),
                                      CURSE.key)
    return back.raw[AMIGA_PICTURE]


@pytest.mark.parametrize("picture", [None, WORG],
                         ids=["his-own-byte", "a-picture-cpic-holds"])
@pytest.mark.parametrize("route", [_via_dos, _via_c64], ids=["dos", "c64"])
def test_an_amiga_companion_comes_back_with_his_own_picture(route, picture):
    """Amiga to DOS or the C64 and back keeps `$127`, byte for byte.

    EVOKER's own byte, 0x79, is the Pool identity draw the game's import
    copied, and the same record holding WORG's id is the case where the
    picture loads; a digest in its place loses both.
    """
    char = _with_picture(_evoker(), picture)
    assert route(char) == char.raw[AMIGA_PICTURE]


def _dos_curse(control: int, picture: int, name: bytes = b"WORG") -> bytes:
    raw = bytearray(CURSE.record_size)
    raw[0] = len(name)
    raw[1:1 + len(name)] = name
    f83 = dos_port.FIELDS_BY_NAME_FOR[CURSE.key]["field_83_87"]
    raw[f83.offset + 1] = control
    raw[PICTURE.offset] = picture
    return bytes(raw)


def _rewrite(record: bytes) -> bytes:
    rec, _, _, _ = dos_codec.write(
        dos_codec.to_neutral(dos_codec.DosCharacter(record)), deltas=CURSE)
    return rec


def test_a_dos_companion_keeps_his_picture():
    """A DOS source's companion keeps 0x126; a digest is for players."""
    assert _rewrite(_dos_curse(0xB2, WORG))[PICTURE.offset] == WORG


def test_a_dos_player_still_gets_the_digest():
    """The control: a player's byte is only the ADD CHARACTER tie-break."""
    rec = _rewrite(_dos_curse(0x00, WORG))
    assert rec[PICTURE.offset] == dos_codec.identity_byte(rec, CURSE)


def test_pool_of_radiance_has_no_companion_picture():
    """Pool's engine reads 0x0AB only at ADD CHARACTER."""
    raw = bytearray(dos_port.POOL_OF_RADIANCE.record_size)
    f83 = dos_port.FIELDS_BY_NAME["field_83_87"]
    raw[f83.offset + 1] = 0xB2
    assert not dos_codec.holds_companion_picture(raw)
    assert dos_codec.holds_companion_picture(_dos_curse(0xB2, WORG))
    assert not dos_codec.holds_companion_picture(_dos_curse(0x7F, WORG))


def test_a_player_the_engine_has_taken_over_keeps_a_player_s_rule():
    """Control 0xB3 passes the loader's test, but his byte is his own draw."""
    assert not dos_codec.holds_companion_picture(_dos_curse(0xB3, WORG))
    rec = _rewrite(_dos_curse(0xB3, WORG))
    assert rec[PICTURE.offset] == dos_codec.identity_byte(rec, CURSE)


def test_a_same_named_player_moves_and_the_companion_keeps_his_picture():
    """The party tie-break never changes a picture, in either order."""
    companion = _dos_curse(0xB2, WORG)
    player = _dos_curse(0x00, WORG)
    for order in ((companion, player), (player, companion)):
        built = [(None, rec, b"", b"", None) for rec in order]
        out = dos_codec._deduplicate_party_identities(built, CURSE)
        got = {rec[0xF7]: rec[PICTURE.offset] for _, rec, *_ in out}
        assert got[0xB2] == WORG
        assert got[0x00] != WORG


def _c64(control: int, picture: int) -> CharacterRecord:
    rec = CharacterRecord(bytes(CharacterRecord.SIZE))
    rec.set("flags_0b8", control)
    rec.set_raw("identity_pair", bytes([picture, 0]))
    return rec


@pytest.mark.parametrize("control, pair, want", [
    (0xB2, WORG, WORG),
    (0xB2, 0xFF, None),
    (0x00, WORG, None),
], ids=["converted-companion", "joined-on-the-c64", "player"])
def test_the_c64_curse_reader_takes_only_a_converted_companion_s_picture(
        control, pair, want):
    char = c64_codec.read(_c64(control, pair), game="curse-of-the-azure-bonds")
    assert char.get("unnamed_0ab") == want
