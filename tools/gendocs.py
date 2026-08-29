#!/usr/bin/env python3
"""Regenerate docs/20-character-record.md from goldbox/layout.py.

The field table is generated rather than hand-written so the documentation
cannot drift from the code. Re-run after changing the layout:

    python3 tools/gendocs.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import layout
from goldbox.layout import Confidence

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "20-character-record.md"

KIND_DESC = {
    "U8": "unsigned byte",
    "U16LE": "16-bit little endian",
    "ASCII_NUL": "ASCII, NUL-padded",
    "RAW": "raw bytes",
}


def main() -> int:
    cov = layout.coverage()
    lines: list[str] = []
    add = lines.append

    add("# Character record")
    add("")
    add("**Generated from `goldbox/layout.py` by `tools/gendocs.py` — do not edit by hand.**")
    add("")
    add(f"A character record is **{layout.RECORD_SIZE} bytes**. Exported to disk it is a PRG "
        f"with a 2-byte load address of `${layout.LOAD_ADDRESS:04X}` "
        f"({layout.PRG_SIZE} bytes total). In `SAVEDGAME0` the same {layout.RECORD_SIZE} "
        "bytes sit at the head of each character slot.")
    add("")
    add("## Confidence")
    add("")
    add("| level | meaning |")
    add("|---|---|")
    add("| `CONFIRMED` | corroborated across specimens, or checked against an external "
        "rule (e.g. an AD&D table) |")
    add("| `PROBABLE` | consistent with the evidence but not independently verified |")
    add("| `GUESS` | a plausible reading that something about the data contradicts |")
    add("| `UNKNOWN` | not understood; bytes preserved verbatim |")
    add("")
    add("## Coverage")
    add("")
    add("| level | bytes | share |")
    add("|---|---:|---:|")
    for c in (Confidence.CONFIRMED, Confidence.PROBABLE, Confidence.GUESS, Confidence.UNKNOWN):
        n = cov.by_confidence.get(c, 0)
        add(f"| {c.name} | {n} | {n / cov.total * 100:.1f}% |")
    add(f"| **known** | **{cov.known}** | **{cov.known / cov.total * 100:.1f}%** |")
    add("")
    add("## Known fields")
    add("")
    add("| offset | size | name | type | confidence | notes |")
    add("|---|---:|---|---|---|---|")
    for f in layout.iter_fields():
        if f.confidence is Confidence.UNKNOWN:
            continue
        kind = KIND_DESC.get(f.kind.name, f.kind.name)
        note = (f.note or "").replace("|", r"\|")
        add(f"| `0x{f.offset:03X}` | {f.size} | `{f.name}` | {kind} | {f.confidence.name} | {note} |")
    add("")
    add("## Unknown regions that hold data")
    add("")
    add("Regions explicitly declared as candidates because they are non-zero in at least "
        "one specimen. Everything not listed here — and not a known field above — is a "
        "gap that is all zeroes in every specimen seen so far.")
    add("")
    add("| offset | size | notes |")
    add("|---|---:|---|")
    for f in layout.iter_fields():
        if f.confidence is Confidence.UNKNOWN and f.candidate:
            note = (f.note or "").replace("|", r"\|")
            add(f"| `0x{f.offset:03X}` | {f.size} | {note} |")
    add("")
    add("## Invariant")
    add("")
    add("The table **tiles the whole record**: every one of the "
        f"{layout.RECORD_SIZE} bytes belongs to exactly one entry, with gaps generated "
        "automatically. That is asserted at import time, so a record can always be "
        "decoded and re-encoded byte-for-byte — an edit can never silently drop bytes "
        "we do not yet understand.")
    add("")

    OUT.write_text(encoding="utf-8", data="\n".join(lines))
    print(f"wrote {OUT} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
