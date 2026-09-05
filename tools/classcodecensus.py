#!/usr/bin/env python3
"""Does a record's class code agree with its class bitmask?

Every Gold Box character record says its class twice: a bitmask (`class_bits`,
C64 `0x0EB` / DOS Curse `0x12B`) and a single code (`char_class`, C64 `0x073` /
DOS Curse `0x075`).  `goldbox/yaml_io.py` says they "agree in every specimen",
and the DOS engine prints the class from the **code** -- so a record where
they disagree draws the wrong word on the sheet after a conversion.

This counts the disagreements, per port and per title, over every save and
record it is pointed at.

    tools/classcodecensus.py                       # the specimen tree
    tools/classcodecensus.py --archives            # and the shipped archives
    tools/classcodecensus.py --c64 ~/wish-specimens/por-c64

The bits-to-code table is **the game's own**, read out of Curse of the Azure
Bonds' `GEN` at `$1951`: a 17-entry run indexed by the class code, holding the
bitmask that code stands for.  `CURSE_CLASS_TABLE` below is that run, and the
routine at `GEN $1939` is what walks it.  Pool of Radiance's table has no
paladin or ranger, and `goldbox/yaml_io.py`'s `CLASS_CODES` is its shared
subset; only entry 10 differs between the two, so a bitmask this tool cannot
place is printed rather than guessed at.

Nothing here writes anything.  The player's disks and archives are opened
read only.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import c64_codec, dos, dos_layout, items  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402

#: Curse of the Azure Bonds' own class table, `GEN $1951`, indexed by the
#: class code and holding the class bitmask.  Index 10 is `0x82`
#: (cleric + ranger), where Pool of Radiance's table has cleric/magic-user.
CURSE_CLASS_TABLE = (0x02, 0x00, 0x08, 0x40, 0x80, 0x01, 0x04, 0x00,
                     0x0A, 0x0B, 0x82, 0x03, 0x06, 0x09, 0x0C, 0x0D, 0x05)

#: Bitmask -> the code that stands for it.  Built from the table above, first
#: occurrence winning, so the two zero entries (druid and monk, neither of
#: which any Gold Box record carries) do not claim the mask 0.
CODE_FOR_BITS = {}
for _code, _bits in enumerate(CURSE_CLASS_TABLE):
    if _bits and _bits not in CODE_FOR_BITS:
        CODE_FOR_BITS[_bits] = _code

#: The C64 record's two offsets, from `goldbox/layout.py`.
C64_CLASS_BITS = 0x0EB
C64_CHAR_CLASS = 0x073

#: Class name -> its bit, in the order every port's bitmask uses once
#: `goldbox.dos.neutral_class_bits` has folded DOS's paladin and ranger back.
BIT_FOR_CLASS = {"magic-user": 0x01, "cleric": 0x02, "thief": 0x04,
                 "fighter": 0x08, "knight": 0x10, "paladin": 0x40,
                 "ranger": 0x80}


def bits_from_levels(levels: dict) -> int:
    """The bitmask of the classes a character currently holds levels in.

    Not the same thing as the stored `class_bits`, and deliberately: for a
    dual-classed character the mask gains the old class's bit back once the
    new class passes the level he left it at while the level array keeps that
    slot at zero, and for SILAS -- the shipped Pool of Radiance fighter -- the
    level array carries a thief 1 the mask has never heard of.  Reading the
    levels catches **both** kinds of disagreement, which is what a census
    wants; `goldbox.dos.write` takes the mask, which is what a *writer* wants,
    and `docs/187-the-class-code-byte.md` says why.
    """
    out = 0
    for name, level in (levels or {}).items():
        if level:
            out |= BIT_FOR_CLASS.get(name, 0)
    return out


def c64_records(root: pathlib.Path):
    """`(label, title, bits, class_bits, char_class)` for every C64 save."""
    paths = sorted(root.rglob("*.[dD]64")) if root.is_dir() else [root]
    for path in paths:
        try:
            game, sg0, sg1 = load_save(D64.open(str(path)))
        except Exception as exc:  # noqa: BLE001 - a disk that is not a save
            print(f"  skipped {path.name}: {exc}")
            continue
        for slot in sg0.characters:
            rec = bytes(slot.record.to_bytes())
            block = sg1.roster(slot.index) if sg1 is not None else None
            inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(),
                                                       slot.index)]
            neutral = c64_codec.read(slot.record, roster=block, inventory=inv,
                                     game=game, source=path.name)
            yield (f"{path.name}#{slot.index}", game.title if game else "?",
                   bits_from_levels(neutral.get("levels")),
                   rec[C64_CLASS_BITS], rec[C64_CHAR_CLASS])


def dos_records(root: pathlib.Path):
    """The same for every DOS character record under `root`.

    **The bitmask is the neutral one**, not the stored byte: DOS numbers the
    paladin's and the ranger's bits differently from the C64, which
    `goldbox.dos.neutral_class_bits` folds back.  Reading the stored byte
    against the C64's table made every DOS ranger in the corpus look like a
    disagreement, which was this tool's fault and not the game's.
    """
    paths = sorted(root.rglob("*")) if root.is_dir() else [root]
    for path in paths:
        if not path.is_file() or path.stat().st_size not in dos_layout.SHAPES_BY_SIZE:
            continue
        try:
            char = dos.read_character(path)
            bits = dos.neutral_class_bits(char)
        except Exception:  # noqa: BLE001
            continue
        raw = char.raw("class_levels")
        levels = {name: raw[n] for n, name in dos.CLASS_BY_SLOT.items()
                  if n < len(raw)}
        yield (f"{path.parent.name}/{path.name}", char.shape.title,
               bits_from_levels(levels), bits, char.get("char_class"))


def report(rows, port: str) -> int:
    seen: collections.Counter = collections.Counter()
    bad: collections.Counter = collections.Counter()
    unplaced: collections.Counter = collections.Counter()
    examples: dict[str, list[str]] = collections.defaultdict(list)
    for label, title, bits, stored_bits, code in rows:
        seen[title] += 1
        want = CODE_FOR_BITS.get(bits)
        if want is None:
            unplaced[title] += 1
            examples[title].append(
                f"{label}: level bits {bits:#04x} (stored mask "
                f"{stored_bits:#04x}) is in no table entry, code {code}")
            continue
        if want != code:
            bad[title] += 1
            examples[title].append(
                f"{label}: level bits {bits:#04x} (stored mask "
                f"{stored_bits:#04x}) wants code {want}, holds {code}")
    total = 0
    for title in sorted(seen):
        print(f"{port} {title}: {seen[title]} records, {bad[title]} "
              f"disagree, {unplaced[title]} with a bitmask the table has no "
              f"entry for")
        for line in examples[title][:20]:
            print(f"    {line}")
        total += bad[title]
    return total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--c64", action="append", default=[],
                    help="a directory or disk of C64 saves, repeatable")
    ap.add_argument("--dos", action="append", default=[],
                    help="a directory of DOS records, repeatable")
    ap.add_argument("--archives", action="store_true",
                    help="add ~/Downloads/fr-archives to the DOS roots")
    args = ap.parse_args(argv)
    c64 = [pathlib.Path(p).expanduser() for p in args.c64]
    dosr = [pathlib.Path(p).expanduser() for p in args.dos]
    if not c64 and not dosr:
        c64 = [pathlib.Path.home() / "wish-specimens" / "por-c64"]
        dosr = [pathlib.Path.home() / "wish-specimens" / "por-dos"]
    if args.archives:
        dosr.append(pathlib.Path.home() / "Downloads" / "fr-archives")
    bad = 0
    for root in c64:
        print(f"== C64: {root}")
        bad += report(c64_records(root), "C64")
    for root in dosr:
        print(f"== DOS: {root}")
        bad += report(dos_records(root), "DOS")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
