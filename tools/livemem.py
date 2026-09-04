#!/usr/bin/env python3
"""Dump a range of a **running** pooled session's memory to a file.

    tools/livemem.py --port 6523 0000 10000 work/issue32/all.bin
    tools/livemem.py --port 6523 4b00 1d00 -            # hex to stdout

`tools/porcmd peek` answers one short range as hex, which is right for a
handful of bytes and useless for the question this was written for: *which
file is the loader asking the player to insert a disk for?*  That is answered
by taking the whole 64K and looking for the filename buffer in it, and a
64K `peek` is 200 kilobytes of hex through a command socket.

The session must be idle -- VICE serves one binary-monitor connection per
process, and `tools/session.py` opens and closes its own for each command, so
this can take the socket between them.  Do not point it at a port the pool did
not give you.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap.vice import Monitor  # noqa: E402

CHUNK = 0x1000


def read_range(port: int, start: int, length: int, host="127.0.0.1") -> bytes:
    """The bytes, taken in chunks so one stop is never long enough to matter."""
    out = bytearray()
    with Monitor(host=host, port=port) as m:
        while len(out) < length:
            want = min(CHUNK, length - len(out))
            out += m.read(start + len(out), want)
    return bytes(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, required=True, help="binary monitor port")
    ap.add_argument("start", help="start address, hex")
    ap.add_argument("length", help="byte count, hex")
    ap.add_argument("out", help="file to write, or - for a hex dump")
    a = ap.parse_args(argv)
    start, length = int(a.start, 16), int(a.length, 16)
    data = read_range(a.port, start, length)
    if a.out == "-":
        for i in range(0, len(data), 16):
            row = data[i:i + 16]
            text = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in row)
            print(f"{start + i:04X}  {row.hex(' '):<47}  |{text}|")
    else:
        pathlib.Path(a.out).write_bytes(data)
        print(f"{len(data)} bytes from ${start:04X} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
