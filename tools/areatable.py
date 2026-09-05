#!/usr/bin/env python3
"""Build a title's area table out of its own `ECL` scripts.

`#20 (Build an area table for Silver Blades)` is the ticket, and the model is
`goldbox/areas.py`: an area is a script, `ECL<id>`, and its row says which disk
side carries it, which `GEO` it puts on the screen, and where the game puts a
party that arrives in it.

Every number is read off the disks rather than carried over from Pool of
Radiance, because the one thing six Gold Box titles have taught this project is
that structure transfers and addresses do not:

* the **VM's opcode tables** come out of `DUNGEON` by the self-modifying
  dispatch `tools/newecl.py` finds, so `LOADFILES` is entry `$21` of this
  title's table and not a remembered address;
* the **script load address** is derived from the scripts themselves -- the
  five `GOTO`s at the head of every script name addresses inside it, so the
  only page-aligned base that puts all of them inside every script is the base.
  It is `$9900` in Pool of Radiance and `$8000` in Secret of the Silver Blades;
* the **disk side** is where the file actually sits in a directory, checked
  against what the scripts write to the loader's disk byte before a `NEWECL`.

    areatable.py pool-of-radiance                 the control
    areatable.py secret-of-the-silver-blades --disks DIR
    areatable.py secret-of-the-silver-blades --python   rows for goldbox/areas.py

**No string operand is ever printed as text.** These are the game's own words
and this tool's output goes into a repository that must not carry them; a
string prints as its length, exactly as `tools/eclwalk.py` does it.

`tools/eclwalk.py` is the fuller reader and is Pool of Radiance's alone -- it
hard-codes `$9900`, `POOL{n}.D64` and the sixty-two opcodes. This one asks the
same questions of any title and answers fewer of them.
"""

from __future__ import annotations

import argparse
import glob
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import disk_globs  # noqa: E402
from goldbox import games  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools import newecl  # noqa: E402

#: Where `LINKER` puts `DUNGEON`, in every title read so far. Not its header.
DUNGEON_BASE = 0x0800

EXIT, GOTO, GOSUB, SAVE, RETURN = 0x00, 0x01, 0x02, 0x09, 0x13
ONGOTO, ONGOSUB = 0x25, 0x26
NEWECL, LOADFILES, LOADPIECES = 0x20, 0x21, 0x37

#: Nothing runs after these.
NO_FALLTHROUGH = {EXIT, GOTO, RETURN, NEWECL}
#: A false condition skips the statement after these.
CONDITIONS = {0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B}
#: Opcodes carrying a count of further operands, and how many fixed operands
#: come first -- the count is the last of those. `tools/eclwalk.py` derived
#: these from Pool of Radiance's handlers; the handlers are the same routine in
#: every title read here, which is checked and reported by `--verify`.
COUNTED = {0x15: 3, 0x25: 2, 0x26: 2, 0x2B: 2}

#: Where Pool of Radiance's operand-count table disagrees with its own
#: handlers -- `docs/125-bug-notes.md` N2. Per title, because Silver Blades'
#: table has the right numbers in all three places and applying Pool of
#: Radiance's correction to it would be inventing a fourth.
HANDLER_OPERANDS = {
    "pool-of-radiance": {0x0C: 3, 0x29: 14, 0x36: 2},
}

#: The live party square, and it does not relocate: page `$C0` is `GDRIVE00`,
#: which is resident in Pool of Radiance, Curse and Silver Blades alike
#: (`docs/118-debug-mode.md`, `docs/121-silver-blades.md`).
MAP_X, MAP_Y, MAP_DIR = 0xC04B, 0xC04C, 0xC04D

#: "two paths reaching here disagree, or nothing wrote it". Not None,
#: because a `SAVE` whose value is computed rather than an immediate is
#: also unknown and must not read back as the byte zero.
UNSET = object()

#: Opcode names this project has established. An opcode nobody has named
#: prints as its number.
NAMES = {
    0x00: "EXIT", 0x01: "GOTO", 0x02: "GOSUB", 0x03: "COMPARE",
    0x05: "SUB", 0x06: "DIV", 0x08: "RANDOM", 0x09: "SAVE",
    0x0A: "LOADCHAR", 0x0C: "SETUPMON", 0x13: "RETURN",
    0x16: "IF=", 0x17: "IF<>", 0x18: "IF<", 0x19: "IF>",
    0x1A: "IF<=", 0x1B: "IF>=",
    0x20: "NEWECL", 0x21: "LOADFILES", 0x24: "COMBAT",
    0x25: "ONGOTO", 0x26: "ONGOSUB", 0x27: "TREASURE", 0x29: "ENCMENU",
    0x2D: "CALL", 0x2E: "DAMAGE", 0x34: "ECLCLOCK", 0x36: "ADDNPC",
    0x37: "LOADPIECES", 0x38: "PROGRAM", 0x3B: "SPELL",
}

#: The five entry addresses at the head of every script, named by the DOS
#: guide -- `docs/128-guide-and-scripting.md`.
ENTRY_NAMES = ["a step", "a step or LOOK", "before camping",
               "camp interrupted", "after loading"]


# -- the disks ---------------------------------------------------------------

def sides(root: str, game: games.Game) -> list[tuple[int, str]]:
    """`(side number, path)` for every side of this title under `root`.

    The number is the digit in the file name, which is what the loader prompts
    for and what a fast travel writes to the disk byte -- Curse's `CURSE_B` is
    side 2 and Silver Blades' `SILVER-2` is side 2. A side whose name carries
    no number, `POOLBOOT`, comes back as 0.
    """
    seen: dict[str, str] = {}
    for pattern in disk_globs(game):
        for path in glob.glob(os.path.join(root, pattern)):
            seen.setdefault(os.path.normcase(os.path.abspath(path)), path)
    out = []
    for path in sorted(seen.values()):
        stem = pathlib.Path(path).stem
        digits = "".join(c for c in stem if c.isdigit())
        letters = stem.rsplit("_", 1)[-1]
        if digits:
            number = int(digits)
        elif len(letters) == 1 and letters.isalpha():
            number = ord(letters.upper()) - ord("A") + 1
        else:
            number = 0
        out.append((number, path))
    return sorted(out)


def catalogue(root: str, game: games.Game) -> dict[str, list[int]]:
    """Every file on every side, and which sides carry it."""
    out: dict[str, list[int]] = {}
    for number, path in sides(root, game):
        try:
            image = D64.open(path)
        except Exception:
            continue
        for entry in image.iter_directory():
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            out.setdefault(name, []).append(number)
    return out


def read(root: str, game: games.Game, name: str) -> tuple[int, bytes] | None:
    """`(side, body)` for a game file, off the lowest-numbered side with it."""
    for number, path in sides(root, game):
        try:
            image = D64.open(path)
        except Exception:
            continue
        for entry in image.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == name:
                return number, image.read_file(name)[2:]
    return None


def script_names(root: str, game: games.Game) -> dict[str, int]:
    """Every `ECL<hex>` on the disks, and the side it is on.

    `ECL64` and `ECL65` are on every side of Silver Blades and on Pool of
    Radiance's side 1, and neither is an area script in either title: their
    first four bytes do not decode as the `GOTO` every script opens with.
    They are excluded by that test rather than by their names, so a title that
    numbers its common files differently is still read right.
    """
    out: dict[str, int] = {}
    for name, on in sorted(catalogue(root, game).items()):
        if not name.startswith("ECL") or len(name) != 5:
            continue
        try:
            int(name[3:], 16)
        except ValueError:
            continue
        out[name] = min(on)
    return out


# -- the machine -------------------------------------------------------------

class Machine:
    """This title's opcode tables, read out of its own `DUNGEON`."""

    def __init__(self, root: str, game: games.Game):
        got = read(root, game, "DUNGEON")
        if got is None:
            raise SystemExit(f"No DUNGEON on any {game.title} side "
                             f"under {root}.")
        _, body = got
        self.body = body
        self.base = DUNGEON_BASE
        call, lo, hi, opcode_at = newecl.dispatch_tables(body, self.base)
        self.dispatch, self.lo_table, self.hi_table = call, lo, hi
        self.opcode_at = opcode_at
        self.count = hi - lo
        at = hi + self.count - self.base
        self.table_operands = list(body[at:at + self.count])
        self.corrections = HANDLER_OPERANDS.get(game.key, {})

    def handler(self, op: int) -> int:
        return newecl.handler(self.body, self.base, self.lo_table,
                              self.hi_table, op)

    def operands(self, op: int) -> int:
        return self.corrections.get(op, self.table_operands[op])

    def shape(self, op: int, limit: int = 24) -> list[str]:
        """The handler's instructions with every address blanked."""
        out = []
        for _, _, text in newecl.instructions(self.body, self.base,
                                              self.handler(op), 0x60):
            out.append(newecl.operands(text))
            head = text.split(" ", 1)[0]
            if head in ("RTS", "RTI") or head == "JMP" or len(out) >= limit:
                break
        return out


# -- statements --------------------------------------------------------------

class Statement:
    __slots__ = ("at", "end", "op", "operands")

    def __init__(self, at, end, op, operands):
        self.at, self.end, self.op, self.operands = at, end, op, operands

    @property
    def name(self) -> str:
        return NAMES.get(self.op, f"OP${self.op:02X}")

    def immediate(self, n: int) -> int | None:
        """Operand `n` if it is a one-byte immediate, else None."""
        if n >= len(self.operands):
            return None
        kind, value = self.operands[n]
        return value if kind == 0x00 else None

    def address(self, n: int = 0) -> int | None:
        """Operand `n` as an address, or None if it is not one."""
        if n >= len(self.operands):
            return None
        kind, value = self.operands[n]
        return value if kind not in (0x00, 0x80) else None

    def text(self) -> str:
        return f"{self.name} " + ", ".join(
            _operand(k, v) for k, v in self.operands) if self.operands \
            else self.name


def _operand(kind: int, value: int) -> str:
    if kind == 0x00:
        return f"{value}"
    if kind == 0x80:
        return f'"{value} bytes"'
    if kind == 0x02:
        return f"#${value:04X}"
    return f"[${value:04X}]"


def _size(body: bytes, i: int):
    """How long the operand at `i` is, its kind and its value, or None.

    The rules are the VM's own operand decoder, which disassembles instruction
    for instruction identically in Pool of Radiance (`DUNGEON $1663`) and
    Silver Blades (`$171C`): kind `$00` is a one-byte immediate, kind `$80` an
    inline packed string with its length in the next byte, and everything else
    a two-byte address.
    """
    if i + 1 >= len(body):
        return None
    kind = body[i]
    if kind == 0x80:
        return 2 + body[i + 1], kind, body[i + 1]
    if kind == 0x00:
        return 2, kind, body[i + 1]
    if i + 2 >= len(body):
        return None
    return 3, kind, body[i + 1] | (body[i + 2] << 8)


def decode(machine: Machine, body: bytes, i: int) -> Statement | None:
    """The statement at offset `i`, or None if the bytes are not one."""
    if i >= len(body):
        return None
    op = body[i]
    if op >= machine.count:
        return None
    j = i + 1
    operands: list[tuple[int, int]] = []
    wanted = COUNTED.get(op) or machine.operands(op)
    for _ in range(wanted):
        got = _size(body, j)
        if got is None:
            return None
        size, kind, value = got
        operands.append((kind, value))
        j += size
    if op in COUNTED:
        kind, count = operands[-1]
        if kind != 0x00 or count > 64:
            return None
        for _ in range(count):
            got = _size(body, j)
            if got is None:
                return None
            size, kind, value = got
            operands.append((kind, value))
            j += size
    if j > len(body):
        return None
    return Statement(i, j, op, operands)


# -- one script --------------------------------------------------------------

class Script:
    """One area script, walked from its five entry points."""

    def __init__(self, machine: Machine, name: str, side: int,
                 body: bytes, base: int):
        self.machine, self.name, self.side = machine, name, side
        self.body, self.base = body, base
        self.statements: dict[int, Statement] = {}
        self.stuck: list[int] = []
        self.targets: set[int] = set()   # offsets something jumps or calls to
        self._walk()

    @property
    def id(self) -> int:
        return int(self.name[3:], 16)

    @property
    def entries(self) -> list[int | None]:
        out = []
        for n in range(5):
            statement = decode(self.machine, self.body, n * 4)
            if statement is None or statement.op != GOTO:
                out.append(None)
                continue
            target = statement.address()
            out.append(None if target is None else target - self.base)
        return out

    def _walk(self) -> None:
        work = [n * 4 for n in range(5)]
        while work:
            i = work.pop()
            if i in self.statements or not 0 <= i < len(self.body):
                continue
            statement = decode(self.machine, self.body, i)
            if statement is None or statement.end <= i:
                self.stuck.append(i)
                continue
            self.statements[i] = statement
            for successor, is_jump in self._successors(statement):
                if 0 <= successor < len(self.body):
                    if is_jump:
                        self.targets.add(successor)
                    work.append(successor)

    def _successors(self, statement: Statement) -> list[tuple[int, bool]]:
        """`(offset, is a jump)` for everything that can run after this."""
        op = statement.op
        out: list[tuple[int, bool]] = []
        if op in (GOTO, GOSUB):
            target = statement.address()
            if target is not None:
                out.append((target - self.base, True))
        if op in (ONGOTO, ONGOSUB):
            for n in range(COUNTED[op], len(statement.operands)):
                target = statement.address(n)
                if target is not None:
                    out.append((target - self.base, True))
        if op not in NO_FALLTHROUGH or op == GOSUB:
            out.append((statement.end, False))
        if op == ONGOTO:
            out.append((statement.end, False))
        if op in CONDITIONS:
            skipped = decode(self.machine, self.body, statement.end)
            if skipped is not None:
                out.append((skipped.end, False))
        return out

    @property
    def reached(self) -> int:
        return sum(s.end - s.at for s in self.statements.values())

    def ordered(self) -> list[Statement]:
        return [self.statements[i] for i in sorted(self.statements)]

    # -- what the area table wants ------------------------------------------

    def loadfiles(self) -> list[tuple[int, tuple[int | None, ...]]]:
        """Every `LOADFILES`, as `(offset, three operands)`.

        An operand that is not a one-byte immediate comes back None rather
        than a guess: the handler takes the value from a variable in that case
        and no static reading can say what it will be.
        """
        out = []
        for s in self.ordered():
            if s.op == LOADFILES:
                out.append((s.at, tuple(s.immediate(n) for n in range(3))))
        return out

    def geos(self) -> list[int]:
        """The map ids this script statically loads, in order, once each.

        `$FF` is `LOADFILES`' "leave the map alone" -- `docs/118-debug-mode.md`
        -- and `$7F` is the same for the other two slots, so neither is a map.
        """
        out: list[int] = []
        for _, (geo, _, _) in self.loadfiles():
            if geo is None or geo in (0xFF, 0x7F) or geo in out:
                continue
            out.append(geo)
        return out

    def exits(self, disk_byte: int) -> list["Exit"]:
        """`NEWECL` by `NEWECL`, with what is certain about the block before it.

        A departing script writes the destination's disk and, often, the
        square the party is to stand on when it gets there, immediately before
        the `NEWECL` -- `docs/118-debug-mode.md`, and it is where sixteen of
        Pool of Radiance's arrival squares came from.

        **Address order is not execution order**, so this is a forward
        propagation over the script's own control-flow graph rather than a
        sweep: four values (the disk byte and the three bytes of the live
        party square) are carried along every edge the walk found, an
        immediate `SAVE` sets one, a computed `SAVE` clears it, and where two
        paths meet a value survives only if both agree. A `NEWECL` then
        reports what is true on **every** path that can reach it.

        Sweeping in address order instead both invents and loses: Silver
        Blades' `ECL30` hands its own entry-4 square to a `NEWECL` forty
        statements below it that no path reaches from there, and clearing at
        each block boundary to stop that drops Pool of Radiance's `ECL1B`
        arrival square for area `$0D`, which is real.
        """
        watched = (disk_byte, MAP_X, MAP_Y, MAP_DIR)
        unknown = (UNSET,) * 4
        state: dict[int, tuple] = {}
        work = []
        for entry in self.entries:
            if entry is not None and entry in self.statements:
                state[entry] = unknown
                work.append(entry)
        while work:
            at = work.pop()
            here = state[at]
            s = self.statements[at]
            after = list(here)
            if s.op == SAVE:
                where = s.address(1)
                if where in watched:
                    after[watched.index(where)] = s.immediate(0) \
                        if s.immediate(0) is not None else UNSET
            after = tuple(after)
            for successor, _ in self._successors(s):
                if successor not in self.statements:
                    continue
                was = state.get(successor)
                merged = after if was is None else tuple(
                    a if a == b else UNSET for a, b in zip(was, after))
                if merged != was:
                    state[successor] = merged
                    work.append(successor)
        out = []
        for s in self.ordered():
            if s.op != NEWECL:
                continue
            target = s.immediate(0)
            if target is None or s.at not in state:
                continue
            disk, x, y, facing = state[s.at]
            out.append(Exit(self.name, s.at, target,
                            None if disk is UNSET else disk,
                            tuple(None if v is UNSET else v
                                  for v in (x, y, facing))))
        return out

    def arrival(self) -> tuple[int | None, int | None, int | None]:
        """`(x, y, facing)` this script sets for a party arriving in it.

        Entry 4 is the area-initialisation entry -- `docs/118-debug-mode.md`
        -- and the run it starts is followed statement by statement: a `GOTO`
        is followed, a conditional's guarded statement is stepped over (the
        arm taken when the party is *not* re-entering the area it left), and
        `EXIT`, `RETURN` and `NEWECL` end it. A `SAVE ..., mapX` deep inside
        an encounter is not where an arriving party lands and is not read.
        """
        entry = self.entries[4]
        if entry is None:
            return (None, None, None)
        x = y = facing = None
        at = entry
        seen = 0
        while at in self.statements and seen < 128:
            s = self.statements[at]
            seen += 1
            if s.op == SAVE:
                where, value = s.address(1), s.immediate(0)
                if where == MAP_X:
                    x = value
                elif where == MAP_Y:
                    y = value
                elif where == MAP_DIR:
                    facing = value
            if s.op == GOTO:
                target = s.address()
                if target is None:
                    break
                at = target - self.base
                continue
            if s.op in CONDITIONS:
                guarded = decode(self.machine, self.body, s.end)
                at = s.end if guarded is None else guarded.end
                continue
            if s.op in NO_FALLTHROUGH:
                break
            at = s.end
        return (x, y, facing)


class Exit:
    """One `NEWECL`, and the disk and square the block before it set."""

    __slots__ = ("script", "at", "target", "disk", "square")

    def __init__(self, script, at, target, disk, square):
        self.script, self.at, self.target = script, at, target
        self.disk, self.square = disk, square

    @property
    def places(self) -> bool:
        return self.square[0] is not None and self.square[1] is not None

    def __str__(self) -> str:
        out = f"${self.target:02X}"
        if self.disk is not None:
            out += f"/d{self.disk}"
        if self.places:
            x, y, facing = self.square
            out += f"@{x},{y}"
            if facing is not None and facing < 4:
                out += "NESW"[facing]
        return out


def script_base(machine: Machine, bodies: dict[str, bytes]) -> int:
    """Where this title's scripts run, from the scripts themselves.

    Every script opens with five `GOTO`s whose targets are inside it, so a
    base must be at or below the lowest target and high enough that the
    highest target in each script is still within that script's length. That
    leaves a window, and exactly one page boundary falls in it: `$9900` for
    Pool of Radiance, `$8000` for Secret of the Silver Blades.
    """
    low = 0x10000
    high = 0
    for body in bodies.values():
        targets = []
        for n in range(5):
            statement = decode(machine, body, n * 4)
            if statement is None or statement.op != GOTO:
                continue
            target = statement.address()
            if target is not None:
                targets.append(target)
        if not targets:
            continue
        low = min(low, min(targets))
        high = max(high, max(targets) - len(body) + 1)
    pages = [p for p in range(high + 0xFF & ~0xFF, low + 1, 0x100)]
    if len(pages) != 1:
        raise SystemExit(
            f"The script base is not pinned: {len(pages)} page boundaries "
            f"fall between ${high:04X} and ${low:04X}. Do not trust an "
            f"address decoded from here.")
    return pages[0]


# -- reporting ---------------------------------------------------------------

def verify(machine: Machine, control: Machine) -> list[str]:
    """Lines saying how far this title's VM agrees with the control's."""
    out = []
    shared = min(machine.count, control.count)
    same = sum(1 for op in range(shared)
               if machine.shape(op) == control.shape(op))
    out.append(f"  handlers identical bar their operands: {same} of {shared} "
               f"opcodes ({machine.count} here, {control.count} there)")
    for op in sorted(set(COUNTED) | set(HANDLER_OPERANDS.get("pool-of-radiance", {}))):
        if op >= shared:
            continue
        agree = "same" if machine.shape(op) == control.shape(op) else "DIFFERS"
        out.append(f"    ${op:02X} {NAMES.get(op, ''):10s} "
                   f"table says {machine.table_operands[op]} here, "
                   f"{control.table_operands[op]} there; handler {agree}")
    return out


def load_scripts(root: str, game: games.Game, machine: Machine
                 ) -> tuple[int, dict[str, Script]]:
    bodies: dict[str, bytes] = {}
    where: dict[str, int] = {}
    for name, side in script_names(root, game).items():
        got = read(root, game, name)
        if got is None:
            continue
        _, body = got
        statement = decode(machine, body, 0)
        if statement is None or statement.op != GOTO:
            continue                     # not an area script; ECL64, ECL65
        bodies[name] = body
        where[name] = side
    base = script_base(machine, bodies)
    return base, {n: Script(machine, n, where[n], b, base)
                  for n, b in bodies.items()}


def report(game: games.Game, root: str, control: games.Game | None,
           as_python: bool) -> int:
    machine = Machine(root, game)
    catalogue_ = catalogue(root, game)
    base, scripts = load_scripts(root, game, machine)

    if not as_python:
        print(f"{game.title}")
        print(f"  DUNGEON at ${machine.base:04X}, {machine.count} opcodes, "
              f"handlers ${machine.lo_table:04X}/${machine.hi_table:04X}, "
              f"counts ${machine.hi_table + machine.count:04X}")
        print(f"  scripts run at ${base:04X}, {len(scripts)} of them")
        if control is not None:
            found = registry(control.key)
            other = pathlib.Path(found) if found else None
            if other is not None:
                for line in verify(machine, Machine(str(other), control)):
                    print(line)

    disk_byte = DISK_BYTES.get(game.key)
    if disk_byte is None:
        print(f"  (no disk byte known for {game.title}; the disk column "
              f"comes from the directory alone)")

    geo_side = {name: min(on) for name, on in catalogue_.items()
                if name.startswith("GEO")}

    rows = []
    for name in sorted(scripts):
        s = scripts[name]
        rows.append((s, s.geos(), s.arrival(),
                     s.exits(disk_byte) if disk_byte else []))

    # Where a departing script places the party, gathered per destination.
    placed: dict[int, dict[tuple, list[str]]] = {}
    for s, _, _, exits in rows:
        for e in exits:
            if e.places:
                placed.setdefault(e.target, {}).setdefault(
                    e.square, []).append(f"{s.name}+${e.at:04X}")

    def settled(area_id, own):
        """The one square everything agrees on for this area, or None."""
        votes = dict(placed.get(area_id, {}))
        if own[0] is not None and own[1] is not None:
            votes.setdefault(own, []).append("its own entry 4")
        if len(votes) == 1:
            return next(iter(votes)), votes
        return None, votes

    if as_python:
        for s, geos, own, _ in rows:
            square, _votes = settled(s.id, own)
            names = ", ".join(f'"GEO{g:02X}"' for g in geos)
            names = f"({names},)" if len(geos) == 1 else f"({names})"
            if square is None:
                arrival = "None"
            else:
                x, y, facing = square
                arrival = (f"Arrival({x}, {y}, {facing})"
                           if facing is not None else f"Arrival({x}, {y})")
            print(f"    _a(0x{s.id:02X}, None, {s.side}, {names}, {arrival}, "
                  f"U),   # {s.name}")
        return 0

    print()
    print(f"{'area':>5} {'ECL':7} {'side':>4} {'bytes':>6} {'reach':>6} "
          f"{'maps':16} {'arrival':12} exits")
    for s, geos, own, exits in rows:
        maps = ", ".join(f"GEO{g:02X}" for g in geos) or "-"
        square, votes = settled(s.id, own)
        if square is None:
            arrival = "-" if not votes else f"{len(votes)} disagree"
        else:
            x, y, facing = square
            arrival = f"{x},{y}" + (f" {'NESW'[facing]}"
                                    if facing is not None and facing < 4
                                    else "")
        reach = 100.0 * s.reached / len(s.body)
        print(f"  ${s.id:02X} {s.name:7} {s.side:>4} {len(s.body):>6} "
              f"{reach:5.1f}% {maps:16} {arrival:12} "
              f"{', '.join(str(e) for e in exits) or '-'}")

    total = sum(len(s.body) for s, _, _, _ in rows)
    got = sum(s.reached for s, _, _, _ in rows)
    print(f"\n  walked {100.0 * got / total:.2f}% of {total} bytes; "
          f"{sum(len(s.stuck) for s, _, _, _ in rows)} offsets did not decode")

    print("\n  arrival squares, and who names them:")
    for s, _, own, _ in rows:
        square, votes = settled(s.id, own)
        if not votes:
            continue
        mark = " " if square is not None else "!"
        for sq, by in sorted(votes.items(), key=lambda kv: str(kv[0])):
            x, y, facing = sq
            where = f"{x},{y}" + (f" {'NESW'[facing]}"
                                  if facing is not None and facing < 4 else "")
            print(f"  {mark} ${s.id:02X} {where:10} <- {', '.join(by)}")

    print("\n  maps, and the side each file is on:")
    claimed: dict[int, list[str]] = {}
    for s, geos, _, _ in rows:
        for g in geos:
            claimed.setdefault(g, []).append(s.name)
    for g in sorted(set(claimed) | {int(n[3:], 16) for n in geo_side}):
        name = f"GEO{g:02X}"
        on = geo_side.get(name)
        by = ", ".join(claimed.get(g, [])) or "no script loads it"
        print(f"    {name}  side {on if on else '-'}  {by}")

    if disk_byte:
        print(f"\n  disk byte ${disk_byte:04X}: every static "
              f"SAVE n, [${disk_byte:04X}] before a NEWECL, against the side "
              f"the target script is on:")
        agree = disagree = unset = 0
        for s, _, _, exits in rows:
            for e in exits:
                on = scripts.get(f"ECL{e.target:02X}")
                if e.disk is None:
                    unset += 1
                elif on is not None and on.side == e.disk:
                    agree += 1
                else:
                    disagree += 1
                    print(f"    {s.name} -> ECL{e.target:02X}: writes "
                          f"{e.disk}, file is on side "
                          f"{on.side if on else 'no such script'}")
        print(f"    {agree} agree, {disagree} disagree, {unset} with no "
              f"disk written in the same block")
    return 0


#: What the loader reads to decide which side to ask for, per title. Both were
#: read off `LINKER`'s own dispatch by `tools/newecl.py` and neither is a
#: guess; a title not here still gets its table, without the cross-check.
DISK_BYTES = {
    "pool-of-radiance": 0x6E12,
    "curse-of-the-azure-bonds": 0x7F12,
    "secret-of-the-silver-blades": 0x7F12,
}


def registry(key: str) -> str:
    """`tools/gamedisks.py`'s answer for this title, or "".

    Second, after `--disks`/`$POR_DISKS`. `automap.paths.find_disks` is the
    *player's* search and looks for a directory named after the game; nobody
    names one that, so it finds Pool of Radiance and neither of the other two
    -- `#251 (Curse's and Silver Blades' disks are where nothing looks for
    them, so every per-title test skips)`. This tool is ours, so it asks the
    registry rather than the player's lookup.
    """
    try:
        import gamedisks
    except ImportError:                     # pragma: no cover - defensive
        return ""
    found = gamedisks.find(key)
    return str(found) if found else ""


def main(argv: list[str]) -> int:
    keys = [g.key for g in games.GAMES]
    ap = argparse.ArgumentParser(
        description="Build a title's area table from its own ECL scripts.")
    ap.add_argument("game", choices=keys)
    ap.add_argument("--disks", default=os.environ.get("POR_DISKS"),
                    metavar="DIR", help="where that title's disks are")
    ap.add_argument("--against", choices=keys, default=None,
                    help="check the VM against this title's, opcode by opcode")
    ap.add_argument("--python", action="store_true",
                    help="print rows for goldbox/areas.py instead of a table")
    args = ap.parse_args(argv[1:])

    game = next(g for g in games.GAMES if g.key == args.game)
    root = args.disks or registry(game.key)
    if not root or not os.path.isdir(root):
        print(f"No {game.title} disks. Set $POR_DISKS or pass --disks.",
              file=sys.stderr)
        return 2
    control = (next(g for g in games.GAMES if g.key == args.against)
               if args.against else None)
    return report(game, root, control, args.python)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
