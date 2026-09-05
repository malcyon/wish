"""Recompute the values the game caches, so a stale one can be spotted.

Armour class, THAC0 and the damage bonus live in the `SAVEDGAME1` roster
blocks, and the game only refreshes them when **equipment** changes. Edit a
character's dexterity or strength and the cached numbers keep the old values --
the character sheet in game will show them, and they will be wrong.

Nothing here writes anything. It computes what the AD&D 1st edition rules say a
character's combat numbers should be, so `wish` can say "this looks stale"
rather than leaving you to notice.

Every formula below is checked against real saves in the tests. BRUTUS used to
come out one point of armour class better than the rules predicted; that was the
dexterity table below being AD&D's rather than the game's, and with the boundary
corrected every character in every save is consistent. MALCYON's THAC0 improving
by one when he readies darts was the last discrepancy, and it was his dexterity:
a ranged weapon takes the missile attack adjustment at record 0x0EC where a
melee one takes the strength bonus (#202).
See docs/30-savegame-layout.md.

**One value here is written rather than only checked**, and it is the
exception that proves the rest: :func:`turn_power`, the byte the C64 keeps at
record `0x0A4`. DOS stores nothing a converter could copy -- it works the
turning row out from the cleric level at the moment somebody presses Turn --
so a conversion that copies has nothing to copy and leaves a cleric who cannot
turn undead. `goldbox/c64_codec.py` calls this instead of copying (#288).
See docs/178-turning-undead.md.
"""

from __future__ import annotations

from typing import Mapping

from .items import TYPE_DAMAGE_MEDIUM, WEAPON_ADDS_STRENGTH, ItemType

# The third byte of a damage expression is its flat bonus: a mace is 1d6+1, so
# its type record carries 1 here and readying it is worth a point of damage.
_TYPE_DAMAGE_BONUS = TYPE_DAMAGE_MEDIUM + 2

# THAC0 by class and level, read off the game's own table at `GEN $1F1F` --
# four rows of nine, indexed `class * 9 + level`. Index by level - 1.
#
# **The fighter row is per level, not per pair of levels.** AD&D 1st edition
# groups fighters 1-2, 3-4 and so on; this file used to carry that grouping and
# gave a level-2 fighter 20 where the game writes 19, a level-4 fighter 18
# where it writes 17, and so on up. Every one of twenty-nine trainings
# disagreed with the grouping (`docs/119-test-party.md`).
_THAC0 = {
    "fighter":    [20, 19, 18, 17, 16, 15, 14, 13, 12],
    "cleric":     [20, 20, 20, 18, 18, 18, 16, 16, 16],
    "thief":      [21, 21, 21, 21, 19, 19, 19, 19, 16],
    "magic-user": [21, 21, 21, 21, 21, 19, 19, 19, 19],
}
CLASS_BITS = ((1, "magic-user"), (2, "cleric"), (4, "thief"), (8, "fighter"))

# Dexterity's defensive adjustment: how much it improves armour class.
#
# NOT the AD&D 1st edition table. The Players Handbook starts the bonus at 15;
# Pool of Radiance starts it at **14**. Read straight off the save where nobody
# is wearing anything, so armour class is 10 minus this and nothing else:
#
#     DEX 12 -> AC 10     DEX 15 -> AC 9
#     DEX 13 -> AC 10     DEX 16 -> AC 8
#     DEX 14 -> AC  9
#
# The penalties for low dexterity are left at the book values because no
# specimen has a dexterity below 12. If the whole table is shifted by one they
# are wrong too, and nothing we hold would show it.
_DEX_AC = {3: -4, 4: -3, 5: -2, 6: -1, 14: 1, 15: 1, 16: 2, 17: 3, 18: 4}
# Strength's to-hit and damage bonuses. Exceptional strength splits 18.
_STR_HIT = {17: 1, 18: 1}
_STR_DAMAGE = {16: 1, 17: 2, 18: 2}

UNARMOURED_AC = 10


def _exceptional(pct: int) -> tuple[int, int]:
    """(to-hit, damage) for an 18 strength with a percentile roll."""
    if pct <= 0:
        return 1, 2
    if pct <= 50:
        return 1, 3
    if pct <= 75:
        return 2, 3
    if pct <= 90:
        return 2, 4
    if pct <= 99:
        return 2, 5
    return 3, 6


def strength_bonuses(strength: int, percentile: int = 0) -> tuple[int, int]:
    """(to-hit, damage) bonuses for a strength score."""
    if strength == 18:
        return _exceptional(percentile or 0)
    return _STR_HIT.get(strength, 0), _STR_DAMAGE.get(strength, 0)


def dexterity_ac_bonus(dexterity: int) -> int:
    """How many points of armour class dexterity is worth. Positive is better."""
    if dexterity >= 18:
        return 4
    return _DEX_AC.get(dexterity, 0)


def base_thac0(class_bits: int, level: int) -> int:
    """The best THAC0 among the character's classes, before any adjustment."""
    level = max(1, min(int(level or 1), 9))
    best = 99
    for bit, name in CLASS_BITS:
        if class_bits & bit:
            best = min(best, _THAC0[name][level - 1])
    return best if best != 99 else 20


def expected_armour_class(record, readied: list[tuple[object, ItemType]]) -> int:
    """Armour class from armour, shield and dexterity."""
    ac = UNARMOURED_AC
    for item, kind in readied:
        worn = kind.armour_class
        if worn is None:
            continue
        bonus = getattr(item, "bonus", 0) or 0
        if kind.is_shield:
            ac -= worn + bonus
        else:
            ac = min(ac, worn - bonus)
    return ac - dexterity_ac_bonus(record.get("dexterity"))


def expected_thac0(record, readied: list[tuple[object, ItemType]]) -> int:
    """THAC0 after the readied weapon's adjustment and its own bonus.

    **Which adjustment is the weapon's business, not the character's.**
    LIBRARY $36A0 rebuilds the roster THAC0 from the record's base and then
    tests the readied weapon's type +14: bit 1, ranged, adds the missile
    attack adjustment at record 0x0EC, and bit 2 adds the strength hit bonus.
    The two blocks are independent -- a heavy crossbow sets both bits and
    takes both -- and a dart sets neither bit 2 nor any strength, which is
    why MALCYON's THAC0 improved by one when he bought darts (#202).

    With nothing readied the strength bonus is used, which is what the six
    unarmoured characters of PORSAVE.D64 hold: three of them cache a THAC0
    two better than their base, and two is their strength bonus. PROBABLE --
    no specimen distinguishes "the game applies it bare-handed" from "the
    cache is left over from the last weapon that was readied".
    """
    hit, _ = strength_bonuses(record.get("strength"),
                              record.get("exceptional_strength"))
    found = next(((i, k) for i, k in readied if k.is_weapon), None)
    if found is None:
        adjustment, bonus = hit, 0
    else:
        weapon, kind = found
        adjustment = 0
        if kind.is_ranged:
            adjustment += record.get("missile_attack_adjustment") or 0
        if kind.adds_strength:
            adjustment += hit
        bonus = getattr(weapon, "bonus", 0) or 0
    return (base_thac0(record.get("class_bits"), record.get("level"))
            - adjustment - bonus)


def expected_damage_bonus(record, readied: list[tuple[object, ItemType]]) -> int:
    """Strength damage bonus plus the readied weapon's own.

    The weapon's own bonus is signed two's complement -- $FF is -1, not +255
    (#201, the same fault #188 fixed in `goldbox/items.py`). And the strength
    term is the weapon's business, not the character's: LIBRARY $36D2 adds it
    only when the readied type's +14 has bit 2 set, `WEAPON_ADDS_STRENGTH`. A
    vial of holy water is ranged and thrown, not "add strength", so readying
    it gets none.
    """
    _, damage = strength_bonuses(record.get("strength"),
                                 record.get("exceptional_strength"))
    for item, kind in readied:
        if kind.is_weapon:
            bonus = kind.raw[_TYPE_DAMAGE_BONUS]
            if bonus > 127:
                bonus -= 256
            strength = damage if kind.weapon_flags & WEAPON_ADDS_STRENGTH else 0
            return strength + bonus
    return damage


def turn_power(game, class_levels: Mapping[str, int] | None) -> int:
    """What the C64 keeps at record `0x0A4` for a character with these levels.

    The one derivation in this module a writer *stores*, because no port a
    conversion can read stores it. All three C64 engines compute this byte
    from the cleric and paladin levels and keep it: `GEN $2388` in Pool of
    Radiance reads the fourteen bytes at `$2399` with the cleric level,
    `GEN $113F` in Curse and `GEN $13A5` in Silver Blades reach the same
    numbers arithmetically and add a paladin, who turns as a cleric two levels
    weaker. Nothing recomputes it afterwards: the byte is written at creation
    and at every training, and a save the engine itself re-writes keeps
    whatever was there (#288).

    DOS has no counterpart. `GAME.OVR:0x139CD` reads the cleric level out of
    `class_levels[0]` at record `0x096` when the player presses Turn, bands it
    1-8 / 9-13 / 14 and up, and uses that as the column of the turning matrix
    -- so the DOS record keeps no caster-side byte at all, and a conversion
    that copies one copies a zero.

    Zero is the honest answer for a character who turns nothing: it is the
    byte the game itself stores for one, and it is what a blank record starts
    at where Pool of Radiance's `BEQ` writes nothing.

    `game` is whatever the caller has for the title -- a `goldbox.games.Game`,
    a `goldbox.levels.LevelTables`, a bare key, or None for Pool of Radiance.
    """
    from . import levels as _levels

    held = class_levels or {}
    want = _levels.turning_level(int(held.get("cleric") or 0), game,
                                 int(held.get("paladin") or 0))
    return 0 if want is None else int(want)


def check(record, block, readied: list[tuple[object, ItemType]]) -> list[str]:
    """Where the cached combat values disagree with the rules.

    An empty list means the cache is consistent. A non-empty one usually means
    an ability score was edited without re-readying equipment in game.
    """
    out: list[str] = []
    for label, want, got in (
        ("armour class", expected_armour_class(record, readied), block.armour_class),
        ("THAC0", expected_thac0(record, readied), block.thac0),
        ("damage bonus", expected_damage_bonus(record, readied), block.damage_bonus),
    ):
        if want != got:
            out.append(f"{label} is cached as {got}, but the rules give {want}")
    return out
