"""Four corrections to field names, each checked against the player's disks.

A third-party document is PROBABLE evidence and nothing more. These are the
checks that turned parts of two community sources into measurements of ours:
the 127-entry effect table (`por/traits.py`), the roster block's current attack
form (`por/savegame.py`) and the armour-protection encoding (`por/items.py`).
`docs/127-community-formats.md` and `docs/128-guide-and-scripting.md` are the
write-ups.

Everything here reads the player's own disks and skips without them.
"""

from __future__ import annotations

import pathlib

import pytest
from gamedata import disk_dir, needs_disks

from por import traits
from por.d64 import D64, split_load_address
from por.items import (
    PROTECTION_BIAS,
    PROTECTION_GRANTS,
    ItemType,
    items_for_slot,
    load_item_names,
    load_item_types,
)
from por.record import CharacterRecord
from por.savegame import (
    ROSTER_ARMOUR_BONUS,
    ROSTER_COUNT,
    ROSTER_DAMAGE_DIE,
    SaveGame0,
    SaveGame1,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

CONFIDENCES = {"CONFIRMED", "PROBABLE", "GUESS", "UNKNOWN"}


def _pool_disk() -> str:
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks")
    disks = sorted(where.glob("POOL*.[dD]64"))
    if not disks:
        pytest.skip("no POOL disk here")
    return str(disks[0])


@pytest.fixture(scope="module")
def monsters() -> dict[str, bytes]:
    """Every `MON<id>` record on every game disk, keyed by creature name."""
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks")
    out: dict[str, bytes] = {}
    for path in sorted(where.glob("POOL*.[dD]64")):
        try:
            disk = D64.open(path)
        except Exception:
            continue
        for entry in disk.directory():
            if not (entry.name.startswith(b"MON") and len(entry.name) == 5):
                continue
            try:
                _, payload = split_load_address(disk.read_file(entry.name))
            except Exception:
                continue
            if len(payload) >= 0x120:
                name = payload[:20].split(b"\x00")[0].decode("latin1")
                out.setdefault(name, bytes(payload))
    if not out:
        pytest.skip("no MON records on these disks")
    return out


def _slots(name: str):
    """A save disk's `SAVEDGAME0` and `SAVEDGAME1`, or a skip."""
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks")
    path = where / f"{name}.D64"
    if not path.exists():
        pytest.skip(f"needs {path.name}")
    disk = D64.open(str(path))
    return (SaveGame0.from_prg(disk.read_file(b"SAVEDGAME0")),
            SaveGame1.from_prg(disk.read_file(b"SAVEDGAME1")))


def _carriers(monsters) -> dict[int, set[str]]:
    """Which creatures carry which trait code."""
    out: dict[int, set[str]] = {}
    for name, record in monsters.items():
        for code in record[traits.FIRST:traits.FIRST + traits.SLOTS]:
            if code:
                out.setdefault(code, set()).add(name)
    return out


# --- P55: the effect table --------------------------------------------------
# The guide enumerates 127 effect ids for the DOS build. The ids are shared
# between the ports, so the C64 census is what promotes them one at a time.

def test_every_documented_effect_id_is_named():
    """1 to 127 with no holes. A gap would read as "there is nothing there"."""
    missing = [n for n in range(1, traits.LAST_DOCUMENTED + 1)
               if n not in traits.NAMES]
    assert missing == []


def test_every_name_carries_a_confidence_from_the_four():
    for code, (what, sure) in traits.NAMES.items():
        assert what, code
        assert sure in CONFIDENCES, (code, sure)


def test_every_code_the_disks_carry_has_a_name(monsters):
    """A code on a real creature that the table does not name is the one thing
    this exercise was for. 139 is past the guide's table and is ours."""
    unnamed = sorted(code for code in _carriers(monsters)
                     if code not in traits.NAMES)
    assert unnamed == []


def test_the_anhkheg_carries_its_own_acid_squirt(monsters):
    """The guide names the anhkheg in the text of effect 121, and the anhkheg
    is the only creature on the disks that carries it. Two ids, one creature:
    80 is the acid bite and 121 the ranged squirt."""
    carriers = _carriers(monsters)
    assert carriers[121] == {"AHNKHEG"}
    assert "AHNKHEG" in carriers[80]
    assert traits.confidence(121) == "CONFIRMED"


def test_the_troll_carries_the_two_troll_effects(monsters):
    carriers = _carriers(monsters)
    assert carriers[100] == carriers[101] == {"TROLL"}


def test_the_wight_and_the_wraith_take_different_weapon_immunities(monsters):
    """The Monster Manual distinction: a wight is hit by silver *or* magic, a
    wraith takes half damage from silver and full from magic. 96 and 123 split
    exactly that way, which no coincidence of population produces."""
    carriers = _carriers(monsters)
    assert carriers[96] == {"WIGHT"}
    assert carriers[123] == {"WRAITH"}


def test_the_mummy_carries_every_mummy_effect(monsters):
    """Six ids whose guide text says "mummy" land on the mummy and nothing
    else: the fear aura, the rot attack, the fire vulnerability, and the
    half-damage-from-magic and non-magical-weapon immunities."""
    carriers = _carriers(monsters)
    for code in (82, 87, 116, 122):
        assert carriers[code] == {"MUMMY"}, code
    assert "MUMMY" in carriers[119]


def test_the_paralysis_family_lands_on_the_paralysers(monsters):
    """67 and 68 are graded by saving throw. The ghoul takes the grade whose
    text says elves are immune, which is the ghoul's own rule."""
    carriers = _carriers(monsters)
    assert carriers[68] == {"GHOUL"}
    assert carriers[67] == {"THRI-KREEN"}
    assert carriers[104] == {"THRI-KREEN"}      # thri-kreen missile evasion


def test_the_level_drains_are_graded_by_the_monster_manual(monsters):
    """One level for wights and wraiths, two for spectres and vampires."""
    carriers = _carriers(monsters)
    assert carriers[85] == {"WIGHT", "WRAITH"}
    assert {"SPECTRE", "VAMPIRE"} <= carriers[86]


def test_two_codes_the_guide_does_not_reach_are_still_ours(monsters):
    """92 the guide calls unused and 139 is past the end of its table. Both
    are carried by a real creature, so neither may be dropped."""
    carriers = _carriers(monsters)
    assert carriers[92] == {"TYRANITHRAXUS"}
    assert carriers[139] == {"PHASE SPIDER"}
    assert traits.confidence(92) == "UNKNOWN"


def test_the_race_seed_is_indexed_by_the_race_byte(monsters):
    """`GEN $0BF3` seeds from [1, 0, 107, 0, 124, 0, 0, 0] indexed by race,
    which is 1-based -- so the leading 1 is unreachable and no dwarf carries
    it. MAGNUS is the dwarf that settles it."""
    save = FIXTURES / "party6_savedgame0.bin"
    if not save.exists():
        pytest.skip("needs the six-character party fixture")
    seeded = {}
    for slot in SaveGame0.from_prg(save.read_bytes()).characters:
        record = slot.record_bytes
        name = record[:20].split(b"\x00")[0].decode("latin1")
        seeded[name] = (record[0x72],
                        list(record[traits.FIRST:traits.FIRST + traits.SLOTS]))
    assert seeded["MALCYON"] == (2, [107] + [0] * 9)            # elf
    assert seeded["LADY KATHERINE"] == (4, [124] + [0] * 9)     # half-elf
    assert seeded["MAGNUS"] == (1, [0] * 10)                    # dwarf: nothing
    assert 1 not in [code for _, block in seeded.values() for code in block]


def test_a_passive_item_puts_an_effect_id_in_its_plus_fourteen():
    """Item byte +15 bit 7 is the discriminator, and the two passive items in
    Donald's saves both land on the guide's name for their id: the cloak of
    displacement carries 89 "displaced" and the undead-slaying sword carries 3
    "wielding an undead-slaying weapon". A potion's +14 is a spell id, not an
    effect, which is why 85 is a healing potion and a level drain at once."""
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks")
    names = load_item_names(_pool_disk())
    found = {}
    for path in sorted(where.glob("PORSAVE*.D64")):
        try:
            payload = D64.open(str(path)).read_file(b"SAVEDGAME0")[2:]
        except Exception:
            continue
        for slot in range(8):
            for item in items_for_slot(payload, slot, names):
                if item.raw[15] & 0x80:
                    found[item.name] = item.raw[14]
    if not found:
        pytest.skip("no passive magical item in these saves")
    for name, code in found.items():
        assert code in traits.NAMES, (name, code)
    if "CLOAK OF DISPLACEMENT" in found:
        assert found["CLOAK OF DISPLACEMENT"] == 89
        assert traits.describe(89) == "displaced"


# --- P56: the roster block's current attack form ----------------------------

@needs_disks
def test_the_roster_die_size_is_the_readied_weapon(monsters):
    """Roster +0x15 was called EQUIPMENT because it "rises with what is
    readied". It is the primary attack's **die size**: it equals the ITEMS
    damage die of whatever weapon the character has equipped, and 2 -- the
    unarmed 1d2 -- when there is none. Checked on every save disk that has a
    roster page, which is thirteen of them."""
    types = load_item_types(_pool_disk())
    names = load_item_names(_pool_disk())
    checked = 0
    for n in ("", "2", "3", "4", "5", "6", "7", "8", "9",
              "11", "12", "13", "14"):
        try:
            sg0, sg1 = _slots(f"PORSAVE{n}")
        except Exception:
            continue
        payload = bytes(sg0)
        for index in range(ROSTER_COUNT):
            block = sg1.roster(index)
            if not block.occupied:
                continue
            weapons = [types[item.type_index]
                       for item in items_for_slot(payload, block.slot_index,
                                                  names)
                       if item.readied and item.type_index in types
                       and types[item.type_index].is_weapon]
            expected = 2                    # bare hands: the record's own 1d2
            if weapons:
                expected = weapons[0].raw[9 + 1]        # damage vs medium: die
            assert block.damage_die == expected, (n, index)
            assert block.raw[ROSTER_DAMAGE_DIE] == block.damage_die
            checked += 1
    if not checked:
        pytest.skip("no save disks with a roster page")
    assert checked >= 6


@needs_disks
def test_the_roster_damage_is_the_whole_readied_attack():
    """Dice, die and bonus together: ROLAND's mace is 1d6+1 and reads as it."""
    sg0, sg1 = _slots("PORSAVE11")
    by_name = {}
    for index in range(ROSTER_COUNT):
        block = sg1.roster(index)
        if not block.occupied:
            continue
        record = sg0.slot(block.slot_index).record_bytes
        by_name[record[:20].split(b"\x00")[0].decode("latin1")] = block
    assert by_name["ROLAND"].damage == "1d6+1"          # mace
    assert by_name["MALCYON"].damage == "1d3"           # dart
    assert by_name["LADY KATHERINE"].damage == "1d6+1"  # short sword, STR +1
    assert by_name["BRUTUS"].damage == "1d8+5"          # long sword


@needs_disks
def test_the_roster_armour_byte_is_the_bonus_and_not_the_rear_armour_class():
    """The DOS record spends this offset on armour class from behind. Ours
    does not: 48/50/54 for nothing, leather and banded mail are the AD&D
    armour bonuses 0/2/6, and a shield does not move the byte -- which a rear
    armour class would."""
    sg0, sg1 = _slots("PORSAVE11")
    seen = {}
    for index in range(ROSTER_COUNT):
        block = sg1.roster(index)
        if not block.occupied:
            continue
        record = sg0.slot(block.slot_index).record_bytes
        name = record[:20].split(b"\x00")[0].decode("latin1")
        seen[name] = (block.raw[ROSTER_ARMOUR_BONUS], block.armour_bonus)
    assert seen["MALCYON"] == (48, 0)                   # nothing
    assert seen["LADY KATHERINE"] == (50, 2)            # leather
    for name in ("SILAS", "MAGNUS", "BRUTUS"):          # banded mail + shield
        assert seen[name] == (54, 6), name
    assert seen["ROLAND"] == (54, 6)                    # banded mail, no shield


# --- P58: the armour rule is the family's own bias --------------------------

def test_armour_protection_is_sixty_minus_the_low_seven_bits():
    """The general rule, on a synthetic record so it needs no disk."""
    raw = bytearray(16)
    raw[6] = PROTECTION_GRANTS | (PROTECTION_BIAS - 8)
    assert ItemType(0, bytes(raw)).armour_class == 8


def test_the_nibble_rule_and_the_bias_rule_diverge_at_armour_class_13():
    """`12 - (byte & 0x0F)` is the bias rule in disguise while the high nibble
    is $B, and nonsense below it. $AF is armour class 13; the old rule gave
    -3. Nothing on the disks reaches it, which is exactly why this test
    exists -- the two readings cannot be told apart by the data we hold."""
    raw = bytearray(16)
    raw[6] = 0xAF
    item = ItemType(0, bytes(raw))
    assert item.armour_class == 13
    assert not item.is_shield
    assert 12 - (raw[6] & 0x0F) == -3            # what it used to say


def test_a_small_value_is_a_bonus_and_a_large_one_is_a_class():
    """Which of the two the low seven bits hold is decided by magnitude, and
    the line cannot serve both ends: $AF is armour class 13 and a +47 at once.
    Pool of Radiance ships nothing between +1 and AC 12, so the ambiguity is
    real and untestable here -- this pins where the line was put."""
    def read(byte):
        raw = bytearray(16)
        raw[6] = byte
        return ItemType(0, bytes(raw))
    assert read(PROTECTION_GRANTS | 1).is_shield           # a +1 shield
    assert read(PROTECTION_GRANTS | 15).is_shield          # the last bonus
    assert not read(PROTECTION_GRANTS | 16).is_shield      # the first class
    assert read(PROTECTION_GRANTS | 16).armour_class == 44


def test_bit_seven_clear_means_no_protection_at_all():
    raw = bytearray(16)
    raw[6] = 0x34                                # a class, without the flag
    assert ItemType(0, bytes(raw)).armour_class is None


@needs_disks
def test_the_armour_ladder_on_the_disks_is_the_advanced_dungeons_dragons_one():
    """Entries 50-58, leather through plate, read 8 7 7 6 5 4 4 3 under the
    bias rule -- the published list in order. The community's own formula
    inverts it and makes leather better than plate; ours is not theirs."""
    types = load_item_types(_pool_disk())
    ladder = [types[i].armour_class for i in range(50, 59)
              if i in types and not types[i].is_shield]
    assert ladder == sorted(ladder, reverse=True)
    assert ladder[0] == 8 and ladder[-1] == 3


@needs_disks
def test_no_item_on_the_disks_changed_meaning_under_the_new_rule():
    """The two rules agree on everything the game ships, which is what makes
    this a correction rather than a fix."""
    types = load_item_types(_pool_disk())
    for index, item in types.items():
        byte = item.raw[6]
        if not byte:
            continue
        old = (byte & 0x0F) if byte & 0xF0 == 0x80 else 12 - (byte & 0x0F)
        assert item.armour_class == old, index


# --- the character record's own note stays true -----------------------------

def test_an_export_round_trips_with_the_effect_block_intact():
    """Renaming the trait table must not touch a byte of the record."""
    export = FIXTURES / "brutus.chr"
    if not export.exists():
        pytest.skip("needs the exported-character fixture")
    raw = export.read_bytes()
    assert CharacterRecord.from_prg(raw).to_prg() == raw
