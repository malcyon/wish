#!/usr/bin/env python3
"""Generate docs/85-item-tables.md from a game disk.

Two tables live on the game disk and neither is in this repo as data:

  ITEMNAMES  the 255-entry word table an item's name is assembled from
  ITEMS      128 item *type* records -- damage, protection, class usage

Both are read straight off the disk, so the names here carry no
transcription errors. Run after changing por/items.py:

    python3 tools/genitems.py [GAME.D64]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from por import d64  # noqa: E402
from por.items import load_item_names  # noqa: E402

DEFAULT_DISK = "work/POOL1.D64.orig"
OUT = Path(__file__).resolve().parent.parent / "docs" / "85-item-tables.md"

CLASS_BITS = ((1, "magic-user"), (2, "cleric"), (4, "thief"), (8, "fighter"))


def dice(n: int, sides: int, bonus: int) -> str:
    if not n or not sides:
        return "—"
    return f"{n}d{sides}" + (f"+{bonus}" if bonus else "")


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
    w("**word table** below — noun, qualifier, suffix — which the game prints in")
    w("that order: `CLOAK` + `OF` + `DISPLACEMENT`, `BANDED` + `MAIL` + `+1`.")
    w("It also stores an index into the **type table**, which is where damage,")
    w("armour protection and class restrictions come from.")
    w("")
    w("## The word table (`ITEMNAMES`)")
    w("")
    w(f"{len(names)} entries. Indices are **1-based** — the value an item record")
    w("stores is the key here, with no adjustment.")
    w("")
    gaps = [i for i in range(1, max(names) + 1) if i not in names]
    w(f"Three indices carry no name: {', '.join(str(g) for g in gaps)}. They are")
    w("real gaps in the pointer table, not empty strings, and reading the file")
    w("by splitting strings in order instead of following its pointers closes")
    w("them and shifts every later name onto a wrong — but plausible — value.")
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
    w("128 records of 16 bytes, loading at `$7600`. An item record's byte `+0`")
    w("indexes this table. Only entries something refers to are listed.")
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
    w("| `+7` | weapon class |")
    w("| `+8` | melee usable |")
    w("| `+9`–`+11` | damage vs medium: dice, sides, bonus |")
    w("| `+12` | range |")
    w("| `+13` | class usage bitmask, same bits as `class_bits` |")
    w("| `+14` | missile type |")
    w("")
    w("**Protection** (`+6`) is `0` for anything that is not armour. For body")
    w("armour the high bits read `$B0` and the low nibble is `12 - AC`; for a")
    w("shield they read `$80` and the low nibble is the AC bonus.")
    w("")
    w("| # | vs large | vs medium | AC | hands | rate | range | usable by |")
    w("|---|---|---|---|---|---|---|---|")
    for idx in range(len(types) // 16):
        r = types[idx * 16:(idx + 1) * 16]
        if not any(r):
            continue
        prot = r[6] & 0x0F
        if r[6] & 0xF0 == 0xB0:
            ac = str(12 - prot)
        elif r[6]:
            ac = f"+{prot}"
        else:
            ac = "—"
        w(f"| {idx} | {dice(r[2], r[3], r[4])} | {dice(r[9], r[10], r[11])} | "
          f"{ac} | {r[1] or '—'} | {r[5] or '—'} | {r[12] or '—'} | "
          f"{classes(r[13] & 0x0F)} |")
    w("")
    OUT.write_text("\n".join(out) + "\n")
    print(f"wrote {OUT} ({len(out)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
