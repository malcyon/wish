#!/usr/bin/env python3
"""Which effect ids reach the C64's ten trait slots, and which do not.

`#394 (A DOS Curse paladin's Protection from Evil sometimes does not reach the
C64, and two specimens disagree on why)` is the ticket. A paladin's
Protection from Evil, a ranger's own id and a dwarf's three racial ids all live
in the same ten bytes at C64 record `0x0AD` (`docs/171-c64-trait-slots.md`),
filled from two neutral fields at once -- `innate_effects` from slot 0 upward
and `granted_effects` from slot 9 down. So "did the effect cross?" cannot be
answered by looking at either list alone, and the question a player actually
asks is about the ten bytes.

This runs the DOS side of the conversion for real: `goldbox.dos_codec.read_character`,
`goldbox.dos_codec.to_neutral`, then `goldbox.c64_codec.write`, and prints per
character what the source `.SPC`/`.FX`/`.SFX`/`.EFX` file held, how the neutral
record classified it, what landed in the ten slots, and -- the column the
ticket is about -- any id that was in the source and reached no slot.

    tools/traitcross.py ~/wish-specimens/por-dos/WISH-SPEC-curse-131-four-items-readied
    tools/traitcross.py --all                      # every DOS specimen
    tools/traitcross.py --c64 ~/wish-specimens/por-c64/WISH-SPEC-curse-h-engine-resave.D64

`--c64` reads a `.d64`'s own ten bytes instead, so the two halves of a
disagreement can be put side by side in one session.

Nothing is written and every file is opened read only.

**What a run here can and cannot say.** It measures *this project's writer*,
not the game: a specimen's own bytes are the input and `c64_codec.write` is
what is under test, so a LOST column is a defect in `goldbox/c64_codec.py` or
`goldbox/dos_codec.py` and an empty one is not evidence about what the engine does
with the slot afterwards. `.claude/rules/testing.md` has the rest of it.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_codec, dos_codec, items  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402

#: The ten trait slots, at C64 record offset 0x0AD -- `docs/171-c64-trait-slots.md`.
TRAIT_SLOTS = 0x0AD
TRAIT_COUNT = 10


def specimen_tree() -> pathlib.Path:
    """The specimen tree `tools/specimens.py` keeps, `$WISH_SPECIMENS`."""
    from tools import specimens
    return specimens.tree_root()


def dos_folders(root: pathlib.Path):
    """Every directory under `root` holding at least one DOS record."""
    if any(root.glob("CHRDAT*.SAV")) or any(root.glob("*.CHA")):
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_dir() and (any(path.glob("CHRDAT*.SAV"))
                              or any(path.glob("*.CHA"))):
            yield path


def cross_one(path: pathlib.Path) -> tuple[str, list[int], list[int],
                                           list[int], list[int], list[str]]:
    """`(name, source ids, innate, granted, slots, lost)` for one record."""
    char = dos_codec.read_character(path)
    neutral = dos_codec.to_neutral(char)
    rec, rep = c64_codec.write(neutral)
    raw = bytes(rec.to_bytes())
    slots = list(raw[TRAIT_SLOTS:TRAIT_SLOTS + TRAIT_COUNT])
    source = [e[0] for e in char.effects]
    innate = list(neutral.get("innate_effects") or [])
    granted = [int(node[0]) for node in (neutral.get("granted_effects") or [])]
    # An id the source held that is in no slot. A running spell counting down
    # is not one of these: `dos.to_neutral` drops a nonzero duration on
    # purpose, so only the permanent ones are asked about.
    permanent = [e[0] for e in char.effects
                 if int.from_bytes(e[1:3], "little") == 0]
    lost = [e for e in permanent if e not in slots]
    return (str(neutral.get("name") or path.stem), source, innate, granted,
            slots, lost, rep.dropped)


def report_dos(folders, verbose: bool) -> int:
    """Print one row per character. Returns the number of lost ids."""
    total = lost_total = 0
    print(f"{'specimen/record':44} {'name':13} {'source':18} "
          f"{'innate':14} {'granted':10} {'slots'}")
    for folder in folders:
        records = sorted(folder.glob("CHRDAT*.SAV")) + sorted(folder.glob("*.CHA"))
        for path in records:
            try:
                name, source, innate, granted, slots, lost, dropped = \
                    cross_one(path)
            except Exception as exc:  # noqa: BLE001 - a record we cannot read
                print(f"  skipped {folder.name}/{path.name}: {exc}")
                continue
            total += 1
            lost_total += len(lost)
            if not verbose and not source:
                continue
            filled = [s for s in slots if s]
            mark = f"  LOST {lost}" if lost else ""
            print(f"{folder.name + '/' + path.name:44} {name:13} "
                  f"{str(source):18} {str(innate):14} {str(granted):10} "
                  f"{filled}{mark}")
            if verbose:
                for line in dropped:
                    if "ffect" in line:
                        print(f"{'':44} drop: {line}")
    print(f"\n{total} records read, {lost_total} permanent effect ids in no "
          f"trait slot.")
    return lost_total


def report_c64(paths) -> int:
    """Print the ten stored bytes of every character on a `.d64`."""
    for p in paths:
        path = pathlib.Path(p).expanduser()
        game, sg0, sg1 = load_save(D64.open(str(path)))
        print(f"== {path.name}  {game.title if game else '?'}")
        for slot in sg0.characters:
            raw = bytes(slot.record.to_bytes())
            block = sg1.roster(slot.index) if sg1 is not None else None
            inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(),
                                                       slot.index)]
            neutral = c64_codec.read(slot.record, roster=block, inventory=inv,
                                     game=game, source=path.name)
            levels = {k: v for k, v in (neutral.get("levels") or {}).items()
                      if v}
            print(f"  #{slot.index} {str(neutral.get('name')):13} "
                  f"{str(levels):34} "
                  f"slots={list(raw[TRAIT_SLOTS:TRAIT_SLOTS + TRAIT_COUNT])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="*",
                    help="a DOS save folder, or a .d64 with --c64")
    ap.add_argument("--all", action="store_true",
                    help="every DOS specimen in $WISH_SPECIMENS")
    ap.add_argument("--c64", action="store_true",
                    help="read the ten stored bytes of a .d64 instead")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show characters with no effects, and drop lines")
    args = ap.parse_args(argv)

    if args.c64:
        if not args.path:
            ap.error("--c64 needs at least one .d64")
        return report_c64(args.path)

    roots = [pathlib.Path(p).expanduser() for p in args.path]
    if args.all:
        tree = specimen_tree()
        if not tree.is_dir():
            print(f"no specimen tree at {tree}; see tools/specimens.py")
            return 2
        roots.append(tree)
    if not roots:
        ap.error("give a DOS save folder, or --all")

    folders = [f for root in roots for f in dos_folders(root)]
    if not folders:
        print("no DOS records found")
        return 2
    return 1 if report_dos(folders, args.verbose) else 0


if __name__ == "__main__":
    raise SystemExit(main())
