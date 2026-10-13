"""A DOS story companion's `size` of 0 converts to the C64.

Every `MON*CHA.DAX` record the DOS game ships holds 0 in `size`, and a join
copies it unchanged, so ALIAS and DRAGONBAIT hold 0 in any DOS party the game
saves after the Pit of Moander.  No DOS figure is composed from that byte, and
the C64 join gives a companion the default icon, so neither does the
conversion.  The tables come from the player's own Curse disks and the
specimen tree, and the tests skip without them.
"""

from __future__ import annotations

import functools

import gamedata
import pytest

from goldbox import c64_port, c64_save, dos_codec
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


def test_a_companions_size_names_no_figure():
    assert DOS_COMPANION_SIZE == 0
    assert dos_figure_size(DOS_COMPANION_SIZE) is None
    assert dos_figure_size(1) == dos_size(1) == "small"
    assert dos_figure_size(2) == dos_size(2) == "large"
    with pytest.raises(ValueError, match="size 3"):
        dos_figure_size(3)


def test_the_game_saved_its_companions_with_size_zero():
    """The specimen is what a player has: the game wrote it, and the size
    byte of both companions is 0 while every player's is 1 or 2."""
    folder = gamedata.specimen(PIT_JOIN)
    party = dos_codec.read_party(folder, PIT_SLOT)
    sizes = {c.name: c.get("size") for c in party}
    assert {sizes[name] for name in JOINED} == {DOS_COMPANION_SIZE}
    assert {s for n, s in sizes.items() if n not in JOINED} <= {1, 2}


def test_the_pit_join_party_converts_to_the_c64():
    """Fails without the fix: `dos_size(0)` raised while composing ALIAS's
    figure, so no C64 save was written for this party at all."""
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
