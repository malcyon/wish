"""The Amiga Pools of Darkness combat figure, as its ICON screen draws it.

The art is the tile system Curse and Silver Blades use
(:mod:`goldbox.amiga_later_icons`), on a 32-colour screen: every figure tile
has a mask plane and five colour planes, and the recolour table maps the
sixteen DOS part values onto sixteen of the 32 palette entries.  What this
module adds is where the files are and what the ICON screen draws around
the figure.  Everything is read from the player's own disks at run time;
nothing of the game's art, colours or tables is held here.

* `Disk3/CHEAD.TLB` and `Disk3/CBODY.TLB` on disk 3: the heads and bodies;
* `DISK1/COMSPR.TLB` on disk 1: art 15 and 16, the boxes behind the ready
  and the action pose;
* `DISK1/ALWAYS.TLB` on disk 1: block 0, the 32 colours the ICON screen
  shows;
* `/Pools of Darkness` on disk 1: the recolour tables
  (:func:`goldbox.amiga_later_icons.recolour_tables`).  One release carries
  it crunched; :func:`goldbox.stonecracker.as_loaded` unpacks it.

Addresses are file offsets in the English `/Pools of Darkness`.
`docs/199-amiga-combat-icons.md`, "Pools of Darkness", is the write-up.
"""

from __future__ import annotations

from . import amiga_later_icons as later
from . import stonecracker

#: The key :func:`read_art` and :func:`disk_files` use for the title.
TITLE = "pools-of-darkness"

#: The executable in disk 1's root, and the drawers of disk 1 and disk 3
#: that hold the figure files.
EXECUTABLE_NAME = "Pools of Darkness"
DRAWERS = ("DISK1", "DISK3")

#: The boxes, `COMSPR.TLB` art ids.  Start-up loads art `n - 15` into figure
#: slot `n` for slots 15 to 36 (`0x1DB54`-`0x1DBAA`), and the ICON screen's
#: draw routine (`0x0C81C`) draws slot 30's ready pose behind the ready
#: figure and slot 31's ready pose behind the action figure: art 15 and 16.
FRAME_IDS = (15, 16)

#: The `ALWAYS.TLB` block the ICON screen shows.  Start-up opens `always`
#: as library 0 and installs its block 0 (`0x1D8F2`-`0x1D904`); the ICON
#: screen clears the current picture (`0x0D27E` calls `0x1C5A6` with none),
#: and with no picture the palette flush installs library 0's block 0 whole
#: (`0x1C610`, `0x1C6C4`).
PALETTE_BLOCK = 0

#: The top-left pixel of the ready and the action pose on the 320x200
#: screen: the ICON screen draws one row, at cells (1, 2) and (4, 2)
#: (`0x0C81C` called with 1 and 2), and a cell's word is
#: `0x1F44 + 12 * cell` (`0x36F5A`), a pixel `2 * (word - 0x1F40)`
#: (`0x4A38A`).  `tools/icons/amigapodicons.py --capture` checks a capture
#: against the distance between them.
PLACES = ((32, 56), (104, 56))


def frames(comspr: dict[int, later.Tile]) -> tuple[later.Tile, later.Tile]:
    """The boxes behind the ready and the action pose, from `COMSPR.TLB`."""
    missing = [a for a in FRAME_IDS if a not in comspr]
    if missing:
        raise later.LaterArtError(f"{later.FRAME_FILE} holds no art "
                                  f"{', '.join(map(str, missing))}")
    return comspr[FRAME_IDS[0]], comspr[FRAME_IDS[1]]


def icon_palette(always: bytes) -> tuple[tuple[int, int, int], ...]:
    """The 32 colours the ICON screen shows: `ALWAYS.TLB` block 0."""
    blocks = later.library(always, later.PALETTE_FILE)
    if PALETTE_BLOCK not in blocks:
        raise later.LaterArtError(f"{later.PALETTE_FILE} holds no block "
                                  f"{PALETTE_BLOCK}")
    palette = later.palette_block(blocks[PALETTE_BLOCK],
                                  f"{later.PALETTE_FILE} block "
                                  f"{PALETTE_BLOCK}")
    if len(palette) != later.DEEP_COLOURS:
        raise later.LaterArtError(f"{later.PALETTE_FILE} block "
                                  f"{PALETTE_BLOCK} holds {len(palette)} "
                                  f"colours, not {later.DEEP_COLOURS}")
    return palette


def read_art(files: dict[str, bytes]) -> later.LaterArt:
    """The figure art, boxes, colours and recolour tables from the five
    files :func:`disk_files` gathers.

    The block loader (`0x36D12`) adds 64 to an option for size 2, gives a
    body's action pose art `+ 128`, and loads the same head art into both
    poses; it has no load table.  The recolour builder (`0x255EA`) works
    over all 32 entries.
    """
    missing = [k for k in (later.HEAD_FILE, later.BODY_FILE,
                           later.FRAME_FILE, later.PALETTE_FILE,
                           later.EXECUTABLE) if k not in files]
    if missing:
        raise later.LaterArtMissing(f"no {', '.join(missing)} to draw a "
                                    f"figure from")
    try:
        executable = stonecracker.as_loaded(files[later.EXECUTABLE])
    except stonecracker.StoneCrackerError as exc:
        raise later.LaterArtError(f"the executable cannot be unpacked: "
                                  f"{exc}") from exc
    entry, parts = later.recolour_tables(executable, later.DEEP_COLOURS)
    return later.LaterArt(
        TITLE, later.read_tiles(files[later.HEAD_FILE], later.HEAD_FILE),
        later.read_tiles(files[later.BODY_FILE], later.BODY_FILE),
        frames(later.read_tiles(files[later.FRAME_FILE], later.FRAME_FILE)),
        icon_palette(files[later.PALETTE_FILE]), entry, parts,
        bytes(range(later.DEEP_COLOURS)), later.DEEP_COLOURS, 0)


def disk_files(disks) -> dict[str, bytes]:
    """The files the figure needs, off opened `AmigaDisk`s.

    Disk 1 has `/Pools of Darkness` in its root and `COMSPR.TLB` and
    `ALWAYS.TLB` in its `DISK1` drawer; disk 3 has `CHEAD.TLB` and
    `CBODY.TLB` in its `Disk3` drawer, in either case.  Raises
    :class:`goldbox.amiga_later_icons.LaterArtMissing` when a file is not
    found.
    """
    first, third = DRAWERS
    found: dict[str, bytes] = {}
    for disk in disks:
        names = {path.strip("/").upper(): path for path, _ in disk.walk()}
        if later.EXECUTABLE not in found:
            wanted = {later.EXECUTABLE: EXECUTABLE_NAME.upper(),
                      later.FRAME_FILE: f"{first}/{later.FRAME_FILE}",
                      later.PALETTE_FILE: f"{first}/{later.PALETTE_FILE}"}
            if all(v in names for v in wanted.values()):
                found.update({k: disk.read_file(names[v])
                              for k, v in wanted.items()})
        if later.HEAD_FILE not in found:
            wanted = {k: f"{third}/{k}"
                      for k in (later.HEAD_FILE, later.BODY_FILE)}
            if all(v in names for v in wanted.values()):
                found.update({k: disk.read_file(names[v])
                              for k, v in wanted.items()})
    missing = [k for k in (later.EXECUTABLE, later.FRAME_FILE,
                           later.PALETTE_FILE, later.HEAD_FILE,
                           later.BODY_FILE) if k not in found]
    if missing:
        raise later.LaterArtMissing(f"no {', '.join(missing)} on these disks")
    return found
