#!/usr/bin/env python3
"""Read Pools of Darkness' spell-slot rows, spell table and creation menus.

    tools/dos/dospodtables.py slots
    tools/dos/dospodtables.py spells
    tools/dos/dospodtables.py menus

The DOS engine's own tables, out of the player's `GAME.OVR` and the expanded
`GAME.EXE`, through `tools/dos/dosspellslots.py`'s overlay helpers.  Nothing
here is found by a committed address: every table offset is read out of the
instruction that indexes it, and the addresses in the comments name a site a
reader can check rather than one the code uses.

* `slots` -- the four per-class slot tables the builder reads, the record
  array each lands in, and the wisdom and intelligence ceilings that follow.
  Pools of Darkness stores **running totals** where Curse and Silver Blades
  store deltas, and its cleric branch assigns where the others add, so the
  rows come back as a character sheet would show them with no accumulation.
* `spells` -- the class and level byte of every spell id, grouped, which is
  what says which spell level an id belongs to without reading its name.
* `menus` -- what CREATE NEW CHARACTER offers: the race list, the classes
  each race may take, the alignments each class may take, the racial and
  class ability limits, and the name-entry length.

`--path` takes the game directory when the registry cannot find it.  Prints
offsets and numbers; the game's bytes stay in the player's own directory.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos_port  # noqa: E402
from tools.dos import dosbox, dosraces, dosspellslots  # noqa: E402

#: The 510-byte record, which is what `goldbox.dos_port` calls this title.
RECORD_SIZE = 510

#: The game directory's name inside the archives.
STEM = "DARKNESS"

#: The record's three slot arrays, in record order.
ARRAYS = ("cleric", "druid", "magic-user")

#: How many class levels the builder will read a row for.  The builder and
#: the cleric's helper both clamp with `cmp byte ptr [bp-2], 0x1d`, so this
#: is the engine's own number rather than a choice.
CEILING = 29


# --- finding the game --------------------------------------------------------

def find_game(path: str | None = None) -> pathlib.Path:
    """The Pools of Darkness game directory, inside the player's archives.

    `tools.dos.dosbox.find_game` insists on a `START.EXE`, which this title
    does not have, so the directory comes from `tools.dos.dosraces`' own
    finder -- the one place in the tree that already knows this title is
    launched through `GAME.EXE`.
    """
    if path:
        return pathlib.Path(path)
    found = dosraces.find_executable(STEM, ("GAME.EXE",))
    if found is None:
        raise FileNotFoundError(
            f"no DOS Pools of Darkness under {dosbox.ARCHIVES}; pass --path")
    return found.parent


def load(path: str | None = None):
    """`(GAME.OVR bytes, expanded image, data segment)`."""
    game = find_game(path)
    ovr = (game / "GAME.OVR").read_bytes()
    image = dosspellslots.image_of(game, None)
    return ovr, image, dosspellslots.data_segment(image)


def pstring(image: bytes, ds: int, offset: int) -> str:
    """A Turbo Pascal counted string at a data-segment offset."""
    at = ds * 16 + offset
    return image[at + 1:at + 1 + image[at]].decode("latin1")


# --- the slot tables ---------------------------------------------------------
# Every class branch of the builder compiles the same way in this title, and
# differently from Curse's and Silver Blades', which is why
# `tools/dos/dosspellslots.py`'s own branch reader finds nothing here:
#
# * the branch opens `cmp al, <class slot> / je|jne`, where Curse opens
#   `mov al, <level> / cmp al, [bp-0xf]`;
# * an optional `cmp byte ptr [bp-2], <n> / ja` is the first class level whose
#   row is read at all -- the paladin's 8 and the ranger's 7, both meaning
#   "from the level above";
# * `mov byte ptr [bp-4], <first>` opens the loop over the row's columns and
#   `cmp byte ptr [bp-4], <last> / jne` closes it;
# * `mov dx, 9 / mul dx` is the row stride, `mov dl, [di + imm16]` reads the
#   table and `add|mov byte ptr es:[di + imm16], dl` says which record array
#   it lands in;
# * `sub ax, imm16` between the two is how the ranger writes his columns 5
#   and 6 into the magic-user array's levels 1 and 2.

#: The class loop's terminator: `cmp byte ptr [bp-1], 7 / je +3 / jmp near`.
_CLASS_LOOP_END = rb"\x80\x7e\xff[\x06\x07]\x74\x03\xe9"

#: `cmp al, <class slot>` opening a branch.
_BRANCH = rb"\x3c(.)[\x74\x75]"

#: `cmp byte ptr [bp-2], <n> / ja` -- the class level the rows start above.
_FROM_LEVEL = rb"\x80\x7e\xfe(.)\x77"

#: `mov byte ptr [bp-<local>], <first>` opens the loop over a row's columns.
#: The local is `[bp-4]` in the main builder's branches and `[bp-1]` in the
#: cleric's helper, so it is read rather than assumed and the close has to
#: name the same one: `cmp byte ptr [bp-<local>], <last> / jne`.
_RUN_OPEN = rb"\xc6\x46(.)(.)"
_RUN_CLOSE = rb"\x80\x7e%s(.)\x75"

#: `mov dl, byte ptr [di + imm16]` -- the table read.
_TABLE = rb"\x8a\x95(..)"

#: `add byte ptr es:[di + imm16], dl` and `mov byte ptr es:[di + imm16], dl`.
_DEST_ADD = rb"\x26\x00\x95(..)"
_DEST_MOV = rb"\x26\x88\x95(..)"

#: `sub ax, imm16`, the column-to-spell-level shift.
_SHIFT = rb"\x2d(.)\x00"

#: `push [bp+8] / push [bp+6] / push cs / call rel16` -- a class branch
#: handing its rows to a local helper, which the cleric's does.
_HELPER_CALL = rb"\xff\x76\x08\xff\x76\x06\x0e\xe8(..)"


class Run:
    """One column loop: a class's table row into one record array."""

    def __init__(self, table: int, dest: int, first: int, last: int,
                 shift: int, assigns: bool):
        self.table, self.dest = table, dest
        self.first, self.last, self.shift = first, last, shift
        self.assigns = assigns

    def cells(self, block: int):
        """`(column, index into the slot block)` for every column written."""
        return [(s, self.dest + s - self.shift - block)
                for s in range(self.first, self.last + 1)]

    def __repr__(self) -> str:                                # pragma: no cover
        return (f"Run(DS:{self.table:04X}, dest={self.dest:#05x}, "
                f"cols {self.first}-{self.last}, shift={self.shift}, "
                f"{'mov' if self.assigns else 'add'})")


class Branch:
    """One class branch: where its rows start and where they go.

    `at` is where the rows were read -- the branch itself, or the helper it
    calls.  `sites` is every address whose instructions belong to this class:
    the branch, its helper, and any leaf either of them calls, which is where
    the wisdom bonus and the two ability ceilings sit.
    """

    def __init__(self, number: int, from_level: int, runs: list[Run],
                 at: int, sites: tuple[int, ...] = ()):
        self.number, self.from_level, self.runs, self.at = (
            number, from_level, runs, at)
        self.sites = sites or (at,)

    def __repr__(self) -> str:                                # pragma: no cover
        return (f"Branch({self.number}, from level {self.from_level}, "
                f"{self.runs})")


def _runs(body: bytes) -> list[Run]:
    """Every column loop in one branch body or helper."""
    out: list[Run] = []
    opens = [(m.start(), m.group(1), m.group(2)[0])
             for m in re.finditer(_RUN_OPEN, body, re.S)]
    for i, (start, local, first) in enumerate(opens):
        span = body[start:opens[i + 1][0] if i + 1 < len(opens) else len(body)]
        read = re.search(_TABLE, span, re.S)
        close = re.search(_RUN_CLOSE % re.escape(local), span, re.S)
        if read is None or close is None:
            continue
        add = re.search(_DEST_ADD, span, re.S)
        mov = re.search(_DEST_MOV, span, re.S)
        dest = add or mov
        if dest is None:
            continue
        shift = re.search(_SHIFT, span[:read.start()], re.S)
        out.append(Run(
            table=struct.unpack("<H", read.group(1))[0],
            dest=struct.unpack("<H", dest.group(1))[0],
            first=first, last=close.group(1)[0],
            shift=shift.group(1)[0] if shift else 0,
            assigns=add is None))
    return out


def branches(ovr: bytes, site: int) -> list[Branch]:
    """Every class branch of the builder at `site`, in the order it tests them.

    A branch whose rows are in a local helper is followed into it, which is
    what the cleric's branch needs -- the helper is where the wisdom bonus
    lives as well.
    """
    end = re.search(_CLASS_LOOP_END, ovr[site:site + 0x800])
    if end is None:
        raise LookupError(f"no class loop after {site:06X}")
    window = ovr[site:site + end.start()]
    marks = [(m.start(), m.group(1)[0])
             for m in re.finditer(_BRANCH, window, re.S)]
    out = []
    for i, (at, number) in enumerate(marks):
        body = window[at:marks[i + 1][0] if i + 1 < len(marks) else len(window)]
        where = site + at
        sites = [where]
        called = [site + at + call.end() + struct.unpack("<h", call.group(1))[0]
                  for call in re.finditer(_HELPER_CALL, body, re.S)]
        runs = _runs(body)
        if not runs:
            for target in called:
                runs = _runs(ovr[target:target + 0x300])
                if runs:
                    where = target
                    break
            if not runs:
                continue
        for target in called:
            if target not in sites:
                sites.append(target)
            span = target + routine_length(ovr, target)
            for leaf in re.finditer(_HELPER_CALL, ovr[target:span], re.S):
                deeper = (target + leaf.end()
                          + struct.unpack("<h", leaf.group(1))[0])
                if deeper not in sites:
                    sites.append(deeper)
        level = re.search(_FROM_LEVEL, body, re.S)
        out.append(Branch(number, (level.group(1)[0] + 1) if level else 1,
                          runs, where, tuple(sites)))
    return out


def rows(image: bytes, ds: int, branch: Branch, block: int, width: int,
         ceiling: int = CEILING) -> dict[str, list[tuple[int, ...]]]:
    """One class's rows per record array, indexed by class level - 1.

    The tables hold running totals, so a row is read at the class level and
    not accumulated.  A level below the branch's own first level gets zeros,
    which is what the cleared block leaves.
    """
    touched = sorted({i // width for run in branch.runs
                      for _, i in run.cells(block)})
    out: dict[str, list[tuple[int, ...]]] = {ARRAYS[i]: [] for i in touched}
    for level in range(1, ceiling + 1):
        held = [0] * (width * len(ARRAYS))
        if level >= branch.from_level:
            for run in branch.runs:
                at = ds * 16 + run.table + width * level
                for s, index in run.cells(block):
                    held[index] += image[at + s]
        for i in touched:
            out[ARRAYS[i]].append(tuple(held[i * width:(i + 1) * width]))
    return out


def slot_tables(ovr: bytes, image: bytes, ds: int,
                ceiling: int = CEILING) -> dict[int, dict[str, list]]:
    """Every class branch's rows, keyed by the record's class-slot number."""
    block, width = dosspellslots.block_of(RECORD_SIZE)
    site = dosspellslots.builder_site(ovr, block)
    return {b.number: rows(image, ds, b, block, width, ceiling)
            for b in branches(ovr, site)}


# --- the two ceilings --------------------------------------------------------
# Both are a run of `cmp byte ptr es:[di + <ability>], <score> / jae|jbe`
# followed by `mov byte ptr es:[di + <slot>], 0`: the score a character must
# reach before the slot survives.  The cleric's sits at the end of the
# helper, the magic-user's in a leaf of its own.

_CEILING = (rb"\x26\x80\x7d(.)(.)\x73\x09"
            rb"\xc4\x7e.\x26\xc6\x85(..)\x00")


def ceilings(ovr: bytes, at: int, window: int = 0x300
             ) -> list[tuple[int, int, int]]:
    """`(ability offset, minimum score, record offset zeroed)`, in order."""
    return [(m.group(1)[0], m.group(2)[0],
             struct.unpack("<H", m.group(3))[0])
            for m in re.finditer(_CEILING, ovr[at:at + window], re.S)]


#: `mov sp, bp / pop bp / retf <n>` -- the end of a Turbo Pascal routine, and
#: what keeps a site's window from reading into the routine after it.
_ROUTINE_END = rb"\x89\xec\x5d\xca"


def routine_length(ovr: bytes, at: int, window: int = 0x300) -> int:
    """How far a routine at `at` runs, cut at its own exit."""
    end = re.search(_ROUTINE_END, ovr[at:at + window])
    return end.end() if end else window


def branch_gates(ovr: bytes, branch: Branch, window: int = 0x300):
    """`(bonus, ceilings)` over every site a class branch reaches.

    Each site is read only as far as its own `retf`, so the cleric's helper
    does not report the magic-user leaf that follows it in the overlay.
    """
    bonus, caps = [], []
    for site in branch.sites:
        span = routine_length(ovr, site, window)
        for row in wisdom_bonus(ovr, site, span):
            if row not in bonus:
                bonus.append(row)
        for row in ceilings(ovr, site, span):
            if row not in caps:
                caps.append(row)
    return bonus, caps


#: The cleric branch's wisdom bonus, which sits between its rows and its
#: ceiling: `cmp byte ptr es:[di + 0x15], <score> / jbe` past
#: `inc byte ptr es:[di + <slot>]`, one compare a point of wisdom.
_BONUS = (rb"\x26\x80\x7d(.)(.)\x76\x13\xc4\x7e.\x26\x80\xbd(..)\x00"
          rb"\x76\x08\xc4\x7e.\x26\xfe\x85(..)")


def wisdom_bonus(ovr: bytes, at: int, window: int = 0x300
                 ) -> list[tuple[int, int, int, int]]:
    """`(ability offset, score exceeded, record offset gated, offset +1)`.

    The gate is the third element and it is not decoration: each bonus is
    skipped unless the slot it would increment already holds something, so a
    cleric gets a bonus only at a spell level his own rows reach.
    """
    return [(m.group(1)[0], m.group(2)[0],
             struct.unpack("<H", m.group(3))[0],
             struct.unpack("<H", m.group(4))[0])
            for m in re.finditer(_BONUS, ovr[at:at + window], re.S)]


# --- the spell table ---------------------------------------------------------

#: `mov cl, 4 / shl di, cl / add di, imm16` -- the builder walking the
#: 16-byte spell table, and `cmp byte ptr [bp-5], <last> / jne` its ceiling.
_SPELL_TABLE = rb"\xb1\x04\xd3\xe7\x81\xc7(..)"
_SPELL_LAST = rb"\x80\x7e\xfb(.)\x75"

#: What the table's class byte means.  Read off the builder: the cleric's
#: branch tests 0 against the cleric array, and the ranger's tests 1 against
#: the druid array and 2 against the magic-user array.
SPELL_CLASSES = {0: "cleric", 1: "druid", 2: "magic-user"}


def spell_table(ovr: bytes, image: bytes, ds: int) -> tuple[int, int]:
    """`(data-segment offset, last spell id)` of the 16-byte spell table."""
    block, _ = dosspellslots.block_of(RECORD_SIZE)
    site = dosspellslots.builder_site(ovr, block)
    window = ovr[site:site + 0x800]
    at = re.search(_SPELL_TABLE, window, re.S)
    last = re.search(_SPELL_LAST, window, re.S)
    if at is None or last is None:
        raise LookupError("no spell-table walk behind the slot builder")
    return struct.unpack("<H", at.group(1))[0], last.group(1)[0]


def spell_groups(image: bytes, ds: int, table: int, last: int
                 ) -> dict[int, tuple[str | None, int]]:
    """`{spell id: (class or None, spell level)}` for every id 1..last."""
    base = ds * 16 + table
    out = {}
    for sid in range(1, last + 1):
        entry = image[base + 16 * sid:base + 16 * sid + 2]
        out[sid] = (SPELL_CLASSES.get(entry[0]), entry[1])
    return out


# --- the creation menus ------------------------------------------------------
# All five tables are read out of the instruction that indexes them, inside
# the creation routine -- the one whose `FillChar` clears the whole 510-byte
# record.  Each anchor below is the index arithmetic, so the offset comes out
# of the game rather than out of this file.

#: `FillChar(record, 510, 0)`: `mov ax, 0x1fe / push ax / lcall`.
_CREATE = rb"\x06\x57\xb8\xfe\x01\x50\x9a"

#: `cmp byte ptr [bp-<local>], <n> / jne` closing the loop that appends the
#: race names to the menu, so `<n>` is the last index the menu lists.  Read
#: after the race table's own read rather than at a known stack offset.
_MENU_LAST = rb"\x80\x7e(.)(.)\x75"

#: `mov al, es:[di + 0xad] / cwde / mov dx, 0xe / mul dx / ... /
#: mov al, [di + imm16]` -- the per-race class list, fourteen bytes a race,
#: the first byte a count.
_RACE_CLASSES = (rb"\x26\x8a\x85\xad\x00\x98\xba\x0e\x00\xf7\xe2\x8b\xf8"
                 rb"\x8a\x85(..)")

#: `mul <stride> / mov di, ax / add di, imm16 / push ds` -- a table of
#: counted strings being pushed at a string routine, which is how every one
#: of the three name tables is reached.  The stride comes out of the `mul`,
#: so nothing here knows a table's width in advance.
_NAME_TABLE = rb"\xba(.)\x00\xf7\xe2\x8b\xf8\x81\xc7(..)\x1e"

#: `mov al, es:[di + 0xae] / cwde / mul 0xa / ... / mov al, [di + imm16]` --
#: the per-class alignment list, ten bytes a class, the first byte a count.
_CLASS_ALIGNMENTS = (rb"\x26\x8a\x85\xae\x00\x98\xba\x0a\x00\xf7\xe2\x8b\xf8"
                     rb"\x8a\x85(..)")

#: `shl di, 4 / [add di, dx] / mov dl, [di + imm16]` -- the racial ability
#: limits, sixteen bytes a race.  Strength's two are indexed by sex as well,
#: which is the `add di, dx` the others do not have.
_RACE_LIMITS = rb"\xb1\x04\xd3\xe7(\x03\xfa)?\x8a\x95(..)"

#: `shl di,1 / mov si,di / shl di,1 / add di,si / add di,dx /
#: mov dl, [di + imm16]` -- the class minimums, six bytes a class.
_CLASS_MINIMUMS = rb"\xd1\xe7\x8b\xf7\xd1\xe7\x01\xf7\x03\xfa\x8a\x95(..)"

#: `mov al, <n> / push ax` three times into `lcall` -- the name prompt's own
#: input call.  The third argument is the length it accepts, and the
#: `mov ax, <n> / push ax / lcall` right after it is the truncation of the
#: answer into the record's name field, which has to agree.
_NAME_INPUT = rb"\xb0(.)\x50\xb0\x00\x50\xb0(.)\x50\x9a...."
_NAME_COPY = rb"\xb8(.)\x00\x50\x9a"

#: The abilities in record order, which is the order the roll loop walks --
#: `goldbox.dos_port`'s own field order for the six two-byte pairs at
#: record `0x010`.
ABILITIES = ("strength", "intelligence", "wisdom", "dexterity",
             "constitution", "charisma")

#: How wide a race's row of ability limits is, from the `shl di, 4` that
#: indexes it.
LIMIT_STRIDE = 16


def creation_site(ovr: bytes, window: int = 0x2200) -> int:
    """Where CREATE NEW CHARACTER clears the record it is about to fill.

    Six routines `FillChar` a whole 510-byte record; the one that then menus
    a race out of a table of counted strings is this one.  Raises when that
    is not exactly one of them, which would mean the reading no longer holds.
    """
    found = [m.start() for m in re.finditer(_CREATE, ovr)
             if re.search(_RACE_CLASSES, ovr[m.start():m.start() + window],
                          re.S)]
    if len(found) != 1:
        raise LookupError(
            f"{len(found)} `FillChar(record, {RECORD_SIZE})` sites carry a "
            f"race menu; expected exactly one")
    return found[0]


def name_tables(body: bytes) -> list[tuple[int, int, int]]:
    """`(position, stride, data-segment offset)` for every name table read.

    Every menu in the routine builds its list the same way, so this is all of
    them in the order the player is asked, and nothing here knows a stride.
    """
    out = []
    for m in re.finditer(_NAME_TABLE, body, re.S):
        out.append((m.start(), m.group(1)[0],
                    struct.unpack("<H", m.group(2))[0]))
    return out


def _entries(tables: list[tuple[int, int, int]], offset: int) -> int | None:
    """How many entries the table at `offset` holds.

    The tables sit next to each other in the data segment in index order, so
    a table runs as far as the next one begins -- which is how many entries
    it has without asking the menu that reads it.
    """
    starts = sorted({o for _, _, o in tables})
    stride = next(s for _, s, o in tables if o == offset)
    after = [o for o in starts if o > offset]
    return (after[0] - offset) // stride if after else None


def menus(ovr: bytes, image: bytes, ds: int, window: int = 0x2200) -> dict:
    """Every table CREATE NEW CHARACTER menus out of, by structure.

    Each table's data-segment offset, its stride and how many entries the
    menu lists come out of the instructions that index it.  The three
    counted-string tables are told apart by *which* menu reads them: the
    first is the race menu's, then the class menu's, then the alignment
    menu's, in the order the routine asks the player.
    """
    at = creation_site(ovr, window)
    body = ovr[at:at + window]

    def one(pattern, group=1):
        m = re.search(pattern, body, re.S)
        return struct.unpack("<H", m.group(group))[0] if m else None

    tables = name_tables(body)

    def after(pattern):
        """The first name table read past the site `pattern` matches."""
        m = re.search(pattern, body, re.S)
        if m is None:
            return None
        return next((t for t in tables if t[0] >= m.start()), None)

    races = tables[0] if tables else None
    race_last = (re.search(_MENU_LAST, body[races[0]:], re.S)
                 if races else None)
    classes_at = one(_RACE_CLASSES)
    class_names = after(_RACE_CLASSES)
    alignments_at = one(_CLASS_ALIGNMENTS)
    alignment_names = after(_CLASS_ALIGNMENTS)

    limits: list[int] = []
    for m in re.finditer(_RACE_LIMITS, body, re.S):
        off = struct.unpack("<H", m.group(2))[0]
        if off not in limits:
            limits.append(off)
    # Only the sixteen bytes of one race's row are this table; a `shl di, 4`
    # somewhere else in the routine indexes something else.
    if limits:
        first = min(limits)
        limits = sorted(o for o in limits if first <= o < first + LIMIT_STRIDE)
    minimums = one(_CLASS_MINIMUMS)

    n_races = (race_last.group(2)[0] + 1) if race_last else 0

    def names(table, count=None):
        if table is None:
            return []
        if count is None:
            count = _entries(tables, table[2]) or 0
        return [pstring(image, ds, table[2] + table[1] * i)
                for i in range(count)]

    race_names = names(races, n_races)
    race_table_names = names(races)
    class_list = names(class_names)
    alignment_list = names(alignment_names)

    def counted(off, stride, n):
        base = ds * 16 + off
        out = []
        for i in range(n):
            row = image[base + stride * i:base + stride * i + stride]
            out.append(tuple(row[1:1 + row[0]]))
        return out

    per_race = counted(classes_at, 14, n_races) if classes_at else []
    used = sorted({c for row in per_race for c in row})
    per_class = (counted(alignments_at, 10, max(used) + 1)
                 if alignments_at and used else [])

    base = ds * 16 + min(limits) if limits else 0
    limit_rows = [tuple(image[base + LIMIT_STRIDE * r:
                              base + LIMIT_STRIDE * (r + 1)])
                  for r in range(n_races)] if limits else []
    min_base = ds * 16 + minimums if minimums else 0
    minimum_rows = ([tuple(image[min_base + 6 * c:min_base + 6 * c + 6])
                     for c in range(max(used) + 1)] if minimums and used
                    else [])

    prompt = re.search(_NAME_INPUT, body, re.S)
    name_max = copy_max = None
    if prompt:
        name_max = prompt.group(2)[0]
        after = re.search(_NAME_COPY, body[prompt.end():prompt.end() + 24],
                          re.S)
        copy_max = after.group(1)[0] if after else None

    return {
        "site": at,
        "races": race_names,
        "race_names_held": race_table_names,
        "race_table": races[2] if races else None,
        "race_stride": races[1] if races else None,
        "name_tables": [(s, o) for _, s, o in tables],
        "classes_by_race": per_race,
        "class_table": classes_at,
        "class_names": class_list,
        "class_name_table": class_names[2] if class_names else None,
        "alignments_by_class": per_class,
        "alignment_table": alignments_at,
        "alignment_names": alignment_list,
        "ability_limits": limit_rows,
        "ability_limit_table": min(limits) if limits else None,
        "ability_limit_columns": [off - min(limits) for off in limits],
        "class_minimum_table": minimums,
        "class_minimums": minimum_rows,
        "name_max": name_max,
        "name_copy_max": copy_max,
    }


# --- the commands ------------------------------------------------------------

def cmd_slots(a) -> int:
    ovr, image, ds = load(a.path)
    block, width = dosspellslots.block_of(RECORD_SIZE)
    site = dosspellslots.builder_site(ovr, block)
    names = {n: name for n, name, _ in _class_slot_names()}
    print(f"DS {ds:04X}, slot builder at {site:06X}, block {block:#05x} "
          f"x {width}, arrays {ARRAYS}")
    for branch in branches(ovr, site):
        print(f"\nclass {branch.number} {names.get(branch.number, '?')}: "
              f"rows from level {branch.from_level}, at {branch.at:06X}")
        for run in branch.runs:
            print(f"    DS:{run.table:04X} columns {run.first}-{run.last} "
                  f"-> record {run.dest + run.first - run.shift:#05x}-"
                  f"{run.dest + run.last - run.shift:#05x} "
                  f"({'assigned' if run.assigns else 'added'})")
        for which, table in rows(image, ds, branch, block, width,
                                 a.ceiling).items():
            print(f"  {which}:")
            for level, row in enumerate(table, start=1):
                print(f"    {level:2d}  " + " ".join(str(v) for v in row))
        bonus, caps = branch_gates(ovr, branch)
        for ability, score, gate, slot in bonus:
            print(f"  bonus: ability @{ability:#04x} above {score} "
                  f"-> +1 at record {slot:#05x}, when {gate:#05x} is not 0")
        for ability, score, slot in caps:
            print(f"  ceiling: ability @{ability:#04x} below {score} "
                  f"-> record {slot:#05x} zeroed")
    return 0


def _class_slot_names():
    from goldbox import dos_codec
    return dos_codec.CLASS_LEVEL_SLOTS


def cmd_spells(a) -> int:
    ovr, image, ds = load(a.path)
    table, last = spell_table(ovr, image, ds)
    print(f"DS {ds:04X}, spell table at DS:{table:04X}, ids 1-{last}")
    groups = spell_groups(image, ds, table, last)
    by_group: dict[tuple[str | None, int], list[int]] = {}
    for sid, key in groups.items():
        by_group.setdefault(key, []).append(sid)
    for key in sorted(by_group, key=lambda k: (k[0] or "~", k[1])):
        ids = by_group[key]
        runs, start, prev = [], ids[0], ids[0]
        for i in ids[1:]:
            if i == prev + 1:
                prev = i
            else:
                runs.append((start, prev))
                start = prev = i
        runs.append((start, prev))
        shown = ", ".join(f"{s}-{e}" if s != e else str(s) for s, e in runs)
        print(f"  {key[0] or 'not a spell':11s} level {key[1]}: "
              f"{len(ids):3d} ids  {shown}")
    spellbook = dos_port.layout_for(RECORD_SIZE)
    book = next(f for f in spellbook if f.name == "spellbook")
    print(f"  spellbook: record {book.offset:#05x}, {book.size} bytes, one "
          f"per id, so ids 1-{book.size} can be recorded")
    return 0


def cmd_menus(a) -> int:
    ovr, image, ds = load(a.path)
    found = menus(ovr, image, ds)
    print(f"DS {ds:04X}, creation at {found['site']:06X}")
    print("name tables read, (stride, DS offset): "
          + ", ".join(f"({s}, {o:#06x})" for s, o in found["name_tables"]))
    print(f"\nraces offered ({len(found['races'])} of "
          f"{len(found['race_names_held'])} the table holds): "
          + ", ".join(f"{i} {n}" for i, n in enumerate(found["races"])))
    held = found["race_names_held"][len(found["races"]):]
    if held:
        print("  in the table and not offered: " + ", ".join(
            f"{i + len(found['races'])} {n}" for i, n in enumerate(held)))
    print("\nclasses by race:")
    for i, (race, row) in enumerate(zip(found["races"],
                                        found["classes_by_race"])):
        print(f"  {i} {race:9s} {len(row):2d}: "
              + ", ".join(found["class_names"][c] for c in row))
    print("\nalignments by class:")
    for c, row in enumerate(found["alignments_by_class"]):
        print(f"  {c:2d} {found['class_names'][c]:26s} {len(row)}: "
              + ", ".join(found["alignment_names"][x] for x in row))
    print(f"\nracial ability limits, DS:{found['ability_limit_table']:04X}, "
          f"{LIMIT_STRIDE} bytes a race, read at columns "
          f"+{found['ability_limit_columns']}:")
    for race, row in zip(found["races"], found["ability_limits"]):
        print(f"  {race:9s} " + " ".join(f"{v:3d}" for v in row))
    print("\nclass ability minimums, DS:"
          f"{found['class_minimum_table']:04X}, six bytes a class "
          f"({' '.join(a[:3].upper() for a in ABILITIES)}):")
    for c, row in enumerate(found["class_minimums"]):
        print(f"  {c:2d} {found['class_names'][c]:26s} "
              + " ".join(f"{v:2d}" for v in row))
    print(f"\nname entry: the prompt accepts {found['name_max']} characters "
          f"and the copy into the record truncates at "
          f"{found['name_copy_max']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("slots", "spells", "menus"))
    ap.add_argument("--path", default=None, help="the game directory")
    ap.add_argument("--ceiling", type=int, default=CEILING,
                    help=f"slots: how many class levels to read (default "
                         f"{CEILING}, the engine's own clamp)")
    a = ap.parse_args(argv)
    return {"slots": cmd_slots, "spells": cmd_spells,
            "menus": cmd_menus}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
