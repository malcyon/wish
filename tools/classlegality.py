#!/usr/bin/env python3
"""Which classes each race may take at character creation, read off the game.

`goldbox/levels.py` carries how *far* a race may take a class -- the racial
limit table -- and nothing anywhere carries whether the creation menu offers
the combination in the first place.  The two are different tables and they
disagree: Pool of Radiance's racial row gives a dwarf a cleric limit of 8,
and no dwarf is ever offered CLERIC.

That gap is what `#510 (Can a Pool of Radiance character memorise more than
the 21 spells its DOS record allots?)` turned on, because only a race that
can hold cleric *and* magic-user levels at once can approach the DOS
record's 21-entry memorised list.  So this reads the legality table out of
both ports:

* **C64 `GEN`** keeps one byte per class code -- a bitmask of the races that
  may take it, bit `race - 1` -- and the menu builder walks all seventeen
  codes against it.  Both addresses come out of that builder's own operands
  (`LDA <race bits>,Y` / `AND <legality>,X`), so nothing here is a constant
  fitted by hand.
* **DOS `START.EXE`** keeps the other half of the same matrix: seven counted
  lists of class codes, one per race, in race order.  They are found by
  content -- a length byte and that many strictly increasing codes the class
  name table names -- and the seven that sit together are the table.

Run it with no arguments to read whichever ports are on this machine:

    tools/classlegality.py
    tools/classlegality.py --gen path/to/GEN.bin --exe .../START.EXE

Reads only.  With neither port present it prints nothing and exits 0, the way
the tests skip.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
# The repository root and nothing else -- `tools/dosraces.py` has why putting
# `tools/` itself on the path breaks a later import of the `wish` package.
sys.path.insert(0, str(ROOT))

from goldbox.d64 import D64, load_payload  # noqa: E402
from tools import dosbox, gamedisks  # noqa: E402

#: `GEN` runs here whatever its PRG header says (`docs/135-levelling.md`).
GEN_BASE = 0x0800

#: The class codes, in the order every Gold Box front end lists them.  Pool of
#: Radiance implements neither the druid, the paladin, the ranger nor the monk,
#: so four of these name a row the legality table leaves empty.
CLASS_NAMES = (
    "cleric", "druid", "fighter", "paladin", "ranger", "magic-user", "thief",
    "monk", "cleric/fighter", "cleric/fighter/magic-user", "cleric/ranger",
    "cleric/magic-user", "cleric/thief", "fighter/magic-user", "fighter/thief",
    "fighter/magic-user/thief", "magic-user/thief")

#: Race codes are 1-based in the record at `0x072` and both tables are laid out
#: in this order.
RACE_NAMES = ("dwarf", "elf", "gnome", "half-elf", "halfling", "half-orc",
              "human")


# --- the C64 half ------------------------------------------------------------

def find_gen() -> bytes | None:
    """`GEN`'s payload off the player's own Pool of Radiance disks, or None."""
    disks = gamedisks.find("pool-of-radiance")
    if not disks:
        return None
    for path in sorted(pathlib.Path(disks).glob("*.[dD]64")):
        try:
            image = D64.open(path)
            if image.find("GEN") is None:
                continue
            return load_payload(image, "GEN")
        except Exception:                      # a save disk, a bad image
            continue
    return None


def c64_tables(gen: bytes, base: int = GEN_BASE) -> tuple[int, int, int]:
    """`(race_bits, legality, codes)` addresses out of the menu builder.

    The builder is `LDA <race bits>,Y` (`$B9`) then `AND <legality>,X`
    (`$3D`) then `BEQ` -- take the race's bit, test it against the class
    code's own mask of races, and skip the code when it is clear.  Nothing
    else in `GEN` puts those two instructions together.  `codes` is how many
    class codes the loop walks, from the `CMP #imm` that ends it.
    """
    hits = []
    for i in range(len(gen) - 7):
        if gen[i] == 0xB9 and gen[i + 3] == 0x3D and gen[i + 6] == 0xF0:
            race_bits = gen[i + 1] | gen[i + 2] << 8
            legality = gen[i + 4] | gen[i + 5] << 8
            hits.append((race_bits, legality))
    if len(hits) != 1:
        raise LookupError(f"{len(hits)} candidate menu builders, wanted one")
    race_bits, legality = hits[0]
    # The loop's bound: `INC $B0 / LDA $B0 / CMP #imm / BCC`, within 0x40
    # bytes of the test.  Read it rather than assume seventeen.
    codes = 0
    start = legality - base
    for i in range(start, min(start + 0x60, len(gen) - 3)):
        if gen[i] == 0xC9 and gen[i + 1] and gen[i + 2] == 0x90:
            codes = gen[i + 1]
            break
    return race_bits, legality, codes


def c64_legality(gen: bytes, base: int = GEN_BASE):
    """`(races, table)` -- the race bit per race, and the mask per class code."""
    race_bits, legality, codes = c64_tables(gen, base)
    codes = codes or len(CLASS_NAMES)
    bits = gen[race_bits - base + 1:race_bits - base + 1 + len(RACE_NAMES)]
    table = gen[legality - base:legality - base + codes]
    return (race_bits, legality, bytes(bits), bytes(table))


# --- the DOS half ------------------------------------------------------------

def find_start_exe() -> bytes | None:
    """DOS Pool of Radiance's `START.EXE` out of the player's archives."""
    if not dosbox.ARCHIVES.is_dir():
        return None
    for collection in sorted(dosbox.ARCHIVES.iterdir()):
        games = collection / "games"
        if not games.is_dir():
            continue
        exe = games / "POOLRAD" / "GAME" / "POOLRAD" / "START.EXE"
        if exe.is_file():
            return exe.read_bytes()
    return None


#: A race's menu always offers the fighter, in every Gold Box title and in
#: every edition of the rules under them.  It is what separates the seven real
#: lists from the short increasing runs any binary is full of.
FIGHTER = 2

#: How far apart two of the seven lists sit.  Measured: the widest gap in Pool
#: of Radiance's is seven bytes, and the seven span 0x49.
DOS_GAP = 8
DOS_SPAN = 0x80


def dos_lists(blob: bytes, want: int = len(RACE_NAMES)):
    """The seven counted class-code lists, in race order, and where they are.

    A candidate is a length byte of three upwards, that many strictly
    increasing codes the class table names, and the fighter among them.  The
    seven real ones sit within a few bytes of each other, so a run of `want`
    candidates end to end is the table; the tool prints the offset it took so
    a reader can check it against the file rather than trust the heuristic.
    """
    limit = len(CLASS_NAMES)
    found = []
    for i in range(len(blob) - 3):
        count = blob[i]
        if not 3 <= count <= limit:
            continue
        run = blob[i + 1:i + 1 + count]
        if len(run) < count or any(c >= limit for c in run):
            continue
        if any(run[k] >= run[k + 1] for k in range(count - 1)):
            continue
        if FIGHTER not in run:
            continue
        found.append((i, tuple(run)))
    for start in range(len(found)):
        picked = [found[start]]
        for offset, run in found[start + 1:]:
            end = picked[-1][0] + len(picked[-1][1]) + 1
            if offset < end:
                continue                      # inside the list before it
            if offset - end > DOS_GAP or offset - picked[0][0] > DOS_SPAN:
                break
            picked.append((offset, run))
            if len(picked) == want:
                return picked
    return []


# --- reporting ---------------------------------------------------------------

def names(codes) -> str:
    return ", ".join(CLASS_NAMES[c] for c in codes)


def report(gen: bytes | None, exe: bytes | None) -> dict:
    """Print both ports' tables and hand back what each said, per race."""
    out: dict[str, dict[str, tuple[int, ...]]] = {}
    if gen is not None:
        race_bits, legality, bits, table = c64_legality(gen)
        print(f"C64 GEN: race bits at ${race_bits:04X}, legality at "
              f"${legality:04X}, {len(table)} class codes")
        rows = {}
        for i, race in enumerate(RACE_NAMES):
            bit = bits[i] if i < len(bits) else 0
            rows[race] = tuple(c for c, mask in enumerate(table) if mask & bit)
        for race, codes in rows.items():
            print(f"  {race:9s} {len(codes):2d}  {names(codes)}")
        out["c64"] = rows
    if exe is not None:
        lists = dos_lists(exe)
        if lists:
            print(f"DOS START.EXE: class lists at 0x{lists[0][0]:06x}")
            rows = {}
            for (offset, run), race in zip(lists, RACE_NAMES):
                rows[race] = run
                print(f"  {race:9s} {len(run):2d}  {names(run)}")
            out["dos"] = rows
    if "c64" in out and "dos" in out:
        same = all(out["c64"][r] == out["dos"][r] for r in RACE_NAMES)
        print("the two ports agree" if same else
              "THE TWO PORTS DISAGREE -- read the rows above")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gen", help="a raw C64 GEN payload, base $0800")
    ap.add_argument("--exe", help="a DOS START.EXE")
    args = ap.parse_args(argv)
    gen = pathlib.Path(args.gen).read_bytes() if args.gen else find_gen()
    exe = pathlib.Path(args.exe).read_bytes() if args.exe else find_start_exe()
    if gen is None and exe is None:
        return 0
    report(gen, exe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
