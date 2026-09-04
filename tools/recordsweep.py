#!/usr/bin/env python3
"""Which files of a title touch one byte of the character record, and where.

`tools/trainerscan.py --refs` censuses one overlay against every record field.
This asks the opposite question: given a record offset whose meaning is in
dispute, which of the title's files reference it at all? That is what settles
an attribution taken from a single overlay -- a byte the trainer writes as the
dual-classed old class slot must be readable by whatever else cares about it,
and a byte nothing anywhere reads is a byte no routine has an opinion about.

The scan needs no load address. An absolute-mode operand carries the record's
own address (`$6B00` for Pool of Radiance, `$7C00` for Curse of the Azure Bonds
and Secret of the Silver Blades), so `LDA $6BB9` is the same three bytes
wherever the file runs; `--base` only changes the addresses printed beside the
hits, and without it the payload offset is printed instead.

    tools/recordsweep.py --game pool --offset 0xB9
    tools/recordsweep.py --game curse --offset 0xB9 --offset 0xBA --context

**A hit is a claim about bytes, not proof they are code** -- the caution
`tools/trainerscan.py` and `tools/d6502.py` both carry. A lone hit inside a
bitmap decodes exactly like a real instruction; a real routine's hits cluster
two or three instructions apart. `--context` disassembles either side of each
hit so the difference can be seen rather than assumed.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools.d6502 import M_ABS, M_ABX, M_ABY, T, lines  # noqa: E402
from tools.trainerscan import TITLES  # noqa: E402

#: How many bytes either side of a hit `--context` disassembles.
CONTEXT = 12


def sides(title: str, directory: str | None = None, pattern: str | None = None):
    """Every disk image of a title, in name order. Yields `(path, D64)`.

    `directory` and `pattern` are for a title `gamedisks.toml` has no entry
    for -- Champions of Krynn and the two after it -- so a question that has
    already been asked of three titles can be asked of the other three without
    a new table entry.
    """
    key, glob, _, _ = TITLES[title]
    if pattern:
        glob = pattern
    where = directory
    if where is None:
        where = gamedisks.find(key)
    if where is None:
        variable = gamedisks.entry(key).get(gamedisks.ENV, "?")
        raise SystemExit(f"recordsweep.py: no {key} disks here; set ${variable}")
    for path in sorted(pathlib.Path(where).expanduser().glob(glob)):
        try:
            yield path, D64.open(str(path))
        except Exception:
            continue                     # not every image in a set is readable


def hits(data: bytes, want: set[int]):
    """Every absolute-mode instruction whose operand is one of `want`.

    Yields `(payload offset, mnemonic, suffix, operand)`.
    """
    suffix = {M_ABS: "", M_ABX: ",X", M_ABY: ",Y"}
    for i in range(len(data) - 2):
        op = data[i]
        if op not in T:
            continue
        mnemonic, mode = T[op]
        if mode not in suffix:
            continue
        target = data[i + 1] | data[i + 2] << 8
        if target in want:
            yield i, mnemonic, suffix[mode], target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default="pool", choices=sorted(TITLES))
    ap.add_argument("--offset", action="append", required=True,
                    help="record offset, hex; repeatable")
    ap.add_argument("--base", help="where the file runs, hex; default per title")
    ap.add_argument("--record", help="the record's address, hex")
    ap.add_argument("--context", action="store_true",
                    help="disassemble either side of each hit")
    ap.add_argument("--dir", help="a directory of disk images, for a title "
                                  "gamedisks.toml has no entry for")
    ap.add_argument("--glob", help="which images in it, e.g. '*.d64'")
    args = ap.parse_args(argv)

    _, _, base, record = TITLES[args.game]
    if args.base:
        base = int(args.base.lstrip("$"), 16)
    if args.record:
        record = int(args.record.lstrip("$"), 16)
    want = {record + int(o.lstrip("$"), 16) for o in args.offset}
    print(f"{args.game}: record at ${record:04X}, looking for "
          + " ".join(f"${a:04X}" for a in sorted(want)))

    seen = set()
    total = 0
    for path, disk in sides(args.game, args.dir, args.glob):
        for entry in disk.directory():
            if not entry.is_prg:
                continue
            name = entry.name.decode("latin-1").rstrip()
            try:
                payload = split_load_address(disk.read_file(entry))[1]
            except Exception:
                continue                 # a broken chain is not a candidate
            key = (name, len(payload), payload[:64])
            if key in seen:
                continue                 # the same file on the other side
            seen.add(key)
            found = list(hits(payload, want))
            if not found:
                continue
            print(f"\n{path.name}:{name}  {len(payload)} bytes")
            for at, mnemonic, sfx, target in found:
                print(f"  +0x{at:04X} (${base + at:04X})  "
                      f"{mnemonic}{sfx} ${target:04X}")
                total += 1
                if args.context:
                    start = max(0, at - CONTEXT)
                    for line in lines(payload, base, base + start, 12):
                        print("      " + line)
    # The sample size is part of the claim: "nothing references it" means
    # nothing in *these* files, and a negative is worth only as many files as
    # were actually opened.
    print(f"\n{total} reference(s) in {len(seen)} distinct files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
