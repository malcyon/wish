#!/usr/bin/env python3
"""Map DOS Pool of Radiance's overlay units, resolve far calls, and read code.

    tools/dosovrmap.py units      GAME.OVR START.img
    tools/dosovrmap.py resolve    GAME.OVR START.img B0:52
    tools/dosovrmap.py dis        GAME.OVR START.img 0x23DCC 0x240C0
    tools/dosovrmap.py callers    GAME.OVR START.img 0x2BD3C [--back 60]

`START.img` is `START.EXE` expanded by `tools/unexepack.py`; the overlay
descriptors only line up on paragraph boundaries in the expanded image.
Each descriptor is `CD 3F 00 00`, a `u32` file offset into `GAME.OVR`, the
code size, the fixup size, the entry count, then from `+0x20` one five-byte
`CD 3F <u16 code offset> 00` stub per public entry.  The descriptor's
paragraph *is* the segment a far call names, so `lcall seg:off` resolves to
a unit and a code offset, and from there to a file offset in `GAME.OVR`.

`units` prints the map.  `resolve` turns one `seg:off` into a file offset --
into `GAME.OVR` for an overlay entry, into the image for resident code.
`dis` disassembles a range of `GAME.OVR` from the nearest preceding Turbo
Pascal prologue (`55 89 E5`).  `callers` finds every near (`E8`) and far
(`9A`) call to a `GAME.OVR` routine and prints the argument pushes before
each, which is how `docs/162-spc-permanence.md`'s call-site table was read.

Prints addresses and short instruction windows and nothing else; the game's
bytes stay in the player's own directory.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys

import capstone

PROLOGUE = b"\x55\x89\xe5"
ARG_OPS = ("push", "mov", "xor", "les", "lcall", "call", "add", "sub", "shl",
           "cbw", "cwde", "inc", "dec", "mul", "imul")


def units(image: bytes, ovr_len: int) -> list[dict]:
    out = []
    for m in re.finditer(rb"\xcd\x3f\x00\x00", image):
        p = m.start()
        if p % 16:
            continue
        fo, code, fix, nent = struct.unpack_from("<IHHH", image, p + 4)
        if not (0 < fo < ovr_len and 0 < code < 0x10000 and 0 < nent < 400):
            continue
        ents = []
        q = p + 0x20
        for _ in range(nent):
            if image[q:q + 2] != b"\xcd\x3f":
                break
            ents.append((q - p, struct.unpack_from("<H", image, q + 2)[0]))
            q += 5
        out.append(dict(seg=p // 16, fileoff=fo, code=code, fix=fix, ents=ents))
    return out


def unit_of(umap: list[dict], fileoff: int) -> dict | None:
    for u in umap:
        if u["fileoff"] <= fileoff < u["fileoff"] + u["code"]:
            return u
    return None


def resolve(umap: list[dict], seg: int, off: int) -> tuple[str, int | None]:
    for u in umap:
        if u["seg"] == seg:
            for stub, code in u["ents"]:
                if stub == off:
                    return "GAME.OVR", u["fileoff"] + code
            return "GAME.OVR", None
    return "START.img", seg * 16 + off


def disasm(data: bytes, start: int, end: int):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    return md.disasm(data[start:end], start)


def window(data: bytes, site: int, back: int, fwd: int = 5):
    """Instructions ending exactly at `site`, found by trying start points."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    for st in range(site - back, site):
        ins = list(md.disasm(data[st:site + fwd], st))
        if ins and any(i.address == site for i in ins):
            return [i for i in ins if i.address <= site]
    return []


def cmd_units(a, ovr, img):
    for u in units(img, len(ovr)):
        print(f"seg {u['seg']:04X} GAME.OVR {u['fileoff']:06X}+{u['code']:04X} "
              f"fixups {u['fix']:04X} entries {len(u['ents'])}")


def cmd_resolve(a, ovr, img):
    seg, off = (int(x, 16) for x in a.target.split(":"))
    src, at = resolve(units(img, len(ovr)), seg, off)
    print(src, f"{at:06X}" if at is not None else "no such entry")


def cmd_dis(a, ovr, img):
    start, end = int(a.start, 0), int(a.end, 0)
    p = ovr.rfind(PROLOGUE, 0, start + 1)
    if p < 0 or start - p > 0x600:
        p = start
    for i in disasm(ovr, p, end):
        print(f"{i.address:06x} {i.bytes.hex():16s} {i.mnemonic} {i.op_str}")


def cmd_callers(a, ovr, img):
    target = int(a.target, 0)
    umap = units(img, len(ovr))
    sites = [p for p in range(len(ovr) - 3)
             if ovr[p] == 0xE8
             and p + 3 + int.from_bytes(ovr[p + 1:p + 3], "little", signed=True) == target]
    kinds = {s: "near" for s in sites}
    u = unit_of(umap, target)
    if u is not None:
        for stub, code in u["ents"]:
            if code == target - u["fileoff"]:
                pat = b"\x9a" + struct.pack("<HH", stub, u["seg"])
                for m in re.finditer(re.escape(pat), ovr):
                    kinds[m.start()] = f"far {u['seg']:X}:{stub:X}"
    for s in sorted(kinds):
        print(f"=== {s:06X} ({kinds[s]})")
        for i in window(ovr, s, a.back):
            if i.mnemonic in ARG_OPS and not (i.mnemonic == "push" and i.op_str == "cs"):
                print(f"   {i.address:06x} {i.mnemonic} {i.op_str}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("cmd", choices=("units", "resolve", "dis", "callers"))
    ap.add_argument("ovr", help="GAME.OVR")
    ap.add_argument("img", help="START.EXE expanded by tools/unexepack.py")
    ap.add_argument("target", nargs="?", help="SEG:OFF for resolve, a file offset for callers")
    ap.add_argument("start", nargs="?", help="dis: first file offset")
    ap.add_argument("end", nargs="?", help="dis: last file offset")
    ap.add_argument("--back", type=int, default=60, help="callers: bytes of window before the call")
    a = ap.parse_args(argv)
    if a.cmd == "dis":
        a.start, a.end = a.target, a.start
    ovr = open(a.ovr, "rb").read()
    img = open(a.img, "rb").read()
    {"units": cmd_units, "resolve": cmd_resolve, "dis": cmd_dis, "callers": cmd_callers}[a.cmd](a, ovr, img)
    return 0


if __name__ == "__main__":
    sys.exit(main())
