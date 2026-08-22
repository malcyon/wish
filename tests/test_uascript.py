"""The community sources' claims, checked against the player's own disks.

Two third-party decodes of the DOS Gold Box engine -- Stephen S. Lee's Pool of
Radiance guide and Draxinusom's ImHex patterns -- describe fields this project
had down as UNKNOWN. Both are DOS work, so nothing they say is true of the
Commodore 64 until a C64 file says it is. These are the checks that made the
claims stick; `docs/128-guide-and-scripting.md` is the write-up.

Everything here reads `MON*`, `ITEMS` and `SPELLN00` off whichever `POOL` disk
carries them, and skips when the player has no disks.
"""

from __future__ import annotations

import pathlib

import pytest
from gamedata import disk_dir, game_file, needs_disks

from por.d64 import D64, split_load_address
from por.items import ItemType
from por.record import CharacterRecord
from por.savegame import SaveGame0
from por.spells import LAST_SPELL, load_spell_names

pytestmark = needs_disks

# GB_ENUM.cs `MON_TYPE`, transcribed. 5, 6 and 13 are absent from the source
# and from our data; a value outside this set would break the identification.
CREATURE_TYPES = {0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19}

# Guide section 12.4.2, GBVM $6C0C.
COMBAT_BEHAVIOUR = {0: "allied, controlled", 128: "allied, uncontrolled",
                    129: "hostile"}

# GB_ITM-Base.hexpat `ITEMDAMAGETYPE_A`.
DAMAGE_TYPES = {0: "slashing", 1: "piercing", 128: "bludgeoning"}

TYPE_DAMAGE_TYPE = 7          # unnamed in por/items.py
TYPE_WEAPON_FLAGS = 14        # likewise
WEAPON_LAUNCH_ARROW = 0x01
WEAPON_RANGED = 0x02
WEAPON_THROWN = 0x10
WEAPON_LAUNCH_BOLT = 0x80


@pytest.fixture(scope="module")
def monsters():
    """Every `MON<id>` record on every game disk, keyed by file name."""
    where = disk_dir()
    out = {}
    for path in sorted(where.glob("POOL*.[dD]64")):
        try:
            disk = D64.open(path)
        except Exception:
            continue
        for entry in disk.directory():
            if entry.name.startswith(b"MON") and len(entry.name) == 5:
                try:
                    _, payload = split_load_address(disk.read_file(entry.name))
                except Exception:
                    continue
                if len(payload) >= 0x120:
                    out[entry.name.decode()] = payload
    if not out:
        pytest.skip("no MON records on these disks")
    return out


def _named(records, wanted):
    for payload in records.values():
        if payload[:20].split(b"\x00")[0].decode("latin1") == wanted:
            return payload
    pytest.skip(f"no monster record named {wanted}")


# --- record 0x0F7: the experience a creature is worth -----------------------
# The guide puts the award at GBVM $6BF7 and the per-hit-point bonus at $6BF9,
# and the record answers to a fixed $6B00, so those are offsets 0x0F7 and
# 0x0F9. Both fell inside `gap_0f4`.

def test_experience_award_matches_the_advanced_dungeons_and_dragons_table(monsters):
    for name, base, per_hp in (("GOBLIN GUARD", 10, 1),
                               ("OGRE", 90, 5),
                               ("HOBGOBLIN", 20, 2)):
        record = _named(monsters, name)
        assert (record[0xF7] | record[0xF8] << 8, record[0xF9]) == (base, per_hp)


def test_no_player_character_carries_an_experience_award(monsters):
    """The field is a monster's, so a fresh export must read zero."""
    export = pathlib.Path("tests/fixtures/brutus.chr")
    if not export.exists():
        pytest.skip("needs the exported-character fixture")
    raw = CharacterRecord.from_prg(export.read_bytes()).to_bytes()
    assert raw[0xF7:0xFA] == b"\x00\x00\x00"


# --- record 0x0D7: what kind of creature this is ----------------------------

def test_creature_type_never_leaves_the_documented_enumeration(monsters):
    seen = {payload[0xD7] for payload in monsters.values()}
    assert seen <= CREATURE_TYPES
    assert len(seen) > 8, "too few distinct values to have identified anything"


def test_creature_type_names_the_creatures_it_should(monsters):
    assert _named(monsters, "TROLL")[0xD7] == 10           # regenerating
    assert _named(monsters, "MUMMY")[0xD7] == 4            # undead


# --- record 0x10C: hostility and autocombat, one byte -----------------------

def test_combat_behaviour_is_one_of_three_values(monsters):
    seen = {payload[0x10C] for payload in monsters.values()}
    assert seen <= set(COMBAT_BEHAVIOUR)
    assert 129 in seen, "expected most MON records to be hostile"


# --- record 0x0A1/0x0A2: drained levels and hit points ----------------------

def test_drain_fields_read_255_on_every_monster(monsters):
    assert {payload[0xA1] for payload in monsters.values()} == {255}
    assert {payload[0xA2] for payload in monsters.values()} == {255}


# --- record 0x0C9: the class-level array is indexed by class_bits -----------

def test_class_levels_are_indexed_by_the_item_usability_bit_order():
    """Magic-user, cleric, thief, fighter -- `por.items.CLASS_USAGE_BITS`.

    The DOS record orders the same eight-entry array cleric, druid, fighter,
    paladin, ranger, magic-user, thief, monk. The C64 does not, so a save
    converter has to permute it.
    """
    save = pathlib.Path("tests/fixtures/party6_savedgame0.bin")
    if not save.exists():
        pytest.skip("needs the six-character party fixture")
    expected = {5: 0, 0: 1, 2: 3}          # magic-user, cleric, fighter
    for slot in SaveGame0.from_prg(save.read_bytes()).characters:
        raw = bytes(slot.record_bytes)
        index = expected.get(raw[0x73])
        if index is None:
            continue
        levels = raw[0xC9:0xD1]
        assert levels[index] == raw[0xA0], raw[:20]
        assert sum(levels) == raw[0xA0]


# --- ITEMS +7 and +14: damage type and weapon flags -------------------------

@pytest.fixture(scope="module")
def item_types():
    data = game_file("ITEMS")
    return [data[i * 16:(i + 1) * 16] for i in range(128)]


def test_damage_type_never_leaves_the_documented_enumeration(item_types):
    seen = {raw[TYPE_DAMAGE_TYPE] for raw in item_types if any(raw)}
    assert seen <= set(DAMAGE_TYPES)
    assert seen == {0, 1, 128}


def test_every_weapon_with_a_range_is_flagged_ranged_or_thrown(item_types):
    """+12 is a range only on a weapon; on a wand it is something else.

    The converse holds too, with one exception: the bec de corbin carries the
    thrown bit and no range at all.
    """
    at_a_distance = WEAPON_RANGED | WEAPON_THROWN
    for raw in item_types:
        if raw[0] != 0 or not any(raw):
            continue
        if raw[12] > 0:
            assert raw[TYPE_WEAPON_FLAGS] & at_a_distance, raw.hex()


def test_the_launcher_flags_separate_bow_from_crossbow_from_sling(item_types):
    """A sling is the case the flags exist to express: ranged, and no ammunition.

    `GB_ITM-Base.hexpat` says so outright -- ranged with neither launch bit nor
    the thrown bit means the weapon needs no ammunition -- and the sling is one
    of only two base records on the disks that reads that way.
    """
    kinds = {}
    for index, raw in enumerate(item_types):
        if raw[0] != 0 or not any(raw) or not raw[TYPE_WEAPON_FLAGS] & WEAPON_RANGED:
            continue
        flags = raw[TYPE_WEAPON_FLAGS]
        if flags & WEAPON_LAUNCH_BOLT:
            kinds.setdefault("bolt", []).append(index)
        elif flags & WEAPON_LAUNCH_ARROW:
            kinds.setdefault("arrow", []).append(index)
        elif flags & WEAPON_THROWN:
            kinds.setdefault("thrown", []).append(index)
        else:
            kinds.setdefault("no ammunition", []).append(index)
    assert set(kinds) == {"arrow", "bolt", "thrown", "no ammunition"}
    # Four bows want arrows; one crossbow wants bolts; the sling wants neither.
    assert len(kinds["arrow"]) >= 4
    assert len(kinds["bolt"]) == 1
    assert 1 <= len(kinds["no ammunition"]) <= 2


# --- ITEMS +6: armour class is stored as 60 - AC, not 12 - a nibble ---------

def test_armour_protection_is_the_standard_sixty_minus_value(item_types):
    """`por.items` reads `12 - (byte & 0x0F)`, which is this rule in disguise.

    The two agree for every armour on the disks and diverge at AC 13 or worse.
    The general rule is the one the DOS engine uses and the one to prefer.
    """
    for index, raw in enumerate(item_types):
        if not (raw[6] & 0x80) or raw[0] != 2:      # body armour only
            continue
        assert 60 - (raw[6] & 0x7F) == ItemType(index, raw).armour_class


def test_body_armour_covers_the_advanced_dungeons_and_dragons_range(item_types):
    classes = {60 - (raw[6] & 0x7F) for raw in item_types
               if raw[0] == 2 and raw[6] & 0x80}
    assert classes == {3, 4, 5, 6, 7, 8}


# --- SPELLN00 past 56 is combat messages, not the DOS item effects ----------

def test_the_spell_name_table_does_not_continue_into_item_effects():
    """DOS spell ids run to 67, adding potions and wands from 57. Not here."""
    where = disk_dir()
    names = {}
    for path in sorted(where.glob("POOL*.[dD]64")):
        try:
            names = load_spell_names(str(path))
        except Exception:
            continue
        if names:
            break
    if not names:
        pytest.skip("no SPELLN00 on these disks")
    assert names[LAST_SPELL] == "RESTORATION"
    for spell_id in range(LAST_SPELL + 1, 68):
        assert names.get(spell_id, "").startswith(("IS ", "TURNS", "FALLS",
                                                   "AGES", "GAZES", "SUCKS",
                                                   "BREATHES", "GETS", "GAINS",
                                                   "AVOIDS", "REFLECTS")), (
            spell_id, names.get(spell_id))
