#!/usr/bin/env python3
"""Generate docs/86-spell-table.md from a game disk.

The spell names live in SPELLN00 and are not in this repo as data.

    python3 tools/genspells.py [GAME.D64]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from por import d64                                       # noqa: E402
from por.spells import (LAST_SPELL, SPELL_GROUPS,          # noqa: E402
                        SPELL_RESTORATION, load_spell_names, spell_group)

DEFAULT_DISK = "work/POOL1.D64.orig"
OUT = Path(__file__).resolve().parent.parent / "docs" / "86-spell-table.md"


def main() -> int:
    disk = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DISK
    names = load_spell_names(d64.D64.open(disk))

    out: list[str] = []
    w = out.append
    w("# Spell table")
    w("")
    w("**Generated** — run `python3 tools/genspells.py`. Read straight off a")
    w("game disk, so the spellings are the game's own.")
    w("")
    w("A character's memorised spells are a packed list of these ids at record")
    w("offset `0x020`, highest spell level first. The file format is described")
    w("in `por/spells.py`; the short version is that the strings **overlap** —")
    w("`CURE LIGHT WOUNDS` and `CAUSE LIGHT WOUNDS` share one copy of")
    w("` LIGHT WOUNDS` — so the table has to be read through its pointers.")
    w("")
    w("The ids run cleric level 1, magic-user level 1, cleric level 2, and so")
    w("on. Each group is alphabetical, with a reversed spell following the one")
    w("it reverses. Every id seen in a real save falls in the group its")
    w("caster's class predicts.")
    w("")
    for low, high, cls, level in SPELL_GROUPS:
        w(f"## {cls.capitalize()}, level {level}  (`{low}`–`{high}`)")
        w("")
        w("| id | spell |")
        w("|---|---|")
        for i in range(low, high + 1):
            if i in names:
                w(f"| {i} | {names[i]} |")
        w("")
    w(f"## Outside the player's list")
    w("")
    w(f"`{SPELL_RESTORATION}` is **{names.get(SPELL_RESTORATION, '?')}**, a")
    w("cleric spell of far higher level than Pool of Radiance grants a player,")
    w("so it is presumably the temple's. Its level is not worth guessing.")
    w("")
    w(f"From `{LAST_SPELL + 1}` the same table continues with **combat message")
    w("fragments** rather than spells — they share the mechanism and not the")
    w("meaning. `wish` refuses to write an id above")
    w(f"`{LAST_SPELL}` into a spell list for that reason.")
    w("")
    w("| id | text |")
    w("|---|---|")
    for i in sorted(names):
        if i > LAST_SPELL:
            w(f"| {i} | {names[i]} |")
    w("")
    OUT.write_text("\n".join(out) + "\n")
    print(f"wrote {OUT} ({len(out)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
