"""The Pools of Darkness record recompute, copied from the Amiga executable.

`0x3C238` of `/Pools of Darkness` rebuilds THAC0, saves, attacks, spell
capacity, thief skills and the class mask from the class levels. Only training
calls it on the Amiga; the load copies the stored THAC0 byte as it finds it
(`docs/124-amiga-port.md` §2.4). `automap/amigalevelup.py` runs it for Level
up and `editor/saveplan.py` for a saved class-level edit. Record offsets are
the `.pc` file's (`goldbox/amiga_pod.py`).
"""

from __future__ import annotations

from goldbox import amiga_pod, levels, spells


class RecomputeError(ValueError):
    """The recompute would read past a table the game has, so no rebuild is copied."""


def _s8(value: int) -> int:
    return value - 256 if value > 127 else value


def _row(rows, name: str, level: int, error=RecomputeError):
    """`goldbox.spells`' capacity row for a class level, or `error` for a
    level past the rows, which no title lets a character reach."""
    if not 1 <= level <= len(rows):
        raise error(f"{name} level {level} is past the capacity rows")
    return rows[level - 1]


#: The record's seven class slots, in the order every table here is indexed.
POD_SLOTS = ("cleric", "druid", "fighter", "paladin", "ranger", "magic-user",
             "thief")
_POD_DRUID = 1
_POD_RANGER = 4
_POD_THIEF = 6
_POD_STATUS = amiga_pod.STATUS              # must be 0: "we only train conscious people"
_POD_RACE = amiga_pod.RACE
_POD_HUMAN = 5                              # `0x3CFB2`: `cmpi.b #5, $58`
_POD_INTELLIGENCE = 0x073
_POD_WISDOM = 0x075
_POD_DEXTERITY = 0x077
_POD_CONSTITUTION = 0x079
_POD_THAC0 = 0x07F                          # stored 60 - THAC0
_POD_SAVES = 0x083                          # five bytes
_POD_LEVEL = 0x089
_POD_FORMER_LEVEL = amiga_pod.FORMER_LEVEL
_POD_THIEF_SKILLS = 0x08B                   # eight bytes
_POD_LEVELS = amiga_pod.CLASS_LEVELS
_POD_FORMER = amiga_pod.FORMER_CLASS_LEVELS
_POD_ATTACKS = amiga_pod.ATTACK_FORMS
_POD_CLASS_BITS = 0x0B7
_POD_SPELLBOOK = 0x159                      # sixteen bytes, id - 1 a bit
_POD_CAPACITY = 0x169                       # cleric 9, druid 9, magic-user 9
#: `g1E7A`: the bit a slot adds to the class mask at `0x0B7`.
_POD_CLASS_BIT = (2, 16, 8, 64, 64, 1, 4)


def _pod_thac0_rows() -> tuple[tuple[int, ...], ...]:
    """`g1DE0`, 22 entries a slot, stored `60 - THAC0`: level 0, then levels
    1-21 out of `levels._DOS_THAC0_POD`, which the Amiga's rows equal 126 of
    126 cells. The druid has no row past level 0; `plan` stops on a druid level."""
    zero = dict(levels._DOS_THAC0_LEVEL0_POD)
    rows = dict(levels._DOS_THAC0_POD)
    out = []
    for name in POD_SLOTS:
        row = [60 - zero[name]]
        row += [60 - t for t in rows.get(name, (zero[name],) * 21)]
        out.append(tuple(row))
    return tuple(out)


_POD_THAC0_ROWS = _pod_thac0_rows()
_POD_TABLE_CLAMP = levels.POD_TABLE_CLAMP


def _pod_save_cell(slot: int, level: int,
                   dos_saves: bool = False) -> tuple[int, ...]:
    """`g189E[slot * 110 + min(level, 21) * 5 + column]`.

    **The thief's slot is all zeros, and the druid's holds the thief's row**,
    so any thief level saves at 0 on all five columns (`99d7ea58`, CONFIRMED
    from the code and in 16 of 16 saved thief records on the player's disk 3). The other five
    rows are `levels._SAVES_POD`, 105 of 105. The DOS load runs the same
    routine with the thief's real row, so `dos_saves` reads that instead.
    """
    name = POD_SLOTS[slot]
    if name == "thief" and not dos_saves:
        return (0, 0, 0, 0, 0)
    if name == "druid":
        name = "thief"
    return levels._band(levels._SAVES_POD[name], min(level, _POD_TABLE_CLAMP))


def _pod_high_constitution(constitution: int) -> int:
    """`0x3C5AC`'s second step on the first save, for everyone: +1 at 19-20,
    +2 at 21-22, +3 at 23-24, +4 at 25 (`levels._dos_con_save_high_step`)."""
    return levels._dos_con_save_high_step(constitution)


#: `g1EAC`, rows by thief level 1-18: Silver Blades' rows 1-14, its rows 15-17
#: with climb walls 100 where Silver Blades has 99, and an eighteenth.
_POD_THIEF_BASE = (levels._THIEF_SKILLS_SSB[:14]
                   + tuple(row[:6] + (100,) + row[7:]
                           for row in levels._THIEF_SKILLS_SSB[14:17])
                   + ((130, 99, 99, 99, 99, 55, 100, 85),))
#: `g1F3C[race * 8]`: AD&D's rows in this title's race order, and **the human's
#: row is the half-orc's** (`99d7ea58`, CONFIRMED: human thieves at 20, 29 and
#: 37 match only with it). Reordered out of DOS Pool of Radiance's rows, which
#: are the same numbers.
_POD_THIEF_RACE = tuple(levels._DOS_THIEF_SKILL_RACE_POOL[i]
                        for i in (1, 3, 0, 2, 4, 5))
#: `g1F6C[(dexterity - 9) * 5]`, dexterity 9-19: DOS Pool of Radiance's rows,
#: dexterity 10's -19 and 16's -5 included. A dexterity outside reads other
#: tables' bytes, so `plan` stops there.
_POD_THIEF_DEX = levels._DOS_THIEF_SKILL_DEX_POOL
_POD_THIEF_DEX_FROM = 9
_POD_THIEF_ROW_CAP = 18


#: `g2726`: each spell id's casting class (0 cleric, 1 druid, 2 magic-user)
#: and level, ids 1-126; `goldbox.spells` reads the same table off DOS.
def _pod_spell_table() -> dict[int, tuple[int, int]]:
    cls = {"cleric": 0, "druid": 1, "magic-user": 2}
    out = {}
    for first, last, who, level in spells.POOLS_OF_DARKNESS.groups:
        for spell in range(first, last + 1):
            out[spell] = (cls[who], level)
    return out


_POD_SPELLS = _pod_spell_table()
_POD_LAST_SPELL = 126
_POD_SLOT_ROWS = spells._SLOTS[spells.POOLS_OF_DARKNESS.key]
#: `0x3BE7C` and `0x3C48A` clamp a class level at 29 before reading a row.
_POD_SLOT_CLAMP = 29


def _pod_learn(rec: bytearray, spell: int) -> None:
    rec[_POD_SPELLBOOK + (spell - 1) // 8] |= 1 << ((spell - 1) % 8)


def pod_regained(rec) -> bool:
    """`0x3D020`: a human whose first held class level is above `0x08A`.

    The compare is signed bytes. The first held class is the first non-zero
    slot of 0-5, or the thief's slot if none is.
    """
    if rec[_POD_RACE] != _POD_HUMAN:
        first = 0
    else:
        slot = 0
        while slot < 6 and rec[_POD_LEVELS + slot] == 0:
            slot += 1
        first = rec[_POD_LEVELS + slot]
    return _s8(first) > _s8(rec[_POD_FORMER_LEVEL])


def pod_effective_level(rec, slot: int) -> int:
    """`0x3D046`: the slot's level, or its former level when that is higher
    and `pod_regained` holds."""
    former = rec[_POD_FORMER + slot] if pod_regained(rec) else 0
    return max(rec[_POD_LEVELS + slot], former)


def _pod_thief_skills(rec: bytearray) -> None:
    """`0x3C7DE`: level row, race row and, on the first five, dexterity.

    A race value that is negative and larger than the level value gives 0;
    nothing is clamped after the dexterity row, at 0 or at 99.
    """
    row = _POD_THIEF_BASE[min(pod_effective_level(rec, _POD_THIEF),
                              _POD_THIEF_ROW_CAP) - 1]
    race = _POD_THIEF_RACE[_s8(rec[_POD_RACE])]
    dex = _POD_THIEF_DEX[rec[_POD_DEXTERITY] - _POD_THIEF_DEX_FROM]
    for skill in range(8):
        base, adjust = row[skill], race[skill]
        value = 0 if adjust < 0 and -adjust > base else base + adjust
        if skill < 5:
            value += dex[skill]
        rec[_POD_THIEF_SKILLS + skill] = value & 0xFF


def _pod_capacity(rec: bytearray, items=()) -> None:
    """`0x3BE7C`: spell capacity from zero, granting as it goes.

    Slot by slot: the cleric's helper `0x3C48A` *assigns* levels 1-7, adds
    one at levels 1, 1, 2, 2, 3, 4 for wisdom above 12-17 where that level
    already has one, and clears level 6 below wisdom 17 and level 7 below 18;
    a paladin above 8 adds four cleric columns; a ranger above 7 adds four
    druid columns and its columns 5-8 to magic-user levels 1-4; a magic-user
    adds nine, with intelligence below 12, 14, 16 and 18 clearing levels 6-9
    (`0x3BE3E`). Each of the cleric, the paladin and the ranger then grants
    every spell its arrays give a slot to, reading the arrays as they stand
    at that point: the ranger's magic-user spells need a druid slot too.
    Last (`0x3C20C`), each readied item node whose power byte `+0x41` is
    exactly `0x41` doubles magic-user level 5, once per such item.
    """
    cleric, druid, mage = 0, 9, 18
    for i in range(27):
        rec[_POD_CAPACITY + i] = 0

    def cap(at, level):
        return rec[_POD_CAPACITY + at + level - 1]

    def add(at, level, value):
        i = _POD_CAPACITY + at + level - 1
        rec[i] = (rec[i] + value) & 0xFF

    def grant(test):
        for spell in range(1, _POD_LAST_SPELL + 1):
            who, level = _POD_SPELLS.get(spell, (3, 0))
            if test(who, level):
                _pod_learn(rec, spell)

    for slot in range(8):
        # Slot 7 reads past the class array; no branch takes it.
        if slot >= len(POD_SLOTS):
            continue
        level = min(pod_effective_level(rec, slot), _POD_SLOT_CLAMP)
        if not level:
            continue
        name = POD_SLOTS[slot]
        if name == "cleric":
            row = _row(_POD_SLOT_ROWS["cleric"], "cleric", level)
            for spell_level in range(1, 8):
                rec[_POD_CAPACITY + cleric + spell_level - 1] = row[spell_level - 1]
            wisdom = rec[_POD_WISDOM]
            for above, spell_level in ((12, 1), (13, 1), (14, 2), (15, 2),
                                       (16, 3), (17, 4)):
                if wisdom > above and cap(cleric, spell_level) > 0:
                    add(cleric, spell_level, 1)
            if wisdom < 17:
                rec[_POD_CAPACITY + cleric + 5] = 0
            if wisdom < 18:
                rec[_POD_CAPACITY + cleric + 6] = 0
            grant(lambda who, lv: who == 0 and 1 <= lv <= 9 and cap(cleric, lv) > 0)
        elif name == "paladin" and level > 8:
            row = _row(_POD_SLOT_ROWS["paladin"], "paladin", level)
            for column in range(4):
                add(cleric, column + 1, row[column])
            grant(lambda who, lv: who == 0 and 1 <= lv <= 9 and cap(cleric, lv) > 0)
        elif name == "ranger" and level > 7:
            # `goldbox.spells` keeps the row's columns 1-4 and 5-8 apart.
            to_druid, to_mage = _row(_POD_SLOT_ROWS["ranger"], "ranger", level)
            for column in range(4):
                add(druid, column + 1, to_druid[column])
                add(mage, column + 1, to_mage[column])
            grant(lambda who, lv: 1 <= lv <= 9 and cap(druid, lv) > 0
                  and (who == 1 or (who == 2 and cap(mage, lv) > 0)))
        elif name == "magic-user":
            row = _row(_POD_SLOT_ROWS["magic-user"], "magic-user", level)
            intelligence = rec[_POD_INTELLIGENCE]
            for column in range(9):
                add(mage, column + 1, row[column])
                for below, spell_level in ((12, 6), (14, 7), (16, 8), (18, 9)):
                    if intelligence < below:
                        rec[_POD_CAPACITY + mage + spell_level - 1] = 0
    for node in items:
        if len(node) > 0x41 and node[0x41] == 0x41 and node[0x35]:
            add(mage, 5, cap(mage, 5))


def _pod_saves(rec: bytearray, items=(), dos_saves: bool = False) -> None:
    """`0x3C5AC`: each column from 20, lowered to each cell below it over
    the slots with an effective level. **The first column's constitution
    steps run inside that slot loop**, once per such slot and before the
    next slot's cell is compared: a readied item of power `& 0x7F == 6`
    (bit 7 set) adds +1 to +5 by constitution 4-18, and everyone takes the
    high step from 19. A one-class character takes each step once."""
    kind_six = readied_power(items, 6)
    constitution = rec[_POD_CONSTITUTION]
    for column in range(5):
        value = 20
        for slot in range(len(POD_SLOTS)):
            level = pod_effective_level(rec, slot)
            if not level:
                continue
            cell = _pod_save_cell(slot, level, dos_saves)[column]
            if cell < value:
                value = cell
            if column == 0:
                if kind_six:
                    value = (value
                             + levels._dos_con_save_racial_step(constitution)) & 0xFF
                value = (value + _pod_high_constitution(constitution)) & 0xFF
        rec[_POD_SAVES + column] = value & 0xFF


def pod_recompute(rec: bytearray, items=(), dos_saves: bool = False) -> None:
    """`0x3C238`, the recompute training runs on the Amiga and the DOS load
    runs: THAC0, the level byte, attacks, capacity and grants, saves, thief
    skills, the class mask, and a regained class's attacks and thief skills.
    The Amiga load does not call it. `dos_saves` gives the thief the saving
    throw row the DOS load uses, where the Amiga's own is all zeros."""
    rec[_POD_THAC0] = 0
    for slot in range(len(POD_SLOTS)):
        level = pod_effective_level(rec, slot)
        value = _POD_THAC0_ROWS[slot][min(level, _POD_TABLE_CLAMP)]
        if value > rec[_POD_THAC0]:
            rec[_POD_THAC0] = value
        if rec[_POD_LEVEL] < level:
            rec[_POD_LEVEL] = level
        # `0x3C2E0`: the druid shares the fighter's branch, and each branch
        # only ever writes; a later slot can lower an earlier one's 4 to 3.
        if slot in (1, 2, 3):
            if level > 6:
                rec[_POD_ATTACKS] = 3
            if level > 12:
                rec[_POD_ATTACKS] = 4
        elif slot == _POD_RANGER:
            if level > 7:
                rec[_POD_ATTACKS] = 3
            if level > 14:
                rec[_POD_ATTACKS] = 4
    _pod_capacity(rec, items)
    _pod_saves(rec, items, dos_saves)
    if rec[_POD_LEVELS + _POD_THIEF] > 0:
        _pod_thief_skills(rec)
    bits = 0
    for slot in range(len(POD_SLOTS)):
        former = rec[_POD_FORMER + slot]
        if rec[_POD_LEVELS + slot] > 0 or 0 < former < rec[_POD_LEVEL]:
            bits = (bits + _POD_CLASS_BIT[slot]) & 0xFF
    rec[_POD_CLASS_BITS] = bits
    # `0x3C376` would unready any readied item whose class mask no longer
    # matches. Training only adds bits, so a level-up never reaches it.
    if pod_regained(rec):
        for slot in range(len(POD_SLOTS)):
            former = rec[_POD_FORMER + slot]
            if POD_SLOTS[slot] in ("fighter", "paladin"):
                if former >= 13:
                    rec[_POD_ATTACKS] = 4
                elif former >= 7:
                    rec[_POD_ATTACKS] = 3
            elif slot == _POD_RANGER:
                if former >= 15:
                    rec[_POD_ATTACKS] = 4
                elif former >= 8:
                    rec[_POD_ATTACKS] = 3
            elif slot == _POD_THIEF and former > 0:
                _pod_thief_skills(rec)


def pod_check(rec) -> None:
    if rec[_POD_STATUS] != 0:
        raise RecomputeError("the trainer only trains conscious characters")
    if rec[_POD_RACE] >= len(_POD_THIEF_RACE):
        raise RecomputeError("a race past the human has no trainer rows to copy")
    if rec[_POD_LEVELS + _POD_DRUID] or rec[_POD_FORMER + _POD_DRUID]:
        raise RecomputeError("a druid level is not copied: no player character was found to hold one")
    if not 3 <= rec[_POD_CONSTITUTION] <= 25:
        raise RecomputeError("a constitution outside 3-25 reads past the "
                          "hit-point bonus table")
    thief = (rec[_POD_LEVELS + _POD_THIEF]
             or (pod_regained(rec) and rec[_POD_FORMER + _POD_THIEF]))
    dex = rec[_POD_DEXTERITY] - _POD_THIEF_DEX_FROM
    if thief and not 0 <= dex < len(_POD_THIEF_DEX):
        raise RecomputeError("a thief's dexterity outside 9-19 reads past the "
                          "thief-skill table")


def readied_power(items, kind: int) -> bool:
    """A readied later-title item node (`+0x35`) whose power byte `+0x41` is
    above 0x80 with `& 0x7F == kind`."""
    return any(len(node) > 0x41 and node[0x35] and node[0x41] > 0x80
               and node[0x41] & 0x7F == kind for node in items)


#: The DOS field names the DOS load rebuilds from the class levels.
DOS_LOAD_FIELDS = (
    "thac0_base", "thac0_current", "save_paralysis", "save_petrification",
    "save_wands", "save_breath", "save_spell", "attack_forms", "level",
    "class_bits", "thief_pick_pockets", "thief_open_locks", "thief_find_traps",
    "thief_move_silently", "thief_hide_in_shadows", "thief_hear_noise",
    "thief_climb_walls", "thief_read_languages")


def recomputed_block(block: bytes, *, dos_load: bool = False) -> bytes:
    """`block` with the game's recompute run on its record.

    The Amiga load never runs the recompute for a player character: it copies
    the stored base THAC0 into the current one and leaves the saves and
    attacks as stored. The current THAC0 moves by the base's change, since
    strength and items are unchanged. `dos_load` is the DOS load's version,
    for a record that came from DOS: the thief's real save row, and the
    source's spell capacity and spellbook kept, because the writer owns
    the capacity (`amiga_pod.engine_spell_slots`) and the DOS book is not
    changed. Raises :class:`RecomputeError` where the recompute's tables
    cannot cover the record.
    """
    rec = bytearray(block[:amiga_pod.RECORD_BYTES])
    character = amiga_pod.PodCharacter.from_bytes(block)
    items = [bytes(amiga_pod.ITEM_NODE_BASE) + item.raw
             for item in character.items]
    old = bytes(rec)
    pod_check(rec)
    pod_recompute(rec, items, dos_saves=dos_load)
    if dos_load:
        rec[_POD_CAPACITY:_POD_CAPACITY + 27] = old[_POD_CAPACITY:
                                                    _POD_CAPACITY + 27]
        rec[_POD_SPELLBOOK:_POD_SPELLBOOK + 16] = old[_POD_SPELLBOOK:
                                                      _POD_SPELLBOOK + 16]
    rec[amiga_pod.THAC0_CURRENT] = (
        old[amiga_pod.THAC0_CURRENT] + rec[amiga_pod.THAC0_BASE]
        - old[amiga_pod.THAC0_BASE]) & 0xFF
    return bytes(rec) + block[amiga_pod.RECORD_BYTES:]
