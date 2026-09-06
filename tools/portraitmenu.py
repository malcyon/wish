#!/usr/bin/env python3
"""Read the character-creation portrait menu off the game and print it.

`goldbox/portraits.py` carries Pool of Radiance's creation menu -- the
fourteen `HEAD<xx>` ids and twelve `BODY<xx>` ids in menu order, twenty-six
integers -- as `POOL_OF_RADIANCE_MENU`, so a DOS-to-C64 conversion needs no
game disk in reach to give a character his own face.  A number nobody can
re-derive is a number nobody can check, and this is how the stored block is
re-derived:

    tools/portraitmenu.py            # print the menu off whatever is here
    tools/portraitmenu.py --check    # exit 1 if the disks disagree with it

It reads the C64 side (`GEN`, off `$POR_DISKS` or wherever `gamedisks.toml`
says the `POOL*.D64` sides are) and the DOS side (`START.EXE`, in the
*Forgotten Realms: The Archives* game directory `tools/dosbox.py` finds),
whichever of the two is on this machine, through the same run-finder the
conversion uses -- `goldbox.portraits.tables_from_disks` and
`tables_from_dos` -- and prints each as the Python literal the stored block
is written in.  Nothing is copied out of either file but the ids themselves,
which is the whole of what the stored block holds.

`--check` compares both readings against `POOL_OF_RADIANCE_MENU` and says
which side agreed; a disagreement is the escape hatch -- a release whose
menu differs from the one read on 2026-09-06 -- and prints both tables so
the difference can be seen rather than inferred.  `--disks DIR` and `--dos
DIR` point it at a particular copy.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

from goldbox import portraits  # noqa: E402
from tools import gamedisks  # noqa: E402


def _dos_game(given: str | None) -> pathlib.Path | None:
    if given:
        return pathlib.Path(given)
    try:
        import dosbox
        return dosbox.find_game("POOLRAD")
    except (FileNotFoundError, ImportError):
        return None


def _c64_disks(given: str | None) -> pathlib.Path | None:
    if given:
        return pathlib.Path(given)
    return gamedisks.find("pool-of-radiance")


def literal(tables: portraits.PortraitTables) -> str:
    """The table as the block in `goldbox/portraits.py` writes it."""
    def row(name, ids, per_line):
        chunks = [", ".join(f"0x{i:02X}" for i in ids[n:n + per_line])
                  for n in range(0, len(ids), per_line)]
        pad = " " * (len(name) + 2)
        return f"{name}=(" + f",\n{pad}".join(chunks) + "),"
    return "\n".join([row("heads", tables.heads, 7),
                      row("bodies", tables.bodies, 6)])


def readings(disks: pathlib.Path | None, dos_game: pathlib.Path | None
             ) -> list[tuple[str, portraits.PortraitTables | str]]:
    """`(label, tables-or-why-not)` for each side that could be tried."""
    out: list[tuple[str, portraits.PortraitTables | str]] = []
    if disks is not None:
        try:
            out.append((f"C64 {disks}", portraits.tables_from_disks(disks)))
        except portraits.PortraitError as e:
            out.append((f"C64 {disks}", str(e)))
    if dos_game is not None:
        try:
            out.append((f"DOS {dos_game}", portraits.tables_from_dos(dos_game)))
        except portraits.PortraitError as e:
            out.append((f"DOS {dos_game}", str(e)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--disks", help="the folder of C64 POOL*.D64 sides")
    ap.add_argument("--dos", help="the DOS game directory holding START.EXE")
    ap.add_argument("--check", action="store_true",
                    help="compare each reading with the stored menu and "
                         "exit 1 on any disagreement")
    args = ap.parse_args(argv)

    found = readings(_c64_disks(args.disks), _dos_game(args.dos))
    if not found:
        print("No Pool of Radiance disks or DOS game directory found here; "
              "set POR_DISKS or FR_ARCHIVES, or pass --disks / --dos.")
        return 2

    stored = portraits.stored_tables(portraits.POOL_OF_RADIANCE_KEY)
    status = 0
    for label, got in found:
        print(f"== {label}")
        if isinstance(got, str):
            print(f"   not read: {got}")
            if args.check:
                status = 1
            continue
        print(f"   {got.source}")
        print(literal(got))
        if args.check:
            if got.agrees_with(stored):
                print("   agrees with the stored menu")
            else:
                status = 1
                print("   DISAGREES with the stored menu, which is:")
                print(literal(stored))
    return status


if __name__ == "__main__":
    sys.exit(main())
