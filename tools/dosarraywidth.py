#!/usr/bin/env python3
"""How wide an array inside a DOS character record is, from the engine's loop.

    tools/dosarraywidth.py spells_memorised
    tools/dosarraywidth.py spells_memorised --title curse-of-the-azure-bonds
    tools/dosarraywidth.py --displacement 0x17 --overlay /path/to/GAME.OVR
    tools/dosarraywidth.py spellbook --sites

A DOS Gold Box character record is reached through a far pointer, so a
compiler emits `es:[di+<offset>]` for every field and a loop over an array
inside the record is a byte counter compared against the array's **last
index**, then `add di, ax` and the access.  Both halves are findable without
an emulator: scan the overlay for `es`-prefixed accesses at the displacement,
disassemble each, and look back for the `cmp byte [bp-n], imm` that guards it.
The immediate is `width - 1`.

Written for `#508 (A converted magic-user loses memorised spells on the way to
DOS, because our table says a title has fewer slots than the engine gives it)`,
where `goldbox/dos_port.py` gave Pool of Radiance's memorised-spell list 16
bytes at `0x01C` and the engine indexes 21 from `0x017`.  The five bytes in
front had been named `gap_017`, and since the array fills from its **end**, no
specimen on the machine contradicted the narrow reading.

**What this is evidence of, and what it is not.**  The same three limits
`tools/dosfieldrefs.py` states apply, and the third is the one that bites: a
linear scan cannot tell an instruction from data, so a match may fall in a
string table or across the tail of one instruction and the head of the next.
Capstone decoding the four bytes filters most of that and does not prove it.

**So run it against the titles it is not about.**  The same routines exist in
all four DOS engines of the family, so a reading is only believable when the
three titles whose widths are already measured come out unchanged --
`--family` does exactly that and is the honest way to use this.

Reads the player's own archives through `tools/dosbox.find_game` and writes
nothing.  Prints addresses, immediates and short instruction windows; the
game's bytes stay in the player's own directory.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

import capstone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos_port  # noqa: E402
from tools import dosbox  # noqa: E402

#: The `find_game` stem for each title whose DOS overlays are on this machine,
#: in release order.  Pools of Darkness installs under `DARKNESS`.
STEMS = {
    "pool-of-radiance": "POOLRAD",
    "curse-of-the-azure-bonds": "CURSE",
    "secret-of-the-silver-blades": "SECRET",
    "pools-of-darkness": "DARKNESS",
}

#: How far back from an access to look for the compare that guards its loop.
#: 90 bytes covers every site measured; a site inside a loop body whose guard
#: is further up has none, which is why the answer is the *set* of immediates
#: found across all the sites rather than one per site.
LOOKBACK = 90

#: `cmp byte [bp+d], imm` and `cmp byte [bx+d], imm` -- a Turbo Pascal `for`
#: over a byte index keeps the index in a stack slot, so this is the shape.
GUARDS = ((rb"\x80\x7e(.)(.)", "bp"), (rb"\x80\x7f(.)(.)", "bx"))


def find_overlay(title: str) -> pathlib.Path:
    """`GAME.OVR` for a title, out of the player's own archives.

    `tools/dosbox.find_game` keys on `START.EXE`, which **Pools of Darkness
    does not have** -- its launcher is `STARTUP.EXE` -- so that title falls
    back to a search for a directory named after the stem holding a
    `GAME.OVR`.
    """
    try:
        stem = STEMS[title]
    except KeyError:
        raise SystemExit(
            f"no DOS overlay stem known for {title!r}; "
            f"{', '.join(sorted(STEMS))} are the titles this reads") from None
    try:
        return dosbox.find_game(stem) / "GAME.OVR"
    except FileNotFoundError:
        for found in sorted(dosbox.ARCHIVES.rglob(f"{stem}/GAME.OVR")):
            return found
        raise


def accesses(data: bytes, displacement: int) -> list[tuple[int, str]]:
    """Every `es:`-prefixed byte access at `displacement`, disassembled.

    Only `mod=01` forms -- an 8-bit displacement -- which is what a field
    inside the first 128 bytes of a record compiles to.
    """
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    want = f"+ {displacement:#x}]"
    out: list[tuple[int, str]] = []
    for m in re.finditer(rb"\x26", data):
        at = m.start()
        for ins in md.disasm(data[at:at + 8], at):
            text = f"{ins.mnemonic} {ins.op_str}"
            if "es:" in ins.op_str and want in ins.op_str:
                out.append((at, text))
            break
    return out


def guards(data: bytes, at: int) -> list[tuple[int, str, int]]:
    """The `cmp byte [bp-n], imm` sites in the `LOOKBACK` bytes before `at`."""
    window = data[max(0, at - LOOKBACK):at]
    base = max(0, at - LOOKBACK)
    found: list[tuple[int, str, int]] = []
    for pattern, reg in GUARDS:
        for m in re.finditer(pattern, window):
            disp = m.group(1)[0]
            imm = m.group(2)[0]
            signed = disp - 256 if disp > 127 else disp
            found.append((base + m.start(), f"{reg}{signed:+d}", imm))
    return sorted(found)


def measure(data: bytes, displacement: int, show_sites: bool = False
            ) -> collections.Counter:
    """Print every access at `displacement` and tally the guard immediates."""
    tally: collections.Counter = collections.Counter()
    for at, text in accesses(data, displacement):
        near = guards(data, at)
        for _where, _reg, imm in near:
            tally[imm] += 1
        if show_sites:
            said = "; ".join(f"{w:#08x} cmp byte [{r}], {i:#04x}"
                             for w, r, i in near) or "no guard in range"
            print(f"  {at:#08x} {text:34} {said}")
    return tally


def report(title: str, field: str | None, displacement: int,
           overlay: pathlib.Path, show_sites: bool) -> int | None:
    """Print one title's answer and hand back the width it implies."""
    data = overlay.read_bytes()
    print(f"{title}  ({overlay.name}, {len(data)} bytes)")
    if field is not None:
        f = dos_port.FIELDS_BY_NAME_FOR[title][field]
        print(f"  our table   {field} @{f.offset:#05x}, {f.size} bytes")
    print(f"  scanning    es:[reg + {displacement:#04x}]")
    tally = measure(data, displacement, show_sites)
    hits = len(accesses(data, displacement))
    # `cmp byte [bp-n], 0` is the commonest instruction in the family and is
    # almost never a loop bound -- it is the "is this entry empty" test inside
    # the body.  Dropping it is the one piece of judgement here, and the whole
    # tally is printed so a reader can disagree with it.
    ranked = [(v, k) for k, v in tally.items() if k]
    if not hits:
        print("  no access at that displacement -- which is evidence and not "
              "proof: a big array is often walked by adding the offset into "
              "a pointer first, and then no instruction carries it")
        return None
    if not ranked:
        print(f"  {hits} access(es), no non-zero loop guard in range -- "
              f"nothing to say")
        return None
    count, top = max(ranked)
    others = ", ".join(f"{k:#04x} x{v}" for k, v in sorted(tally.items())
                       if k != top)
    print(f"  {hits} access(es); guard immediates: {top:#04x} x{count}"
          + (f", {others}" if others else ""))
    print(f"  width       {top + 1} bytes, "
          f"{displacement:#05x}-{displacement + top:#05x}")
    return top + 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("field", nargs="?",
                    help="a field name in goldbox/dos_layout.py, whose "
                         "offset is what gets scanned")
    ap.add_argument("--title", default="pool-of-radiance",
                    help="which title's overlay to read (default: %(default)s)")
    ap.add_argument("--displacement", type=lambda s: int(s, 0),
                    help="scan this record offset instead of a field's")
    ap.add_argument("--overlay", type=pathlib.Path,
                    help="a GAME.OVR to read instead of the archives'")
    ap.add_argument("--family", action="store_true",
                    help="every title that has the field, so the three whose "
                         "widths are already measured act as controls")
    ap.add_argument("--sites", action="store_true",
                    help="print every access and its guard")
    args = ap.parse_args(argv)

    if args.field is None and args.displacement is None:
        ap.error("name a field or pass --displacement")

    titles = list(STEMS) if args.family else [args.title]
    for n, title in enumerate(titles):
        if n:
            print()
        table = dos_port.FIELDS_BY_NAME_FOR.get(title, {})
        if args.displacement is not None:
            at = args.displacement
        elif args.field in table:
            at = table[args.field].offset
        else:
            print(f"{title}  -- no {args.field!r} in this title's table")
            continue
        try:
            overlay = args.overlay or find_overlay(title)
        except FileNotFoundError as exc:
            print(f"{title}  -- {exc}")
            continue
        report(title, args.field if args.field in table else None,
               at, overlay, args.sites)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
