#!/usr/bin/env python3
"""Diff two Pool of Radiance save disks and say what changed, in game terms.

This is the workhorse of the discovery phase. The method is: save, change
exactly one thing in-game, save again, then

    tools/diff.py before.d64 after.d64

Changed bytes inside SAVEDGAME0 are resolved to slot + record offset and
labelled with the layout field name when we know it, or flagged as an unknown
region when we do not. Unknown-region hits are the interesting ones -- they are
candidate locations for whatever you just changed.

Also diffs raw files (character exports, memory dumps) of equal length.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from por import layout
from por.d64 import D64, split_load_address
from por.record import RECORD_SIZE
from por.savegame import HEADER_SIZE, SAVE0_LOAD_ADDRESS, SLOT_STRIDE, SaveGame0

IMAGE_SIZE = 174848


def describe_save0_offset(off: int) -> str:
    """Map a SAVEDGAME0 payload offset to a human description."""
    addr = SAVE0_LOAD_ADDRESS + off
    if off < HEADER_SIZE:
        return f"${addr:04X}  header+${off:03X}"
    slot_off = off - HEADER_SIZE
    slot, within = divmod(slot_off, SLOT_STRIDE)
    if within >= RECORD_SIZE:
        return f"${addr:04X}  slot {slot} tail+${within - RECORD_SIZE:03X}  (past record)"
    field = next((f for f in layout.iter_fields()
                  if f.offset <= within < f.offset + f.size), None)
    if field is None:
        label = "?"
    elif field.confidence is layout.Confidence.UNKNOWN:
        label = f"UNKNOWN region (+${within - field.offset:x} into ${field.offset:03X})"
    else:
        label = f"{field.name}  [{field.confidence.name}]"
    return f"${addr:04X}  slot {slot} rec+${within:03X}  {label}"


def diff_bytes(a: bytes, b: bytes) -> list[tuple[int, int, int]]:
    return [(i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]


def report_save0(a: bytes, b: bytes) -> None:
    _, pa = split_load_address(a)
    _, pb = split_load_address(b)
    changes = diff_bytes(pa, pb)
    if not changes:
        print("    (identical)")
        return
    print(f"    {len(changes)} byte(s) changed")
    # Group by slot so a multi-byte field reads as one thing
    for off, old, new in changes:
        print(f"      {describe_save0_offset(off)}   {old:02x} -> {new:02x}"
              f"   ({old} -> {new})")
    # Highlight which characters were touched
    try:
        sa, sb = SaveGame0.from_prg(a), SaveGame0.from_prg(b)
        touched = sorted({(off - HEADER_SIZE) // SLOT_STRIDE
                          for off, _, _ in changes if off >= HEADER_SIZE})
        for i in touched:
            ra, rb = sa.slot(i).record, sb.slot(i).record
            if ra and rb:
                fields = [f.name for f in layout.iter_fields()
                          if f.confidence is not layout.Confidence.UNKNOWN
                          and ra.get(f.name) != rb.get(f.name)]
                if fields:
                    print(f"    slot {i} ({ra.name}) known fields changed: "
                          + ", ".join(f"{n}: {ra.get(n)!r} -> {rb.get(n)!r}"
                                      for n in fields))
    except Exception as exc:                      # noqa: BLE001 - diagnostic only
        print(f"    (slot analysis skipped: {exc})")


def diff_images(pa: pathlib.Path, pb: pathlib.Path) -> int:
    ia, ib = D64.open(pa), D64.open(pb)
    na = {bytes(e.raw_name).rstrip(b"\xa0"): e for e in ia.directory()}
    nb = {bytes(e.raw_name).rstrip(b"\xa0"): e for e in ib.directory()}

    only_a, only_b = sorted(na.keys() - nb.keys()), sorted(nb.keys() - na.keys())
    for n in only_a:
        print(f"  - {n.decode('latin-1')!r}  (only in {pa.name})")
    for n in only_b:
        print(f"  + {n.decode('latin-1')!r}  (only in {pb.name})")

    changed = False
    for name in sorted(na.keys() & nb.keys()):
        da, db = ia.read_file(na[name]), ib.read_file(nb[name])
        if da == db:
            continue
        changed = True
        label = name.decode("latin-1")
        print(f"  ~ {label!r}  ({len(da)} -> {len(db)} bytes)")
        if len(da) != len(db):
            print("    (different lengths -- byte offsets not comparable)")
        elif name == b"SAVEDGAME0":
            report_save0(da, db)
        else:
            for off, old, new in diff_bytes(da, db)[:80]:
                print(f"      +${off:04X}  {old:02x} -> {new:02x}")
    if not changed and not only_a and not only_b:
        print("  (no differences)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before")
    ap.add_argument("after")
    args = ap.parse_args()
    pa, pb = pathlib.Path(args.before), pathlib.Path(args.after)
    print(f"{pa}  ->  {pb}\n")

    da, db = pa.read_bytes(), pb.read_bytes()
    if len(da) == len(db) == IMAGE_SIZE:
        return diff_images(pa, pb)

    if len(da) != len(db):
        print(f"different lengths: {len(da)} vs {len(db)}", file=sys.stderr)
        return 1
    for off, old, new in diff_bytes(da, db):
        print(f"  +${off:04X}  {old:02x} -> {new:02x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
