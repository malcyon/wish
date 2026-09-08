#!/usr/bin/env python3
"""What each Gold Box trainer does about spells, read out of the player's disks.

Every title's training hall has one step per spellcasting class, and the
shape of the step is per class *and* per title. This reads all three C64
titles' `GEN` overlays, decodes each step's own tables, and prints -- or
checks against `goldbox/spells.py` and `goldbox/levelup.py` -- the exact set
of spell ids a character of each level comes away with.

    tools/trainerspells.py --rows
    tools/trainerspells.py --check          # exits non-zero on a mismatch

**The step has to be in the sequence or nothing here is about the trainer.**
That is the trap this tool exists to close. Silver Blades' `GEN $0F7C` ORs a
whole magic-user spell list in from a table, and for a year that was read as
its trainer granting a row where Pool of Radiance offers a menu. It is the
*starting spellbook*: its only caller is `$0EF9`, the tail of `$0EF3`, which
is reached from `$09FA` -- 34 bytes after `$09D8` zeroes the whole
sixteen-byte mask, which no trainer would ever do -- and from `$1FC3`, the
dual-class routine that has just written `0x0B9`/`0x0BA`. The same misreading
had already been found and corrected in Curse, whose `$167F` is the same
routine in the same place. So every step below is asserted to be a `JSR` the
title's own level-up sequence makes, checked from the bytes on each run, and
a step that is not in the sequence is not reported as a trainer step.

The five shapes, all of them read here rather than assumed:

* **`menu_pool`** -- Pool of Radiance's `$215A` and Curse's `$2200`. The
  castable spell level is `(level + 1) // 2` (`LSR A / ADC #$00`), and a
  per-id table of spell levels decides what goes on the list.
* **`menu_blades`** -- Silver Blades' `$1896`. A per-level table of spell
  levels with a **minimum intelligence** beside it, and the candidates come
  from a bitmask union rather than a per-id table.
* **`grant_loop`** -- the cleric's everywhere but Pool of Radiance, and the
  ranger's in Silver Blades: `LDY levels,X / LDX offsets,Y / LDA masks,Y /
  ORA mask,X`, walked backwards from a per-level ceiling.
* **`grant_inline`** -- Pool of Radiance's cleric (`$20C6`) and Curse's
  ranger (`$2305`): immediate `ORA` constants behind `CPX` gates.
* **`grant_borrowed`** -- the paladin's, which jumps into the cleric's own
  loop with a row index of its own: Curse fixes it at 1 (`LDX #$01`), Silver
  Blades scales it with the paladin's level (`SBC #$08 / TAX`).

Nothing here needs an emulator. `tools/trainerscan.py` supplies the overlay
and the record base; `tools/d6502.py` is the disassembler behind the
addresses quoted in the docstrings.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools.d6502 import M_IMM, SZ, T  # noqa: E402
from tools.trainerscan import overlay  # noqa: E402

#: Where `GEN` runs in all three titles, whatever the PRG header says.
BASE = 0x0800

#: The record's address while `GEN` runs, per title.
RECORD = {"pool": 0x6B00, "curse": 0x7C00, "ssb": 0x7C00}

#: The spellbook bitmask's first byte, per title: record + `0x078`.
MASK = {"pool": 0x6B78, "curse": 0x7C78, "ssb": 0x7C78}

#: Each title's level-up sequence -- the routine the `TRAIN WHO` prompt runs
#: once a class has actually been raised. Every step below is asserted to be
#: a `JSR` inside `(start, end)`.
SEQUENCE = {"pool": (0x1B8C, 0x1BB9), "curse": (0x205E, 0x2079),
            "ssb": (0x1527, 0x1542)}

#: The steps, `(title, class, address, shape)`. Each address was found by
#: walking `tools/trainerscan.py --callers` back from the routine that writes
#: the spellbook mask, and each is checked against `SEQUENCE` on every run.
STEPS = (
    ("pool", "cleric", 0x20BC, "grant_inline_pool"),
    ("pool", "magic-user", 0x20BC, "menu_pool"),
    ("curse", "cleric", 0x1649, "grant_loop"),
    ("curse", "magic-user", 0x2200, "menu_pool"),
    ("curse", "paladin", 0x22F4, "grant_borrowed_curse"),
    ("curse", "ranger", 0x2305, "grant_inline_ranger"),
    ("ssb", "cleric", 0x0F30, "grant_loop"),
    ("ssb", "magic-user", 0x1896, "menu_blades"),
    ("ssb", "paladin", 0x1BEB, "grant_borrowed_blades"),
    ("ssb", "ranger", 0x0EFC, "grant_loop"),
)

#: How far an inline run reaches, keyed by the step's address. Bounded by
#: hand because neither run ends at an `RTS` a walker could stop on: Curse's
#: ranger returns in the middle of its own routine for a level-8 ranger, and
#: Pool of Radiance's cleric runs straight on into the spell-capacity code.
SPAN = {0x20BC: 0x40, 0x2305: 0x24}

#: Pool of Radiance alone puts the cleric's grant, both classes' spell
#: capacity and the magic-user's menu in **one** routine: the sequence calls
#: `$20BC`, which falls through to `$213C` and is joined to the menu at
#: `$215A` by the `JMP` at `$2157`. So the menu's decode starts there, and
#: the join is checked byte for byte on every run rather than assumed --
#: `(step address) -> (where the shape starts, the joining address, its
#: bytes)`.
INDIRECT = {(0x20BC, "menu_pool"): (0x215A, 0x2157, b"\x4C\x5A\x21")}


class Unreadable(Exception):
    """The bytes at an address are not the shape this tool expects."""


def _word(data: bytes, at: int) -> int:
    return data[at] | data[at + 1] << 8


def _sequence_calls(data: bytes, title: str) -> set[int]:
    """Every address the title's level-up sequence `JSR`s, from the bytes."""
    start, end = SEQUENCE[title]
    out = set()
    at = start - BASE
    while at < end - BASE:
        if data[at] == 0x20:
            out.add(_word(data, at + 1))
            at += 3
        elif data[at] == 0x4C:
            out.add(_word(data, at + 1))
            break
        else:
            at += 1
    return out


# --- the five shapes ---------------------------------------------------------

def _clamp(gap: bytes, exit_at: int):
    """Interpret the instructions between `LDX <class level>` and the `LDY`.

    Every grant loop in the family clamps its own row index before indexing,
    and the clamp is the whole reason a row read straight out of the level
    table can be nonsense: Silver Blades' ranger table has no rows below 8 at
    all, and reading one gives a byte number outside the sixteen-byte mask.
    Six instructions cover all four titles' clamps, so this interprets rather
    than pattern-matches, and `(level, score) -> row index or None` is the
    answer -- None where the routine returns without granting anything.

        BEQ         a level of 0 grants nothing
        CPX #n      compare the row index with a constant
        BCC / BCS   taken inside the gap it skips an `LDX`; taken past the
                    end of it, it is the routine's own way out
        LDX #m      the clamped row
        LDA <score> the wisdom Silver Blades' cleric asks for above level 10
        CMP #n      compare that score instead
    """
    def row(level: int, score: int):
        x, acc, carry, i = level, level, False, 0
        while i < len(gap):
            op = gap[i]
            if op == 0xF0:                                    # BEQ
                if acc == 0 and i + 2 + gap[i + 1] >= exit_at:
                    return None
                i += 2
            elif op == 0xE0:                                  # CPX #n
                acc, carry, i = x, x >= gap[i + 1], i + 2
            elif op == 0xC9:                                  # CMP #n
                carry, i = acc >= gap[i + 1], i + 2
            elif op in (0x90, 0xB0):                          # BCC / BCS
                taken = (not carry) if op == 0x90 else carry
                target = i + 2 + gap[i + 1]
                if not taken:
                    i += 2
                elif target >= exit_at:
                    return None
                else:
                    i = target
            elif op == 0xA2:                                  # LDX #m
                x, i = gap[i + 1], i + 2
            elif op == 0xAD:                                  # LDA <score>
                acc, i = score, i + 3
            else:
                i += 1
        return x
    return row


def _grant_loop(data: bytes, title: str, at: int):
    """A `LDY levels,X / LDX offsets,Y / LDA masks,Y / ORA mask,X` loop.

    Returns `(record offset read, level -> set of ids, the three tables)`.
    The gap between the `LDX` and the `LDY` is what the two earlier readings
    of this shape could not allow for, and it is where every clamp lives:
    Curse's magic-user starting book clamps at 6, Silver Blades' cleric asks
    for a Wisdom of 17 above level 10, and its ranger grants nothing at all
    below 8.
    """
    mask = MASK[title]
    hi = re.escape(bytes((mask >> 8,)))
    body = re.compile(
        rb"\xBC(..)(.{0,12}?)\xBE(..)\xB9(..)\x1D(.)" + hi + rb"\x9D(.)" + hi
        + rb"\x88\x10", re.DOTALL)
    head = data[at - BASE:at - BASE + 24]
    if head[:1] != b"\xAE":
        raise Unreadable(f"${at:04X} does not open LDX <record byte>")
    record_byte = head[1] | head[2] << 8
    match = body.search(data, at - BASE, at - BASE + 40)
    if match is None:
        raise Unreadable(f"${at:04X} is not a grant loop")
    levels, offsets, masks = (_word(match.group(n), 0) for n in (1, 3, 4))
    # **The two titles index the OR differently and the offsets table absorbs
    # it.** Curse writes `ORA $7C00,X` and holds record offsets 0x078-0x087;
    # Silver Blades writes `ORA $7C78,X` and holds byte numbers 0-15. So the
    # byte a row touches is `or base + offset - mask base` in both.
    if match.group(5)[0] != match.group(6)[0]:
        raise Unreadable(f"${at:04X} reads and writes different bytes")
    shift = (mask >> 8 << 8 | match.group(5)[0]) - mask
    gap = data[at - BASE + 3:match.start()]
    # A branch that lands exactly on the `LDY` falls into the loop; anything
    # past it is the routine's own way out to the `RTS`.
    clamp = _clamp(gap, len(gap) + 1)

    def ids_for(row: int | None):
        if row is None:
            return set()
        top = data[levels - BASE + row]
        ids = set()
        for y in range(top + 1):
            byte = data[offsets - BASE + y] + shift
            bits = data[masks - BASE + y]
            if not 0 <= byte <= 0x0F:
                return None                # a row the routine never reads
            ids |= {byte * 8 + b for b in range(8) if bits & 1 << b}
        return ids

    return (record_byte,
            {level: ids_for(clamp(level, 18)) for level in range(0, 32)},
            (levels, offsets, masks), clamp, ids_for)


def _grant_inline(data: bytes, title: str, at: int):
    """`(class level -> set of ids)` for a run of immediate `ORA` constants
    behind `CPX`/`CMP` gates, cumulative by level.

    Pool of Radiance's cleric (`$20C6`) and Curse's ranger (`$2305`) are the
    two, and neither is a table. Both spellings of the OR are read -- Pool of
    Radiance's `LDA mask+n / ORA #imm / STA mask+n` and Curse's `LDA #imm /
    ORA mask+n / STA mask+n` -- and a `JSR` inside the run is followed, which
    Curse's level-8 block needs: `$2310 JSR $2329` is where 77-80 live.

    **The walk does not stop at the first `RTS`.** Curse's ranger routine
    returns at `$2317` for a level-8 ranger and falls past it for a level-9
    one, so `SPAN` bounds each run instead.
    """
    mask = MASK[title]

    def constants(i: int, stop: int, follow: bool) -> set[int]:
        found: set[int] = set()
        while i < stop:
            op = data[i]
            if op == 0xAD and mask <= _word(data, i + 1) < mask + 16 \
                    and data[i + 3] == 0x09:
                byte, bits = _word(data, i + 1) - mask, data[i + 4]
                found |= {byte * 8 + b for b in range(8) if bits & 1 << b}
                i += 8
                continue
            if op == 0xA9 and data[i + 2] == 0x0D \
                    and mask <= _word(data, i + 3) < mask + 16:
                bits, byte = data[i + 1], _word(data, i + 3) - mask
                found |= {byte * 8 + b for b in range(8) if bits & 1 << b}
                i += 8
                continue
            if op == 0x60 and not follow:                # a subroutine ends
                break
            if op == 0x20 and follow:
                target = _word(data, i + 1) - BASE
                found |= constants(target, target + 0x20, False)
            mnemonic = T.get(op)
            i += SZ[mnemonic[1]] if mnemonic else 1
        return found

    span = SPAN[at]
    gates: dict[int, set[int]] = {0: set()}
    gate, i, stop = 0, at - BASE, at - BASE + span
    while i < stop:
        op = data[i]
        if op in (0xE0, 0xC9) and T[op][1] == M_IMM:
            gate = data[i + 1]
            gates.setdefault(gate, set())
            i += 2
            continue
        step = constants(i, i + 1, True) if op == 0x20 else set()
        if op in (0xAD, 0xA9):
            step = constants(i, i + 8, False)
        gates[gate] |= step
        mnemonic = T.get(op)
        i += max(SZ[mnemonic[1]] if mnemonic else 1, len(step) and 8 or 1) \
            if op in (0xAD, 0xA9) and step else (SZ[mnemonic[1]]
                                                 if mnemonic else 1)
    return {level: set().union(*(ids for g, ids in gates.items() if g <= level))
            for level in range(0, 32)}


def _menu_pool(data: bytes, title: str, at: int):
    """`(level -> list of ids the menu offers a character who knows none)`.

    `LSR A / ADC #$00` is `(level + 1) // 2`; `$268E`/`$273F` is a spell level
    per id and `$226B` (Pool of Radiance only) a per-id "never offer this".
    """
    i = at - BASE
    window = data[i:i + 0x60]
    if b"\x4A\x69\x00" not in window:
        raise Unreadable(f"${at:04X} does not compute (level + 1) // 2")
    # `CMP <levels>,X` -- the only absolute,X compare in the walk.
    m = re.search(rb"\xDD(..)", window, re.DOTALL)
    if m is None:
        raise Unreadable(f"${at:04X} has no per-id spell level table")
    levels = _word(m.group(1), 0)
    skip = None
    s = re.search(rb"\xBD(..)\xD0", window, re.DOTALL)
    if s is not None:
        skip = _word(s.group(1), 0)
    # Two spellings of the same ceiling: Curse counts up and stops with
    # `CMP #$5F / BCC`, Pool of Radiance skips every id at or above
    # `CPX #$38 / BCS` and lets the counter wrap. Both mean "ids 1 to N-1".
    top = re.search(rb"\xC9(.)\x90", window, re.DOTALL) \
        or re.search(rb"\xE0(.)\xB0", window, re.DOTALL)
    if top is None:
        raise Unreadable(f"${at:04X} never stops walking the spellbook")
    last = top.group(1)[0]
    out = {}
    for level in range(1, 20):
        castable = (level + 1) // 2
        ids = []
        for sid in range(1, last):
            if data[levels - BASE + sid] > castable:
                continue
            if skip is not None and data[skip - BASE + sid]:
                continue
            ids.append(sid)
        out[level] = ids
    return out, last


def _menu_blades(data: bytes, title: str, at: int):
    """`((level, intelligence) -> list of ids)` for Silver Blades' `$1896`.

    The walk down `$1917,X` is the intelligence cap: a magic-user's own level
    indexes the table, and while the score is short of what that row asks the
    index drops. `$1926,X` is then the row of the same offsets-and-masks pair
    the grant loops use.
    """
    i = at - BASE
    window = data[i:i + 0x70]
    m = re.search(rb"\xAE(..)\xAD(..)\xDD(..)\xB0\x03\xCA\x10\xF8"
                  rb"\xBC(..)\xB9(..)\xBE(..)", window, re.DOTALL)
    if m is None:
        raise Unreadable(f"${at:04X} is not Silver Blades' menu")
    level_at, score_at, min_score, top, masks, offsets = (
        _word(m.group(n), 0) for n in range(1, 7))
    if level_at != RECORD[title] + 0x0C9:
        raise Unreadable(f"${at:04X} reads 0x{level_at - RECORD[title]:03X}, "
                         f"not the magic-user's level")
    ceiling = re.search(rb"\xC0(.)\x90", window, re.DOTALL)
    if ceiling is None:
        raise Unreadable(f"${at:04X} never stops walking the mask")
    last = ceiling.group(1)[0]
    out = {}
    for level in range(1, 16):
        for score in range(3, 19):
            x = level
            while x >= 1 and score < data[min_score - BASE + x]:
                x -= 1
            ids = set()
            for y in range(data[top - BASE + x] + 1):
                byte = data[offsets - BASE + y]
                bits = data[masks - BASE + y]
                ids |= {byte * 8 + b for b in range(8) if bits & 1 << b}
            out[(level, score)] = sorted(i for i in ids if i < last)
    return out, score_at - RECORD[title], last


def _borrowed(data: bytes, title: str, at: int):
    """`(paladin level -> the cleric row index its grant reads)`.

    `LDX #$06 / <eligible?> / CMP #$09 / BCC out` in both titles; then Curse
    loads a constant row and Silver Blades subtracts.
    """
    i = at - BASE
    window = data[i:i + 0x18]
    if window[0] != 0xA2:
        raise Unreadable(f"${at:04X} does not open LDX #<class slot>")
    slot = window[1]
    m = re.search(rb"\xC9(.)\x90", window, re.DOTALL)
    if m is None:
        raise Unreadable(f"${at:04X} has no level gate")
    gate = m.group(1)[0]
    # Past the gate, because the routine opens with an `LDX #<class slot>`
    # of the same shape as the constant row Curse loads.
    tail = window[m.end():]
    fixed = re.search(rb"\xA2(.)\x20(..)", tail, re.DOTALL)
    scaled = re.search(rb"\xE9(.)\xAA\x20(..)", tail, re.DOTALL)
    if scaled is not None:
        return slot, gate, {lv: lv - scaled.group(1)[0]
                            for lv in range(gate, 20)}, _word(scaled.group(2), 0)
    if fixed is not None:
        return slot, gate, {lv: fixed.group(1)[0]
                            for lv in range(gate, 20)}, _word(fixed.group(2), 0)
    raise Unreadable(f"${at:04X} neither fixes nor scales the row")


# --- what the steps say ------------------------------------------------------

def read(title: str) -> dict:
    """Every trainer spell step this title has, decoded."""
    data = overlay(title, "GEN")
    called = _sequence_calls(data, title)
    out = {}
    for name, cls, at, shape in STEPS:
        if name != title:
            continue
        if at not in called:
            raise Unreadable(
                f"{title}: ${at:04X} is not called by the level-up sequence "
                f"at ${SEQUENCE[title][0]:04X}, so it is not a trainer step")
        join = INDIRECT.get((at, shape))
        if join is not None:
            at, where, want = join
            if data[where - BASE:where - BASE + len(want)] != want:
                raise Unreadable(
                    f"{title}: ${where:04X} no longer joins the step to "
                    f"${at:04X}")
        if shape == "grant_loop":
            byte, row_ids, tables, clamp, ids_for = _grant_loop(data, title, at)
            out[cls] = {"shape": shape, "at": at, "record": byte - RECORD[title],
                        "rows": row_ids, "tables": tables,
                        "clamp": clamp, "ids_for": ids_for}
        elif shape.startswith("grant_inline"):
            out[cls] = {"shape": shape, "at": at,
                        "rows": _grant_inline(data, title, at)}
        elif shape == "menu_pool":
            rows, last = _menu_pool(data, title, at)
            out[cls] = {"shape": shape, "at": at, "rows": rows, "last": last}
        elif shape == "menu_blades":
            rows, score, last = _menu_blades(data, title, at)
            out[cls] = {"shape": shape, "at": at, "rows": rows,
                        "score": score, "last": last}
        else:
            slot, gate, row, target = _borrowed(data, title, at)
            out[cls] = {"shape": shape, "at": at, "slot": slot, "gate": gate,
                        "rows": row, "target": target}
    return out


def _spans(ids) -> str:
    """`9-21, 77-80` rather than nineteen numbers."""
    ids = sorted(ids)
    out, i = [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        out.append(str(ids[i]) if j == i else f"{ids[i]}-{ids[j]}")
        i = j + 1
    return ", ".join(out) or "-"


def rows(title: str) -> None:
    steps = read(title)
    print(f"=== {title}: level-up sequence ${SEQUENCE[title][0]:04X}")
    for cls in ("cleric", "magic-user", "paladin", "ranger"):
        step = steps.get(cls)
        if step is None:
            print(f"  {cls:11s} -- no step in this title's sequence")
            continue
        print(f"  {cls:11s} ${step['at']:04X}  {step['shape']}")
        if step["shape"] == "menu_blades":
            seen = None
            for level in range(1, 16):
                for score in (9, 18):
                    ids = step["rows"][(level, score)]
                    if (level, score, tuple(ids)) and ids != seen:
                        print(f"      level {level:2d} int {score:2d}: "
                              f"{_spans(ids)}")
                        seen = ids
        elif step["shape"] == "menu_pool":
            seen = None
            for level in range(1, 16):
                ids = step["rows"][level]
                if ids != seen:
                    print(f"      level {level:2d}: {_spans(ids)}")
                    seen = ids
        elif step["shape"].startswith("grant_borrowed"):
            print(f"      slot {step['slot']}, from level {step['gate']}, "
                  f"into the cleric loop at ${step['target']:04X}")
            print("      " + ", ".join(
                f"{lv}->row {r}" for lv, r in sorted(step["rows"].items())
                if lv <= 15))
        else:
            seen = None
            # 15 is the highest ceiling any caster in the family has, and a
            # row past it is read out of whatever table follows the level one.
            for level in range(1, 16):
                ids = step["rows"].get(level)
                if ids is None:
                    continue
                if ids != seen:
                    print(f"      level {level:2d}: {_spans(ids)}")
                    seen = ids


def check(title: str) -> list[str]:
    """Diff the game's own steps against `goldbox/levelup.py`. Empty is good."""
    from goldbox import games, levels, levelup, spells

    game = {"pool": games.POOL_OF_RADIANCE,
            "curse": games.CURSE_OF_THE_AZURE_BONDS,
            "ssb": games.SECRET_OF_THE_SILVER_BLADES}[title]
    ceiling = dict((n, len(r)) for n, r in levels.for_game(game).classes)
    steps = read(title)
    bad = []

    step = steps.get("cleric")
    if step is not None:
        # Pool of Radiance's trainer never ORs the first spell level in --
        # character creation has already done it -- so what is comparable
        # between a title that grants a row and a model that unions the whole
        # known list is what each *adds* at a level.
        # Both sides of Silver Blades' Wisdom gate, and the low one is the
        # half a single reading would have missed: below 17 the routine drops
        # a cleric of 11 back to the level-10 row.
        for score in (9, 18):
            if step["shape"] == "grant_loop":
                rows = {lv: step["ids_for"](step["clamp"](lv, score))
                        for lv in range(0, 32)}
            elif score != 18:
                continue
            else:
                rows = step["rows"]
            for level in range(2, ceiling["cleric"] + 1):
                was = set(levelup._cleric_spell_ids(level - 1, game, score))
                now = set(levelup._cleric_spell_ids(level, game, score))
                if rows.get(level) is None or rows.get(level - 1) is None:
                    continue
                if now - was != rows[level] - rows[level - 1]:
                    bad.append(f"{title} cleric {level} wis {score}: "
                               f"{sorted(now - was)} != "
                               f"{sorted(rows[level] - rows[level - 1])}")

    step = steps.get("ranger")
    if step is not None:
        for level in range(1, ceiling["ranger"] + 1):
            want = step["rows"].get(level) or set()
            got = set(levelup._ranger_spell_ids(level, game))
            if got != want:
                bad.append(f"{title} ranger {level}: {sorted(got)} != "
                           f"{sorted(want)}")

    step = steps.get("paladin")
    if step is not None:
        cleric = steps["cleric"]["rows"]
        for level in range(1, ceiling["paladin"] + 1):
            row = step["rows"].get(level)
            want = set() if row is None else cleric[row]
            got = set(levelup._paladin_spell_ids(level, game, 18))
            if got != want:
                bad.append(f"{title} paladin {level}: {sorted(got)} != "
                           f"{sorted(want)}")

    step = steps.get("magic-user")
    if step is not None:
        table = spells.for_game(game)
        for level in range(1, ceiling["magic-user"] + 1):
            for score in (9, 12, 14, 18):
                if step["shape"] == "menu_blades":
                    want = list(step["rows"][(level, score)])
                else:
                    want = list(step["rows"][level])
                want = [i for i in want if table.in_spellbook(i)]
                got = levelup.learnable(_blank(level, score), game,
                                        level=level)
                if got != want:
                    bad.append(f"{title} magic-user {level} int {score}: "
                               f"{got} != {want}")
                if step["shape"] != "menu_blades":
                    break
    return bad


def _blank(level: int, intelligence: int):
    """A record that knows no spell, at a magic-user level and intelligence."""
    from goldbox.record import RECORD_SIZE, CharacterRecord

    rec = CharacterRecord(bytes(RECORD_SIZE))
    rec.set("level_magic_user", level)
    rec.set("intelligence", intelligence)
    raw = bytearray(7)
    raw[1] = intelligence
    rec.set_raw("abilities_second", bytes(raw))
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", choices=sorted(RECORD), action="append")
    ap.add_argument("--rows", action="store_true", help="print every step")
    ap.add_argument("--check", action="store_true",
                    help="diff against goldbox/levelup.py")
    args = ap.parse_args(argv)
    titles = args.game or sorted(RECORD)

    failed = []
    for title in titles:
        if args.rows or not args.check:
            rows(title)
        if args.check:
            failed += check(title)
    if args.check:
        for line in failed:
            print("MISMATCH", line)
        print(f"{len(failed)} mismatches over {len(titles)} titles")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
