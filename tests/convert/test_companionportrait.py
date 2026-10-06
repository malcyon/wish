"""A companion's sheet portrait crosses ports as the byte its own record holds.

The game's NPC records hold one portrait byte on all three ports, and DOS and
the Amiga draw it by indexing off the end of the creation menu's tables, so it
is not a menu position.  A player character keeps the menu-position mapping.
"""

from __future__ import annotations

import pytest
from gamedata import npc_party_disk

from goldbox import amiga_por, c64_codec, dos_codec, dos_port
from goldbox.d64 import D64
from goldbox.portraits import PortraitTables, neutral_menu
from goldbox.savegame import SaveGame0

POR = dos_port.POOL_OF_RADIANCE
HEAD = dos_codec.FIELDS_BY_NAME["portrait_head"].offset
BODY = dos_codec.FIELDS_BY_NAME["portrait_body"].offset

#: The Amiga Pool record holds the pair two bytes later than DOS.
AMIGA_HEAD, AMIGA_BODY = HEAD + 2, BODY + 2

MENU = PortraitTables(heads=tuple(range(0x10, 0x10 + 14)),
                      bodies=tuple(range(0x01, 0x0D)),
                      source="synthetic, for this test")


def _neutral(head, body, npc, control=None):
    char = dos_codec.to_neutral(
        dos_codec.DosCharacter(bytes(POR.record_size), deltas=POR),
        portraits=MENU)
    char.set("npc", npc, "test")
    if control is not None:
        char.set("npc_control_byte", control, "test")
    char.set("portrait_head", head, "test")
    char.set("portrait_body", body, "test")
    return char


def _portrait_drops(rep):
    return [d for d in rep.dropped if "portrait" in d.lower()]


@pytest.mark.parametrize("head,body", [(35, 3), (32, 3), (0, 4), (255, 255)])
def test_a_companion_portrait_pair_round_trips_through_dos_unchanged(head, body):
    char = _neutral(head, body, True, 0xB2)
    rec, _itm, _spc, rep = dos_codec.write(char, portraits=MENU)
    assert (rec[HEAD], rec[BODY]) == (head, body)
    assert not _portrait_drops(rep), rep.dropped
    back = dos_codec.to_neutral(dos_codec.DosCharacter(rec, deltas=POR),
                                portraits=MENU)
    assert (back.get("portrait_head"), back.get("portrait_body")) == (head, body)


def test_a_companion_portrait_pair_crosses_to_the_amiga_unchanged():
    char = _neutral(35, 3, True, 0xB2)
    record, _itm, _spc, rep = amiga_por.write_por(char)
    assert not _portrait_drops(rep), rep.dropped
    assert (record[AMIGA_HEAD], record[AMIGA_BODY]) == (35, 3)


def test_a_player_character_keeps_the_menu_position_mapping():
    char = _neutral(0x12, 4, False)
    rec, _itm, _spc, _rep = dos_codec.write(char, portraits=MENU)
    assert (rec[HEAD], rec[BODY]) == (3, 4)


def test_a_player_character_outside_the_menu_is_still_reported():
    char = _neutral(35, 3, False)
    rec, _itm, _spc, rep = dos_codec.write(char, portraits=MENU)
    assert rec[HEAD] == 0
    assert _portrait_drops(rep)


def test_a_character_the_game_has_taken_over_keeps_the_mapping():
    char = _neutral(0x12, 4, True, c64_codec.DOS_PC_TAKEN_OVER)
    rec, _itm, _spc, _rep = dos_codec.write(char, portraits=MENU)
    assert (rec[HEAD], rec[BODY]) == (3, 4)


def test_a_dos_pc_record_reads_through_the_menu_and_a_companion_raw():
    pc = _neutral(0x12, 4, False)
    rec, *_ = dos_codec.write(pc, portraits=MENU)
    back = dos_codec.to_neutral(dos_codec.DosCharacter(rec, deltas=POR),
                                portraits=MENU)
    assert back.get("portrait_head") == 0x12
    comp = _neutral(0x12, 4, True, 0xB2)
    rec, *_ = dos_codec.write(comp, portraits=MENU)
    assert (rec[HEAD], rec[BODY]) == (0x12, 4)


# -- the saved party that stopped Save As ------------------------------------

#: name -> (head, body) the C64 record holds, which every port's own record
#: for that NPC holds too.
NPC_PAIRS = {"GENHEERIS": (16, 2), "MAD MAN": (35, 3), "DIRTEN": (0, 4),
             "SKULLCRUSHER": (32, 3)}


def _npc_party():
    disk = npc_party_disk()
    if disk is None:
        pytest.skip("needs npc_party.d64 from the npc-party-save registry entry")
    img = D64.open(str(disk))
    sg0 = SaveGame0.from_prg(img.read_file(b"SAVEDGAME0"))
    return [c64_codec.read(s.record, game="pool-of-radiance")
            for s in sg0.characters]


def test_the_npc_party_converts_to_dos_with_every_companion_head_kept():
    seen = set()
    for char in _npc_party():
        rec, _itm, _spc, rep = dos_codec.write(
            char, portraits=neutral_menu(POR.key))
        assert not _portrait_drops(rep), (char.get("name"), rep.dropped)
        want = NPC_PAIRS.get(char.get("name"))
        if want:
            assert (rec[HEAD], rec[BODY]) == want, char.get("name")
            seen.add(char.get("name"))
    assert seen == set(NPC_PAIRS)


def test_the_npc_party_converts_to_the_amiga_with_every_companion_head_kept():
    seen = set()
    for char in _npc_party():
        record, _itm, _spc, rep = amiga_por.write_por(char)
        assert not _portrait_drops(rep), (char.get("name"), rep.dropped)
        want = NPC_PAIRS.get(char.get("name"))
        if want:
            assert (record[AMIGA_HEAD], record[AMIGA_BODY]) == want
            seen.add(char.get("name"))
    assert seen == set(NPC_PAIRS)
