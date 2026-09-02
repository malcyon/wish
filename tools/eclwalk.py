#!/usr/bin/env python3
"""Read an area script statement by statement, and say what each exit runs.

The `ECL` scripts are bytecode for a virtual machine inside `DUNGEON`, and
every number this needs is read out of `DUNGEON` itself at run time rather than
written down here:

* `$15A9` (low) and `$15E7` (high) are the handler address per opcode, `$1625`
  the operand count. Sixty-two opcodes, `$00`-`$3D`.
* `$1663` decodes one operand and says how long it is. Kind `$00` is a
  one-byte immediate, kind `$80` an inline packed string with its length in the
  next byte, and every other kind is a two-byte address. So an operand is 2, 3
  or `2 + len` bytes and nothing else.
* `$1625` is the count the engine's own *skip* routine uses, and for three
  opcodes it disagrees with the handler -- `SETUPMON`, `ENCMENU` and `ADDNPC`,
  `docs/125-bug-notes.md` N2. `HANDLER_OPERANDS` carries the handlers' real
  counts. Four more opcodes are variable length: the two menus and the two
  `ON` jumps each carry a count operand and then that many more.

A script is walked from its five entry addresses, following `GOTO`, `GOSUB`,
`ONGOTO` and `ONGOSUB` and both arms of every `IF`, rather than swept linearly:
a linear sweep runs into the data tables `$2A` indexes and turns them into
nonsense. What the walk does not reach is reported as a percentage, and on the
thirty area scripts the walk reaches 98% of all bytes with the rest accounted
for by those tables. Do not trust that figure from here: `eclwalk.py list`
prints the measured one, and this sentence said 94% until 2026-09-02, when a
run showed 98.04%.

**Why this exists.** `FastTravel` enters `NEWECL` at its tail, `$2034`, which
is past everything the departing script would have run -- see
`docs/150-departing-prologues.md`. `exits` prints, per script and per exit,
exactly the statements that get skipped.

    eclwalk.py list                 every script, and how much of it was reached
    eclwalk.py listing ECL00        every statement the walk reached
    eclwalk.py exits                every NEWECL, with the statements before it
    eclwalk.py exits ECL00 ECL14    the same, for named scripts

No string is printed as text: these are the game's own words, and this tool's
output goes into a repository that must not carry them. A string operand prints
as its length.
"""
import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from automap.paths import find_disks  # noqa: E402
from goldbox.d64 import D64  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or (find_disks() or ""))

#: Where a script is loaded, `docs/140-loaded-files-cache.md` slot 8.
BASE = 0x9900
#: Where `DUNGEON` runs, `docs/118-debug-mode.md`; its PRG header says `$1000`.
DUNGEON_BASE = 0x0800
OPCODES = 62
HANDLER_LO, HANDLER_HI, OPERAND_COUNT = 0x15A9, 0x15E7, 0x1625

#: The three the operand-count table gets wrong, read off the handlers.
#: `docs/125-bug-notes.md` N2.
HANDLER_OPERANDS = {0x0C: 3, 0x29: 14, 0x36: 2}
#: Opcodes that carry a count of further operands, and how many fixed
#: operands come first. The count is the last of those. `$15` differs from
#: `$2B` by one because `DUNGEON $18AD` prints a prompt operand on that arm
#: and `$18AB` branches over it on the other.
COUNTED = {0x15: 3, 0x25: 2, 0x26: 2, 0x2B: 2}
#: Nothing runs after these, so the next statement begins a new block.
NO_FALLTHROUGH = {0x00, 0x01, 0x13, 0x20}
#: A false condition skips the statement after these.
CONDITIONS = {0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B}

EXIT, GOTO, GOSUB, RETURN = 0x00, 0x01, 0x02, 0x13
ONGOTO, ONGOSUB = 0x25, 0x26
NEWECL, LOADFILES, LOADPIECES = 0x20, 0x21, 0x37

#: Only the mnemonics this repository has already established, from
#: `docs/118-debug-mode.md`, `docs/128-guide-and-scripting.md` and
#: `docs/50-experiments.md`. An opcode nobody has named prints as its number,
#: because a guessed name is what `$1F` cost us.
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


# -- reading the disks --------------------------------------------------------

def _file(name, sides=("POOLBOOT", *[f"POOL{i}" for i in range(1, 9)])):
    for side in sides:
        path = DISKS / f"{side}.D64"
        if not path.exists():
            continue
        img = D64.open(path)
        for entry in img.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == name:
                return side, img.read_file(name)[2:]
    return None, None


def scripts():
    """Every area script, by name, with the side it was read from.

    `ECL64` and `ECL65` are not area scripts -- `64` is the machine, not an
    area (`docs/140-loaded-files-cache.md`) -- and neither loads at `$9900`.
    """
    out = {}
    for n in range(1, 9):
        path = DISKS / f"POOL{n}.D64"
        if not path.exists():
            continue
        img = D64.open(path)
        for entry in img.iter_directory():
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            if not name.startswith("ECL") or name in out:
                continue
            if name[3:] in ("64", "65"):
                continue
            out[name] = (f"POOL{n}", img.read_file(name)[2:])
    return dict(sorted(out.items()))


class Machine:
    """The opcode tables, read out of `DUNGEON`."""

    def __init__(self):
        _, body = _file("DUNGEON")
        if body is None:
            raise SystemExit("No DUNGEON on any side. Set $POR_DISKS.")
        at = lambda a, n: body[a - DUNGEON_BASE:a - DUNGEON_BASE + n]  # noqa: E731
        self.handler = [lo | (hi << 8) for lo, hi in
                        zip(at(HANDLER_LO, OPCODES), at(HANDLER_HI, OPCODES))]
        self.table_operands = list(at(OPERAND_COUNT, OPCODES))
        # Every handler address has to land inside DUNGEON itself.  One that
        # does not means the tables were read from the wrong offsets -- a
        # different build, or a DUNGEON that is not this one -- and every
        # operand count below it would then be somebody else's bytes.  Refuse
        # rather than decode confidently from them.
        top = DUNGEON_BASE + len(body)
        stray = [(op, a) for op, a in enumerate(self.handler)
                 if not DUNGEON_BASE <= a < top]
        if stray:
            op, a = stray[0]
            raise SystemExit(
                f"DUNGEON's handler table is not where this expects it: "
                f"opcode {op:#04x} points at ${a:04X}, outside "
                f"${DUNGEON_BASE:04X}-${top - 1:04X}. "
                f"{len(stray)} of {OPCODES} opcodes are out of range.")

    def operands(self, op):
        return HANDLER_OPERANDS.get(op, self.table_operands[op])


# -- one statement ------------------------------------------------------------

class Statement:
    __slots__ = ("at", "end", "op", "operands")

    def __init__(self, at, end, op, operands):
        self.at, self.end, self.op, self.operands = at, end, op, operands

    @property
    def address(self):
        return BASE + self.at

    @property
    def name(self):
        return NAMES.get(self.op, f"OP${self.op:02X}")

    def target(self, n=0):
        """Operand `n` as a script address, or None if it is not one."""
        kind, value = self.operands[n]
        return value if kind not in (0x00, 0x80) else None

    def __str__(self):
        return f"{self.name} " + ", ".join(
            _operand(k, v) for k, v in self.operands) if self.operands \
            else self.name


def _operand(kind, value):
    if kind == 0x00:
        return f"{value}"
    if kind == 0x80:
        return f'"{value} bytes"'
    if kind == 0x02:
        return f"#${value:04X}"
    return f"[${value:04X}]"


def _size(body, i):
    """How long the operand at offset `i` is and what it holds, or None.

    None means the operand runs off the end of the body, which is not a
    statement and must not be guessed at.  An address operand is three bytes
    and the caller has only proved two are there, so the check belongs here.
    """
    kind = body[i]
    if kind == 0x80:
        return 2 + body[i + 1], kind, body[i + 1]
    if kind == 0x00:
        return 2, kind, body[i + 1]
    if i + 2 >= len(body):
        return None
    return 3, kind, body[i + 1] | (body[i + 2] << 8)


def decode(machine, body, i):
    """The statement at offset `i`, or None if the bytes are not one."""
    op = body[i]
    if op >= OPCODES:
        return None
    j = i + 1
    operands = []
    wanted = COUNTED.get(op) or machine.operands(op)
    for _ in range(wanted):
        if j + 1 >= len(body):
            return None
        got = _size(body, j)
        if got is None:
            return None
        size, kind, value = got
        operands.append((kind, value))
        j += size
    if op in COUNTED:
        last = operands[-1]
        count = last[1] if last[0] == 0x00 else None
        if count is None or count > 64:
            return None
        for _ in range(count):
            if j + 1 >= len(body):
                return None
            got = _size(body, j)
            if got is None:
                return None
            size, kind, value = got
            operands.append((kind, value))
            j += size
    if j > len(body):
        return None
    return Statement(i, j, op, operands)


# -- the walk -----------------------------------------------------------------

class Script:
    """One area script, walked from its five entry points."""

    def __init__(self, machine, name, side, body):
        self.machine, self.name, self.side, self.body = machine, name, side, body
        self.statements = {}        # offset -> Statement
        self.stuck = []             # offsets the walk could not decode
        self.targets = set()        # offsets something jumps or calls to
        self._walk()

    @property
    def entries(self):
        """The five entry offsets, from the `GOTO`s at the head of the file."""
        out = []
        for n in range(5):
            statement = decode(self.machine, self.body, n * 4)
            out.append(None if statement is None or statement.op != GOTO
                       else statement.target() - BASE)
        return out

    def _walk(self):
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

    def _successors(self, statement):
        op = statement.op
        out = []
        if op in (GOTO, GOSUB):
            target = statement.target()
            if target is not None:
                out.append((target - BASE, True))
        if op in (ONGOTO, ONGOSUB):
            for n in range(COUNTED[op], len(statement.operands)):
                target = statement.target(n)
                if target is not None:
                    out.append((target - BASE, True))
        if op not in NO_FALLTHROUGH or op == GOSUB:
            out.append((statement.end, False))
        if op == ONGOTO:
            # An index past the end of the list falls out of the statement.
            out.append((statement.end, False))
        if op in CONDITIONS:
            skipped = decode(self.machine, self.body, statement.end)
            if skipped is not None:
                out.append((skipped.end, False))
        return out

    @property
    def reached(self):
        return sum(s.end - s.at for s in self.statements.values())

    def ordered(self):
        return [self.statements[i] for i in sorted(self.statements)]

    def block_of(self, statement):
        """The statements from the start of `statement`'s block up to it.

        A block starts after anything that does not fall through, and at
        anything something jumps to or enters at. Conditions do **not** end a
        block: a false `IF` skips the one statement after it, and `FastTravel`
        skips the condition as well as what it guards, so the honest answer to
        "what did not happen" is the whole run with its guards still in it.
        """
        order = sorted(self.statements)
        n = order.index(statement.at)
        entries = {e for e in self.entries if e is not None}
        first = n
        while first > 0:
            previous = self.statements[order[first - 1]]
            if previous.end != order[first]:
                break                       # not contiguous: a new block
            if previous.op in NO_FALLTHROUGH:
                break
            if order[first] in self.targets or order[first] in entries:
                break
            first -= 1
        return [self.statements[a] for a in order[first:n + 1]]

    def predecessors(self, statement):
        """The blocks that reach `statement`'s block from somewhere else.

        A `NEWECL` that something jumps to has more than one departing
        prologue: which statements ran depends on the route in. One level is
        reported, which is enough to see the exits `ECL06` guards on facing.
        """
        block = self.block_of(statement)
        head = block[0].at
        if head == statement.at and head not in self.targets:
            return []
        out = []
        for other in self.ordered():
            if other.at == head:
                continue
            if any(succ == head for succ, _ in self._successors(other)):
                run = self.block_of(other)
                if run and run[0].at != head:
                    out.append(run)
        return out

    def exits(self):
        """Every `NEWECL`, with the block that runs into it."""
        return [(s, self.block_of(s))
                for s in self.ordered() if s.op == NEWECL]


# -- the commands -------------------------------------------------------------

def cmd_list(machine, chosen):
    print(f"{'script':8s} {'side':6s} {'bytes':>6s} {'stmts':>6s} "
          f"{'reached':>8s} {'exits':>6s}  entries")
    for name, (side, body) in chosen.items():
        script = Script(machine, name, side, body)
        entries = " ".join("----" if e is None else f"{BASE + e:04X}"
                           for e in script.entries)
        print(f"{name:8s} {side:6s} {len(body):6d} {len(script.statements):6d} "
              f"{script.reached / len(body):7.1%} "
              f"{len(script.exits()):6d}  {entries}")


def cmd_listing(machine, chosen):
    for name, (side, body) in chosen.items():
        script = Script(machine, name, side, body)
        entries = {e: n for n, e in enumerate(script.entries) if e is not None}
        print(f"{name} on {side}, {len(body)} bytes at ${BASE:04X}")
        for statement in script.ordered():
            mark = ""
            if statement.at in entries:
                mark = f"   <- entry {entries[statement.at]}, {ENTRY_NAMES[entries[statement.at]]}"
            elif statement.at in script.targets:
                mark = "   <-"
            print(f"  ${statement.address:04X}  {statement}{mark}")
        for at in sorted(script.stuck):
            print(f"  ${BASE + at:04X}  ** not decodable **")


def cmd_exits(machine, chosen):
    for name, (side, body) in chosen.items():
        script = Script(machine, name, side, body)
        entries = {e: n for n, e in enumerate(script.entries) if e is not None}
        print(f"{name} on {side}")
        for statement, block in script.exits():
            area = statement.operands[0][1] if statement.operands[0][0] == 0 \
                else None
            where = f"area {area}" if area is not None else "a computed area"
            print(f"  ${statement.address:04X}  to {where}, "
                  f"{len(block) - 1} statement(s) skipped before it")
            for line in block:
                print(f"      ${line.address:04X}  {line}"
                      + ("   <- entry point" if line.at in entries else ""))
            for run in script.predecessors(statement):
                print(f"      -- and, arriving from ${BASE + run[0].at:04X}:")
                for line in run:
                    print(f"      ${line.address:04X}  {line}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("list", "listing", "exits"))
    parser.add_argument("script", nargs="*", help="ECL00 … ; default is all")
    args = parser.parse_args()
    if not DISKS or not DISKS.exists():
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    every = scripts()
    if not every:
        raise SystemExit("No ECL files on those disks.")
    chosen = {k: v for k, v in every.items()
              if not args.script or k in args.script}
    if not chosen:
        raise SystemExit(f"No such script: {' '.join(args.script)}")
    machine = Machine()
    {"list": cmd_list, "listing": cmd_listing, "exits": cmd_exits}[
        args.command](machine, chosen)


if __name__ == "__main__":
    main()
