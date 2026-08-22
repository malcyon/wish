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


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="fail if the committed files are not what this "
                             "would write")
    parser.add_argument("--into", default=str(ASSETS), type=pathlib.Path)
    args = parser.parse_args(argv[1:])

    app = QGuiApplication(["genicons"])     # a QImage still wants one
    assert app is not None                  # and wants it kept alive

    stale = []
    for path, data in artefacts(pathlib.Path(args.into)).items():
        if args.check:
            if not path.exists() or path.read_bytes() != data:
                stale.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"{path.relative_to(ROOT)}  {len(data)} bytes")
    if stale:
        print("out of date -- run tools/genicons.py:", file=sys.stderr)
        for path in stale:
            print(f"  {path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
