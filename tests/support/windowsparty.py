"""Helpers `test_windowslayout` shares with the test files that reuse them."""
from __future__ import annotations

import pathlib


def _ordinary_party(tmp_path) -> str:
    """Six characters at a size a player would actually see, not the widest
    the format allows -- `gamedata.synthetic_party`'s widest-of-everything
    shape is for a different question (`tests/wish/test_mapscale.py`, `#71`) and
    would make the Name and Class columns dwarf their own headings, which is
    not the case this bug is about.
    """
    import gamedata

    from goldbox import c64_port
    from goldbox.d64 import attach_load_address
    from goldbox.encoding import COMBAT_BIAS
    from goldbox.record import CharacterRecord
    from goldbox.savegame import (
        HEADER_SIZE,
        ROSTER_ARMOUR_CLASS,
        ROSTER_HP_CURRENT,
        ROSTER_MOVEMENT,
        ROSTER_SLOT_INDEX,
        ROSTER_STRIDE,
        ROSTER_THAC0,
        SLOT_STRIDE,
    )

    game = c64_port.POOL_OF_RADIANCE
    record = CharacterRecord.blank()
    record.set("name", "Grix")
    for ability in ("strength", "intelligence", "wisdom", "dexterity",
                    "constitution", "charisma"):
        record.set(ability, 15)
    record.set("race", 1)          # dwarf
    record.set("class_bits", 8)    # fighter
    record.set("hp_max", 8)
    head = record.to_bytes()[:SLOT_STRIDE]

    payload = bytearray(game.save_size)
    roster = bytearray(game.roster_size)
    for i in range(6):
        payload[HEADER_SIZE + i * SLOT_STRIDE:
                HEADER_SIZE + (i + 1) * SLOT_STRIDE] = head
        at = i * ROSTER_STRIDE
        roster[at + ROSTER_SLOT_INDEX] = i
        roster[at + ROSTER_THAC0] = COMBAT_BIAS - 2
        roster[at + ROSTER_ARMOUR_CLASS] = COMBAT_BIAS - 8
        roster[at + ROSTER_HP_CURRENT] = 8
        roster[at + ROSTER_MOVEMENT] = 12
    if game.roster_in_payload:
        payload[game.roster_offset:game.roster_offset + game.roster_size] = roster
        files = [(game.save_file,
                  attach_load_address(game.save_load_address, bytes(payload)))]
    else:
        files = [(game.save_file,
                  attach_load_address(game.save_load_address, bytes(payload))),
                 (game.roster_file,
                  attach_load_address(game.roster_load_address, bytes(roster)))]
    disk = pathlib.Path(tmp_path) / "ORDINARY.D64"
    disk.write_bytes(gamedata._disk_with(files))
    return str(disk)
