#!/usr/bin/env python3
"""Every stored thief skill on this machine, against the port's own tables.

The C64 and DOS builds of Pool of Radiance do **not** ship the same racial
adjustment table, and this is what established that the disagreement is the
game's rather than ours.  It reads each port's tables out of the player's own
files and then sweeps every character record it can reach, saying for each
thief whether the eight stored bytes are what that port's own tables give.

    tools/thiefskillcensus.py tables     both ports' tables, side by side
    tools/thiefskillcensus.py rows       the racial rows aligned, and the
                                         byte-stream diff between the ports
    tools/thiefskillcensus.py c64        every C64 record, against `GEN`
    tools/thiefskillcensus.py dos        every DOS record, against `START.EXE`
    tools/thiefskillcensus.py dos --title curse-of-the-azure-bonds

**Neither side is hardcoded.**  The C64's tables come off whichever disk of
the title carries `GEN`, at the addresses `goldbox/levels.py` names -- which
the engine's own `LDA $102E,X` / `LDA $1076,X` fixes for Pool of Radiance.
The DOS ones come out of `START.EXE`, which is EXEPACK-packed
(`tools/unexepack.py`), located in the expanded image by **the C64's own 72
bytes of level table**: that run occurs exactly once in each of the three
images, so the anchor is a file on the player's shelf rather than a number in
this repository.  Two structural checks then say the geometry is right and
both are arithmetic rather than judgement: the racial block's human row has to
be all zeros where the title has one, and the dexterity block's rows for 13,
14 and 15 have to be zeros.

The two ports do not run the same rule, which is the point:

* **C64 Pool of Radiance** adds the level row and the racial row and stops.
  `GEN $1FEC` reads `level_thief`, copies eight bytes from `$102E`, then reads
  `race`, decrements, and adds eight bytes from `$1076`.  `$2020 RTS`.  No
  dexterity anywhere.
* **DOS** adds a dexterity block too, five columns wide, from a dexterity of
  9 up -- and stores the result unclamped, negatives included.

`--rule` prints, per record, which of the candidate rules reproduces the
stored bytes, which is how the dexterity block was shown to be live in DOS and
absent from the C64.

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

from goldbox import dos, games  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402
from goldbox.savegame import SaveGame0  # noqa: E402
from tools import gamedisks  # noqa: E402

#: `GEN` is resident here whatever its PRG header claims.
GEN_BASE = 0x0800

#: The eight skills, in the order both ports store them.
SKILLS = ("thief_pick_pockets", "thief_open_locks", "thief_find_traps",
          "thief_move_silently", "thief_hide_in_shadows", "thief_hear_noise",
          "thief_climb_walls", "thief_read_languages")

#: Where each C64 title keeps the three tables, and how it indexes the racial
#: one.  Every address is `goldbox/levels.py`'s, read there off the engine's
#: own instruction; `race_from` is 1 where the engine decrements the race byte
#: and 0 where it does not -- Silver Blades does not, which is `#89`.
C64_TABLES = {
    "pool-of-radiance": dict(level=0x102E, level_rows=9, race=0x1076,
                             race_rows=8, race_from=1, dex=None, dex_rows=0),
    "curse-of-the-azure-bonds": dict(level=0x1004, level_rows=12, race=0x1064,
                                     race_rows=8, race_from=1, dex=0x10A4,
                                     dex_rows=17),
    "secret-of-the-silver-blades": dict(level=0x126D, level_rows=17,
                                        race=0x12F5, race_rows=6, race_from=0,
                                        dex=0x131D, dex_rows=17),
}

#: How many racial rows each DOS build lays out, and whether the last is the
#: human row of zeros.  Silver Blades reorders its races and drops both the
#: half-orc's neighbours and the human row.
DOS_RACE_ROWS = {"pool-of-radiance": 7, "curse-of-the-azure-bonds": 7,
                 "secret-of-the-silver-blades": 6}

#: The dexterity block is five columns -- pick pockets, open locks, find
#: traps, move silently, hide in shadows -- and starts at a dexterity of 9.
#: **Eleven rows, 9 to 19, and the twelfth is not a dexterity row**: in all
#: three DOS images the bytes after it are `08 08 12 11 63`, which is the
#: ability-minimum block rather than an adjustment.  A character cannot hold
#: a dexterity above 18, so the block covers everything reachable.
DEX_COLUMNS = 5
DEX_FROM = 9
DEX_ROWS = 11

#: Which `START.EXE` each title's tables live in.
DOS_STEM = {"pool-of-radiance": "POOLRAD",
            "curse-of-the-azure-bonds": "CURSE",
            "secret-of-the-silver-blades": "SECRET"}


def _signed(raw) -> list[int]:
    return [b - 256 if b > 127 else b for b in raw]


def _dexterity(char) -> int:
    """The score the trainer reads, from a title that keeps one or two.

    Curse and everything after it store every ability as a **(base, current)
    pair**, so `get` hands back two bytes there and one in Pool of Radiance.
    The second is the one play changes, so it is the one taken.
    """
    got = char.get("dexterity") or 0
    if isinstance(got, (bytes, bytearray)):
        return got[-1] if got else 0
    return int(got)


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------
def _gen(title: str) -> bytes:
    """The title's own `GEN`, off whichever of the player's disks carries it."""
    where = gamedisks.find(title)
    if where is None:
        raise SystemExit(f"no {title} disks; see tools/gamedisks.py")
    for path in sorted(where.glob("*.[dD]64")):
        try:
            disk = D64.open(str(path))
        except Exception:
            continue
        for entry in disk.directory():
            if entry.name.strip() == b"GEN":
                return disk.read_file(entry)[2:]
    raise SystemExit(f"no GEN on any disk under {where}")


def c64_tables(title: str = "pool-of-radiance") -> dict:
    """`{level, race, dex}` for a title, read off the player's own `GEN`."""
    spec = C64_TABLES[title]
    gen = _gen(title)

    def rows(address, count, width):
        at = address - GEN_BASE
        return [_signed(gen[at + r * width:at + r * width + width])
                for r in range(count)]

    out = {"level": rows(spec["level"], spec["level_rows"], 8),
           "race": rows(spec["race"], spec["race_rows"], 8),
           "race_from": spec["race_from"], "dex": None}
    if spec["dex"] is not None:
        out["dex"] = rows(spec["dex"], spec["dex_rows"], 8)
    return out


def dos_image(title: str = "pool-of-radiance") -> bytes:
    """The player's own `START.EXE`, EXEPACK-expanded."""
    from tools import dosbox, unexepack

    folder = dosbox.find_game(DOS_STEM[title])
    image, _ = unexepack.unpack((folder / "START.EXE").read_bytes())
    return image


def dos_tables(title: str = "pool-of-radiance",
               image: bytes | None = None,
               anchor: list[int] | None = None) -> dict:
    """`{level, race, dex, at}` out of the DOS build's own data segment.

    Anchored on the C64's first nine level rows, which must occur exactly once
    in the image.  Pass `anchor` to use something else; the default reads the
    C64 disk, so the anchor is never a number from this repository.
    """
    image = dos_image(title) if image is None else image
    if anchor is None:
        anchor = [b for row in c64_tables(title)["level"][:9] for b in row]
    needle = bytes(b & 0xFF for b in anchor)
    hits = [m.start() for m in re.finditer(re.escape(needle), image)]
    if len(hits) != 1:
        raise SystemExit(f"{title}: the level-table anchor occurs "
                         f"{len(hits)} times, so it does not locate anything")
    at = hits[0]
    # The level rows run until the racial block, and how many there are is
    # per-title -- 9 in Pool of Radiance, 12 in Curse, 18 in Silver Blades.
    # Count them rather than declaring them: every level row has a climb-walls
    # column of 80 or more and a pick-pockets column of 30 or more, read
    # **unsigned** (Silver Blades' eighteenth row picks 130 pockets), and no
    # racial row has either.
    level = []
    off = at
    while off + 8 <= len(image) and image[off + 6] >= 80 and image[off] >= 30:
        level.append(_signed(image[off:off + 8]))
        off += 8
    race_rows = DOS_RACE_ROWS[title]
    race = [_signed(image[off + r * 8:off + r * 8 + 8])
            for r in range(race_rows)]
    dex_at = off + race_rows * 8
    dex = [_signed(image[dex_at + r * DEX_COLUMNS:
                         dex_at + r * DEX_COLUMNS + DEX_COLUMNS])
           for r in range(DEX_ROWS)]
    return {"level": level, "race": race, "dex": dex, "race_from": 1,
            "at": at, "race_at": off, "dex_at": dex_at}


def check_dos_geometry(tables: dict, title: str) -> list[str]:
    """The two structural checks that say the blocks were found, not guessed."""
    bad = []
    if DOS_RACE_ROWS[title] == 7 and any(tables["race"][6]):
        bad.append("the seventh racial row is not the human row of zeros")
    for score in (13, 14, 15):
        row = tables["dex"][score - DEX_FROM]
        if any(row):
            bad.append(f"the dexterity {score} row is {row}, not zeros")
    return bad


# ---------------------------------------------------------------------------
# The rule each port runs
# ---------------------------------------------------------------------------
def expected(tables: dict, thief_level: int, race: int, dexterity: int,
             with_dex: bool, clamp: bool = False) -> list[int] | None:
    """The eight skills the port's own tables give, or None off the end.

    `clamp` is the DOS rule: a column that would come out negative is stored
    as zero.  The C64 stores the negative -- `$FB` for the halfling's -5 read
    languages -- which is why its record field is signed.
    """
    if not thief_level:
        return None
    if thief_level > len(tables["level"]):
        return None
    out = list(tables["level"][thief_level - 1])
    index = race - tables["race_from"]
    if 0 <= index < len(tables["race"]):
        row = tables["race"][index]
        out = [a + b for a, b in zip(out, row)]
    if with_dex and tables.get("dex"):
        at = max(0, min(dexterity, DEX_FROM + DEX_ROWS - 1) - DEX_FROM)
        row = tables["dex"][at]
        for i in range(min(DEX_COLUMNS, len(row))):
            out[i] += row[i]
    return [max(0, v) for v in out] if clamp else out


# ---------------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------------
def c64_records(title: str = "pool-of-radiance"):
    """`(source, name, race, thief level, dexterity, stored eight)`."""
    where = gamedisks.find(title)
    paths = []
    if where is not None:
        paths += [p for p in sorted(where.glob("*.[dD]64"))
                  if p.name.upper().startswith(("PORSAVE", "NEWSAVE"))]
    tree = pathlib.Path(os.environ.get("WISH_SPECIMENS",
                                       pathlib.Path.home() / "wish-specimens"))
    for folder in ("por-c64", "curse-c64", "ssb-c64"):
        paths += sorted((tree / folder).glob("*.[dD]64"))
    paths += sorted(tree.glob("*/*.[dD]64"))
    for path in sorted(set(paths)):
        try:
            disk = D64.open(str(path))
            names = {e.name for e in disk.directory()}
        except Exception:
            continue
        # A disk of another title reads as plausible rubbish against this
        # one's tables, so ask the disk what it is rather than sweeping
        # everything the tree holds.
        found = games.detect(disk)
        if found is not None and found.key != title:
            continue
        records = []
        if found is not None and found.save_file in names:
            try:
                save = SaveGame0.from_prg(disk.read_file(found.save_file),
                                          found)
            except Exception:
                continue
            records = [(path.name, s.record) for s in save.characters]
        else:
            for entry in disk.directory():
                if not entry.is_prg or entry.is_empty:
                    continue
                try:
                    label = entry.name.decode("latin1").strip()
                    records.append((f"{path.name}:{label}",
                                    CharacterRecord.from_prg(
                                        disk.read_file(entry))))
                except Exception:
                    pass
        for source, record in records:
            level = record.get("level_thief") or 0
            if not level:
                continue
            yield (source, record.name, record.get("race") or 0, level,
                   record.get("dexterity") or 0,
                   [record.get(f) for f in SKILLS])


def dos_records(title: str = "pool-of-radiance", extra=()):
    """The same, for every DOS record the specimen tree and archives hold."""
    from tools import dosbox

    tree = pathlib.Path(os.environ.get("WISH_SPECIMENS",
                                       pathlib.Path.home() / "wish-specimens"))
    folders = [str(p) for p in sorted(tree.glob("*/WISH-SPEC-*")) if p.is_dir()]
    folders += [str(p) for p in extra]
    files: list[str] = []
    for folder in folders:
        files += glob.glob(folder + "/CHRDAT*.SAV") + glob.glob(folder + "/*.CHA")
    if dosbox.ARCHIVES.is_dir():
        files += glob.glob(str(dosbox.ARCHIVES) + "/**/*.SAV", recursive=True)
        files += glob.glob(str(dosbox.ARCHIVES) + "/**/*.CHA", recursive=True)
    for path in sorted(set(files)):
        try:
            char = dos.read_character(path)
        except Exception:
            continue
        if char.shape.key != title:
            continue
        level = dict(char.class_levels or {}).get("thief") or 0
        if not level:
            continue
        parent = pathlib.Path(path).parent.name
        yield (f"{parent}/{pathlib.Path(path).name}", char.name,
               char.get("race") or 0, level, _dexterity(char),
               [char.get(f) for f in SKILLS])


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------
def _race_names(title: str) -> list[str]:
    """The title's own race numbering, so a row is labelled by what reads it.

    Silver Blades reorders the table, so calling its row 0 "dwarf" -- which
    an earlier draft of this tool did -- is how a reader ends up comparing
    two different races and calling it a difference between the ports.
    """
    from goldbox import games

    table = games.race_table(games.by_key(title))
    top = max(table) if table else 0
    return [table.get(i + 1, f"row {i}") for i in range(top)]


def _print_tables(title: str) -> None:
    c64 = c64_tables(title)
    print(f"=== {title}")
    print("C64 level rows (GEN):")
    for i, row in enumerate(c64["level"], start=1):
        print(f"  {i:2d} " + " ".join(f"{v:4d}" for v in row))
    print(f"C64 racial rows, indexed race - {c64['race_from']}:")
    for i, row in enumerate(c64["race"]):
        print(f"  {i} " + " ".join(f"{v:4d}" for v in row))
    try:
        dostab = dos_tables(title)
    except Exception as e:
        print(f"(no DOS tables: {e})")
        return
    print(f"DOS level rows (START.EXE at 0x{dostab['at']:05X}):")
    for i, row in enumerate(dostab["level"], start=1):
        print(f"  {i:2d} " + " ".join(f"{v:4d}" for v in row))
    print(f"DOS racial rows (0x{dostab['race_at']:05X}):")
    for i, row in enumerate(dostab["race"]):
        print(f"  {i} " + " ".join(f"{v:4d}" for v in row))
    print(f"DOS dexterity rows (0x{dostab['dex_at']:05X}), from {DEX_FROM}:")
    for i, row in enumerate(dostab["dex"]):
        print(f"  {DEX_FROM + i:2d} " + " ".join(f"{v:4d}" for v in row))
    for line in check_dos_geometry(dostab, title):
        print(f"  GEOMETRY: {line}")


def _print_rows(title: str) -> None:
    """The racial rows of the two ports beside each other, and the diff."""
    c64 = c64_tables(title)["race"]
    dostab = dos_tables(title)["race"]
    print(f"=== {title}: racial thief adjustments, both ports")
    header = ("pick", "lock", "trap", "move", "hide", "hear", "climb", "read")
    print(f"{'race':<10} {'port':<4} " + " ".join(f"{h:>5}" for h in header))
    names = _race_names(title)
    for i in range(max(len(c64), len(dostab))):
        name = names[i] if i < len(names) else f"row {i}"
        if i < len(c64):
            print(f"{name:<10} {'C64':<4} "
                  + " ".join(f"{v:5d}" for v in c64[i]))
        if i < len(dostab):
            same = i < len(c64) and c64[i] == dostab[i]
            print(f"{'':<10} {'DOS':<4} "
                  + " ".join(f"{v:5d}" for v in dostab[i])
                  + ("" if same else "   <- differs"))
    a = [v for row in c64 for v in row]
    b = [v for row in dostab for v in row]
    shared = 0
    while shared < min(len(a), len(b)) and a[shared] == b[shared]:
        shared += 1
    print(f"\nthe two byte streams agree for {shared} bytes, then diverge")
    for shift in range(1, 4):
        for start in range(shared, shared + 8):
            end = min(len(a), len(b) - shift)
            if start >= end:
                break
            if end - start >= 8 and all(a[i] == b[i + shift]
                                        for i in range(start, end)):
                print(f"and from byte {start} the C64 stream is the DOS "
                      f"stream {shift} byte(s) later, for the remaining "
                      f"{end - start} bytes of the DOS table")
                return


def _sweep(rows, tables, label: str, quiet: bool, with_dex: bool,
           rule: bool, clamp: bool = False) -> int:
    total = agree = 0
    counts = {"level+race": 0, "level+race+dex": 0,
              "level+race+dex, clamped": 0, "neither": 0}
    for source, name, race, level, dexterity, stored in rows:
        plain = expected(tables, level, race, dexterity, False)
        dexed = expected(tables, level, race, dexterity, True)
        clamped = expected(tables, level, race, dexterity, True, clamp=True)
        if plain is None:
            continue
        total += 1
        want = (clamped if clamp else dexed) if with_dex else plain
        if stored == want:
            agree += 1
        elif not quiet:
            print(f"MISMATCH {source:<44} {name:<12} "
                  f"race {race} thief {level} dex {dexterity}")
            print(f"    stored {stored}")
            print(f"    table  {want}")
        if rule:
            which = ("level+race" if stored == plain else
                     "level+race+dex" if stored == dexed else
                     "level+race+dex, clamped" if stored == clamped
                     else "neither")
            counts[which] += 1
    print(f"{label}: {agree} of {total} agree")
    if rule:
        print("  by rule: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return total - agree


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("tables", "rows", "c64", "dos"))
    ap.add_argument("--title", default="pool-of-radiance",
                    choices=sorted(C64_TABLES))
    ap.add_argument("--extra", action="append", default=[],
                    help="another directory of DOS records to sweep")
    ap.add_argument("--quiet", action="store_true", help="counts only")
    ap.add_argument("--rule", action="store_true",
                    help="also say which rule reproduces each record")
    ap.add_argument("--no-dex", action="store_true",
                    help="score DOS records without the dexterity block")
    args = ap.parse_args(argv)

    if args.what == "tables":
        _print_tables(args.title)
        return 0
    if args.what == "rows":
        _print_rows(args.title)
        return 0
    if args.what == "c64":
        tables = c64_tables(args.title)
        return 1 if _sweep(c64_records(args.title), tables,
                           f"C64 {args.title}", args.quiet,
                           tables.get("dex") is not None, args.rule) else 0
    tables = dos_tables(args.title)
    for line in check_dos_geometry(tables, args.title):
        print(f"GEOMETRY: {line}")
    return 1 if _sweep(dos_records(args.title, args.extra), tables,
                       f"DOS {args.title}", args.quiet,
                       not args.no_dex, args.rule, clamp=True) else 0


if __name__ == "__main__":
    raise SystemExit(main())
