#!/usr/bin/env python3
"""Every reference the thirty area scripts make to the quest-flag page.

`$4A00`-`$4AF8` is where Pool of Radiance keeps what the party has done.
`$4A00`-`$4A1F` is scratch the engine zeroes on every area change and
`$4A20`-`$4AF8` survives one -- [`41-memory-regions.md`](../docs/41-memory-regions.md).
This walks all thirty scripts with `eclwalk.py`, classifies every operand that
names an address in that range as a read or a write, and prints the map.

    eclflags.py summary             the counts, and the unreferenced gaps
    eclflags.py map                 one row per address
    eclflags.py map --scratch       the same for $4A00-$4A1F
    eclflags.py sites 4A81          every reference to one address
    eclflags.py doc                 docs/151-quest-flags.md, whole

**No string is printed as text.** The strings at these write sites are the
game's own words and this repository must not carry them, so a string operand
is reported as its length and its address, exactly as `eclwalk.py` does. What
names an address in English is `goldbox/commissions.py`, which this reads, so
the table cannot drift from the code.

A *write* is an operand the VM stores through. Which operand that is per
opcode comes from the instruction set in
[`128-guide-and-scripting.md`](../docs/128-guide-and-scripting.md) §12.3.3,
checked against 62 handlers in `DUNGEON`; `DESTINATIONS` below carries it.
Everything else is a read.

**Not every row of `DESTINATIONS` is corroborated by a real hit.** The
classification comes from the handlers, but the thirty scripts only exercise
some of it: `$08 RANDOM`, `$0F`/`$10 INPUT NUMBER`/`INPUT STRING`,
`$1E CHECKPARTY`, `$22 PARTY SURPRISE`, `$23 SURPRISE`, `$2C PARLEY` and
`$3B SPELL` never touch `$4A00`-`$4AF8` anywhere, and `$29 ENCMENU`'s
declared destination operand never lands on an in-range address in any of its
five firings -- so all five are classified as reads without the write rule
being tested. None of that moves a number in today's output. It means a flag
written by one of those opcodes would be classified on the handler reading
alone, so check that reading again before trusting a new quest that uses one.
"""
import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from goldbox import commissions  # noqa: E402
from tools import eclwalk  # noqa: E402

#: The whole page an area script can name. `$4AF8` is the top: no operand in
#: any of the thirty scripts names anything above it.
PAGE_BASE, PAGE_END = 0x4A00, 0x4AF8
#: Scratch below, persistent from here up. `DUNGEON $202A`-`$2032`.
PERSISTENT_BASE = 0x4A20

#: Which operands an opcode stores through, by opcode. Anything not here
#: reads all of its operands. The ones that matter for this page are `$09`
#: SAVE, `$04` ADD (a counter), `$30` OR (a bit flag) and `$35` SAVETABLE.
DESTINATIONS = {
    0x04: (2,),         # ADD <var1> <var2> <address>
    0x05: (2,),         # SUBTRACT
    0x06: (2,),         # DIVIDE
    0x07: (2,),         # MULTIPLY
    0x08: (1,),         # RANDOM <var> <address>
    0x09: (1,),         # SAVE <var> <address>
    0x0F: (1,),         # INPUT NUMBER <maxDigits> <address>
    0x10: (1,),         # INPUT STRING <maxLength> <address>
    0x15: (0,),         # VERTICAL MENU <address> ...
    0x1D: (0,),         # PARTYSTRENGTH <address>
    0x1E: (2, 3, 4, 5),  # CHECKPARTY <attr> <effect> <a1> <a2> <a3> <a4>
    0x22: (0, 1),       # PARTY SURPRISE <address1> <address2>
    0x23: (0, 1),       # SURPRISE <address1> <address2> <var1> <var2>
    0x29: (3,),         # ENCOUNTER MENU ... <address> ...
    0x2A: (2,),         # GETTABLE <base> <var> <address>
    0x2B: (0,),         # HORIZONTAL MENU <address> ...
    0x2C: (5,),         # PARLEY <five attitudes> <address>
    0x2F: (2,),         # AND <var1> <var2> <address>
    0x30: (2,),         # OR <var1> <var2> <address>
    0x35: (1,),         # SAVE TABLE <var1> <address> <var2> -- indexed
    0x3B: (1, 2),       # SPELL <spellID> <address1> <address2>
}

#: Opcodes that reach `base + index`, and which operand is the base. A byte
#: inside one of these is written by a script that never names it.
INDEXED = {0x2A: 0, 0x35: 1}

# The tables whose interiors are reached only through `GETTABLE`/`SAVETABLE`,
# each with the instruction that bounds the index. Declared rather than
# inferred, because the bound is a loop in the script and not a property of
# the access; `check_tables()` refuses a base the walk does not find.
#
#   $4A39 and $4A8F   ECL08 $9C4A/$9C54, both indexed by [$6E79], whose loop
#                     is `ADD 1 / COMPARE [$6E79], 7 / IF< / GOTO $9C4A` at
#                     $9C9A-$9CAA. Seven entries, 0..6.
#   $4AA6             the reward ledger. `ECL08 $9D12` reads it with the same
#                     index, bounded by `COMPARE [$6E79], 25 / IF>` at $9D34,
#                     and the clerk's `ONGOSUB [$6E79], 26` at $9D55 names 26
#                     handlers. `goldbox/commissions.py` has the same 26.
#   $4AEA             ECL0E $9F77/$9F6D, indexed by [$6E7A]. The bound was
#                     not established -- and it changes nothing, because every
#                     byte from $4AEA to $4AF8 is named directly as well.
TABLES = (
    (0x4A39, 7, "ECL08 $9C4A, index bounded at $9CA3"),
    (0x4A8F, 7, "ECL08 $9C54, index bounded at $9CA3"),
    (0x4AA6, commissions.LEDGER_COUNT, "ECL08 $9D12, the reward ledger"),
    (0x4AEA, None, "ECL0E $9F77, index bound not established"),
)


# --- what we can call a flag in English -------------------------------------

def known_names():
    """Our own words for the addresses this project has already attributed.

    Read out of `goldbox/commissions.py` rather than repeated here, so the
    generated table and the code cannot disagree. Nothing in this dictionary
    is the game's text.
    """
    out = {}
    for index, (name, _source) in enumerate(commissions.LEDGER):
        if name:
            out[commissions.LEDGER_BASE + index] = f"ledger: {name}"
    for address, name, kind, _when, _live in commissions.APPOINTMENTS:
        out[address] = f"{kind}: {name}"
    for quest in commissions.SIDE_QUESTS:
        per_address = collections.defaultdict(list)
        for address, value, what in quest.flags:
            per_address[address].append(f"{value} = {what}")
        for address, parts in per_address.items():
            out[address] = f"{quest.name}: " + "; ".join(parts)
    out[commissions.COMPLETED] = "count of major commissions paid"
    # `commissions.py` knows this byte as SLUM_WANDERING but has no name-lookup
    # entry for it, so the cap is read from there rather than repeated as a
    # number here.  The wording is this file's; the value is not.
    out.setdefault(
        0x4A80,
        f"slums: won wandering fights, capped at {commissions.SLUM_WANDERING}")
    return out


# --- the walk ---------------------------------------------------------------

class Reference:
    """One operand naming an address on the page."""

    __slots__ = ("script", "side", "at", "statement", "operand", "write",
                 "indexed", "value")

    def __init__(self, script, side, statement, operand, write, indexed, value):
        self.script, self.side = script, side
        self.at, self.statement = statement.at, statement
        self.operand, self.write = operand, write
        self.indexed, self.value = indexed, value

    @property
    def address(self):
        return eclwalk.BASE + self.at

    def __str__(self):
        kind = "writes" if self.write else "reads "
        if self.indexed:
            kind = "writes" if self.write else "reads "
            kind += "[i]"
        return (f"{self.script} ${self.address:04X} +{self.at:04X}  {kind}  "
                f"{self.statement}")


def _immediate(statement, operand, write):
    """What a write puts there, when the source operand is a constant.

    `None` means the source is a variable or the opcode is not a plain store,
    so the value is not knowable from the bytecode alone. `ADD` with a
    constant first operand is reported as an increment, because that is what
    every one of them in these scripts is.
    """
    if not write:
        return None
    op = statement.op
    if op == 0x09 and statement.operands[0][0] == 0x00:      # SAVE <var> <a>
        return statement.operands[0][1]
    if op == 0x35 and statement.operands[0][0] == 0x00:      # SAVE TABLE
        return statement.operands[0][1]
    if op == 0x04 and statement.operands[0][0] == 0x00:      # ADD
        return f"+{statement.operands[0][1]}"
    if op == 0x30 and statement.operands[1][0] == 0x00:      # OR: set a bit
        return f"|{statement.operands[1][1]}"
    if op == 0x2F and statement.operands[1][0] == 0x00:      # AND: clear bits
        return f"&{statement.operands[1][1]}"
    del operand
    return None


def _has_string(statement):
    return any(kind == 0x80 for kind, _ in statement.operands)


def references(machine, chosen):
    """Every reference to the page, and which written flags a string names.

    The second return value is the set of addresses with a printed string in
    the same basic block as one of their writes -- the block being what
    `eclwalk.Script.block_of` calls one. That is the closest this can get to
    the lost report's "a printed string at the write site"; the rule it used
    is not recorded, and this one does not reproduce its count. See
    `docs/151-quest-flags.md`.
    """
    refs = collections.defaultdict(list)
    named = set()
    bases = collections.defaultdict(set)
    reach = {}
    for name, (side, body) in chosen.items():
        script = eclwalk.Script(machine, name, side, body)
        order = sorted(script.statements)
        strung = [_has_string(script.statements[a]) for a in order]
        blocks = {}
        for i, at in enumerate(order):
            statement = script.statements[at]
            destinations = DESTINATIONS.get(statement.op, ())
            base_operand = INDEXED.get(statement.op)
            for n, (kind, value) in enumerate(statement.operands):
                if kind != 0x01 or not PAGE_BASE <= value <= PAGE_END:
                    continue
                write = n in destinations
                indexed = n == base_operand
                if indexed:
                    bases[value].add(name)
                refs[value].append(Reference(
                    name, side, statement, n, write, indexed,
                    _immediate(statement, n, write)))
                if not write:
                    continue
                if statement.at not in blocks:
                    blocks[statement.at] = any(
                        _has_string(b) for b in script.block_of(statement))
                if blocks[statement.at]:
                    named.add(value)
                back = next((i - j for j in range(i - 1, -1, -1) if strung[j]),
                            None)
                if back is not None:
                    reach[value] = min(reach.get(value, back), back)
    return refs, named, bases, reach


#: The statement distances the summary reports a naming string at. The lost
#: report's 158 sits between the last two and no rule here produces it.
REACHES = (1, 2, 4, 8, 16, 32)


def naming_reach(reach, lo, hi):
    """How many written addresses have a printed string N statements back."""
    return [(n, sum(1 for a, d in reach.items() if lo <= a <= hi and d <= n))
            for n in REACHES]


def check_tables(bases):
    """Refuse a declared table whose base no script actually indexes."""
    for base, _length, where in TABLES:
        if base not in bases:
            raise SystemExit(
                f"${base:04X} is declared a table base ({where}) and no "
                f"GETTABLE or SAVETABLE in the thirty scripts uses it. The "
                f"declaration in TABLES is stale.")


def table_interiors(refs):
    """Addresses no operand names, that a declared table still reaches."""
    out = {}
    for base, length, where in TABLES:
        if length is None:
            continue
        for address in range(base + 1, base + length):
            if address not in refs and address >= PERSISTENT_BASE:
                out[address] = f"${base:04X} + {address - base}, {where}"
    return out


# --- rows --------------------------------------------------------------------

class Row:
    __slots__ = ("address", "writes", "reads", "scripts", "values", "named",
                 "interior")

    def __init__(self, address, refs, named, interior):
        rows = refs.get(address, [])
        self.address = address
        self.writes = [r for r in rows if r.write]
        self.reads = [r for r in rows if not r.write]
        self.scripts = sorted({r.script for r in rows})
        seen = []
        for r in self.writes:
            if r.value is not None and r.value not in seen:
                seen.append(r.value)
        self.values = seen
        self.named = address in named
        self.interior = interior.get(address)

    @property
    def referenced(self):
        return bool(self.writes or self.reads)

    @property
    def value_text(self):
        if not self.values:
            return "-" if not self.writes else "computed"
        text = ", ".join(str(v) for v in sorted(
            self.values, key=lambda v: (isinstance(v, str), v)))
        if len(self.values) < len(self.writes):
            text += ", computed"
        return text


def rows(refs, named, interior, lo, hi):
    return [Row(a, refs, named, interior) for a in range(lo, hi + 1)]


def gaps(all_rows, interior):
    out, runs = [], []
    for row in all_rows:
        if row.referenced or row.address in interior:
            continue
        if runs and runs[-1][1] + 1 == row.address:
            runs[-1][1] = row.address
        else:
            runs.append([row.address, row.address])
    for a, b in runs:
        out.append(f"${a:04X}" if a == b else f"${a:04X}-${b:04X}")
    return out


# --- the commands ------------------------------------------------------------

def cmd_summary(refs, named, bases, reach, args):
    interior = table_interiors(refs)
    persistent = rows(refs, named, interior, PERSISTENT_BASE, PAGE_END)
    scratch = rows(refs, named, interior, PAGE_BASE, PERSISTENT_BASE - 1)
    direct = [r for r in persistent if r.referenced]
    written = [r for r in direct if r.writes]
    total = sum(len(r.writes) + len(r.reads) for r in persistent)
    print(f"persistent block  ${PERSISTENT_BASE:04X}-${PAGE_END:04X}  "
          f"{len(persistent)} bytes")
    print(f"  named by an operand          {len(direct)}")
    print(f"  reached only through a table {len(interior)}")
    print(f"  named, either way            {len(direct) + len(interior)}")
    print(f"  never referenced             "
          f"{len(persistent) - len(direct) - len(interior)}")
    print(f"  operand references           {total}"
          f"  ({sum(len(r.writes) for r in persistent)} write, "
          f"{sum(len(r.reads) for r in persistent)} read)")
    print(f"  written somewhere            {len(written)}")
    print(f"  read and never written       {len(direct) - len(written)}")
    print(f"  a printed string in the block that writes it  "
          f"{len([a for a in named if a >= PERSISTENT_BASE])}")
    print(f"scratch page      ${PAGE_BASE:04X}-${PERSISTENT_BASE - 1:04X}  "
          f"{len(scratch)} bytes")
    print(f"  named by an operand          "
          f"{len([r for r in scratch if r.referenced])}")
    print(f"  operand references           "
          f"{sum(len(r.writes) + len(r.reads) for r in scratch)}")
    print(f"  a printed string in the block that writes it  "
          f"{len([a for a in named if a < PERSISTENT_BASE])}")
    print("a printed string within N statements before a write, "
          "persistent block:")
    print("  " + "  ".join(
        f"{n}: {c}" for n, c in naming_reach(reach, PERSISTENT_BASE, PAGE_END)))
    print("gaps: " + " ".join(gaps(persistent, interior)))
    print("table bases: " + " ".join(
        f"${b:04X} ({','.join(sorted(s))})" for b, s in sorted(bases.items())))
    del args


def cmd_map(refs, named, bases, reach, args):
    interior = table_interiors(refs)
    lo, hi = ((PAGE_BASE, PERSISTENT_BASE - 1) if args.scratch
              else (PERSISTENT_BASE, PAGE_END))
    names = known_names()
    print(f"{'addr':6s} {'w':>3s} {'r':>3s}  {'values written':30s} "
          f"{'s':1s}  {'scripts':28s} what we can call it")
    for row in rows(refs, named, interior, lo, hi):
        if not row.referenced and not row.interior:
            print(f"${row.address:04X}    -   -  {'-':30s} -  "
                  f"{'-':28s} never referenced")
            continue
        what = names.get(row.address, "")
        if row.interior and not row.referenced:
            what = what or f"table interior: {row.interior}"
        print(f"${row.address:04X} {len(row.writes):3d} {len(row.reads):3d}  "
              f"{row.value_text[:30]:30s} {'*' if row.named else ' '}  "
              f"{','.join(row.scripts)[:28]:28s} {what}")
    del bases, reach


def cmd_sites(refs, named, bases, reach, args):
    names = known_names()
    for text in args.address:
        address = int(text.lstrip("$"), 16)
        rows_ = refs.get(address, [])
        print(f"${address:04X}  {len(rows_)} reference(s)  "
              f"{names.get(address, '')}")
        for ref in rows_:
            print(f"  {ref}")
    del named, bases, reach


DOC_HEADER = """\
# The quest-flag page, and what writes it

**Generated** by `tools/eclflags.py doc` -- do not edit. Nothing here is
transcribed by hand, and no line of it is the game's own text.

`$4A00`-`$4AF8` is where the game records what the party has done.
`$4A00`-`$4A1F` is a scratch page the engine zeroes on every area change and
`$4A20`-`$4AF8` survives one ([`41`](41-memory-regions.md)). This is every
reference the thirty area scripts make to either half.

It replaces `work/reports/quest-flags.md`, which is lost (`#136`), and was
rebuilt for `#158 (Track the quests the game itself forgets, starting with
Ohlo's potion)`.

## How to read it

`w` and `r` count the operands that write the byte and that read it. `values
written` is what a write stores when the source is a constant; `computed`
means at least one write stores a variable. `+1` is `ADD`, `|n` is `OR` --
a counter and a bit flag respectively. A `*` in the `s` column means a
printed string sits in the same basic block as one of the writes, which is
usually the speech that names the event.

The last column is **our own words**, joined from `goldbox/commissions.py` at
generation time; a blank means this project has not attributed the byte yet.
"""


def cmd_doc(refs, named, bases, reach, args):
    interior = table_interiors(refs)
    names = known_names()
    persistent = rows(refs, named, interior, PERSISTENT_BASE, PAGE_END)
    scratch = rows(refs, named, interior, PAGE_BASE, PERSISTENT_BASE - 1)
    direct = [r for r in persistent if r.referenced]
    written = [r for r in direct if r.writes]
    print(DOC_HEADER)
    print("## The counts\n")
    print("| | |")
    print("|---|---:|")
    print(f"| bytes in `${PERSISTENT_BASE:04X}`-`${PAGE_END:04X}` "
          f"| {len(persistent)} |")
    print(f"| named by an operand | {len(direct)} |")
    print(f"| reached only through a table | {len(interior)} |")
    print(f"| **named, either way** | **{len(direct) + len(interior)}** |")
    print(f"| never referenced | "
          f"{len(persistent) - len(direct) - len(interior)} |")
    print(f"| operand references | "
          f"{sum(len(r.writes) + len(r.reads) for r in persistent)} |")
    print(f"| of those, writes | {sum(len(r.writes) for r in persistent)} |")
    print(f"| addresses written somewhere | {len(written)} |")
    print(f"| read and never written | {len(direct) - len(written)} |")
    print(f"| a printed string in the block that writes it | "
          f"{len([a for a in named if a >= PERSISTENT_BASE])} |")
    print(f"| bytes in the scratch page `${PAGE_BASE:04X}`-"
          f"`${PERSISTENT_BASE - 1:04X}` | {len(scratch)} |")
    print(f"| of those, named by an operand | "
          f"{len([r for r in scratch if r.referenced])} |")
    print(f"| scratch-page references | "
          f"{sum(len(r.writes) + len(r.reads) for r in scratch)} |")
    print("\n**What names an event.** The lost report said 158 of the named "
          "bytes had \"a printed string at the write site\", and the rule it "
          "used for *at* is not recorded. No rule tried here produces 158. "
          "This is how many written bytes have a printed string within N "
          "statements before one of their writes, so a reader can judge:\n")
    print("| statements back | addresses |")
    print("|---:|---:|")
    for n, count in naming_reach(reach, PERSISTENT_BASE, PAGE_END):
        print(f"| {n} | {count} |")
    print("\n**The gaps** -- bytes no script names and no table reaches:\n")
    print(", ".join(f"`{g}`" for g in gaps(persistent, interior)) + ".")
    print("\n**The table bases** -- an address a `GETTABLE` or `SAVETABLE` "
          "indexes off, so the bytes above it are written by a script that "
          "never names them:\n")
    for base, length, where in TABLES:
        span = (f"`${base:04X}`-`${base + length - 1:04X}`" if length
                else f"`${base:04X}`, length not established")
        print(f"* {span} -- {where}"
              f" ({', '.join(sorted(bases.get(base, ['nothing'])))})")
    for title, block, note in (
        ("The persistent block", persistent,
         "Survives an area change."),
        ("The scratch page", scratch,
         "Zeroed by the `NEWECL` handler at `DUNGEON $202A`-`$2032` whenever "
         "the resident script changes, so a byte here means something only "
         "while the party is still in the area that wrote it."),
    ):
        print(f"\n## {title}\n\n{note}\n")
        print("| addr | w | r | values written | s | scripts | what we call it |")
        print("|---|---:|---:|---|---|---|---|")
        for row in block:
            if not row.referenced and not row.interior:
                print(f"| `${row.address:04X}` | | | | | | *never referenced* |")
                continue
            what = names.get(row.address, "")
            if row.interior and not row.referenced:
                what = what or f"table interior: {row.interior}"
            print(f"| `${row.address:04X}` | {len(row.writes)} "
                  f"| {len(row.reads)} | {row.value_text} "
                  f"| {'*' if row.named else ''} "
                  f"| {', '.join(row.scripts)} | {what} |")
    del args


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("summary")
    p_map = sub.add_parser("map")
    p_map.add_argument("--scratch", action="store_true",
                       help="$4A00-$4A1F instead of the persistent block")
    p_sites = sub.add_parser("sites")
    p_sites.add_argument("address", nargs="+", help="4A81, or $4A81")
    sub.add_parser("doc")
    args = parser.parse_args()
    if not eclwalk.DISKS or not eclwalk.DISKS.exists():
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    chosen = eclwalk.scripts()
    if not chosen:
        raise SystemExit("No ECL files on those disks.")
    machine = eclwalk.Machine()
    refs, named, bases, reach = references(machine, chosen)
    check_tables(bases)
    {"summary": cmd_summary, "map": cmd_map, "sites": cmd_sites,
     "doc": cmd_doc}[args.command](refs, named, bases, reach, args)


if __name__ == "__main__":
    main()
