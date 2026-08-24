"""Write a C64 party into Amiga Pools of Darkness as `Save/NAME.pc` files.

    tools/toamiga.py PORSAVE.D64 -o work/pod-save/SAVE

One file per character, 484 bytes each, ready to be dropped into the `Save`
drawer of a Pools of Darkness disk 3 and picked up with
`Add Character -> Pools`. The C64 disk is opened read-only.

The conversion goes through `por/neutral.py`'s `NeutralCharacter`, so it reads a
save of any of the six C64 titles whose race and class tables the project
knows. What cannot cross is printed rather than dropped quietly --
`--quiet` prints only the file names, `--verbose` prints the byte-by-byte
provenance.

`docs/124-amiga-port.md` has the measurements the writer rests on.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from por.amiga import ConversionError, export_party  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="toamiga",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("save", help="a C64 save disk (.D64)")
    ap.add_argument("-o", "--out", required=True,
                    help="the directory the .pc files are written to")
    ap.add_argument("--game-disk", default=None,
                    help="a game disk, only used to name items in the report")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="print the file names and nothing else")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="also print where every byte of each record came "
                         "from")
    args = ap.parse_args(argv)

    try:
        written = export_party(args.save, args.out, args.game_disk)
    except ConversionError as exc:
        print(f"toamiga: {exc}", file=sys.stderr)
        return 2

    for path, rep in written:
        print(path)
        if args.quiet:
            continue
        print("   ", rep.summary().replace("\n", "\n    "))
        if args.verbose:
            for offset in sorted(rep.sources):
                print(f"    {offset:#05x}  {rep.sources[offset]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
