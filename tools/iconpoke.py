#!/usr/bin/env python3
"""Give every character on a save disk a different combat figure, for a run.

A measurement instrument, not a feature.  `#184 (A converted combat icon's
colours are proven in the game and its shapes are not)` needs a party whose
six icons are **deliberately different**, because a party of six identical
ones cannot tell "the engine drew each character's own shape" apart from "the
engine drew the same shape six times".  The conversion writes one composed
default into all six slots today, which is
`#130 (A converted DOS party arrives with six identical combat figures, not
its own)`, so the party has to be made by hand.

    tools/iconpoke.py --disk work/issue184/SIX.D64

Every icon it writes is one the game's own ICON menu can reach:
`IconParts.compose` applies a weapon option and then a head option out of
`SPELLE64`/`SPELLN64` on the player's disks, which is what character creation
does.  Nothing is invented and nothing is stored here -- the part tables are
read off the disks at run time.

The disk is edited **in place**, so point it at a copy under `work/`.  It
refuses a directory it was not given, refuses to write two slots the same
shape, and prints the eighteen screen codes it left in each slot so the run
that follows has the file's side of the comparison in its log.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.iconparts import (  # noqa: E402
    DEFAULT_BACKGROUND,
    DEFAULT_PART_COLOURS,
    MULTICOLOUR,
    IconParts,
)
from goldbox.icons import ICON_SIZE, ICON_TABLE_BASE  # noqa: E402
from goldbox.savegame import (  # noqa: E402
    SAVE0_LOAD_ADDRESS,
    SaveGame0,
    load_save,
    store_save,
)

#: Where the player keeps the C64 game disks.  Read only.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: Six figures a person can tell apart on a 24x24 grid: the size, then the
#: weapon and head option numbers `IconParts.compose` takes.  Chosen for
#: distance rather than meaning -- what matters is that no two of the eighteen
#: screen codes agree, which `main` checks rather than assumes.
FIGURES = [
    ("large", 0, 0),
    ("large", 7, 4),
    ("large", 11, 9),
    ("small", 3, 2),
    ("small", 16, 7),
    ("large", 21, 12),
]


def compose(parts: IconParts, size: str, weapon: int, head: int) -> bytes:
    """One 36-byte icon: eighteen screen codes and eighteen colours.

    The colours are `DEFAULT_PART_COLOURS`, the game's own creation answer,
    so a poked party's colour half is the colour half a converted party has
    and the two runs stay comparable.
    """
    shape = parts.compose(size, weapon, head)
    seed = bytes([DEFAULT_BACKGROUND | MULTICOLOUR] * len(shape))
    return shape + parts.colours_for(shape, DEFAULT_PART_COLOURS, seed)


def parts_from(disks: pathlib.Path) -> IconParts:
    """The icon option tables, off whichever side carries them."""
    for path in sorted(disks.glob("*.[dD]64")):
        try:
            return IconParts.load(str(path))
        except Exception:
            continue
    raise SystemExit(f"no SPELLE64/SPELLN64 on any disk in {disks}")


def poke(disk: pathlib.Path, disks: pathlib.Path,
         figures=FIGURES) -> list[tuple[int, bytes]]:
    """Write one figure per occupied slot.  Returns what it wrote."""
    parts = parts_from(disks)
    image = D64(disk.read_bytes())
    game, sg0, sg1 = load_save(image)
    payload = bytearray(sg0.to_bytes())
    written: list[tuple[int, bytes]] = []
    used: set[bytes] = set()
    n = 0
    for slot in range(8):
        if not sg0.slot(slot).occupied:
            continue
        if n >= len(figures):
            break
        icon = compose(parts, *figures[n])
        if icon[:18] in used:
            raise SystemExit(f"figure {figures[n]} composes the same eighteen "
                             f"codes as one already written; pick another")
        used.add(icon[:18])
        base = ICON_TABLE_BASE - SAVE0_LOAD_ADDRESS + slot * ICON_SIZE
        payload[base:base + ICON_SIZE] = icon
        written.append((slot, icon))
        n += 1
    store_save(image, SaveGame0.from_bytes(bytes(payload), game), sg1, game)
    disk.write_bytes(image.data)
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True,
                   help="the save .d64 to edit in place; keep it under work/")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's game disks are; read, never written")
    args = p.parse_args(argv)
    disk = pathlib.Path(args.disk)
    for slot, icon in poke(disk, pathlib.Path(args.disks)):
        print(f"slot {slot}: {icon[:18].hex()} / {icon[18:].hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
