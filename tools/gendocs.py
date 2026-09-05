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


def _table_cell(note: str) -> str:
    """Render a note for a single table cell.

    A markdown table row has to be one physical line. A note that carries
    more than one paragraph -- several do, at several thousand characters of
    evidence -- would otherwise run on past its own line and stop the
    renderer from seeing a table at all. Where that happens, the cell holds
    only the first paragraph, escaped, with a pointer to the full text under
    "Field notes"; the rest holds the whole note in one paragraph, since a
    long single line is at least a table that renders.
    """
    first, sep, _ = note.partition("\n")
    cell = first.replace("|", r"\|")
    if sep:
        cell += " *(rest under Field notes, below.)*"
    return cell


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
    known_fields = [f for f in layout.iter_fields() if f.confidence is not Confidence.UNKNOWN]
    for f in known_fields:
        kind = KIND_DESC.get(f.kind.name, f.kind.name)
        cell = _table_cell(f.note or "")
        add(f"| `0x{f.offset:03X}` | {f.size} | `{f.name}` | {kind} | {f.confidence.name} | {cell} |")
    add("")

    long_notes = [f for f in known_fields if "\n" in (f.note or "")]
    if long_notes:
        add("## Field notes")
        add("")
        add("Notes too long, or too many paragraphs, for a table cell -- kept "
            "here in full rather than run on past their own row above.")
        add("")
        for f in long_notes:
            add(f"### `0x{f.offset:03X}` `{f.name}`")
            add("")
            for paragraph in f.note.split("\n"):
                add(paragraph)
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
