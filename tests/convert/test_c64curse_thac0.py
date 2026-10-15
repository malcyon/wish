"""A Curse character converted to the C64 arrives with his readied weapon's THAC0.

`LIBRARY $3918` (weapon block `$387E`) adds record `0x0EC` for a weapon whose
item-type flag has bit 1 and the strength step for bit 2, and `COM.PREP $1740`
caches `0x0EC` from the dexterity table at `$178B`. The writer used to store `0x0EC` as 0 and base
plus strength whatever was readied, so a bowman showed one point worse than the
game computes.
"""

from __future__ import annotations

import pathlib

import gamedata
import pytest

from goldbox import c64_codec, derive, dos_codec
from goldbox.encoding import COMBAT_BIAS
from goldbox.items import (
    TYPE_LOCATION,
    TYPE_WEAPON_FLAGS,
    ItemType,
    load_item_types,
)
from goldbox.neutral import NeutralCharacter

CURSE = "curse-of-the-azure-bonds"

#: ALIAS in the DOS save the WISH-387 Amiga-to-DOS leg re-saved, with his bow
#: readied; written by this project's DOS writer, so evidence about the
#: conversion's input and not about the game.
ALIAS_SAV = pathlib.Path("~/.cache/wish/acceptance/387/532aba3536-a2-amiga-to-dos"
                         "/resave/CHRDATD7.SAV").expanduser()


def _type(flags: int, location: int = 0) -> ItemType:
    raw = bytearray(16)
    raw[TYPE_LOCATION] = location
    raw[TYPE_WEAPON_FLAGS] = flags
    return ItemType(0, bytes(raw))


def _item(type_index: int) -> bytes:
    raw = bytearray(16)
    raw[0] = type_index
    raw[6] = 0x80
    return bytes(raw)


#: 1 a long sword (`$04`, strength only), 2 a composite bow (`$0B`, missile
#: and arrows, no strength), 0x49 arrows.
_TYPES = {1: _type(0x04), 2: _type(0x0B), 0x49: _type(0x00, location=10)}


def _alias(item: int):
    char = NeutralCharacter("ALIAS", source="made up", game=CURSE)
    for name, value in (("levels", {"fighter": 6}), ("strength", 17),
                        ("exceptional_strength", 0), ("dexterity", 17),
                        ("thac0_base", COMBAT_BIAS - 15),
                        ("thac0_current", COMBAT_BIAS - 14),
                        ("inventory", [_item(item)])):
        char.set(name, value, "made up")
    rec, _ = c64_codec.write(char, item_types=_TYPES)
    return rec


def test_a_curse_bow_takes_the_dexterity_step_and_not_strength():
    rec = _alias(2)
    assert rec.get("missile_attack_adjustment") == 2
    assert rec.get("thac0") == rec.get("thac0_base") + 2


def test_a_curse_long_sword_takes_the_strength_step_only():
    rec = _alias(1)
    hit, _ = derive.strength_bonuses(17, 0)
    assert rec.get("missile_attack_adjustment") == 2
    assert rec.get("thac0") == rec.get("thac0_base") + hit


def _curse_item_types():
    for disk in gamedata.curse_disks():
        try:
            return load_item_types(disk)
        except Exception:
            continue
    pytest.skip("no Curse disk carries ITEMS")


@pytest.mark.skipif(not ALIAS_SAV.exists(),
                    reason="needs the WISH-387 Amiga-to-DOS re-save")
@gamedata.needs_curse_disks
def test_the_converted_alias_with_his_bow_arrives_at_thac0_13():
    """The record the bow-readied sheet reads: `0x0EC` 2 and THAC0 13 (byte
    0x2F), the number both games compute for him."""
    char = dos_codec.read_character(ALIAS_SAV)
    rec, _ = dos_codec.to_c64_record(char, item_types=_curse_item_types())
    assert rec.get("missile_attack_adjustment") == 2
    assert rec.get("thac0") == COMBAT_BIAS - 13
