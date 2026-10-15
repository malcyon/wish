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


@pytest.mark.skipif(not ALIAS_SAV.exists(),
                    reason="needs the WISH-387 Amiga-to-DOS re-save")
@gamedata.needs_curse_disks
def test_the_converter_path_reads_the_item_table_for_curse(tmp_path):
    """What `convertrun --to c64` and Save As do: the game files come off the
    player's folder through `saveplan`, and the table must be among them or
    ALIAS arrives with a zero 0x0EC and the strength-only byte."""
    import shutil

    from editor import dosimport, saveplan
    from goldbox import c64_port
    from goldbox.savegame import SaveGame1

    game = c64_port.by_key(CURSE)
    files = saveplan._game_files_from_folder(gamedata.curse_dir(), game)
    assert files is not None
    folder = tmp_path / "dos"
    folder.mkdir()
    for path in ALIAS_SAV.parent.iterdir():
        shutil.copy(path, folder / path.name)
    conversion = dosimport.rehearse(folder, "D", files)
    slot = next(s for s in conversion.save0.slots if s.occupied
                if s.record.name == "ALIAS")
    assert slot.record.get("missile_attack_adjustment") == 2
    roster = SaveGame1(conversion.save0.roster_page(), game)
    block = next(b for b in roster.roster_blocks
                 if b.slot_index == slot.index)
    assert block.thac0 == 13


def _armour_only_alias():
    """A Curse character with body armour readied and no weapon: the weapon
    hand is empty, which is the `LIBRARY $387E` entry's `JMP $3914` unarmed
    path whatever else is worn."""
    char = NeutralCharacter("ALIAS", source="made up", game=CURSE)
    for name, value in (("levels", {"fighter": 6}), ("strength", 18),
                        ("exceptional_strength", 0), ("dexterity", 17),
                        ("thac0_base", COMBAT_BIAS - 15),
                        ("thac0_current", COMBAT_BIAS - 14),
                        ("attack_forms", bytes([0, 0, 1, 0, 2, 0, 0, 0])),
                        ("roster_tail", bytes([0x30, 0, 0, 9, 9, 9, 9, 9, 9])),
                        ("inventory", [_item(5)])):
        char.set(name, value, "made up")
    return char


def test_a_readied_suit_of_armour_alone_gets_the_unarmed_attack_bytes():
    """Roster tail bytes 3-8 are the attack dice plus the strength damage
    step (+2 for 18) -- the engine's unarmed result -- not the source's."""
    types = dict(_TYPES)
    types[5] = _type(0x00, location=2)
    rec, _ = c64_codec.write(_armour_only_alias(), item_types=types)
    assert rec.get_raw("roster_tail")[3:9] == bytes([1, 0, 2, 0, 2, 0])


@pytest.mark.skipif(gamedata.specimen_root() is None,
                    reason="needs the specimen tree")
@gamedata.needs_curse_disks
def test_engine_written_curse_characters_keep_their_unarmed_attack_bytes():
    """The 24 character files the C64 Curse game itself exported
    (`coab-c64` specimens, nobody readied anything): reading each and
    writing it again with the item table leaves roster tail bytes 3-8 as
    the engine wrote them."""
    from goldbox.d64 import D64
    from goldbox.record import CharacterRecord

    types = _curse_item_types()
    files = 0
    for path in sorted((gamedata.specimen_root() / "coab-c64").glob(
            "WISH-SPEC-curse-*.[dD]64")):
        disk = D64.open(str(path))
        for entry in disk.directory():
            if not entry.is_prg or entry.is_empty:
                continue
            data = disk.read_file(entry)
            if len(data) != 582 or entry.name == b"SAVEAZURE":
                continue
            try:
                record = CharacterRecord.from_prg(data, 0x7C00)
            except Exception:
                continue
            raw = record.get_raw("inventory")
            if any(raw[n * 16] and raw[n * 16 + 6] & 0x80 for n in range(16)):
                continue
            out, _ = c64_codec.write(c64_codec.read(record, source=path.name),
                                     item_types=types)
            files += 1
            assert out.to_bytes()[0x113:0x119] == record.to_bytes()[0x113:0x119], (
                path.name, record.name)
    if not files:
        pytest.skip("no engine-exported Curse character files here")
