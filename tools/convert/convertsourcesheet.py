#!/usr/bin/env python3
"""Print the source records' own sheet values, so the WinUAE screen has
something to be read against for step 4 of `#36 (Write an Amiga disk image,
not just the character files)`.

    .venv/bin/python tools/convert/convertsourcesheet.py SOURCE --disk por2.adf

SOURCE is a C64 disk image or a DOS saved game; `--disk` is the Amiga Pool of
Radiance disk 2 image the conversion is rehearsed against (nothing is written
to it, and it has no default). Runs the Amiga conversion's rehearsal on the
first slot and prints every field of every converted character.
`tools/convert/convertamigadisks.py` writes the disks these values are read against.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from editor import convert as convert_mod  # noqa: E402


def show(source_path, disk2):
    source = convert_mod.Source.detect(pathlib.Path(source_path))
    direction = next(d for d in convert_mod.destinations_for(source)
                     if d.destination_port == "amiga")
    r = direction.rehearse(source, "A", disk2)
    for c in r.party:
        keys = list(c.keys())
        print("---", c.get("name"))
        for f in keys:
            print("   {:<20} {}".format(f, c.get(f)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="a C64 disk image or a DOS saved game")
    ap.add_argument("--disk", required=True,
                    help="the Amiga Pool of Radiance disk 2 image")
    args = ap.parse_args(argv)
    show(args.source, args.disk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
