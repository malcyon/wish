"""A DOS story companion's `size` of 0 converts to the C64.

Every `MON*CHA.DAX` record the DOS game ships holds 0 in `size`, and a join
copies it unchanged, so ALIAS and DRAGONBAIT hold 0 in any DOS party the game
saves after the Pit of Moander.  No DOS figure is composed from that byte, and
the C64 join gives a companion the default icon, so neither does the
conversion.  A player's figure is 1 small or 2 medium, and any other value in
a player's record stops the conversion.  The tables come from the player's own
Curse disks and the specimen tree, and the tests skip without them.
"""

from __future__ import annotations

import functools

import gamedata
import pytest

from goldbox import (
    c64_codec,
    c64_port,
    c64_save,
    dos_codec,
    dos_port,
    dos_savegame,
    world_state,
)
from goldbox.companions import CURSE_KEY, Companions
from goldbox.iconparts import (
    DOS_COMPANION_SIZE,
    IconParts,
    dos_figure_size,
    dos_size,
)
from goldbox.record import CharacterRecord

#: The DOS Curse party the game saved after ALIAS and DRAGONBAIT joined.
PIT_JOIN = "curse-pit-join-alias-dragonbait-dos"
PIT_SLOT = "D"
#: Name, `MON` id and the story byte his own C64 file holds.
JOINED = {"ALIAS": (0x16, 0x16), "DRAGONBAIT": (0x17, 0x17)}
FIELDS = dos_port.FIELDS_BY_NAME_FOR[CURSE_KEY]
CURSE_C64 = c64_port.CURSE_OF_THE_AZURE_BONDS


@functools.lru_cache(maxsize=None)
def _disks():
    return tuple(gamedata.curse_disks())


@functools.lru_cache(maxsize=None)
def _table() -> Companions:
    return Companions.load(CURSE_KEY, _disks())


@functools.lru_cache(maxsize=None)
def _parts() -> IconParts:
    for disk in _disks():
        if disk.find(b"SPELLE64") and disk.find(b"SPELLN64"):
            return IconParts.load(disk)
    pytest.skip("no Curse side here carries the icon option tables")


def _edited(char: dos_codec.DosCharacter, **at: int) -> dos_codec.DosCharacter:
    """`char`'s record with the named fields set to new bytes."""
    raw = bytearray(char.to_bytes())
    for name, value in at.items():
        raw[FIELDS[name].offset] = value
    return dos_codec.DosCharacter(bytes(raw))


def _renamed(char: dos_codec.DosCharacter, name: bytes) -> dos_codec.DosCharacter:
    raw = bytearray(char.to_bytes())
    raw[0] = len(name)
    raw[1:16] = name.ljust(15, b"\0")
    return dos_codec.DosCharacter(bytes(raw))


def _convert(party, companions):
    """`new_save` for an edited party: the specimen's own place and clock."""
    folder = gamedata.specimen(PIT_JOIN)
    container = c64_save.container_for(CURSE_C64)
    dos_container = dos_savegame.container_for(container.key)
    path = dos_savegame.save_file(
        folder, f"SAVGAM{PIT_SLOT}{dos_container.suffix}")
    state = world_state.from_dos(path.read_bytes(), dos_container,
                                 source=str(path))
    save0, _save1, report = dos_codec.new_save_from(
        state, party, _parts(), animate=None, game=CURSE_C64,
        companions=companions)
    return save0, report


def _figure(save0, party, index: int) -> bytes:
    container = c64_save.container_for(CURSE_C64)
    at = container.icon(dos_codec.marching_slot(index, len(party)))
    return bytes(save0[at:at + container.icon_size])


def test_only_a_companions_zero_names_no_figure():
    assert DOS_COMPANION_SIZE == 0
    assert dos_figure_size(DOS_COMPANION_SIZE, companion=True) is None
    for companion in (False, True):
        assert dos_figure_size(1, companion) == dos_size(1) == "small"
        assert dos_figure_size(2, companion) == dos_size(2) == "large"
        with pytest.raises(ValueError, match="size 3"):
            dos_figure_size(3, companion)
    with pytest.raises(ValueError, match="size 0"):
        dos_figure_size(DOS_COMPANION_SIZE, companion=False)


def test_the_game_saved_its_companions_with_size_zero():
    """The specimen is what a player has: the game wrote it, and the size
    byte of both companions is 0 while every player's is 1 or 2."""
    folder = gamedata.specimen(PIT_JOIN)
    party = dos_codec.read_party(folder, PIT_SLOT)
    sizes = {c.name: c.get("size") for c in party}
    assert {sizes[name] for name in JOINED} == {DOS_COMPANION_SIZE}
    assert {s for n, s in sizes.items() if n not in JOINED} <= {1, 2}


def test_the_pit_join_party_converts_to_the_c64():
    """ALIAS and DRAGONBAIT arrive with their story bytes, pictures and the
    default icon, and the players keep their own figures."""
    folder = gamedata.specimen(PIT_JOIN)
    table = _table()
    save0, _save1, report = dos_codec.new_save(
        folder, PIT_SLOT, _parts(), animate=None,
        game=c64_port.CURSE_OF_THE_AZURE_BONDS, companions=table)
    assert report.unwritten == []
    container = c64_save.container_for(c64_port.CURSE_OF_THE_AZURE_BONDS)
    party = dos_codec.read_party(folder, PIT_SLOT)
    seen = {}
    for place in range(len(party)):
        at = container.slot(place)
        rec = CharacterRecord(bytes(save0[at:at + CharacterRecord.SIZE]))
        icon = bytes(save0[container.icon(place):
                           container.icon(place) + container.icon_size])
        seen[rec.get("name")] = (rec.get("story_picture"),
                                 rec.get_raw("identity_pair"), icon)
    for name, (mon_id, story) in JOINED.items():
        got_story, pair, icon = seen[name]
        assert got_story == story, name
        assert pair[0] == mon_id, name
        assert icon == table.default_icon, name
    players = [icon for name, (_s, _p, icon) in seen.items()
               if name not in JOINED]
    assert len(set(players)) > 1, "the players lost their own figures"


@pytest.mark.parametrize("size", [0, 3])
def test_a_players_size_outside_one_and_two_stops_the_conversion(size):
    """A player's figure is composed from his size, so a value naming no
    figure stops the C64 save rather than becoming the default icon."""
    party = dos_codec.read_party(gamedata.specimen(PIT_JOIN), PIT_SLOT)
    index = next(i for i, c in enumerate(party) if c.name not in JOINED)
    party[index] = _edited(party[index], size=size)
    with pytest.raises(ValueError, match=f"DOS size {size} "):
        _convert(party, _table())


def test_a_taken_over_player_with_size_zero_stops_the_conversion():
    """Control `$B3` is a player the engine drives, not a companion the join
    added (`c64_codec.joined_companion`), so his 0 is a player's 0."""
    party = dos_codec.read_party(gamedata.specimen(PIT_JOIN), PIT_SLOT)
    index = next(i for i, c in enumerate(party) if c.name == "ALIAS")
    raw = bytearray(party[index].to_bytes())
    f83 = FIELDS["field_83_87"]
    raw[f83.offset + (1 if f83.size == 5 else 0)] = c64_codec.DOS_PC_TAKEN_OVER
    party[index] = dos_codec.DosCharacter(bytes(raw))
    assert party[index].get("size") == DOS_COMPANION_SIZE
    # The control byte is the only difference: picture and title still name
    # a joinable companion, and only `$B3` makes him a player.
    taken_over = dos_codec.to_neutral(party[index])
    assert taken_over.get("unnamed_0ab") == JOINED["ALIAS"][0]
    assert taken_over.get("npc_control_byte") == c64_codec.DOS_PC_TAKEN_OVER
    assert not c64_codec.joined_companion(taken_over)
    with pytest.raises(ValueError, match="DOS size 0 "):
        _convert(party, _table())


def test_the_joined_companions_are_companions_on_the_whole_route():
    """The game's own ALIAS and DRAGONBAIT, read through `to_neutral` and
    written by `write_c64_save` with nothing built by hand: both are joined
    companions, both read size_small 0 with no drop, and both get the
    default icon."""
    party = dos_codec.read_party(gamedata.specimen(PIT_JOIN), PIT_SLOT)
    joined = [i for i, c in enumerate(party) if c.name in JOINED]
    assert len(joined) == len(JOINED)
    for index in joined:
        neutral = dos_codec.to_neutral(party[index])
        assert c64_codec.joined_companion(neutral), party[index].name
        assert neutral.get("size_small") == 0, party[index].name
        assert not any("figure's size" in line for line in neutral.dropped)
    save0, report = _convert(party, _table())
    assert report.unwritten == []
    for index in joined:
        assert _figure(save0, party, index) == _parts().default_icon()


def test_a_players_size_outside_one_and_two_is_reported_not_rounded():
    party = dos_codec.read_party(gamedata.specimen(PIT_JOIN), PIT_SLOT)
    player = next(c for c in party if c.name not in JOINED)
    neutral = dos_codec.to_neutral(_edited(player, size=0))
    assert neutral.get("size_small") is None
    assert any("figure's size" in line for line in neutral.dropped)
    companion = next(c for c in party if c.name == "ALIAS")
    neutral = dos_codec.to_neutral(companion)
    assert neutral.get("size_small") == 0
    assert not any("figure's size" in line for line in neutral.dropped)


def _unmatched_by_name(party):
    index = next(i for i, c in enumerate(party) if c.name == "ALIAS")
    party[index] = _renamed(party[index], b"WORG")
    return party, index, _table()


def _unmatched_by_picture(party):
    index = next(i for i, c in enumerate(party) if c.name == "ALIAS")
    party[index] = _edited(party[index], unnamed_0ab=JOINED["DRAGONBAIT"][0])
    return party, index, _table()


def _unjoinable_picture(party):
    """A picture no join writes: not a joined companion, still drawn from
    CPIC by the DOS load like any member above control `$80`."""
    index = next(i for i, c in enumerate(party) if c.name == "ALIAS")
    party[index] = _edited(party[index], unnamed_0ab=0x01)
    neutral = dos_codec.to_neutral(party[index])
    assert not c64_codec.joined_companion(neutral)
    assert c64_codec.picture_companion(neutral)
    return party, index, _table()


def _no_table(party):
    return party, next(i for i, c in enumerate(party) if c.name == "ALIAS"), None


@pytest.mark.parametrize("unmatch", [_unmatched_by_name, _unmatched_by_picture,
                                     _unjoinable_picture, _no_table],
                         ids=["name", "picture", "unjoinable-picture",
                              "no-table"])
def test_an_unmatched_companion_gets_the_default_icon(unmatch):
    """DOS draws every companion from `CPIC` by his picture, so his record's
    head, body and colours name no figure the game ever drew.  Unmatched by
    the companion table, he still has no figure of his own, and gets the icon
    a C64 join leaves him."""
    party = dos_codec.read_party(gamedata.specimen(PIT_JOIN), PIT_SLOT)
    party, index, companions = unmatch(party)
    save0, report = _convert(party, companions)
    assert report.unwritten == []
    assert _figure(save0, party, index) == _parts().default_icon()


#: The Pools of Darkness party in which PRIAM joined through the developers'
#: tester: control `$B2`, picture `$71`, size 0, written by the game.
POD_PRIAM = ("pod-dos", "WISH-SPEC-wish331-pod-tester-anpc-113-dos",
             "CHRDATE7.SAV")


def test_a_pools_of_darkness_companion_keeps_his_size_zero():
    """Pools of Darkness has no joinable table, but its load draws PRIAM from
    CPIC as Curse's does (`GAME.OVR 0x12F52`), so his 0 is a companion's and
    crosses unchanged rather than as a player's drop."""
    root = gamedata.specimen_root()
    path = root.joinpath(*POD_PRIAM) if root is not None else None
    if path is None or not path.is_file():
        pytest.skip(f"needs specimen {POD_PRIAM[1]}")
    priam = dos_codec.read_character(path)
    assert priam.get("size") == DOS_COMPANION_SIZE
    neutral = dos_codec.to_neutral(priam)
    assert c64_codec.picture_companion(neutral)
    assert not c64_codec.joined_companion(neutral)
    assert neutral.get("size_small") == 0
    assert not any("figure's size" in line for line in neutral.dropped)
    deltas = dos_port.POOLS_OF_DARKNESS
    back, _, _, _ = dos_codec.write(neutral, deltas=deltas)
    size = dos_port.FIELDS_BY_NAME_FOR[deltas.key]["size"]
    assert back[size.offset] == DOS_COMPANION_SIZE
