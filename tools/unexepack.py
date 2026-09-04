#!/usr/bin/env python3
"""Expand a Microsoft EXEPACK-compressed DOS executable to its load image.

    tools/unexepack.py START.EXE work/START.img

DOS Pool of Radiance's `START.EXE` is EXEPACK-compressed: the entry stub
(`mov ax, es; add ax, 0x10 ... std; rep movsb`) copies the packed image to the
top of memory and expands it downwards, then walks a packed relocation table.
Reading the file as if it were the image works for the first few hundred
bytes and then drifts, which is why the Turbo Pascal overlay descriptors in
it looked unaligned and the data segment could not be found by file offset.

This writes the expanded image with **no relocation applied**, so a `seg:off`
the code uses is `seg * 16 + off` into the output -- the same numbering
`GAME.OVR`'s far calls and the overlay descriptors carry.  The format is the
documented one: commands read backwards from the end of the packed data,
`0xB0`/`0xB1` fill a byte, `0xB2`/`0xB3` copy a run, bit 0 marks the last.

Nothing here is game data; the output goes under `work/` and stays there.
"""

from __future__ import annotations

import struct
import sys


def unpack(exe: bytes) -> tuple[bytes, dict]:
    """The expanded image and the EXEPACK header's fields."""
    header_paras = struct.unpack_from("<H", exe, 8)[0]
    cs = struct.unpack_from("<H", exe, 0x16)[0]
    base = header_paras * 16
    stub = base + cs * 16
    (real_ip, real_cs, _mem_start, _exepack_size, real_sp, real_ss,
     dest_len, _skip_len, sig) = struct.unpack_from("<HHHHHHHH2s", exe, stub)
    if sig != b"RB":
        raise ValueError(f"not an EXEPACK executable: signature {sig!r}")

    packed = exe[base:stub]
    p = len(packed)
    while p > 0 and packed[p - 1] == 0xFF:
        p -= 1
    out = bytearray(dest_len * 16)
    dst = len(out)
    while True:
        cmd = packed[p - 1]
        p -= 1
        length = packed[p - 2] | (packed[p - 1] << 8)
        p -= 2
        if cmd & 0xFE == 0xB0:
            fill = packed[p - 1]
            p -= 1
            out[dst - length:dst] = bytes((fill,)) * length
        elif cmd & 0xFE == 0xB2:
            out[dst - length:dst] = packed[p - length:p]
            p -= length
        else:
            raise ValueError(f"bad EXEPACK command {cmd:02x} at {p}")
        dst -= length
        if cmd & 1:
            break
    # Whatever lies below the last command is stored uncompressed.
    out[:dst] = packed[:dst]
    info = dict(real_cs=real_cs, real_ip=real_ip, real_ss=real_ss, real_sp=real_sp,
                dest_len=dest_len, image=len(out), plain_prefix=dst)
    return bytes(out), info


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
