"""What the game caches, recomputed -- and which adjustment a weapon takes.

The formulas are in `goldbox/derive.py`. The one they used to get wrong is
THAC0 with a ranged weapon readied: the engine adds the character's missile
attack adjustment, record `0x0EC`, and *not* the strength hit bonus, so
MALCYON's THAC0 improved by a point when he bought darts and `wish` reported
his roster as stale for years afterwards (#202).

The synthetic tests need no disks. The live ones read the player's own saves,
which is where the population is: 122 of 126 character records agree with the
recomputed THAC0 and 121 with the recomputed damage bonus, and the nine that do
not are named one at a time in `THAC0_EXPLAINED` and `DAMAGE_EXPLAINED` rather
than counted.
"""

import pytest
from gamedata import needs_disks, save_disks

from goldbox import derive
from goldbox.d64 import D64
from goldbox.items import (
    WEAPON_ADDS_STRENGTH,
    WEAPON_RANGED,
    ItemType,
    items_for_slot,
    load_item_types,
)
from goldbox.record import CharacterRecord
from goldbox.savegame import SaveGame0, SaveGame1

#: A fighter's THAC0 at level 1, off the game's own table at `GEN $1F1F`.
FIGHTER, LEVEL_1 = 8, 1


def a_weapon(flags: int, bonus: int = 0) -> ItemType:
    """A type record carrying damage dice and nothing else but `flags`.

    Built here rather than read off a disk: what is under test is the
    arithmetic each flag bit provokes, and the game's own records happen to
    pair the bits with ranges, rates of fire and damage bonuses that would
    make a failure ambiguous. `bonus` is the raw byte, not a signed value --
    pass `0xFF` for a -1 the way the vial of holy water's record does.
    """
    raw = bytearray(16)
    raw[2:5] = bytes([1, 6, bonus & 0xFF])   # 1d6 vs large, so it is a weapon
    raw[9:12] = bytes([1, 6, bonus & 0xFF])  # 1d6 vs medium
    raw[14] = flags
    return ItemType(0, bytes(raw))


class FakeItem:
    """The half of an item record `expected_thac0` reads: its magic plus."""

    def __init__(self, bonus: int = 0):
        self.bonus = bonus


def a_character(*, strength: int = 18, percentile: int = 0,
                missile: int = 3) -> CharacterRecord:
    rec = CharacterRecord.blank()
    rec.set("class_bits", FIGHTER)
    rec.set("level_fighter", LEVEL_1)
    rec.set("strength", strength)
    rec.set("exceptional_strength", percentile)
    rec.set("missile_attack_adjustment", missile)
    return rec


def test_a_bow_takes_the_missile_adjustment_and_not_strength():
    """The bug a player saw: a character who readies a ranged weapon has his
    dexterity counted, not his strength, and `wish` used to call the resulting
    THAC0 stale."""
    rec = a_character(strength=18, missile=3)
    base = derive.base_thac0(FIGHTER, LEVEL_1)
    bow = [(FakeItem(), a_weapon(WEAPON_RANGED))]
    assert derive.expected_thac0(rec, bow) == base - 3


def test_a_melee_weapon_takes_strength_and_not_the_missile_adjustment():
    rec = a_character(strength=18, missile=3)
    base = derive.base_thac0(FIGHTER, LEVEL_1)
    sword = [(FakeItem(), a_weapon(WEAPON_ADDS_STRENGTH))]
    hit, _ = derive.strength_bonuses(18, 0)
    assert hit == 1
    assert derive.expected_thac0(rec, sword) == base - 1


def test_a_heavy_crossbow_takes_both_because_it_carries_both_bits():
    """The two blocks at LIBRARY $36A0 and $36B1 each add when their own bit
    is set, and four POOL1 records set both."""
    rec = a_character(strength=18, missile=3)
    base = derive.base_thac0(FIGHTER, LEVEL_1)
    crossbow = [(FakeItem(), a_weapon(WEAPON_RANGED | WEAPON_ADDS_STRENGTH))]
    assert derive.expected_thac0(rec, crossbow) == base - 4


def test_a_negative_missile_adjustment_makes_the_thac0_worse():
    """Dexterity 5 is -1 in the game's table, stored as $FF, and the field is
    signed -- read unsigned it would be worth 255 points of THAC0."""
    rec = a_character(strength=10, missile=-1)
    assert rec.to_bytes()[0x0EC] == 0xFF
    base = derive.base_thac0(FIGHTER, LEVEL_1)
    assert derive.expected_thac0(rec, [(FakeItem(), a_weapon(WEAPON_RANGED))]) \
        == base + 1


def test_nothing_readied_keeps_the_strength_bonus():
    """PORSAVE.D64's six characters have nothing readied and three of them
    cache a THAC0 two better than their base, which is their strength."""
    rec = a_character(strength=18, percentile=98, missile=3)
    hit, _ = derive.strength_bonuses(18, 98)
    base = derive.base_thac0(FIGHTER, LEVEL_1)
    assert derive.expected_thac0(rec, []) == base - hit


def test_a_readied_vial_of_holy_water_is_expected_to_subtract_one():
    """The bug a player saw: a fighter strong enough for a damage bonus reads
    the vial's own $FF byte as 255 and the strength bonus on top, and `wish`
    called the resulting 257 the rules' answer (#201).

    The vial's type record is ranged and thrown (bit 1) and never carries
    `WEAPON_ADDS_STRENGTH` (bit 2), so a strength of 17 should add nothing.
    """
    rec = a_character(strength=17)
    hit, damage = derive.strength_bonuses(17, 0)
    assert damage == 2, "a strength-17 fighter has a damage bonus to lose"
    vial = [(FakeItem(), a_weapon(WEAPON_RANGED, bonus=0xFF))]
    assert derive.expected_damage_bonus(rec, vial) == -1


def test_a_melee_weapon_still_adds_strength_to_its_own_bonus():
    """The other half of the fix: `WEAPON_ADDS_STRENGTH` still adds the
    strength term, so a sword with a +1 keeps reading +3 for an 18-strength
    fighter."""
    rec = a_character(strength=18, percentile=0)
    hit, damage = derive.strength_bonuses(18, 0)
    assert damage == 2
    sword = [(FakeItem(), a_weapon(WEAPON_ADDS_STRENGTH, bonus=1))]
    assert derive.expected_damage_bonus(rec, sword) == 3


# --- the population, off the player's own disks -----------------------------

def _party(path, types):
    """Every character on a save disk, with what they have readied."""
    image = D64.open(str(path))
    save0 = SaveGame0.from_prg(image.read_file(b"SAVEDGAME0"))
    save1 = SaveGame1.from_prg(image.read_file(b"SAVEDGAME1"))
    for slot in save0.characters:
        readied = [(i, types[i.type_index])
                   for i in items_for_slot(save0.to_bytes(), slot.index)
                   if i.readied and i.type_index in types]
        yield slot.record, save1.roster(slot.index), readied


#: Every record on the player's disks whose cached THAC0 is not what the rules
#: give, and the reason each one is not a defect in `goldbox/derive.py`.
#:
#: **A named set rather than a count.** `assert agree >= total - 2` said
#: nothing about *which* two, so when the player added two disks it went red
#: with no clue why and a whole session went into re-deriving what the two had
#: been. This fails when a new record disagrees **and** when one of these stops
#: -- which is what makes it the test that `#366 (A converted magic-user or
#: thief arrives with the other port's THAC0, because the two ports ship
#: different tables and the conversion copies the byte)` will change.
THAC0_EXPLAINED = {
    ("PORSAVEA.D64", "ASTRID"): "converted from DOS; carries the DOS table's "
                                "20 for a magic-user 3 where the C64's is 21",
    ("PORSAVEA.D64", "GILES"): "the same, and the same party",
    ("PORSAVEB.D64", "ASTRID"): "the same party, saved again",
    ("PORSAVEB.D64", "GILES"): "the same",
}

#: The same, for the damage bonus. All five are on the two disks GARRETT's
#: party lives on, and all five are the check doing its job: GRIMNIR and BRUTUS
#: cache 3 with an 18/00 strength, which is the number for a percentile of 1 to
#: 50, and ROLAND on `NEWSAVE2` caches 2 while holding a mace worth 3 -- caches
#: left behind by an edit, which is what `derive.check` exists to report.
DAMAGE_EXPLAINED = {
    ("NEWSAVE1.D64", "GRIMNIR"): "cached 3 for an 18/00 strength worth 2",
    ("NEWSAVE1.D64", "BRUTUS"): "cached 3 for an 18/00 strength worth 2",
    ("NEWSAVE2.D64", "GRIMNIR"): "cached 3 for an 18/00 strength worth 2",
    ("NEWSAVE2.D64", "BRUTUS"): "cached 3 for an 18/00 strength worth 2",
    ("NEWSAVE2.D64", "ROLAND"): "cached 2 with a mace readied, which is 3",
}


def _population(kind):
    """`(total, {(disk, name): (cached, expected)})` over every save disk."""
    from gamedata import disk_dir, game_disk

    types = load_item_types(str(game_disk("POOL1")))
    disks = sorted(p for p in disk_dir().glob("*.[dD]64")
                   if p.name.upper().startswith(("PORSAVE", "NEWSAVE")))
    if not disks:
        pytest.skip("no save disks")
    recompute = {"thac0": derive.expected_thac0,
                 "damage_bonus": derive.expected_damage_bonus}[kind]
    total, off = 0, {}
    for path in disks:
        try:
            party = list(_party(path, types))
        except Exception:            # PORSAVE10 is a roster disk with no save
            continue
        for record, roster, readied in party:
            total += 1
            want, got = recompute(record, readied), getattr(roster, kind)
            if want != got:
                off[(path.name.upper(), record.name)] = (got, want)
    return total, off


@needs_disks
def test_every_cached_thac0_agrees_with_the_recomputed_one():
    """The sample is the finding: 126 records across the player's save disks,
    122 of which agree, and the four that do not are named in
    `THAC0_EXPLAINED` one at a time.

    GARRETT on `NEWSAVE1` and `NEWSAVE2` used to be here and is not any more,
    and that is a fix rather than an excuse: he has `level` 5, `level_thief` 1
    and no experience, and the game's own loop reads the per-class array. His
    cached 21 is right for the thief 1 he is; it was `derive.base_thac0`
    reading `level` that made him look stale.
    """
    total, off = _population("thac0")
    assert total >= 100, f"only {total} records; the disks look incomplete"
    assert set(off) == set(THAC0_EXPLAINED), \
        "\n".join(f"{d} {n}: cached {c}, rules give {w}"
                  for (d, n), (c, w) in sorted(off.items()))


@needs_disks
def test_every_cached_damage_bonus_agrees_with_the_recomputed_one():
    """Before #201, only 91 of 114 records agreed -- the unsigned byte and the
    ungated strength term between them threw off every readied weapon with a
    negative bonus or a bit-1-only flag.

    It went to twelve out of 126 when a party carrying *magical* weapons
    arrived, and that was a third term missing rather than a third kind of
    edited record: `LIBRARY $36E3` adds the readied item's own bonus to the
    damage the same way `$36C2` adds it to the THAC0, and this did not. Seven
    records agreed the moment it was added. The five left are named in
    `DAMAGE_EXPLAINED`, all on the two disks GARRETT's party lives on.
    """
    total, off = _population("damage_bonus")
    assert total >= 100, f"only {total} records; the disks look incomplete"
    assert set(off) == set(DAMAGE_EXPLAINED), \
        "\n".join(f"{d} {n}: cached {c}, rules give {w}"
                  for (d, n), (c, w) in sorted(off.items()))


def test_a_magical_weapons_own_bonus_reaches_the_damage():
    """The term that was missing: `LIBRARY $36E3` adds `$6D80`, the readied
    item's enchantment, to the damage bonus unconditionally.

    A long sword +1 in the hands of an 18/00 fighter caches 3 on the player's
    own `PORSAVEA.D64` -- 2 for the strength, 0 for the type's flat damage and
    1 for the enchantment -- and this returned 2 until the third term went in.
    """
    rec = a_character(strength=18, percentile=0)
    _, damage = derive.strength_bonuses(18, 0)
    assert damage == 2
    sword = [(FakeItem(bonus=1), a_weapon(WEAPON_ADDS_STRENGTH, bonus=0))]
    assert derive.expected_damage_bonus(rec, sword) == 3
    # And it is added for a weapon that takes no strength at all, because the
    # engine adds it outside the `AND #$04` block.
    dart = [(FakeItem(bonus=2), a_weapon(WEAPON_RANGED, bonus=0))]
    assert derive.expected_damage_bonus(rec, dart) == 2


@needs_disks
def test_the_thac0_base_comes_from_the_per_class_array():
    """`GEN $1EF3` reads `$6BC9,X` -- the per-class array at `0x0C9` -- and
    never `level` at `0x0BA`, and GARRETT on `NEWSAVE1` is the record where the
    two disagree: `level` 5, `level_thief` 1, no experience, cached THAC0 21.

    21 is the thief 1 row and 19 is the thief 5 row, so reading the wrong field
    reported a record that is right about its THAC0 as stale, and pointed the
    reader at the wrong number.
    """
    assert derive.base_thac0(4, 5) == 19                    # the old reading
    assert derive.base_thac0(4, 5, {"thief": 1}) == 21      # the engine's
    rec = a_character()
    rec.set("class_bits", 4)
    rec.set("level", 5)
    rec.set("level_fighter", 0)
    rec.set("level_thief", 1)
    assert derive.class_levels(rec) == {"thief": 1}
    assert derive.expected_thac0(rec, []) == 21 - derive.strength_bonuses(
        rec.get("strength"), rec.get("exceptional_strength"))[0]


@needs_disks
def test_a_character_with_darts_readied_is_not_reported_as_stale():
    """MALCYON, whose THAC0 improved by one when he bought darts. His record
    is the one `goldbox/derive.py` could not explain until #202: PORSAVE2 has
    him at 20 against a base of 21, and PORSAVE11 at 18 after his dexterity
    was raised to 18 and a fight rebuilt the cache.
    """
    from gamedata import game_disk

    types = load_item_types(str(game_disk("POOL1")))
    seen = 0
    for path in save_disks():
        if path.stem.upper() not in ("PORSAVE2", "PORSAVE11"):
            continue
        for record, roster, readied in _party(path, types):
            if record.name != "MALCYON":
                continue
            seen += 1
            assert not [w for w in derive.check(record, roster, readied)
                        if "THAC0" in w], f"{path.name}: {record.name}"
    if not seen:
        pytest.skip("neither PORSAVE2 nor PORSAVE11 is here")
    assert seen == 2
