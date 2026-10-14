"""A companion converted between DOS and the C64 gets the figure size his
destination port's own join writes.

The C64 join copies `0x099` of his `MON` file (1 in every joinable Curse and
Silver Blades file); the DOS join copies the size of his `MON*CHA.DAX` record
(0), and the Amiga join that of his `MONCHA.GLB` record (0).  A player's size
converts as before.  The tests read the player's own
disks and the specimen tree, and skip without them.
"""

from __future__ import annotations

import functools

import gamedata
import pytest
from conftest import load_tools_module
from support import silverblades

from goldbox import amiga_later, c64_codec, dos_codec, dos_port
from goldbox.companions import (
    COMPANION_SIZE,
    CURSE_KEY,
    JOINABLE,
    MON_SIZE,
    SILVER_BLADES_KEY,
    Companions,
    companion_size,
)
from goldbox.d64 import split_load_address
from tests.convert import test_companionc64 as c64_tests

convertrun = load_tools_module("convertrun")

TILVERTON_JOIN = "curse-tilverton-alias-dragonbait-dos"
PIT_JOIN = "curse-pit-join-alias-dragonbait-dos"
PIT_SLOT = "D"
SIZE_OFFSET = 0x099


def _disks(key):
    return (gamedata.curse_disks() if key == CURSE_KEY
            else silverblades.ssb_disks())


@functools.lru_cache(maxsize=None)
def _table(key) -> Companions:
    return Companions.load(key, _disks(key))


def test_the_table_names_the_value_per_title_and_port():
    assert companion_size(CURSE_KEY, "C64") == 1
    assert companion_size(CURSE_KEY, "DOS") == 0
    assert companion_size(SILVER_BLADES_KEY, "C64") == 1
    assert companion_size(CURSE_KEY, "Amiga") == 0
    assert companion_size(SILVER_BLADES_KEY, "Amiga") == 0
    assert companion_size("pool-of-radiance", "C64") is None


@pytest.mark.parametrize("key", sorted(JOINABLE))
def test_the_c64_value_is_what_every_joinable_mon_file_holds(key):
    sizes = set()
    for mon_id in JOINABLE[key]:
        for disk in _disks(key):
            if disk.find(f"MON{mon_id:02X}".encode()):
                payload = split_load_address(
                    disk.read_file(f"MON{mon_id:02X}".encode()))[1]
                assert len(payload) == MON_SIZE
                sizes.add(payload[SIZE_OFFSET])
                break
    assert sizes == {COMPANION_SIZE[key]["C64"]}


def test_a_dos_companion_gets_the_c64_join_size_and_a_player_keeps_his():
    """Fails without the fix: ALIAS's DOS 0 became C64 0."""
    folder = gamedata.specimen(PIT_JOIN)
    table = _table(CURSE_KEY)
    party = dos_codec.read_party(folder, PIT_SLOT)
    seen = {"companion": 0, "player": 0}
    for char in party:
        neutral = dos_codec.to_neutral(char)
        rec, _ = c64_codec.write(neutral, icon=table.default_icon,
                                 companions=table)
        if str(neutral.get("name")) in ("ALIAS", "DRAGONBAIT"):
            assert char.get("size") == 0
            assert rec.get("size_small") == 1
            assert rec.to_bytes()[SIZE_OFFSET] == 1
            seen["companion"] += 1
        else:
            assert rec.get("size_small") == max(0, char.get("size") - 1)
            seen["player"] += 1
    assert seen["companion"] == 2 and seen["player"] >= 1


@pytest.mark.parametrize("key, name, mon_id, story", c64_tests.CASES,
                         ids=c64_tests.IDS)
def test_a_c64_companion_gets_the_dos_join_size(key, name, mon_id, story):
    """Fails without the fix: the C64's 1 became DOS 2."""
    char = c64_codec.read(c64_tests._join(key, mon_id), game=key,
                          companions=_table(key))
    char.set("treasure_share", 0, "test") if "treasure_share" in char.fields else None
    back, _, _, _ = dos_codec.write(char, deltas=c64_tests.DEFAULTS[key])
    f = dos_port.FIELDS_BY_NAME_FOR[key]["size"]
    assert back[f.offset] == COMPANION_SIZE[key]["DOS"] == 0


def test_a_c64_player_character_keeps_the_plus_one():
    key = CURSE_KEY
    rec = c64_tests._join(key, 0x16)
    rec.set("flags_0b8", 0)
    rec.set("size_small", 1)
    char = c64_codec.read(rec, game=key, companions=_table(key))
    assert not char.get("npc")
    back, _, _, _ = dos_codec.write(char, deltas=c64_tests.DEFAULTS[key])
    f = dos_port.FIELDS_BY_NAME_FOR[key]["size"]
    assert back[f.offset] == 2


def test_an_npc_who_is_not_a_joinable_companion_keeps_the_existing_rule():
    """Only the joinable companions' sizes are measured, so another npc's
    picture keeps the rule that converts a player's size."""
    key = CURSE_KEY
    table = _table(key)
    stray = 0x01
    assert stray not in JOINABLE[key]
    char = c64_codec.read(c64_tests._join(key, 0x16), game=key, companions=table)
    char.set("unnamed_0ab", stray, "test")
    if "treasure_share" in char.fields:
        char.set("treasure_share", 0, "test")
    back, _, _, _ = dos_codec.write(char, deltas=c64_tests.DEFAULTS[key])
    f = dos_port.FIELDS_BY_NAME_FOR[key]["size"]
    assert back[f.offset] == 2

    party = dos_codec.read_party(gamedata.specimen(PIT_JOIN), PIT_SLOT)
    alias = next(c for c in party
                 if str(dos_codec.to_neutral(c).get("name")) == "ALIAS")
    neutral = dos_codec.to_neutral(alias)
    neutral.set("unnamed_0ab", stray, "test")
    rec, _ = c64_codec.write(neutral, icon=table.default_icon, companions=table)
    assert rec.to_bytes()[SIZE_OFFSET] == 0


@pytest.mark.parametrize("size_small", [0, 1])
def test_a_c64_player_keeps_his_size_on_dos(size_small):
    key = CURSE_KEY
    rec = c64_tests._join(key, 0x16)
    rec.set("flags_0b8", 0)
    rec.set("size_small", size_small)
    char = c64_codec.read(rec, game=key, companions=_table(key))
    assert not char.get("npc")
    back, _, _, _ = dos_codec.write(char, deltas=c64_tests.DEFAULTS[key])
    f = dos_port.FIELDS_BY_NAME_FOR[key]["size"]
    assert back[f.offset] == size_small + 1


def test_a_pools_of_darkness_npc_is_not_a_joined_companion():
    """Pools of Darkness has no C64 port, so it has no joinable row."""
    from goldbox.neutral import NeutralCharacter

    char = NeutralCharacter("DOS", source="made up", game="pools-of-darkness")
    char.set("npc", True, "made up")
    char.set("unnamed_0ab", 0x16, "made up")
    assert c64_codec.joined_companion(char) is False


@pytest.mark.parametrize("key, name, mon_id, story", c64_tests.CASES,
                         ids=c64_tests.IDS)
def test_a_c64_companion_gets_the_amiga_join_size(key, name, mon_id, story):
    """Fails without the fix: the C64's 1 became Amiga 2."""
    char = c64_codec.read(c64_tests._join(key, mon_id), game=key,
                          companions=_table(key))
    if "treasure_share" in char.fields:
        char.set("treasure_share", 0, "test")
    built, _ = amiga_later.write_later(char, key)
    back = amiga_later.to_neutral_later(built)
    assert back.get("size_small") == companion_size(key, "Amiga") == 0


def test_a_c64_player_keeps_his_size_on_the_amiga():
    key = CURSE_KEY
    rec = c64_tests._join(key, 0x16)
    rec.set("flags_0b8", 0)
    rec.set("size_small", 1)
    char = c64_codec.read(rec, game=key, companions=_table(key))
    assert not char.get("npc")
    built, _ = amiga_later.write_later(char, key)
    assert amiga_later.to_neutral_later(built).get("size_small") == 1


def test_a_dos_curse_party_with_two_companions_saves_as_amiga(tmp_path):
    """Fails without the fix: the sheet reads a DOS companion's size as the
    C64 join's 1, the Amiga read-back as 0, and Save As stopped on
    `size_small: 1 arrived as 0`."""
    from tools.convert import convertdrops

    source = gamedata.specimen(TILVERTON_JOIN)
    two = convertdrops.amiga_game_disks(tmp_path).get(CURSE_KEY)
    one = convertdrops.amiga_disks_one(tmp_path).get(CURSE_KEY)
    if two is None or one is None:
        pytest.skip("needs Curse's own Amiga disks 1 and 2")
    rc = convertrun.main(["--source", str(source), "--source-slot", "D",
                          "--to", "amiga", "--amiga-disk", str(two),
                          "--amiga-disk-one", str(one),
                          "--out", str(tmp_path / "out"), "--no-play"])
    assert rc == 0
    assert len(list((tmp_path / "out").rglob("*.ADF"))) == 1
