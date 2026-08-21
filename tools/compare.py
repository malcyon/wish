#!/usr/bin/env python3
"""Compare character records byte by byte to locate unknown fields.

Loads every specimen we have and reports, for each offset, how the value varies
across characters. Offsets that vary are candidate fields; correlating that
variation with attributes we already know (race, class, sex, age) is how the
remaining fields get identified -- no emulator required.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from por import layout
from por.d64 import D64
from por.layout import Confidence
from por.record import RECORD_SIZE, CharacterRecord

DISKS = "/mnt/media/roms/c64/Pool of Radiance Disks"


def load_specimens() -> dict[str, CharacterRecord]:
    out: dict[str, CharacterRecord] = {}
    img = D64.open(f"{DISKS}/PORSAVE.D64")
    for e in img.directory():
        if bytes(e.raw_name).startswith(b"\x01"):
            blob = img.read_file(e)
            if len(blob) == RECORD_SIZE + 2:
                r = CharacterRecord.from_prg(blob)
                out[r.name] = r
    return out


def known_offsets() -> set[int]:
    s = set()
    for f in layout.iter_fields():
        if f.confidence is not Confidence.UNKNOWN:
            s.update(range(f.offset, f.offset + f.size))
    return s


def main() -> int:
    recs = load_specimens()
    names = list(recs)
    data = {n: recs[n].to_bytes() for n in names}
    known = known_offsets()

    varying, constant_nonzero = [], []
    for off in range(RECORD_SIZE):
        vals = {n: data[n][off] for n in names}
        if len(set(vals.values())) > 1:
            varying.append((off, vals))
        elif next(iter(vals.values())) != 0:
            constant_nonzero.append((off, next(iter(vals.values()))))

    short = {n: (n[:7] if len(n) > 7 else n) for n in names}
    print(f"{len(names)} specimens: {', '.join(names)}\n")
    print(f"{'off':>5} {'known?':<22}" + "".join(f"{short[n]:>8}" for n in names))
    print("-" * (27 + 8 * len(names)))
    for off, vals in varying:
        if off in known:
            fname = next(f.name for f in layout.iter_fields()
                         if f.offset <= off < f.offset + f.size)
            tag = fname[:21]
        else:
            tag = "** UNKNOWN **"
        print(f"0x{off:03X} {tag:<22}" + "".join(f"{vals[n]:>8}" for n in names))

    print(f"\n{len(varying)} offsets vary; "
          f"{sum(1 for o, _ in varying if o not in known)} of them are unidentified.")
    print(f"{len(constant_nonzero)} offsets are non-zero but identical in every specimen "
          f"(defaults, or fields nobody has changed yet):")
    print("   " + " ".join(f"0x{o:03X}={v}" for o, v in constant_nonzero))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
