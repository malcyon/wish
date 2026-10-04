#!/usr/bin/env python3
"""Generate docs/86-spell-table.md from a game disk.

The spell names live in SPELLN00 and are not in this repo as data.

    python3 tools/generate/genspells.py [GAME.D64]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from automap import gamedisks  # noqa: E402
from goldbox import d64  # noqa: E402
from goldbox.spells import (  # noqa: E402
    LAST_SPELL,
    SPELL_GROUPS,
    SPELL_RESTORATION,
    load_spell_names,
)


def default_disk() -> str:
    where = gamedisks.find("pool-of-radiance")
    if where is None:
        sys.exit("No Pool of Radiance disks found; pass a disk, set POR_DISKS "
                 "or add the directory to gamedisks.yaml")
    return str(where / "POOL1.D64")



#: Where every port keeps its names, hand-written: the tables above are
#: generated from the C64 disk, and this section is the same on every run.
PORTS = """## Where each port keeps the names

`goldbox/spell_names.py` reads all of them at run time:
`spell_names(title, "c64" | "dos" | "amiga", where)`. Every table is found
from the instruction that indexes it, never from a stored address; the
addresses below are what that search finds on the builds here, for checking.

**The id is the table index on every port.** Each table's slot 0 is the id-0
slot no spell uses, so no DOS or Amiga build numbers a spell differently from
the C64: id for id, after dropping case and punctuation, the DOS names match
the C64's on all 56 Pool of Radiance spells, all but 2 of Curse's and all but
5 of Silver Blades', and the Amiga's match DOS on every spell of Pool of
Radiance and Curse. The exceptions are wording, and
`tests/records/test_spell_names.py` lists each id.

| title | DOS (`DS` offset, stride) | Amiga |
|---|---|---|
| Pool of Radiance | `START.EXE` `DS:28E9`, 41 (`String[40]`) | `/program` hunk 31 `+0x27CB`, `char[41]` cells |
| Curse of the Azure Bonds | `START.EXE` `DS:27BF`, 41 | `/Curse` small data `0x1D5A` (`-$62A4(a4)`), a pointer an id |
| Secret of the Silver Blades | `START.EXE` `DS:348B`, 35 (`String[34]`) | `/Secret` small data `0x253C` (`-$5AC2(a4)`) |
| Pools of Darkness | `GAME.EXE` `DS:53CD`, 35 | `/Pools of Darkness` small data `0x250A` (`-$5AF4(a4)`); the German build `0x2526` (`-$5AD8(a4)`) |

* **DOS.** The launcher is EXEPACK-packed (`goldbox/exepack.py` expands it);
  `DS` comes from the entry's far call into `System`'s initialiser
  (`0C7C`, `0ABE`, `0DE2`, `09E7`). `GAME.OVR` indexes the table as
  `mov dx, stride / mul dx / mov di, ax / add di, base` at five or six sites
  per title. Each slot is a Pascal string, zero-padded. The slots run from
  id 1 to exactly the last spell (56, 100, 117, 126) and the next slot is the
  start of the class-and-level table, which is how the names are told from
  the other tables indexed the same way.
* **Amiga Pool of Radiance** multiplies the id by 41 (`moveq #$29, d1` and a
  library multiply) and adds a relocated `lea $27cb.l, a0`; the `Spell:` line
  at `/program` `0x3982A` is one reader.
* **Amiga Curse, Silver Blades and Pools of Darkness** index a pointer array
  in the small-data hunk: the id shifted left twice (`asl.l`), then `lea d16(a4), a0 /
  move.l (a0, d0.l), -(a7)`, read by the `Spell:%s` and `%s%s` lines
  (`/Secret` `0x37BAC`, `/Pools of Darkness` `0x3479A`). Pools of Darkness'
  pointers run on past id 126 into eleven item names; the reader stops at 126.

What a non-spell id holds differs by port: empty in DOS and Amiga Curse,
`spell N` in DOS Silver Blades, an item that casts the spell in DOS Pools of
Darkness (57 `Potion Of Speed`), and the engine's own internal name on Amiga
Silver Blades, which also names its spells that way (`CLERIC DETECT MAGIC`,
`SHIELD SPELL`, `PROT NORM MISSILES`). **Silver Blades' id 109 is not a
named spell on either later port**: DOS calls it `spell 109` and the Amiga
`RESERVED`, where the C64 repeats `DEATH SPELL` -- the same id Pools of
Darkness' engine makes a druid spell.

**The `[a]` release of Amiga Pools of Darkness disk 1 is the German one, and
its program is crunched.** `/Pools of Darkness` there is StoneCracker 4.04
(`S404` at file offset 512, after a 76-byte stub hunk); `goldbox/stonecracker.py`
decrunches it in memory, from a format read off the decrunch routine in the
file itself, and `spell_names` reads the result like any other build. The
decrunched program is a different build from the English ones -- a 355,844-byte
code hunk against 316,128 -- with German text throughout, and its 134 named
entries (ids 1-137) are the English ones translated id for id: the same ids are empty, the
same ids repeat a name (12 of the English build's 13 repeated pairs; the German
text words Bestow Curse two ways at 44 and 100), and the names are ISO 8859-1 with
umlauts. The other Pools of Darkness disk-1 images here hold three uncrunched
English programs that differ by hash, and all three read the same names.
"""

OUT = Path(__file__).resolve().parent.parent.parent / "docs" / "86-spell-table.md"


def main() -> int:
    disk = sys.argv[1] if len(sys.argv) > 1 else default_disk()
    names = load_spell_names(d64.D64.open(disk))

    out: list[str] = []
    w = out.append
    w("# Spell table")
    w("")
    w("**Generated** — run `python3 tools/generate/genspells.py`. Read straight off a")
    w("game disk, so the spellings are the game's own.")
    w("")
    w("A character's memorised spells are a packed list of these ids at record")
    w("offset `0x020`, highest spell level first. The file format is described")
    w("in `goldbox/spells.py`; the short version is that the strings **overlap** —")
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
    w("## Outside the player's list")
    w("")
    w(f"`{SPELL_RESTORATION}` is **{names.get(SPELL_RESTORATION, '?')}**, a")
    w("cleric spell of far higher level than Pool of Radiance grants a player,")
    w("so it is presumably the temple's. Its level is left unguessed.")
    w("")
    w(f"From `{LAST_SPELL + 1}` the same table continues with **combat message")
    w("fragments** rather than spells — they share the mechanism and not the")
    w("meaning. `wish` will not write an id above")
    w(f"`{LAST_SPELL}` into a spell list for that reason.")
    w("")
    w("| id | text |")
    w("|---|---|")
    for i in sorted(names):
        if i > LAST_SPELL:
            w(f"| {i} | {names[i]} |")
    w("")
    w(PORTS.rstrip("\n"))
    w("")
    OUT.write_text(encoding="utf-8", data="\n".join(out) + "\n")
    print(f"wrote {OUT} ({len(out)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
