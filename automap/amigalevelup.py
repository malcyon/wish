"""Level up on an Amiga title: that title's own trainer, copied from its executable.

The Amiga trainers are not the C64 ones (`docs/124-amiga-port.md` §1.23), so
`goldbox/levelup.py` does not describe them. Each title here is a copy of the
trainer and the record recompute it calls, run on a copy of the live heap
record, and a level-up is the bytes that copy changed: `plan` returns them as
`(record offset, bytes)` writes for `automap/amigaactions.py`'s writer.

Nothing here charges money, and nothing heals: no Amiga trainer heals, and the
C64 Level up never touches money (`goldbox/levelup.py`). A press raises what
the title's trainer raises in one YES: every ready class in Pools of Darkness
and Silver Blades, the trainer's own one class in Curse, and in Pool of
Radiance, whose halls train one class each, the class the C64 Level up would
pick (`levelup.best_next_class`).

What a caller must supply because a record cannot: the spell a magic-user
learns (`offers` lists the trainer's own menu), the dice (`rng`), and the item
and effect nodes the recompute and the trainer read (`plan_member` takes both
from the live party member). Where the copy would need something no caller can
supply, `plan` raises `CannotLevel` and writes nothing: a druid or monk level,
which no player was found to hold.

The effect node the Silver Blades and Pools of Darkness trainers add for a
regained ranger or paladin is not a record write: `Plan.added_effects` names
it, and `write_plan` makes it in the game's own effect pool with
`automap/amigaeffects.py` before it writes the record.

**A Curse or Silver Blades thief does not get the trainer's thief skills.**
Those two trainers mis-compute them (`docs/124` §1.23), so the level, race and
dexterity rows are summed by `levels.ad_d_thief_skills`, which clamps each
column at 0 as the DOS port does; the C64 stores the negative sum as its
wrapped byte.

Each section names its executable, the routines it copies and where
`docs/124` §1.23 records their reading; addresses are file offsets into that executable and
`gNNNN` its data-hunk offsets, record offsets the heap record's.
"""

from __future__ import annotations

import functools
import random
from dataclasses import dataclass

from goldbox import amiga_pod, levels, spells
from goldbox.amiga_pod_recompute import (
    _POD_CAPACITY,
    _POD_CLASS_BITS,
    _POD_CONSTITUTION,
    _POD_FORMER,
    _POD_FORMER_LEVEL,
    _POD_INTELLIGENCE,
    _POD_LAST_SPELL,
    _POD_LEVEL,
    _POD_LEVELS,
    _POD_RACE,
    _POD_RANGER,
    _POD_SPELLBOOK,
    _POD_SPELLS,
    POD_SLOTS,
    RecomputeError,
    _pod_learn,
    _row,
    _s8,
    pod_check,
    pod_recompute,
    pod_regained,
    readied_power,
)

from . import amigaeffects, amigaparty


class CannotLevel(RecomputeError):
    """The trainer would not train this character, or would do something
    a write to the record cannot copy. The message says which."""


_row = functools.partial(_row, error=CannotLevel)


class NeedsSpell(CannotLevel):
    """The trainer's menu asks for a spell and none was given: `offers` is
    the menu, in id order."""

    def __init__(self, offers: list[int]):
        super().__init__("the trainer makes a magic-user pick a new spell")
        self.offers = list(offers)


@dataclass(frozen=True)
class Plan:
    """One press of Level up: what the trainer's YES leaves in the record."""

    key: str
    #: The class slots raised, by name, in slot order.
    classes: tuple[str, ...]
    #: Experience after the trainer's clamp.
    experience: int
    #: `(record offset, bytes)`, one run of changed bytes each.
    writes: tuple[tuple[int, bytes], ...]
    #: The spell the magic-user learned, if the trainer asked.
    learned: int | None = None
    #: The effect nodes the trainer appends to the character's effect list,
    #: in its order, as `amigaeffects.NewEffect`.
    added_effects: tuple[amigaeffects.NewEffect, ...] = ()


def writes_between(before: bytes, after: bytes) -> tuple[tuple[int, bytes], ...]:
    """Every run of bytes that differs, as `(offset, new bytes)`."""
    out = []
    at = None
    for i, (a, b) in enumerate(zip(before, after)):
        if a != b:
            if at is None:
                at = i
        elif at is not None:
            out.append((at, bytes(after[at:i])))
            at = None
    if at is not None:
        out.append((at, bytes(after[at:len(after)])))
    return tuple(out)


def _effect_ids(effects) -> set[int]:
    """The id of each effect: an int is the id, a node's bytes hold it at +0,
    which is the byte every Amiga trainer's find-effect routine compares."""
    return {e if isinstance(e, int) else e[0] for e in effects or () if
            isinstance(e, int) or len(e)}


#: What `plan` says for a class level this module does not copy: a druid or
#: monk level (and in Pool of Radiance a paladin or ranger), which none of the
#: records on the player's disks holds and no route a player was found to
#: take gives (`docs/124` §1.23).
_NOT_COPIED = ("a {} level is not copied: no player character was found "
               "to hold one")


def _regained_effects(rec, pairs, effects, signed: bool
                      ) -> tuple[amigaeffects.NewEffect, ...]:
    """The nodes the Silver Blades and Pools of Darkness trainers add once
    the class is regained: for each `(former level offset, id)` whose former
    level is above 0 (compared signed or unsigned, as the title's trainer
    does) and whose id the character's list lacks, the constructor's
    `(record, id, 0, 0xFF, 0)`, in that order."""
    have = _effect_ids(effects)
    return tuple(amigaeffects.NewEffect(effect) for at, effect in pairs
                 if (_s8(rec[at]) if signed else rec[at]) > 0
                 and effect not in have)


def apply_to(raw: bytes, plan_: Plan) -> bytes:
    """The record with the plan's writes made."""
    out = bytearray(raw)
    for offset, data in plan_.writes:
        out[offset:offset + len(data)] = data
    return bytes(out)


def _s32(raw, at: int) -> int:
    return int.from_bytes(raw[at:at + 4], "big", signed=True)


def _dice(rng, count: int, sides: int) -> int:
    return sum(rng.randint(1, sides) for _ in range(count))


# --- Pools of Darkness -------------------------------------------------------
#
# The trainer `0x3D106` of `/Pools of Darkness` (sha256 `a572e95a7bc0`), its
# recompute `0x3C238` and hit points `0x24334`, recorded in `docs/124`
# §1.23. Record offsets are the `.pc` file's
# (`goldbox/amiga_pod.py`). The recompute's two item steps are copied from
# the code: the item-gated constitution step on the first saving throw
# (`_pod_saves`) and the doubling of magic-user level 5 capacity by a readied
# item of power `0x41` (`_pod_capacity`). No item in the 86 saved records on
# the player's disk 3 takes either, so neither has been seen in a running
# game. The ring of power `0x81` needs nothing here: its doubling belongs to
# the ready handler, and the recompute rebuilds capacity from zero without it
# (PROBABLE, `99d7ea58`). Unreadying an item whose class mask no longer fits
# (`0x22152`) a level-up cannot cause: training only adds class bits.

POOLS_OF_DARKNESS = "pools-of-darkness"

_POD_MAGIC_USER = 5

_POD_STRENGTH = 0x071                       # the in-force half of each pair
_POD_EXPERIENCE = amiga_pod.EXPERIENCE      # s32, compared signed
_POD_HP_MAX = amiga_pod.HP_MAX
_POD_HP_ROLLED = amiga_pod.HP_ROLLED
_POD_READY = 0x0CB                          # the name's ready colour
_POD_HP_CURRENT = 0x191

#: `g1E81`: the bit a slot answers to in the trainer's ready mask. The cleric
#: and the druid share one.
_POD_READY_BIT = (2, 2, 8, 16, 32, 1, 4)
#: `0x24334`: a class rolls while its new level is below `g1E91`, with
#: `g1E98` dice at level 1 and one after, of `g1E9F` sides; at or past it the
#: running total is replaced by a flat number (`0x24436`; the druid's entry
#: leaves the total alone).
_POD_ROLL_BELOW = (10, 10, 10, 10, 11, 12, 11)
_POD_FIRST_DICE = (1, 2, 1, 1, 2, 1, 1)
_POD_SIDES = (8, 10, 10, 10, 8, 4, 6)
_POD_FLAT = (2, None, 3, 3, 2, 1, 2)
#: `0x3D31A`: no class trains past this.
_POD_LAST_LEVEL = levels.POD_LAST_LEVEL
#: `0x3D090`: the threshold of any level past 40.
_POD_NO_THRESHOLD = 0x7FFFFFFF
#: `g1BA0[race * 7 + slot]`, which the ready flag (`0x1B500`) reads and the
#: trainer does not: a level at or above the entry is never shown ready. The
#: trainer's own hard-coded limits are `_pod_race_blocked`.
_POD_READY_CEILING = (
    (0, 0, 7, 0, 0, 11, 40),        # elf
    (5, 0, 8, 0, 8, 8, 40),         # half-elf
    (0, 0, 9, 0, 0, 0, 40),         # dwarf
    (0, 0, 6, 0, 0, 0, 40),         # gnome
    (0, 0, 6, 0, 0, 0, 40),         # halfling
    (40, 0, 40, 40, 40, 40, 40),    # human
)


def _pod_has_spell(rec, spell: int) -> bool:
    return bool(rec[_POD_SPELLBOOK + (spell - 1) // 8] & (1 << ((spell - 1) % 8)))


def pod_threshold(slot: int, level: int) -> int:
    """`0x3D090`: the experience a slot needs to reach `level`. Past 40 it is
    `0x7FFFFFFF`, and the druid's is -1 throughout."""
    if level >= _POD_LAST_LEVEL + 1:
        return _POD_NO_THRESHOLD
    name = POD_SLOTS[slot]
    if name == "druid":
        return -1
    return levels.POOLS_OF_DARKNESS.at_level(name, level).experience


def _pod_race_blocked(rec, slot: int, level: int) -> bool:
    """The trainer's own race limits (`0x3D184`-`0x3D2FE`), on in-force
    strength and intelligence; each tests the level for equality, so a
    character already past a limit is not stopped by it."""
    race = rec[_POD_RACE]
    strength = rec[_POD_STRENGTH]
    intelligence = rec[_POD_INTELLIGENCE]
    name = POD_SLOTS[slot]

    def banded(score, low, mid, high):
        return (level == high or (level == mid and score == 17)
                or (level == low and score < 17))

    if race == 0:                                       # elf
        if name == "fighter" and banded(strength, 5, 6, 7):
            return True
        if name == "magic-user" and (level == 11
                                     or (level == 9 and intelligence < 17)
                                     or (level == 10 and intelligence == 17)):
            return True
    elif race == 1:                                     # half-elf
        if name == "cleric" and level == 5:
            return True
        if name in ("fighter", "ranger") and banded(strength, 6, 7, 8):
            return True
        if name == "magic-user" and banded(intelligence, 6, 7, 8):
            return True
    elif race == 2:                                     # dwarf
        if name == "fighter" and banded(strength, 7, 8, 9):
            return True
    elif race == 3:                                     # gnome
        if name == "fighter" and (level == 6 or (level == 5 and strength < 18)):
            return True
        if name == "cleric" and level >= 7:
            return True
    elif race == 4:                                     # halfling
        if name == "fighter" and banded(strength, 4, 5, 6):
            return True
    return level >= _POD_LAST_LEVEL


def _pod_ready_blocked(rec, slot: int, level: int) -> bool:
    """The ready flag's limits (`0x1B500`): `g1BA0`, then its own hard-coded
    rules, which differ from the trainer's (no top-of-band test)."""
    race = rec[_POD_RACE]
    if race < len(_POD_READY_CEILING) and _POD_READY_CEILING[race][slot] <= level:
        return True
    strength = rec[_POD_STRENGTH]
    intelligence = rec[_POD_INTELLIGENCE]
    name = POD_SLOTS[slot]

    def banded(score, low, mid):
        return (level == mid and score == 17) or (level == low and score < 17)

    if race == 0:
        return ((name == "fighter" and banded(strength, 5, 6))
                or (name == "magic-user"
                    and ((level == 9 and intelligence < 17)
                         or (level == 10 and intelligence == 17))))
    if race == 1:
        return ((name in ("fighter", "ranger") and banded(strength, 6, 7))
                or (name == "magic-user" and banded(intelligence, 6, 7)))
    if race == 2:
        return name == "fighter" and banded(strength, 7, 8)
    if race == 3:
        return ((name == "fighter" and level == 5 and strength < 18)
                or (name == "cleric" and level >= 7))
    if race == 4:
        return name == "fighter" and banded(strength, 4, 5)
    return False


def pod_ready_flag(rec) -> int:
    """`0x1B500`, which the trainer stores in `0x0CB` last: 1 if any slot
    below 40 has the experience for its next level and is not blocked."""
    experience = _s32(rec, _POD_EXPERIENCE)
    for slot in range(len(POD_SLOTS)):
        level = rec[_POD_LEVELS + slot]
        if not 0 < level < _POD_LAST_LEVEL:
            continue
        want = pod_threshold(slot, level + 1)
        if _pod_ready_blocked(rec, slot, level):
            continue
        if experience >= want and want > 0:
            return 1
    return 0


def _pod_ready_mask(rec) -> tuple[int, int]:
    """The trainer's first loop (`0x3D140`): the ready mask, and the clamp it
    finds before the two best-class passes. Also the last held slot's level,
    which the first of those passes reads for every class (`0x3D41E`)."""
    experience = _s32(rec, _POD_EXPERIENCE)
    held = [slot for slot in range(len(POD_SLOTS)) if rec[_POD_LEVELS + slot]]
    mask = 0
    clamp = 0
    for slot in held:
        level = rec[_POD_LEVELS + slot]
        if _pod_race_blocked(rec, slot, level):
            continue
        if not pod_threshold(slot, level + 1) <= experience:
            continue
        mask = (mask + _POD_READY_BIT[slot]) & 0xFF
        ceiling = pod_threshold(slot, level + 2)
        for other in held:
            want = pod_threshold(other, rec[_POD_LEVELS + other] + 1)
            if want > ceiling:
                ceiling = want
        if experience >= ceiling and ceiling > clamp:
            clamp = ceiling - 1
    return mask, clamp


def _pod_clamp(rec, mask: int, clamp: int) -> int:
    """`0x3D41E`-`0x3D5BC`: the clamp the trainer writes before its prompt.

    Two more candidates join the first loop's. The class whose next threshold
    is largest **read at the last held slot's level** (the register the first
    loop left behind), counted if experience reaches its threshold two up from
    there; and the class whose own next threshold is largest, counted always.
    Experience becomes the largest candidate less one, if that is lower.
    """
    experience = _s32(rec, _POD_EXPERIENCE)
    held = [slot for slot in range(len(POD_SLOTS)) if rec[_POD_LEVELS + slot]]
    ready = [slot for slot in range(len(POD_SLOTS))
             if mask & _POD_READY_BIT[slot]]
    last = rec[_POD_LEVELS + held[-1]] if held else 0
    best, best_want = None, 0
    for slot in ready:
        want = pod_threshold(slot, last + 1)
        if want > best_want:
            best, best_want = slot, want
    if best is not None:
        ceiling = pod_threshold(best, last + 2)
        if ceiling > 0 and experience >= ceiling and ceiling > clamp:
            clamp = ceiling - 1
    best, best_want = None, 0
    for slot in ready:
        want = pod_threshold(slot, rec[_POD_LEVELS + slot] + 1)
        if want > best_want:
            best, best_want = slot, want
    if best is not None:
        ceiling = pod_threshold(best, rec[_POD_LEVELS + best] + 2)
        if ceiling > 0 and ceiling > clamp:
            clamp = ceiling - 1
    return clamp


def _pod_ready_slots(rec) -> list[int]:
    mask, _ = _pod_ready_mask(rec)
    return [slot for slot in range(len(POD_SLOTS))
            if rec[_POD_LEVELS + slot] and mask & _POD_READY_BIT[slot]]


def pod_offers(rec) -> list[int]:
    """The trainer's spell menu (`0x3596C` mode 4, "to Choose"): every
    magic-user spell whose level has a magic-user slot and that the book
    does not hold, read after the recompute."""
    out = []
    for spell in range(1, _POD_LAST_SPELL + 1):
        who, level = _POD_SPELLS.get(spell, (3, 0))
        if (who == 2 and 1 <= level <= 9
                and rec[_POD_CAPACITY + 18 + level - 1] > 0
                and not _pod_has_spell(rec, spell)):
            out.append(spell)
    return out


#: The effects `0x3D884` adds when `pod_regained` holds, through the
#: constructor `0x12FD4`: 0x69 for a former ranger (`tst.b $A8` then `bls`,
#: unsigned) and then 8 for a former paladin (`$A7`), each only if the
#: character lacks it (`0x1A6EE`).
_POD_REGAINED_EFFECTS = ((_POD_FORMER + _POD_RANGER, 0x69), (_POD_FORMER + 3, 8))


def _pod_hit_points(rec: bytearray, mask: int, classes: int, rng) -> None:
    """`0x24334(record, mask, classes, 1)`, after the recompute.

    For each held class in the mask: below its cap, two rolls of the die
    keeping the higher, added to a byte total, and `dice * 0x24550` to a
    bonus byte; at its cap the total is *replaced* by the flat number and no
    bonus is added. Both totals are divided by the class count (the bonus
    read unsigned), the rolls raised to 1, and the damage is kept.
    """
    rolled = 0
    bonus = 0
    for slot in range(len(POD_SLOTS)):
        level = rec[_POD_LEVELS + slot]
        if not level or not mask & _POD_READY_BIT[slot]:
            continue
        if level < _POD_ROLL_BELOW[slot]:
            dice = 1 if level > 1 else _POD_FIRST_DICE[slot]
            roll = max(_dice(rng, dice, _POD_SIDES[slot]),
                       _dice(rng, dice, _POD_SIDES[slot])) & 0xFF
            rolled = (rolled + roll) & 0xFF
            bonus = (bonus + dice * _pod_hp_bonus(rec, slot)) & 0xFF
        elif _POD_FLAT[slot] is not None:
            rolled = _POD_FLAT[slot]
    rolled = max(rolled // classes, 1)
    bonus = (bonus // classes) & 0xFF
    damage = (rec[_POD_HP_MAX] - rec[_POD_HP_CURRENT]) & 0xFF
    rec[_POD_HP_ROLLED] = (rec[_POD_HP_ROLLED] + rolled) & 0xFF
    rec[_POD_HP_MAX] = (rec[_POD_HP_MAX] + bonus + rolled) & 0xFF
    rec[_POD_HP_CURRENT] = (0 if damage > rec[_POD_HP_MAX]
                            else rec[_POD_HP_MAX] - damage)


def _pod_hp_bonus(rec, slot: int) -> int:
    """`0x24550`: `g130A[constitution]` -- -2 at 3, -1 at 4-6, +1 at 15, +2
    from 16 -- and for the druid, fighter, paladin and ranger slots +1 at 17,
    +2 at 18, +3 at 19-20, +4 at 21-23, +5 at 24-25. The DOS row
    `levels._HP_BONUS_POD` is the uncapped sum, so both halves come from it."""
    constitution = rec[_POD_CONSTITUTION]
    value = levels._HP_BONUS_POD[min(constitution, 16)]
    if slot in (1, 2, 3, 4) and constitution >= 17:
        value += levels._HP_BONUS_POD[constitution] - levels._HP_BONUS_POD[16]
    return value


def _pod_plan(raw: bytes, rng, learn: int | None, effects, items=()) -> Plan:
    rec = bytearray(raw)
    try:
        pod_check(rec)
    except RecomputeError as why:
        raise CannotLevel(str(why)) from None
    mask, clamp = _pod_ready_mask(rec)
    clamp = _pod_clamp(rec, mask, clamp)
    if clamp > 0 and _s32(rec, _POD_EXPERIENCE) > clamp:
        rec[_POD_EXPERIENCE:_POD_EXPERIENCE + 4] = clamp.to_bytes(4, "big", signed=True)
    if not mask:
        raise CannotLevel("no class has the experience for its next level")
    held = [slot for slot in range(len(POD_SLOTS)) if rec[_POD_LEVELS + slot]]
    old_magic = rec[_POD_LEVELS + _POD_MAGIC_USER]
    rec[_POD_CLASS_BITS] = 0
    trained = []
    for slot in held:
        if mask & _POD_READY_BIT[slot]:
            rec[_POD_LEVELS + slot] = (rec[_POD_LEVELS + slot] + 1) & 0xFF
            trained.append(POD_SLOTS[slot])
    try:
        pod_recompute(rec, items)
    except RecomputeError as why:
        raise CannotLevel(str(why)) from None
    learned = None
    if (rec[_POD_LEVELS + _POD_MAGIC_USER] > old_magic
            or rec[_POD_LEVELS + _POD_RANGER] > 8):
        offers = pod_offers(rec)
        if offers:
            if learn is None:
                raise NeedsSpell(offers)
            if learn not in offers:
                raise CannotLevel(f"spell {learn} is not on the trainer's menu")
            _pod_learn(rec, learn)
            learned = learn
    added = (_regained_effects(rec, _POD_REGAINED_EFFECTS, effects, False)
             if pod_regained(rec) else ())
    if rec[_POD_LEVEL] > rec[_POD_FORMER_LEVEL]:
        _pod_hit_points(rec, mask, len(held), rng)
    rec[_POD_READY] = pod_ready_flag(rec)
    return Plan(POOLS_OF_DARKNESS, tuple(trained), _s32(rec, _POD_EXPERIENCE),
                writes_between(raw, rec), learned, added)


# --- Pool of Radiance --------------------------------------------------------
#
# The trainer `0x18ED8` (hunk 10) of `/program` (sha256 `b1cbbecc0188`), its
# recompute `0x3D682`, hit dice `0x1A86C` and bonus `0x1A51C`; `docs/124`
# §1.23. Record offsets
# are the 288-byte Amiga record's (`goldbox.amiga_por.amiga_por_offset` of
# the DOS ones). The halls train one class each; Level up trains the class
# the C64 Level up would pick (`_por_pick`). Money is not charged.

POOL_OF_RADIANCE = "pool-of-radiance"

POR_SLOTS = ("cleric", "druid", "fighter", "paladin", "ranger", "magic-user",
             "thief", "monk")
_POR_CLERIC = 0
_POR_FIGHTER = 2
_POR_MAGIC_USER = 5
_POR_THIEF = 6

_POR_STRENGTH = 0x010
_POR_WISDOM = 0x012
_POR_DEXTERITY = 0x013
_POR_CONSTITUTION = 0x014
_POR_THAC0 = 0x02D
_POR_RACE = 0x02E
_POR_CLASS = 0x02F
_POR_HP_MAX = 0x032
_POR_SPELLBOOK = 0x032                      # one byte a spell, at 0x032 + id
_POR_SAVES = 0x06D
_POR_LEVEL = 0x073
_POR_DRAINED = 0x074
_POR_HP_LOST = 0x075
_POR_THIEF_SKILLS = 0x077
_POR_LEVELS = 0x098
_POR_ATTACKS = 0x0A3
_POR_EXPERIENCE = 0x0AE
_POR_HP_ROLLED = 0x0B3
_POR_SLOTS_AT = 0x0B3                       # + class * 3 + spell level
_POR_STATUS = 0x10E
_POR_HP_CURRENT = 0x11D

#: `h11+0xA9`: each slot's bit in the ready and hall masks.
_POR_BIT = (2, 2, 8, 0x10, 0x10, 1, 4, 6)
#: `h11+0x774` and `h11+0x77C`: dice and sides by slot.
_POR_DICE = (1, 1, 1, 1, 2, 1, 1, 2)
_POR_SIDES = (8, 8, 10, 10, 8, 4, 6, 4)
#: `h31+0x24A7[constitution]`, 3-20; past 20 the bytes are another table's.
_POR_CON_BONUS = {3: -2, 4: -1, 5: -1, 6: -1, 15: 1, 16: 2, 17: 2, 18: 2,
                  19: 2, 20: 2}
#: `h31+0x30DC`, ids 1-56: `goldbox.spells`' groups, with the class byte 0
#: for a cleric and 1 for a magic-user, and id 56, which the engine's own
#: table calls a cleric spell of level 7 and every id loop reaches.
_POR_LAST_SPELL = 56


def _por_spell_table() -> dict[int, tuple[int, int]]:
    cls = {"cleric": 0, "magic-user": 1}
    out = {}
    for first, last, who, level in spells.POOL_OF_RADIANCE.groups:
        for spell in range(first, last + 1):
            out[spell] = (cls[who], level)
    out[56] = (0, 7)
    return out


_POR_SPELLS = _por_spell_table()
_POR_SLOT_ROWS = spells._SLOTS[spells.POOL_OF_RADIANCE.key]
_POR_TABLES = levels.POOL_OF_RADIANCE


def por_threshold(slot: int, level: int) -> int:
    """`h31+0x24BC[slot * 56 + (level - 2) * 4]`: the experience for `level`.
    A class with no such level reads -1 or 0, which never qualifies."""
    row = _POR_TABLES.at_level(POR_SLOTS[slot], level)
    return row.experience if row is not None and level >= 2 else -1


def _por_thac0(slot: int, level: int) -> int:
    """`h31+0x20B7[slot * 11 + level]`, stored `60 - THAC0`: 40 at level 0
    for every slot, then `levels._DOS_THAC0_POOL`."""
    if level == 0:
        return 60 - dict(_POR_TABLES.dos_thac0_level0)[POR_SLOTS[slot]]
    return 60 - _POR_TABLES.dos_thac0_at(POR_SLOTS[slot], level)


def _por_save_row(slot: int, level: int) -> tuple[int, ...]:
    """`h31+0x268C[slot * 45 + (level - 1) * 5]`: the DOS rows."""
    row = _POR_TABLES.dos_engine_saving_throws({POR_SLOTS[slot]: level})
    if row is None:
        raise CannotLevel(f"no save row is copied for {POR_SLOTS[slot]} "
                          f"level {level}")
    return row


def _por_race_blocked(rec, slot: int, level: int) -> bool:
    """`0x18F9E`-`0x19110`: hard-coded limits on the fighter, by strength at
    `0x010`, and the half-elf cleric at 5. Each tests the level for
    equality."""
    race = rec[_POR_RACE]
    strength = rec[_POR_STRENGTH]
    name = POR_SLOTS[slot]
    if race == 1:                                       # dwarf
        return name == "fighter" and ((level == 8 and strength == 17)
                                      or (level == 7 and strength < 17))
    if race == 2:                                       # elf
        return name == "fighter" and (level == 7
                                      or (level == 6 and strength == 17)
                                      or (level == 5 and strength < 17))
    if race == 3:                                       # gnome
        return name == "fighter" and (level == 6
                                      or (level == 5 and strength < 18))
    if race == 4:                                       # half-elf
        if name == "cleric":
            return level == 5
        return name == "fighter" and (level == 8
                                      or (level == 7 and strength == 17)
                                      or (level == 6 and strength < 17))
    if race == 5:                                       # halfling
        return name == "fighter" and (level == 6
                                      or (level == 5 and strength == 17)
                                      or (level == 4 and strength < 17))
    return False


def _por_held(rec) -> list[int]:
    return [slot for slot in range(len(POR_SLOTS))
            if 0 < _s8(rec[_POR_LEVELS + slot])]


def _por_ready(rec) -> tuple[list[int], int]:
    """The trainer's loop (`0x18F50`): the ready slots, and the clamp: the
    largest threshold two levels up, less one, over ready slots whose
    experience already reaches it."""
    experience = _s32(rec, _POR_EXPERIENCE)
    ready, clamp = [], 0
    for slot in _por_held(rec):
        level = rec[_POR_LEVELS + slot]
        if _por_race_blocked(rec, slot, level):
            continue
        want = por_threshold(slot, level + 1)
        if experience < want or want <= 0:
            continue
        ready.append(slot)
        two_up = por_threshold(slot, level + 2)
        if two_up > 0 and experience >= two_up and two_up > clamp:
            clamp = two_up - 1
    return ready, clamp


#: The C64 Level up's tie-break order (`levelup.best_next_class`).
_POR_ORDER = ("magic-user", "cleric", "thief", "fighter")


def _por_pick(rec, ready: list[int]) -> int:
    """The one class a press trains: the C64 Level up's choice, the ready
    class whose threshold after the level is largest, ties in class-bit
    order. Each Amiga hall trains one class and a button is not in a hall."""
    def rank(slot):
        after = max(por_threshold(slot, rec[_POR_LEVELS + slot] + 2), 0)
        name = POR_SLOTS[slot]
        order = _POR_ORDER.index(name) if name in _POR_ORDER else len(_POR_ORDER)
        return (after, -order)
    return max(ready, key=rank)


def _por_thief_skills(rec: bytearray) -> None:
    """`0x3D9C8`: level row, race row (0 when a negative race value exceeds
    the level value) and, on the first five, the dexterity row. No clamp."""
    row = _POR_TABLES.thief_skills[rec[_POR_LEVELS + _POR_THIEF] - 1]
    race = levels._DOS_THIEF_SKILL_RACE_POOL[rec[_POR_RACE] - 1]
    dex = levels._DOS_THIEF_SKILL_DEX_POOL[rec[_POR_DEXTERITY] - 9]
    for skill in range(8):
        base, adjust = row[skill], race[skill]
        if adjust < 0 and -adjust > base:
            rec[_POR_THIEF_SKILLS + skill] = 0
            continue
        value = base + adjust
        if skill < 5:
            value += dex[skill]
        rec[_POR_THIEF_SKILLS + skill] = value & 0xFF


def por_recompute(rec: bytearray) -> None:
    """`0x3D682`, which training and every load run: THAC0 over all eight
    slots with level 0 included, the level byte, `attack_forms[0]` written
    outright from the fighter's level, cleric and magic-user slots from level
    2 with the wisdom bonus and the cleric's grants, saves, thief skills."""
    rec[_POR_THAC0] = 0
    for slot in range(len(POR_SLOTS)):
        level = _s8(rec[_POR_LEVELS + slot])
        value = _por_thac0(slot, level)
        if rec[_POR_THAC0] < value:
            rec[_POR_THAC0] = value
        if _s8(rec[_POR_LEVEL]) < level:
            rec[_POR_LEVEL] = level
        if slot == _POR_FIGHTER:
            rec[_POR_ATTACKS] = 3 if level > 6 else 2
        elif slot == _POR_CLERIC and level > 1:
            row = _row(_POR_SLOT_ROWS["cleric"], "cleric", level)
            for i in range(3):
                rec[_POR_SLOTS_AT + 1 + i] = row[i]
            _por_wisdom(rec)
            for spell in range(1, _POR_LAST_SPELL + 1):
                who, spell_level = _POR_SPELLS[spell]
                if who == 0 and rec[_POR_SLOTS_AT + spell_level] > 0:
                    rec[_POR_SPELLBOOK + spell] = 1
        elif slot == _POR_MAGIC_USER and level > 1:
            row = _row(_POR_SLOT_ROWS["magic-user"], "magic-user", level)
            for i in range(3):
                rec[_POR_SLOTS_AT + 4 + i] = row[i]
    for column in range(5):
        rec[_POR_SAVES + column] = 20
        for slot in _por_held(rec):
            cell = _por_save_row(slot, rec[_POR_LEVELS + slot])[column]
            if rec[_POR_SAVES + column] > cell:
                rec[_POR_SAVES + column] = cell
    if _s8(rec[_POR_LEVELS + _POR_THIEF]) > 0:
        _por_thief_skills(rec)


def _por_wisdom(rec: bytearray) -> None:
    """`0x3D83C`: wisdom above 12 and 13 each add a first-level slot, above
    14 and 15 a second, above 16 a third, each only where one already is."""
    wisdom = rec[_POR_WISDOM]
    for above, spell_level in ((12, 1), (13, 1), (14, 2), (15, 2), (16, 3)):
        at = _POR_SLOTS_AT + spell_level
        if wisdom > above and rec[at] > 0:
            rec[at] = (rec[at] + 1) & 0xFF


def por_offers(rec) -> list[int]:
    """The trainer's spell menu (`0x36ACC`, mode 4): every id 1-56 whose
    class has a slot at its level and that the book does not hold."""
    out = []
    for spell in range(1, _POR_LAST_SPELL + 1):
        who, level = _POR_SPELLS[spell]
        if rec[_POR_SLOTS_AT + who * 3 + level] > 0 and not rec[_POR_SPELLBOOK + spell]:
            out.append(spell)
    return out


def _por_check(rec) -> None:
    if rec[_POR_STATUS] != 0:
        raise CannotLevel("the trainer only trains conscious characters")
    for slot in _por_held(rec):
        if POR_SLOTS[slot] not in _POR_ORDER:
            raise CannotLevel(_NOT_COPIED.format(POR_SLOTS[slot]))
    if rec[_POR_CONSTITUTION] not in range(3, 21):
        raise CannotLevel("a constitution outside 3-20 reads past the "
                          "hit-point bonus table")
    if _s8(rec[_POR_LEVELS + _POR_THIEF]) > 0:
        if not 1 <= rec[_POR_RACE] <= 7:
            raise CannotLevel("a thief's race has no thief-skill row")
        if not 9 <= rec[_POR_DEXTERITY] <= 19:
            raise CannotLevel("a thief's dexterity outside 9-19 reads past "
                              "the thief-skill table")


def _por_bonus(rec) -> int:
    """`0x1A51C`: the constitution bonus once for every class held, plus 1
    above 16 and 1 more above 17 for a single-class fighter (`char_class`
    2)."""
    constitution = rec[_POR_CONSTITUTION]
    total = 0
    for _slot in _por_held(rec):
        total += _POR_CON_BONUS.get(constitution, 0)
        if constitution > 16 and rec[_POR_CLASS] == 2:
            total += 1
        if constitution > 17 and rec[_POR_CLASS] == 2:
            total += 1
    return _s8(total & 0xFF)


def _por_ready_slots(rec) -> list[int]:
    ready, _ = _por_ready(rec)
    return [_por_pick(rec, ready)] if ready else []


def _por_raise(rec: bytearray, slot: int) -> None:
    """`0x19444`: the class level, and a drained character's lost hit points
    shared out over the drained levels (`0x1CEB0` divides)."""
    rec[_POR_LEVELS + slot] = (rec[_POR_LEVELS + slot] + 1) & 0xFF
    drained = rec[_POR_DRAINED]
    if drained > 0:
        lost = rec[_POR_HP_LOST]
        rec[_POR_HP_LOST] = (lost - lost // drained) & 0xFF
        rec[_POR_DRAINED] = drained - 1


def _por_plan(raw: bytes, rng, learn: int | None, effects, items=()) -> Plan:
    rec = bytearray(raw)
    _por_check(rec)
    ready, clamp = _por_ready(rec)
    if clamp > 0:
        rec[_POR_EXPERIENCE:_POR_EXPERIENCE + 4] = clamp.to_bytes(4, "big", signed=True)
    if not ready:
        raise CannotLevel("no class has the experience for its next level")
    slot = _por_pick(rec, ready)
    classes = len(_por_held(rec))
    old_magic = rec[_POR_LEVELS + _POR_MAGIC_USER]
    _por_raise(rec, slot)
    por_recompute(rec)
    learned = None
    if _s8(rec[_POR_LEVELS + _POR_MAGIC_USER]) > _s8(old_magic):
        offers = por_offers(rec)
        if offers:
            if learn is None:
                raise NeedsSpell(offers)
            if learn not in offers:
                raise CannotLevel(f"spell {learn} is not on the trainer's menu")
            rec[_POR_SPELLBOOK + learn] = 1
            learned = learn
    die = 0
    level = rec[_POR_LEVELS + slot]
    roll = _dice(rng, _POR_DICE[slot], _POR_SIDES[slot])
    if level == 1:
        roll = max(roll, 2 * _POR_SIDES[slot] // 3)
    die = (die + roll) & 0xFF
    rolled = die // classes or 1
    rec[_POR_HP_ROLLED] = (rec[_POR_HP_ROLLED] + rolled) & 0xFF
    gained = int((die + _por_bonus(rec)) / classes)
    gained = max(gained, 1)
    damage = (rec[_POR_HP_MAX] - rec[_POR_HP_CURRENT]) & 0xFF
    rec[_POR_HP_MAX] = (rec[_POR_HP_MAX] + gained) & 0xFF
    rec[_POR_HP_CURRENT] = (rec[_POR_HP_MAX] - damage) & 0xFF
    return Plan(POOL_OF_RADIANCE, (POR_SLOTS[slot],), _s32(rec, _POR_EXPERIENCE),
                writes_between(raw, rec), learned)


# --- Curse of the Azure Bonds ------------------------------------------------
#
# The trainer `0x16910` of `/Curse` (sha256 `8d4ceba86e4b`), its recompute
# `0x38A52` (capacity `0x3872A`, wisdom `0x38CB0`, saves `0x38DC6`, thief
# skills `0x390C4`), hit dice `0x16718` and bonus `0x16310`; `docs/124`
# §1.23.
# Record offsets are the 428-byte Amiga record's (`CURSE_DELTAS`).
#
# **The thief-skill step `0x390C4` is not copied**: it adds a leftover start-up
# register to every skill (`docs/124` §1.23), so the skills come from
# `levels.ad_d_thief_skills` instead.

CURSE = "curse-of-the-azure-bonds"

CURSE_SLOTS = ("cleric", "druid", "fighter", "paladin", "ranger",
               "magic-user", "thief", "monk")
_CU_CLERIC, _CU_PALADIN, _CU_RANGER, _CU_MAGIC_USER, _CU_THIEF = 0, 3, 4, 5, 6

_CU_STRENGTH = 0x011                        # in-force halves of the pairs
_CU_INTELLIGENCE = 0x013
_CU_WISDOM = 0x015
_CU_CONSTITUTION = 0x019
_CU_THAC0 = 0x073
_CU_RACE = 0x074
_CU_HUMAN = 7
_CU_CLASS = 0x075
_CU_HP_MAX = 0x078
_CU_SPELLBOOK = 0x078                       # one byte a spell, at 0x078 + id
_CU_SAVES = 0x0DF
_CU_LEVEL = 0x0E5
_CU_FORMER_LEVEL = 0x0E6
_CU_DRAINED = 0x0E7
_CU_HP_LOST = 0x0E8
_CU_LEVELS = 0x10A
_CU_FORMER = 0x112                          # eight bytes; the ninth is the sex
_CU_SEX = 0x11A
_CU_ATTACKS = 0x11D
_CU_EXPERIENCE = 0x128
_CU_CLASS_BITS = 0x12C
_CU_HP_ROLLED = 0x12D
_CU_CAPACITY = 0x12E                        # cleric, druid, magic-user; six each
_CU_CAPACITY_BYTES = 18
_CU_STATUS = 0x19A
_CU_HP_CURRENT = 0x1A9
_CU_DEXTERITY = 0x017
_CU_THIEF_SKILLS = 0x0EA                    # eight bytes

#: `g1BA0`: each slot's bit in the ready mask.
_CU_READY_BIT = (2, 2, 8, 16, 32, 1, 4, 4)
#: `g1B98`: each slot's bit in the class mask at `0x12C`.
_CU_CLASS_BIT = (2, 16, 8, 64, 64, 1, 4, 32)
#: `0x16718`: a class rolls while its new level is below `g1BB1`, `g0ED4`
#: dice at level 1 and one after, of `g0EDC` sides, two rolls keeping the
#: higher; at or past it the running total is replaced by a flat number.
_CU_ROLL_BELOW = (10, 15, 10, 10, 11, 12, 11, 19)
_CU_FIRST_DICE = (1, 1, 1, 1, 2, 1, 1, 2)
_CU_SIDES = (8, 8, 10, 10, 8, 4, 6, 4)
_CU_FLAT = (2, None, 3, 3, 2, 1, 2, None)
#: `g16B0[8 * 65 + sex * 5]`: the five bytes the save rebuild reads one slot
#: past its table (see `_curse_saves`).
_CU_PAST_TABLE_SAVES = ((0, 0, 0, 1, 0), (0, 0, 10, 0, 0))
_CU_TABLES = levels.CURSE_OF_THE_AZURE_BONDS
#: `g1290`: the two thresholds where the Amiga's table is not the C64's.
_CU_THRESHOLDS = {("ranger", 2): 2251, ("fighter", 11): 750001}
#: `g1EDE`, ids 1-100: `goldbox.spells`' groups, corrected where the Amiga's
#: own table says otherwise. 36 and 90 are no class's (3), 56 a cleric spell
#: of level 7, and 100 a magic-user spell of level 4.
_CU_LAST_SPELL = 100


def _curse_spell_table() -> dict[int, tuple[int, int]]:
    cls = {"cleric": 0, "druid": 1, "magic-user": 2}
    out = {}
    for first, last, who, level in spells.CURSE_OF_THE_AZURE_BONDS.groups:
        for spell in range(first, last + 1):
            out[spell] = (cls[who], level)
    out.update({36: (3, 7), 56: (0, 7), 90: (3, 5), 100: (2, 4)})
    return out


_CU_SPELLS = _curse_spell_table()
_CU_SLOT_ROWS = spells._SLOTS[spells.CURSE_OF_THE_AZURE_BONDS.key]


def curse_threshold(slot: int, level: int) -> int:
    """`g1290[slot * 130 + level * 4]`. Past a ceiling it reads -1 or 0,
    which never qualifies and never clamps."""
    name = CURSE_SLOTS[slot]
    if (name, level) in _CU_THRESHOLDS:
        return _CU_THRESHOLDS[(name, level)]
    row = _CU_TABLES.at_level(name, level)
    return row.experience if row is not None and level >= 2 else -1


def _curse_first_held(rec) -> int:
    slot = 0
    while slot < 7 and rec[_CU_LEVELS + slot] == 0:
        slot += 1
    return rec[_CU_LEVELS + slot]


def curse_regained(rec) -> bool:
    """`0x39870`: a human (`0x074 == 7`) whose first held class level is
    above `0x0E6`, signed."""
    first = _curse_first_held(rec) if rec[_CU_RACE] == _CU_HUMAN else 0
    return _s8(first) > _s8(rec[_CU_FORMER_LEVEL])


def _curse_race_blocked(rec, slot: int, level: int) -> bool:
    """`0x169DC`-`0x16B4A`, by the race at `0x074` (1 dwarf, 2 elf, 3 gnome,
    4 half-elf, 5 halfling); each tests the level for equality."""
    race = rec[_CU_RACE]
    strength = rec[_CU_STRENGTH]
    intelligence = rec[_CU_INTELLIGENCE]
    name = CURSE_SLOTS[slot]

    def banded(score, low, mid, high):
        return (level == high or (level == mid and score == 17)
                or (level == low and score < 17))

    if race == 1:
        return name == "fighter" and banded(strength, 7, 8, 9)
    if race == 2:
        if name == "fighter":
            return banded(strength, 5, 6, 7)
        return name == "magic-user" and (level == 11
                                         or (level == 9 and intelligence < 17)
                                         or (level == 10 and intelligence == 17))
    if race == 3:
        return name == "fighter" and (level == 6
                                      or (level == 5 and strength < 18))
    if race == 4:
        if name == "cleric":
            return level == 5
        if name in ("fighter", "ranger") and banded(strength, 6, 7, 8):
            return True
        return name == "magic-user" and banded(intelligence, 6, 7, 8)
    if race == 5:
        return name == "fighter" and banded(strength, 4, 5, 6)
    return False


def _curse_held(rec) -> list[int]:
    return [slot for slot in range(len(CURSE_SLOTS))
            if _s8(rec[_CU_LEVELS + slot]) > 0]


def _curse_ready(rec) -> tuple[int, int]:
    """`0x16998`-`0x16D4A`: the one class trained and the clamp.

    The first loop finds the ready classes and the largest two-up threshold
    experience already reaches. The second keeps only the ready class whose
    next threshold is largest **read at the last held slot's level** (the
    register the first loop leaves), and counts its threshold two up from
    that level too. That is why a fighter 4 / thief 5 at 100000 is clamped
    to 70000, the fighter's level 7, as the live training measured
    (`974fd5e0`), where the first loop alone gives 42500.
    """
    experience = _s32(rec, _CU_EXPERIENCE)
    mask, clamp, last = 0, 0, 0
    for slot in _curse_held(rec):
        level = rec[_CU_LEVELS + slot]
        last = level
        if _curse_race_blocked(rec, slot, level):
            continue
        want = curse_threshold(slot, level + 1)
        if want > experience or want <= 0:
            continue
        mask |= _CU_READY_BIT[slot]
        two_up = curse_threshold(slot, level + 2)
        if two_up > 0 and experience >= two_up and two_up > clamp:
            clamp = two_up - 1
    best, best_want = None, 0
    for slot in range(len(CURSE_SLOTS)):
        if not mask & _CU_READY_BIT[slot]:
            continue
        want = curse_threshold(slot, last + 1)
        if want > best_want:
            best, best_want = slot, want
    if best is not None:
        mask = _CU_READY_BIT[best]
        two_up = curse_threshold(best, last + 2)
        if two_up > 0 and experience >= two_up and two_up > clamp:
            clamp = two_up - 1
    return mask, clamp


def _curse_thac0(slot: int, level: int) -> int:
    """`g1B30[slot * 13 + level]`, stored `60 - THAC0`."""
    name = CURSE_SLOTS[slot]
    if level == 0:
        return 60 - dict(_CU_TABLES.dos_thac0_level0)[name]
    return 60 - _CU_TABLES.dos_thac0_at(name, level)


def _curse_save_row(slot: int, level: int) -> tuple[int, ...]:
    """`g16B0[slot * 65 + level * 5]`: the DOS cells, paladin's included."""
    row = _CU_TABLES.dos_engine_saving_throws({CURSE_SLOTS[slot]: level})
    if row is None:
        raise CannotLevel(f"no save row is copied for {CURSE_SLOTS[slot]} "
                          f"level {level}")
    return row


def _curse_capacity(rec: bytearray, items) -> None:
    """`0x3872A`: capacity from zero, slot by slot, at the former level when
    `curse_regained` holds and there is one.

    The cleric's rows (`g12C4`, deltas from 1 at level 1) are followed by the
    wisdom bonus (`0x38CB0`: above 12 and 13 a first-level slot, 14 and 15 a
    second, 16 a third, 17 a fourth, each where one already is) and the grant
    of every cleric spell with a slot, id 36 excepted. A paladin above 8 adds
    `g144A` to the cleric's array and grants the same way; a ranger above 7
    adds `g14CC` columns 1-3 to the druid's and 4-5 to the magic-user's
    levels 1-2, and grants every druid spell; a magic-user adds `g154E`.
    The sums are `goldbox.spells`' rows. Last, a readied item of power `0x81`
    doubles magic-user levels 1-3.
    """
    for i in range(_CU_CAPACITY_BYTES):
        rec[_CU_CAPACITY + i] = 0

    def add(array, column, value):
        at = _CU_CAPACITY + array * 6 + column
        rec[at] = (rec[at] + value) & 0xFF

    def grant(test):
        for spell in range(1, _CU_LAST_SPELL + 1):
            who, level = _CU_SPELLS.get(spell, (3, 0))
            if test(spell, who, level):
                rec[_CU_SPELLBOOK + spell] = 1

    def cleric_slot(level):
        return rec[_CU_CAPACITY - 1 + level] > 0

    regained = curse_regained(rec)
    for slot in range(len(CURSE_SLOTS)):
        former = rec[_CU_FORMER + slot]
        level = _s8(former if regained and former else rec[_CU_LEVELS + slot])
        if level <= 0:
            continue
        if slot == _CU_CLERIC:
            for column, value in enumerate(_row(_CU_SLOT_ROWS["cleric"], "cleric", level)):
                add(0, column, value)
            _curse_wisdom(rec)
            grant(lambda spell, who, lv: who == 0 and cleric_slot(lv)
                  and spell != 36)
        elif slot == _CU_PALADIN and level > 8:
            for column, value in enumerate(_row(_CU_SLOT_ROWS["paladin"], "paladin", level)):
                add(0, column, value)
            grant(lambda spell, who, lv: who == 0 and cleric_slot(lv))
        elif slot == _CU_RANGER and level > 7:
            to_druid, to_mage = _row(_CU_SLOT_ROWS["ranger"], "ranger", level)
            for column in range(5):
                add(1, column, to_druid[column])
                add(2, column, to_mage[column])
            grant(lambda spell, who, lv: who == 1)
        elif slot == _CU_MAGIC_USER:
            for column, value in enumerate(_row(_CU_SLOT_ROWS["magic-user"], "magic-user", level)):
                add(2, column, value)
    for node in items:
        if len(node) > 0x41 and node[0x41] == 0x81 and node[0x35]:
            for column in range(3):
                add(2, column, rec[_CU_CAPACITY + 12 + column])


def _curse_wisdom(rec: bytearray) -> None:
    """`0x38CB0(record, 0)`: the wisdom bonus, if the cleric's level plus a
    regained former level is above 0."""
    level = rec[_CU_LEVELS] + (rec[_CU_FORMER] if curse_regained(rec) else 0)
    if _s8(level & 0xFF) <= 0:
        return
    wisdom = rec[_CU_WISDOM]
    for above, spell_level in ((12, 1), (13, 1), (14, 2), (15, 2), (16, 3),
                               (17, 4)):
        at = _CU_CAPACITY + spell_level - 1
        if wisdom > above and rec[at] > 0:
            rec[at] = (rec[at] + 1) & 0xFF


def _curse_saves(rec: bytearray, items) -> None:
    """`0x38DC6`: each column from 20, lowered over held slots; then the
    compare one slot past the class array, which reads the former cleric
    level against the sex byte and, if larger, lowers the column to a cell
    past the table (`_CU_PAST_TABLE_SAVES`; the same lookup is CONFIRMED
    live in Silver Blades, `9f0896c0`); then column 0's constitution steps:
    the racial one for a dwarf or halfling or a readied item of power kind
    6, and the high one for everyone."""
    kind_six = readied_power(items, 6)
    for column in range(5):
        value = 20
        for slot in _curse_held(rec):
            cell = _curse_save_row(slot, rec[_CU_LEVELS + slot])[column]
            if cell < value:
                value = cell
        if _s8(rec[_CU_FORMER]) > _s8(rec[_CU_SEX]):
            cell = _CU_PAST_TABLE_SAVES[rec[_CU_SEX]][column]
            if cell < value:
                value = cell
        if column == 0:
            constitution = rec[_CU_CONSTITUTION]
            if rec[_CU_RACE] in (1, 5) or kind_six:
                value += levels._dos_con_save_racial_step(constitution)
            value += levels._dos_con_save_high_step(constitution)
        rec[_CU_SAVES + column] = value & 0xFF


def _curse_thief_skills(rec: bytearray) -> None:
    """The eight thief skills at the thief level (plus a regained former
    one), by `levels.ad_d_thief_skills`."""
    level = _s8((int(curse_regained(rec)) * _s8(rec[_CU_FORMER + _CU_THIEF])
                 + _s8(rec[_CU_LEVELS + _CU_THIEF])) & 0xFF)
    skills = levels.ad_d_thief_skills(level, rec[_CU_RACE], CURSE,
                                      rec[_CU_DEXTERITY])
    if skills is None:
        raise CannotLevel("a thief with no dexterity has no thief-skill row")
    rec[_CU_THIEF_SKILLS:_CU_THIEF_SKILLS + 8] = bytes(skills)


def curse_recompute(rec: bytearray, items=()) -> None:
    """`0x38A52`: THAC0 over all eight slots with level 0 included, the
    level byte, `attack_forms[0]` raised to 3, capacity, saves, thief skills
    for a thief level, the class mask, and a regained class's attacks, THAC0
    and, for a regained former thief, the thief skills again."""
    rec[_CU_THAC0] = 0
    for slot in range(len(CURSE_SLOTS)):
        level = rec[_CU_LEVELS + slot]
        value = _curse_thac0(slot, level)
        if value > rec[_CU_THAC0]:
            rec[_CU_THAC0] = value
        if _s8(rec[_CU_LEVEL]) < _s8(level):
            rec[_CU_LEVEL] = level
        if (slot in (2, 3) and _s8(level) > 6) or (slot == _CU_RANGER
                                                   and _s8(level) > 7):
            rec[_CU_ATTACKS] = 3
    _curse_capacity(rec, items)
    _curse_saves(rec, items)
    if _s8(rec[_CU_LEVELS + _CU_THIEF]) > 0:
        _curse_thief_skills(rec)
    bits = 0
    for slot in range(len(CURSE_SLOTS)):
        former = _s8(rec[_CU_FORMER + slot])
        if (_s8(rec[_CU_LEVELS + slot]) > 0
                or 0 < former < _s8(rec[_CU_LEVEL])):
            bits = (bits + _CU_CLASS_BIT[slot]) & 0xFF
    rec[_CU_CLASS_BITS] = bits
    # `0x38B6E` would unready an item whose class mask no longer matches;
    # training only adds bits, so a level-up never reaches it.
    if curse_regained(rec):
        for slot in range(len(CURSE_SLOTS)):
            former = rec[_CU_FORMER + slot]
            if (slot in (2, 3) and _s8(former) > 6) or (slot == _CU_RANGER
                                                        and _s8(former) > 7):
                rec[_CU_ATTACKS] = 3
            value = _curse_thac0(slot, former)
            if value > rec[_CU_THAC0]:
                rec[_CU_THAC0] = value
        if (_s8(rec[_CU_FORMER + 2]) > 6 or _s8(rec[_CU_FORMER + 4]) > 7
                or _s8(rec[_CU_FORMER + 3]) > 6):
            rec[_CU_ATTACKS] = 3
        if _s8(rec[_CU_FORMER + _CU_THIEF]) > 0:
            _curse_thief_skills(rec)


def _curse_can_cast(rec, who: int) -> bool:
    """`0x2F4FA`, for the trainer's menu: a cleric spell needs wisdom above
    8 and a cleric level or a paladin above 8; a druid spell wisdom above 8
    and a ranger above 6; a magic-user spell intelligence above 8 and a
    magic-user level or a ranger above 8. A regained former level counts.
    The magic-user's last test, a human in armour during a fight, cannot
    hold at a trainer."""
    regained = curse_regained(rec)

    def level(slot, former=False):
        value = rec[(_CU_FORMER if former else _CU_LEVELS) + slot]
        return _s8(value)

    def either(slot, above):
        return level(slot) > above or (regained and level(slot, True) > above)

    if who == 0:
        return rec[_CU_WISDOM] > 8 and (either(_CU_CLERIC, 0)
                                        or either(_CU_PALADIN, 8))
    if who == 1:
        return rec[_CU_WISDOM] > 8 and either(_CU_RANGER, 6)
    if who == 2:
        return rec[_CU_INTELLIGENCE] > 8 and (either(_CU_RANGER, 8)
                                              or either(_CU_MAGIC_USER, 0))
    return False


def curse_offers(rec) -> list[int]:
    """The trainer's menu (`0x2FD26` mode 4): every id 1-100 whose class has
    a slot at its level, that the character can cast, and that the book
    does not hold."""
    out = []
    for spell in range(1, _CU_LAST_SPELL + 1):
        who, level = _CU_SPELLS.get(spell, (3, 0))
        if who > 2:
            continue
        # Id 56, a cleric spell of level 7, reads the druid's first slot.
        if (rec[_CU_CAPACITY + who * 6 + level - 1] > 0
                and _curse_can_cast(rec, who) and not rec[_CU_SPELLBOOK + spell]):
            out.append(spell)
    return out


def _curse_check(rec) -> None:
    if rec[_CU_STATUS] != 0:
        raise CannotLevel("the trainer only trains conscious characters")
    for slot in _curse_held(rec):
        if CURSE_SLOTS[slot] in ("druid", "monk"):
            raise CannotLevel(_NOT_COPIED.format(CURSE_SLOTS[slot]))
    if (_s8(rec[_CU_FORMER]) > _s8(rec[_CU_SEX])
            and rec[_CU_SEX] >= len(_CU_PAST_TABLE_SAVES)):
        raise CannotLevel("a sex byte past 1 reads further past the save table")
    if not 3 <= rec[_CU_CONSTITUTION] <= 25:
        raise CannotLevel("a constitution outside 3-25 reads past the "
                          "hit-point bonus table")


def _curse_bonus(rec) -> int:
    """`0x16310`: per held class below its cap, `g1276[constitution]`
    (`levels._HP_BONUS_POD`'s row below 17) and, for a single-class fighter,
    paladin or ranger (`char_class` 2-4), +1 to +5 from 17; a ranger at
    level 1 doubles the sum so far. Returned as a signed byte."""
    constitution = rec[_CU_CONSTITUTION]
    total = 0
    for slot in _curse_held(rec):
        level = rec[_CU_LEVELS + slot]
        if level >= _CU_ROLL_BELOW[slot]:
            continue
        total += levels._HP_BONUS_POD[min(constitution, 16)]
        if rec[_CU_CLASS] in (2, 3, 4) and constitution >= 17:
            total += (levels._HP_BONUS_POD[constitution]
                      - levels._HP_BONUS_POD[16])
        if slot == _CU_RANGER and level == 1:
            total *= 2
        total = _s8(total & 0xFF)
    return total


def _curse_dice(rec, mask: int, rng) -> int:
    """`0x16718`: the dice of the trained class, as a byte."""
    total = 0
    for slot in _curse_held(rec):
        if not _CU_READY_BIT[slot] & mask:
            continue
        level = rec[_CU_LEVELS + slot]
        if level < _CU_ROLL_BELOW[slot]:
            dice = 1 if level > 1 else _CU_FIRST_DICE[slot]
            roll = max(_dice(rng, dice, _CU_SIDES[slot]),
                       _dice(rng, dice, _CU_SIDES[slot])) & 0xFF
            total = (total + roll) & 0xFF
        elif _CU_FLAT[slot] is not None:
            total = _CU_FLAT[slot]
    return total


def _curse_ready_slots(rec) -> list[int]:
    mask, _ = _curse_ready(rec)
    return [slot for slot in _curse_held(rec) if _CU_READY_BIT[slot] & mask]


def _curse_raise(rec: bytearray, mask: int) -> None:
    rec[_CU_CLASS_BITS] = 0
    for slot in _curse_held(rec):
        if not _CU_READY_BIT[slot] & mask:
            continue
        rec[_CU_LEVELS + slot] = (rec[_CU_LEVELS + slot] + 1) & 0xFF
        drained = rec[_CU_DRAINED]
        if drained > 0:
            lost = rec[_CU_HP_LOST]
            rec[_CU_HP_LOST] = (lost - lost // drained) & 0xFF
            rec[_CU_DRAINED] = drained - 1


def _curse_plan(raw: bytes, rng, learn: int | None, effects, items=()) -> Plan:
    rec = bytearray(raw)
    _curse_check(rec)
    mask, clamp = _curse_ready(rec)
    if clamp > 0:
        rec[_CU_EXPERIENCE:_CU_EXPERIENCE + 4] = clamp.to_bytes(4, "big", signed=True)
    if not mask:
        raise CannotLevel("no class has the experience for its next level")
    classes = len(_curse_held(rec))
    old_magic = rec[_CU_LEVELS + _CU_MAGIC_USER]
    trained = tuple(CURSE_SLOTS[slot] for slot in _curse_held(rec)
                    if _CU_READY_BIT[slot] & mask)
    _curse_raise(rec, mask)
    curse_recompute(rec, items)
    learned = None
    if (_s8(rec[_CU_LEVELS + _CU_MAGIC_USER]) > _s8(old_magic)
            or _s8(rec[_CU_LEVELS + _CU_RANGER]) > 8):
        offers = curse_offers(rec)
        if offers:
            if learn is None:
                raise NeedsSpell(offers)
            if learn not in offers:
                raise CannotLevel(f"spell {learn} is not on the trainer's menu")
            rec[_CU_SPELLBOOK + learn] = 1
            learned = learn
    if _s8(rec[_CU_LEVEL]) > _s8(rec[_CU_FORMER_LEVEL]):
        die = _curse_dice(rec, mask, rng)
        rolled = int(die / classes) or 1
        rec[_CU_HP_ROLLED] = (rec[_CU_HP_ROLLED] + rolled) & 0xFF
        gained = max(int((die + _curse_bonus(rec)) / classes), 1)
        damage = (rec[_CU_HP_MAX] - rec[_CU_HP_CURRENT]) & 0xFF
        rec[_CU_HP_MAX] = (rec[_CU_HP_MAX] + gained) & 0xFF
        rec[_CU_HP_CURRENT] = (rec[_CU_HP_MAX] - damage) & 0xFF
    return Plan(CURSE, trained, _s32(rec, _CU_EXPERIENCE),
                writes_between(raw, rec), learned)


# --- Secret of the Silver Blades ---------------------------------------------
#
# The trainer `0xDF3E` of `/Secret` (sha256 `ba6c8b5ed94b`), its recompute
# `0x3C802` (capacity `0x3C478`, cleric `0x3CA68`, saves `0x3CB8A`, thief
# skills `0x3CE78`), hit points `0xB8C4` and bonus `0x17A1C`; `docs/124`
# §1.23.
# Record offsets are the 340-byte Amiga record's (`SILVER_BLADES_DELTAS`).
# The Hall of Training trains every ready class, so a press does too.
#
# **The thief-skill step `0x3CE78` is not copied**: it reads its tables off by
# one and past the dexterity table (`docs/124` §1.23), so the skills come from
# `levels.ad_d_thief_skills` instead.

SILVER_BLADES = "secret-of-the-silver-blades"

SSB_SLOTS = ("cleric", "druid", "fighter", "paladin", "ranger", "magic-user",
             "thief")
_SB_CLERIC, _SB_PALADIN, _SB_RANGER, _SB_MAGIC_USER, _SB_THIEF = 0, 3, 4, 5, 6

_SB_STRENGTH = 0x011
_SB_INTELLIGENCE = 0x013
_SB_WISDOM = 0x015
_SB_CONSTITUTION = 0x019
_SB_THAC0 = 0x06A
_SB_RACE = 0x06B
_SB_HUMAN = 6
_SB_HP_MAX = 0x070
_SB_SPELLBOOK = 0x071                       # fifteen bytes, id - 1 a bit
_SB_SAVES = 0x082
_SB_LEVEL = 0x088
_SB_FORMER_LEVEL = 0x089
_SB_DRAINED = 0x08A
_SB_HP_LOST = 0x08B
_SB_LEVELS = 0x0AC
_SB_FORMER = 0x0B3                          # seven bytes; the eighth is the sex
_SB_SEX = 0x0BA
_SB_ATTACKS = 0x0BC
_SB_EXPERIENCE = 0x0C8
_SB_CLASS_BITS = 0x0CC
_SB_HP_ROLLED = 0x0CD
_SB_CAPACITY = 0x0CE                        # cleric, druid, unread, magic-user
_SB_CAPACITY_BYTES = 28
_SB_STATUS = 0x143
_SB_HP_CURRENT = 0x152
_SB_DEXTERITY = 0x017
_SB_THIEF_SKILLS = 0x08D                    # eight bytes
#: `g1F48` (words): each slot's bit in the ready mask.
_SB_READY_BIT = (2, 2, 8, 16, 32, 1, 4)
#: `g1F3A` (words): each slot's bit in the class mask at `0x0CC`.
_SB_CLASS_BIT = (2, 16, 8, 64, 64, 1, 4)
#: `0xB8C4`: below `g1F68` a class rolls `g0FAA` dice at level 1 (two for a
#: cleric or ranger) and one after, of `g0FB1` sides, twice keeping the
#: higher; at or past it the total is replaced by a flat number.
_SB_ROLL_BELOW = (10, 15, 10, 10, 11, 12, 11)
_SB_FIRST_DICE = (2, 1, 1, 1, 2, 1, 1)
_SB_SIDES = (8, 8, 10, 10, 8, 4, 6)
_SB_FLAT = (2, None, 3, 3, 2, 1, 2)
#: `g195C[7 * 95 + sex * 5]`, past the save table (`_ssb_saves`).
_SB_PAST_TABLE_SAVES = ((1, 1, 2, 3, 4), (5, 6, 7, 8, 0))
_SB_TABLES = levels.SECRET_OF_THE_SILVER_BLADES
#: `g1312`: where the Amiga's thresholds are not the C64's.
_SB_THRESHOLDS = {("ranger", 2): 2251, ("fighter", 11): 750001,
                  ("paladin", 15): 2460001}
#: `g1C63[level * 12 + 1..11]`: the trainer's magic-user list by spell
#: level, in menu order, up to its first 0.
_SB_MENU = {1: (9, 10, 13, 16, 17, 19, 20, 14, 15, 12),
            2: (29, 30, 31, 32, 33, 34, 35),
            3: (45, 46, 48, 49, 50, 51, 52, 53, 54, 55, 47),
            4: (81, 82, 83, 84, 85, 86, 87, 88, 89, 100),
            5: (91, 92, 93, 94),
            6: (111, 112, 113, 114, 110),
            7: (115, 116, 117)}
_SB_LAST_SPELL = 117


def _ssb_spell_table() -> dict[int, tuple[int, int]]:
    """`g2704`, ids 1-117: class 0 cleric, 1 druid, 3 magic-user, at
    `goldbox.spells`' levels; the one id the Amiga adds is 108, a druid
    spell of level 9."""
    cls = {"cleric": 0, "druid": 1, "magic-user": 3}
    out = {}
    for first, last, who, level in spells.SECRET_OF_THE_SILVER_BLADES.groups:
        for spell in range(first, last + 1):
            out[spell] = (cls[who], level)
    out[108] = (1, 9)
    return out


_SB_SPELLS = _ssb_spell_table()
_SB_SLOT_ROWS = spells._SLOTS[spells.SECRET_OF_THE_SILVER_BLADES.key]


def ssb_threshold(slot: int, level: int) -> int:
    """`g1312[slot * 228 + level * 4]`; -1 or 0 past a ceiling."""
    name = SSB_SLOTS[slot]
    if (name, level) in _SB_THRESHOLDS:
        return _SB_THRESHOLDS[(name, level)]
    row = _SB_TABLES.at_level(name, level)
    return row.experience if row is not None and level >= 2 else -1


def ssb_regained(rec) -> bool:
    """`0x3D5D0`: a human (`0x06B == 6`) whose first held class level (slots
    0-5, else the thief's) is above `0x089`, signed."""
    if rec[_SB_RACE] != _SB_HUMAN:
        first = 0
    else:
        slot = 0
        while slot < 6 and rec[_SB_LEVELS + slot] == 0:
            slot += 1
        first = rec[_SB_LEVELS + slot]
    return _s8(first) > _s8(rec[_SB_FORMER_LEVEL])


def _ssb_held(rec) -> list[int]:
    return [slot for slot in range(len(SSB_SLOTS))
            if _s8(rec[_SB_LEVELS + slot]) > 0]


def _ssb_race_blocked(rec, slot: int, level: int) -> bool:
    """`0xDFDE`-`0xE164`, by race (1 elf, 2 half-elf, 3 dwarf, 4 gnome,
    5 halfling); the fighter and magic-user limits test the level for
    equality, the elf's and gnome's cleric limit for 7 and above."""
    race = rec[_SB_RACE]
    strength = rec[_SB_STRENGTH]
    intelligence = rec[_SB_INTELLIGENCE]
    name = SSB_SLOTS[slot]

    def banded(score, low, mid, high):
        return (level == high or (level == mid and score == 17)
                or (level == low and score < 17))

    if race == 1:
        return ((name == "fighter" and banded(strength, 5, 6, 7))
                or (name == "magic-user"
                    and (level == 11 or (level == 9 and intelligence < 17)
                         or (level == 10 and intelligence == 17)))
                or (name == "cleric" and level >= 7))
    if race == 2:
        if name == "cleric":
            return level == 5
        return ((name in ("fighter", "ranger") and banded(strength, 6, 7, 8))
                or (name == "magic-user" and banded(intelligence, 6, 7, 8)))
    if race == 3:
        return name == "fighter" and banded(strength, 7, 8, 9)
    if race == 4:
        return ((name == "fighter" and (level == 6
                                        or (level == 5 and strength < 18)))
                or (name == "cleric" and level >= 7))
    if race == 5:
        return name == "fighter" and banded(strength, 4, 5, 6)
    return False


def _ssb_ready(rec) -> tuple[int, int]:
    """`0xDF90`-`0xE3D0`: the ready mask (every ready class trains) and the
    clamp, which, unlike Pool's and Curse's, takes no account of experience:
    the largest of a ready class's threshold two up and an unready,
    unblocked class's next threshold, less one, and the threshold two up of
    the ready class whose next one is largest."""
    experience = _s32(rec, _SB_EXPERIENCE)
    mask, clamp = 0, 0
    for slot in _ssb_held(rec):
        level = rec[_SB_LEVELS + slot]
        blocked = _ssb_race_blocked(rec, slot, level)
        want = ssb_threshold(slot, level + 1)
        if not blocked and want <= experience and want > 0:
            mask |= _SB_READY_BIT[slot]
            two_up = ssb_threshold(slot, level + 2)
            if two_up > 0 and two_up > clamp:
                clamp = two_up - 1
        elif not blocked and not mask & _SB_READY_BIT[slot]:
            if want > 0 and want > clamp:
                clamp = want - 1
    best, best_want = None, 0
    for slot in range(len(SSB_SLOTS)):
        if not mask & _SB_READY_BIT[slot]:
            continue
        want = ssb_threshold(slot, rec[_SB_LEVELS + slot] + 1)
        if want > best_want:
            best, best_want = slot, want
    if best is not None:
        two_up = ssb_threshold(best, rec[_SB_LEVELS + best] + 2)
        if two_up > 0 and two_up > clamp:
            clamp = two_up - 1
    return mask, clamp


def _ssb_thac0(slot: int, level: int) -> int:
    """`g1E30[slot * 19 + level]` (words), stored `60 - THAC0`."""
    name = SSB_SLOTS[slot]
    if level == 0:
        return 60 - dict(_SB_TABLES.dos_thac0_level0)[name]
    return 60 - _SB_TABLES.dos_thac0_at(name, level)


def _ssb_save_row(slot: int, level: int) -> tuple[int, ...]:
    """`g195C[slot * 95 + level * 5]`: the class rows with the DOS paladin
    cells."""
    name = SSB_SLOTS[slot]
    row = dict(_SB_TABLES.dos_save_overrides).get((name, level))
    if row is None:
        entry = _SB_TABLES.at_level(name, level)
        if entry is None:
            raise CannotLevel(f"no save row is copied for {name} level {level}")
        row = entry.saves
    return row


def _ssb_has_spell(rec, spell: int) -> bool:
    return bool(rec[_SB_SPELLBOOK + (spell - 1) // 8] & (1 << ((spell - 1) % 8)))


def _ssb_learn(rec: bytearray, spell: int) -> None:
    rec[_SB_SPELLBOOK + (spell - 1) // 8] |= 1 << ((spell - 1) % 8)


def _ssb_capacity(rec: bytearray, items) -> None:
    """`0x3C478`: capacity from zero, slot by slot, at the former level when
    `ssb_regained` holds and there is one.

    The cleric's routine `0x3CA68` builds its own rows (`g135E`, from 1 at
    level 1) at the cleric's level plus a regained former one, adds the
    wisdom bonus at levels 1, 1, 2, 2, 3, 4 above 12-17 where a slot already
    is, and clears level 6 below wisdom 17 and level 7 below 18; every cleric
    spell with a slot is then granted. A paladin above 8 adds `g160A` and
    grants the same way; a ranger above 7 adds `g16EE` columns 1-3 to the
    druid's and 4-5 to the magic-user's levels 1-2, and grants every druid
    spell with a druid slot and magic-user spell with a magic-user slot; a
    magic-user adds `g17D2`, and intelligence below 12 and 14 clears levels
    6 and 7 (`0x3C452`). The sums are `goldbox.spells`' rows. Last, each
    readied item of power `0x81` doubles magic-user level 5.
    """
    for i in range(_SB_CAPACITY_BYTES):
        rec[_SB_CAPACITY + i] = 0

    def at(array, level):
        return _SB_CAPACITY + array * 7 + level - 1

    def add(array, level, value):
        rec[at(array, level)] = (rec[at(array, level)] + value) & 0xFF

    def grant(test):
        for spell in range(1, _SB_LAST_SPELL + 1):
            who, level = _SB_SPELLS.get(spell, (4, 0))
            if test(who, level):
                _ssb_learn(rec, spell)

    def slot_at(array, level):
        # `0x0CD + level` and the like: level 0 reads the byte before.
        return rec[at(array, level)] > 0

    regained = ssb_regained(rec)
    for slot in range(8):
        if slot >= len(SSB_SLOTS):
            continue                # slot 7 reads the former cleric level; no branch
        former = rec[_SB_FORMER + slot]
        level = _s8(former if regained and former else rec[_SB_LEVELS + slot])
        if level <= 0:
            continue
        if slot == _SB_CLERIC:
            _ssb_cleric(rec)
            grant(lambda who, lv: who == 0 and slot_at(0, lv))
        elif slot == _SB_PALADIN and level > 8:
            for column, value in enumerate(_row(_SB_SLOT_ROWS["paladin"], "paladin", level)):
                add(0, column + 1, value)
            grant(lambda who, lv: who == 0 and slot_at(0, lv))
        elif slot == _SB_RANGER and level > 7:
            to_druid, to_mage = _row(_SB_SLOT_ROWS["ranger"], "ranger", level)
            for column in range(7):
                add(1, column + 1, to_druid[column])
                add(3, column + 1, to_mage[column])
            grant(lambda who, lv: (who == 1 and slot_at(1, lv))
                  or (who == 3 and slot_at(3, lv)))
        elif slot == _SB_MAGIC_USER:
            for column, value in enumerate(_row(_SB_SLOT_ROWS["magic-user"], "magic-user", level)):
                add(3, column + 1, value)
            if rec[_SB_INTELLIGENCE] < 12:
                rec[at(3, 6)] = 0
            if rec[_SB_INTELLIGENCE] < 14:
                rec[at(3, 7)] = 0
    for node in items:
        if len(node) > 0x41 and node[0x41] == 0x81 and node[0x35]:
            add(3, 5, rec[at(3, 5)])


def _ssb_cleric(rec: bytearray) -> None:
    """`0x3CA68`: the cleric's slots at its level plus a regained former
    level, then the wisdom bonus and ceilings."""
    level = rec[_SB_LEVELS] + (rec[_SB_FORMER] if ssb_regained(rec) else 0)
    level = _s8(level & 0xFF)
    if level <= 0:
        return
    for column, value in enumerate(_row(_SB_SLOT_ROWS["cleric"], "cleric", level)):
        rec[_SB_CAPACITY + column] = value
    wisdom = rec[_SB_WISDOM]
    for above, spell_level in ((12, 1), (13, 1), (14, 2), (15, 2), (16, 3),
                               (17, 4)):
        here = _SB_CAPACITY + spell_level - 1
        if wisdom > above and rec[here] > 0:
            rec[here] = (rec[here] + 1) & 0xFF
    if wisdom < 17:
        rec[_SB_CAPACITY + 5] = 0
    if wisdom < 18:
        rec[_SB_CAPACITY + 6] = 0


def _ssb_saves(rec: bytearray, items) -> None:
    """`0x3CB8A`: each column from 20, lowered over held slots; then the
    compare one slot past the class array, which reads the former cleric
    level against the sex byte and, if larger, lowers the columns to a cell
    past the table (CONFIRMED live: a male human who left cleric saves
    1 1 2 3 4, `9f0896c0`); then column 0's constitution steps: the
    racial-table one only for a readied item of power kind 6 (no race
    test), and the high one for everyone."""
    kind_six = readied_power(items, 6)
    for column in range(5):
        value = 20
        for slot in _ssb_held(rec):
            cell = _ssb_save_row(slot, rec[_SB_LEVELS + slot])[column]
            if cell < value:
                value = cell
        if _s8(rec[_SB_FORMER]) > _s8(rec[_SB_SEX]):
            cell = _SB_PAST_TABLE_SAVES[rec[_SB_SEX]][column]
            if cell < value:
                value = cell
        if column == 0:
            constitution = rec[_SB_CONSTITUTION]
            if kind_six:
                value += levels._dos_con_save_racial_step(constitution)
            value += levels._dos_con_save_high_step(constitution)
        rec[_SB_SAVES + column] = value & 0xFF


def _ssb_thief_skills(rec: bytearray) -> None:
    """The eight thief skills at the thief level (plus a regained former
    one), by `levels.ad_d_thief_skills`."""
    level = _s8((int(ssb_regained(rec)) * _s8(rec[_SB_FORMER + _SB_THIEF])
                 + _s8(rec[_SB_LEVELS + _SB_THIEF])) & 0xFF)
    skills = levels.ad_d_thief_skills(level, rec[_SB_RACE], SILVER_BLADES,
                                      rec[_SB_DEXTERITY])
    if skills is None:
        raise CannotLevel("a thief with no dexterity has no thief-skill row")
    rec[_SB_THIEF_SKILLS:_SB_THIEF_SKILLS + 8] = bytes(skills)


def ssb_recompute(rec: bytearray, items=()) -> None:
    """`0x3C802`: THAC0 over all seven slots with level 0 included, the
    level byte, `attack_forms[0]` (3 above fighter or paladin 6 and 4 above
    12; the ranger 7 and 14), capacity, saves, thief skills for a thief
    level, the class mask, and a regained class's attacks and THAC0."""
    rec[_SB_THAC0] = 0
    for slot in range(len(SSB_SLOTS)):
        level = rec[_SB_LEVELS + slot]
        value = _ssb_thac0(slot, level)
        if value > rec[_SB_THAC0]:
            rec[_SB_THAC0] = value
        if _s8(rec[_SB_LEVEL]) < _s8(level):
            rec[_SB_LEVEL] = level
        if slot in (2, 3):
            if _s8(level) > 6:
                rec[_SB_ATTACKS] = 3
            if _s8(level) > 12:
                rec[_SB_ATTACKS] = 4
        elif slot == _SB_RANGER:
            if _s8(level) > 7:
                rec[_SB_ATTACKS] = 3
            if _s8(level) > 14:
                rec[_SB_ATTACKS] = 4
    _ssb_capacity(rec, items)
    _ssb_saves(rec, items)
    if _s8(rec[_SB_LEVELS + _SB_THIEF]) > 0:
        _ssb_thief_skills(rec)
    bits = 0
    for slot in range(len(SSB_SLOTS)):
        former = _s8(rec[_SB_FORMER + slot])
        if (_s8(rec[_SB_LEVELS + slot]) > 0
                or 0 < former < _s8(rec[_SB_LEVEL])):
            bits = (bits + _SB_CLASS_BIT[slot]) & 0xFF
    rec[_SB_CLASS_BITS] = bits
    # `0x3C938` would unready an item whose class mask no longer matches;
    # training only adds bits, so a level-up never reaches it.
    if ssb_regained(rec):
        for slot in range(len(SSB_SLOTS)):
            former = _s8(rec[_SB_FORMER + slot])
            if slot in (2, 3):
                if former > 13:
                    rec[_SB_ATTACKS] = 4
                elif former > 7:
                    rec[_SB_ATTACKS] = 3
            elif slot == _SB_RANGER:
                # `0x3C9F2` writes 4 above 15 and then 3 above 8, so a
                # regained ranger above 15 ends at 3.
                if former > 15:
                    rec[_SB_ATTACKS] = 4
                if former > 8:
                    rec[_SB_ATTACKS] = 3
            value = _ssb_thac0(slot, rec[_SB_FORMER + slot])
            if value > rec[_SB_THAC0]:
                rec[_SB_THAC0] = value


def ssb_offers(rec) -> list[int]:
    """The trainer's menu (`0x32F8E` mode 4): for each spell level with a
    magic-user slot, the ids of `_SB_MENU` the book does not hold."""
    out = []
    for level, ids in _SB_MENU.items():
        if rec[_SB_CAPACITY + 21 + level - 1] > 0:
            out += [spell for spell in ids if not _ssb_has_spell(rec, spell)]
    return out


def _ssb_check(rec) -> None:
    if rec[_SB_STATUS] != 0:
        raise CannotLevel("the trainer only trains conscious characters")
    for slot in _ssb_held(rec):
        if SSB_SLOTS[slot] == "druid":
            raise CannotLevel(_NOT_COPIED.format("druid"))
    if (_s8(rec[_SB_FORMER]) > _s8(rec[_SB_SEX])
            and rec[_SB_SEX] >= len(_SB_PAST_TABLE_SAVES)):
        raise CannotLevel("a sex byte past 1 reads further past the save table")
    if not 3 <= rec[_SB_CONSTITUTION] <= 25:
        raise CannotLevel("a constitution outside 3-25 reads past the "
                          "hit-point bonus table")


def _ssb_bonus(rec, slot: int) -> int:
    """`0x17A1C(record, slot)`: `g12F8[constitution]` and, for the fighter,
    paladin and ranger slots, +1 to +5 from 17."""
    constitution = rec[_SB_CONSTITUTION]
    value = levels._HP_BONUS_POD[min(constitution, 16)]
    if slot in (2, 3, 4) and constitution >= 17:
        value += levels._HP_BONUS_POD[constitution] - levels._HP_BONUS_POD[16]
    return value


def _ssb_hit_points(rec: bytearray, classes: int, rng) -> None:
    """`0xB8C4(record, mask, classes)`. **Every class held rolls**, not only
    the trained ones: the mask is tested for being non-zero and never ANDed
    with a class's bit (CONFIRMED live, `9f0896c0`). The rest is Pools of
    Darkness' rule: a byte of rolls and of `dice * bonus`, both divided by
    the class count, the rolls raised to 1, and the damage kept."""
    rolled, bonus = 0, 0
    for slot in _ssb_held(rec):
        level = rec[_SB_LEVELS + slot]
        if level < _SB_ROLL_BELOW[slot]:
            dice = 1 if level > 1 else _SB_FIRST_DICE[slot]
            roll = max(_dice(rng, dice, _SB_SIDES[slot]),
                       _dice(rng, dice, _SB_SIDES[slot])) & 0xFF
            rolled = (rolled + roll) & 0xFF
            bonus = (bonus + dice * _ssb_bonus(rec, slot)) & 0xFF
        elif _SB_FLAT[slot] is not None:
            rolled = _SB_FLAT[slot]
    rolled = max(rolled // classes, 1)
    bonus = (bonus // classes) & 0xFF
    damage = (rec[_SB_HP_MAX] - rec[_SB_HP_CURRENT]) & 0xFF
    rec[_SB_HP_ROLLED] = (rec[_SB_HP_ROLLED] + rolled) & 0xFF
    rec[_SB_HP_MAX] = (rec[_SB_HP_MAX] + bonus + rolled) & 0xFF
    rec[_SB_HP_CURRENT] = (rec[_SB_HP_MAX] - damage) & 0xFF


#: `0xE732`: the effects added when `ssb_regained` holds, through the
#: constructor `0x12DAC`: 0x69 for a former ranger (`tst.b $B7` then `ble`,
#: signed) and then 8 for a former paladin (`$B6`), each only if the
#: character lacks it (`0x1AB12`).
_SB_REGAINED_EFFECTS = ((_SB_FORMER + _SB_RANGER, 0x69),
                        (_SB_FORMER + _SB_PALADIN, 8))


def _ssb_ready_slots(rec) -> list[int]:
    mask, _ = _ssb_ready(rec)
    return [slot for slot in _ssb_held(rec) if _SB_READY_BIT[slot] & mask]


def _ssb_plan(raw: bytes, rng, learn: int | None, effects, items=()) -> Plan:
    rec = bytearray(raw)
    _ssb_check(rec)
    mask, clamp = _ssb_ready(rec)
    if clamp > 0 and clamp < _s32(rec, _SB_EXPERIENCE):
        rec[_SB_EXPERIENCE:_SB_EXPERIENCE + 4] = clamp.to_bytes(4, "big", signed=True)
    if not mask:
        raise CannotLevel("no class has the experience for its next level")
    held = _ssb_held(rec)
    old_magic = rec[_SB_LEVELS + _SB_MAGIC_USER]
    rec[_SB_CLASS_BITS] = 0
    trained = []
    for slot in held:
        if not _SB_READY_BIT[slot] & mask:
            continue
        trained.append(SSB_SLOTS[slot])
        rec[_SB_LEVELS + slot] = (rec[_SB_LEVELS + slot] + 1) & 0xFF
        drained = rec[_SB_DRAINED]
        if drained > 0:
            lost = rec[_SB_HP_LOST]
            rec[_SB_HP_LOST] = (lost - lost // drained) & 0xFF
            rec[_SB_DRAINED] = drained - 1
    ssb_recompute(rec, items)
    learned = None
    if (_s8(rec[_SB_LEVELS + _SB_MAGIC_USER]) > _s8(old_magic)
            or _s8(rec[_SB_LEVELS + _SB_RANGER]) > 8):
        offers = ssb_offers(rec)
        if offers:
            if learn is None:
                raise NeedsSpell(offers)
            if learn not in offers:
                raise CannotLevel(f"spell {learn} is not on the trainer's menu")
            _ssb_learn(rec, learn)
            learned = learn
    added = (_regained_effects(rec, _SB_REGAINED_EFFECTS, effects, True)
             if ssb_regained(rec) else ())
    if _s8(rec[_SB_LEVEL]) > _s8(rec[_SB_FORMER_LEVEL]):
        _ssb_hit_points(rec, len(held), rng)
    return Plan(SILVER_BLADES, tuple(trained), _s32(rec, _SB_EXPERIENCE),
                writes_between(raw, rec), learned, added)


# --- every title -------------------------------------------------------------

_PLANNERS = {POOLS_OF_DARKNESS: _pod_plan, POOL_OF_RADIANCE: _por_plan,
             CURSE: _curse_plan, SILVER_BLADES: _ssb_plan}


def supported(key: str) -> bool:
    """Whether this module copies the trainer of the title `key` names."""
    return key in _PLANNERS


def plan(raw: bytes, key: str, *, rng=None, learn: int | None = None,
         effects=(), items=()) -> Plan:
    """What one press of Level up writes into the heap record `raw`.

    `key` is the `automap.amiga.MACHINES` key. `learn` is the spell a
    magic-user picks from `offers`; `effects` the bytes of each of the
    character's effect nodes (or bare effect ids), which the trainer looks
    through before it adds one; `items` the bytes of each of its item nodes,
    in list order, which the recomputes read; `rng` anything with `randint`. `plan_member` takes all of these but the
    dice and the spell from a live party member. Raises `CannotLevel`, and
    `NeedsSpell` when the trainer's menu wants a pick `learn` did not give.
    """
    planner = _PLANNERS.get(key)
    if planner is None:
        raise CannotLevel(f"no Amiga trainer is copied for {key}")
    return planner(bytes(raw), rng or random, learn, tuple(effects or ()),
                   tuple(items))


def plan_member(member, key: str, *, rng=None, learn: int | None = None) -> Plan:
    """`plan` for an `automap.amigaparty.AmigaMember`: its record, its item
    nodes and its effect nodes as the party list holds them."""
    return plan(member.raw, key, rng=rng, learn=learn,
                effects=[node.raw for node in member.effect_nodes],
                items=[node.raw for node in member.item_nodes])


#: Per title: the record offsets `summary` reads, as (class levels, former
#: class levels or None, experience, level, former level or None, hit points
#: current, hit points maximum).
_SUMMARY = {
    POOLS_OF_DARKNESS: (_POD_LEVELS, _POD_FORMER, _POD_EXPERIENCE, _POD_LEVEL,
                        _POD_FORMER_LEVEL, _POD_HP_CURRENT, _POD_HP_MAX),
    POOL_OF_RADIANCE: (_POR_LEVELS, None, _POR_EXPERIENCE, _POR_LEVEL, None,
                       _POR_HP_CURRENT, _POR_HP_MAX),
    CURSE: (_CU_LEVELS, _CU_FORMER, _CU_EXPERIENCE, _CU_LEVEL,
            _CU_FORMER_LEVEL, _CU_HP_CURRENT, _CU_HP_MAX),
    SILVER_BLADES: (_SB_LEVELS, _SB_FORMER, _SB_EXPERIENCE, _SB_LEVEL,
                    _SB_FORMER_LEVEL, _SB_HP_CURRENT, _SB_HP_MAX),
}


def summary(raw: bytes, key: str) -> dict:
    """What a record holds that Level up reads and writes, by name: the
    class levels and former class levels in slot order, experience, the level
    and former level bytes, and hit points."""
    if key not in _SUMMARY:
        raise CannotLevel(f"no Amiga trainer is copied for {key}")
    levels_at, former_at, xp, level, former_level, hp, hp_max = _SUMMARY[key]
    slots = len({POOLS_OF_DARKNESS: POD_SLOTS, POOL_OF_RADIANCE: POR_SLOTS,
                 CURSE: CURSE_SLOTS, SILVER_BLADES: SSB_SLOTS}[key])
    return {"levels": list(raw[levels_at:levels_at + slots]),
            "former": (None if former_at is None
                       else list(raw[former_at:former_at + slots])),
            "experience": _s32(raw, xp), "level": raw[level],
            "former_level": None if former_level is None else raw[former_level],
            "hp": [raw[hp], raw[hp_max]]}


def _not_on_the_chain(target, key: str, address: int, wanted):
    """`wanted` without the effects whose id is already on the record's live
    effect list, so a plan read before another press cannot add a duplicate."""
    if not wanted:
        return ()
    row = amigaparty.ROWS.get(key)
    if row is None:
        return tuple(wanted)
    head = int.from_bytes(bytes(target.read(address + row.effects.head, 4)),
                          "big")
    try:
        nodes = amigaparty.chain(target, head, row.effects.link,
                                 row.effects.size, "the effect list")
    except amigaparty.PartyError as exc:
        raise CannotLevel(str(exc)) from exc
    have = {node.raw[0] for node in nodes}
    return tuple(e for e in wanted if e.id not in have)


class WriteLog:
    """A target that lists each write it has made, so a press that fails
    part-way can say what it changed in the running game."""

    def __init__(self, target):
        self._target = target
        self.made: list[tuple[int, bytes]] = []

    def write(self, at, data):
        result = self._target.write(at, data)
        self.made.append((at, bytes(data)))
        return result

    def __getattr__(self, name):
        return getattr(self._target, name)


def write_plan(target, member, plan_: Plan) -> tuple[tuple[int, bytes], ...]:
    """Make `plan_` in the running game for `member`, the
    `automap.amigaparty.AmigaMember` it was planned from, and return the
    `(address, bytes)` writes in the order they were made.

    The trainer's new effect nodes go first, through `amigaeffects`, then the
    record's bytes. Raises `CannotLevel`, having written nothing, when a byte
    the plan replaces no longer holds what `member` read, or when the effect
    pool or list does not read as the game keeps them.
    """
    address = member.address
    for offset, data in plan_.writes:
        live = bytes(target.read(address + offset, len(data)))
        if live != bytes(member.raw[offset:offset + len(data)]):
            raise CannotLevel("the record changed after it was read")
    try:
        added = amigaeffects.writes(
            target, plan_.key, address,
            _not_on_the_chain(target, plan_.key, address, plan_.added_effects))
    except amigaeffects.EffectError as exc:
        raise CannotLevel(str(exc)) from exc
    made = added + tuple((address + offset, data)
                         for offset, data in plan_.writes)
    for at, data in made:
        target.write(at, data)
    return made


_READY = {POOLS_OF_DARKNESS: (lambda rec: _pod_ready_slots(rec), POD_SLOTS),
          POOL_OF_RADIANCE: (lambda rec: _por_ready_slots(rec), POR_SLOTS),
          CURSE: (lambda rec: _curse_ready_slots(rec), CURSE_SLOTS),
          SILVER_BLADES: (lambda rec: _ssb_ready_slots(rec), SSB_SLOTS)}


def ready_classes(raw: bytes, key: str) -> tuple[str, ...]:
    """The classes a press would raise, in slot order; empty if none. Says
    nothing about whether `plan` would then stop."""
    if key not in _READY:
        raise CannotLevel(f"no Amiga trainer is copied for {key}")
    slots, names = _READY[key]
    return tuple(names[slot] for slot in slots(bytes(raw)))


def offers(raw: bytes, key: str, items=(), effects=()) -> list[int]:
    """The spell ids the trainer's menu offers on this press; empty when it
    asks for none or `plan` stops. No die is rolled for the answer."""
    try:
        plan(raw, key, rng=random.Random(0), items=items, effects=effects)
    except NeedsSpell as asked:
        return asked.offers
    except CannotLevel:
        return []
    return []
