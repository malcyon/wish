#!/usr/bin/env python3
"""Which instructions in a DOS memory image touch a character-record offset.

A companion to `tools/dosfightwatch.py` for the half of `#69 (No
WRITE_UNSOURCED zero has been tested during combat)` no watchpoint can answer.
DOSBox-X's three memory breakpoints -- `BPM`, `BPLM`, `BPPM` -- are all on
*change*, so "is this byte read during a round" cannot be put to the emulator.
It can be put to the code: a character record is reached through a far
pointer, so the compiler emits `es:[di+<offset>]`, and every instruction that
touches `hands_used` is an `ES`-prefixed byte access at displacement `0x100`.

Counting them across a memory image says how many places in the game can see
a field at all, and which of those write it rather than read it.  The two
writes to `0x100` this found -- an immediate zero and an accumulate, both
inside one routine -- are what turned "the engine rewrote it by the end of the
fight" into "the engine discards it before it can be read".

**What this is evidence of, and what it is not.**  Three limits, and the
third is the one that bites hardest:

1. A displacement match does not prove the pointer is a character record: any
   structure reached the same way with a field at the same offset matches too.
2. An offset can be reached without a matching displacement -- a pointer added
   into a register first, a `rep movsb` that copies the whole record, a `lea`.
   So **an empty result is evidence rather than proof**.
3. **Nothing here checks that a match is an instruction.**  The image is
   scanned as an undifferentiated byte stream, so a match may fall in the
   stack, in the heap, in video memory, in a string table, or across the tail
   of one instruction and the head of the next -- three bytes of `26 8B 85`
   are as likely to be data as code, and a linear scan cannot tell.  The only
   filters are that the opcode and the ModRM `reg` decode to an instruction
   the 8086 defines, and `--region`, which is a memory-map bound rather than a
   real one.  A sound answer would need a disassembler walking from known
   entry points, and this is not that.

So a count from this tool is an **upper bound**.  A single site is only worth
believing when something else corroborates it -- a `BPM` hit landing at the
`CS:IP` after it, or a disassembly of the routine around it that makes sense.

**One image is one set of overlays.**  Pool of Radiance overlays its code, so
an image holds only what was resident when it was dumped.  Pass every dump a
run made -- at the encounter and after the fight -- and the union is what was
loaded across the fight.

    tools/dosfieldrefs.py work/issue69/watch13b/memory-*.bin --offset 0x100
    tools/dosfieldrefs.py work/issue69/*/memory-*.bin --unsourced
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos  # noqa: E402
from goldbox import dos_layout as dl  # noqa: E402

#: Segment override prefixes, by opcode byte.
SEGMENT_PREFIX = {0x26: "es", 0x2E: "cs", 0x36: "ss", 0x3E: "ds"}

#: The 8086 opcodes that take a `mod reg r/m` byte and touch memory, with what
#: they do to it.  `W` writes without reading, `R` reads, `RW` does both --
#: which is the distinction the whole exercise turns on, since a field that is
#: only ever the destination of an immediate store cannot be misread.
#:
#: **Six opcodes are not in here, because the opcode does not decide.**  For
#: `0x80`, `0x81`, `0x83`, `0xF6`, `0xF7`, `0xFE` and `0xFF` the operation is
#: chosen by the ModRM `reg` sub-field, and `GROUPS` below carries them.  This
#: table called all seven `RW` in its first version, which counted a
#: `cmp byte ptr es:[di+100h], 0` and a `push word ptr es:[di+104h]` as writes.
OPCODES = {
    0x88: ("W", "mov m8,r8"), 0x89: ("W", "mov m16,r16"),
    0x8A: ("R", "mov r8,m8"), 0x8B: ("R", "mov r16,m16"),
    0xC6: ("W", "mov m8,imm8"), 0xC7: ("W", "mov m16,imm16"),
    0xC4: ("R", "les r16,m32"), 0xC5: ("R", "lds r16,m32"),
    0x8D: ("-", "lea r16,m"),
    0x00: ("RW", "add m8,r8"), 0x01: ("RW", "add m16,r16"),
    0x02: ("R", "add r8,m8"), 0x03: ("R", "add r16,m16"),
    0x08: ("RW", "or m8,r8"), 0x09: ("RW", "or m16,r16"),
    0x0A: ("R", "or r8,m8"), 0x0B: ("R", "or r16,m16"),
    0x20: ("RW", "and m8,r8"), 0x21: ("RW", "and m16,r16"),
    0x22: ("R", "and r8,m8"), 0x23: ("R", "and r16,m16"),
    0x28: ("RW", "sub m8,r8"), 0x29: ("RW", "sub m16,r16"),
    0x2A: ("R", "sub r8,m8"), 0x2B: ("R", "sub r16,m16"),
    0x30: ("RW", "xor m8,r8"), 0x31: ("RW", "xor m16,r16"),
    0x32: ("R", "xor r8,m8"), 0x33: ("R", "xor r16,m16"),
    0x38: ("R", "cmp m8,r8"), 0x39: ("R", "cmp m16,r16"),
    0x3A: ("R", "cmp r8,m8"), 0x3B: ("R", "cmp r16,m16"),
    0x84: ("R", "test m8,r8"), 0x85: ("R", "test m16,r16"),
}

#: The opcodes whose operation is the ModRM `reg` field, by `reg`.
#:
#: Group 1 (`0x80`, `0x81`, `0x83`) is `add or adc sbb and sub xor cmp`, and
#: only the last of the eight leaves the memory operand alone.  Group 3
#: (`0xF6`, `0xF7`) writes memory for `not` and `neg` and for nothing else --
#: `test`, `mul`, `imul`, `div` and `idiv` all read it and write a register.
#: Group 5 (`0xFF`) writes for `inc` and `dec`, and for `call`, `jmp` and
#: `push` it only reads the pointer through.
GROUPS: dict[int, dict[int, tuple[str, str]]] = {
    0x80: {r: ("RW", n + " m8,imm8") for r, n in enumerate(
        ("add", "or", "adc", "sbb", "and", "sub", "xor"))},
    0x81: {r: ("RW", n + " m16,imm16") for r, n in enumerate(
        ("add", "or", "adc", "sbb", "and", "sub", "xor"))},
    0x83: {r: ("RW", n + " m16,imm8") for r, n in enumerate(
        ("add", "or", "adc", "sbb", "and", "sub", "xor"))},
    0xF6: {0: ("R", "test m8,imm8"), 1: ("R", "test m8,imm8"),
           2: ("RW", "not m8"), 3: ("RW", "neg m8"),
           4: ("R", "mul m8"), 5: ("R", "imul m8"),
           6: ("R", "div m8"), 7: ("R", "idiv m8")},
    0xF7: {0: ("R", "test m16,imm16"), 1: ("R", "test m16,imm16"),
           2: ("RW", "not m16"), 3: ("RW", "neg m16"),
           4: ("R", "mul m16"), 5: ("R", "imul m16"),
           6: ("R", "div m16"), 7: ("R", "idiv m16")},
    0xFE: {0: ("RW", "inc m8"), 1: ("RW", "dec m8")},
    0xFF: {0: ("RW", "inc m16"), 1: ("RW", "dec m16"),
           2: ("R", "call m16"), 3: ("R", "call far m32"),
           4: ("R", "jmp m16"), 5: ("R", "jmp far m32"),
           6: ("R", "push m16")},
}
GROUPS[0x80][7] = ("R", "cmp m8,imm8")
GROUPS[0x81][7] = ("R", "cmp m16,imm16")
GROUPS[0x83][7] = ("R", "cmp m16,imm8")

#: Where a linear address lies in a PC's memory map, which is the only check
#: this tool makes that a match is code at all -- and it is a weak one.
REGIONS = (
    (0x00000, 0x00600, "interrupt vectors and BIOS data"),
    (0x00600, 0xA0000, "conventional memory: DOS, the game, its heap and stack"),
    (0xA0000, 0xC0000, "video memory"),
    (0xC0000, 0x100000, "option ROMs and the BIOS"),
)


def region_of(linear: int) -> str:
    """Which entry of `REGIONS` an address is in."""
    for lo, hi, name in REGIONS:
        if lo <= linear < hi:
            return name
    return "above 1MB"


#: `mod reg r/m`'s r/m field, for the addressing forms with a displacement.
RM = {0: "bx+si", 1: "bx+di", 2: "bp+si", 3: "bp+di",
      4: "si", 5: "di", 6: "bp", 7: "bx"}


def references(image: bytes, offset: int, *,
               prefixes: tuple[int, ...] = (0x26,)) -> list[dict]:
    """Every instruction in `image` addressing `<seg>:[<reg>+offset]`.

    Both displacement encodings are searched: `mod=01` with a signed byte,
    which is how a displacement under 128 is emitted, and `mod=10` with a
    word.  Missing the byte form is how a scan for `effect_chain` at `0x07F`
    would come back empty and mean nothing.
    """
    out: list[dict] = []
    lo, hi = offset & 0xFF, (offset >> 8) & 0xFF
    byte_form = 0 <= offset <= 0x7F
    for i in range(len(image) - 8):
        j = i
        seg = ""
        if image[j] in prefixes:
            seg = SEGMENT_PREFIX[image[j]] + ":"
            j += 1
        elif prefixes and image[j] in SEGMENT_PREFIX:
            continue          # a different segment override; not ours
        elif prefixes:
            continue          # a prefix was asked for and there is none
        op = image[j]
        if op not in OPCODES and op not in GROUPS:
            continue
        m = image[j + 1]
        mod, reg, rm = m >> 6, (m >> 3) & 7, m & 7
        if mod == 0b01:
            if not byte_form or image[j + 2] != lo:
                continue
        elif mod == 0b10:
            if image[j + 2] != lo or image[j + 3] != hi:
                continue
        else:
            continue
        if op in GROUPS:
            # **The `reg` field is the operation, not the opcode.**  Reading
            # it is the difference between calling `cmp es:[di+100h], 0` a
            # write and calling it what it is.  A `reg` with no entry is an
            # encoding the 8086 does not define, so it is not an instruction
            # and the match is discarded.
            entry = GROUPS[op].get(reg)
            if entry is None:
                continue
            kind, mnem = entry
        else:
            kind, mnem = OPCODES[op]
        out.append({"linear": i, "seg": seg, "rm": RM[rm], "reg": reg,
                    "kind": kind, "mnem": mnem, "region": region_of(i),
                    "disp": "byte" if mod == 0b01 else "word"})
    return out


def unsourced_fields() -> list[tuple[str, int, int]]:
    """`(name, offset, size)` for every field `goldbox.dos.write` zeroes."""
    return [(n, dl.FIELDS_BY_NAME[n].offset, dl.FIELDS_BY_NAME[n].size)
            for n, _ in dos.WRITE_UNSOURCED]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("images", nargs="+", help="memory images to scan")
    ap.add_argument("--offset", default=None,
                    help="the record offset, e.g. 0x100")
    ap.add_argument("--unsourced", action="store_true",
                    help="every offset goldbox.dos.write leaves zero")
    ap.add_argument("--any-segment", action="store_true",
                    help="do not require an ES override (noisier by far)")
    ap.add_argument("--region", default=None,
                    help="only count hits inside LOW-HIGH, e.g. 0x600-0xA0000")
    args = ap.parse_args(argv)

    if args.unsourced:
        wanted = [(n, off) for n, off, _ in unsourced_fields()]
    elif args.offset:
        wanted = [(args.offset, int(args.offset, 0))]
    else:
        ap.error("name an --offset or ask for --unsourced")

    prefixes: tuple[int, ...] = () if args.any_segment else (0x26,)
    bound = None
    if args.region:
        first, _, last = args.region.partition("-")
        bound = (int(first, 0), int(last, 0))
    images = {p: pathlib.Path(p).read_bytes() for p in args.images}
    print(f"{len(images)} image(s), "
          f"{'any segment' if args.any_segment else 'ES-prefixed only'}\n")
    for name, off in wanted:
        seen: dict[int, dict] = {}
        per_image: dict[str, int] = {}
        for path, img in images.items():
            hits = references(img, off, prefixes=prefixes)
            per_image[pathlib.Path(path).parent.name + "/"
                      + pathlib.Path(path).name] = len(hits)
            for h in hits:
                if bound and not bound[0] <= h["linear"] < bound[1]:
                    continue
                seen.setdefault(h["linear"], h)
        writes = sum(1 for h in seen.values() if "W" in h["kind"])
        reads = sum(1 for h in seen.values() if "R" in h["kind"])
        print(f"{name} (+{off:#05x}): {len(seen)} site(s), "
              f"{writes} write, {reads} read")
        for lin in sorted(seen):
            h = seen[lin]
            print(f"    {lin:06X}  {h['kind']:2s} {h['mnem']:16s}"
                  f" {h['seg']}[{h['rm']}+{off:#x}]")
        for k, v in per_image.items():
            print(f"      {v:3d} in {k}")
        regions: dict[str, int] = {}
        for h in seen.values():
            regions[h["region"]] = regions.get(h["region"], 0) + 1
        for region, n in sorted(regions.items(), key=lambda kv: -kv[1]):
            print(f"      {n:3d} in {region}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
