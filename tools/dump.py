#!/usr/bin/env python3
"""Annotated dump of a Pool of Radiance D64, save game, or character file.

Discovery tool -- not part of the shipped editor.

    tools/dump.py work/PORSAVE.D64                 # disk directory + save summary
    tools/dump.py tests/fixtures/brutus.chr        # one character record
    tools/dump.py work/PORSAVE.D64 --raw SAVEDGAME0 --range 0x4c00-0x4cff
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import layout
from goldbox.d64 import D64, split_load_address
from goldbox.record import RECORD_SIZE, CharacterRecord
from goldbox.savegame import SaveGame0


def hexdump(data: bytes, base: int = 0, width: int = 16) -> str:
    out = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hexs = " ".join(f"{b:02x}" for b in chunk).ljust(width * 3 - 1)
        text = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
        out.append(f"{base + i:04x}  {hexs}  |{text}|")
    return "\n".join(out)


def annotate_record(rec: CharacterRecord) -> str:
    """Field-by-field view: what we know, and the raw bytes of what we don't."""
    lines = [f"Character record ({RECORD_SIZE} bytes)", ""]
    raw = rec.to_bytes()
    for f in layout.iter_fields():
        chunk = raw[f.offset:f.offset + f.size]
        if f.confidence is layout.Confidence.UNKNOWN:
            if not any(chunk):
                continue                      # skip all-zero unknown gaps
            lines.append(f"  ${f.offset:03x} +{f.size:<4d} {'?':<22s} "
                         f"{' '.join(f'{b:02x}' for b in chunk[:16])}"
                         f"{' ...' if f.size > 16 else ''}")
        else:
            val = rec.get(f.name)
            lines.append(f"  ${f.offset:03x} +{f.size:<4d} {f.name:<22s} {val!r}"
                         f"   [{f.confidence.name}]")
    lines += ["", layout.format_coverage()]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--raw", metavar="FILENAME",
                    help="hexdump this file from the D64 instead of summarising")
    ap.add_argument("--range", metavar="LO-HI",
                    help="restrict --raw to an address range, e.g. 0x4c00-0x4cff")
    args = ap.parse_args()

    path = pathlib.Path(args.path)
    data = path.read_bytes()

    # A bare character record (582-byte PRG)
    if len(data) == RECORD_SIZE + 2:
        print(annotate_record(CharacterRecord.from_prg(data)))
        return 0

    if len(data) != 174848:
        print(f"{path}: {len(data)} bytes -- not a D64 and not a character PRG",
              file=sys.stderr)
        return 1

    img = D64.from_bytes(data)
    print(f"{path}   disk name {img.disk_name!r}  id {img.disk_id!r}")
    print(f"{len(img.directory())} files\n")

    if args.raw:
        entry = img.entry(args.raw.encode("latin-1"))
        blob = img.read_file(entry)
        load, payload = split_load_address(blob)
        base = load
        if args.range:
            lo, hi = (int(x, 0) for x in args.range.split("-"))
            payload = payload[lo - load:hi - load + 1]
            base = lo
        print(hexdump(payload, base))
        return 0

    for e in img.directory():
        print(f"  {e.block_count:4d}  {e.type_name}  {e.display_name}")

    for name in (b"SAVEDGAME0",):
        if name in img:
            print()
            print(SaveGame0.from_prg(img.read_file(name)).summary())

    for e in img.directory():
        if e.raw_name.startswith(b"\x01"):
            blob = img.read_file(e)
            if len(blob) == RECORD_SIZE + 2:
                print(f"\n=== character file {e.display_name} ===")
                print(annotate_record(CharacterRecord.from_prg(blob)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
