#!/usr/bin/env python3
"""Generate the high-level test party, records and all, from code alone.

`#10 (Finish the high-level test party)` asked for a **generator, not a
disk**.  A party that exists only as a saved image is a party somebody has to
keep -- and the one this project drove through the training hall on
2026-08-22, `work/drive/P18PARTY.D64`, is gone from this machine, so that is
not a hypothetical.  This rebuilds an equivalent party from nothing in about a
second, with no emulator and no game bytes in the repository.

What it does not do
-------------------
Three things, each with the reason:

* **No items.**  Every generated character carries an empty inventory, so the
  roster's damage bonus and damage dice are zero and nobody is armed.  The
  item templates live on the player's own disks (`tools/gentemplates.py`), so
  equipping is a disk read this tool does not yet do; `Spec.inventory` is the
  hook, and filling it is the obvious next step.  It also means the sixteen-
  item ceiling `.claude/rules/conversions.md` names is **not** exercised here.
* **No combat icon.**  `goldbox.c64_codec.write` reports it, because a
  generated character has no combat art to turn into eighteen C64 screen
  codes -- `#130 (A converted DOS party arrives with six identical combat
  figures, not its own)` is the same gap from the other direction.
* **No trait ceiling.**  Pool of Radiance's C64 seeds trait slots from
  `GEN $0BF3`'s `[1, 0, 107, 0, 124, 0, 0, 0]`, indexed by the race byte, so
  only an elf (107) and a half-elf (124) are born with anything at all --
  MAGNUS, a dwarf, carries an empty block (`goldbox/traits.py`).  DOS seeds a
  dwarf four ids and the C64 does not, so no C64-born party can fill more than
  one of the ten slots and the dwarf here fills none.

**And one thing `--disk` keeps rather than generates, deliberately**: the base
save's header -- where the party is standing, the loaded map and script, the
clock and the quest flags.  A generated party arrives wherever the base save's
party was, which is somewhere the game already agrees is legal.  Everything
else that belongs to a character is overwritten, including the item pages and
the combat icons, so nobody inherits the base party's gear or art.

Where each number comes from
----------------------------
The generator is two halves and they have different authorities.

**Level 1 is seeded from the tables, checked against six characters the engine
itself rolled.**  `WISH-SPEC-por-party-l1-rolled` is six DOS Pool of Radiance
characters captured between creation and `ADD CHARACTER TO PARTY`, driven by
`tools/dosparty.py` for `#249 (Build a DOS party from creation and level it
ourselves, so DOS measurements rest on records we watched being written)`.
Every level-1 constant below is what those six hold:

| what creation writes | the six | here |
|---|---|---|
| `experience` | 0 | 0 |
| `thac0_base` | 40, i.e. THAC0 20, every class | `levels.at_level(cls, 1)` |
| `armour_class_base` | 50, i.e. AC 10 | 50 |
| `movement` | 12 | 12 |
| `attack_forms` | `02 00 01 00 02 00 00 00` | the same eight bytes |
| `attack_level` | **1 for every class**, magic-user included | 1 |
| `hp_max` | `hp_rolled + constitution bonus` | `levels`, via the same rule |
| `hp_rolled` | a plain roll of the class's die for a single-class character; **more than the trainer's rule allows** for a multi-class one | see `_seed_hit_points`, where the multi-class rule is a guess |

`tests/test_testparty.py` re-derives each of those from the specimen rather
than trusting this table, and skips where the specimen tree is absent.

**Every level above 1 is `goldbox.levelup`**, which is the training hall
reproduced routine by routine and was measured over twenty-nine trainings
(`docs/135-levelling.md`).  So the generator does not read the level tables
itself for THAC0, saving throws, thief skills, spell slots, turning power,
attacks a round or the experience clamp: it grants experience and calls
`plan`, which is what the school does.

**The die is the one thing nothing derives.**  `--rolls max` hands `plan` an
rng that always returns the largest number it could have rolled, which is what
makes the party reach the documented ceilings and makes it reproducible;
`--rolls min` and `--rolls seeded` are the other two.  The number is *chosen*
and this says so wherever it prints one.

Two corrections to `docs/119-test-party.md` this run forced
-----------------------------------------------------------
* **ASTRA cannot be a cleric 6.**  A half-elf's cleric limit is 5 --
  `GEN $1E64`, seven races of four classes, CONFIRMED -- so the plan's
  6 / 6 / 6 is refused by the game's own clamp and by `levelup.plan`.  She is
  generated as cleric 5 / fighter 6 / magic-user 6, which still puts both
  nibbles of `spells_castable` above zero, which is what she was for.
* **A wound cannot come from the trainer.**  Training heals to the new maximum
  (MAGNUS went in at 2 of 9 and came out at 13 of 13), so BULWARK's wound is
  applied *after* the last training, as an edit, and is reported as one.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import random
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from goldbox import (  # noqa: E402
    c64_codec,
    classcode,
    derive,
    games,
    levels,
    levelup,
    portraits,
    savegame,
)
from goldbox.d64 import D64  # noqa: E402
from goldbox.neutral import NeutralCharacter, Provenance  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402

#: The five saving throws in stored order, so the seed writes them in the same
#: order `goldbox.levelup` rewrites them at every level after the first.
SAVE_FIELDS = ("save_paralysis", "save_petrification", "save_wands",
               "save_breath", "save_spell")

#: What creation writes into `attack_forms` at `0x0D9`: one attack, stored
#: doubled, then the form's damage.  All six engine-rolled level-1 records
#: hold exactly these eight bytes.
CREATION_ATTACK_FORMS = bytes((2, 0, 1, 0, 2, 0, 0, 0))

#: `armour_class_base` and `thac0_base` are stored `60 - value`; creation
#: writes AC 10 and THAC0 20 for every class.
CREATION_ARMOUR_CLASS = 50
CREATION_MOVEMENT = 12

#: `GEN $0BF3`, indexed by the race byte: the only innate effects a C64 Pool
#: of Radiance character is born with.  DOS seeds a dwarf, a gnome and a
#: halfling as well and the C64 does not (`goldbox/traits.py`,
#: `goldbox/dos.py`'s `RACE_COMBAT_EFFECTS`), which is why no generated C64
#: party can exercise more than one of the ten trait slots.
C64_RACE_TRAIT_SEED: dict[int, tuple[int, ...]] = {2: (107,), 4: (124,)}

#: Races whose characters are stored small.  Neutral `size_small` is "0 small,
#: 1 large", which is the opposite way round from the name.
SMALL_RACES = frozenset({1, 3, 5})


class FixedRolls(random.Random):
    """An rng that always returns one end of every range, so a party is the
    same party every time.

    `goldbox.levelup` draws twice: `randint(1, die)` for the hit die and
    `randrange(class_count)` for the round-up that splits it between a
    multi-class character's classes.  Returning the top of the first and 0
    from the second -- which `divide_between_classes` turns into a roll of 1,
    and Pool of Radiance rounds up on `<=` -- is the largest hit point total
    the trainer could have produced.  `high=False` is the smallest.
    """

    def __init__(self, high: bool = True) -> None:
        super().__init__(0)
        self.high = high

    def randint(self, a: int, b: int) -> int:      # noqa: D102
        return b if self.high else a

    def randrange(self, *args, **kwargs) -> int:   # noqa: D102
        stop = args[0] if args else 1
        return 0 if self.high else max(0, int(stop) - 1)


def rolls_for(mode: str, seed: int = 0):
    """The rng behind `--rolls`: `max`, `min` or `seeded`."""
    if mode == "max":
        return FixedRolls(True)
    if mode == "min":
        return FixedRolls(False)
    if mode == "seeded":
        return random.Random(seed)
    raise SystemExit(f"--rolls wants max, min or seeded, not {mode!r}")


@dataclasses.dataclass(frozen=True)
class Spec:
    """One character to generate, in the terms a player would describe them.

    `levels` is class name to the level wanted, and everything derived from it
    -- THAC0, the five saves, the thief skills, spell capacity, turning power,
    attacks a round, hit points -- comes out of the trainer rather than out of
    this table.  `experience` is what the party is given before the last
    training; the trainer's own clamp then decides what the record keeps.
    """

    name: str
    race: int
    sex: int
    levels: dict[str, int]
    abilities: dict[str, int]
    alignment: int
    age: int
    experience: int
    #: Menu positions into the game's own creation menu, 0-13 and 0-11.
    portrait: tuple[int, int]
    gold: int = 0
    #: Hit points below the maximum, applied after the last training because
    #: the trainer heals.  0 means unwounded.
    wound: int = 0
    #: Sixteen-byte item records.  Empty, for now -- see the module docstring.
    inventory: tuple[bytes, ...] = ()
    #: The hit points creation rolled, when they are already known -- which is
    #: what rebuilding a character the engine rolled needs, since **the rule
    #: creation uses is not the trainer's**.  None asks `_seed_hit_points`.
    hit_points_rolled: "int | None" = None
    #: Why this character is in the party, for `--list`.
    proves: str = ""

    @property
    def class_bits(self) -> int:
        return sum(classcode.CLASS_BIT_FOR_NAME[n] for n in self.levels)


#: The six of `docs/119-test-party.md` §1, with ASTRA's cleric dropped to the
#: level a half-elf is allowed -- see the module docstring.
PARTY: tuple[Spec, ...] = (
    Spec(name="WARDEN", race=7, sex=1, levels={"cleric": 6},
         abilities=dict(strength=14, intelligence=11, wisdom=18, dexterity=12,
                        constitution=16, charisma=13, exceptional_strength=0),
         alignment=0, age=25, experience=30000, portrait=(1, 0), gold=5000,
         proves="cleric spell slots above the class table, because a WIS 18 "
                "bonus lands in the high nibble of spells_castable; every "
                "cleric spell id set in the spellbook"),
    Spec(name="EMBER", race=7, sex=0, levels={"magic-user": 6},
         abilities=dict(strength=10, intelligence=17, wisdom=11, dexterity=15,
                        constitution=14, charisma=12, exceptional_strength=0),
         alignment=4, age=24, experience=42000, portrait=(4, 2), gold=5000,
         proves="the top spell level the game implements, the low nibble of "
                "spells_castable, and a spellbook that is a subset rather "
                "than every bit set"),
    Spec(name="PILFER", race=5, sex=0, levels={"thief": 9},
         abilities=dict(strength=12, intelligence=13, wisdom=10, dexterity=18,
                        constitution=15, charisma=14, exceptional_strength=0),
         alignment=3, age=40, experience=115000, portrait=(7, 5), gold=5000,
         proves="the highest level anywhere in the game's tables; all eight "
                "thief skills off their level-1 values, with a halfling's "
                "read-languages crossing zero from below"),
    Spec(name="BULWARK", race=7, sex=0, levels={"fighter": 8},
         abilities=dict(strength=18, intelligence=10, wisdom=10, dexterity=16,
                        constitution=18, charisma=12, exceptional_strength=76),
         alignment=1, age=22, experience=130000, portrait=(0, 1), gold=5000,
         wound=40,
         proves="the fighter ceiling -- THAC0 13, hp_max 112 and 3/2 attacks "
                "at 0x0D9 -- carried wounded, which the trainer cannot do"),
    Spec(name="GRIMSTONE", race=1, sex=0,
         levels={"fighter": 7, "thief": 8},
         abilities=dict(strength=17, intelligence=10, wisdom=11, dexterity=17,
                        constitution=17, charisma=9, exceptional_strength=0),
         alignment=1, age=75, experience=150000, portrait=(2, 3), gold=5000,
         proves="a multi-class character far above level 1: two different "
                "non-zero entries in the per-class array at 0x0C9, which is "
                "the only thing that separates level from the class's level"),
    Spec(name="ASTRA", race=4, sex=1,
         levels={"cleric": 5, "fighter": 6, "magic-user": 6},
         abilities=dict(strength=15, intelligence=16, wisdom=17, dexterity=16,
                        constitution=15, charisma=13, exceptional_strength=0),
         alignment=0, age=45, experience=135000, portrait=(9, 8), gold=5000,
         proves="the widest class mask the game supports, and the only record "
                "in which both nibbles of spells_castable are non-zero at "
                "once; the half-elf trait seed 124 in the first trait slot"),
)


def _seed_hit_points(spec: Spec, game, rng) -> int:
    """The hit points a level-1 character starts with.

    **A single-class character's is the trainer's rule and a multi-class
    character's is not.**  All four single-class records among the six the
    engine rolled hold a plain roll of the class's own die -- cleric 6 of a
    d8, fighter 6 of a d10, magic-user 4 of a d4, thief 4 of a d6 -- which is
    what `goldbox.levelup.roll_hit_points` gives.  The two multi-class ones
    hold **more than that rule allows**: the dwarf fighter/thief stores 6,
    where one die divided between two classes could never exceed 5, and the
    half-elf cleric/fighter/magic-user stores 7 against a ceiling of 5.  Both
    fit "one die per class, averaged", which is AD&D's own creation rule and
    is *not* the rule `GEN $208D` uses at the school.

    So for a multi-class character this **UNMEASURED** rule is used and said
    to be a guess, and a caller who knows the number hands it in through
    `Spec.hit_points_rolled` instead.  The experiment that would settle it:
    roll six multi-class characters in the game's own creation screens with
    `tools/dosparty.py` and see whether any `hp_rolled` exceeds the largest
    single die of the character's classes.
    """
    if spec.hit_points_rolled is not None:
        return spec.hit_points_rolled
    order = [n for n in levels.for_game(game).class_order if n in spec.levels]
    if len(order) <= 1:
        first = order[0] if order else next(iter(spec.levels))
        return levelup.roll_hit_points(
            first, class_count=1, fighter_only=(spec.class_bits == 8),
            rng=rng, game=game, level=1)
    total = sum(rng.randint(1, levels.hit_die(name, game) or 4)
                for name in order)
    return max(1, total // len(order))


def level_one(spec: Spec, game, rng) -> tuple[CharacterRecord, object]:
    """The record character creation would have written, as 580 C64 bytes.

    Built through `goldbox.c64_codec.write`, which is the reviewed writer the
    conversions use and the thing that accounts for all 580 bytes: a second
    record builder here would be a second, unreviewed opinion about the same
    format.  The report it hands back is what says what could not be made.
    """
    tables = levels.for_game(game)
    class_levels = {name: 1 for name in spec.levels}
    char = NeutralCharacter("generated", source="tools/testparty.py",
                            game=game)

    def put(name, value, origin):
        char.set(name, value, origin, how=Provenance.COMPUTED)

    put("name", spec.name, "the party specification")
    put("sex", spec.sex, "the party specification")
    put("race", spec.race, "the party specification")
    put("alignment", spec.alignment, "the party specification")
    put("age", spec.age, "the party specification")
    put("class_bits", spec.class_bits, "the party specification")
    put("char_class",
        classcode.code_for(spec.class_bits, class_levels, game=game),
        "the class code the mask names")
    for ability, score in spec.abilities.items():
        put(ability, score, "the party specification")

    put("level", 1, "character creation, which starts every class at 1")
    put("levels", class_levels, "character creation")
    put("experience", 0,
        "character creation, which writes 0 in all six engine-rolled records")

    rolled = _seed_hit_points(spec, game, rng)
    bonus = tables.constitution_hp_bonus(
        spec.abilities["constitution"], fighter="fighter" in spec.levels)
    hp_max = max(1, rolled + bonus)
    put("hp_rolled", rolled, "a hit die, chosen rather than rolled")
    put("hp_max", hp_max, "the roll plus the constitution bonus, GEN $2079")
    put("hp_current", hp_max, "created characters start whole")

    row = min((tables.at_level(n, 1).thac0 for n in class_levels),
              default=20)
    put("thac0_base", 60 - row, "the class table at level 1")
    put("thac0_current", 60 - row, "the same, with nothing carried")
    put("armour_class_base", CREATION_ARMOUR_CLASS, "AC 10, unarmoured")
    # The cached copy carries the dexterity bonus and the base does not, in
    # all six engine-rolled records: DEX 15 stores 51, DEX 16 stores 52 and
    # DEX 18 stores 54, against 50 for every dexterity below 15.
    put("armour_class",
        CREATION_ARMOUR_CLASS
        + derive.dexterity_ac_bonus(spec.abilities["dexterity"]),
        "AC 10 less the dexterity bonus, the way creation caches it")
    put("movement", CREATION_MOVEMENT, "12, in all six engine-rolled records")
    put("movement_current", CREATION_MOVEMENT, "12, unencumbered")
    put("attack_level", 1,
        "1 in all six engine-rolled records, whatever the class")
    put("attack_forms", CREATION_ATTACK_FORMS,
        "one attack, stored doubled, as all six engine-rolled records hold it")
    put("size_small", 0 if spec.race in SMALL_RACES else 1,
        "the race's own size")

    saves = tables.saving_throws(class_levels, spec.race,
                                 spec.abilities["constitution"])
    for field, value in zip(SAVE_FIELDS, saves or ()):
        put(field, value, "the class table less the C64's constitution bonus")

    if "thief" in class_levels:
        skills = tables.thief_skill_row(1, spec.race,
                                        spec.abilities["dexterity"])
        for field, value in zip(levelup.THIEF_FIELDS, skills or ()):
            put(field, value, "the level-1 thief row plus the racial row")

    turning = levels.turning_level(class_levels.get("cleric", 0), game)
    if turning is not None:
        put("turn_power", turning, "the cleric's turning level")

    # `roster_tail` is the nine bytes at `0x110` -- the armour bonus, the two
    # attack forms, the damage dice and the damage bonus. Only the damage
    # bonus is a property of the character rather than of a readied weapon,
    # and `goldbox.derive.check` is the thing that asks for it, so that byte
    # is written and the other eight are left zero.
    #
    # UNVERIFIED: nothing here has watched the engine rebuild an *unarmed*
    # character's tail, so whether those eight zeros are what a fight would
    # leave behind is open. The experiment is one boot -- load a generated
    # party, start a fight, and read `$8300 + slot * 0x20 + 0x10` for nine
    # bytes before and after the first round.
    tail = bytearray(9)
    tail[0x17 - 0x10] = derive.strength_bonuses(
        spec.abilities["strength"],
        spec.abilities.get("exceptional_strength", 0))[1] & 0xFF
    put("roster_tail", bytes(tail),
        "the strength damage bonus; the weapon's terms are zero because "
        "nothing is readied")

    put("status", "okay", "a created character is well")
    put("active", True, "a created character is in the party")
    put("npc", False, "the player made this one")
    put("hostile", False, "0 for every player character on both ports")
    put("quickfight", False, "nobody has chosen QUICK yet")

    for coin in ("copper", "silver", "electrum", "platinum", "gems",
                 "jewelry"):
        put(coin, 0, "the party specification")
    put("gold", spec.gold, "the party specification")
    # Encumbrance is deliberately not set: the C64 record has no field for it
    # and rebuilds the number when a screen draws it. It is worth knowing for
    # a DOS generator, though -- a coin weighs one unit, and `encumbrance`
    # equals the gold exactly in all six engine-rolled DOS records, at 70, 90,
    # 100, 100, 110 and 140 against gold of the same six numbers.
    put("inventory", list(spec.inventory), "the party specification")

    put("spells_known", [], "a level-1 spellbook, filled by the trainer")
    put("spells_memorised", [], "nothing is memorised yet")
    put("spells_castable", {}, "written by the trainer at every level")
    put("innate_effects", list(C64_RACE_TRAIT_SEED.get(spec.race, ())),
        "GEN $0BF3's race-indexed seed table")
    put("granted_effects", [], "no item is readied")

    menu = portraits.stored_tables(game)
    if menu is not None:
        head, body = spec.portrait
        put("portrait_head", menu.heads[head % len(menu.heads)],
            "the game's own creation menu")
        put("portrait_body", menu.bodies[body % len(menu.bodies)],
            "the game's own creation menu")

    return c64_codec.write(char)


@dataclasses.dataclass
class Built:
    """One generated character: the record, and how it got there."""

    spec: Spec
    record: CharacterRecord
    steps: list[str] = dataclasses.field(default_factory=list)
    gaps: list[str] = dataclasses.field(default_factory=list)
    notes: list[str] = dataclasses.field(default_factory=list)


def build(spec: Spec, game=None, rolls: str = "max", seed: int = 0) -> Built:
    """Generate one character, level 1 to the levels the spec asks for.

    Experience is granted before each training and the trainer's own clamp
    decides what is kept, which is exactly the route
    `docs/119-test-party.md` §2 calls (b): write `0x0E8` past the threshold
    and let the school do the arithmetic.
    """
    game = game or games.by_key("pool-of-radiance")
    rng = rolls_for(rolls, seed)
    record, report = level_one(spec, game, rng)
    out = Built(spec=spec, record=record,
                gaps=list(report.dropped), notes=list(report.warnings))
    if report.unaccounted:
        raise SystemExit(f"{spec.name}: {len(report.unaccounted)} of 580 "
                         f"bytes have no provenance; refusing to generate a "
                         f"record nobody can explain")

    wanted = dict(spec.levels)
    guard = 0
    while True:
        guard += 1
        if guard > 200:
            raise SystemExit(f"{spec.name}: level-up did not converge")
        behind = [n for n in wanted
                  if levelup.class_level(out.record, n) < wanted[n]]
        if not behind:
            break
        # The class furthest from where it should end up, so a multi-class
        # character does not stall behind the experience clamp.
        name = max(behind,
                   key=lambda n: wanted[n] - levelup.class_level(out.record, n))
        at = levelup.class_level(out.record, name)
        need = levels.next_threshold(name, at, game)
        last = sum(wanted.values()) - sum(
            levelup.class_level(out.record, n) for n in wanted) == 1
        out.record.set("experience",
                       max(spec.experience if last else 0, need or 0))
        learn = None
        if name == "magic-user":
            offered = levelup.learnable(out.record, game, level=at + 1)
            learn = offered[0] if offered else None
        plan = levelup.plan(out.record, name, game=game, rng=rng, learn=learn)
        cached = out.record.get("thac0")
        out.record = levelup.apply_to(out.record, plan)
        # `apply_to` moves `thac0_base` at `0x071` and leaves the roster's
        # cached THAC0 at `0x10E` alone, because that copy carries the
        # strength bonus and the readied weapon on top of the base. `GEN`
        # moves it by the same delta rather than overwriting it, which is
        # what `Plan.thac0_delta` is for.
        out.record.set("thac0", cached + plan.thac0_delta)
        out.steps.append(
            f"{name} {plan.from_level}->{plan.to_level}: "
            f"{plan.hit_points_rolled} hit points, THAC0 "
            f"{60 - out.record.get('thac0_base')}, "
            f"{out.record.get('experience')} experience")

    if spec.wound:
        maximum = out.record.get("hp_max")
        out.record.set("hp_current", max(1, maximum - spec.wound))
        out.notes.append(
            f"wounded to {out.record.get('hp_current')} of {maximum} after "
            f"the last training, because the trainer heals to the maximum "
            f"and cannot leave a character hurt")
    return out


def party(game=None, rolls: str = "max", seed: int = 0,
          specs: "tuple[Spec, ...]" = PARTY) -> list[Built]:
    """The whole party, in marching order."""
    game = game or games.by_key("pool-of-radiance")
    built = [build(spec, game, rolls, seed) for spec in specs]
    for position, one in enumerate(built):
        one.record.set("party_order", position)
    return built


def summary(one: Built) -> dict:
    """What a generated character came out as, for `--json` and for a test."""
    rec = one.record
    return {
        "name": str(rec.name),
        "race": rec.get("race"),
        "class_bits": rec.get("class_bits"),
        "levels": {n: levelup.class_level(rec, n) for n in one.spec.levels},
        "level": rec.get("level"),
        "experience": rec.get("experience"),
        "thac0": rec.thac0_base_value,
        "hp_max": rec.get("hp_max"),
        "hp_current": rec.get("hp_current"),
        "hp_rolled": rec.get("hp_rolled"),
        "saves": [rec.get(n) for n in SAVE_FIELDS],
        "attacks_doubled": rec.get_raw("attack_forms")[0],
        "turn_power": rec.get("turn_power"),
        "spells_castable": rec.get_raw("spells_castable").hex(),
        "thief_skills": [rec.get(n) for n in levelup.THIEF_FIELDS],
        "traits": [b for b in rec.get_raw("item_effects") if b],
        "steps": one.steps,
        "gaps": one.gaps,
        "notes": one.notes,
    }


def write_records(built: list[Built], out: pathlib.Path) -> list[pathlib.Path]:
    """One 582-byte `.CHR` export per character, the shape `wish` reads."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for one in built:
        path = out / f"{str(one.record.name).replace(' ', '_')}.CHR"
        path.write_bytes(one.record.to_prg())
        written.append(path)
    return written


def write_disk(built: list[Built], base: pathlib.Path, out: pathlib.Path,
               keep_icons: bool = False) -> pathlib.Path:
    """Put the party on a **copy** of a save disk, and never on the original.

    The player's own disk is opened nowhere here: `base` is copied to `out`
    first and every write lands on the copy, which is the promise
    `docs/119-test-party.md` §4 makes and the one `wish` itself makes.

    **A character goes into three places**, because that is where the C64
    keeps one: the first 256 bytes into the save slot; the 32-byte roster
    block at record `0x100` into `SAVEDGAME1`, which is where the armour
    class, the THAC0 and the current hit points a sheet draws are cached; and
    the record's own 256-byte item block at `0x120` into the save's item page
    for that slot, which is `goldbox.items.ITEM_AREA_BASE + slot * 0x100`.

    **The item page is written even though nobody carries anything**, and
    that is the point: leaving it alone would hand a generated character the
    base disk's party's gear, which is inherited data wearing our name.  The
    combat icons go the same way and for the same reason -- `--keep-icons`
    leaves the disk's own, which is the only art on it that is known to draw,
    and is a deliberate exception a caller has to ask for.

    **What the copy keeps, deliberately**, is the base save's header: where
    the party is standing, which map and script are loaded, the clock and the
    quest flags.  A generated party arrives wherever the base save's party
    was, which is a place the game agrees is legal; generating one would be a
    second experiment.
    """
    from goldbox import icons, items

    if len(built) > savegame.ROSTER_COUNT:
        raise SystemExit(f"a party holds at most {savegame.ROSTER_COUNT}")
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(base, out)
    disk = D64.open(str(out))
    game, sg0, sg1 = savegame.load_save(disk)
    if sg1 is None:
        raise SystemExit(f"{base.name} carries no roster file, so a party "
                         f"written into it would have no combat numbers")

    roster = bytearray(sg1.to_bytes())
    payload = bytearray(sg0.to_bytes())
    item_base = items.ITEM_AREA_BASE - game.save_load_address
    icon_base = icons.ICON_TABLE_BASE - game.save_load_address
    for index in range(savegame.ROSTER_COUNT):
        one = built[index] if index < len(built) else None
        record = one.record if one else None
        sg0.write_record(index, record if record
                         else bytes(savegame.SLOT_STRIDE))
        at = index * savegame.ROSTER_STRIDE
        roster[at:at + savegame.ROSTER_STRIDE] = (
            record.slice(0x100, savegame.ROSTER_STRIDE) if record
            else bytes(savegame.ROSTER_STRIDE))
        at = item_base + index * items.ITEM_BLOCK_STRIDE
        payload[at:at + items.ITEM_BLOCK_STRIDE] = (
            record.slice(0x120, items.ITEM_BLOCK_STRIDE) if record
            else bytes(items.ITEM_BLOCK_STRIDE))
        if not keep_icons:
            at = icon_base + index * icons.ICON_SIZE
            payload[at:at + icons.ICON_SIZE] = bytes(icons.ICON_SIZE)

    # The slot writes went into `sg0`; the item and icon writes went into a
    # copy of its payload, so put the slots back over it rather than losing
    # one set or the other.
    for index in range(savegame.ROSTER_COUNT):
        at = sg0.game.slot_area_base - game.save_load_address \
            + index * savegame.SLOT_STRIDE
        payload[at:at + savegame.SLOT_STRIDE] = \
            sg0.slot(index).window[:savegame.SLOT_STRIDE]

    savegame.store_save(disk, savegame.SaveGame0.from_bytes(bytes(payload),
                                                            game),
                        savegame.SaveGame1(bytes(roster), game), game)
    disk.save(str(out))
    return out


def base_save_disk() -> pathlib.Path:
    """A save disk to copy: `$POR_DISKS` first, then `automap.paths`.

    The same one-liner `tools/geomap.py` uses, so a fourth way of finding the
    player's disks does not appear here.
    """
    import os

    from automap import paths

    where = os.environ.get("POR_DISKS") or paths.find_disks()
    if not where:
        raise SystemExit("no Pool of Radiance disks found; set $POR_DISKS")
    found = sorted(pathlib.Path(where).glob("PORSAVE*.[dD]64"))
    if not found:
        raise SystemExit(f"no PORSAVE disk in {where}")
    return found[0]


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rolls", default="max",
                    choices=("max", "min", "seeded"),
                    help="which hit die to hand the trainer (default: max, "
                         "which reaches the documented ceilings)")
    ap.add_argument("--seed", type=int, default=0,
                    help="the seed behind --rolls seeded")
    ap.add_argument("--list", action="store_true",
                    help="say what each character is for and stop")
    ap.add_argument("--json", action="store_true",
                    help="print what every character came out as")
    ap.add_argument("--records", type=pathlib.Path,
                    help="write one .CHR export per character into this "
                         "directory")
    ap.add_argument("--disk", type=pathlib.Path,
                    help="write the party onto a copy of a save disk at this "
                         "path; the original is never touched")
    ap.add_argument("--base", type=pathlib.Path,
                    help="the save disk to copy (default: the player's own)")
    ap.add_argument("--keep-icons", action="store_true",
                    help="leave the base disk's combat icons alone instead of "
                         "clearing them; inherited art, and the only art on "
                         "the disk known to draw")
    args = ap.parse_args(argv)

    if args.list:
        for spec in PARTY:
            classes = ", ".join(f"{n} {lv}" for n, lv in spec.levels.items())
            print(f"{spec.name:<10s} {classes:<38s} {spec.proves}")
        return 0

    built = party(rolls=args.rolls, seed=args.seed)
    if args.json:
        print(json.dumps([summary(one) for one in built], indent=2))
    else:
        for one in built:
            s = summary(one)
            print(f"{s['name']:<10s} level {s['level']}  THAC0 {s['thac0']:>2}"
                  f"  {s['hp_current']}/{s['hp_max']} hp"
                  f"  {s['experience']:>7} xp"
                  f"  saves {s['saves']}")
        gaps = sorted({g for one in built for g in one.gaps})
        for gap in gaps:
            print(f"  not generated: {gap}")

    if args.records:
        for path in write_records(built, args.records):
            print(f"wrote {path}")
    if args.disk:
        base = args.base or base_save_disk()
        where = write_disk(built, base, args.disk, args.keep_icons)
        print(f"wrote {where} from {base}"
              + ("" if args.keep_icons else
                 "; item pages and combat icons cleared"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
