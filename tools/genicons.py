"""Render the application icon into the files the platforms want.

    .venv/bin/python tools/genicons.py            # rewrite assets/
    .venv/bin/python tools/genicons.py --check    # is assets/ in step?

Offscreen, through `ui.iconpaint`, exactly as `tools/iconsheet.py` renders the
sheet: `ui/icons.py` is the vector source and this is a size-tuned export of
it, so the icon on the taskbar can never drift from the glyph the map and the
roster paint. Nothing here is drawn by hand.

**Every size is rendered, not scaled.** Windows picks the entry nearest the
size it wants and bilinearly scales when it has to, so a `.ico` holding only a
256 gives mush at 16 -- and 16 is the title bar, Alt-Tab and Explorer's list
view. 20, 24 and 40 are the same slots at 125 %, 150 % and 250 % display
scaling, which Windows asks for rather than rounding to 16 or 32.

**The `.ico` container is written here**, in `ico_bytes`, rather than by a
library. Not for the fun of it: a `.ico` wants a 32-bit DIB for the small
entries and a PNG for the 256, and every library that writes one -- Pillow
included -- makes that choice for the whole file at once. Thirty lines of `struct` buys the mix
Windows documents, and leaves the generator needing nothing Qt does not
already provide.

**The output is committed**, under `assets/`. The alternative is a build step
before `pyinstaller`, and PyInstaller wants the `.ico` to exist when it reads
`wish.spec`; committing it keeps the release a single command.
`tests/test_appicon.py` re-renders and compares, so a committed file that no
longer matches the drawing fails the build rather than shipping.

**The comparison is pixels within a tolerance** -- `differences`, and the note
above it. Qt does not promise a byte-identical PNG on two machines and did not
deliver one, and it does not quite promise the last bit of an antialiased pixel
either. `TOLERANCE` and `MOST` are what separates that from a real change.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QBuffer, QIODevice  # noqa: E402
from PyQt6.QtGui import QGuiApplication, QImage  # noqa: E402

from ui import appicon  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

#: What goes in `wish.ico`. 16 and 32 are the ones that matter -- the title bar
#: and the taskbar button -- and the rest are what Windows asks for at the
#: display scalings, plus 256 for Explorer's extra-large view and the
#: Properties sheet.
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)

#: Above this an entry is stored as a PNG. Windows Vista introduced that and
#: nothing before it can read a 256 any other way; below it the documented
#: form is a DIB, and the shell has been happier with one there ever since.
PNG_FROM = 256

#: The freedesktop `hicolor` theme. 22 is GNOME's panel size and 24 is KDE's;
#: neither is anybody's export default, and a missing one is a blurred icon.
HICOLOR_SIZES = (16, 22, 24, 32, 48, 64, 128, 256)

#: One image at a size a README renders comfortably.
LOGO_SIZE = 256


def png_bytes(size: int) -> bytes:
    """The icon at `size`, PNG-encoded by Qt."""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not appicon.image(size).save(buffer, "PNG"):
        raise RuntimeError(f"Qt would not encode a {size}px PNG")
    return bytes(buffer.data())


def _bgra(size: int) -> bytes:
    """The icon's pixels as straight-alpha BGRA, which is what a DIB holds.

    Read as RGBA and swapped here rather than read as `Format_ARGB32`, whose
    byte order in memory is the machine's. The generator has to produce the
    same file on any host that runs it.
    """
    image = appicon.image(size).convertToFormat(QImage.Format.Format_RGBA8888)
    # RGBA at any width is already 4-byte aligned, so Qt's stride is 4*width
    # and the buffer can be taken whole.
    assert image.bytesPerLine() == 4 * size, image.bytesPerLine()
    out = bytearray(image.constBits().asstring(image.sizeInBytes()))
    out[0::4], out[2::4] = out[2::4], out[0::4]
    return bytes(out)


def _dib(size: int) -> bytes:
    """One ICO entry as a 32-bit bottom-up DIB, with its AND mask.

    Two things about it that are not obvious. The header's height is *twice*
    the image, because the structure covers the colour rows and the mask rows
    together; and the mask is written all-zero and still has to be there --
    the alpha channel is what Windows actually uses, but a 32-bit entry with
    the mask missing is a malformed icon.
    """
    rows = _bgra(size)
    stride = 4 * size
    bottom_up = b"".join(rows[y * stride:(y + 1) * stride]
                         for y in reversed(range(size)))
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                         len(bottom_up), 0, 0, 0, 0)
    mask_stride = ((size + 31) // 32) * 4          # 1 bpp, rows padded to 4
    return header + bottom_up + b"\0" * (mask_stride * size)


def ico_bytes(sizes=ICO_SIZES) -> bytes:
    """A Windows `.ico`: header, directory, then one entry per size."""
    entries = [(s, png_bytes(s) if s >= PNG_FROM else _dib(s))
               for s in sorted(sizes)]
    offset = 6 + 16 * len(entries)
    directory, payload = b"", b""
    for size, data in entries:
        directory += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                                 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    return struct.pack("<HHH", 0, 1, len(entries)) + directory + payload


def artefacts(assets: pathlib.Path = ASSETS) -> dict[pathlib.Path, bytes]:
    """Every file this generator owns, as path -> contents."""
    out = {assets / "wish.ico": ico_bytes(),
           assets / "wish.png": png_bytes(LOGO_SIZE)}
    for size in HICOLOR_SIZES:
        out[assets / "icons" / "hicolor" / f"{size}x{size}" / "apps"
            / "wish.png"] = png_bytes(size)
    return out


# --- comparing a committed artefact with today's drawing -----------------
#
# Not by its bytes. A PNG's bytes are libpng's and zlib's, and on Linux Qt
# links the *host's* copies of both (`ldd libQt6Gui.so.6` finds
# `libpng16.so.16` and `libz.so.1`) while the Windows wheel bundles its own.
# Qt promises the pixels, not the file, so the pixels are compared and the
# encoding is left to the machine.
#
# And not by exact pixels either. Qt's rasteriser rounds the last bit of an
# antialiased edge differently on different hosts: CI came back with 8 of
# 65536 pixels moved at 256, 8 of 484 at 22 and 1 of 4096 at 64, every one of
# them by 1 of 255. That is the noise the tolerance below has to sit above.


def png_pixels(data: bytes) -> tuple[int, int, bytes]:
    """An encoded PNG as (width, height, RGBA8888 rows)."""
    image = QImage.fromData(data, "PNG")
    if image.isNull():
        raise ValueError("not a PNG this Qt can read")
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return (image.width(), image.height(),
            bytes(image.constBits().asstring(image.sizeInBytes())))


def ico_entries(data: bytes) -> list[dict]:
    """`wish.ico`'s directory, parsed. Twelve lines beats a dependency."""
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    if (reserved, kind) != (0, 1):
        raise ValueError("not an icon file")
    out = []
    for i in range(count):
        w, h, colours, _, planes, bpp, length, offset = struct.unpack(
            "<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        out.append({"size": w or 256, "height": h or 256, "bpp": bpp,
                    "planes": planes, "colours": colours,
                    "payload": data[offset:offset + length]})
    return out


def drawing(name: str, data: bytes) -> dict[str, tuple[int, int, bytes]]:
    """Every square an artefact holds, as label -> (width, height, pixels).

    A DIB is already pixels and is taken as it stands, header and AND mask
    left off; a PNG -- the whole of a `.png`, and the 256 inside the `.ico` --
    is decoded. The label carries the entry's shape, so an `.ico` that lost a
    size or turned an entry 24-bit compares unequal rather than silently
    matching on the sizes it still has.
    """
    if not name.endswith(".ico"):
        return {"": png_pixels(data)}
    out = {}
    for entry in ico_entries(data):
        size, payload = entry["size"], entry["payload"]
        label = (f"{size}x{entry['height']} {entry['bpp']}-bit "
                 f"{entry['planes']}-plane")
        out[label] = (png_pixels(payload)
                      if payload[:8] == b"\x89PNG\r\n\x1a\n"
                      else (size, size, payload[40:40 + 4 * size * size]))
    return out


#: How far a stored square may be from today's render and still be the same
#: drawing: no channel of any pixel off by more than `TOLERANCE`, and no more
#: than `MOST` of the pixels touched at all. Both bounds are measured rather
#: than chosen. The rounding noise above is 1 of 255 on at most 1.65 % of a
#: square, so each has about six times the room it needs; and every edit small
#: enough to be worth arguing about breaks one of them at one size or another
#: -- moving the inset by a part in a thousand goes 4 of 255 out at 24, moving
#: one path point by 1/640 goes 35 out at 256, and changing a colour by a
#: single unit moves 70 % of the pixels at every size.
TOLERANCE = 2
MOST = 0.10


def _difference(was, now) -> str:
    """Why two squares are not the same square, or "" when they are."""
    if was is None or now is None:
        return "only one of the two has it"
    (width, height, before), (wide, high, after) = was, now
    if (width, height) != (wide, high):
        return f"{width}x{height} against {wide}x{high}"
    if before == after:
        return ""
    total = width * height
    pixels = sum(1 for i in range(0, len(before), 4)
                 if before[i:i + 4] != after[i:i + 4])
    worst = max(abs(a - b) for a, b in zip(before, after))
    if worst <= TOLERANCE and pixels <= total * MOST:
        return ""
    return (f"{pixels} of {total} pixels differ ({100 * pixels / total:.2f} %),"
            f" by up to {worst} of 255")


def differences(assets: pathlib.Path = ASSETS) -> dict[pathlib.Path, str]:
    """The committed artefacts that are not today's drawing, and why."""
    out = {}
    for path, data in artefacts(assets).items():
        if not path.exists():
            out[path] = "missing"
            continue
        was, now = drawing(path.name, path.read_bytes()), drawing(path.name,
                                                                 data)
        notes = [f"{label}: {note}" if label else note
                 for label in sorted(set(was) | set(now))
                 if (note := _difference(was.get(label), now.get(label)))]
        if notes:
            out[path] = "; ".join(notes)
    return out


def _name(path: pathlib.Path) -> str:
    """Short where it can be -- `--into` may point anywhere."""
    return str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="fail if the committed files are not what this "
                             "would write")
    parser.add_argument("--into", default=str(ASSETS), type=pathlib.Path)
    args = parser.parse_args(argv[1:])

    app = QGuiApplication(["genicons"])     # a QImage still wants one
    assert app is not None                  # and wants it kept alive

    into = pathlib.Path(args.into)
    if args.check:
        stale = differences(into)
        if stale:
            print("out of date -- run tools/genicons.py:", file=sys.stderr)
            for path, why in stale.items():
                print(f"  {_name(path)}: {why}", file=sys.stderr)
            return 1
        return 0

    for path, data in artefacts(into).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"{_name(path)}  {len(data)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
