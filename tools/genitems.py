#!/usr/bin/env python3
"""Generate docs/85-item-tables.md from a game disk.

Two tables live on the game disk and neither is in this repo as data:

  ITEMNAMES  a 256-entry pointer table, of which 252 carry a word an item's
             name is assembled from -- index 0 is unused and 62, 63 and 168
             are real gaps
  ITEMS      128 item *type* records -- damage, protection, class usage

Both are read straight off the disk, so the names here carry no
transcription errors. Run after changing por/items.py:

    python3 tools/genitems.py [GAME.D64]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from por import d64  # noqa: E402
from por.items import (  # noqa: E402
    NAMES_TABLE_ENTRIES,
    ItemType,
    load_item_names,
)

DEFAULT_DISK = "work/POOL1.D64.orig"
OUT = Path(__file__).resolve().parent.parent / "docs" / "85-item-tables.md"

CLASS_BITS = ((1, "magic-user"), (2, "cleric"), (4, "thief"), (8, "fighter"))
DAMAGE_TYPES = {0: "slashing", 1: "piercing", 128: "bludgeoning"}
WEAPON_FLAGS = ((1, "arrows"), (2, "ranged"), (4, "strength"),
                (8, "multi-shot"), (16, "thrown"), (128, "bolts"))


def dice(n: int, sides: int, bonus: int) -> str:
    if not n or not sides:
        return "—"
    return f"{n}d{sides}" + (f"+{bonus}" if bonus else "")


def flags(bits: int) -> str:
    set_ = [name for bit, name in WEAPON_FLAGS if bits & bit]
    return ", ".join(set_) if set_ else "—"


def classes(bits: int) -> str:
    used = [name for bit, name in CLASS_BITS if bits & bit]
    return ", ".join(used) if used else "—"


def main() -> int:
    disk = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DISK
    img = d64.D64.open(disk)
    names = load_item_names(img)
    types = img.read_file(b"ITEMS")[2:]

    out: list[str] = []
    w = out.append
    w("# Item tables")
    w("")
    w("**Generated** — run `python3 tools/genitems.py` after changing")
    w("`por/items.py`. Both tables are read directly off a game disk, so the")
    w("spellings are the game's own.")
    w("")
    w("An item record does not store a name. It stores three indices into the")
    w("**word table** below, at its bytes `+1`, `+2` and `+3`, and the game")
    w("prints them in the **opposite** order: `+3` is the noun, `+2` the")
    w("qualifier, `+1` the suffix, so `CLOAK` + `OF` + `DISPLACEMENT` and")
    w("`BANDED` + `MAIL` + `+1` are stored back to front. It also stores an")
    w("index into the **type table**, which is where damage, armour protection")
    w("and class restrictions come from.")
    w("")
    w("## The word table (`ITEMNAMES`)")
    w("")
    gaps = [i for i in range(1, max(names) + 1) if i not in names]
    w(f"{len(names)} words, out of a {NAMES_TABLE_ENTRIES}-entry pointer table "
      f"whose index 0 is")
    w("unused. Indices are **1-based** — the value an item record stores is the")
    w("key here, with no adjustment.")
    w("")
    w(f"Indices {', '.join(str(g) for g in gaps)} carry no name. They are real "
      f"gaps in the pointer")
    w("table, not empty strings, and reading the file by splitting strings in")
    w("order instead of following its pointers closes them and shifts every")
    w("later name onto a wrong — but plausible — value.")
    w("")
    w("| # | word | # | word | # | word | # | word |")
    w("|---|---|---|---|---|---|---|---|")
    keys = sorted(names)
    rows = (len(keys) + 3) // 4
    cols = [keys[i * rows:(i + 1) * rows] for i in range(4)]
    for r in range(rows):
        cells = []
        for c in cols:
            if r < len(c):
                cells += [str(c[r]), names[c[r]]]
            else:
                cells += ["", ""]
        w("| " + " | ".join(cells) + " |")
    w("")
    w("## The type table (`ITEMS`)")
    w("")
    w("128 records of 16 bytes, loading at `$7B00` — not the `$7600` its PRG")
    w("header claims, which is the address `docs/125-bug-notes.md` R51 and")
    w("`docs/127-community-formats.md` are talking about. An item record's byte")
    w("`+0` indexes this table. Records that are 16 zero bytes are left out;")
    w("nothing here checks whether anything refers to the rest.")
    w("")
    w("Layout, in the order the fields appear:")
    w("")
    w("| Byte | Field |")
    w("|---|---|")
    w("| `+0` | location / slot the item occupies |")
    w("| `+1` | hands required |")
    w("| `+2`–`+4` | damage vs large: dice, sides, bonus |")
    w("| `+5` | rate of fire |")
    w("| `+6` | protection — see below |")
    w("| `+7` | damage type: `0` slashing, `1` piercing, `128` bludgeoning |")
    w("| `+8` | unknown; `0` or `128`, set on weapons and quarrels only |")
    w("| `+9`–`+11` | damage vs medium: dice, sides, bonus |")
    w("| `+12` | range |")
    w("| `+13` | class usage bitmask, same bits as `class_bits` |")
    w("| `+14` | weapon flags — see below |")
    w("| `+15` | zero throughout |")
    w("")
    w("**Protection** (`+6`) is `0` for anything that does not affect armour")
    w("class. Bit 7 means it does, and the low **seven** bits carry the")
    w("family's `60 - value` bias: `60 - (byte & 0x7F)`, the same encoding")
    w("THAC0 and armour class use. Body armour stores a class that way (`$B9`")
    w("→ AC 3, plate; `$B4` → AC 8, leather); a shield and the magical")
    w("protective items store a small flat bonus instead (`$81` = +1), and the")
    w("two are told apart by magnitude. Reading this as `$B0` plus a `12 - AC`")
    w("nibble is the same arithmetic over a narrower range and agrees on every")
    w("armour the disks carry; the two diverge at AC 13, where `$AF` is 13")
    w("under the general rule and -3 under the nibble one.")
    w("")
    w("**Weapon flags** (`+14`) are a bitfield, not a missile type: bit 0")
    w("needs arrows, bit 1 ranged, bit 2 adds the strength bonus, bit 3")
    w("multi-shot, bit 4 throwable, bit 7 needs bolts. `4` is a plain melee")
    w("weapon, `20` a thrown one, `11` a bow, `15` a composite bow, `138` a")
    w("crossbow, `26` a sling.")
    w("")
    w("| # | vs large | vs medium | AC | damage type | flags | hands | rate | "
      "range | usable by |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for idx in range(len(types) // 16):
        r = types[idx * 16:(idx + 1) * 16]
        if not any(r):
            continue
        # por.items owns the protection rule; reading the byte a second way
        # here is how docs/85 came to carry a nibble rule the library had
        # already dropped.
        t = ItemType(index=idx, raw=bytes(r))
        value = t.armour_class
        if value is None:
            ac = "—"
        elif t.is_shield:
            ac = f"+{value}"
        else:
            ac = str(value)
        # +7 and +14 describe how a weapon hits, so they are noise on a suit
        # of armour -- every non-weapon reads 0, which would print "slashing".
        kind = DAMAGE_TYPES.get(r[7], str(r[7])) if t.is_weapon else "—"
        w(f"| {idx} | {dice(r[2], r[3], r[4])} | {dice(r[9], r[10], r[11])} | "
          f"{ac} | {kind} | {flags(r[14])} | "
          f"{r[1] or '—'} | {r[5] or '—'} | {r[12] or '—'} | "
          f"{classes(r[13] & 0x0F)} |")
    w("")
    OUT.write_text("\n".join(out) + "\n")
    print(f"wrote {OUT} ({len(out)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
