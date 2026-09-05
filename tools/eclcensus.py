#!/usr/bin/env python3
"""Where a title's area scripts keep their variables, censused on both ports.

`#192 (Convert a Curse of the Azure Bonds DOS save into a C64 one, which the
importer refuses today)` step 0a is the ticket. A conversion writes the
saved-game header, and the header is mostly script variables: quest flags, the
per-script scratch, the party's square. Before `apply_quest_flags` can be
trusted at a new base, somebody has to say **which addresses the scripts
actually name**, and say it for the C64 and for DOS separately, because the two
ports load the save at different addresses.

    eclcensus.py curse-of-the-azure-bonds              the page histogram
    eclcensus.py curse-of-the-azure-bonds --range 4B00 4EFF   one row per address
    eclcensus.py curse-of-the-azure-bonds --compare    C64 bytes against DOS's
    eclcensus.py pool-of-radiance                      the control

`tools/eclflags.py` asks this of Pool of Radiance's thirty scripts and knows
what each address means; it goes through `tools/eclwalk.py`, which hard-codes
`$9900`, `POOL{n}.D64` and sixty-two opcodes. This one asks any title, reads
the DOS side as well, and answers less about each hit.

**Nothing is assumed from Pool of Radiance.** The opcode tables come out of the
title's own `DUNGEON` by `tools/newecl.py`'s self-modifying dispatch, the
operand counts out of the table beyond them, and the script base out of the
five `GOTO`s every script opens with. A string operand prints as its length,
never as text, because this output goes into a repository the game's words must
not enter.

## Reading both ports

The C64 keeps each script in its own file, `ECL<id>`; DOS packs them into
`ECL<n>.DAX` as numbered blocks. `--dos DIR` points at the DOS game directory
(`.../games/CURSE/GAME/CURSE`); with no `--dos` the census is the C64's alone.
The DOS block id is the number the C64 spells in hex, so DOS block 21 is
`ECL15` -- checked and reported rather than assumed, since one Curse script
breaks it.
"""

from __future__ import annotations

import argparse
import collections
import glob
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import newecl  # noqa: E402

from automap.paths import disk_globs, find_disks  # noqa: E402
from goldbox import games  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.dos_savegame import dax_blocks  # noqa: E402

#: Where `LINKER` puts `DUNGEON`, in every title read so far -- not its header.
DUNGEON_BASE = 0x0800

GOTO, GOSUB = 0x01, 0x02
ONGOTO, ONGOSUB = 0x25, 0x26
EXIT, RETURN, NEWECL = 0x00, 0x13, 0x20

#: Nothing runs after these.
NO_FALLTHROUGH = {EXIT, GOTO, RETURN, NEWECL}
#: A false condition skips the statement after these.
CONDITIONS = {0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B}
#: Opcodes carrying a count of further operands, and how many fixed operands
#: come first -- the count is the last of those.
COUNTED = {0x15: 3, 0x25: 2, 0x26: 2, 0x2B: 2}

#: Where Pool of Radiance's operand-count table disagrees with its own
#: handlers -- `docs/125-bug-notes.md` N2. Per title, because Silver Blades'
#: table has the right numbers and correcting it would invent a fourth error.
HANDLER_OPERANDS = {
    "pool-of-radiance": {0x0C: 3, 0x29: 14, 0x36: 2},
}

#: Which operands an opcode stores through. `tools/eclflags.py` derived this
#: from the instruction set and checked it against sixty-two handlers; it is
#: copied rather than imported because that module is Pool of Radiance's.
DESTINATIONS = {
    0x04: (2,), 0x05: (2,), 0x06: (2,), 0x07: (2,),
    0x08: (1,), 0x09: (1,), 0x0F: (1,), 0x10: (1,),
    0x15: (0,), 0x1D: (0,), 0x1E: (2, 3, 4, 5),
    0x22: (0, 1), 0x23: (0, 1), 0x29: (3,), 0x2A: (2,),
    0x2B: (0,), 0x2C: (5,), 0x2F: (2,), 0x30: (2,),
    0x35: (1,), 0x3B: (1, 2),
}


#: Opcode names this project has established. An opcode nobody has named
#: prints as its number.
OPCODE_NAMES = {
    0x00: "EXIT", 0x01: "GOTO", 0x02: "GOSUB", 0x03: "COMPARE",
    0x04: "ADD", 0x05: "SUB", 0x06: "DIV", 0x07: "MUL", 0x08: "RANDOM",
    0x09: "SAVE", 0x0A: "LOADCHAR", 0x0C: "SETUPMON", 0x13: "RETURN",
    0x16: "IF=", 0x17: "IF<>", 0x18: "IF<", 0x19: "IF>",
    0x1A: "IF<=", 0x1B: "IF>=", 0x20: "NEWECL", 0x21: "LOADFILES",
    0x24: "COMBAT", 0x25: "ONGOTO", 0x26: "ONGOSUB", 0x27: "TREASURE",
    0x29: "ENCMENU", 0x2A: "GETTABLE", 0x2B: "HORIZMENU", 0x2D: "CALL",
    0x2E: "DAMAGE", 0x2F: "AND", 0x30: "OR", 0x34: "ECLCLOCK",
    0x35: "SAVETABLE", 0x36: "ADDNPC", 0x37: "LOADPIECES", 0x38: "PROGRAM",
    0x3B: "SPELL",
}


# -- the files ---------------------------------------------------------------

def c64_sides(root: str, game: games.Game) -> list[tuple[int, str]]:
    """`(side number, path)` for every side of this title under `root`."""
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


def c64_file(root: str, game: games.Game, name: str) -> tuple[int, bytes] | None:
    """`(side, body without its two-byte header)` for a game file."""
    for number, path in c64_sides(root, game):
        try:
            image = D64.open(path)
        except Exception:
            continue
        for entry in image.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == name:
                return number, image.read_file(name)[2:]
    return None


def c64_scripts(root: str, game: games.Game) -> dict[str, tuple[int, bytes]]:
    """Every `ECL<hex>` on the sides, by name, with its side and its body."""
    out: dict[str, tuple[int, bytes]] = {}
    for number, path in c64_sides(root, game):
        try:
            image = D64.open(path)
        except Exception:
            continue
        for entry in image.iter_directory():
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            if not name.startswith("ECL") or len(name) != 5:
                continue
            try:
                int(name[3:], 16)
            except ValueError:
                continue
            if name not in out:
                out[name] = (number, image.read_file(name)[2:])
    return out


def dos_scripts(directory: str) -> dict[int, tuple[str, bytes]]:
    """Every block of every `ECL<n>.DAX`, by block id, less its two-byte head.

    The two bytes dropped are the same two the C64's `.PRG` header occupies,
    so the bodies line up operand for operand and can be compared directly.
    """
    out: dict[int, tuple[str, bytes]] = {}
    for path in sorted(glob.glob(os.path.join(directory, "ECL*.DAX"))):
        name = os.path.basename(path)
        with open(path, "rb") as handle:
            data = handle.read()
        for block_id, body in dax_blocks(data, name):
            out.setdefault(block_id, (name, body[2:]))
    return out


# -- the machine -------------------------------------------------------------

class Machine:
    """This title's opcode tables, read out of its own `DUNGEON`."""

    def __init__(self, body: bytes, key: str, base: int = DUNGEON_BASE):
        self.body, self.base = body, base
        call, lo, hi, _store = newecl.dispatch_tables(body, base)
        self.dispatch, self.lo_table, self.hi_table = call, lo, hi
        self.count = hi - lo
        at = hi + self.count - base
        self.table_operands = list(body[at:at + self.count])
        self.corrections = HANDLER_OPERANDS.get(key, {})

    def operands(self, op: int) -> int:
        return self.corrections.get(op, self.table_operands[op])


class Statement:
    __slots__ = ("at", "end", "op", "operands")

    def __init__(self, at, end, op, operands):
        self.at, self.end, self.op, self.operands = at, end, op, operands

    def address(self, n: int) -> int | None:
        if n >= len(self.operands):
            return None
        kind, value = self.operands[n]
        return value if kind not in (0x00, 0x80) else None


def _size(body: bytes, i: int):
    """`(length, kind, value)` of the operand at `i`, or None."""
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


def walk(machine: Machine, body: bytes, base: int) -> dict[int, Statement]:
    """Every statement reachable from the five entry `GOTO`s.

    A linear sweep runs into the data tables opcode `$2A` indexes and reads
    them as instructions, which is how a census of a data table's bytes turns
    into a census of addresses nothing ever names.
    """
    found: dict[int, Statement] = {}
    work = [n * 4 for n in range(5)]
    while work:
        i = work.pop()
        if i in found or not 0 <= i < len(body):
            continue
        statement = decode(machine, body, i)
        if statement is None or statement.end <= i:
            continue
        found[i] = statement
        op = statement.op
        successors: list[int] = []
        if op in (GOTO, GOSUB):
            target = statement.address(0)
            if target is not None:
                successors.append(target - base)
        if op in (ONGOTO, ONGOSUB):
            for n in range(COUNTED[op], len(statement.operands)):
                target = statement.address(n)
                if target is not None:
                    successors.append(target - base)
        if op not in NO_FALLTHROUGH or op in (GOSUB, ONGOTO):
            successors.append(statement.end)
        if op in CONDITIONS:
            skipped = decode(machine, body, statement.end)
            if skipped is not None:
                successors.append(skipped.end)
        work.extend(successors)
    return found


def script_base(machine: Machine, bodies: dict[str, bytes]) -> int:
    """Where the scripts run, from the five `GOTO`s at the head of each."""
    low, high = 0x10000, 0
    for body in bodies.values():
        targets = []
        for n in range(5):
            statement = decode(machine, body, n * 4)
            if statement is None or statement.op != GOTO:
                continue
            target = statement.address(0)
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
            f"fall between ${high:04X} and ${low:04X}.")
    return pages[0]


# -- the census --------------------------------------------------------------

class Hit:
    __slots__ = ("script", "at", "op", "operand", "address", "write")

    def __init__(self, script, at, op, operand, address, write):
        self.script, self.at, self.op = script, at, op
        self.operand, self.address, self.write = operand, address, write


def census(machine: Machine, scripts: dict[str, bytes], base: int
           ) -> tuple[list[Hit], dict[str, tuple[int, int]]]:
    """Every address operand in every reachable statement, and the reach."""
    hits: list[Hit] = []
    reach: dict[str, tuple[int, int]] = {}
    for name in sorted(scripts):
        body = scripts[name]
        found = walk(machine, body, base)
        reach[name] = (sum(s.end - s.at for s in found.values()), len(body))
        for at in sorted(found):
            statement = found[at]
            writes = DESTINATIONS.get(statement.op, ())
            for n, (kind, value) in enumerate(statement.operands):
                if kind in (0x00, 0x80):
                    continue
                hits.append(Hit(name, at, statement.op, n, value, n in writes))
    return hits, reach


def histogram(hits: list[Hit]) -> collections.Counter:
    return collections.Counter(h.address & 0xFF00 for h in hits)


LOADFILES, LOADPIECES = 0x21, 0x37


def raw_loads(body: bytes) -> list[tuple[int, int, tuple[int, int, int]]]:
    """`LOADFILES`/`LOADPIECES` by byte pattern, not by walking.

    The all-immediate form only: opcode, then three `00 <value>` operands.
    `tools/loadfiles.py` does this for Pool of Radiance and it is the
    independent check on the walk -- a scan finds statements the walk never
    reached, and reads data tables as statements, so the two disagreeing is
    the interesting case rather than either being right.
    """
    out = []
    for i in range(len(body) - 7):
        op = body[i]
        if op not in (LOADFILES, LOADPIECES):
            continue
        if body[i + 1] or body[i + 3] or body[i + 5]:
            continue
        out.append((i, op, (body[i + 2], body[i + 4], body[i + 6])))
    return out


def walked_loads(machine: "Machine", body: bytes, base: int
                 ) -> list[tuple[int, int, tuple]]:
    """The same, from the statements the walk actually reached."""
    out = []
    for at, statement in sorted(walk(machine, body, base).items()):
        if statement.op not in (LOADFILES, LOADPIECES):
            continue
        values = []
        for n in range(3):
            kind, value = statement.operands[n]
            values.append(value if kind == 0x00 else None)
        out.append((at, statement.op, tuple(values)))
    return out



# -- reporting ---------------------------------------------------------------

def load_port(root: str, game: games.Game, dos: str | None):
    """`(machine, base, {name: body}, {name: side})` for one port."""
    got = c64_file(root, game, "DUNGEON")
    if got is None:
        raise SystemExit(f"No DUNGEON on any {game.title} side under {root}.")
    machine = Machine(got[1], game.key)
    c64 = c64_scripts(root, game)
    bodies = {}
    sides = {}
    for name, (side, body) in c64.items():
        statement = decode(machine, body, 0)
        if statement is None or statement.op != GOTO:
            continue                     # not an area script; ECL64, ECL65
        bodies[name] = body
        sides[name] = side
    base = script_base(machine, bodies)
    dos_bodies = {}
    if dos:
        for block_id, (source, body) in dos_scripts(dos).items():
            statement = decode(machine, body, 0)
            if statement is None or statement.op != GOTO:
                continue
            dos_bodies[f"{block_id:02X}"] = (source, body)
    return machine, base, bodies, sides, dos_bodies


def registry(key: str) -> str:
    """`tools/gamedisks.py`'s answer for this title, or "".

    `automap.paths.find_disks` is the player's search and looks for a directory
    named after the game; nobody names one that, so on this machine it finds
    Pool of Radiance and neither of the other two --
    `#251 (Curse's and Silver Blades' disks are where nothing looks for them,
    so every per-title test skips)`.
    """
    try:
        import gamedisks
    except ImportError:                     # pragma: no cover - defensive
        return ""
    found = gamedisks.find(key)
    return str(found) if found else ""


def cmd(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("title")
    parser.add_argument("--disks", help="the C64 sides")
    parser.add_argument("--dos", help="the DOS game directory")
    parser.add_argument("--range", nargs=2, metavar=("LO", "HI"),
                        help="one row per address in this range, hex")
    parser.add_argument("--compare", action="store_true",
                        help="C64 script bytes against the DOS blocks'")
    parser.add_argument("--sites", nargs="+", metavar="ADDR",
                        help="every statement naming these addresses, hex")
    parser.add_argument("--loadfiles", action="store_true",
                        help="what each script loads, walked and rescanned")
    args = parser.parse_args(argv)

    game = None
    for candidate in games.GAMES:
        if candidate.key == args.title or candidate.title == args.title:
            game = candidate
    if game is None:
        raise SystemExit(f"No such title: {args.title}")
    root = args.disks or registry(game.key) or str(find_disks(game) or "")
    if not root or not os.path.isdir(root):
        raise SystemExit(f"No disks for {game.title}; pass --disks.")

    machine, base, bodies, sides, dos_bodies = load_port(root, game, args.dos)
    print(f"{game.title}")
    print(f"  DUNGEON at ${machine.base:04X}, {machine.count} opcodes, "
          f"handlers ${machine.lo_table:04X}/${machine.hi_table:04X}")
    print(f"  scripts run at ${base:04X}: {len(bodies)} on the C64, "
          f"{len(dos_bodies)} DOS blocks")

    if args.compare and dos_bodies:
        print("\n  C64 file against the DOS block of the same id:")
        same = differ = missing = 0
        for name in sorted(bodies):
            key = name[3:]
            if key not in dos_bodies:
                print(f"    {name}: no DOS block ${key}")
                missing += 1
                continue
            source, body = dos_bodies[key]
            if body == bodies[name]:
                same += 1
            else:
                differ += 1
                first = next((i for i in range(min(len(body),
                                                   len(bodies[name])))
                              if body[i] != bodies[name][i]), None)
                print(f"    {name}: DIFFERS ({len(bodies[name])} C64, "
                      f"{len(body)} in {source}, first at "
                      f"{'-' if first is None else first})")
        for key in sorted(dos_bodies):
            if f"ECL{key}" not in bodies:
                print(f"    DOS block ${key} ({dos_bodies[key][0]}): "
                      f"no C64 file of that id")
        print(f"    {same} identical, {differ} differ, {missing} with no "
              f"DOS block")

    hits, reach = census(machine, bodies, base)
    got = sum(r for r, _ in reach.values())
    total = sum(t for _, t in reach.values())
    print(f"\n  C64: {len(hits)} address operands over {100.0 * got / total:.1f}% "
          f"of {total} bytes")
    counts = histogram(hits)
    print(f"\n  {'page':>6} {'refs':>6} {'reads':>6} {'writes':>6}")
    for page in sorted(counts):
        reads = sum(1 for h in hits if h.address & 0xFF00 == page
                    and not h.write)
        writes = counts[page] - reads
        print(f"  ${page:04X} {counts[page]:>6} {reads:>6} {writes:>6}")

    if dos_bodies:
        plain = {f"ECL{k}": v[1] for k, v in dos_bodies.items()}
        dhits, dreach = census(machine, plain, base)
        dgot = sum(r for r, _ in dreach.values())
        dtotal = sum(t for _, t in dreach.values())
        print(f"\n  DOS: {len(dhits)} address operands over "
              f"{100.0 * dgot / dtotal:.1f}% of {dtotal} bytes")
        dcounts = histogram(dhits)
        pages = sorted(set(counts) | set(dcounts))
        print(f"\n  {'page':>6} {'C64':>6} {'DOS':>6}  same set")
        for page in pages:
            c64set = {h.address for h in hits if h.address & 0xFF00 == page}
            dosset = {h.address for h in dhits if h.address & 0xFF00 == page}
            mark = "yes" if c64set == dosset else (
                f"C64 only {sorted(c64set - dosset)}, "
                f"DOS only {sorted(dosset - c64set)}")
            print(f"  ${page:04X} {counts.get(page, 0):>6} "
                  f"{dcounts.get(page, 0):>6}  {mark}")

    if args.range:
        lo, hi = (int(v, 16) for v in args.range)
        print(f"\n  ${lo:04X}-${hi:04X}, one row per address named:")
        by_address: dict[int, list[Hit]] = {}
        for h in hits:
            if lo <= h.address <= hi:
                by_address.setdefault(h.address, []).append(h)
        for address in sorted(by_address):
            here = by_address[address]
            reads = sum(1 for h in here if not h.write)
            who = sorted({h.script for h in here})
            print(f"    ${address:04X}  {reads:>3}r {len(here) - reads:>3}w  "
                  f"{', '.join(who)}")
        if not by_address:
            print("    nothing in this range is named by any script")

    if args.loadfiles:
        print("\n  what each script loads. `walked` is the control-flow walk, "
              "`scan` the byte pattern;")
        print("  $FF and $7F are LOADFILES' \"leave this slot alone\".")
        for name in sorted(bodies):
            body = bodies[name]
            walked = walked_loads(machine, body, base)
            scanned = raw_loads(body)
            same = ([(a, o, v) for a, o, v in walked]
                    == [(a, o, v) for a, o, v in scanned])
            geos = []
            for _at, op, (geo, _b, _c) in walked:
                if op == LOADFILES and geo not in (None, 0xFF, 0x7F) \
                        and geo not in geos:
                    geos.append(geo)
            print(f"    {name}: {len(walked)} walked, {len(scanned)} scanned, "
                  f"{'agree' if same else 'DISAGREE'}; maps "
                  + (", ".join(f"GEO{g:02X}" for g in geos) or "none"))
            if not same:
                for at, op, values in scanned:
                    if (at, op, values) not in walked:
                        print(f"      scan only: +${at:04X} "
                              f"{OPCODE_NAMES.get(op)} {values}")
                for at, op, values in walked:
                    if (at, op, values) not in scanned:
                        print(f"      walk only: +${at:04X} "
                              f"{OPCODE_NAMES.get(op)} {values}")

    if args.sites:
        wanted = {int(v, 16) for v in args.sites}
        print("\n  every statement naming "
              + ", ".join(f"${a:04X}" for a in sorted(wanted)) + ":")
        for name in sorted(bodies):
            body = bodies[name]
            for at, statement in sorted(walk(machine, body, base).items()):
                addresses = {statement.address(n)
                             for n in range(len(statement.operands))}
                if not (addresses & wanted):
                    continue
                writes = DESTINATIONS.get(statement.op, ())
                parts = []
                for n, (kind, value) in enumerate(statement.operands):
                    mark = "=" if n in writes else ""
                    if kind == 0x00:
                        parts.append(f"{mark}{value}")
                    elif kind == 0x80:
                        parts.append(f'{mark}"{value} bytes"')
                    else:
                        parts.append(f"{mark}[${value:04X}]")
                print(f"    {name}+${at:04X}  "
                      f"{OPCODE_NAMES.get(statement.op, f'OP${statement.op:02X}')} "
                      + ", ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(cmd())
