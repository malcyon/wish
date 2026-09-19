#!/usr/bin/env python3
"""Read one area script: its statements, an opcode's 6502 handler, and which
of its `COMBAT` statements a given saved game can actually reach.

`#334 (The session driver cannot fight in Curse or Silver Blades, and says the
party is not in a fight while it is standing on the combat floor)` is the
ticket, and the gap is the reason for the file. `tools/areas/eclcensus.py` answers
"which addresses does this title's scripts name" and `--sites` prints the
statements naming one; neither prints a **run of statements from an offset**,
which is what every reading on that ticket wanted, and four of them were done
by hand. `tools/areas/ecltext.py` decodes the strings. This one decodes the code.

    ecllist.py secret-of-the-silver-blades ECL10 --at 8513 --count 40
    ecllist.py secret-of-the-silver-blades ECL10 --walk
    ecllist.py secret-of-the-silver-blades ECL10 --at 8571 --raw 48
    ecllist.py secret-of-the-silver-blades --handler 09 --count 20
    ecllist.py secret-of-the-silver-blades ECL10 --combat --save FILE.D64

`--at` takes the address the script runs at (`$8000` upward on the three C64
titles) or the offset within the file; anything at or above the script base is
read as the former. `--raw` dumps bytes instead, which is how an operand's
**kind** byte gets read -- `$00` immediate byte, `$01` byte variable, `$02`
immediate word, `$03` word variable, `$80` string -- and the kind is what says
whether a store touches one byte or two.

`--handler` disassembles the 6502 routine behind an opcode, found through
`tools/areas/newecl.py`'s self-modifying dispatch rather than by an address anybody
wrote down. That is what settles a question like "does `SAVE` into a byte
variable clobber its neighbour" from the engine instead of from plausibility.

`--combat` walks every arm of an entry's `ONGOTO` with a real `SAVEDBASH` in
hand, evaluating each `COMPARE`/`IF` pair against the save's own bytes and
branching both ways only where a value is genuinely unknown (a `RANDOM`, a
menu answer, an engine variable). It prints the arms that can reach a
`COMBAT`, and the decisions still open on the way -- the question "which
square in this area fights *this* party" answered from the file.

It prints no string of the game's as text: a string operand prints as
`str(<length>)`, the way `eclcensus.py` does.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools.areas import newecl  # noqa: E402
from tools.areas.eclcensus import (  # noqa: E402
    CONDITIONS,
    DESTINATIONS,
    DUNGEON_BASE,
    OPCODE_NAMES,
    Machine,
    c64_file,
    c64_scripts,
    decode,
    script_base,
)
from tools.c64 import d6502  # noqa: E402

EXIT, GOTO, GOSUB, RETURN, NEWECL, COMBAT = 0x00, 0x01, 0x02, 0x13, 0x20, 0x24
COMPARE = 0x03
IF_EQ, IF_NE, IF_LT, IF_GT, IF_LE, IF_GE = 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B
ONGOTO, ONGOSUB, HORIZMENU = 0x25, 0x26, 0x2B
AND, OR = 0x2F, 0x30

#: `AND` and `OR` latch the status register too -- their handlers end
#: `PHA / JSR <the latch> / PLA`, and the latch is `PHP / PLA / STA $7F45`.
#: Only the zero flag is theirs, though: the carry is whatever it was before,
#: so a following `IF<`, `IF>`, `IF<=` or `IF>=` is reading a stale compare
#: and is left open here rather than guessed at.
BITWISE_TESTS = {IF_EQ: lambda r: r == 0, IF_NE: lambda r: r != 0}

#: Nothing runs after these, so a walk does not fall through them.
NO_FALLTHROUGH = {EXIT, GOTO, RETURN, NEWECL}

#: How a condition compares the two values `COMPARE` latched.
TESTS = {
    IF_EQ: lambda a, b: a == b, IF_NE: lambda a, b: a != b,
    IF_LT: lambda a, b: a < b, IF_GT: lambda a, b: a > b,
    IF_LE: lambda a, b: a <= b, IF_GE: lambda a, b: a >= b,
}


def load(title: str, disks: str | None = None):
    """`(game, root, machine, base, {name: body})` for one C64 title."""
    game = None
    for candidate in c64_port.GAMES:
        if candidate.key == title or candidate.title == title:
            game = candidate
    if game is None:
        raise SystemExit(f"No such title: {title}")
    found = disks or gamedisks.find(game.key)
    if not found:
        raise SystemExit(f"No disks for {game.title}; pass --disks.")
    root = str(found)
    got = c64_file(root, game, "DUNGEON")
    if got is None:
        raise SystemExit(f"No DUNGEON on any {game.title} side under {root}.")
    machine = Machine(got[1], game.key)
    bodies = {}
    for name, (_side, body) in c64_scripts(root, game).items():
        statement = decode(machine, body, 0)
        if statement is not None and statement.op == GOTO:
            bodies[name] = body
    return game, root, machine, script_base(machine, bodies), bodies


def text(statement, base: int) -> str:
    """One statement, as `+$offset ($address) OPCODE operands`."""
    writes = DESTINATIONS.get(statement.op, ())
    parts = []
    for n, (kind, value) in enumerate(statement.operands):
        mark = "=" if n in writes else ""
        if kind == 0x00:
            parts.append(f"{mark}#{value}")
        elif kind == 0x80:
            parts.append(f"{mark}str({value})")
        else:
            parts.append(f"{mark}[${value:04X}]")
    name = OPCODE_NAMES.get(statement.op, f"OP${statement.op:02X}")
    return (f"  +${statement.at:04X} (${base + statement.at:04X})  "
            f"{name:<10} " + ", ".join(parts))


def walk_all(machine: Machine, body: bytes, base: int) -> dict:
    """Every statement reachable from the five entry `GOTO`s."""
    from tools.areas.eclcensus import walk
    return walk(machine, body, base)


def entry_arms(machine: Machine, body: bytes, base: int, entry: int):
    """`(dispatch statement, [(arm number, offset)])` for one entry's ONGOTO."""
    first = decode(machine, body, entry * 4)
    if first is None or first.op != GOTO:
        raise SystemExit(f"entry {entry} does not open with a GOTO")
    at = first.address(0) - base
    for _ in range(64):
        statement = decode(machine, body, at)
        if statement is None:
            break
        if statement.op == ONGOTO:
            arms = [(n - 2, statement.address(n) - base)
                    for n in range(2, len(statement.operands))]
            return statement, arms
        if statement.op in NO_FALLTHROUGH:
            break
        at = statement.end
    raise SystemExit(f"no ONGOTO found on entry {entry}'s path")


def reachable_combat(machine: Machine, body: bytes, base: int, entry: int,
                     save: bytes, load_address: int):
    """`{(arm, offset): shortest list of open decisions}` for each COMBAT."""
    dispatch, arms = entry_arms(machine, body, base, entry)

    def value(kind, operand):
        if kind in (0x00, 0x02):
            return operand
        if kind == 0x80:
            return None
        if load_address <= operand < load_address + len(save):
            return save[operand - load_address]
        return None

    found: dict[tuple[int, int], tuple] = {}
    for arm, arm_at in arms:
        seen: set[int] = set()
        queue = collections.deque([(arm_at, (), None)])
        while queue:
            at, why, previous = queue.popleft()
            if at in seen or not 0 <= at < len(body):
                continue
            seen.add(at)
            statement = decode(machine, body, at)
            if statement is None:
                continue
            if statement.op == COMBAT:
                key = (arm, at)
                if key not in found or len(why) < len(found[key]):
                    found[key] = why
                continue
            nxt: list[tuple[int, tuple]] = []
            # every successor inherits this statement as its predecessor
            condition = decode(machine, body, statement.end)
            if statement.op == COMPARE and condition is not None \
                    and condition.op in CONDITIONS:
                a = value(*statement.operands[0])
                b = value(*statement.operands[1])
                guarded = decode(machine, body, condition.end)
                after = guarded.end if guarded else condition.end
                tag = (f"+${statement.at:04X} "
                       f"[${statement.operands[0][1]:04X}]="
                       f"{'?' if a is None else a} "
                       f"{OPCODE_NAMES[condition.op]} "
                       f"{'?' if b is None else b}")
                if a is None or b is None:
                    nxt.append((condition.end, why + (tag + " taken",), statement))
                    nxt.append((after, why + (tag + " not taken",), statement))
                elif TESTS[condition.op](a, b):
                    nxt.append((condition.end, why, statement))
                else:
                    nxt.append((after, why, statement))
            elif statement.op in CONDITIONS:
                skipped = decode(machine, body, statement.end)
                tag = f"+${statement.at:04X} {OPCODE_NAMES[statement.op]}"
                took = None
                if previous is not None and previous.op in (AND, OR) \
                        and statement.op in BITWISE_TESTS:
                    a = value(*previous.operands[0])
                    b = value(*previous.operands[1])
                    if a is not None and b is not None:
                        result = (a & b) if previous.op == AND else (a | b)
                        took = BITWISE_TESTS[statement.op](result)
                        tag += f" on {'AND' if previous.op == AND else 'OR'}" \
                               f" {a},{b} = {result}"
                if took is None:
                    nxt.append((statement.end, why + (tag + " taken",),
                                statement))
                    if skipped is not None:
                        nxt.append((skipped.end, why + (tag + " not taken",),
                                    statement))
                elif took:
                    nxt.append((statement.end, why, statement))
                elif skipped is not None:
                    nxt.append((skipped.end, why, statement))
            elif statement.op in (GOTO, GOSUB):
                target = statement.address(0)
                if target is not None:
                    nxt.append((target - base, why, statement))
                if statement.op == GOSUB:
                    nxt.append((statement.end, why, statement))
            elif statement.op in (ONGOTO, ONGOSUB):
                for n in range(2, len(statement.operands)):
                    target = statement.address(n)
                    if target is not None:
                        nxt.append((target - base,
                                    why + (f"+${statement.at:04X} "
                                           f"arm {n - 2}",), statement))
                nxt.append((statement.end, why, statement))
            elif statement.op == HORIZMENU:
                nxt.append((statement.end,
                            why + (f"+${statement.at:04X} menu answered",),
                            statement))
            elif statement.op not in NO_FALLTHROUGH:
                nxt.append((statement.end, why, statement))
            queue.extend(nxt)
    return dispatch, found


def cmd(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("title")
    parser.add_argument("script", nargs="?",
                        help="an ECL file name, for everything but --handler")
    parser.add_argument("--disks", help="the C64 sides")
    parser.add_argument("--at", help="where to start, hex: an address or an "
                                     "offset")
    parser.add_argument("--count", type=int, default=40,
                        help="how many statements, or instructions")
    parser.add_argument("--raw", type=int, default=0,
                        help="dump this many bytes at --at instead")
    parser.add_argument("--walk", action="store_true",
                        help="every statement reachable from the five entries")
    parser.add_argument("--handler", metavar="OPCODE",
                        help="disassemble this opcode's 6502 handler, hex")
    parser.add_argument("--code", metavar="ADDR",
                        help="disassemble DUNGEON from this address, hex")
    parser.add_argument("--combat", action="store_true",
                        help="which COMBAT statements --save can reach")
    parser.add_argument("--save", help="a D64 holding the title's saved game")
    parser.add_argument("--entry", type=int, default=1,
                        help="which script entry --combat dispatches from")
    args = parser.parse_args(argv)

    game, root, machine, base, bodies = load(args.title, args.disks)
    print(f"{game.title}: DUNGEON at ${machine.base:04X}, {machine.count} "
          f"opcodes; scripts run at ${base:04X}, {len(bodies)} of them")

    if args.handler or args.code:
        body = c64_file(root, game, "DUNGEON")[1]
        if args.handler:
            opcode = int(args.handler, 16)
            start = newecl.handler(body, DUNGEON_BASE, machine.lo_table,
                                   machine.hi_table, opcode)
            print(f"  opcode ${opcode:02X} "
                  f"({OPCODE_NAMES.get(opcode, 'unnamed')}) takes "
                  f"{machine.operands(opcode)} operand(s), handler "
                  f"${start:04X}")
        else:
            start = int(args.code.lstrip("$"), 16)
        for line in d6502.lines(body, DUNGEON_BASE, start, args.count):
            print("   " + line)
        return 0

    if not args.script:
        parser.error("a script name is needed unless --handler or --code")
    if args.script not in bodies:
        raise SystemExit(f"{args.script} is not one of: "
                         + ", ".join(sorted(bodies)))
    body = bodies[args.script]
    print(f"  {args.script}: {len(body)} bytes")

    if args.combat:
        if not args.save:
            parser.error("--combat needs --save")
        image = D64.open(args.save)
        load_address, save = split_load_address(
            image.read_file(game.save_file))
        dispatch, found = reachable_combat(machine, body, base, args.entry,
                                           save, load_address)
        print(f"  entry {args.entry} dispatches at +${dispatch.at:04X} over "
              f"{len(dispatch.operands) - 2} arms; save loads at "
              f"${load_address:04X}, {len(save)} bytes")
        print(f"  {len(found)} (arm, COMBAT) pair(s) reachable:")
        for arm, at in sorted(found):
            why = found[(arm, at)]
            print(f"    arm {arm:2d} -> COMBAT at +${at:04X}, "
                  f"{len(why)} open decision(s)")
            for line in why:
                print(f"        {line}")
        return 0

    if args.walk:
        statements = walk_all(machine, body, base)
        print(f"  {len(statements)} statements reachable")
        for at in sorted(statements):
            print(text(statements[at], base))
        return 0

    if args.at is None:
        parser.error("one of --at, --walk, --combat, --handler, --code")
    at = int(args.at.lstrip("$+"), 16)
    if at >= base:
        at -= base
    if args.raw:
        chunk = body[at:at + args.raw]
        for i in range(0, len(chunk), 16):
            row = chunk[i:i + 16]
            print(f"  +${at + i:04X}  " + " ".join(f"{b:02x}" for b in row))
        return 0
    for _ in range(args.count):
        statement = decode(machine, body, at)
        if statement is None:
            print(f"  +${at:04X}  <undecodable: ${body[at]:02x}>")
            break
        print(text(statement, base))
        at = statement.end
    return 0


if __name__ == "__main__":
    raise SystemExit(cmd())
