#!/usr/bin/env python3
"""Does the word `OUTDOORS` appear on any Curse or Silver Blades disk?

Written for `#205 (A party that walks out onto the travel grid leaves the
automapper's marker behind)`, whose plan needs this settled before the memory
fallback can be turned on for any title but Pool of Radiance: if the word
never reaches row 14 in either game, there is no status line to misread and
the file-level absence of `SQRDATA`/`SQRPACI` (`docs/121-silver-blades.md`)
closes the question without an emulator. If it turns up, a driven session is
what settles what it means there.

Searches every file on every side, in both encodings the word could be stored
in: PETSCII, which is what a `LDA #` string constant looks like in a PRG, and
C64 screen codes, which is what it would look like if it were baked into a
pre-rendered screen. Prints one line per hit, or says nothing was found.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import gamedisks  # noqa: E402

from goldbox import games  # noqa: E402
from goldbox.d64 import D64  # noqa: E402

WORD = "OUTDOORS"
#: PETSCII (upper/graphics mode): A-Z is the same as ASCII.
PETSCII = WORD.encode("ascii")
#: C64 screen codes: A-Z is 1-26, not 65-90.
SCREEN_CODE = bytes(ord(c) - 64 for c in WORD)

TITLES = {
    "curse-of-the-azure-bonds": games.CURSE_OF_THE_AZURE_BONDS,
    "secret-of-the-silver-blades": games.SECRET_OF_THE_SILVER_BLADES,
}


def search_disk(path: pathlib.Path) -> list[str]:
    """Every `(file, encoding)` pair that carries the word, in this image."""
    hits = []
    try:
        disk = D64.open(path)
    except Exception as exc:                          # a bad or short image
        return [f"{path.name}: could not open ({exc})"]
    for entry in disk.directory():
        try:
            data = disk.read_file(entry)
        except Exception as exc:
            hits.append(f"{path.name}/{entry.display_name}: unreadable ({exc})")
            continue
        if PETSCII in data:
            hits.append(f"{path.name}/{entry.display_name}: PETSCII")
        if SCREEN_CODE in data:
            hits.append(f"{path.name}/{entry.display_name}: screen code")
    return hits


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", choices=sorted(TITLES), action="append",
                        help="default: both Curse and Silver Blades")
    args = parser.parse_args(argv)
    wanted = args.title or sorted(TITLES)

    any_hit = False
    for key in wanted:
        root = gamedisks.find(key)
        if root is None:
            print(f"{key}: no disks found (set {gamedisks.entry(key).get('env')})")
            continue
        game = TITLES[key]
        # `disk_glob` is one pattern per title, e.g. "CURSE*.[dD]64".
        sides = sorted(root.glob(game.disk_glob))
        if not sides:
            print(f"{key}: {root} holds no disks matching {game.disk_glob!r}")
            continue
        for side in sides:
            hits = search_disk(side)
            for line in hits:
                print(line)
                any_hit = True
    if not any_hit:
        print(f"'{WORD}' found nowhere, in either encoding, on any side searched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
