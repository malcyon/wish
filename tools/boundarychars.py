#!/usr/bin/env python3
"""Deliberately extreme Pool of Radiance characters, for `tests/test_boundary.py`.

`#516 (Generate boundary characters and check every writer's field widths,
since no real save reaches a limit and the corpus cannot find a wrong one)`:
every conversion test in this project runs against records that exist, which
is the right corpus for asking whether a conversion is faithful and the wrong
one for asking whether it is *safe* -- a real party rarely sits near a limit,
and `#508 (A converted magic-user loses memorised spells on the way to DOS,
because our table says a title has fewer slots than the engine gives it)` is
what a generator that walks straight up to a ceiling would have caught on its
first run.

Every case here is a `NeutralCharacter` read as though off a C64 Pool of
Radiance disk (`port="C64"`), because that is what a real conversion into DOS
sees and it is the port that makes `goldbox.dos_codec.write` recompute
thief skills and THAC0 through DOS's own tables rather than copy the
source's. Every ceiling is computed from `goldbox/levels.py`,
`goldbox/spells.py` or `tools/classlegality.py`, or cited to a byte address
in the game's own code -- nothing here is typed in from memory. Pool of
Radiance only: Curse of the Azure Bonds and Secret of the Silver Blades need
their own creation-menu tables read first (the plan comment on `#516`, order
of work, step 5).

    tools/boundarychars.py

prints every case's fields, so a person can read what the harness builds
without opening a debugger.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import c64_codec, classcode, dos_codec
from goldbox import items as items_mod
from goldbox import levels as level_tables
from goldbox import spells as spells_mod
from goldbox.neutral import Confidence, NeutralCharacter, Provenance

#: The title every case is for.  `tools/classlegality.py` reads this one;
#: Curse and Silver Blades are out of scope (plan, step 5).
GAME = "pool-of-radiance"

#: Pool of Radiance's own race numbers, shared with the C64 side
#: (`goldbox/dos_port.py` `RACE_NUMBERS`, `goldbox/titles.py`
#: `RACES_FORGOTTEN_REALMS`) -- monster is 0 on both and nothing here uses it.
RACE_DWARF = 1
RACE_ELF = 2
RACE_GNOME = 3
RACE_HALF_ELF = 4
RACE_HALFLING = 5
RACE_HALF_ORC = 6
RACE_HUMAN = 7

#: The four races whose own racial ids the DOS writer adds to a converted
#: character's `.SPC` file regardless of what `innate_effects` carries --
#: `tests/test_doswriter.py`'s own measurements
#: (`test_a_converted_dwarf_carries_his_constitution_bonus_to_saves`,
#: `test_a_converted_halfling_carries_the_two_records_his_own_kind_has`,
#: `test_a_converted_gnome_carries_his_four_innate_records`,
#: `test_a_race_with_no_innate_effects_gets_no_spc_file`).  A case whose race
#: is not one of these three keys gets none, which is also measured there
#: (elf, half-elf and human).
_RACIAL_INNATE_IDS = {
    RACE_DWARF: (90, 97, 26, 47),
    RACE_GNOME: (97, 18, 47, 48),
    RACE_HALFLING: (90, 97),
}


def _innate_for_race(race: int) -> list[int]:
    """The racial ids the DOS engine seeds for this race, and no others."""
    return list(_RACIAL_INNATE_IDS.get(race, ()))


def _class_fields(levels: dict[str, int]) -> tuple[int, int]:
    """`(class_bits, char_class)`, computed so the two agree with each other
    and with `levels` -- which is what keeps `goldbox.classcode.repair` from
    rewriting `char_class` on the way through the writer (#310), so the
    round trip in test A sees the same code it set rather than a repaired
    one.
    """
    bits = 0
    for name, level in levels.items():
        if level:
            bits |= classcode.CLASS_BIT_FOR_NAME.get(name, 0)
    code = classcode.code_for(bits, levels, {}, GAME)
    if code is None:
        raise ValueError(f"{levels} has no DOS class code in {GAME!r}")
    return bits, code


def _effect(effect_id: int, value: int = 0) -> bytes:
    """One nine-byte `.SPC` node for `granted_effects`: the id, a
    little-endian duration of zero (permanent -- `docs/162-spc-permanence.md`),
    the value the effect carries, the flag byte, and a NULL next pointer --
    the shape `tests/test_doswriter.py`'s own `_effect` builds and
    `goldbox.dos_codec.write` reads back unchanged."""
    return (bytes((effect_id,)) + (0).to_bytes(2, "little")
            + bytes((value, 0)) + dos_codec.EFFECT_NEXT_NULL)


def _item(weight_tenths: int = 50) -> bytes:
    """One legal, unremarkable C64 inventory item: a real type, one held,
    a real weight, nothing readied or cursed -- `goldbox.items.build_item`
    leaves everything else zero, which is what keeps the round trip in test
    A exact rather than losing an unattributed byte the way `bytes(range(16))`
    does in `tests/test_neutral.py::_filled`."""
    return items_mod.build_item(type_index=1, quantity=1,
                                weight_tenths=weight_tenths)


def _base() -> NeutralCharacter:
    """Every field `dos_codec.write_field_disposition("pool-of-radiance")`
    calls `copied to` or transformed, set to an unremarkable legal value.

    This is test B's whole point: a field added to `goldbox/neutral.py` and
    wired into the writer has no value here until somebody says what its
    extreme is, and the coverage sweep in `tests/test_boundary.py` fails
    until it does. The four cases below start from this and push their own
    fields to a ceiling; everything they do not mention keeps the value set
    here.
    """
    char = NeutralCharacter("C64", source="tools/boundarychars.py", game=GAME)
    char.set("name", "BASE", "made up", Confidence.CONFIRMED,
             Provenance.RESHAPED)
    # Every scalar `c64_codec.DIRECT` names, at a small sequential value --
    # proven by `tests/test_neutral.py::_filled` to reach `dos_codec.write`
    # with zero warnings, since none of these are near a `U8` field's own
    # ceiling of 255. `race`, `char_class`, `attack_level` and the eight
    # thief-skill columns are overridden below to values consistent with
    # each other and with what the DOS engine actually stores.
    for n, (field, _) in enumerate(c64_codec.DIRECT):
        char.set(field, n + 1, f"base: value {n + 1}")
    char.set("race", RACE_HUMAN, "base: human, so no racial ceiling narrows "
             "a case that has not overridden it")
    char.set("levels", {"fighter": 1}, "base")
    char.set("char_class", classcode.code_for(8, {"fighter": 1}, {}, GAME),
             "base: fighter, agrees with levels and class_bits")
    char.set("class_bits", 8, "base: fighter")
    # Pool of Radiance's engine writes the constant 1 here for every
    # character regardless of class (`goldbox.dos_port.POOL_OF_RADIANCE`'s
    # own docstring, `attack_level_classes=()`, #527) -- setting the neutral
    # value to what the engine always writes is what keeps this field's
    # round trip exact without adding it to the named exceptions.
    char.set("attack_level", 1, "base: Pool of Radiance's own constant (#527)")
    char.set("spells_known", [], "base: nothing memorised in the book")
    char.set("spells_memorised", [], "base: nothing memorised")
    char.set("spells_castable", {}, "base: no caster class")
    char.set("size_small", 0, "base: medium")
    char.set("attack_forms", bytes(range(1, 9)), "base")
    char.set("innate_effects", [], "base: a human seeds nothing (measured, "
             "test_a_race_with_no_innate_effects_gets_no_spc_file)")
    char.set("inventory", [_item() for _ in range(1)], "base: one item")
    char.set("roster_tail", bytes(range(9)), "base")
    char.set("portrait_head", 0x08, "base: HEAD08, the menu's own eighth "
             "entry, not the menu's first (#503)")
    char.set("portrait_body", 0x04, "base: BODY04")
    # The nine active/status/NPC-adjacent fields `c64_codec.DIRECT` does not
    # carry, each an unremarkable legal value.  `npc` is true and
    # `npc_control_byte` is given, since a control byte with `npc` false is
    # reported rather than written (`goldbox.dos_codec.write`'s own account
    # of `field_83_87`) -- an ordinary player character is simpler to reach
    # by giving every case its own override where it matters, which none of
    # the four does.
    char.set("status", "okay", "base")
    char.set("active", True, "base")
    char.set("hostile", False, "base")
    char.set("quickfight", False, "base")
    char.set("npc", True, "base")
    char.set("npc_control_byte", 0x80, "base: bit 7 set, no morale")
    char.set("treasure_share", 0, "base")
    char.set("granted_effects", [_effect(61, value=12)], "base: a Ring of "
             "Fire Resistance, the shape #232 measured the engine writing")
    char.set("unnamed_0ab", 77, "base: an arbitrary identity draw")
    return char


def caster() -> NeutralCharacter:
    """The half-elf cleric 5 / magic-user 6, memorising all 20 spells the
    title's own table gives him -- Pool of Radiance's one ceiling `#508`
    walked straight into and the corpus never could, because the array
    fills from its end and nothing on this machine's disks holds more than
    seventeen (WISHHEL, per the plan's own comment on `#516`).

    Half-elf is the *only* race Pool of Radiance's own creation menu offers
    both cleric and magic-user to at once (`tools/classlegality.py`, 37 of 37
    entries agreeing on both ports); 5 and 6 are the class ceilings at
    `GEN $1E5C` (`06 06 09 08`) after the half-elf's racial limits at
    `GEN $1E60` (8 for magic-user, clamped down to the class ceiling; 5 for
    cleric) narrow them, and 18 is the half-elf's own ability maximum
    (`START.EXE 0x00F3E0`).
    """
    char = _base()
    levels = {"cleric": 5, "magic-user": 6}
    bits, code = _class_fields(levels)
    char.set("name", "CASTER", "made up", Confidence.CONFIRMED,
             Provenance.RESHAPED)
    char.set("race", RACE_HALF_ELF, "the only race offered cleric and "
             "magic-user at once")
    char.set("levels", levels, "the class ceiling for each, narrowed by the "
             "half-elf's own racial limits (5 cleric, 8-clamped-to-6 "
             "magic-user)")
    char.set("class_bits", bits, "computed from levels")
    char.set("char_class", code, "computed from class_bits and levels")
    char.set("wisdom", 18, "the half-elf's own ability maximum")
    capacity = spells_mod.capacity_by_class(levels, 18, GAME)
    total = sum(sum(row) for row in capacity.values())
    char.set("spells_castable", capacity, "goldbox.spells.capacity_by_class "
             "for cleric 5 / magic-user 6 at wisdom 18 -- excluded from the "
             "round trip: a C64 source has this recomputed (#547)")
    char.set("spells_memorised", list(range(total, 0, -1)),
             f"{total} distinct ids, descending -- the sum of the capacity "
             f"above; the corpus reaches 17 (WISHHEL)")
    char.set("spells_known", list(range(1, 56)),
             "every id the C64 mask has a bit for, 1 to 55 (#509)")
    char.set("innate_effects", _innate_for_race(RACE_HALF_ELF),
             "a half-elf seeds nothing (measured)")
    return char


def warrior() -> NeutralCharacter:
    """The dwarf fighter 8: the class ceiling, the hit-point ceiling, every
    ability at its racial maximum, the longest legal name, a full sixteen
    item slots, the format's own ceiling on every coin purse, and the four
    racial ids a dwarf's own `.SPC` file carries.
    """
    char = _base()
    level = 8
    levels = {"fighter": level}
    bits, code = _class_fields(levels)
    hp_max = (level_tables.at_level("fighter", level, GAME).hp_max
              + level * level_tables.constitution_hp_bonus(
                  18, fighter=True, game=GAME))
    char.set("name", "AAAAAAAAAAAAAAA", "made up: fifteen characters, the "
             "DOS name_text width", Confidence.CONFIRMED, Provenance.RESHAPED)
    char.set("race", RACE_DWARF, "the sturdiest race with a full four-id "
             "innate-effects seed (#84)")
    char.set("levels", levels, "the class ceiling; every race's fighter "
             "limit is 8 or more except the gnome's 6")
    char.set("class_bits", bits, "computed from levels")
    char.set("char_class", code, "computed from class_bits and levels")
    char.set("experience", level_tables.clamp_threshold("fighter", level,
                                                        GAME),
             "what the trainer clamps to at the ceiling (GEN $23D4)")
    char.set("hp_max", hp_max,
             "the fighter's own hit-die maximum plus the constitution bonus "
             "at every level -- the most the dice and the bonus give")
    char.set("hp_current", hp_max, "full health")
    char.set("hp_rolled", hp_max, "matches hp_max: nothing lost to drain")
    for name in ("strength", "intelligence", "wisdom", "dexterity",
                "constitution", "charisma"):
        char.set(name, 18, "the per-race maxima are all 18 for a human and "
                 "a half-elf (START.EXE 0x00F3E0); used here as an "
                 "unremarkable legal ceiling")
    char.set("exceptional_strength", 100, "18/00, stored as 100")
    char.set("inventory", [_item() for _ in range(16)],
             "the C64's own sixteen slots (goldbox.items.ITEMS_PER_CHARACTER)"
             "; a C64 source can hand over no more")
    for coin in ("copper", "silver", "electrum", "gold", "platinum", "gems",
                "jewelry"):
        char.set(coin, 0xFFFF, "the format's own ceiling on both ports "
                 "(U16); whether the game caps coins lower is UNMEASURED, "
                 "so this is a format extreme and says so")
    char.set("innate_effects", _innate_for_race(RACE_DWARF),
             "the most any race seeds (#84)")
    return char


def thief() -> NeutralCharacter:
    """The halfling thief 9 at dexterity 18: the class ceiling (unlimited
    for every race, so 9 is the table's own last row), halfling because it
    leads on two of the eight stored percentages (`thief_move_silently`,
    `thief_hide_in_shadows`) -- no single race reaches every column's own
    ceiling at once, checked across all seven races for thief 9 at dexterity
    18: dwarf leads `thief_open_locks` and `thief_find_traps`, half-orc leads
    `thief_climb_walls`, gnome leads `thief_hear_noise`, and `thief_pick_
    pockets` and `thief_read_languages` each go to a different race again.
    """
    char = _base()
    level = 9
    levels = {"thief": level}
    bits, code = _class_fields(levels)
    expected = level_tables.dos_thief_skills(level, RACE_HALFLING, GAME,
                                             dexterity=18)
    char.set("name", "THIEF", "made up", Confidence.CONFIRMED,
             Provenance.RESHAPED)
    char.set("race", RACE_HALFLING, "leads two of the eight stored "
             "percentages (move_silently, hide_in_shadows); no single race "
             "leads all eight (checked across all seven races)")
    char.set("dexterity", 18, "the dexterity block's own top row")
    char.set("levels", levels, "the thief ceiling; no race limits it")
    char.set("class_bits", bits, "computed from levels")
    char.set("char_class", code, "computed from class_bits and levels")
    for name, value in zip(
            ("thief_pick_pockets", "thief_open_locks", "thief_find_traps",
             "thief_move_silently", "thief_hide_in_shadows",
             "thief_hear_noise", "thief_climb_walls",
             "thief_read_languages"), expected):
        char.set(name, value, "goldbox.levels.dos_thief_skills for thief 9, "
                 "halfling, dexterity 18 -- excluded from the round trip: a "
                 "C64 source has these eight recomputed at the destination "
                 "(#431, #440)")
    char.set("innate_effects", _innate_for_race(RACE_HALFLING),
             "the two records a halfling's own kind carries")
    return char


def triple() -> NeutralCharacter:
    """The deepest legal combination: half-elf cleric 5 / fighter 8 /
    magic-user 6, the same 20 spells the caster memorises, and three of the
    DOS level array's eight slots filled at once.
    """
    char = _base()
    levels = {"cleric": 5, "fighter": 8, "magic-user": 6}
    bits, code = _class_fields(levels)
    char.set("name", "TRIPLE", "made up", Confidence.CONFIRMED,
             Provenance.RESHAPED)
    char.set("race", RACE_HALF_ELF, "the only race offered all three at "
             "once (tools/classlegality.py)")
    char.set("levels", levels, "each class's own ceiling, cleric narrowed "
             "by the half-elf's racial limit")
    char.set("class_bits", bits, "computed from levels")
    char.set("char_class", code, "computed from class_bits and levels")
    char.set("wisdom", 18, "the half-elf's own ability maximum")
    capacity = spells_mod.capacity_by_class(levels, 18, GAME)
    total = sum(sum(row) for row in capacity.values())
    char.set("spells_castable", capacity, "goldbox.spells.capacity_by_class "
             "-- excluded from the round trip: a C64 source has this "
             "recomputed (#547)")
    char.set("spells_memorised", list(range(total, 0, -1)),
             f"{total} distinct ids, descending -- the same 20 the caster "
             f"case reaches")
    char.set("spells_known", list(range(1, 56)),
             "every id the C64 mask has a bit for, 1 to 55 (#509)")
    char.set("innate_effects", _innate_for_race(RACE_HALF_ELF),
             "a half-elf seeds nothing (measured)")
    return char


#: Every case, by name -- what `tests/test_boundary.py` parametrises over and
#: what `__main__` below prints.
CASES = {
    "caster": caster,
    "warrior": warrior,
    "thief": thief,
    "triple": triple,
}


def main(argv=None) -> int:
    for name, build in CASES.items():
        char = build()
        print(f"{name} ({char.get('name')!r})")
        for field in char.keys():
            print(f"  {field}: {char.get(field)!r}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
