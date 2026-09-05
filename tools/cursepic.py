#!/usr/bin/env python3
"""Decode a Curse `PIC` file's animation frames, and say which one a save holds.

`#283 (What Curse keeps in the area map region at +$1800 is unread, and a
conversion writes zeroes there)` asked what the 1024 bytes at `+$1800` of a
`SAVEAZURE` are.  They are `ANIMATE00`'s picture buffer: the glyph bitmaps
and colour bytes of whatever picture is in the view window, at whatever frame
its animation had reached when `ENCAMP > SAVE` took the whole of `$4B00`-`$67FF`
in one KERNAL `SAVE` (`CAMP $0CEC`-`$0CFC`, `LIBRARY $317A`).  On `ENCAMP`
that picture is always `PIC1D`, the camp scene, so every engine-written Curse
save carries one frame of a campfire.

This is that unpacker, transcribed from `ANIMATE00 $6AC0`, so the claim can be
checked against any save without an emulator:

    tools/cursepic.py frames PIC1D                    each frame's shape
    tools/cursepic.py frames PIC1D --png work/pic     and a PNG of each
    tools/cursepic.py match SAVE.D64 PIC1D            which frame the save holds

`match` prints, for every frame, how many of the 1024 bytes differ; the answer
is the row that reads 0.  A save Wish wrote reads 526 against every frame,
because Wish writes zeroes there and the engine never reads them back
(`docs/181-curse-picture-buffer.md`).

The format, as `ANIMATE00` reads it:

    +$00   frame table: one byte per frame after the first, `$41`, `$42`, ...;
           a zero ends the cycle and the next call decodes the full frame again
    +$20   per-frame delay, indexed by `frame byte - $41`
    +$2C   delay loop count
    +$2D   width in cells,  +$2E height in cells
    +$2F   glyph bytes, 16-bit (width x height x 8)
    +$31   cell count (width x height)
    +$33   frame counter, written by the engine as it animates
    +$34   background, +$35 and +$36 the two shared multicolour registers
    +$38   the streams: glyphs then colours for the full frame, then a pair
           of delta streams for each frame in the table

A stream is a run of count bytes.  `n` below `$80` means `n` literal bytes,
each XORed into the destination; `n` from `$80` up means the next byte XORed
in `256 - n` times; `0` ends the stream.  The full frame's glyph stream lands
at buffer `+0` and its colour stream at `+glyph bytes`; each delta frame is
two more streams onto the same two places, so the buffer accumulates.  The
buffer is zeroed before a full decode (`$6962`-`$6980`), which is why XOR onto
zero yields the picture.

**The colour bytes run past the save's region.**  Eleven by eleven is 121
colour bytes from `$66C8`, and `$66C8 + 121` is `$6741`: the last 65 land on
the first two roster slots at `$6700`.  What the engine does about that is
`docs/181-curse-picture-buffer.md`'s business; this tool decodes the whole
`$441`-byte buffer and compares only the 1024 bytes the region holds.

Nothing here writes to a disk image, and nothing it prints is committed.
"""
from __future__ import annotations

import argparse
import glob
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox.d64 import D64, load_payload  # noqa: E402
from tools import gamedisks  # noqa: E402

#: Where the buffer sits in the running machine and in the save's payload.
BUFFER = 0x6300
REGION = 0x1800
REGION_SIZE = 0x400
#: The header fields `ANIMATE00` reads, by offset into the PIC.
FRAME_TABLE = 0x00
DELAYS = 0x20
WIDTH = 0x2D
HEIGHT = 0x2E
GLYPH_BYTES = 0x2F
CELLS = 0x31
COUNTER = 0x33
COLOURS = 0x34
STREAMS = 0x38

#: The VIC's sixteen colours, for the PNG.  Pepto's palette, rounded.
PALETTE = [
    (0, 0, 0), (255, 255, 255), (136, 0, 0), (170, 255, 238),
    (204, 68, 204), (0, 204, 85), (0, 0, 170), (238, 238, 119),
    (221, 136, 85), (102, 68, 0), (255, 119, 119), (51, 51, 51),
    (119, 119, 119), (170, 255, 102), (0, 136, 255), (187, 187, 187),
]


def curse_sides(disks: str | None = None) -> list[str]:
    """Every Curse side, from `--disks`, `$COAB_DISKS`, or the registry."""
    root = disks or os.environ.get("COAB_DISKS") or \
        str(gamedisks.find("curse-of-the-azure-bonds") or "")
    if not root or not os.path.isdir(root):
        raise SystemExit("No Curse disks: pass --disks or set $COAB_DISKS.")
    for pattern in ("CURSE_?.D64", "CURSE?.D64", "*Disk?.d64"):
        sides = sorted(glob.glob(os.path.join(root, pattern)))
        if sides:
            return sides
    raise SystemExit(f"No Curse sides under {root}")


def read_file(name: str, disks: str | None = None) -> bytes:
    """The payload of `name` off the first Curse side that carries it."""
    for side in curse_sides(disks):
        image = D64.open(side)
        for entry in image.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == name:
                return load_payload(image, name)
    raise SystemExit(f"No file called {name} on any Curse side")


class Picture:
    """One PIC file, decoded the way `ANIMATE00` decodes it."""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.width = raw[WIDTH]
        self.height = raw[HEIGHT]
        self.glyph_bytes = raw[GLYPH_BYTES] | (raw[GLYPH_BYTES + 1] << 8)
        self.cells = raw[CELLS]
        self.background = raw[COLOURS] & 0x0F
        self.multicolour = (raw[COLOURS + 1] & 0x0F, raw[COLOURS + 2] & 0x0F)
        self.size = self.glyph_bytes + self.cells
        # Not every `PIC` on the disks is one of these: `PIC64`, `PIC79` and
        # `PIC7B` carry no such header and are drawn by something else.  The
        # header has to describe itself before the streams are believed.
        if not (0 < self.width <= 40 and 0 < self.height <= 25
                and self.cells == self.width * self.height
                and self.glyph_bytes == self.cells * 8
                and STREAMS < len(raw)):
            raise ValueError(
                f"not an ANIMATE00 picture: header says {self.width}x"
                f"{self.height} cells, {self.cells} colour bytes, "
                f"{self.glyph_bytes} glyph bytes")
        self.frames: list[bytes] = []
        self.ends: list[int] = []
        self._decode()

    def _stream(self, pos: int, buf: bytearray, at: int) -> tuple[int, int]:
        """One stream from `raw[pos]` XORed onto `buf[at:]`; returns
        (position after the stream, first untouched buffer offset)."""
        raw = self.raw
        while True:
            n = raw[pos]
            pos += 1
            if n == 0:
                return pos, at
            if n < 0x80:
                for _ in range(n):
                    buf[at] ^= raw[pos]
                    pos += 1
                    at += 1
            else:
                value = raw[pos]
                pos += 1
                for _ in range(256 - n):
                    buf[at] ^= value
                    at += 1

    def _decode(self) -> None:
        buf = bytearray(self.size)
        pos = STREAMS
        # The full frame, then one delta per entry of the frame table.  The
        # engine walks the table until it meets a zero; a file whose streams
        # outnumber its table entries is decoded to the end anyway and the
        # difference is reported by `frames` rather than hidden.
        while pos < len(self.raw):
            pos, _ = self._stream(pos, buf, 0)
            pos, _ = self._stream(pos, buf, self.glyph_bytes)
            self.frames.append(bytes(buf))
            self.ends.append(pos)

    @property
    def table_frames(self) -> int:
        """How many frames the engine cycles through.

        `$6923` reads the counter at `+$33`, zero meaning the full frame, and
        looks the count up in the table at `+$00`: a zero there ends the
        cycle.  Entry 0 is the full frame's own delay index, so the frames in
        a cycle are the non-zero entries counted from the start -- `41 42 43
        44 00` is four, the full frame and three deltas.
        """
        n = 0
        while self.raw[FRAME_TABLE + n]:
            n += 1
        return n

    def region(self, frame: int) -> bytes:
        """What the save's `+$1800`-`+$1BFF` holds for that frame."""
        return self.frames[frame][:REGION_SIZE]

    def compare(self, region: bytes) -> list[tuple[int, int]]:
        """(frame, bytes differing) for every decoded frame."""
        out = []
        for k, f in enumerate(self.frames):
            d = sum(1 for i in range(REGION_SIZE) if region[i] != f[i])
            out.append((k, d))
        return out

    def png(self, frame: int, path: str, scale: int = 4) -> None:
        from PIL import Image  # noqa: PLC0415

        f = self.frames[frame]
        w, h = self.width, self.height
        im = Image.new("RGB", (w * 8, h * 8))
        for cell in range(self.cells):
            cx, cy = (cell % w) * 8, (cell // w) * 8
            colour = f[self.glyph_bytes + cell] & 0x07
            for r in range(8):
                byte = f[cell * 8 + r]
                for p in range(4):
                    bits = (byte >> (6 - 2 * p)) & 3
                    rgb = PALETTE[
                        (self.background, self.multicolour[0],
                         self.multicolour[1], colour)[bits]]
                    im.putpixel((cx + p * 2, cy + r), rgb)
                    im.putpixel((cx + p * 2 + 1, cy + r), rgb)
        im.resize((im.width * scale, im.height * scale),
                  Image.NEAREST).save(path)


def payload_of(path: str) -> bytes:
    raw = pathlib.Path(path).read_bytes()
    if len(raw) == 7424:
        return raw
    return load_payload(path, "SAVEAZURE")


def picture(name: str, disks: str | None) -> Picture:
    try:
        return Picture(read_file(name, disks))
    except (ValueError, IndexError) as exc:
        raise SystemExit(f"{name}: {exc}")


def cmd_frames(args) -> int:
    pic = picture(args.pic, args.disks)
    print(f"{args.pic}: {len(pic.raw)} bytes, {pic.width}x{pic.height} cells, "
          f"{pic.glyph_bytes} glyph bytes + {pic.cells} colour bytes = "
          f"${pic.size:X} at ${BUFFER:04X}-${BUFFER + pic.size - 1:04X}; "
          f"background {pic.background}, multicolour {pic.multicolour}")
    print(f"  frame table {pic.raw[FRAME_TABLE:FRAME_TABLE + 8].hex(' ')} -> "
          f"{pic.table_frames} frames in the cycle; "
          f"delays {pic.raw[DELAYS:DELAYS + 12].hex(' ')}")
    prev = None
    for k, f in enumerate(pic.frames):
        nonzero = sum(1 for b in f[:REGION_SIZE] if b)
        changed = "" if prev is None else \
            f", {sum(1 for i in range(pic.size) if f[i] != prev[i])} bytes " \
            f"changed from frame {k - 1}"
        print(f"  frame {k}: stream ends at +${pic.ends[k]:X}, "
              f"{nonzero} non-zero of the region's 1024{changed}")
        prev = f
        if args.png:
            os.makedirs(args.png, exist_ok=True)
            out = os.path.join(args.png, f"{args.pic}-frame{k}.png")
            pic.png(k, out)
            print(f"           -> {out}")
    if pic.ends[-1] != len(pic.raw):
        print(f"  {len(pic.raw) - pic.ends[-1]} bytes past the last stream")
    return 0


def cmd_match(args) -> int:
    pic = picture(args.pic, args.disks)
    region = payload_of(args.save)[REGION:REGION + REGION_SIZE]
    print(f"{args.save}: {sum(1 for b in region if b)} non-zero bytes at "
          f"+${REGION:04X}-+${REGION + REGION_SIZE - 1:04X}")
    best = None
    for k, d in pic.compare(region):
        print(f"  against {args.pic} frame {k}: {d} of {REGION_SIZE} differ")
        if best is None or d < best[1]:
            best = (k, d)
    if best[1] == 0:
        print(f"  = {args.pic} frame {best[0]}, byte for byte")
        return 0
    print("  matches no frame")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--disks", default=None, help="where the Curse sides are")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("frames", help="decode a PIC and describe its frames")
    f.add_argument("pic", help="the file's name on the disk, e.g. PIC1D")
    f.add_argument("--png", default=None, metavar="DIR",
                   help="write one PNG per frame into DIR")
    f.set_defaults(fn=cmd_frames)
    m = sub.add_parser("match", help="which frame a save's region holds")
    m.add_argument("save", help="a .D64 carrying SAVEAZURE, or the payload")
    m.add_argument("pic", nargs="?", default="PIC1D")
    m.set_defaults(fn=cmd_match)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
