#!/usr/bin/env python3
"""Say whether the Amiga record's portrait byte is a menu position or an art id.

`goldbox/portraits.py` states that the Amiga Pool of Radiance record keeps the
**creation menu's one-based position** at `0x0BD` and `0x0BE`, the way DOS
does, rather than the art's own id the way the C64 does.  Until 2026-09-09 the
only evidence for that was a range: every value in the shipped records falls
inside 1-14 and 1-12, and a character the game generated looks the same either
way, so no corpus of generated characters could tell the two readings apart
(`#480`).

This tool settles it out of the engine.  It finds the creation menu's two
tables in `/program` the way `tools/amigaportraitmenu.py` does -- by the shape
of the run, checked against the art beside it -- then asks the executable's
own `RELOC32` entries **who references them**, disassembles each referring
instruction's neighbourhood, and reports the shape it found:

    tools/amigaportraitresolve.py                 # the finding, in full
    tools/amigaportraitresolve.py --check         # exit 1 if it no longer holds
    tools/amigaportraitresolve.py --out-of-range 32
    tools/amigaportraitresolve.py --file work/issue480/program

What it looks for is one instruction sequence, and either the executable has
it or the reading in `goldbox/portraits.py` is wrong:

* `move.b $bd(a0), d0` -- the record's own byte, from the current-character
  pointer;
* `lea.l <heads table minus one>, a0` and `adda.l d0, a0` -- one-based
  indexing, which is what makes the byte a position;
* `move.b (a0), d0` -- and *that* is the art id, which goes on to name a
  `HEAD<xx>` or `BODY<xx>` block in the Amiga's `head.dax` and `body.dax`.

`--out-of-range` answers the question that follows from it: the resolving
routine tests each byte for zero and for nothing else, so a value past the end
of a table indexes off it into whatever data the linker put there.  The map it
prints is what an engine would draw for a record somebody wrote by hand, and
it is a fact about **one build** of the game -- the bytes after the table are
not a table, and nothing may be written that relies on them.

**What it prints is an art id, and an art id is not a picture.** The Amiga's
`body.dax` and DOS's `BODY<n>.DAX` share a numbering and not a set of
drawings: the Amiga keeps `0D`, `18` and `22` as one block, so its `0x18` is
the drawing DOS calls `0x22` and not the one DOS calls `0x18`.  Reading the
`33 -> art 0x18` row as "this reaches the DOS body" is the mistake `#480` was
about; `tools/bodychoices.py --all` draws both containers side by side.

Every disk and executable is opened read-only; nothing is written.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import portraits  # noqa: E402
from tools import amiga68k, m68dis  # noqa: E402

#: Where the pair sits in the Amiga Pool of Radiance record, from
#: `goldbox.amiga`'s field table: the DOS record's `0x0BB`/`0x0BC` shifted by
#: the three insertions in `AMIGA_POR_SHIFTS`.
RECORD_HEAD, RECORD_BODY = 0xBD, 0xBE

#: How far either side of a referring instruction to read.  The resolving
#: sequence is nine instructions and 0x30 bytes covers it twice over.
WINDOW_BEFORE, WINDOW_AFTER = 0x30, 0x20


class NotFound(RuntimeError):
    """The executable does not have the shape this tool reports on."""


# ---------------------------------------------------------------------------
# Getting the three files
# ---------------------------------------------------------------------------
def from_disks(roots=None) -> tuple[bytes, bytes, bytes, str]:
    """`/program`, `/head.dax`, `/body.dax` off the player's own Amiga sides."""
    from tools import amigaportraitmenu

    found = amigaportraitmenu.amiga_files(roots)
    missing = [n for n in amigaportraitmenu.WANTED if n not in found]
    if missing:
        raise NotFound(f"no Amiga side here carries {', '.join(missing)}")
    return (found[portraits.AMIGA_PROGRAM][1],
            found[portraits.AMIGA_HEAD_DAX][1],
            found[portraits.AMIGA_BODY_DAX][1],
            found[portraits.AMIGA_PROGRAM][0])


def table_offset(program: bytes, head: bytes, body: bytes) -> int:
    """The file offset of the heads table, found by shape and checked by art."""
    tables = portraits.tables_from_amiga(program, head, body)
    return int(tables.source.rsplit("@", 1)[1])


# ---------------------------------------------------------------------------
# Who references the tables
# ---------------------------------------------------------------------------
def references(exe: amiga68k.Executable, program: bytes, wanted: int
               ) -> list[int]:
    """File offsets of the `abs.l` fields whose `RELOC32` target is `wanted`.

    The Amiga linker leaves a hunk-relative offset in the instruction and a
    relocation entry saying which hunk it belongs to, so a reference is found
    by matching both rather than by searching for a number.
    """
    hunk = exe.hunk_at(wanted)
    if hunk is None:
        raise NotFound(f"file offset 0x{wanted:X} is in no hunk")
    target = wanted - hunk.file_offset
    out = []
    for (number, offset), to_hunk in exe.relocs.items():
        if to_hunk != hunk.number:
            continue
        at = exe.by_number(number).file_offset + offset
        if int.from_bytes(program[at:at + 4], "big") == target:
            out.append(at)
    return sorted(out)


def _decode(program: bytes, start: int, end: int) -> list[m68dis.Instruction]:
    return m68dis.disassemble(program, start, end - start)


def routine_start(program: bytes, at: int, back: int = 0x400) -> int | None:
    """The `link.w a5, #imm` opening the routine `at` sits in, if there is one."""
    for cursor in range(at & ~1, max(0, at - back), -2):
        if program[cursor:cursor + 2] == b"\x4e\x55":
            return cursor
    return None


# ---------------------------------------------------------------------------
# The sequence that makes the byte a position
# ---------------------------------------------------------------------------
def resolves_through_table(program: bytes, field: int) -> dict | None:
    """Classify one reference: does the code index the table with a record byte?

    `field` is the file offset of the `abs.l` operand, so the instruction
    starts two bytes earlier.  Answers a dict describing the sequence, or
    `None` if the neighbourhood is not the shape this tool reports.
    """
    lea_at = field - 2
    window = _decode(program, lea_at, lea_at + WINDOW_AFTER)
    if not window or not window[0].mnemonic.startswith("lea"):
        return None
    text = [f"{i.mnemonic} {i.operands}".strip() for i in window]
    register = window[0].operands.rsplit(",", 1)[1].strip()
    index = next((n for n, t in enumerate(text[1:4], 1)
                  if t.startswith("adda.l") and t.endswith(register)), None)
    if index is None:
        return None
    indexed_by = text[index].split()[1].split(",")[0]
    load = next((t for t in text[index + 1:index + 4]
                 if t.startswith("move.b") and t.split()[1].startswith(f"({register}")),
                None)
    if load is None:
        return None

    opens = routine_start(program, lea_at)
    start = opens if opens is not None else max(0, lea_at - WINDOW_BEFORE)
    before = _decode(program, start, lea_at)
    came_from, reads = _provenance(before)
    if came_from.get(indexed_by) is None:
        return None
    return {
        "lea": lea_at,
        "indexed_by": indexed_by,
        "record_offset": came_from[indexed_by],
        "art_into": load.rsplit(",", 1)[1].strip(),
        "reads": reads,
        "sequence": [(i.address, f"{i.mnemonic} {i.operands}".strip())
                     for i in window[:index + 3]],
    }


def _provenance(before: list) -> tuple[dict[str, int], list[tuple[int, str]]]:
    """Which data register last came from record `+0xBD` or `+0xBE`, and where.

    A byte reaches the index register through a copy -- `move.b $bd(a0), d0`
    then `move.b d0, d1` -- so following the copies is what says *which* of
    the two fields indexes *which* table.  Any other write to a register
    clears it, which errs towards reporting nothing rather than towards
    reporting the wrong field.
    """
    wanted = {f"${RECORD_HEAD:x}(": RECORD_HEAD, f"${RECORD_BODY:x}(": RECORD_BODY}
    came_from: dict[str, int] = {}
    reads: list[tuple[int, str]] = []
    for item in before:
        operands = item.operands
        if "," not in operands:
            continue
        source, destination = operands.rsplit(",", 1)
        destination = destination.strip()
        if not (len(destination) == 2 and destination[0] == "d"):
            continue
        origin = None
        if item.mnemonic == "move.b":
            for prefix, offset in wanted.items():
                if source.startswith(prefix):
                    origin = offset
                    reads.append((item.address, f"{item.mnemonic} {operands}"))
            if origin is None and len(source) == 2 and source[0] == "d":
                origin = came_from.get(source)
        came_from[destination] = origin
    return came_from, reads


def tests_on_the_path(program: bytes, start: int, end: int) -> list[tuple[int, str]]:
    """Every compare, test or mask between two offsets, so a bound cannot hide.

    A range check on the record's byte would be one of these, and the claim
    that the resolving routine applies none but a test for zero is only
    checkable if the list is printed rather than asserted.
    """
    kinds = ("cmp", "tst", "chk", "and", "btst", "bclr", "sub", "lsr", "asr")
    return [(i.address, f"{i.mnemonic} {i.operands}".strip())
            for i in _decode(program, start, end)
            if any(i.mnemonic.startswith(k) for k in kinds)]


# ---------------------------------------------------------------------------
# What a value past the end of a table reaches
# ---------------------------------------------------------------------------
def out_of_range(program: bytes, base: int, count: int, upto: int
                 ) -> list[tuple[int, int, bool]]:
    """`(value, byte the engine would fetch, whether it is in the table)`.

    `base` is the table's own first byte and the code indexes from `base - 1`,
    so value `n` fetches `program[base - 1 + n]`.
    """
    return [(n, program[base - 1 + n], 1 <= n <= count)
            for n in range(1, upto + 1)]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def report(program: bytes, heads_at: int, where: str, upto: int = 0) -> list[str]:
    exe = amiga68k.Executable.parse(program)
    bodies_at = heads_at + portraits.HEAD_COUNT
    lines = [f"/program: {where} ({len(program)} bytes)",
             f"creation menu: heads at file 0x{heads_at:X}, "
             f"bodies at file 0x{bodies_at:X}"]

    findings = []
    for name, at, count in (("heads", heads_at, portraits.HEAD_COUNT),
                            ("bodies", bodies_at, portraits.BODY_COUNT)):
        refs = references(exe, program, at - 1)
        lines.append("")
        lines.append(f"{name}: {len(refs)} reference(s) to the table's byte "
                     f"before it (0x{at - 1:X}), which is one-based indexing")
        for field in refs:
            found = resolves_through_table(program, field)
            if found is None:
                lines.append(f"  0x{field - 2:06X}: not the resolving shape")
                continue
            findings.append((name, at, count, found))
            lines.append(f"  0x{found['lea']:06X}: record +0x"
                         f"{found['record_offset']:02X} -> {found['indexed_by']}"
                         f" -> table -> {found['art_into']}")
            for address, text in found["sequence"]:
                lines.append(f"      {address:06x}: {text}")

    if findings:
        first = min(f["reads"][0][0] for _n, _a, _c, f in findings)
        last = max(f["sequence"][-1][0] for _n, _a, _c, f in findings)
        lines.append("")
        lines.append(f"tests applied between 0x{first:06X} and 0x{last:06X}, "
                     "which is the whole resolving path:")
        for address, text in tests_on_the_path(program, first, last):
            lines.append(f"  {address:06x}: {text}")

    if upto:
        for name, at, count in (("heads", heads_at, portraits.HEAD_COUNT),
                                ("bodies", bodies_at, portraits.BODY_COUNT)):
            lines.append("")
            lines.append(f"{name}: what a record value fetches, 1..{upto}")
            for value, byte, inside in out_of_range(program, at, count, upto):
                mark = "" if inside else "   <- past the end of the table"
                lines.append(f"  {value:3d} -> art 0x{byte:02X}{mark}")
    return lines


def checks(program: bytes, heads_at: int) -> list[str]:
    """Everything this tool asserts, as `[]` when the executable still has it."""
    bad = []
    exe = amiga68k.Executable.parse(program)
    for name, at, offset in (("heads", heads_at, RECORD_HEAD),
                             ("bodies", heads_at + portraits.HEAD_COUNT,
                              RECORD_BODY)):
        refs = references(exe, program, at - 1)
        if not refs:
            bad.append(f"{name}: nothing references the table's base minus one")
            continue
        shapes = [resolves_through_table(program, f) for f in refs]
        shapes = [s for s in shapes if s]
        if not shapes:
            bad.append(f"{name}: no reference resolves a record byte through it")
        elif not any(s["record_offset"] == offset for s in shapes):
            bad.append(f"{name}: no reference indexes it with record +0x{offset:02X}")
    return bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", help="a copy of /program, instead of the disks")
    parser.add_argument("--head", help="a copy of /head.dax, with --file")
    parser.add_argument("--body", help="a copy of /body.dax, with --file")
    parser.add_argument("--out-of-range", type=int, default=0, metavar="N",
                        help="also print what values 1..N fetch")
    parser.add_argument("--check", action="store_true",
                        help="print nothing but failures, and exit 1 on one")
    args = parser.parse_args(argv)

    try:
        if args.file:
            program = pathlib.Path(args.file).read_bytes()
            where = args.file
            if args.head and args.body:
                head = pathlib.Path(args.head).read_bytes()
                body = pathlib.Path(args.body).read_bytes()
            else:
                head = body = None
        else:
            program, head, body, where = from_disks()
        if head is None or body is None:
            _p, head, body, _w = from_disks()
        heads_at = table_offset(program, head, body)
    except (NotFound, portraits.PortraitError, OSError) as exc:
        print(f"amigaportraitresolve: {exc}", file=sys.stderr)
        return 2

    if args.check:
        bad = checks(program, heads_at)
        for line in bad:
            print(f"amigaportraitresolve: {line}", file=sys.stderr)
        return 1 if bad else 0
    print("\n".join(report(program, heads_at, where, args.out_of_range)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
