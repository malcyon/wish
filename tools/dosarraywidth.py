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

**This holds for a 0-based loop, and this compiler also emits 1-based
ones**, where the immediate is the width itself rather than `width - 1` --
`#516 (Generate boundary characters and check every writer's field widths,
since no real save reaches a limit and the corpus cannot find a wrong one)`'s
slice 3 found the record-array fill loops (`spells_castable_cleric` among
them) generated as `for i := 1 to N`, which puts `offset - 1` in the
instruction's displacement and `N` in the guard immediate.  Scanning at the
field's own offset finds nothing for one of these, because the instruction
carries the offset one lower: pass `--displacement <offset-1>` to reach it.
`tools/dosrecordloops.py` reads this shape directly, by tying the guard to
the stack slot actually added into `di` and reading its initialiser, rather
than assuming 0-based.

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

**`spells_castable_cleric`, `attack_forms` and `field_83_87` are settled** --
`#516` slice 3 read the guarded loops behind all three with
`tools/dosrecordloops.py` and confirmed the declared widths in every title
that has them.  `--family`'s own disagreeing numbers for two of them were
defects in this tool's 0-based/`imm`-only reading (see above and the
`LOOKBACK` note below), not real widths; do not re-run the family scan on
these three expecting a different answer.

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
#:
#: The window is truncated at a `retf`/`ret` between the guard and the site,
#: found by `_window_start` below -- a flat 90-byte window routinely crosses
#: into the *previous* subroutine, which is what produced Pool of Radiance's
#: false "8" for `spells_castable_cleric` in `#516` slice 3: the site at
#: `0x02ac52` is in the function that begins `0x02ac36`, and the compare
#: that used to win the tally, `cmp byte [bp-1], 7` at `0x02ac08`, belongs to
#: the one before it, which ends `retf 4` at `0x02ac33`.
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


def _window_start(data: bytes, at: int) -> int:
    """Where the `LOOKBACK` window should actually begin: the earliest byte
    in `[at - LOOKBACK, at)` whose decode, run forward, lands an instruction
    boundary exactly on `at` -- the same synchronisation trick
    `tools/dosrecordloops.py` uses -- truncated to just past the last
    `retf`/`ret` that stream contains, so the guard scan never crosses into
    a different subroutine.  Falls back to the flat window when no alignment
    lands on `at` at all.
    """
    lo = max(0, at - LOOKBACK)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    for start in range(lo, at + 1):
        ins = list(md.disasm(data[start:at], start))
        if ins and ins[-1].address + ins[-1].size == at:
            for i in ins:
                if i.mnemonic in ("retf", "ret", "retn"):
                    lo = i.address + i.size
            return lo
    return lo


def guards(data: bytes, at: int) -> list[tuple[int, str, int]]:
    """The `cmp byte [bp-n], imm` sites in the `LOOKBACK` bytes before `at`,
    not crossing a `retf`/`ret` into a different subroutine."""
    base = _window_start(data, at)
    window = data[base:at]
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


def _pick(tally: collections.Counter) -> tuple[int, int] | None:
    """The `(count, immediate)` `width` and `report` agree the loop bound is:
    the most common non-zero guard immediate across every site, or `None`
    when there is nothing to say.

    `cmp byte [bp-n], 0` is the commonest instruction in the family and is
    almost never a loop bound -- it is the "is this entry empty" test inside
    the body.  Dropping it is the one piece of judgement here, and it lives
    in exactly this one place so `width` and `report` cannot drift apart
    on it.
    """
    ranked = [(v, k) for k, v in tally.items() if k]
    if not ranked:
        return None
    return max(ranked)


def width(data: bytes, displacement: int) -> int | None:
    """The width the engine's own loop implies for an array at
    `displacement`, or `None` when there is nothing to say.

    Lifted out of :func:`report` for `#516 (Generate boundary characters and
    check every writer's field widths, since no real save reaches a limit
    and the corpus cannot find a wrong one)`'s `tests/test_boundary.py`,
    which asserts against this rather than parsing what `report` prints.
    `report` calls this for its own top-line answer, through `_pick`, so the
    selection rule lives once.
    """
    picked = _pick(measure(data, displacement))
    return None if picked is None else picked[1] + 1


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
    # The whole tally is printed so a reader can disagree with the choice
    # `_pick` makes above.
    picked = _pick(tally)
    if not hits:
        print("  no access at that displacement -- which is evidence and not "
              "proof: a big array is often walked by adding the offset into "
              "a pointer first, and then no instruction carries it")
        return None
    if picked is None:
        print(f"  {hits} access(es), no non-zero loop guard in range -- "
              f"nothing to say")
        return None
    count, top = picked
    others = ", ".join(f"{k:#04x} x{v}" for k, v in sorted(tally.items())
                       if k != top)
    print(f"  {hits} access(es); guard immediates: {top:#04x} x{count}"
          + (f", {others}" if others else ""))
    print(f"  width       {top + 1} bytes, "
          f"{displacement:#05x}-{displacement + top:#05x}")
    result = width(data, displacement)
    assert result == top + 1, (result, top + 1)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("field", nargs="?",
                    help="a field name in goldbox/dos_port.py, whose "
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
