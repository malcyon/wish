"""Render the application icon into an `.icns`, for macOS.

    .venv/bin/python packaging/geniconset.py            # rewrite assets/wish.icns
    .venv/bin/python packaging/geniconset.py --check    # is it in step?

Offscreen, through `ui.appicon`, exactly as `tools/genicons.py` renders the
`.ico` and the hicolor tree: `assets/logo/mark.svg` is the vector source and
this is a size-tuned export of it, so the Dock icon can never drift from the
drawing the taskbar and the About box use.

**Every size is rendered from the vector, never scaled.** `docs/132-logo.md`
§1b's `.icns` row: 16, 32, 64, 128, 256, 512 and 1024, each rendered once, and
some of those pixel sizes are stored twice under different Apple type codes --
`32x32` and `16x16@2x` are the same 32 pixels, tagged `icp5` and `ic11`, and
the drawing behind both is one call to `ui.appicon.image(32)`.

**The container is written here**, in `icns_bytes`, the same reason
`tools/genicons.py` writes its own `.ico`: an `.icns` is a short sequence of
four-byte type, four-byte length and a PNG payload, and there is nothing a
library buys over forty lines of `struct` -- see Apple's Icon Services header,
which this follows.

**No Mac has run this.** `docs/132-logo.md` says so; the container's byte
layout is documented and checkable without one, and `tests/test_geniconset.py`
parses back what this writes and checks each chunk decodes to the size its tag
promises, but nobody has yet dropped the file on a real Dock.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QBuffer, QIODevice  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402

from ui import appicon  # noqa: E402

ICNS = ROOT / "assets" / "wish.icns"

#: Apple's Icon Services type codes, and the pixel size each one holds. Two
#: codes can share a size -- `32x32`@1x and `16x16`@2x are both 32 pixels --
#: and both get the same render, because they are the same drawing.
TAGS: tuple[tuple[str, int], ...] = (
    ("icp4", 16),
    ("icp5", 32),
    ("ic11", 32),
    ("icp6", 64),
    ("ic12", 64),
    ("ic07", 128),
    ("ic08", 256),
    ("ic13", 256),
    ("ic09", 512),
    ("ic14", 512),
    ("ic10", 1024),
)


def png_bytes(size: int) -> bytes:
    """The icon at `size`, PNG-encoded by Qt -- `tools/genicons.py`'s own
    helper, kept separate rather than imported so this file builds a `.icns`
    without reaching into a module it does not own."""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not appicon.image(size).save(buffer, "PNG"):
        raise RuntimeError(f"Qt would not encode a {size}px PNG")
    return bytes(buffer.data())


def icns_bytes(tags: tuple[tuple[str, int], ...] = TAGS) -> bytes:
    """A macOS `.icns`: the `icns` header, then one chunk per tag.

    Each chunk is the four-byte type, a four-byte big-endian length that
    counts the chunk's own eight-byte header, and the PNG payload -- Apple's
    Icon Services layout, current since PNG-backed icons replaced the old raw
    bitmap types.
    """
    cache: dict[int, bytes] = {}
    body = b""
    for tag, size in tags:
        data = cache.setdefault(size, png_bytes(size))
        body += struct.pack(">4sI", tag.encode("ascii"), 8 + len(data)) + data
    header = struct.pack(">4sI", b"icns", 8 + len(body))
    return header + body


def entries(data: bytes) -> list[dict]:
    """A `.icns`'s chunks, parsed back -- what a test checks against."""
    magic, total = struct.unpack(">4sI", data[:8])
    if magic != b"icns":
        raise ValueError("not an icns file")
    out, offset = [], 8
    while offset < total:
        tag, length = struct.unpack(">4sI", data[offset:offset + 8])
        payload = data[offset + 8:offset + length]
        out.append({"tag": tag.decode("ascii"), "payload": payload})
        offset += length
    return out


def differences(path: pathlib.Path = ICNS) -> str:
    """Why the committed `.icns` is not today's drawing, or "" when it is."""
    fresh = icns_bytes()
    if not path.exists():
        return "missing"
    stored = path.read_bytes()
    if stored == fresh:
        return ""
    return f"{len(stored)} bytes stored, {len(fresh)} bytes today"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="fail if assets/wish.icns is not what this "
                             "would write")
    args = parser.parse_args(argv[1:])

    app = QGuiApplication(["geniconset"])   # a QImage still wants one
    assert app is not None                  # and wants it kept alive

    if args.check:
        why = differences()
        if why:
            print(f"out of date -- run packaging/geniconset.py: {why}",
                  file=sys.stderr)
            return 1
        return 0

    data = icns_bytes()
    ICNS.write_bytes(data)
    print(f"assets/wish.icns  {len(data)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
