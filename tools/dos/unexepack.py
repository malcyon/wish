#!/usr/bin/env python3
"""Expand a Microsoft EXEPACK-compressed DOS executable to its load image.

    tools/dos/unexepack.py START.EXE START.img

DOS Pool of Radiance's `START.EXE` is EXEPACK-compressed: the entry stub
(`mov ax, es; add ax, 0x10 ... std; rep movsb`) copies the packed image to the
top of memory and expands it downwards, then walks a packed relocation table.
Reading the file as if it were the image works for the first few hundred
bytes and then drifts, which is why the Turbo Pascal overlay descriptors in
it looked unaligned and the data segment could not be found by file offset.

This writes the image `goldbox.exepack.unpack` expands, with **no relocation
applied**, so a `seg:off` the code uses is `seg * 16 + off` into the output.

Nothing here is game data; the output goes where you name it and stays out of the repository.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox.exepack import unpack  # noqa: E402

__all__ = ["unpack", "main"]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__.splitlines()[2].strip())
        return 2
    image, info = unpack(open(argv[0], "rb").read())
    open(argv[1], "wb").write(image)
    print(info)
    return 0


if __name__ == "__main__":
    sys.exit(main())
