#!/usr/bin/env python3
"""Disassemble a window around a file offset in a 16-bit DOS overlay.

#516 (Generate boundary characters and check every writer's field widths, since no real save reaches a limit and the corpus cannot find a wrong one).
Back-synchronises: tries every start in [at-back, at) and keeps the earliest
one whose decode lands an instruction boundary exactly on `at`, which is how a
linear 16-bit scan finds the real stream without a symbol table.  `capstone`
does the decoding.

    tools/dos/dosovrwindow.py OVERLAY 1A2B[,3C4D...] [BACK [FWD]]

`OVERLAY` is a file, or a title whose overlay `tools/dos/dosarraywidth.py` can
find.  The offsets are hexadecimal and comma-separated; `BACK` (default 140)
and `FWD` (default 60) are decimal byte counts either side.  The line at the
requested offset is marked with `>>`.  Read only.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import capstone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from tools.dos import dosarraywidth  # noqa: E402

MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)


def window(data: bytes, at: int, back: int = 140, fwd: int = 60):
    """Instructions covering [at-back, at+fwd], synchronised on `at`."""
    best = None
    for start in range(max(0, at - back), at + 1):
        ins = list(MD.disasm(data[start:at + fwd], start))
        if any(i.address == at for i in ins):
            best = ins
            break
    return best or list(MD.disasm(data[at:at + fwd], at))


def show(data: bytes, at: int, back: int = 140, fwd: int = 60, label: str = ""):
    print(f"--- {label}{at:#08x} " + "-" * 40)
    for i in window(data, at, back, fwd):
        mark = ">>" if i.address == at else "  "
        raw = i.bytes.hex()
        print(f"{mark} {i.address:#08x}  {raw:<16} {i.mnemonic} {i.op_str}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("overlay", help="an overlay file, or a title to look one up for")
    p.add_argument("offsets", help="hexadecimal offsets, comma-separated")
    p.add_argument("back", nargs="?", type=int, default=140)
    p.add_argument("fwd", nargs="?", type=int, default=60)
    a = p.parse_args(argv)

    overlay = pathlib.Path(a.overlay)
    if not overlay.exists():
        overlay = dosarraywidth.find_overlay(a.overlay)
    data = overlay.read_bytes()
    for spec in a.offsets.split(","):
        show(data, int(spec, 16), a.back, a.fwd)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
