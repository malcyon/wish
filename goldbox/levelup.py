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

**Curse of the Azure Bonds runs the same eight steps at different addresses
and by eight different rules**, all of them read off its own `GEN` and `ECL65`
(`#18`, `docs/135-levelling.md`). Each is a per-title field on
`goldbox.levels.LevelTables` rather than a branch here:

| rule | Pool of Radiance | Curse | where |
|---|---|---|---|
| the hit die | one roll (`$2037`) | two, keep the higher (`$15FC`) | `hit_die_rolls` |
| a lone fighter's floor | 4 (`CMP #$04`) | none | `hit_die_fighter_floor` |
| a divided roll's floor | 1 (`$20A2`) | none (`$11CC`) | `hit_die_divide_floor` |
| `hp_max` | `hp_rolled + level * bonus` (`$2079`) | per class slot, summed and divided (`$11F1`) | `_hit_point_maximum` |
| the constitution bonus | two banded rows from 15 (`$247B`) | one signed row, no floor (`$11D7`) | `hp_bonus_by_score` |
| thief skills | level and race (`$1FEC`) | level, **dexterity** and race (`$0FAD`) | `thief_skill_dexterity` |
| `attack_forms` | raised to 3, never lowered (`$2342`) | written outright, 2 or 3 (`$1909`) | `attack_forms_overwritten` |
| `spells_castable` | written (`$20BC`) | **never stored** | `stores_spell_capacity` |

**Curse is still refused**, because `levels.TRAINER_MEASURED` has one entry --
but no longer because nothing has been watched. Five Curse level-ups were
driven and diffed on 2026-09-05 and 75 derived fields and 5 spellbooks come
back out of this module and `goldbox.levels` with no mismatches, and a
dual-classed character was trained eight more times the same night
(`docs/192-curse-dual-class.md`). What stands between the measurement and the
key is in that page's last section.

**One field is a die and cannot be anything else.** `hp_rolled` at `0x0ED`
takes a fresh roll of the class's hit die at every training, so this module
rolls one too rather than pretending to derive it. Everything the roll feeds --
`hp_max`, and the roster's current hit points -- follows from it exactly, by
`hp_max = hp_rolled + level * constitution bonus`, which is `$2079`.

**A multi-class character's roll is divided between the classes, and the two
titles round up on different comparisons.** `$208D` and `$11AB` both roll
`1..class_count` out of the same resident routine and compare it with the
remainder; Pool of Radiance increments on `<=` and Curse on `<`. So Pool of
Radiance rounds up with chance `remainder / class_count` and **Curse with
`(remainder - 1) / class_count`, which is never for a two-class character**.
`divide_between_classes` still implements Pool of Radiance's rule for both
titles, and what that needs is written up there.

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
#: tables is indexed in. Paladin and ranger are here because Curse has both and
#: `classes_of` names them for a title whose `class_order` does (#18).
CLASS_LEVEL_FIELD = {"magic-user": "level_magic_user", "cleric": "level_cleric",
                     "thief": "level_thief", "fighter": "level_fighter",
                     "paladin": "level_paladin", "ranger": "level_ranger"}

#: The five saving throws, in stored order at `0x09A`.
SAVE_FIELDS = ("save_paralysis", "save_petrification", "save_wands",
               "save_breath", "save_spell")

#: The eight thief skills, in stored order at `0x0A5`.
THIEF_FIELDS = ("thief_pick_pockets", "thief_open_locks", "thief_find_traps",
                "thief_move_silently", "thief_hide_in_shadows",
                "thief_hear_noise", "thief_climb_walls",
                "thief_read_languages")

#: The cleric's bit in the mask at `0x0EB`, for asking `goldbox.spells.capacity`
#: about a cleric without a record in hand.
CLASS_CLERIC = {n: b for b, n in CLASS_BITS_CLASSIC}["cleric"]


class CannotLevel(Exception):
    """The character cannot take this level, and why."""


@dataclass(frozen=True)
class Plan:
    """Every field a level-up writes, and what it would write there.

    `fields` is record field name to value; `spellbook` is the mask at `0x078`
    when it changes, and None when it does not -- as many bytes of it as the
    title uses, so seven on Pool of Radiance and thirteen on Curse. Nothing
    here has touched a machine: a caller turns it into writes, and a test
    compares it with what the trainer produced for the same character.
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


def _tables_for(game):
    """The title's *own* level tables, or a refusal naming the title.

    `levels.for_game` falls back to Pool of Radiance for a title it has no
    tables for. That is right for reading a spell name and wrong for writing a
    character record: every number `plan` writes -- thresholds, THAC0, saving
    throws, the hit die, thief skills, spell slots -- would be another game's,
    and nothing on the way out would say so.

    Refusing is the visible half of the same rule `goldbox.spells.capacity`
    follows by returning nothing: an unread table shows as unread.

    UNAPPROVED WORDING: the refusal below is a new string and Donald has not
    seen it. It reaches a user as the level-up button's reason for saying no.
    """
    tables = levels.for_game(game)
    key = getattr(game, "key", game)
    if game is not None and not isinstance(game, levels.LevelTables) \
            and key != tables.key:
        raise CannotLevel(f"{key} has no level tables of its own; only "
                          f"{', '.join(t.title for t in levels.TITLES)} "
                          f"have been read")
    if not levels.trainer_measured(tables):
        raise CannotLevel(f"{tables.title}'s trainer tables have not been read")
    return tables


def classes_of(record, game=None) -> list[str]:
    """The character's classes, in class-bit order.

    **Which bits exist is the title's**, and `LevelTables.class_order` is that
    list: index `n` is bit `n` of `0x0EB` and slot `n` of the per-class level
    array at `0x0C9`, with None for a bit the title has no class for. Pool of
    Radiance's four are the first four, which is `CLASS_BITS_CLASSIC` exactly;
    Curse adds the paladin at `0x40` and the ranger at `0x80`, and without them
    `plan` told a Curse paladin it was not one (#18).

    A title `goldbox.levels` has no tables for falls back to Pool of Radiance's
    order, which would miss a Krynn knight at `0x10`. Nothing reaches that:
    `_tables_for` refuses such a title before `plan` asks.
    """
    bits = record.get("class_bits") or 0
    order = levels.for_game(game).class_order
    return [name for index, name in enumerate(order)
            if name and bits & (1 << index)]


def class_level(record, class_name: str) -> int:
    """The stored level for one class, falling back to the single level byte."""
    return (record.get(CLASS_LEVEL_FIELD[class_name])
            or record.get("level") or 1)


def dual_class_old(record, game=None) -> tuple[str | None, int]:
    """The class a character trained out of, and the level it stopped at.

    `0x0BA` holds that level and **a zero means "has not dual-classed"** --
    `GEN $18EB LDY #$FF / LDA $7CBA / BEQ / LDY $7CB9`, which is what stops
    slot 0, the magic-user, being ambiguous. `0x0B9` holds the slot, so the
    name comes from the title's own `class_order` (#224).

    Curse, Silver Blades and Gateway to the Savage Frontier write the pair;
    Pool of Radiance, Champions of Krynn and Death Knights of Krynn never
    reference either byte on any of their disks, and 13 of 13 Pool of Radiance
    records in `tests/fixtures/` hold zero there. So this answers `(None, 0)`
    for a title that has no such rule without needing to know which titles
    those are.
    """
    if not record.is_stored("dual_class_level"):
        return None, 0
    old_level = record.get("dual_class_level") or 0
    if not old_level:
        return None, 0
    slot = record.get("dual_class_slot") or 0
    order = levels.for_game(game).class_order
    return (order[slot] if slot < len(order) else None), old_level


def ready_classes(record, game=None) -> list[str]:
    """Which of the character's classes have the experience for another level.

    **The class a dual-classed character left is never ready**, `GEN $1321`,
    and that holds *after* `$20A3` has put its level back in the array.
    Watched: PHILIPPE, magic-user 6 turned fighter, was refused with
    `UNABLE TO ADVANCE` holding 150,000 experience and a restored magic-user 6
    -- 15,000 more than the magic-user's ninth level asks for (#18).

    **Experience is not divided between classes.** The trainer reads the whole
    stored number against the single-class table -- LADY KATHERINE, magic-user
    1 / thief 7 with 70,100 points, was offered thief 8, whose single-class
    threshold is 70,001 (`docs/119-test-party.md`). So each class is measured
    against the same number.

    **`>=`, against the game's own number, which is the published one plus 1.**
    `GEN $1BBC` walks the class's threshold column downwards and takes the
    first row it is not below (`SBC` then `BCS`), and the rows themselves hold
    2501 for magic-user 2 where AD&D prints 2500 -- so 2500 exactly is refused
    and 2501 is offered. `goldbox/levels.py` stores the game's numbers, which is
    why the comparison here is a plain `>=`.
    """
    experience = record.get("experience") or 0
    left_behind, _ = dual_class_old(record, game)
    out = []
    for name in classes_of(record, game):
        if name == left_behind:
            continue
        want = levels.next_threshold(name, class_level(record, name), game)
        if want is not None and experience >= want:
            out.append(name)
    return out


#: Class-bit order, as a plain list, for the tie-break in `best_next_class`.
#: Pool of Radiance's four; a title with more of them overrides it from its own
#: `LevelTables.class_order`, which is the same list with the gaps in.
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

    Ties break in class-bit order -- magic-user, cleric, thief, fighter, and
    then Curse's paladin and ranger -- which is the order `0x0C9` stores and
    the order every one of the game's own tables is indexed in. Repeated calls
    then walk down the order themselves, because each level raises the class it
    just picked.
    """
    order_of = [name for name in levels.for_game(game).class_order if name] \
        or _CLASS_ORDER

    def rank(name: str):
        # None where the title's tables have no entry past the ceiling; sorts
        # last rather than raising, since something has to be picked.
        after = levels.clamp_threshold(name, class_levels[name] + 1, game)
        order = (order_of.index(name) if name in order_of else len(order_of))
        return (after or 0, -order)

    ready = [name for name in ready if name in class_levels]
    return max(ready, key=rank) if ready else None


def best_class(record, game=None) -> str | None:
    """The class `plan` would raise if it were not told which. None if none is
    ready."""
    return best_next_class(
        ready_classes(record, game),
        {name: class_level(record, name) for name in classes_of(record, game)},
        game)


def divide_between_classes(value: int, class_count: int, rng=None,
                           game=None) -> int:
    """Split hit points between a multi-class character's classes.

    `GEN $208D` in Pool of Radiance and `$11AB` in Curse, and they are the same
    routine twice: divide, then **round up at random against the remainder**.
    Pool of Radiance increments when the roll is at or below the remainder
    (`CMP $6E3F / BEQ inc / BCS out`) and Curse when it is below it
    (`CMP $7F3F / BCS out`).

    **Both rolls run `1..class_count`, which is now read rather than guessed.**
    The random routine is in `LIBRARY`, not in `GEN`: `LIBRARY $2F46` in Curse
    and `$2DBC` in Pool of Radiance, the same code twice, masking a random byte
    to the bit width of `Y` and retrying while it exceeds `Y`, so it returns
    `0..Y`. Two entry points sit above it one byte apart, `DEY` then the call,
    and both titles reach the lower one. Curse's `LIBRARY` runs at `$2DC8`,
    which is exact: `$2DC8` plus its 7480 bytes is `$4B00`, where `SAVEAZURE`
    loads. Aligning Pool of Radiance's copy against it puts its `LIBRARY` at
    `$2C48`, which lands **four bytes below** the `$4900` its own saved game
    loads at -- close enough to corroborate the technique and not an
    independent check of the base, since a four-byte error in the alignment
    would look exactly like this.

    **So the two titles differ only in the comparison, and Curse's is not
    random for a two-class character.** Pool of Radiance rounds up with chance
    `remainder / class_count`; Curse's `BCS` with no `BEQ` in front of it makes
    that `(remainder - 1) / class_count`, which is **zero** whenever the
    remainder is 1 -- and a two-class character's remainder is only ever 0 or
    1. CONFIRMED from the bytecode and from 40 engine-written divides on
    2026-09-05: 14 of 14 round-downs at two classes, 12 of 12 at three with
    remainder 1, and 5 round-ups in 14 at three with remainder 2, against the
    1 in 3 this rule predicts and the 2 in 3 the code below gives.

    **This function still implements Pool of Radiance's rule for both
    titles.** Curse needs `LevelTables` to carry the comparison beside
    `hit_die_divide_floor` -- Pool of Radiance rounds up when the roll is at or
    below the remainder, Curse only when it is below -- and `goldbox/levels.py`
    was another agent's file the night this was measured. Nothing reaches the
    error today, because `_tables_for` refuses Curse outright
    (`docs/192-curse-dual-class.md`).

    Pool of Radiance then floors the result at 1 (`$20A2 BNE / LDA #$01`) and
    Curse does not (`$11CC` is a bare `LDA $4C / RTS`), so a Curse character
    with three classes can come out of a training with nothing.
    """
    tables = levels.for_game(game)
    if class_count <= 1:
        return value
    quotient, remainder = divmod(value, class_count)
    if remainder and (rng or random).randrange(class_count) < remainder:
        quotient += 1
    return max(quotient, tables.hit_die_divide_floor)


def roll_hit_points(class_name: str, class_count: int = 1,
                    fighter_only: bool = False, rng=None, game=None,
                    level: int | None = None) -> int:
    """One hit die, the way the title's trainer rolls it.

    The die is the class's own -- `GEN $20A7` in Pool of Radiance, `$161E` in
    Curse -- and the roll is then split between the character's classes by
    `divide_between_classes`. Three things are the title's:

    * **how many dice.** Pool of Radiance rolls one (`$2037`); Curse rolls two
      and keeps the higher (`$15FC`), which is `hit_die_rolls`. PROBABLE, from
      the bytecode alone: a roll leaves no trace of itself in a record.
    * **the single-class fighter's floor of 4.** Pool of Radiance's `CMP #$04`
      against `class_bits == 8` and nothing else, which is why no fighter in
      twenty-nine trainings gained fewer than four hit points. Curse has no
      floor of any kind -- `$15E1` carries no `CMP #$04` in its 61 bytes.
    * **when the dice stop.** Past `roll_to` a class adds a flat number a
      level instead of rolling (`$15F2 CMP $1626,X / BCC roll`), and the flat
      number goes through the same divide. `level` is the level being trained
      *to*; without it this always rolls, which is right for Pool of Radiance,
      where no class reaches its own `roll_to`.
    """
    tables = levels.for_game(game)
    flat = tables.flat_hit_points(class_name, level) if level else None
    if flat is None:
        die = levels.hit_die(class_name, game)
        if not die:
            raise CannotLevel(f"no hit die is known for {class_name}")
        source = rng or random
        rolled = max(source.randint(1, die)
                     for _ in range(max(1, tables.hit_die_rolls)))
    else:
        rolled = flat
    rolled = divide_between_classes(rolled, class_count, rng, game)
    floor = tables.hit_die_fighter_floor
    if fighter_only and floor is not None and rolled < floor:
        rolled = floor
    return rolled


def learnable(record, game=None, level: int | None = None) -> list[int]:
    """The magic-user spells the trainer would offer, in the order it offers.

    **The trainer does not roll and it does not grant.** `GEN $215A` walks the
    spellbook bitmask, keeps every id the character does not already know whose
    spell level is at or below `(level + 1) // 2`, drops every cleric spell,
    and puts the survivors on a menu. The player picks one and the level-up
    does not finish until they do -- which is why a magic-user needs a dialog
    and a cleric does not.

    **How far the walk goes is the title's**, `SpellTable.last_spellbook_spell`
    -- 55, 100 or 117. Pool of Radiance's 55 was the module constant here, so a
    Curse magic-user reaching 7 was offered no fourth-level spell at all: ids
    81-90 are past the end of a list nobody told this function had grown
    (issue #87).

    **`level` is the level being trained *to*.** `GEN $1FDE` writes the new
    per-class levels before the menu is built, so a magic-user reaching 3 is
    offered second-level spells at that same training. Defaults to what the
    record already holds, for a caller asking what is on offer now.

    **Not every title builds a menu at all.** Silver Blades' `0x0C9` routine
    ORs a whole row into the mask instead of listing choices -- see
    `_magic_user_grant_row`, which `plan` calls for the actual write -- so its
    trainer offers nothing to pick and this returns empty rather than Pool of
    Radiance's rule applied to the wrong list (#89). Curse is left alone: its
    `GEN` carries no grant loop for `0x0C9` at all, so whether it menus or
    grants is UNKNOWN, and this keeps treating it as a menu rather than guess.
    """
    if level is None:
        level = class_level(record, "magic-user")
    if spells.for_game(game).magic_user_grant:
        return []
    castable = (level + 1) // 2
    table = spells.for_game(game)
    known = set(spells.spells_known(bytes(record), game))
    out = []
    for spell_id in range(1, table.last_spellbook_spell + 1):
        if spell_id in known or spell_id in table.not_granted:
            continue
        group = spells.spell_group(spell_id, game)
        if group is None:
            continue
        who, spell_level = group
        if who != "magic-user" or spell_level > castable:
            continue
        out.append(spell_id)
    return out


def _castable_levels(cleric_level: int, game=None) -> int:
    """How many spell levels a cleric of that level may cast, per title.

    The title's own slot table, read through `goldbox.spells.capacity`, and not a
    ladder: Pool of Radiance's `GEN $222C` gives a new level at cleric 1, 3 and
    5, Curse's `ECL65` continues to 7 and 9, and both fall straight out of
    counting the leading non-zero columns of the cleric row.

    **Zero where the title's tables have not been read**, which is Silver
    Blades and everything after it. `capacity` returns nothing there rather
    than another game's numbers, and so does this.
    """
    row = spells.capacity(CLASS_CLERIC, cleric_level, 0, game).get("cleric")
    castable = 0
    for slots in row or ():
        if not slots:
            break
        castable += 1
    return castable


def _cleric_spell_ids(cleric_level: int, game=None) -> list[int]:
    """Every cleric spell a cleric of that level is granted.

    `GEN $20CF` ORs whole spell levels in, so on Pool of Radiance this is
    exactly "every cleric spell of a level it can cast" and does not hard-code
    a bitmask. Curse replaced that routine with a per-level table and left two
    of its own cleric spells out of it -- 36 ANIMATE DEAD and 100 BESTOW CURSE
    -- so those are skipped here as well; with them the set is Curse's grant
    table id for id at every level it reaches. `SpellTable.not_granted` also
    carries the magic-user ANIMATE DEAD, id 90, which never reaches this
    function because it is not a cleric spell (#223).
    """
    table = spells.for_game(game)
    castable = _castable_levels(cleric_level, game)
    out = []
    for spell_id in range(1, table.last_spellbook_spell + 1):
        if spell_id in table.not_granted:
            continue
        group = spells.spell_group(spell_id, game)
        if group and group[0] == "cleric" and group[1] <= castable:
            out.append(spell_id)
    return out


def _row_at(table: tuple[tuple[int, tuple[int, ...]], ...],
           level: int, floor: int) -> tuple[int, ...] | None:
    """The row for the highest key at or below `level`, or None below `floor`.

    A grant table only records the levels where the row actually changes, so
    a level between two entries gets the lower one -- the trainer's own
    routine does the same by indexing a monotonic array rather than one row
    per level.
    """
    if level < floor:
        return None
    rows = dict(table)
    idx = max(k for k in rows if k <= level)
    return rows[idx]


def _magic_user_grant_row(level: int, game=None) -> tuple[int, ...] | None:
    """The whole spell list Silver Blades' `0x0C9` routine ORs in at `level`,
    or None for a title with no grant table of its own -- see
    `SpellTable.magic_user_grant`.

    `GEN` floors its own index at 5 and caps it at 9, so a level outside that
    still reads the nearest end of it (#89).
    """
    table = spells.for_game(game).magic_user_grant
    if not table:
        return None
    return _row_at(table, min(max(level, 5), 9), floor=5)


def _ranger_spell_ids(level: int, game=None) -> list[int]:
    """Every spell a ranger of `level` is granted by Silver Blades' `0x0D0`
    routine. Empty for a title with no ranger grant table, and below the
    level the gate `CPX #$08` first lets the routine run (#89)."""
    table = spells.for_game(game).ranger_grant
    if not table:
        return []
    row = _row_at(table, min(level, max(k for k, _ in table)), floor=table[0][0])
    return sorted(row or ())


def _spells_castable(record, class_levels: dict[str, int],
                     game=None) -> list[int]:
    """The whole `spells_castable` field, as `GEN $20BC` writes it.

    **Zeroed first, unconditionally** -- the routine clears the block before it
    looks at a class, so a fighter's bytes are cleared too. Then the cleric's
    row into the high nibble, with the wisdom bonus added only where the class
    table already gives a slot; then the magic-user's row into the low nibble.

    **As many spell levels as the class row has**, which is the title's: Pool
    of Radiance's rows stop at three -- `GEN $20BC` clears nine bytes, so the
    field was always wider than that game can fill -- and Curse's reach five.
    The field at `0x0EE` is six bytes, so both fit.
    """
    width = len(record.get_raw("spells_castable"))
    out = [0] * width
    cleric = class_levels.get("cleric", 0)
    if cleric:
        row = levels.at_level("cleric", cleric, game)
        slots = list(row.spells) if row else []
        bonus = levels.wisdom_bonus_spells(record.get("wisdom"), game)
        for i in range(width):
            have = slots[i] if i < len(slots) else 0
            if have and i < len(bonus):
                have += bonus[i]
            out[i] = (have & 0x0F) << 4
    magic_user = class_levels.get("magic-user", 0)
    if magic_user:
        row = levels.at_level("magic-user", magic_user, game)
        slots = list(row.spells) if row else []
        for i in range(width):
            out[i] += (slots[i] if i < len(slots) else 0) & 0x0F
    return out[:width]


def _hit_point_maximum(record, class_levels: dict[str, int], hp_rolled: int,
                       game=None, rng=None) -> int:
    """`hp_max` at `0x076`, the way the title's recompute builds it.

    **Pool of Radiance's is one line** -- `GEN $2079`, `hp_rolled + level *
    bonus`, with the constitution row picked by the fighter bit.

    **Curse's is a loop over the eight class slots** (`$11F1`), and it
    disagrees with Pool of Radiance's on three of the six characters SSI
    shipped: 5 low on the paladin, 8 low on the ranger, 1 high on the
    fighter/thief. Per slot it takes `min(level, roll_to)` -- the dice count,
    so **the constitution bonus stops when the dice stop** (`$1204 SBC
    $1282,Y`) -- times that slot's constitution bonus, which is the capped one
    for slots 0 to 2. It adds one whole extra bonus for a ranger (`$128A`,
    because a ranger is 2d8 at level 1), divides by the class count, adds
    `hp_rolled`, and finally floors the answer at the character's `level` and
    throws away anything reaching 200 (`$123C`/`$1241`).

    **The arithmetic is eight-bit and the constitution row is signed**, which
    is why the total is masked here rather than left as a Python integer: a
    character with a constitution of 6 or less has a negative total, `$1230
    BMI` skips the divide for it, and the addition wraps.

    **Three branches nothing has ever taken.** No character SSI shipped has a
    constitution below 14, so the negative total is unexercised; all six are
    level 5 against a `roll_to` of 9 or more, so the dice cap is; and nothing
    can approach 200 at level 5. The dual-class terms are unexercised too, and
    for a stronger reason: there is no dual-classed Curse character anywhere on
    these disks, which is why `plan` refuses one rather than writing this.
    """
    tables = levels.for_game(game)
    level = max(class_levels.values(), default=1)
    if not tables.hp_bonus_by_score:
        bits = record.get("class_bits") or 0
        return hp_rolled + level * tables.constitution_hp_bonus(
            record.get("constitution"), fighter=bool(bits & 8))

    constitution = record.get("constitution")
    old_level = record.get("dual_class_level") or 0
    old_slot = record.get("dual_class_slot") or 0
    order = tables.class_order
    total = 0
    if old_level:
        # `$124F`: the class the character left keeps its own term, once.
        name = order[old_slot] if old_slot < len(order) else None
        if name:
            dice = tables.hit_dice_rolled(name, tables.ceiling(name)) or 0
            total += min(old_level, dice) * tables.constitution_hp_bonus(
                constitution, class_slot=old_slot)
    counted = 0
    for slot, name in enumerate(order):
        if not name or not class_levels.get(name):
            continue
        if not (old_level and slot == old_slot):
            counted += 1        # `$18E4` leaves the old class out of the count
        dice = tables.hit_dice_rolled(name, class_levels[name]) or 0
        total += max(0, dice - old_level) * tables.constitution_hp_bonus(
            constitution, class_slot=slot)
    if class_levels.get("ranger") or (old_level and old_slot < len(order)
                                      and order[old_slot] == "ranger"):
        total += tables.constitution_hp_bonus(
            constitution, class_slot=order.index("ranger"))

    total &= 0xFF
    if total < 0x80 and counted:
        total = divide_between_classes(total, counted, rng, game)
    points = (hp_rolled + total) & 0xFF
    return points if level <= points < 200 else level


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

    **The class a dual-classed character left is out of the maximum**,
    `GEN $1470`, and leaving it out makes the clamp *tighter* rather than
    looser. Watched with a staged input on 2026-09-05: a character carrying a
    magic-user 10 as its old class and a fighter 1 as its new one was trained
    once with 400,000 experience and came out with **4,000**, which is the
    fighter's `clamp_threshold(2) - 1`. Had the old class counted it would
    have been the magic-user's 375,000 (#18).
    """
    experience = record.get("experience") or 0
    left_behind, _ = dual_class_old(record, game)
    ceiling = None
    for name, level in class_levels.items():
        if name == left_behind:
            continue        # `$1470` leaves the old class out of the maximum
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
    tables = _tables_for(game)
    if not class_name:
        # Nothing ready falls through to the threshold check below, which says
        # which class and what it is short of -- a better answer than "no".
        class_name = (best_class(record, game)
                      or (classes_of(record, game) or [""])[0])
    if class_name not in classes_of(record, game):
        raise CannotLevel(f"{record.name} is not a {class_name}")
    # `0x0BA` non-zero is the "has dual-classed" sentinel (`GEN $18EB`), and
    # four routines change behaviour for it: `$15E7` refuses the die until the
    # new class passes the old level, `$124F` gives the old class its own
    # hit-point term, `$1470` and `$1321` leave its slot out of the clamp and
    # out of eligibility, and `$20A3` puts it back afterwards. All four were
    # watched happening on 2026-09-05, over eight trainings of one character
    # (#18); until then this refused rather than write a rule nothing had
    # checked.
    left_behind, old_level = dual_class_old(record, game)
    if class_name == left_behind:
        # UNAPPROVED WORDING: a new string Donald has not seen, reaching a user
        # as the level-up button's reason for saying no.
        raise CannotLevel(f"{record.name} trained out of being a {class_name} "
                          f"and the trainer will not take it up again")

    class_levels = {name: class_level(record, name)
                    for name in classes_of(record, game)}
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
        if old_level and old_level >= to_level:
            # `GEN $15E7 LDA $7CBA / CMP $7CC9,X / BCS out`: a dual-classed
            # character rolls **no hit die at all** until the new class passes
            # the level the old one stopped at. Watched over five levels --
            # PHILIPPE, magic-user 6 turned fighter, held 21 `hp_rolled` from
            # fighter 2 to fighter 6 and gained at fighter 7 (#18).
            rolled = 0
        else:
            rolled = roll_hit_points(
                class_name, class_count=len(class_levels),
                fighter_only=(bits == 8), rng=rng, game=game, level=to_level)

    # `GEN $20A3`, the last step of the sequence and after the die: once the
    # new class is *above* the old one's level, the old class's entry goes back
    # into the array at `0x0C9` and its bit back into the mask at `0x0EB`, and
    # everything below is then computed with it in. Watched at the same
    # training that first rolled a die, and at no earlier one.
    restored = None
    if left_behind and old_level and old_level < level:
        class_levels[left_behind] = old_level
        bits |= 1 << list(tables.class_order).index(left_behind)
        level = max(class_levels.values())
        restored = left_behind

    hp_rolled = (record.get("hp_rolled") or 0) + rolled
    hp_max = _hit_point_maximum(record, class_levels, hp_rolled, game, rng)

    fields: dict[str, object] = {
        CLASS_LEVEL_FIELD[class_name]: to_level,
        "level": level,
        "thac0_base": 60 - min(levels.at_level(n, lv, game).thac0
                               for n, lv in class_levels.items()
                               if levels.at_level(n, lv, game)),
        "hp_rolled": hp_rolled,
        "hp_max": hp_max,
        "experience": _experience(record, class_levels, game),
        # `GEN $2342` writes the fighter's level; Curse's `$0DF1` writes the
        # best of fighter, paladin and ranger, and that byte is what feeds the
        # fighter group's THAC0 and its saving-throw column.
        "attack_level": max((class_levels.get(name, 0)
                             for name in ("fighter", "paladin", "ranger")),
                            default=0),
    }

    if restored:
        fields["class_bits"] = bits
        fields[CLASS_LEVEL_FIELD[restored]] = old_level

    saves = levels.saving_throws(class_levels, race,
                                 record.get("constitution"), game)
    for name, value in zip(SAVE_FIELDS, saves):
        fields[name] = value

    # `attack_forms` at `0x0D9` holds attacks a round doubled, so 2 or 3.
    # **Pool of Radiance only ever raises it to 3** -- `$2342 LDX #$03 / CPX
    # $6BD9 / BCC skip`, and only for a fighter at 7. **Curse writes what it
    # computed**, `$1909 STY $7CD9`, comparing every class slot's level with
    # the row at `$191E`: fighter 7, paladin 7, **ranger 8**.
    want = int(round(max((levels.at_level(n, lv, game).attacks
                          for n, lv in class_levels.items()
                          if levels.at_level(n, lv, game)), default=1) * 2))
    forms = bytearray(record.get_raw("attack_forms"))
    if forms:
        if tables.attack_forms_overwritten:
            new_forms = want
        elif want >= 3:
            new_forms = max(forms[0], want)
        else:
            new_forms = forms[0]
        if new_forms != forms[0]:
            forms[0] = new_forms
            fields["attack_forms"] = bytes(forms)

    turning = levels.turning_level(class_levels.get("cleric", 0), game,
                                   class_levels.get("paladin", 0))
    if turning is not None:
        fields["turn_power"] = turning

    if class_levels.get("thief"):
        skills = tables.thief_skill_row(class_levels["thief"], race,
                                        record.get("dexterity") or 0)
        if skills is None:
            raise CannotLevel(f"{tables.title}'s thief skills need a "
                              f"dexterity and {record.name} has none")
        for name, value in zip(THIEF_FIELDS, skills):
            fields[name] = value

    # **Curse never stores spell capacity**: nothing in `GEN`, `ECL64` or
    # `ECL65` writes `0x0EE`-`0x0F3`, `ECL65 $880D` rebuilds the number in
    # fifteen bytes of workspace whenever the sheet is drawn, and all six
    # shipped characters hold zero there. Writing it would be the only field
    # in this plan the game itself leaves alone.
    if tables.stores_spell_capacity:
        fields["spells_castable"] = bytes(
            _spells_castable(record, class_levels, game))

    known = set(spells.spells_known(bytes(record), game))
    learned = None
    if class_levels.get("cleric"):
        known |= set(_cleric_spell_ids(class_levels["cleric"], game))
    if class_levels.get("ranger"):
        known |= set(_ranger_spell_ids(class_levels["ranger"], game))
    if class_name == "magic-user":
        grant = _magic_user_grant_row(to_level, game)
        if grant is not None:
            known |= set(grant)      # a row, not a choice -- nothing to ask
        else:
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
    # As wide as the title's mask: seven bytes on Pool of Radiance, thirteen on
    # Curse. Compared against the same span of the record, so a level-up that
    # changes nothing above id 55 still reports no change.
    spellbook = spells.spellbook_bytes(sorted(known), game)
    if spellbook == spells.spellbook_raw(record)[:len(spellbook)]:
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
        # Across both fields the mask is declared as, because Curse's thirteen
        # bytes and Silver Blades' sixteen run past `spells_known`'s seven.
        spells.set_spellbook_raw(out, plan_.spellbook)
    # `hp_current` at `0x119` is past the 256 bytes a save slot holds, so it
    # exists in a 580-byte export and not in a save. Where it is there, the
    # heal goes in it; live and on disk the roster block's `+0x19` is the only
    # copy and the caller writes that.
    if out.is_stored("hp_current"):
        out.set("hp_current", plan_.hp_max)
    return out
