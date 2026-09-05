#!/usr/bin/env python3
"""List, unpack and render the blocks of a DOS Gold Box `.DAX` container.

`goldbox.dos_savegame` decodes the container -- a `u16le` index size, nine
bytes an entry (`id:u8 offset:u32le raw:u16le packed:u16le`), then the
run-length coded blocks -- and the tools that need one block each reach
into it.  This is the command-line form: the index of any `.DAX`, one
block's bytes to a file, or an image block drawn as a PNG, so that the next
question about a container starts from a listing rather than from a hex
dump.

    tools/daxls.py CBODY.DAX                  # the index: id, sizes, image header
    tools/daxls.py CBODY.DAX --dump 64 work/issue130/cbody-64.bin
    tools/daxls.py CHEAD.DAX --png 3 work/issue130/chead-3.png --scale 8

An *image* block, which is what `HEAD*`, `BODY*`, `CHEAD`, `CBODY`, `CPIC*`,
`ICON` and `COMSPR` hold, is a 17-byte header and then 4-bit pixels: byte 0
the row count, byte 2 the width in eights, bytes 8-16 nine bytes that are
the same across a file and unread here, and `17 + rows * width_in_eights * 4`
the block's whole length.  `--png` reads the 4-bit values as EGA indices
straight off the block, which is what the sheet portraits are; for a combat
figure the values are part numbers and `tools/iconproposal.py` recolours
them the way the engine does (`docs/168-dos-dax-and-combat-icons.md`).

Anything written goes where the command names, and the game's bytes belong
under `work/`.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.dos_savegame import (  # noqa: E402
    DAX_ENTRY,
    DaxError,
    dax_block,
    dax_index,
    dax_unpack,
)

IMAGE_HEADER = 17
EGA = ("#000000", "#0000AA", "#00AA00", "#00AAAA", "#AA0000", "#AA00AA",
       "#AA5500", "#AAAAAA", "#555555", "#5555FF", "#55FF55", "#55FFFF",
       "#FF5555", "#FF55FF", "#FFFF55", "#FFFFFF")


def image_shape(block: bytes) -> tuple[int, int] | None:
    """`(rows, width)` in pixels if the block is an image block, else None.

    The test is the one every image block in the game passes: its length is
    exactly the header plus `rows * width_in_eights * 4`.
    """
    if len(block) < IMAGE_HEADER:
        return None
    rows, eights = block[0], block[2]
    if rows and eights and len(block) == IMAGE_HEADER + rows * eights * 4:
        return rows, eights * 8
    return None


def pixels(block: bytes) -> list[list[int]]:
    """An image block's 4-bit values, `[y][x]`, high nibble first."""
    shape = image_shape(block)
    if shape is None:
        raise DaxError("not an image block")
    rows, width = shape
    stride = width // 2
    out = []
    for y in range(rows):
        row = block[IMAGE_HEADER + y * stride:IMAGE_HEADER + (y + 1) * stride]
        out.append([v for b in row for v in (b >> 4, b & 0x0F)])
    return out


def listing(data: bytes, name: str) -> list[str]:
    """One line per block: id, offset, packed and raw sizes, image shape."""
    index = dax_index(data, name)
    base = 2 + struct.unpack_from("<H", data, 0)[0]
    lines = [f"{name}: {len(data)} bytes, {len(index)} blocks, "
             f"index {len(index) * DAX_ENTRY} bytes, data from {base}"]
    for bid, off, raw, packed in index:
        try:
            block = dax_unpack(data[base + off:base + off + packed], raw)
            shape = image_shape(block)
            extra = (f"image {shape[1]}x{shape[0]}  header "
                     f"{block[8:IMAGE_HEADER].hex(' ')}" if shape else "")
        except DaxError as e:
            extra = f"unpack failed: {e}"
        lines.append(f"  id {bid:3}  at {base + off:6}  packed {packed:5}  "
                     f"raw {raw:5}  {extra}")
    return lines


def write_png(block: bytes, path: pathlib.Path, scale: int) -> None:
    from PIL import Image

    grid = pixels(block)
    image = Image.new("RGB", (len(grid[0]), len(grid)))
    image.putdata([tuple(int(EGA[v][i:i + 2], 16) for i in (1, 3, 5))
                   for row in grid for v in row])
    if scale > 1:
        image = image.resize((image.width * scale, image.height * scale),
                             Image.NEAREST)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dax", help="a .DAX file")
    ap.add_argument("--dump", nargs=2, metavar=("ID", "PATH"),
                    help="write one unpacked block to PATH")
    ap.add_argument("--png", nargs=2, metavar=("ID", "PATH"),
                    help="draw one image block to PATH")
    ap.add_argument("--scale", type=int, default=4)
    args = ap.parse_args(argv)
    path = pathlib.Path(args.dax)
    data = path.read_bytes()
    try:
        if args.dump:
            block = dax_block(data, int(args.dump[0]), path.name)
            out = pathlib.Path(args.dump[1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(block)
            print(f"{out}  {len(block)} bytes")
        elif args.png:
            block = dax_block(data, int(args.png[0]), path.name)
            write_png(block, pathlib.Path(args.png[1]), args.scale)
            print(args.png[1])
        else:
            print("\n".join(listing(data, path.name)))
    except DaxError as e:
        raise SystemExit(str(e))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
