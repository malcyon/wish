#!/usr/bin/env python3
"""A 16-bit listing of any window of a DOS Gold Box image, by file offset.

`tools/dualclassdos.py code` disassembles the one site it went looking for.
This is the general form, for the sites you find by other means -- a string
you grepped for, a displacement `tools/dosfieldrefs.py` counted, an address a
DOSBox-X breakpoint reported -- and it exists because reading a routine out of
`GAME.OVR` was otherwise a fresh throwaway script every time.

    tools/dosdis16.py --game SECRET --file GAME.OVR --at 0x1d94a --window 120
    tools/dosdis16.py --path /some/GAME.OVR --at 0x3bd7b --before 40
    tools/dosdis16.py --game SECRET --strings train

**An overlay is a byte stream with no entry point to walk from**, so the
alignment is chosen rather than known: the listing backs up until a decode
puts an instruction boundary on the requested offset, exactly as
`tools/dualclassdos.py` does, and every line printed is the true decode of
those bytes from the chosen start.  A listing that starts mid-instruction is
the one failure mode this cannot detect on its own; corroborate a finding with
a second window at a different `--before`.

Offsets are **file** offsets, not segment:offset.  A Borland `FBOV` overlay is
loaded whole, so a file offset differs from the runtime address by whatever
paragraph the loader chose, which is why `--at` takes what a grep gives you.

The player's archives are read only, found the way `tools/dosbox.py` finds
them.  Nothing here writes anything.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from tools import dosbox  # noqa: E402


def listing(image: bytes, at: int, before: int, window: int) -> list[str]:
    """Lines of 16-bit disassembly with an instruction boundary on `at`."""
    try:
        import capstone
    except ImportError:                                 # pragma: no cover
        return ["  (capstone is not installed, so no listing)"]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    start = None
    for back in range(0, max(before, 1) + 1):
        candidate = at - back
        if candidate < 0:
            break
        if any(i.address == at
               for i in md.disasm(image[candidate:at + 8], candidate)):
            start = candidate
    if start is None:
        return [f"  (no alignment within {before} bytes lands on {at:#x})"]
    out = []
    for ins in md.disasm(image[start:at + window], start):
        mark = "   <<<" if ins.address == at else ""
        out.append(f"  {ins.address:06X}  {ins.bytes.hex():<14} "
                   f"{ins.mnemonic} {ins.op_str}{mark}")
    return out


def find_file(game: str, name: str) -> pathlib.Path:
    return dosbox.find_game(game) / name


def strings_in(image: bytes, pattern: str) -> list[tuple[int, str]]:
    """`(offset, text)` for every printable run matching `pattern`."""
    out = []
    for m in re.finditer(rb"[ -~]{4,}", image):
        text = m.group().decode("ascii")
        if re.search(pattern, text, re.I):
            out.append((m.start(), text))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default="SECRET", help="game directory stem")
    ap.add_argument("--file", default="GAME.OVR", help="file inside it")
    ap.add_argument("--path", default=None, help="an explicit path instead")
    ap.add_argument("--at", type=lambda s: int(s, 0), default=None,
                    help="file offset to disassemble around")
    ap.add_argument("--before", type=int, default=32,
                    help="how far back to search for an alignment")
    ap.add_argument("--window", type=int, default=96,
                    help="bytes of listing past the offset")
    ap.add_argument("--strings", default=None,
                    help="instead, list printable runs matching this regex")
    args = ap.parse_args(argv)

    try:
        path = (pathlib.Path(args.path) if args.path
                else find_file(args.game, args.file))
    except FileNotFoundError as exc:
        print(exc)
        return 0
    if not path.is_file():
        print(f"no such file: {path}")
        return 1
    image = path.read_bytes()
    print(f"=== {path.name}, {len(image)} bytes")
    if args.strings is not None:
        for off, text in strings_in(image, args.strings):
            print(f"  {off:06X}  {text}")
        return 0
    if args.at is None:
        ap.error("one of --at or --strings is required")
    for line in listing(image, args.at, args.before, args.window):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
