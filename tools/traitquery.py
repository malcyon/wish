#!/usr/bin/env python3
"""Which effect ids the engine asks a character's **trait slots** about.

`#252 (Does a C64 trait slot apply an item-granted effect id, or only the ones
its own READY routine wrote?)` is the question this answers. The ten trait
slots at record `0x0AD` are one of *two* backing stores the C64 engine keeps
for "does this character have effect N?"; the other is the 64-entry active
effect array in the save header. Two routines sit over them:

* the **array-only** predicate -- `LIBRARY $3FE4` in Pool of Radiance, with
  `$3FE1` a `LDX $6DB4` wrapper that supplies the current character. A caller
  that goes here never sees a trait slot.
* the **array-then-traits** predicate at `$4027`, three instructions long:
  `JSR $3FE4 / BCC / RTS` and then `LDX #$09 / LDA $6BAD,X / CMP <wanted>`.
  A caller that goes here treats a trait slot exactly like a running spell.

So the answer to "does a trait slot apply an id put there" is a **census of
which ids reach which predicate**, and this prints the half of it a static
read can see: call sites that name the id with a `LDA #imm`. **The other half
is data.** The combat engine walks twenty per-check id lists under the I/O
area (`SQRPACI01 $072E`, lists at `$DB7A`) and asks `COMBAT $28A4` about every
id on them, and no literal appears anywhere -- 61 is on two of those lists and
this census reports it asked about nowhere. `tools/traitask.py` reads the
lists off the running machine and logs the asks; `docs/171-c64-trait-slots.md`
has both halves.

    tools/traitquery.py pool-of-radiance
    tools/traitquery.py curse-of-the-azure-bonds --sites

Nothing here needs an emulator or a save: it reads the overlays off the
player's own disks through `tools/gamedisks.py`, and nothing it prints is
committed.

## Finding the predicate without knowing where the overlay runs

A PRG header on these disks is a family stamp (`docs/40-memory-map.md`), so the
address of a routine inside `LIBRARY` cannot be read off the file. This locates
it from the file's own absolute operands instead, which carry their targets
wherever the overlay runs:

1. find the trait scan by its bytes -- `A2 09 BD <lo> <hi> CD <e_lo> <e_hi>`,
   where `<lo,hi>` is the record base plus `0x0AD`. That gives the file offset
   `k` of the `LDX #$09`, and `<e_lo,e_hi>` is the scratch byte holding the id
   the caller asked about;
2. the entry is six bytes earlier: `20 <s_lo> <s_hi> 90 01 60`. `<s_lo,s_hi>`
   is the **address** of the array-only predicate;
3. that predicate opens `8D <e_lo> <e_hi> 8E`, storing the id into the same
   scratch. Find *that* byte string in the same file to get its **offset**.

Address minus offset is the overlay's run base, so the entry address falls out
of the file with nothing assumed. The base it derives is printed, and for Pool
of Radiance it comes to `$2C48`, which is what `docs/40-memory-map.md` has for
`LIBRARY` on independent evidence.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import d6502  # noqa: E402
import gamedisks  # noqa: E402
from absrefsweep import files, is_art  # noqa: E402

from goldbox import games, traits  # noqa: E402

#: Where `LINKER` puts an overlay it dispatches to, used only to print a call
#: site's address in the same coordinates `tools/absrefsweep.py` prints.
OVERLAY_BASE = 0x0800

#: The staging record each title reads and writes a character through, and the
#: trait block's offset inside it. `tools/coldread.py` carries the same pair.
STAGING = {"pool-of-radiance": 0x6B00}
STAGING_LATER = 0x7C00
TRAIT_SLOT = 0x0AD

#: How far back from a call site to look for the `LDA #imm` that set the id.
LOOKBACK = 24


def staging(game: games.Game) -> int:
    return STAGING.get(game.key, STAGING_LATER)


class Predicate:
    """One `has this character got effect N?` routine, found in an overlay."""

    def __init__(self, file: str, base: int, entry: int, array: int,
                 scratch: int, trait_scan: int):
        self.file = file
        self.base = base            # where the overlay runs
        self.entry = entry          # array, then the ten trait slots
        self.array = array          # array only -- a trait slot is invisible
        self.scratch = scratch      # where the wanted id is parked
        self.trait_scan = trait_scan


def find_predicate(name: str, body: bytes, record: int) -> Predicate | None:
    """Locate the array-then-traits predicate in one overlay, base and all."""
    block = record + TRAIT_SLOT
    want = bytes((0xA2, 0x09, 0xBD, block & 0xFF, block >> 8, 0xCD))
    k = body.find(want)
    if k < 0 or k < 6:
        return None
    scratch = body[k + 6] | body[k + 7] << 8
    head = body[k - 6:k]
    if head[0] != 0x20 or head[3:] != bytes((0x90, 0x01, 0x60)):
        return None
    array = head[1] | head[2] << 8
    opening = bytes((0x8D, scratch & 0xFF, scratch >> 8, 0x8E))
    j = body.find(opening)
    if j < 0:
        return None
    base = array - j
    return Predicate(name, base, base + k - 6, array, scratch, base + k)


def immediate_before(body: bytes, at: int) -> set[int]:
    """Every `LDA #imm` a linear decode reaching `at` ends on, as a set.

    A 6502 has no instruction alignment, so reading backwards is a guess. This
    decodes forward from each of the `LOOKBACK` bytes before the call site and
    keeps only the runs that land **exactly** on it; the last immediate load in
    each is a candidate for the id. One value means every alignment agrees.
    """
    found: set[int] = set()
    for start in range(max(0, at - LOOKBACK), at):
        pc = start
        last: int | None = None
        while pc < at:
            op = body[pc]
            if op not in d6502.T:
                break
            mn, mode = d6502.T[op]
            size = d6502.SZ[mode]
            if mn == "LDA" and mode == d6502.M_IMM:
                last = body[pc + 1]
            elif mn in ("JSR", "JMP", "RTS", "RTI") or mode == d6502.M_REL:
                last = None                       # control left; A is not ours
            pc += size
        if pc == at and last is not None:
            found.add(last)
    return found


def call_sites(root: str, game: games.Game, target: int):
    """`(file, offset, kind, ids)` for every `JSR`/`JMP` to one address."""
    lo, hi = target & 0xFF, target >> 8
    for _disk, name, body in files(root, game):
        if is_art(name):
            continue
        for i in range(len(body) - 2):
            if body[i + 1] != lo or body[i + 2] != hi:
                continue
            if body[i] == 0x20:
                kind = "JSR"
            elif body[i] == 0x4C:
                kind = "JMP"
            else:
                continue
            yield name, i, kind, immediate_before(body, i)


def describe(game: games.Game, code: int) -> str:
    return traits.describe(code, game.key)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("title")
    parser.add_argument("--disks", help="where that title's sides are")
    parser.add_argument("--overlay", default="LIBRARY",
                        help="which file to look for the predicate in")
    parser.add_argument("--sites", action="store_true",
                        help="one row per call site, not one per id")
    args = parser.parse_args(argv)

    game = next((g for g in games.GAMES
                 if g.key == args.title or g.title == args.title), None)
    if game is None:
        raise SystemExit(f"No such title: {args.title}")
    root = args.disks or str(gamedisks.find(game.key) or "")
    if not root or not os.path.isdir(root):
        raise SystemExit(f"No disks for {game.title}; pass --disks.")

    record = staging(game)
    predicate = None
    for _disk, name, body in files(root, game):
        if args.overlay and name != args.overlay:
            continue
        predicate = find_predicate(name, body, record)
        if predicate is not None:
            break
    if predicate is None:
        raise SystemExit(
            f"traitquery.py: no array-then-traits predicate in "
            f"{args.overlay} for {game.title}; try --overlay.")

    print(f"{game.title}: record ${record:04X}, trait block "
          f"${record + TRAIT_SLOT:04X}")
    print(f"  {predicate.file} runs at ${predicate.base:04X} "
          f"(derived, not from the header)")
    print(f"  ${predicate.entry:04X}  array, then the ten trait slots")
    print(f"  ${predicate.array:04X}  array only -- a trait slot is invisible "
          f"here")
    print(f"  ${predicate.trait_scan:04X}  the LDX #$09 scan itself")

    for label, target in (("honours a trait slot", predicate.entry),
                          ("array only", predicate.array),
                          ("array only, current character",
                           predicate.array - 3)):
        sites = list(call_sites(root, game, target))
        print(f"\n  ${target:04X}, {label}: {len(sites)} call sites")
        if not sites:
            continue
        if args.sites:
            for name, off, kind, ids in sorted(sites):
                shown = ", ".join(str(i) for i in sorted(ids)) or "?"
                print(f"    {name:<10} ${OVERLAY_BASE + off:04X}  {kind}  "
                      f"id {shown}")
            continue
        per: dict[str, list[str]] = collections.defaultdict(list)
        for name, off, _kind, ids in sites:
            key = str(sorted(ids)[0]) if len(ids) == 1 else "?"
            per[key].append(f"{name} ${OVERLAY_BASE + off:04X}")
        for key in sorted(per, key=lambda v: (v == "?", int(v) if v != "?"
                                              else 0)):
            if key == "?":
                print(f"    {'?':>4}  {'(the caller supplies it)':<48} "
                      + ", ".join(sorted(per[key])))
                continue
            print(f"    {key:>4}  {describe(game, int(key))[:48]:<48} "
                  + ", ".join(sorted(per[key])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
