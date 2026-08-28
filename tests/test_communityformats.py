from __future__ import annotations

"""The findings `docs/127-community-formats.md` earned, asserted.

A community worker's format spreadsheets for the DOS Gold Box games were
compared against this project's C64 tables. Nothing here reads that document --
it is somebody else's work and is not in this repository. What is here is the
part of the comparison that our *own* data settled, turned into checks that
fail if a decoder drifts away from it.

Everything reads the player's own saved games and disks and skips when there
are none, the same as every other test that needs game data.
"""


import pytest

from goldbox import items, levels, spells
from goldbox.record import CharacterRecord
from goldbox.savegame import SaveGame0
from tests.gamedata import FIXTURES, game_disk, game_file

# --- offsets under test, all from goldbox.layout ---------------------------------
CASTABLE = 0x0EE          # three used bytes, three spare
MEMORISED = 0x020
SAVES = 0x09A
CLASS_BITS = 0x0EB
LEVEL = 0x0A0
WISDOM = 0x016
CONSTITUTION = 0x018
RACE = 0x072
PER_CLASS_LEVEL = 0x0C9   # indexed by class_bits bit number

#: Dwarves, gnomes and halflings take the AD&D constitution bonus against
#: magic. Race is 1-based: 1 dwarf, 2 elf, 3 gnome, 4 half-elf, 5 halfling,
#: 6 half-orc, 7 human.
STURDY_RACES = {1, 3, 5}

#: Which `goldbox.levels` table each bit of `class_bits` names.
CLASS_BIT_TABLE = {0: "magic-user", 1: "cleric", 2: "thief", 3: "fighter"}


def _records():
    """Every C64 character record reachable from the player's own saves."""
    out = []
    for path in sorted(FIXTURES.glob("*.chr")):
        out.append((path.name, CharacterRecord.from_bytes(path.read_bytes()[2:])))
    for name in ("savedgame0.bin", "party6_savedgame0.bin",
                 "party6_after_combat.bin"):
        save = SaveGame0.from_prg((FIXTURES / name).read_bytes())
        for index, slot in enumerate(save.characters):
            if slot.record is not None:
                out.append((f"{name}#{index}", slot.record))
    return out


RECORDS = _records()


def _raw(record) -> bytes:
    return bytes(record.to_bytes())


def _classes(raw: bytes):
    """(table name, level) for each class the character holds."""
    bits = raw[CLASS_BITS]
    return [(CLASS_BIT_TABLE[bit], raw[PER_CLASS_LEVEL + bit])
            for bit in CLASS_BIT_TABLE if bits & (1 << bit)]


def _constitution_bonus(constitution: int) -> int:
    """AD&D 1e: +1 saving throw per 3.5 points of constitution."""
    for floor, bonus in ((18, 5), (14, 4), (11, 3), (7, 2), (4, 1)):
        if constitution >= floor:
            return bonus
    return 0


# --- saving throws -----------------------------------------------------------
# goldbox/levels.py used to say its saving-throw columns "cannot be compared to a
# record" because the modifiers were not understood. They are: best column
# across the character's classes, less the racial constitution bonus.

def test_stored_saves_are_the_class_table_less_the_racial_bonus():
    checked = 0
    for label, record in RECORDS:
        raw = _raw(record)
        held = _classes(raw)
        if not held:
            continue
        rows = [levels.at_level(name, max(level, 1)).saves
                for name, level in held]
        best = [min(row[column] for row in rows) for column in range(5)]
        adjust = (_constitution_bonus(raw[CONSTITUTION])
                  if raw[RACE] in STURDY_RACES else 0)
        expected = tuple(value - adjust for value in best)
        assert tuple(raw[SAVES:SAVES + 5]) == expected, label
        checked += 1
    assert checked >= 6


def test_the_multiclass_rule_is_load_bearing():
    """A multi-class character's saves are neither class's row.

    LADY KATHERINE is magic-user 1 / thief 1 and reads the column-wise minimum
    of the two, which is why the rule has to take the best of each column
    rather than pick a class.
    """
    raw = _raw(dict(RECORDS)["lady_katherine.chr"])
    assert sorted(name for name, _ in _classes(raw)) == ["magic-user", "thief"]
    magic_user = levels.at_level("magic-user", 1).saves
    thief = levels.at_level("thief", 1).saves
    assert magic_user != thief
    observed = tuple(raw[SAVES:SAVES + 5])
    assert observed != magic_user and observed != thief
    assert observed == tuple(min(a, b) for a, b in zip(magic_user, thief))


def test_the_dwarf_takes_the_constitution_bonus():
    """MAGNUS is the only dwarf in the fixtures and the only one shifted.

    Without the racial rule he reads three lower than an identical human
    fighter, which is exactly his constitution band.
    """
    magnus = next(r for label, r in RECORDS if r.name == "MAGNUS")
    brutus = next(r for label, r in RECORDS if r.name == "BRUTUS")
    magnus_raw, brutus_raw = _raw(magnus), _raw(brutus)
    assert magnus_raw[RACE] == 1 and brutus_raw[RACE] == 7
    assert _classes(magnus_raw) == _classes(brutus_raw)
    shift = _constitution_bonus(magnus_raw[CONSTITUTION])
    assert shift == 3
    assert [b - m for m, b in zip(magnus_raw[SAVES:SAVES + 5],
                                  brutus_raw[SAVES:SAVES + 5])] == [shift] * 5


# --- spells castable ---------------------------------------------------------

def test_spells_castable_matches_the_derived_capacity():
    """0x0EE-0x0F0, cleric high nibble, magic-user low, one per spell level.

    The field is a **cache**: it is written when the character is made or
    gains a level and is not recomputed when wisdom changes. A record whose
    ability scores have been edited since can disagree, and one on a save disk
    here does. Every fixture agrees, which is what this asserts.
    """
    checked = 0
    for label, record in RECORDS:
        raw = _raw(record)
        want = spells.capacity(raw[CLASS_BITS], raw[LEVEL], raw[WISDOM])
        cleric = want.get("cleric", (0, 0, 0))
        magic_user = want.get("magic-user", (0, 0, 0))
        packed = bytes((c << 4) | m for c, m in zip(cleric, magic_user))
        assert raw[CASTABLE:CASTABLE + 3] == packed, label
        checked += 1
    assert checked >= 6


def test_spell_levels_four_to_six_are_unused_in_this_game():
    """The field is six bytes; Pool of Radiance stops at third-level spells."""
    for label, record in RECORDS:
        assert _raw(record)[CASTABLE + 3:CASTABLE + 6] == b"\x00\x00\x00", label


# --- memorised spells --------------------------------------------------------

def test_memorised_spells_pack_forward_in_descending_id():
    """Ids run from 0x020 upward, highest first, and stop at the first zero.

    Vacuous on a party that has memorised nothing; it earns its place on a
    save where somebody has. The width the layout declares is 16 and the
    format allows 21 (docs/127), so the check deliberately reads past the
    declared field and asserts only that nothing lives beyond a gap.
    """
    for label, record in RECORDS:
        raw = _raw(record)
        window = raw[MEMORISED:MEMORISED + 21]
        used = len(window.rstrip(b"\x00"))
        assert 0 not in window[:used], f"{label}: a gap inside the list"
        ids = list(window[:used])
        assert ids == sorted(ids, reverse=True), label
        assert all(1 <= i <= spells.LAST_SPELL for i in ids), label
        want = spells.capacity(raw[CLASS_BITS], raw[LEVEL], raw[WISDOM])
        assert used <= sum(sum(counts) for counts in want.values()), label


# --- the ITEMS type table ----------------------------------------------------
# The C64 `ITEMS` file and the DOS one are the same 128 records, so the DOS
# field names apply here. Three of them sharpen ours; the fourth is where the
# community document is wrong and this table proves it.

@pytest.fixture(scope="module")
def item_types():
    return items.load_item_types(str(game_disk("POOL1")))


def test_damage_type_takes_only_three_values(item_types):
    """Byte +7 is a damage type -- slashing, piercing, bludgeoning."""
    seen = {t.raw[7] for t in item_types.values()}
    assert seen <= {0, 1, 128}
    assert seen == {0, 1, 128}


def test_byte_eight_is_a_flag_not_a_count(item_types):
    """Byte +8 only ever reads 0 or 128, so it is bit 7 and nothing else."""
    assert {t.raw[8] for t in item_types.values()} == {0, 128}


def test_weapon_flags_decode_as_a_bitfield(item_types):
    """Byte +14 is flags, not a missile-type enum.

    Bit 0 launch-arrow, 1 ranged, 2 strength bonus, 3 multi-fire, 4 thrown,
    7 launch-bolt. Bits 5 and 6 are unassigned, and nothing in the table sets
    them -- which is the check: an enum would.
    """
    launch_arrow, ranged, multi_fire, launch_bolt = 0x01, 0x02, 0x08, 0x80
    unassigned = 0x60
    values = {t.raw[14] for t in item_types.values()}
    assert values, "no item types read"
    assert not any(value & unassigned for value in values), sorted(values)
    for value in values:
        # A weapon that fires more than once a round is a ranged weapon, and
        # both launchers are. An enumeration would have no reason to agree.
        if value & (multi_fire | launch_bolt):
            assert value & ranged, hex(value)
    assert any(value & launch_arrow for value in values)
    assert any(value & launch_bolt for value in values)


def test_armour_protection_uses_the_sixty_minus_bias(item_types):
    """`60 - (byte & 0x7F)` and goldbox.items' `12 - low nibble` are one rule.

    The community document gives `10 - (60 - (AC & 127))`, which is this list
    reversed and would make leather better than plate. The nine armour records
    settle it: read our way they are the AD&D armour classes in order.
    """
    armour = {index: t for index, t in item_types.items()
              if t.armour_class is not None and not t.is_shield}
    assert len(armour) >= 9
    for index, t in armour.items():
        assert t.armour_class == 60 - (t.raw[6] & 0x7F), index
    # Entries 50-58 are leather, padded, studded, ring, scale, chain, splint,
    # banded and plate, in the word table's own order.
    ladder = [armour[i].armour_class for i in range(50, 59) if i in armour]
    assert ladder == [8, 8, 7, 7, 6, 5, 4, 4, 3]


def test_the_c64_dagger_can_be_thrown():
    """Item type 8 carries a rate of fire, a range and the thrown flag.

    The DOS table gives the same record rate of fire 0, range 1 and no thrown
    flag -- two of the 128 records differ between the ports and both are
    thrown weapons. Kept as a regression guard on the C64 side only; the DOS
    file is not in this repository.
    """
    raw = game_file("ITEMS")
    dagger = raw[8 * 16:9 * 16]
    assert dagger[5] == 2          # rate of fire
    assert dagger[12] == 4         # range
    assert dagger[14] & 0x10       # thrown
