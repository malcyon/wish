"""DOS executables as the loader would lay them out: EXEPACK expanded, or the
plain image after the MZ header.

The DOS Gold Box launchers are Microsoft EXEPACK-compressed: the entry stub
copies the packed image to the top of memory and expands it downwards, then
walks a packed relocation table. `unpack` expands it with **no relocation
applied**, so a `seg:off` the code uses is `seg * 16 + off` into the output --
the same numbering `GAME.OVR`'s far calls and the overlay descriptors carry.
The format is the documented one: commands read backwards from the end of the
packed data, `0xB0`/`0xB1` fill a byte, `0xB2`/`0xB3` copy a run, bit 0 marks
the last.
"""

from __future__ import annotations

import struct


def unpack(exe: bytes) -> tuple[bytes, dict]:
    """The expanded image and the EXEPACK header's fields.

    Raises `ValueError` for an executable that is not EXEPACK-compressed.
    """
    if len(exe) < 0x1C or exe[:2] not in (b"MZ", b"ZM"):
        raise ValueError("not a DOS executable: no MZ header")
    header_paras = struct.unpack_from("<H", exe, 8)[0]
    cs = struct.unpack_from("<H", exe, 0x16)[0]
    base = header_paras * 16
    stub = base + cs * 16
    if stub + 18 > len(exe):
        raise ValueError("not an EXEPACK executable: the entry is past the file")
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
        if p < 3:
            raise ValueError("EXEPACK data ends before its last command")
        cmd = packed[p - 1]
        p -= 1
        length = packed[p - 2] | (packed[p - 1] << 8)
        p -= 2
        if length > dst:
            raise ValueError(f"EXEPACK command {cmd:02x} writes before the image")
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


def load_image(exe: bytes) -> tuple[bytes, int]:
    """`(image, entry)`: the load image and the entry point's offset in it.

    EXEPACK is expanded; any other MZ executable is its bytes after the
    header. `entry` is the unrelocated `cs * 16 + ip`.
    """
    try:
        image, info = unpack(exe)
    except ValueError:
        if len(exe) < 0x1C or exe[:2] not in (b"MZ", b"ZM"):
            raise ValueError("not a DOS executable: no MZ header") from None
        header = struct.unpack_from("<H", exe, 8)[0] * 16
        ip, cs = struct.unpack_from("<HH", exe, 0x14)
        return exe[header:], cs * 16 + ip
    return image, info["real_cs"] * 16 + info["real_ip"]


def data_segment(image: bytes, entry: int) -> int:
    """The paragraph a Turbo Pascal program loads into `DS` at start-up.

    The entry point's first instruction is a far call to `System`'s
    initialisation, which opens `mov dx, seg DATA / mov ds, dx`.
    """
    if image[entry:entry + 1] != b"\x9A":
        raise ValueError(f"no far call at the entry point {entry:#x}")
    off, seg = struct.unpack_from("<HH", image, entry + 1)
    at = seg * 16 + off
    if image[at:at + 1] != b"\xBA" or image[at + 3:at + 5] != b"\x8E\xDA":
        raise ValueError(f"no `mov dx, seg / mov ds, dx` at {at:#x}")
    return struct.unpack_from("<H", image, at + 1)[0]
