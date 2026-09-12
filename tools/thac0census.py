#!/usr/bin/env python3
"""Every stored `thac0_base` on this machine, against the port's own table.

The two ports do not agree about a low-level magic-user or thief, and this is
what established that the disagreement is the game's rather than ours. It reads
each port's THAC0 table out of the player's own files and then sweeps every
character record it can reach, saying for each one whether the stored byte is
what that port's table gives.

    tools/thac0census.py tables      both ports' tables, side by side
    tools/thac0census.py c64         every C64 record, against `GEN $1F1F`
    tools/thac0census.py dos         every DOS record, against `START.EXE`
    tools/thac0census.py dos --title curse-of-the-azure-bonds

**Neither table is hardcoded here.** The C64's comes off whichever `POOL*.D64`
carries `GEN`. The DOS one comes out of `START.EXE`, which is EXEPACK-packed
(`tools/unexepack.py`) and is located in the expanded image by the **class-bit
table** that sits immediately after it -- eight bytes, one a class, in class
number order, `02 20 08 40 80 01 04 10` for Pool of Radiance. That run occurs
exactly once in the image, and anchoring on it keeps this from assuming the
answer it is meant to check. The geometry comes from the engine instead of from
a guess: `GAME.OVR` reaches the table through `mov dx, <stride> / mul dx /
mov di, ax / add di, cx / mov al, [di + <offset>]`, and `--code` prints every
site of that shape with the stride and offset it carries.

The rule both engines implement is the same: clear the byte, walk the class
slots, keep the row that is best. So a record's expected value is the best of
its classes and nothing else -- no strength, no weapon, no clamp.

Nothing here writes anything, and no table it prints is committed.
"""

from __future__ import annotations

import argparse
import glob
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos_codec, levels  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402
from goldbox.savegame import SaveGame0  # noqa: E402
from tools import gamedisks  # noqa: E402

#: `GEN` is resident here whatever its PRG header claims.
GEN_BASE = 0x0800

#: `GEN $1F1F`, four rows of nine, `LDA $1F1F,X` with `X = class * 9 + level`.
POOL_C64_TABLE = 0x1F1F
POOL_C64_STRIDE = 9
#: The C64's rows are in class-bit order, which is not the DOS class numbering.
C64_CLASS_ORDER = ("magic-user", "cleric", "thief", "fighter")

#: The eight DOS class numbers, in the order `class_levels` stores them and the
#: order the DOS THAC0 table's rows are in.  `goldbox.dos.CLASS_LEVEL_SLOTS`
#: names the same eight; this is here so the anchor below can be built without
#: importing the record layout.
DOS_CLASS_ORDER = ("cleric", "druid", "fighter", "paladin", "ranger",
                   "magic-user", "thief", "monk")

#: The class-bit table the DOS build keeps immediately after the THAC0 one.
#: Cleric 2, fighter 8, magic-user 1 and thief 4 are the C64's own class bits,
#: which is what makes this an anchor independent of anything about THAC0.
DOS_CLASS_BITS = bytes((2, 32, 8, 64, 128, 1, 4, 16))

#: How wide a DOS row is, per title -- levels 1..n with entry 0 unused.  Taken
#: from the `mul` in the engine's own loop, which `--code` prints.
DOS_STRIDE = {"pool-of-radiance": 11,
              "curse-of-the-azure-bonds": 13,
              "secret-of-the-silver-blades": 19}

#: `mov dx, imm16 / mul dx / mov di, ax / add di, cx / mov al, [di + imm16]`.
DOS_LOOKUP = re.compile(rb"\xba(..)\xf7\xe2\x8b\xf8\x03\xf9\x8a\x85(..)",
                        re.DOTALL)


def _u16(raw: bytes) -> int:
    return int.from_bytes(raw, "little")


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------
def c64_table(title: str = "pool-of-radiance") -> dict[str, list[int]]:
    """One class name to THAC0 by level, read off the player's own `GEN`.

    Pool of Radiance only: the later titles hold their rows at other addresses
    and in other shapes, and `goldbox/levels.py`'s docstring has them.
    """
    if title != "pool-of-radiance":
        raise SystemExit(f"the C64 side of {title} is not read here; "
                         "goldbox/levels.py names its addresses")
    where = gamedisks.find(title)
    if where is None:
        raise SystemExit("no Pool of Radiance disks; set $POR_DISKS")
    for path in sorted(where.glob("POOL*.[dD]64")):
        disk = D64.open(str(path))
        for entry in disk.directory():
            if entry.name.strip() == b"GEN":
                gen = disk.read_file(entry)[2:]
                out = {}
                for index, name in enumerate(C64_CLASS_ORDER):
                    at = POOL_C64_TABLE - GEN_BASE + index * POOL_C64_STRIDE
                    out[name] = [60 - b
                                 for b in gen[at + 1:at + 1 + POOL_C64_STRIDE]]
                return out
    raise SystemExit(f"no GEN on any POOL disk under {where}")


def dos_image(title: str = "pool-of-radiance") -> bytes:
    """The player's own `START.EXE`, EXEPACK-expanded."""
    from tools import dosbox, unexepack

    stem = {"pool-of-radiance": "POOLRAD",
            "curse-of-the-azure-bonds": "CURSE",
            "secret-of-the-silver-blades": "SECRET"}[title]
    folder = dosbox.find_game(stem)
    image, _ = unexepack.unpack((folder / "START.EXE").read_bytes())
    return image


def dos_table(title: str = "pool-of-radiance",
              image: bytes | None = None) -> dict[str, list[int]]:
    """One class name to THAC0 by level, out of the DOS build's own table.

    Anchored on `DOS_CLASS_BITS`, which sits immediately after it and must
    occur exactly once; the eight rows are the `stride * 8` bytes before.
    """
    image = dos_image(title) if image is None else image
    stride = DOS_STRIDE[title]
    hits = [m.start() for m in re.finditer(re.escape(DOS_CLASS_BITS), image)]
    if len(hits) != 1:
        raise SystemExit(f"{title}: the class-bit anchor occurs {len(hits)} "
                         "times, so it does not locate the table")
    end = hits[0]
    out = {}
    for index, name in enumerate(DOS_CLASS_ORDER):
        at = end - stride * 8 + index * stride
        out[name] = [60 - b for b in image[at + 1:at + stride]]
    return out


def dos_table_code(title: str = "pool-of-radiance") -> list[tuple[int, int, int]]:
    """Every `mul <stride>` table lookup in the title's `GAME.OVR`.

    Returns `(file offset, stride, DS offset)`.  The THAC0 loop is the one
    whose stride matches this title's row width; a run of identical hits is the
    compiler failing to share one lookup between the compare and the store.
    """
    from tools import dosbox

    stem = {"pool-of-radiance": "POOLRAD",
            "curse-of-the-azure-bonds": "CURSE",
            "secret-of-the-silver-blades": "SECRET"}[title]
    raw = (dosbox.find_game(stem) / "GAME.OVR").read_bytes()
    return [(m.start(), _u16(m.group(1)), _u16(m.group(2)))
            for m in DOS_LOOKUP.finditer(raw)]


def _best(table: dict[str, list[int]], class_levels) -> int | None:
    """The best row among the classes the character has a level in."""
    best = None
    for name, level in dict(class_levels or {}).items():
        row = table.get(name)
        if not row or not level:
            continue
        got = row[max(0, min(int(level), len(row)) - 1)]
        best = got if best is None else min(best, got)
    return best


# ---------------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------------
#: The four classes Pool of Radiance has, and the record field each keeps its
#: own level in.  `GEN $1EF3` walks the array these sit in, one slot a class.
C64_LEVEL_FIELDS = (("magic-user", "level_magic_user"),
                    ("cleric", "level_cleric"),
                    ("thief", "level_thief"),
                    ("fighter", "level_fighter"))


def c64_records(title: str = "pool-of-radiance"):
    """`(source, name, class levels, stored THAC0)` for every C64 record.

    The player's save disks and every C64 specimen.  The levels come from the
    **per-class array at `0x0C9`**, which is the array `GEN $1EF3` itself
    reads as `LDA $6BC9,X` -- not from `level` at `0x0BA`, which is one number
    and is wrong for a multi-class character.
    """
    where = gamedisks.find(title)
    paths = []
    if where is not None:
        paths += [p for p in sorted(where.glob("*.[dD]64"))
                  if p.name.upper().startswith(("PORSAVE", "NEWSAVE"))]
    tree = pathlib.Path(os.environ.get("WISH_SPECIMENS",
                                       pathlib.Path.home() / "wish-specimens"))
    paths += sorted((tree / "por-c64").glob("WISH-SPEC-por-*.[dD]64"))
    for path in paths:
        try:
            disk = D64.open(str(path))
            names = {e.name for e in disk.directory()}
        except Exception:
            continue
        records = []
        if b"SAVEDGAME0" in names:
            try:
                save = SaveGame0.from_prg(disk.read_file(b"SAVEDGAME0"))
            except Exception:
                continue
            records = [(path.name, s.record) for s in save.characters]
        else:
            for entry in disk.directory():
                if not entry.is_prg or entry.is_empty:
                    continue
                try:
                    records.append((f"{path.name}:{entry.name.decode('latin1').strip()}",
                                    CharacterRecord.from_prg(disk.read_file(entry))))
                except Exception:
                    pass
        for source, record in records:
            held = {name: record.get(field)
                    for name, field in C64_LEVEL_FIELDS
                    if record.get(field)}
            yield source, record.name, held, record.thac0_base_value


DOS_TITLE_BY_KEY = {"pool-of-radiance": "pool-of-radiance",
                    "curse-of-the-azure-bonds": "curse-of-the-azure-bonds",
                    "secret-of-the-silver-blades": "secret-of-the-silver-blades"}


def dos_records(title: str = "pool-of-radiance", extra: list[str] = ()):
    """`(source, name, class levels, stored THAC0)` for every DOS record.

    The specimen tree, the player's DOS game folder, the archives, and any
    `--extra` directory.  Records of another title are skipped, so one sweep
    can be pointed at a tree holding several.
    """
    from tools import dosbox

    tree = pathlib.Path(os.environ.get("WISH_SPECIMENS",
                                       pathlib.Path.home() / "wish-specimens"))
    folders = [str(p) for p in sorted(tree.glob("*/WISH-SPEC-*"))
               if p.is_dir()]
    folders += [str(p) for p in extra]
    files: list[str] = []
    for folder in folders:
        files += glob.glob(folder + "/CHRDAT*.SAV") + glob.glob(folder + "/*.CHA")
    if dosbox.ARCHIVES.is_dir():
        files += glob.glob(str(dosbox.ARCHIVES) + "/**/*.SAV", recursive=True)
        files += glob.glob(str(dosbox.ARCHIVES) + "/**/*.CHA", recursive=True)
    for path in sorted(set(files)):
        try:
            char = dos_codec.read_character(path)
        except Exception:
            continue
        if DOS_TITLE_BY_KEY.get(char.shape.key) != title:
            continue
        parent = pathlib.Path(path).parent.name
        yield (f"{parent}/{pathlib.Path(path).name}", char.name,
               char.class_levels, 60 - char.get("thac0_base"))


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------
def _print_tables(title: str) -> None:
    c64 = c64_table(title)
    try:
        dostab = dos_table(title)
    except Exception as e:                       # no archives, or no anchor
        dostab = {}
        print(f"(no DOS table: {e})")
    print(f"{'class':<12} {'port':<4} THAC0 by level")
    for name in C64_CLASS_ORDER:
        print(f"{name:<12} {'C64':<4} "
              + " ".join(f"{v:2d}" for v in c64[name]))
        if name in dostab:
            row = dostab[name]
            mark = "" if row[:len(c64[name])] == c64[name] else "   <- differs"
            print(f"{'':<12} {'DOS':<4} "
                  + " ".join(f"{v:2d}" for v in row) + mark)
    for offset, stride, ds in dos_table_code(title) if dostab else []:
        print(f"  GAME.OVR 0x{offset:06X}  mul {stride}  DS:0x{ds:04X}")
    tables = levels.for_game(title)
    for name, row in tables.dos_thac0:
        got = dostab.get(name)
        if got is None:
            continue
        state = "matches" if list(row) == got[:len(row)] else "DISAGREES"
        print(f"  goldbox.levels dos_thac0[{name}] {state}")


def _sweep(rows, table, label: str, quiet: bool) -> int:
    total = agree = 0
    for source, name, held, stored in rows:
        want = _best(table, held)
        if want is None:
            continue
        total += 1
        if want == stored:
            agree += 1
        elif not quiet:
            classes = ", ".join(f"{k} {v}" for k, v in sorted(held.items()))
            print(f"MISMATCH {source:<34} {name:<14} {classes:<28} "
                  f"stored={stored:<3} table={want}")
    print(f"{label}: {agree} of {total} agree")
    return total - agree


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("tables", "c64", "dos", "code"))
    ap.add_argument("--title", default="pool-of-radiance")
    ap.add_argument("--extra", action="append", default=[],
                    help="another directory of DOS records to sweep")
    ap.add_argument("--quiet", action="store_true",
                    help="counts only, no per-record lines")
    args = ap.parse_args(argv)

    if args.what == "tables":
        _print_tables(args.title)
        return 0
    if args.what == "code":
        for offset, stride, ds in dos_table_code(args.title):
            print(f"GAME.OVR 0x{offset:06X}  mul {stride}  DS:0x{ds:04X}")
        return 0
    if args.what == "c64":
        return 1 if _sweep(c64_records(args.title), c64_table(args.title),
                           f"C64 {args.title}", args.quiet) else 0
    return 1 if _sweep(dos_records(args.title, args.extra),
                       dos_table(args.title),
                       f"DOS {args.title}", args.quiet) else 0


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(main())
