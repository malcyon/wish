"""What the training hall writes, reproduced field by field.

The training hall is the authority and this module copies it. `GEN $1B8C` is
the sequence a level-up runs, and every routine it calls has been read:

| what it does | routine | where it is here |
|---|---|---|
| per-class level `+1` at `0x0C9` | `$1FDE` | `plan` |
| `level` is the maximum of those | `$2021` | `plan` |
| THAC0, best of the classes | `$1EF3` | `plan` |
| the five saving throws | `$1F44`, `$2359` | `levels.saving_throws` |
| `attack_level`, and 3/2 attacks at fighter 7 | `$2342` | `plan` |
| the turning level at `0x0A4` | `$2388` | `levels.turning_level` |
| spell capacity, plus the wisdom bonus | `$20BC` | `_spells_castable` |
| the cleric's new spell level, granted whole | `$20CF` | `_cleric_spell_ids` |
| the magic-user's one new spell, **chosen** | `$215A` | `learnable` |
| the eight thief skills | `$1FEC` | `levels.thief_skills` |
| a hit die, and hit points from it | `$2037`, `$2079` | `roll_hit_points` |
| experience clamped to the next threshold | `$23D4` | `_experience` |

**One field is a die and cannot be anything else.** `hp_rolled` at `0x0ED`
takes a fresh roll of the class's hit die at every training, so this module
rolls one too rather than pretending to derive it. Everything the roll feeds --
`hp_max`, and the roster's current hit points -- follows from it exactly, by
`hp_max = hp_rolled + level * constitution bonus`, which is `$2079`.

**Money is not touched, and the trainer does touch it.** A training costs a
flat 1000 gold at every level and the rest of the character's coin is converted
to platinum -- measured across all twenty-nine. That is what walking into a
school costs, not what gaining a level costs, so none of the seven coin fields
at `0x0BB` is written here.

**Healing is done, because the trainer does it**: current hit points end at the
new maximum. MAGNUS went into the school at 2 of 9 and came out at 13 of 13.
The order matters and is the trainer's: roll, raise `hp_rolled` and `hp_max`,
*then* heal to the new maximum.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from dataclasses import field as dc_field

from . import levels, spells
from .games import CLASS_BITS_CLASSIC

#: `0x0C9` upwards, in class-bit order -- the order every one of the game's own
#: tables is indexed in.
CLASS_LEVEL_FIELD = {"magic-user": "level_magic_user", "cleric": "level_cleric",
                     "thief": "level_thief", "fighter": "level_fighter"}

#: The five saving throws, in stored order at `0x09A`.
SAVE_FIELDS = ("save_paralysis", "save_petrification", "save_wands",
               "save_breath", "save_spell")

#: The eight thief skills, in stored order at `0x0A5`.
THIEF_FIELDS = ("thief_pick_pockets", "thief_open_locks", "thief_find_traps",
                "thief_move_silently", "thief_hide_in_shadows",
                "thief_hear_noise", "thief_climb_walls",
                "thief_read_languages")

#: `0x0EE`-`0x0F0`: one byte a spell level, magic-user in the low nibble and
#: cleric in the high one. Pool of Radiance reaches three spell levels; `GEN
#: $20BC` clears nine bytes, so the field is wider than the game can fill.
SPELLS_CASTABLE_LEVELS = 3


class CannotLevel(Exception):
    """The character cannot take this level, and why."""


@dataclass(frozen=True)
class Plan:
    """Every field a level-up writes, and what it would write there.

    `fields` is record field name to value; `spellbook` is the seven bytes of
    `0x078` when they change, and None when they do not. Nothing here has
    touched a machine: a caller turns it into writes, and a test compares it
    with what the trainer produced for the same character.
    """

    class_name: str
    from_level: int
    to_level: int
    fields: dict[str, object]
    hit_points_rolled: int
    #: How much better `thac0_base` got. The roster's cached THAC0 at `+0x0E`
    #: carries strength and the readied weapon on top of it, so it is moved by
    #: this delta rather than overwritten -- which is what `GEN` does too.
    thac0_delta: int = 0
    #: The new `hp_max`. **Current hit points are set to it**, which is what
    #: the trainer does -- MAGNUS went into the school at 2 of 9 and came out
    #: at 13 of 13 -- and the order matters: the die is rolled, `hp_max` and
    #: `hp_rolled` rise, and only then does the heal happen, or the character
    #: is healed to the maximum it used to have.
    hp_max: int = 0
    spellbook: bytes | None = None
    learned_spell: int | None = None
    #: What the clamp at `GEN $23D4` throws away -- experience before minus
    #: experience after. Never negative; usually large, because the trainer
    #: leaves a character one point short of its next level whatever it
    #: arrived with. A caller that offers this as a button should say so.
    experience_lost: int = 0
    #: Classes that had the experience for a level before this training and do
    #: not after, because the clamp lowered the number past their threshold.
    #: Empty for a single-class character; see `_experience`.
    classes_disqualified: tuple[str, ...] = dc_field(default=())
    notes: tuple[str, ...] = dc_field(default=())


def classes_of(record) -> list[str]:
    """The character's classes, in class-bit order."""
    bits = record.get("class_bits") or 0
    return [name for bit, name in CLASS_BITS_CLASSIC if bits & bit]


def class_level(record, class_name: str) -> int:
    """The stored level for one class, falling back to the single level byte."""
    return (record.get(CLASS_LEVEL_FIELD[class_name])
            or record.get("level") or 1)


def ready_classes(record, game=None) -> list[str]:
    """Which of the character's classes have the experience for another level.

    **Experience is not divided between classes.** The trainer reads the whole
    stored number against the single-class table -- LADY KATHERINE, magic-user
    1 / thief 7 with 70,100 points, was offered thief 8, whose single-class
    threshold is 70,001 (`docs/119-test-party.md`). So each class is measured
    against the same number.

    **`>=`, against the game's own number, which is the published one plus 1.**
    `GEN $1BBC` walks the class's threshold column downwards and takes the
    first row it is not below (`SBC` then `BCS`), and the rows themselves hold
    2501 for magic-user 2 where AD&D prints 2500 -- so 2500 exactly is refused
    and 2501 is offered. `por/levels.py` stores the game's numbers, which is
    why the comparison here is a plain `>=`.
    """
    experience = record.get("experience") or 0
    out = []
    for name in classes_of(record):
        want = levels.next_threshold(name, class_level(record, name), game)
        if want is not None and experience >= want:
            out.append(name)
    return out


#: Class-bit order, as a plain list, for the tie-break in `best_next_class`.
_CLASS_ORDER = [name for _, name in CLASS_BITS_CLASSIC]


def best_next_class(ready, class_levels, game=None) -> str | None:
    """Which of the ready classes to train, when nobody has said.

    **The one whose threshold after the level it is about to gain is largest.**
    The clamp at `GEN $23D4` reads the *new* per-class levels -- `$1FDE` has
    already written them -- so the number that decides the ceiling is the one a
    class will have once it is raised, not the one it has now. Raising the
    class with the highest post-level threshold leaves the ceiling as high as
    it can be, which is what keeps the other classes above their own
    thresholds.

    The two readings genuinely differ: a magic-user 4 / thief 5 wants the
    magic-user by current threshold (22,501 against 20,001) and the thief by
    post-level threshold (42,501 against 40,001), and the thief is right --
    with 42,500 points the thief-first order reaches magic-user 6 / thief 6
    where magic-user-first stalls at 5 / 6. Across every two- and three-class
    combination in Pool of Radiance's tables the post-level rule never gains
    fewer levels and sometimes gains more.

    Ties break in class-bit order -- magic-user, cleric, thief, fighter --
    which is the order `0x0C9` stores and the order every one of the game's own
    tables is indexed in. Repeated calls then walk down the order themselves,
    because each level raises the class it just picked.
    """
    def rank(name: str):
        # None where the title's tables have no entry past the ceiling; sorts
        # last rather than raising, since something has to be picked.
        after = levels.clamp_threshold(name, class_levels[name] + 1, game)
        order = (_CLASS_ORDER.index(name) if name in _CLASS_ORDER
                 else len(_CLASS_ORDER))
        return (after or 0, -order)

    ready = [name for name in ready if name in class_levels]
    return max(ready, key=rank) if ready else None


def best_class(record, game=None) -> str | None:
    """The class `plan` would raise if it were not told which. None if none is
    ready."""
    return best_next_class(
        ready_classes(record, game),
        {name: class_level(record, name) for name in classes_of(record)},
        game)


def roll_hit_points(class_name: str, class_count: int = 1,
                    fighter_only: bool = False, rng=None, game=None) -> int:
    """One hit die, the way `GEN $2037` rolls it.

    The die is the class's own (`GEN $20A7`); a multi-class character divides
    the roll by how many classes it has, and never gets less than 1. **A
    single-class fighter never rolls below 4** -- `CMP #$04` against
    `class_bits == 8` and nothing else -- which is why no fighter in twenty-nine
    trainings gained fewer than four hit points.
    """
    die = levels.hit_die(class_name, game)
    if not die:
        raise CannotLevel(f"no hit die is known for {class_name}")
    rolled = (rng or random).randint(1, die)
    if class_count > 1:
        rolled = max(1, round(rolled / class_count))
    if fighter_only and rolled < 4:
        rolled = 4
    return rolled


def learnable(record, game=None, level: int | None = None) -> list[int]:
    """The magic-user spells the trainer would offer, in the order it offers.

    **The trainer does not roll and it does not grant.** `GEN $215A` walks the
    spellbook bitmask, keeps every id from 1 to 55 the character does not
    already know whose spell level is at or below `(level + 1) // 2`, drops
    every cleric spell, and puts the survivors on a menu. The player picks one
    and the level-up does not finish until they do -- which is why a magic-user
    needs a dialog and a cleric does not.

    **`level` is the level being trained *to*.** `GEN $1FDE` writes the new
    per-class levels before the menu is built, so a magic-user reaching 3 is
    offered second-level spells at that same training. Defaults to what the
    record already holds, for a caller asking what is on offer now.
    """
    if level is None:
        level = class_level(record, "magic-user")
    castable = (level + 1) // 2
    known = set(spells.spells_known(bytes(record)))
    out = []
    for spell_id in range(1, spells.LAST_SPELLBOOK_SPELL + 1):
        if spell_id in known:
            continue
        group = spells.spell_group(spell_id, game)
        if group is None:
            continue
        who, spell_level = group
        if who != "magic-user" or spell_level > castable:
            continue
        out.append(spell_id)
    return out


def _cleric_spell_ids(cleric_level: int, game=None) -> list[int]:
    """Every cleric spell a cleric of that level knows.

    `GEN $20CF` ORs whole spell levels in: the second at cleric 3 and the third
    at cleric 5. Expressed as "every cleric spell of a level it can cast",
    which is the same set and does not hard-code a bitmask.
    """
    castable = 1
    if cleric_level >= 3:
        castable = 2
    if cleric_level >= 5:
        castable = 3
    out = []
    for spell_id in range(1, spells.LAST_SPELLBOOK_SPELL + 1):
        group = spells.spell_group(spell_id, game)
        if group and group[0] == "cleric" and group[1] <= castable:
            out.append(spell_id)
    return out


def _spells_castable(record, class_levels: dict[str, int],
                     game=None) -> list[int]:
    """The whole `spells_castable` field, as `GEN $20BC` writes it.

    **Zeroed first, unconditionally** -- the routine clears the block before it
    looks at a class, so a fighter's bytes are cleared too. Then the cleric's
    row into the high nibble, with the wisdom bonus added only where the class
    table already gives a slot; then the magic-user's row into the low nibble.
    """
    width = len(record.get_raw("spells_castable"))
    out = [0] * width
    cleric = class_levels.get("cleric", 0)
    if cleric:
        row = levels.at_level("cleric", cleric, game)
        slots = list(row.spells) if row else []
        bonus = levels.wisdom_bonus_spells(record.get("wisdom"))
        for i in range(SPELLS_CASTABLE_LEVELS):
            have = slots[i] if i < len(slots) else 0
            if have:
                have += bonus[i]
            out[i] = (have & 0x0F) << 4
    magic_user = class_levels.get("magic-user", 0)
    if magic_user:
        row = levels.at_level("magic-user", magic_user, game)
        slots = list(row.spells) if row else []
        for i in range(SPELLS_CASTABLE_LEVELS):
            out[i] += (slots[i] if i < len(slots) else 0) & 0x0F
    return out[:width]


def _experience(record, class_levels: dict[str, int], game=None) -> int:
    """The clamp at `GEN $23D4`: one short of the largest next threshold.

    Across *all* the character's classes, not the one trained, and it only
    lowers -- a character below the clamp keeps what it had. The routine loops
    the four slots of the per-class level array at `0x0C9`, skips a zero, reads
    `threshold[class * 9 + level]` -- the row for the level *after* the one now
    stored -- keeps the largest, subtracts 1, and writes it only if it is less
    than what `0x0E8` holds.

    **Measured on a multi-class character, twice.** LADY KATHERINE, magic-user
    1 / thief 1 with 5,002 points, came out of the thieves' school at thief 2
    and **2,500** -- the larger of magic-user 2's 2,501 and thief 3's 2,501,
    minus one. At magic-user 2 / thief 9 she came out of the magic-user's
    school at **160,000**, which is the thief's entry one past its ceiling and
    not magic-user 3's 5,001. `work/p18/lk-{before,after}.hex` and
    `work/p18b/rec-kath-m2-*.bin`.

    So the rule is the game's, not an extrapolation from single-class runs, and
    it is why training the *lower* threshold first can cost a multi-class
    character a level it had already earned -- `docs/135-levelling.md`.
    """
    experience = record.get("experience") or 0
    ceiling = None
    for name, level in class_levels.items():
        want = levels.clamp_threshold(name, level, game)
        if want is not None:
            ceiling = want if ceiling is None else max(ceiling, want)
    if ceiling is None:
        return experience
    return min(experience, ceiling - 1)


def plan(record, class_name: str | None = None, *, game=None, rng=None,
         learn: int | None = None, rolled: int | None = None) -> Plan:
    """What one level in `class_name` would write. Raises rather than guessing.

    **An absent `class_name` means "the best one"** -- `best_next_class` picks
    it -- and not "refuse because two are ready". An explicit name still works
    and is what the byte-for-byte replay of the measured trainings passes.

    `learn` is the spell a magic-user picks. It is required whenever the
    trainer's own menu would have offered one, because the game does not finish
    the level-up until the choice is made and neither should we.

    `rolled` replaces the hit-die roll with a number already known, which is
    what replaying a measured training needs: the die is the one field nothing
    derives, so a test that wants to compare every *other* byte hands the roll
    in rather than hoping.
    """
    tables = levels.for_game(game)
    if not tables.thief_skills:
        raise CannotLevel(f"{tables.title}'s trainer tables have not been read")
    if not class_name:
        # Nothing ready falls through to the threshold check below, which says
        # which class and what it is short of -- a better answer than "no".
        class_name = (best_class(record, game)
                      or (classes_of(record) or [""])[0])
    if class_name not in classes_of(record):
        raise CannotLevel(f"{record.name} is not a {class_name}")

    class_levels = {name: class_level(record, name)
                    for name in classes_of(record)}
    from_level = class_levels[class_name]
    to_level = from_level + 1
    row = levels.at_level(class_name, to_level, game)
    if row is None:
        raise CannotLevel(f"{class_name} stops at {tables.ceiling(class_name)} "
                          f"in {tables.title}")
    race = record.get("race")
    limit = tables.racial_limit(race, class_name)
    if limit is not None and to_level > limit:
        raise CannotLevel(f"race {race} stops at {limit} as a {class_name}")
    want = levels.next_threshold(class_name, from_level, game)
    if want is None or (record.get("experience") or 0) < want:
        raise CannotLevel(f"{class_name} {to_level} needs {want} experience")

    class_levels[class_name] = to_level
    level = max(class_levels.values())
    bits = record.get("class_bits") or 0
    notes = []

    if rolled is None:
        rolled = roll_hit_points(
            class_name, class_count=len(class_levels),
            fighter_only=(bits == 8), rng=rng, game=game)
    hp_rolled = (record.get("hp_rolled") or 0) + rolled
    hp_max = hp_rolled + level * levels.constitution_hp_bonus(
        record.get("constitution"), fighter=bool(bits & 8))

    fields: dict[str, object] = {
        CLASS_LEVEL_FIELD[class_name]: to_level,
        "level": level,
        "thac0_base": 60 - min(levels.at_level(n, lv, game).thac0
                               for n, lv in class_levels.items()
                               if levels.at_level(n, lv, game)),
        "hp_rolled": hp_rolled,
        "hp_max": hp_max,
        "experience": _experience(record, class_levels, game),
        "attack_level": class_levels.get("fighter", 0),
    }

    saves = levels.saving_throws(class_levels, race,
                                 record.get("constitution"), game)
    for name, value in zip(SAVE_FIELDS, saves):
        fields[name] = value

    if class_levels.get("fighter", 0) >= 7:
        forms = bytearray(record.get_raw("attack_forms"))
        if forms and forms[0] < 3:
            forms[0] = 3
            fields["attack_forms"] = bytes(forms)

    if class_levels.get("cleric"):
        turning = levels.turning_level(class_levels["cleric"], game)
        if turning is not None:
            fields["turn_power"] = turning

    if class_levels.get("thief"):
        skills = tables.thief_skill_row(class_levels["thief"], race)
        for name, value in zip(THIEF_FIELDS, skills):
            fields[name] = value

    fields["spells_castable"] = bytes(
        _spells_castable(record, class_levels, game))

    known = set(spells.spells_known(bytes(record)))
    learned = None
    if class_levels.get("cleric"):
        known |= set(_cleric_spell_ids(class_levels["cleric"], game))
    if class_name == "magic-user":
        offered = learnable(record, game, level=to_level)
        if offered:
            if learn is None:
                raise CannotLevel(
                    "a magic-user picks one new spell at the trainer and "
                    "nothing derives which; pass learn=<spell id>")
            if learn not in offered:
                raise CannotLevel(f"spell {learn} is not one the trainer "
                                  f"would offer")
            known.add(learn)
            learned = learn
        else:
            notes.append("no magic-user spell was left to learn")
    spellbook = spells.spellbook_bytes(sorted(known))
    if spellbook == record.get_raw("spells_known"):
        spellbook = None

    before = record.get("experience") or 0
    after = fields["experience"]
    disqualified = []
    for name in ready_classes(record, game):
        if name == class_name:
            continue
        want = levels.next_threshold(name, class_levels[name], game)
        if want is not None and after < want:
            disqualified.append(name)
    disqualified = tuple(disqualified)
    if disqualified:
        notes.append(
            "the trainer's experience clamp takes "
            f"{', '.join(disqualified)} below the next threshold, so the "
            "level it has already earned goes with it")

    return Plan(class_name=class_name, from_level=from_level, to_level=to_level,
                fields=fields, hit_points_rolled=rolled,
                thac0_delta=fields["thac0_base"] - record.get("thac0_base"),
                hp_max=hp_max,
                spellbook=spellbook, learned_spell=learned,
                experience_lost=max(0, before - after),
                classes_disqualified=disqualified, notes=tuple(notes))


def apply_to(record, plan_: Plan):
    """A copy of the record with the plan written into it."""
    from .record import CharacterRecord

    out = CharacterRecord.from_bytes(bytes(record))
    for name, value in plan_.fields.items():
        if isinstance(value, (bytes, bytearray)):
            out.set_raw(name, bytes(value))
        else:
            out.set(name, value)
    if plan_.spellbook is not None:
        out.set_raw("spells_known", plan_.spellbook)
    # `hp_current` at `0x119` is past the 256 bytes a save slot holds, so it
    # exists in a 580-byte export and not in a save. Where it is there, the
    # heal goes in it; live and on disk the roster block's `+0x19` is the only
    # copy and the caller writes that.
    if out.is_stored("hp_current"):
        out.set("hp_current", plan_.hp_max)
    return out
