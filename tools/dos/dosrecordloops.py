#!/usr/bin/env python3
"""What actually walks a DOS record array: the index slot, not any nearby cmp.

`tools/dos/dosarraywidth.py` tallies every `cmp byte [bp-n], imm` in the 90 bytes
before an `es:[di+disp]` access, whatever `n` is.  In this compiler's output
that window routinely crosses a `retf` into the previous subroutine, so the
immediate can belong to a loop that has nothing to do with the array.

This reads the same sites and asks three narrower questions per site:

* is the access **indexed** at all -- is there an `add di, ax` fed by a byte
  stack slot immediately before it, or is the displacement fixed?
* if it is indexed by `[bp-n]`, what is the `cmp byte [bp-n], imm` that the
  loop's own backward jump tests, and where is `[bp-n]` initialised?
* is the loop 0-based (`mov byte [bp-n], 0`, so `imm+1` entries at
  `disp .. disp+imm`) or 1-based (`mov byte [bp-n], 1`, so `imm` entries at
  `disp+1 .. disp+imm`)?

1-based is the case `dosarraywidth` cannot see at all: the instruction then
carries `offset - 1` as its displacement, so scanning at the field's own
offset finds nothing.

**The index is not always a straight byte count.** A `shl ax, N` between the
byte load and `add di, ax` scales the index -- the seven coin purses in
`goldbox/dos_port.py` are `word` values walked by a `for i := 0 to 6` loop
with `shl ax, 1` before the add, so the loop bound (7 entries) and the byte
span it covers (14 bytes) are not the same number.  Reported as `stride`; a
span that ignores it is half (or a quarter) of the true one.

Promoted from `issue516/loopwalk.py` (scratch, deleted) for `#516 (Generate boundary
characters and check every writer's field widths, since no real save reaches
a limit and the corpus cannot find a wrong one)`'s slice 3, which used it to
settle `spells_castable_cleric`, `attack_forms` and `field_83_87`.

    tools/dos/dosrecordloops.py <title> <hex-displacement>[,<hex>...]
    tools/dos/dosrecordloops.py <title> --field attack_forms --around 2

Reads the player's own archives through `tools/dos/dosbox.find_game` (via
`tools/dos/dosarraywidth.find_overlay`) and writes nothing.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import capstone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from goldbox import dos_port  # noqa: E402
from tools.dos import dosarraywidth  # noqa: E402

MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
BACK = 420


def stream(data: bytes, at: int, back: int = BACK, fwd: int = 48):
    """Instructions over [at-back, at+fwd], synchronised on `at`."""
    for start in range(max(0, at - back), at + 1):
        ins = list(MD.disasm(data[start:at + fwd], start))
        if any(i.address == at for i in ins):
            return ins
    return list(MD.disasm(data[at:at + fwd], at))


def _imm(op: str) -> int | None:
    """The last operand as an integer -- capstone prints small immediates
    without an `0x` prefix, which is what this is here for."""
    try:
        return int(op.split(", ")[-1], 0)
    except ValueError:
        return None


def _slot(op: str) -> str | None:
    """`[bp - 2]` out of an operand string, or None."""
    if op.startswith("byte ptr [bp") and op.endswith("]"):
        return op[len("byte ptr "):]
    return None


def analyse(data: bytes, at: int) -> dict:
    ins = stream(data, at)
    here = [n for n, i in enumerate(ins) if i.address == at]
    if not here:
        return {"at": at, "text": "?", "indexed": None}
    k = here[0]
    out = {"at": at, "text": f"{ins[k].mnemonic} {ins[k].op_str}",
           "indexed": False, "slot": None, "bound": None, "init": None,
           "boundat": None, "initat": None, "backjump": None, "stride": 1}
    # An indexed access is `mov al, [bp-n] / cbw / [shl ax, N] / les di, [..]
    # / add di, ax` in the handful of instructions before it.  The optional
    # `shl` scales the index -- a word-strided array doubles it, and nothing
    # else in this window multiplies `ax`.
    slot = None
    stride = 1
    for j in range(max(0, k - 6), k):
        if ins[j].mnemonic == "mov" and ins[j].op_str.startswith("al, byte ptr [bp"):
            slot = _slot(ins[j].op_str.split(", ", 1)[1])
        if ins[j].mnemonic == "shl" and ins[j].op_str.startswith("ax,") and slot:
            n = _imm(ins[j].op_str)
            if n:
                stride *= (1 << n)
        if ins[j].mnemonic == "add" and ins[j].op_str == "di, ax" and slot:
            out["indexed"] = True
            out["slot"] = slot
            out["stride"] = stride
    if not out["indexed"]:
        return out
    # The loop's bottom test: `cmp byte ptr [bp-n], imm` on the same slot,
    # followed by a jump backwards.  This compiler puts it *after* the body,
    # so look forward first and only then back.
    order = list(range(k, len(ins))) + list(range(k, -1, -1))
    for j in order:
        i = ins[j]
        if (i.mnemonic == "cmp" and _slot(i.op_str.split(", ")[0]) == out["slot"]
                and _imm(i.op_str) is not None):
            nxt = ins[j + 1] if j + 1 < len(ins) else None
            if nxt and nxt.mnemonic.startswith("j") and nxt.mnemonic != "jmp":
                target = int(nxt.op_str, 16)
                out["bound"] = _imm(i.op_str)
                out["boundat"] = i.address
                out["backjump"] = (nxt.mnemonic, target, target < i.address)
                break
    # Where the index is initialised.
    for j in range(k, -1, -1):
        i = ins[j]
        if (i.mnemonic == "mov" and _slot(i.op_str.split(", ")[0]) == out["slot"]
                and _imm(i.op_str) is not None):
            out["init"] = _imm(i.op_str)
            out["initat"] = i.address
            break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("title")
    ap.add_argument("displacements", nargs="?", default=None)
    ap.add_argument("--field")
    ap.add_argument("--around", type=int, default=0,
                    help="also scan this many displacements either side")
    ap.add_argument("--overlay", type=pathlib.Path)
    args = ap.parse_args(argv)

    overlay = args.overlay or dosarraywidth.find_overlay(args.title)
    data = overlay.read_bytes()
    if args.field:
        f = dos_port.FIELDS_BY_NAME_FOR[args.title][args.field]
        lo, hi = f.offset - args.around, f.offset + f.size - 1 + args.around
        disps = list(range(lo, hi + 1))
        print(f"{args.title}: {args.field} @{f.offset:#05x} size {f.size}; "
              f"scanning {lo:#05x}-{hi:#05x}")
    else:
        disps = [int(s, 16) for s in args.displacements.split(",")]
        print(f"{args.title}: scanning "
              + ", ".join(f"{d:#05x}" for d in disps))

    for disp in disps:
        sites = dosarraywidth.accesses(data, disp)
        if not sites:
            print(f"  +{disp:#05x}: no access")
            continue
        print(f"  +{disp:#05x}: {len(sites)} access(es)")
        for at, _text in sites:
            a = analyse(data, at)
            if not a["indexed"]:
                print(f"    {at:#08x} {a['text']:<38} FIXED displacement")
                continue
            b, i, stride = a["bound"], a["init"], a["stride"]
            if b is None:
                say = "indexed, no cmp on that slot in range"
            else:
                mn, tgt, back = a["backjump"]
                n = (b + 1 - i) if i is not None else None
                lo_addr = disp + (i or 0) * stride
                hi_addr = disp + b * stride
                say = (f"indexed by {a['slot']}, init {i} @{a['initat']:#08x}, "
                       f"cmp {b:#04x} @{a['boundat']:#08x} "
                       f"{mn} {tgt:#08x}{' back' if back else ' FORWARD'}"
                       + (f" -> {n} entries"
                          + (f", stride {stride}" if stride != 1 else "")
                          + f" at {lo_addr:#05x}-{hi_addr:#05x}"
                          if n is not None else ""))
            print(f"    {at:#08x} {a['text']:<38} {say}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
