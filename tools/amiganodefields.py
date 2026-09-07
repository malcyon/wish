#!/usr/bin/env python3
"""Which bytes of an Amiga Gold Box heap node the game's own code touches.

`#387 (The Amiga Silver Blades effect node keeps a byte DOS has not got, and
a converted character loses it)` asked what the byte at offset 1 of an Amiga
*Secret of the Silver Blades* effect node holds.  Grepping a 300KB code hunk
for a literal `$1(aN)` answers nothing, because a byte reached through a
register that was loaded three instructions earlier does not look like a
reference to a fixed address.  This asks the question from the other end.

Every node of a given kind is a slot in one **fixed-size pool**, and a pool
is a five-field descriptor in the SAS/Lattice small-data segment: slot count,
element size, base pointer, then the allocation bitmap.  So every node
pointer in the program is born at a reference to that descriptor, and every
one afterwards is reached from a record's chain-head field or from a node's
own `next`.  Both are countable:

* `pool` lists every instruction that names the descriptor and says whether
  it allocates, frees or sets the pool up, with the routine's own call to
  the allocator resolved;
* `fields` walks forward from every load of the chain-head field, tracks
  which address registers hold a node, and prints every displacement each
  instruction reads or writes through one -- which offsets of the node the
  game uses, and at what width.

`tools/amigarecordrefs.py` is the same question asked of a **character
record** and the search there is a displacement search, which works because
`$145(a0)` is a rare two-byte pattern.  It does not work here: a ten-byte
node's fields are `$1` to `$6`, and `$1(aN)` matches 81 instructions in
`/Secret` of which none is a node.  Hence the walk.

The register walk **over-approximates**: it keeps a register marked as
holding a node until something overwrites it, ignores control flow, and runs
to a fixed point.  That is the safe direction for the question being asked.
A displacement it does not report is one no instruction downstream of a
chain-head load can reach, whatever path the game takes; a displacement it
does report may be a coincidence of the over-approximation and has to be
read.

Nothing is written, and both disk images are opened read-only.

    tools/amiganodefields.py --adf <ssb-disk-1.adf> --exe /Secret \\
        pool --global 7618
    tools/amiganodefields.py --adf <ssb-disk-1.adf> --exe /Secret \\
        fields --chain 96 --size 10
    tools/amiganodefields.py --adf <curse-disk-1.adf> --exe /Curse \\
        fields --chain f2 --size 10
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import capstone  # noqa: E402

from tools.amiga68k import Executable, load  # noqa: E402
from tools.amigaglobal import code_range, operand  # noqa: E402

#: `d16(aN)` as capstone prints it, with the displacement and the register.
DISPLACED = re.compile(r"(-?)\$([0-9a-f]+)\((a[0-7])\)")
#: `(aN)` with no displacement, which is the node's own offset 0.
DIRECT = re.compile(r"(?<![\w$)])\((a[0-7])\)")
#: `movea.l <something>, aN` -- the only way an address register is loaded
#: with a pointer on this compiler's output.
LOAD_A = re.compile(r"^(.*),\s*(a[0-7])$")

#: How wide each mnemonic's memory operand is, for the report.
WIDTH = {"b": 1, "w": 2, "l": 4}


def _md() -> "capstone.Cs":
    return capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)


def _decode_one(md, code: bytes, base: int, at: int):
    """The one instruction starting at file offset `at`, or `None`."""
    for ins in md.disasm(code[at - base:at - base + 12], at):
        return ins
    return None


def sites(exe: Executable, pattern: re.Pattern) -> list:
    """Every word-aligned offset whose instruction matches, decoded alone.

    Decoding each candidate from its own start is what `tools/amigaglobal.py`
    does and for the same reason: a linear sweep of a 300KB code hunk
    desynchronises on the jump tables and string data between routines.
    """
    start, size = code_range(exe)
    code = exe.data[start:start + size]
    md, out = _md(), []
    for at in range(0, size - 1, 2):
        for ins in md.disasm(code[at:at + 12], start + at):
            if pattern.search(ins.op_str):
                out.append(ins)
            break
    return out


def width_of(mnemonic: str) -> int | None:
    """1, 2 or 4 from a mnemonic's suffix; `None` when it carries none."""
    head, _, suffix = mnemonic.partition(".")
    return WIDTH.get(suffix)


def is_write(mnemonic: str, op_str: str, register: str) -> bool:
    """Whether the instruction stores through `register`.

    `clr`, `move X, d16(aN)` and the read-modify-writes all write; a `move
    d16(aN), X`, a `tst`, a `cmp` and a `lea` do not.  Anything unrecognised
    is called a write, so the report never quietly downgrades one.
    """
    head = mnemonic.split(".")[0]
    if head in ("tst", "cmp", "cmpi", "cmpa", "btst", "lea", "pea", "jsr",
                "jmp"):
        return False
    if head in ("clr", "st", "sf"):
        return True
    if head.startswith("move") or head in ("or", "and", "add", "sub", "eor",
                                           "ori", "andi", "addi", "subi",
                                           "eori", "not", "neg", "bset",
                                           "bclr", "bchg", "asl", "asr",
                                           "lsl", "lsr", "addq", "subq"):
        # The destination is the last operand.
        return op_str.rsplit(",", 1)[-1].strip().endswith(f"({register})")
    return True


def _touches(ins, register: str) -> list[tuple[int, int | None, bool]]:
    """`(displacement, width, writes)` for each access through `register`."""
    out = []
    for sign, digits, reg in DISPLACED.findall(ins.op_str):
        if reg != register or sign == "-":
            continue
        out.append((int(digits, 16), width_of(ins.mnemonic),
                    is_write(ins.mnemonic, ins.op_str, register)))
    for reg in DIRECT.findall(ins.op_str):
        if reg == register:
            out.append((0, width_of(ins.mnemonic),
                        is_write(ins.mnemonic, ins.op_str, register)))
    return out


def walk(exe: Executable, start_at: int, chain: int, node_next: int,
         span: int = 0x400, passes: int = 3) -> dict:
    """Node displacements reachable from one chain-head load.

    Decodes forward from `start_at` for `span` bytes, marking an address
    register as holding a node when it is loaded from the record's chain
    head or from a node's `next`, and clearing it when anything else is
    written to it.  Repeats until the marks stop growing, which is what
    catches a chain walked by a backward branch.
    """
    base, size = code_range(exe)
    code = exe.data[base:base + size]
    md = _md()
    held: set[str] = set()
    found: dict[tuple[int, int | None, bool], list[int]] = {}
    calls: dict[int, set[str]] = {}
    for _ in range(passes):
        before = len(found)
        at = start_at
        while at < min(start_at + span, base + size):
            ins = _decode_one(md, code, base, at)
            if ins is None:
                break
            op = ins.op_str
            for register in sorted(held):
                for hit in _touches(ins, register):
                    found.setdefault(hit, []).append(ins.address)
            # A node pointer is born here, or moves to another register.
            loaded = LOAD_A.match(op)
            if loaded:
                source, target = loaded.group(1).strip(), loaded.group(2)
                becomes = False
                if re.fullmatch(rf"\${chain:x}\(a[0-7]\)", source):
                    becomes = True
                if any(re.fullmatch(rf"\${node_next:x}\({r}\)", source)
                       for r in held):
                    becomes = True
                if source in held:
                    becomes = True
                if becomes:
                    held.add(target)
                elif target in held:
                    held.discard(target)
            if ins.mnemonic.split(".")[0] == "jsr" and held:
                calls.setdefault(ins.address, set()).update(held)
            if ins.mnemonic.split(".")[0] in ("rts", "rte"):
                break
            at = ins.address + ins.size
        if len(found) == before:
            break
    return {"displacements": found, "calls": calls}


def report_fields(exe: Executable, chain: int, node_next: int, size: int,
                  span: int) -> list[str]:
    """The whole census: every chain-head load, every node byte touched."""
    heads = sites(exe, re.compile(rf"(?<!-)\${chain:x}\(a[0-7]\)"))
    lines = [f"{len(heads)} instructions name the chain head at "
             f"${chain:x}(aN)"]
    every: dict[tuple[int, int | None, bool], list[int]] = {}
    calls: dict[int, set[str]] = {}
    for ins in heads:
        out = walk(exe, ins.address, chain, node_next, span)
        for key, where in out["displacements"].items():
            every.setdefault(key, []).extend(where)
        for where, regs in out["calls"].items():
            calls.setdefault(where, set()).update(regs)
    lines.append("")
    lines.append("node offset  width  access  sites  first three")
    per: dict[int, list] = collections.defaultdict(list)
    for (offset, width, writes), where in sorted(every.items()):
        per[offset].append((width, writes, sorted(set(where))))
    for offset in range(size):
        rows = per.get(offset)
        if not rows:
            lines.append(f"  {offset:#05x}      --     --        0  "
                         f"no instruction reaches it")
            continue
        for width, writes, where in rows:
            first = " ".join(f"{w:06x}" for w in where[:3])
            lines.append(f"  {offset:#05x}      {width or '?'}    "
                         f"{'write' if writes else 'read ':5}  "
                         f"{len(where):5}  {first}")
    if calls:
        lines.append("")
        lines.append("routines called while a node pointer was live:")
        for where in sorted(calls):
            lines.append(f"  {where:06x}  ({', '.join(sorted(calls[where]))})")
    return lines


def report_pool(exe: Executable, pool: int) -> list[str]:
    """Every instruction that names a pool descriptor, classified."""
    text = operand(pool)
    hits = sites(exe, re.compile(re.escape(text)))
    lines = [f"g{pool:04x} ({text}): {len(hits)} references"]
    base, size = code_range(exe)
    code, md = exe.data[base:base + size], _md()
    for ins in hits:
        note = ""
        if ins.mnemonic.startswith("pea"):
            # The call three to five instructions on is what it is for.
            at, seen = ins.address + ins.size, []
            for _ in range(6):
                nxt = _decode_one(md, code, base, at)
                if nxt is None:
                    break
                seen.append(nxt)
                if nxt.mnemonic.split(".")[0] == "jsr":
                    target = None
                    m = re.search(r"(-?\$[0-9a-f]+)\(a4\)", nxt.op_str)
                    if m and exe.small_data is not None:
                        target = exe.resolve_a4(
                            int(m.group(1).replace("$", "0x"), 16))
                    note = (f"-> {target:06x}" if target
                            else f"-> {nxt.op_str}")
                    sizes = [s.op_str for s in seen
                             if s.mnemonic.startswith("move.w")
                             and s.op_str.endswith("-(a7)")]
                    if sizes:
                        note += f"   size {sizes[0].split(',')[0]}"
                    break
                at = nxt.address + nxt.size
        lines.append(f"  {ins.address:06x}  {ins.mnemonic:<9} "
                     f"{ins.op_str:<26}{note}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adf", help="a disk image holding the executable")
    parser.add_argument("--exe", help="the executable's path on the disk")
    parser.add_argument("--file", help="the executable as a loose file")
    sub = parser.add_subparsers(dest="command", required=True)
    pool = sub.add_parser("pool", help="who allocates and frees a node")
    pool.add_argument("--global", dest="pool", required=True,
                      help="the pool descriptor's data-hunk offset, hex")
    fields = sub.add_parser("fields", help="which node bytes the code uses")
    fields.add_argument("--chain", required=True,
                        help="the record's chain-head displacement, hex")
    fields.add_argument("--next", default="6",
                        help="the node's own next displacement, hex "
                             "(default 6)")
    fields.add_argument("--size", type=int, default=10,
                        help="the node's size in bytes (default 10)")
    fields.add_argument("--span", default="400",
                        help="how far to walk from each load, hex "
                             "(default 400)")
    args = parser.parse_args(argv)

    exe = Executable.parse(load(args))
    if args.command == "pool":
        lines = report_pool(exe, int(args.pool, 16))
    else:
        lines = report_fields(exe, int(args.chain, 16), int(args.next, 16),
                              args.size, int(args.span, 16))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
