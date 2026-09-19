#!/usr/bin/env python3
"""Every C64 monster name on the three titles' disks, run through one labelling rule.

Kept from `#345 (Draw a letter in each combat-map square saying what is standing
there, instead of the index the backend counts with)`. The rule being tried is
Donald's: a monster's label is the first letter of each whitespace-separated
word of its name, no capital forced. For each title this reads the name out of
every `MON*` file on its disks, then prints how many files and distinct names
there are, how long the labels come out, the eight longest, the names with a
hyphen, apostrophe or full stop in them, and every label that two or more
different names share.

    tools/c64/c64monsterlabelcensus.py [--pool DIR] [--curse DIR] [--ssb DIR]

Each directory defaults to the title's entry in `automap/gamedisks.py` (so
`$POR_DISKS`, `$COAB_DISKS` and `$SSB_DISKS` win). For Pool of Radiance the
unmodified `POOL1.D64.orig` is used when it sits beside the disks, otherwise
`POOL1.D64`. Disks are opened read only; a title with no directory is reported
missing and skipped.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap import gamedisks  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402


def label(name):
    """First letter of each whitespace-separated word, no cap."""
    return "".join(w[0] for w in name.split() if w)


def pool_disks(folder: pathlib.Path):
    first = folder / "POOL1.D64.orig"
    return ([first if first.exists() else folder / "POOL1.D64"]
            + [folder / f"POOL{n}.D64" for n in range(2, 9)])


def glob_disks(folder: pathlib.Path, stem: str):
    return sorted(set(folder.glob(f"{stem}*.D64")) | set(folder.glob(f"{stem}*.d64")))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pool", type=pathlib.Path,
                        help="Pool of Radiance disks directory")
    parser.add_argument("--curse", type=pathlib.Path,
                        help="Curse of the Azure Bonds disks directory")
    parser.add_argument("--ssb", type=pathlib.Path,
                        help="Secret of the Silver Blades disks directory")
    args = parser.parse_args(argv)

    folders = {
        "Pool": args.pool or gamedisks.find("pool-of-radiance"),
        "Curse": args.curse or gamedisks.find("curse-of-the-azure-bonds"),
        "SSB": args.ssb or gamedisks.find("secret-of-the-silver-blades"),
    }
    titles = {}
    for title, folder in folders.items():
        if folder is None:
            print("missing disks for", title)
            titles[title] = []
        elif title == "Pool":
            titles[title] = pool_disks(folder)
        else:
            titles[title] = glob_disks(folder, "CURSE" if title == "Curse"
                                       else "SILVER")

    for title, disks in titles.items():
        names = {}
        for disk in disks:
            if not disk.exists():
                print("missing", disk.name)
                continue
            img = D64.open(str(disk))
            for e in img.directory():
                fn = bytes(e.name)
                if not fn.startswith(b"MON") or not e.is_prg:
                    continue
                _, p = split_load_address(img.read_file(e))
                nm = p[:20].split(b"\0")[0].decode("latin-1").strip()
                names.setdefault(fn.decode(), nm)
        labs = collections.defaultdict(set)
        for fn, nm in names.items():
            labs[label(nm)].add(nm)
        lens = collections.Counter(len(lb) for lb in labs)
        print(f"\n== {title}: {len(names)} MON files, "
              f"{len(set(names.values()))} distinct names, {len(labs)} "
              f"distinct labels; label lengths {dict(sorted(lens.items()))}")
        longest = sorted(labs, key=len, reverse=True)[:8]
        print("  longest:", [(lb, sorted(labs[lb])) for lb in longest])
        print("  hyphen/odd:", sorted({nm for nm in names.values()
                                       if "-" in nm or "'" in nm or "." in nm}))
        shared = {lb: sorted(v) for lb, v in labs.items() if len(v) > 1}
        print(f"  {len(shared)} labels shared by more than one distinct name:")
        for lb, v in sorted(shared.items()):
            print(f"    {lb:4s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
