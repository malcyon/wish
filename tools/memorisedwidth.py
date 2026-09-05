#!/usr/bin/env python3
"""How wide the memorised-spell list is in a C64 Gold Box title, from its CAMP.

The character record's list of prepared spells is a run of spell ids the
engine walks with a count-down loop, and the *count* is an immediate operand
in the title's own `CAMP` overlay -- so the width can be read off the player's
disks with no emulator and no specimen, which matters because no C64 party on
this machine has ever had more than sixteen spells memorised.

    tools/memorisedwidth.py                       all three measured titles
    tools/memorisedwidth.py secret-of-the-silver-blades --sites
    tools/memorisedwidth.py champions-of-krynn --disks DIR

The shape it looks for, once per title:

    LDX #$50  /  LDA <record>+0x020,X          Pool of Radiance
    LDY #$44  /  LDA <record>+0x020,Y          Curse of the Azure Bonds
    LDX #$49  /  CMP <record>+0x01B,X          Secret of the Silver Blades

`<record>` is the staging page the overlay reads a character through --
`$6B00` in Pool of Radiance, `$7C00` in every title after it -- so the
*offset* of the list falls out of the low byte and the *width* out of the
immediate, `count + 1` slots because the loop counts down through zero.
Written for `#268 (A character with more than sixteen memorised spells loses
the rest, because the layout gives the list sixteen bytes and the game gives
it eighty-one)`.

Nothing here writes, and nothing it prints is committed: the overlays stay on
the player's own disks.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.games import GAMES  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools.coldread import GEN_BASE, overlay, staging  # noqa: E402

#: The titles whose list this has been read for, in release order.
MEASURED = ("pool-of-radiance", "curse-of-the-azure-bonds",
            "secret-of-the-silver-blades")

#: Absolute-indexed opcodes that touch the list, and which register indexes.
INDEXED = {0xBD: ("LDA", "X"), 0xB9: ("LDA", "Y"),
           0x9D: ("STA", "X"), 0x99: ("STA", "Y"),
           0xDD: ("CMP", "X"), 0xD9: ("CMP", "Y"),
           0xFE: ("INC", "X"), 0xDE: ("DEC", "X")}

#: `LDX #` and `LDY #`, the two instructions that start such a loop.
IMMEDIATE = {"X": 0xA2, "Y": 0xA0}

#: How far back from an indexed access to look for the immediate that seeded
#: its index. Sixteen bytes covers every site measured; a site that continues
#: a loop a previous site started has none, which is why the answer is the
#: *set* of immediates found rather than one per site.
LOOKBACK = 16


def by_key(key: str):
    for g in GAMES:
        if g.key == key:
            return g
    raise SystemExit(f"No such game: {key}")


def accesses(camp: bytes, page: int, base: int = GEN_BASE
             ) -> dict[int, list[tuple[int, str, str, int | None]]]:
    """Every indexed access to `page`, grouped by the offset it names.

    One entry per site: `(address, mnemonic, register, immediate or None)`.
    """
    out: dict[int, list[tuple[int, str, str, int | None]]] = (
        collections.defaultdict(list))
    for i in range(len(camp) - 2):
        if camp[i] not in INDEXED or camp[i + 2] != page:
            continue
        mnemonic, reg = INDEXED[camp[i]]
        want = IMMEDIATE[reg]
        seed = None
        window = camp[max(0, i - LOOKBACK):i]
        for j in range(len(window) - 2, -1, -1):
            if window[j] == want:
                seed = window[j + 1]
                break
        out[camp[i + 1]].append((i + base, mnemonic, reg, seed))
    return out


def measure(key: str, root: str | None, show_sites: bool) -> None:
    game = by_key(key)
    camp = overlay(game, b"CAMP", root)
    page = staging(game) >> 8
    found = accesses(camp, page)
    if not found:
        print(f"{game.title}: CAMP touches no ${page:02X}xx address at all")
        return

    # The list is the offset with the most sites: the record's other fields
    # are read singly and this one is walked six ways.
    offset, sites = max(found.items(), key=lambda kv: len(kv[1]))
    seeds = sorted({s for _a, _m, _r, s in sites if s is not None})
    print(f"{game.title}")
    print(f"  staging page  ${page:02X}00, so the list is record offset "
          f"0x{offset:03X} (${page:02X}{offset:02X})")
    print(f"  sites         {len(sites)} in CAMP, "
          f"{len(seeds)} distinct count-down immediate(s): "
          + ", ".join(f"#${s:02X}" for s in seeds))
    if len(seeds) == 1:
        width = seeds[0] + 1
        print(f"  width         {width} bytes, 0x{offset:03X}-"
              f"0x{offset + seeds[0]:03X}")
    else:
        print("  width         NOT SETTLED -- the sites disagree, so read "
              "them by hand")
    if show_sites:
        for address, mnemonic, reg, seed in sorted(sites):
            imm = f"#${seed:02X}" if seed is not None else "(continues a loop)"
            print(f"    ${address:04X}  {mnemonic} ${page:02X}{offset:02X},"
                  f"{reg}   {imm}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("game", nargs="*", default=list(MEASURED),
                    help="game keys; default is the three measured titles")
    ap.add_argument("--disks", help="where that title's D64 sides are")
    ap.add_argument("--sites", action="store_true",
                    help="list every access site, not just the count")
    args = ap.parse_args(argv)
    for key in args.game:
        root = args.disks
        if root is None:
            where = gamedisks.find(key)
            root = str(where) if where else None
        measure(key, root, args.sites)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
