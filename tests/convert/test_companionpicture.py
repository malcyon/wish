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


def _evoker_party() -> tuple:
    """The party of the slot the Amiga's own ADD CHARACTER wrote."""
    where = specimen("wish-plane-303-curse-evoker-add", "amiga")
    slot = amiga_savegame.read_slot(AmigaDisk.open(str(where / "fetched-save.adf")),
                                    "D", "curse-of-the-azure-bonds")
    return tuple(slot.characters)


def _evoker() -> amiga_later.AmigaCharacter:
    """EVOKER, the zombie companion the Amiga's own ADD CHARACTER wrote."""
    return next(m for m in _evoker_party() if m.raw[0xF7] >= 0x80)


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


def _dos_record(deltas, control: int, picture: int,
                name: bytes = b"WORG") -> bytes:
    """A synthetic record of `deltas`' title with the control byte set."""
    fields = dos_port.FIELDS_BY_NAME_FOR[deltas.key]
    raw = bytearray(deltas.record_size)
    raw[0] = len(name)
    raw[1:1 + len(name)] = name
    f83 = fields["field_83_87"]
    raw[f83.offset + (1 if f83.size == 5 else 0)] = control
    raw[fields["unnamed_0ab"].offset] = picture
    return bytes(raw)


def _dos_curse(control: int, picture: int, name: bytes = b"WORG") -> bytes:
    return _dos_record(CURSE, control, picture, name)


def _rewrite(record: bytes, deltas=CURSE) -> bytes:
    rec, _, _, _ = dos_codec.write(
        dos_codec.to_neutral(dos_codec.DosCharacter(record)), deltas=deltas)
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


def test_a_player_the_engine_has_taken_over_keeps_his_picture():
    """Control 0xB3 passes the loader's test, so his byte is drawn from CPIC."""
    assert dos_codec.holds_companion_picture(_dos_curse(0xB3, WORG))
    assert _rewrite(_dos_curse(0xB3, WORG))[PICTURE.offset] == WORG


@pytest.mark.parametrize("control, companion", [
    (0x7F, False), (0x80, True), (0xB2, True), (0xB3, True),
    (0xB4, True), (0xFF, True),
])
def test_the_control_byte_boundaries(control, companion):
    """Bit 7 is the loader's test, the taken-over 0xB3 included."""
    record = _dos_curse(control, WORG)
    assert dos_codec.holds_companion_picture(record) is companion
    got = _rewrite(record)[PICTURE.offset]
    if companion:
        assert got == WORG
    else:
        assert got != WORG


def test_silver_blades_reads_its_control_byte_at_the_field_start():
    """Its 4-byte `field_83_87` has the control byte at +0, Curse's 5-byte at +1."""
    silver = dos_port.SECRET_OF_THE_SILVER_BLADES
    offset = dos_port.FIELDS_BY_NAME_FOR[silver.key]["unnamed_0ab"].offset
    for control, companion in ((0x7F, False), (0x80, True), (0xFF, True)):
        record = _dos_record(silver, control, WORG)
        assert dos_codec.holds_companion_picture(record) is companion
        assert (_rewrite(record, silver)[offset] == WORG) is companion


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
    (0x00, WORG, WORG),
    (0x00, 0x00, None),
], ids=["converted-companion", "joined-on-the-c64", "converted-player",
        "player-made-on-the-c64"])
def test_the_c64_curse_reader_takes_only_what_a_conversion_wrote(
        control, pair, want):
    char = c64_codec.read(_c64(control, pair), game="curse-of-the-azure-bonds")
    assert char.get("unnamed_0ab") == want


@pytest.mark.parametrize("pair, want", [
    (WORG, WORG), (0x00, None), (0xFF, 0xFF),
], ids=["converted", "made-on-the-c64", "a-draw-of-ff"])
def test_the_c64_curse_reader_returns_a_raised_player_s_byte(pair, want):
    """A player at status $03: DOS and the Amiga hold him taken over (0xB3).

    $FF is the MON files' fill, which only a companion carries, so for a
    player it is a draw like any other; 0 is what Curse's GEN leaves.
    """
    rec = _c64(0x00, pair)
    rec.set("roster_in_use", c64_codec.ZOMBIE_STATUS)
    char = c64_codec.read(rec, game="curse-of-the-azure-bonds")
    assert char.get("npc_control_byte") == c64_codec.DOS_PC_TAKEN_OVER
    assert char.get("unnamed_0ab") == want


@pytest.mark.parametrize("control, pair, want", [
    (0x00, WORG, WORG), (0xB2, WORG, WORG), (0x00, 0x00, None),
    (0xB2, 0x00, None),
], ids=["converted-player", "converted-companion", "player-made-on-the-c64",
        "joined-on-the-c64"])
def test_silver_blades_on_the_c64_returns_what_a_conversion_wrote(
        control, pair, want):
    """Its MON files and its GEN both leave 0 at 0x0E6, and no C64 code of
    the title reads the byte, so anything else is what a conversion wrote."""
    char = c64_codec.read(_c64(control, pair),
                          game="secret-of-the-silver-blades")
    assert char.get("unnamed_0ab") == want


# --- BRUTUS: a player Animate Dead raised, control 0xB3 ---------------------
# DOS Curse's Animate Dead (`GAME.OVR` 0x30EC9-0x30EDF) writes 0xB2 over a
# companion's control byte and 0xB3 over a player's; the party loader draws
# either from `CPIC` by this byte.  BRUTUS was imported from Pool already
# animated, so his `$127` is his Pool draw, 0x57, which Amiga Curse finds.

def _brutus():
    from tools.registry import scratch
    where = scratch.cache_dir("acceptance", "WISH-303", "s5-c64",
                              "source-save.adf")
    if not where.is_file():
        pytest.skip("needs the WISH-303 s5-c64 source save")
    slot = amiga_savegame.read_slot(AmigaDisk.open(str(where)), "D",
                                    "curse-of-the-azure-bonds")
    return next(m for m in slot.characters if m.name == "BRUTUS")


def test_a_raised_player_keeps_his_picture_through_dos():
    """Amiga to DOS and back, still raised: 0xB3 and his own 0x57."""
    brutus = _brutus()
    assert (brutus.raw[0xF7], brutus.raw[AMIGA_PICTURE]) == (0xB3, WORG)
    rec, _, _, _ = dos_codec.write(amiga_later.to_neutral_later(brutus),
                                   deltas=CURSE)
    back, _ = amiga_later.write_later(
        dos_codec.to_neutral(dos_codec.DosCharacter(rec)), CURSE.key)
    assert (back.raw[0xF7], back.raw[AMIGA_PICTURE]) == (0xB3, WORG)


def test_the_c64_route_makes_a_raised_player_living():
    """The C64 writer turns him into a living player under the player's
    orders, so he comes back at control 0 and the loader composes his
    player figure; `$127` is then only the ADD CHARACTER tie-break."""
    neutral = amiga_later.to_neutral_later(_brutus())
    rec, _ = c64_codec.write(neutral)
    back, _ = amiga_later.write_later(c64_codec.read(rec, game=neutral.game),
                                      CURSE.key)
    assert back.raw[0xF7] == 0x00
    assert not dos_codec.holds_companion_picture(
        dos_codec.write(c64_codec.read(rec, game=neutral.game),
                        deltas=CURSE)[0])


# --- A living player's own draw through the C64 -----------------------------
# The C64 Curse engine never reads 0x0E6, and the conversion writes the
# player's draw there so that a conversion back returns his own number
# (`.claude/rules/conversions.md`, the identity byte's worked example).

def _via_c64_to_dos(record: bytes) -> int:
    char = dos_codec.to_neutral(dos_codec.DosCharacter(record))
    rec, _ = c64_codec.write(char)
    back, _, _, _ = dos_codec.write(c64_codec.read(rec, game=char.game),
                                    deltas=CURSE)
    return back[PICTURE.offset]


def test_a_dos_player_comes_back_from_the_c64_with_his_own_draw():
    assert _via_c64_to_dos(_dos_curse(0x00, 0x42)) == 0x42


SILVER_BLADES = dos_port.SECRET_OF_THE_SILVER_BLADES


def _round_trip(record: bytes, deltas) -> tuple[bytes, bytes]:
    """DOS to the C64 and back to DOS: the C64 pair and the DOS record."""
    char = dos_codec.to_neutral(dos_codec.DosCharacter(record))
    rec, _ = c64_codec.write(char)
    back, _, _, _ = dos_codec.write(c64_codec.read(rec, game=char.game),
                                    deltas=deltas)
    return rec.get_raw("identity_pair"), back


@pytest.mark.parametrize("deltas, control, own, pair", [
    (CURSE, 0x00, 0x00, b"\x00\x01"),
    (CURSE, 0x00, 0xFF, b"\xff\x01"),
    (CURSE, 0xB2, 0xFF, b"\xff\x01"),
    (CURSE, 0xB2, 0x00, b"\x00\x01"),
    (SILVER_BLADES, 0x00, 0x00, b"\x00\x01"),
    (SILVER_BLADES, 0xB2, 0x00, b"\x00\x01"),
    (SILVER_BLADES, 0xB2, 0x4D, b"\x4d\x00"),
], ids=["curse-player-0", "curse-player-ff", "curse-companion-ff",
        "curse-companion-0", "silver-blades-player-0",
        "silver-blades-companion-0", "silver-blades-companion-vala"])
def test_a_byte_equal_to_the_fill_comes_back_from_the_c64(
        deltas, control, own, pair):
    """A byte equal to a fill the title leaves at 0x0E6 is marked at 0x0E7,
    so the conversion back returns it rather than a digest."""
    record = _dos_record(deltas, control, own)
    written, back = _round_trip(record, deltas)
    assert written == pair
    assert back[dos_port.FIELDS_BY_NAME_FOR[deltas.key]
                ["unnamed_0ab"].offset] == own


def test_a_player_made_on_the_c64_still_gets_the_digest():
    """`00 00`, what each later title's GEN leaves, is still absent."""
    for game in ("curse-of-the-azure-bonds", "secret-of-the-silver-blades"):
        assert c64_codec.read(_c64(0x00, 0x00),
                              game=game).get("unnamed_0ab") is None


def test_an_amiga_player_drawn_zero_comes_back_from_the_c64():
    """The Amiga is a port whose own draw a conversion back keeps."""
    player = next(m for m in _evoker_party() if m.raw[0xF7] < 0x80)
    assert _via_c64(_with_picture(player, 0x00)) == 0x00


def test_an_amiga_player_comes_back_from_the_c64_with_his_own_draw():
    """Every member of EVOKER's party but him is a player with a real draw."""
    players = [m for m in _evoker_party() if m.raw[0xF7] < 0x80]
    assert len(players) == 4
    for char in players:
        assert _via_c64(char) == char.raw[AMIGA_PICTURE], char.name


def test_the_party_tie_break_still_moves_a_returned_duplicate():
    """Two same-named players come back from the C64 with the same draw: the
    first keeps it and the tie-break moves the second."""
    built = []
    for _ in range(2):
        record = _dos_curse(0x00, 0x42, b"DUPLICO")
        char = dos_codec.to_neutral(dos_codec.DosCharacter(record))
        rec, _ = c64_codec.write(char)
        back, _, _, _ = dos_codec.write(c64_codec.read(rec, game=char.game),
                                        deltas=CURSE)
        built.append((None, back, b"", b"", None))
    out = dos_codec._deduplicate_party_identities(built, CURSE)
    first, second = (r[PICTURE.offset] for _, r, *_ in out)
    assert first == 0x42
    assert second != 0x42


# --- The editor's rewrite keeps a raised player's picture -------------------
# A gold edit renders the record through the C64 record the sheet binds to.
# A taken-over player drawn 0 has nothing there the C64 reader returns, so
# `goldbox.rewrite` gives each rendering the record's own byte.

def test_a_dos_rewrite_keeps_a_raised_player_s_picture():
    from goldbox import rewrite
    from goldbox.c64_port import by_key
    original = dos_codec.DosCharacter(_dos_curse(0xB3, 0x00, b"RANGER"))
    before, _ = dos_codec.to_c64_record(original)
    after = CharacterRecord(before.to_bytes(), before.stored_size)
    after.gold = 1234
    out = rewrite.rewrite_dos(original, before, after, by_key(CURSE.key))
    assert out.record[PICTURE.offset] == 0x00
    assert "gold" in out.moved


def test_an_amiga_rewrite_keeps_a_raised_player_s_picture():
    """The Amiga record keeps the byte at `$127`, one past DOS's 0x126."""
    from goldbox import amiga_port, rewrite
    from goldbox.c64_port import by_key
    deltas = amiga_port.CURSE_DELTAS
    raw = bytearray(deltas.record_size)
    raw[0:6] = b"RANGER"
    raw[deltas.offset(0xF7)] = 0xB3
    raw[deltas.offset(PICTURE.offset)] = 0x00
    assert deltas.offset(PICTURE.offset) == AMIGA_PICTURE
    original = amiga_later.AmigaCharacter.from_bytes(bytes(raw), deltas)
    before, _ = dos_codec.neutral_to_c64_record(
        amiga_later.to_neutral_later(original))
    after = CharacterRecord(before.to_bytes(), before.stored_size)
    after.gold = 1234
    out = rewrite.rewrite_amiga_later(original, before, after,
                                      by_key(CURSE.key))
    assert out.character.raw[AMIGA_PICTURE] == 0x00
    assert out.character.raw[deltas.offset(0xF7)] == 0xB3
