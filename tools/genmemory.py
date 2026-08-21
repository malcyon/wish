#!/usr/bin/env python3
"""Generate docs/41-memory-regions.md from por/memory.py."""

import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from por.memory import MAP  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "41-memory-regions.md"

HEADER = """# Memory regions

**Generated** by `tools/genmemory.py` from `por/memory.py` — do not edit.

Every address this project has named, in one place. It answers "what is at
`$4BC2`" without grepping, which is what it exists for;
[40-memory-map.md](40-memory-map.md) holds the *reasoning* and the game's own
string tables.

Addresses are **live** addresses. `SAVEDGAME0` is a verbatim image of
`$4900`–`$64FF` and `SAVEDGAME1` of `$8300`–`$8AFF`, so anything marked as saved
is also a file offset once the base is subtracted. Everything else means what it
says only while the overlay that owns it is resident.

"""


def main() -> int:
    rows = ["| where | what | saved in | confidence | notes |",
            "|---|---|---|---|---|"]
    for r in sorted(MAP, key=lambda r: r.start):
        span = (f"`${r.start:04X}`" if r.size <= 1
                else f"`${r.start:04X}`–`${r.end - 1:04X}`")
        note = r.note.replace("|", r"\|") if r.note else ""
        rows.append(f"| {span} | **{r.name}** | {r.saved_in or '—'} "
                    f"| {r.confidence.value} | {note} |")
    OUT.write_text(HEADER + "\n".join(rows) + "\n")
    print(f"{len(MAP)} regions -> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
