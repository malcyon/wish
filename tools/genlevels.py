#!/usr/bin/env python3
"""Generate docs/89-level-tables.md from goldbox/levels.py."""

import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from goldbox.levels import TABLES  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "89-level-tables.md"

HEADER = """# Level progression

**Generated** by `tools/genlevels.py` from `goldbox/levels.py` — do not edit.

What each class needs to advance and what it gets. Pool of Radiance stops well
short of the rulebook — a fighter at 8, a cleric at 6 — because it was built to
hand its party on to *Curse of the Azure Bonds*.

**THAC0 is verified against the game**, which caught two errors in the published
table it came from: magic-user and thief level 1 are **21**, not 20. Rows the
game itself confirms are marked ✓; `tests/test_levels.py` asserts them against
every character record we hold.

**The saving throws are the game's own too.** Pool of Radiance does not
tabulate them: `GEN $1F44` cuts a level-1 row at `$1FA2` by two per-column
bitmasks, and `$2359` then takes `constitution * 2 / 7` off all five columns
for a dwarf, gnome or halfling. That is why two level-1 fighters read
`(14,15,16,17,17)` and `(11,12,13,14,14)` — the second is a dwarf — and it is
what settles the fighter's level-4 breath save at **15** where AD&D says 16.
`tests/test_levels.py` re-expands every row off the player's own `GEN`.

"""

CONFIRMED = {("cleric", 1), ("cleric", 6), ("fighter", 1), ("fighter", 7),
             ("fighter", 8), ("magic-user", 1), ("magic-user", 6), ("thief", 1)}


def main() -> int:
    out = [HEADER]
    for name, rows in TABLES.items():
        out.append(f"## {name}\n")
        spells = any(r.spells for r in rows)
        head = "| level | experience | hit dice | max hp | THAC0 | attacks | saves |"
        if spells:
            head += " spells |"
        out.append(head)
        out.append("|---|---|---|---|---|---|---|" + ("---|" if spells else ""))
        for r in rows:
            tick = " ✓" if (name, r.level) in CONFIRMED else ""
            saves = " / ".join(str(s) for s in r.saves)
            attacks = "3/2" if r.attacks == 1.5 else str(int(r.attacks))
            row = (f"| {r.level} | {r.experience:,} | {r.hit_dice} | {r.hp_max} "
                   f"| {r.thac0}{tick} | {attacks} | {saves} |")
            if spells:
                row += " " + ("/".join(str(s) for s in r.spells) or "—") + " |"
            out.append(row)
        out.append("")
    OUT.write_text(encoding="utf-8", data="\n".join(out) + "\n")
    print(f"{len(TABLES)} classes -> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
