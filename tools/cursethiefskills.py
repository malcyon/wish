#!/usr/bin/env python3
"""Why a DOS Curse thief's eight stored skills sit seven points high (#437).

The DOS engines compute a thief's eight percentages in one routine, and all
three builds of it are the same shape: a loop over skills 1 to 8 that adds a
level row, a racial row, a dexterity row for the first five columns, and a
one-byte stack local this file calls `var_2` -- the item bonus for a readied
pair of thieves' tools.  **Curse never initialises that local**, so a thief
with no such item readied has whatever the stack held added to every one of
his eight skills.  On this machine it is 7, in every DOS Curse record there
is.  Silver Blades' copy of the same routine opens with `mov byte [bp-2], 0`
and Pool of Radiance's has no such term at all, which is why neither title
shows the offset.

    tools/cursethiefskills.py routine    the three DOS routines, and which
                                         initialises the local
    tools/cursethiefskills.py records    every Curse record, DOS and C64,
                                         against the port's own tables
    tools/cursethiefskills.py labels     whether either port ever draws a
                                         thief skill

`routine` reads the player's own `GAME.OVR` for each title -- nothing here is
hardcoded but the instruction encodings.  The routine is located by its store
into the thief-skill array, `mov byte ptr es:[di+<pick pockets - 1>], 0`,
which is the clamp arm; the function entry is the nearest `push bp / mov bp,
sp / sub sp, imm` before it, and the initialisation test is whether
`c6 46 fe <imm>` (`mov byte [bp-2], imm8`) appears between that entry and the
first read of the local.

**A byte pattern is not proof that bytes are code**, the caution
`tools/d6502.py` and `tools/dosdis16.py` both carry.  What makes this one
sound is that the three matches sit inside three routines of identical shape,
each reading three tables at displacements 0x60 and 0x73 apart -- the same
geometry `tools/thiefskillcensus.py` reads the tables at -- and each storing
eight bytes into the record offset this project has already attributed.
`tools/dosdis16.py --game CURSE --file GAME.OVR --at 0x3b74a` prints the
routine itself.

`records` says the same thing from the other side: columns 6, 7 and 8 take no
dexterity term, so a record's residual there is `var_2` and nothing else.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos  # noqa: E402
from tools import thiefskillcensus as census  # noqa: E402

#: `push bp / mov bp, sp / sub sp, imm8` -- a Borland C far function's prologue.
PROLOGUE = re.compile(rb"\x55\x89\xe5\x83\xec.", re.S)

#: `mov byte ptr [bp-2], imm8`, the assignment Curse's routine never makes
#: before its loop.
SET_VAR2 = re.compile(rb"\xc6\x46\xfe(.)", re.S)

#: `mov al, byte ptr [bp-2]`, where the local is read.
GET_VAR2 = bytes.fromhex("8a46fe")

#: The three DOS builds, by the stem `tools/dosbox.py` finds them under.
TITLES = (("pool-of-radiance", "POOLRAD"),
          ("curse-of-the-azure-bonds", "CURSE"),
          ("secret-of-the-silver-blades", "SECRET"))


def _skill_base(title: str) -> int:
    """The displacement the routine indexes: pick pockets minus one.

    The loop counts skills 1 to 8 and adds the counter to the record pointer,
    so every access is written `es:[di + <pick pockets - 1>]`.
    """
    for field in dos.LAYOUTS[title]:
        if getattr(field, "name", "") == "thief_pick_pockets":
            return field.offset - 1
    raise SystemExit(f"{title}: no thief_pick_pockets in the layout")


def _store_pattern(offset: int) -> re.Pattern:
    """`mov byte ptr es:[di+offset], 0`, in whichever displacement form fits."""
    if offset <= 0x7F:
        return re.compile(re.escape(bytes([0x26, 0xC6, 0x45, offset, 0x00])))
    return re.compile(re.escape(bytes([0x26, 0xC6, 0x85, offset & 0xFF,
                                       offset >> 8, 0x00])))


#: `mov cl, 3 / shl di, cl / add di, dx` -- how every one of the three tables
#: is indexed, `row * 8 + skill`.  The record's own byte at `pick pockets - 1`
#: is a field in its own right in the later titles, so a store into it is not
#: on its own the routine; a store with three of these in front of it is.
TABLE_INDEX = re.compile(re.escape(bytes.fromhex("b103d3e703fa")))

#: How far back from a candidate store the indexing has to be found.
WINDOW = 0x200


def routine(title: str, stem: str) -> dict:
    """Where the title's thief-skill routine is, and what it adds."""
    from tools import dosbox

    folder = dosbox.find_game(stem)
    if folder is None:
        raise SystemExit(f"no {stem} directory; see tools/dosbox.py")
    image = (folder / "GAME.OVR").read_bytes()
    offset = _skill_base(title)
    stores = [m.start() for m in _store_pattern(offset).finditer(image)]
    stores = [s for s in stores
              if len(TABLE_INDEX.findall(image[max(0, s - WINDOW):s])) >= 3]
    if not stores:
        return {"title": title, "at": None}
    at = stores[0]
    entries = [m.start() for m in PROLOGUE.finditer(image) if m.start() < at]
    entry = entries[-1] if entries else None
    head = image[entry:at] if entry is not None else b""
    sets = [(entry + m.start(), m.group(1)[0]) for m in SET_VAR2.finditer(head)]
    reads = [entry + m.start() for m in re.finditer(re.escape(GET_VAR2), head)]
    # **Before the loop, not merely before the read.**  The four assignments
    # Curse makes are inside the loop body and behind the item test, so they
    # run for nobody carrying no item; the one Silver Blades makes is in the
    # prologue.  `mov byte ptr [bp-1], 1` is where the skill counter is set
    # up, and everything after it is inside the loop.
    loop = head.find(bytes.fromhex("c646ff01"))
    loop = entry + loop if loop >= 0 else at
    before = [s for s in sets if s[0] < loop]
    # `add byte ptr es:[di+offset], imm8` -- the flat item bonus.
    if offset <= 0x7F:
        add = re.compile(re.escape(bytes([0x26, 0x80, 0x45, offset])) + b"(.)",
                         re.S)
    else:
        add = re.compile(re.escape(bytes([0x26, 0x80, 0x85, offset & 0xFF,
                                          offset >> 8])) + b"(.)", re.S)
    adds = [(m.start(), m.group(1)[0]) for m in add.finditer(image)]
    return {"title": title, "offset": offset, "at": at, "entry": entry,
            "loop": loop, "stores": stores, "sets_before_loop": before,
            "sets_in_loop": [s for s in sets if s[0] >= loop], "reads": reads,
            "adds": adds, "initialised": bool(before)}


def _print_routine() -> None:
    for title, stem in TITLES:
        try:
            found = routine(title, stem)
        except SystemExit as why:
            print(f"{title}: {why}")
            continue
        if found["at"] is None:
            print(f"{title}: no store into the thief-skill array found")
            continue
        print(f"=== {title} (GAME.OVR)")
        print(f"  routine entry   0x{found['entry']:06X}")
        print(f"  clamp store     0x{found['at']:06X}  "
              f"es:[di+0x{found['offset']:02X}], 0")
        where = ", ".join(f"0x{r:06X}" for r in found["reads"]) or "none"
        print(f"  reads of [bp-2] {where}")
        if found["initialised"]:
            for where, value in found["sets_before_loop"]:
                print(f"  INITIALISED     0x{where:06X}  "
                      f"mov byte [bp-2], {value}  (before the loop)")
        elif found["reads"]:
            print("  NOT INITIALISED before the loop -- the local is whatever "
                  "the stack held")
        else:
            print("  no [bp-2] term at all")
        for where, value in found["sets_in_loop"]:
            print(f"  inside the loop 0x{where:06X}  "
                  f"mov byte [bp-2], {value}")
        for where, value in found["adds"]:
            print(f"  flat item bonus 0x{where:06X}  "
                  f"add es:[di+0x{found['offset']:02X}], {value}")


def residuals(title: str = "curse-of-the-azure-bonds"):
    """`(source, name, stored, wanted, residual)` for every DOS record."""
    tables = census.dos_tables(title)
    for row in census.dos_records(title):
        source, name, race, level, dexterity, stored = row
        want = census.expected(tables, level, race, dexterity, True)
        if want is None:
            continue
        yield source, name, stored, want, [a - b for a, b in zip(stored, want)]


def _print_records(title: str) -> None:
    print(f"=== {title}: DOS records against the DOS tables")
    seen: dict[int, int] = {}
    for source, name, stored, want, delta in residuals(title):
        # Columns 6, 7 and 8 have no dexterity term, so their residual is the
        # stack local and nothing else.
        tail = set(delta[5:])
        flat = delta[0] if len(set(delta)) == 1 else None
        if flat is not None:
            seen[flat] = seen.get(flat, 0) + 1
        print(f"  {source:<56} {name:<14} residual {delta}"
              + ("" if len(tail) == 1 else "   <- not flat on 6-8"))
    print("  flat residual, by value: "
          + ", ".join(f"{k}: {v} record(s)" for k, v in sorted(seen.items())))
    print(f"=== {title}: C64 records against the C64 tables")
    tables = census.c64_tables(title)
    for row in census.c64_records(title):
        source, name, race, level, dexterity, stored = row
        want = census.expected(tables, level, race, dexterity, True)
        if want is None:
            continue
        print(f"  {source:<56} {name:<14} residual "
              f"{[a - b for a, b in zip(stored, want)]}")


#: The words a sheet would have to draw, in the C64's three encodings.
LABELS = (b"POCKET", b"NOISE", b"SHADOW", b"SILENT", b"CLIMB", b"LOCKS",
          b"LANGUAGE")

#: Words the same disks certainly do carry, so a count of zero means something.
CONTROLS = (b"ENCAMP", b"SEARCH", b"MOVE", b"EXPERIENCE")


def _screen_codes(word: bytes) -> bytes:
    """PETSCII capitals as screen codes: `A` is 1 rather than 0x41."""
    return bytes(b - 0x40 for b in word)


def _print_labels(title: str) -> None:
    from goldbox.d64 import D64
    from tools import gamedisks

    where = gamedisks.find(title)
    if where is None:
        raise SystemExit(f"no {title} disks; see tools/gamedisks.py")
    counts: dict[bytes, int] = {w: 0 for w in LABELS + CONTROLS}
    files = 0
    for path in sorted(where.glob("*.[dD]64")):
        try:
            disk = D64.open(str(path))
            entries = list(disk.directory())
        except Exception:
            continue
        for entry in entries:
            try:
                data = disk.read_file(entry)
            except Exception:
                continue
            files += 1
            for word in counts:
                if (word in data or _screen_codes(word) in data
                        or word.lower() in data):
                    counts[word] += 1
    print(f"=== {title}: {files} files on the C64 disks")
    for word in LABELS:
        print(f"  {word.decode():<10} {counts[word]:3d} file(s)")
    print("  -- controls --")
    for word in CONTROLS:
        print(f"  {word.decode():<10} {counts[word]:3d} file(s)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("routine", "records", "labels"))
    ap.add_argument("--title", default="curse-of-the-azure-bonds",
                    choices=sorted(census.C64_TABLES))
    args = ap.parse_args(argv)
    if args.what == "routine":
        _print_routine()
    elif args.what == "records":
        _print_records(args.title)
    else:
        _print_labels(args.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
