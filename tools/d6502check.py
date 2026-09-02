#!/usr/bin/env python3
"""Check `tools/d6502.py` against capstone, on the table and on real code.

`d6502.py`'s guarantee is that **every instruction it prints is the true
decode of those bytes** -- 151 opcodes decoded, the other 105 printed as
`.byte`. That claim is one hand-typed table away from being false, and a wrong
mnemonic in a listing is exactly the kind of error that gets believed and
written into a document. This is what settles it, and it is worth keeping
because the answer has to be got again every time that table is touched.

Two sweeps, and they fail differently:

* `--table` decodes every byte value with a `$1234` operand and compares
  the mnemonic and the size with capstone's. This catches a typed row: the
  copy of this table that `work/d6502/before.py` holds has `F6 SBC ZPX` where
  the real opcode is `INC`, and the sweep names it.
* `--code` walks whole overlays end to end, advancing by `d6502`'s own size
  (one byte for a `.byte`), which is what a reader actually does. It catches
  a size that is right in isolation and wrong in a stream.

`$00` is skipped by both sweeps by declaration rather than by accident:
capstone gives `BRK` two bytes and `d6502` gives it one, and `docs/148-d6502.md`
records that as a known difference rather than a fault.

    tools/d6502check.py                 both sweeps
    tools/d6502check.py --table

**capstone is not a dependency of `wish` and must not become one** -- it is a
cross-check, so the tool that needs it lives here and the committed suite
builds its own encodings instead.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import d6502  # noqa: E402

from automap.paths import find_disks  # noqa: E402
from goldbox.d64 import load_payload  # noqa: E402

#: capstone gives `BRK` two bytes and `d6502` gives it one.
#: `docs/148-d6502.md` records that as a declared difference rather than a
#: fault, so neither sweep counts it.
BRK = 0x00

#: The two overlays `docs/147-combat-rolls.md` was read out of, and the
#: addresses they run at rather than the ones their PRG headers declare.
OVERLAYS = (("COMBAT", 0x0800), ("LIBRARY", 0x2C48))


def _capstone():
    try:
        import capstone
    except ImportError:
        print("This needs capstone, which wish does not depend on:\n"
              "    .venv/bin/pip install capstone", file=sys.stderr)
        raise SystemExit(2)
    return capstone.Cs(capstone.CS_ARCH_MOS65XX,
                       capstone.CS_MODE_MOS65XX_6502)


def ours(data: bytes, at: int):
    """`(mnemonic, size)` if `d6502` decodes the byte at `at`, else None."""
    op = data[at]
    if op not in d6502.T:
        return None
    mn, mode = d6502.T[op]
    size = d6502.SZ[mode]
    return (mn, size) if len(data) - at >= size else None


def table(cs) -> int:
    """Every byte value, with an operand behind it. Returns the disagreements."""
    bad = 0
    for op in range(256):
        if op == BRK:                   # the declared BRK-size difference
            continue
        buf = bytes([op, 0x34, 0x12])
        found = next(cs.disasm(buf, 0x1000), None)
        theirs = None if found is None else (found.mnemonic.upper(),
                                             found.size)
        mine = ours(buf, 0)
        if (theirs is None) != (mine is None):
            print(f"  ${op:02X}: capstone {theirs}, d6502 {mine} "
                  f"-- one decodes it and the other does not")
            bad += 1
        elif theirs and mine and theirs != mine:
            print(f"  ${op:02X}: capstone {theirs}, d6502 {mine}")
            bad += 1
    print(f"table: {255 - bad} of 255 byte values agree (BRK excepted), "
          f"{bad} disagreement{'' if bad == 1 else 's'}")
    return bad


def code(cs, data: bytes, base: int, label: str) -> int:
    """One overlay end to end, stepping the way a reader steps."""
    compared = bad = 0
    at = 0
    while at < len(data):
        pc = base + at
        found = next(cs.disasm(bytes(data[at:at + 3]), pc), None)
        theirs = None
        if found is not None and found.address == pc:
            theirs = (found.mnemonic.upper(), found.size)
        mine = ours(data, at)
        if data[at] == BRK:             # the declared BRK-size difference
            at += 1
            continue
        compared += 1
        if (theirs is None) != (mine is None):
            print(f"  ${pc:04X}: capstone {theirs}, d6502 {mine} "
                  f"-- one decodes it and the other does not")
            bad += 1
        elif theirs and mine and theirs != mine:
            print(f"  ${pc:04X}: capstone {theirs}, d6502 {mine}")
            bad += 1
        at += mine[1] if mine is not None else 1
    print(f"{label}: {compared - bad} of {compared} instructions agree, "
          f"{bad} disagreement{'' if bad == 1 else 's'}")
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Compare tools/d6502.py with capstone.")
    ap.add_argument("--table", action="store_true",
                    help="only the 256-opcode table")
    ap.add_argument("--code", action="store_true",
                    help="only the real overlays")
    ap.add_argument("--disks", default=os.environ.get("POR_DISKS"),
                    metavar="DIR",
                    help="where the game disks are (default: $POR_DISKS, "
                         "then wherever the program looks)")
    args = ap.parse_args(argv[1:])
    both = not (args.table or args.code)

    cs = _capstone()
    bad = 0
    if both or args.table:
        bad += table(cs)
    if both or args.code:
        root = args.disks or str(find_disks() or "")
        if not root or not os.path.isdir(root):
            print("No game disks, so only the table was checked. Set "
                  "$POR_DISKS or pass --disks.", file=sys.stderr)
            return 2 if bad == 0 else 1
        for name, base in OVERLAYS:
            found = None
            for path in sorted(pathlib.Path(root).glob("POOL*.[dD]64")):
                try:
                    found = load_payload(str(path), name)
                    break
                except Exception:
                    continue
            if found is None:
                print(f"{name}: on no side under {root}")
                continue
            bad += code(cs, found, base, name)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
