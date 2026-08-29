#!/usr/bin/env python3
"""Generate docs/87-item-templates.md -- every item on the game disks.

These are the records `wish` copies when a YAML item entry names a `template`.

    python3 tools/gentemplates.py [GAME.D64]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldbox.items import (  # noqa: E402
    Item,
    load_item_names,
    load_item_templates,
    load_item_types,
)

DEFAULT_DISK = "/mnt/media/roms/c64/Pool of Radiance Disks/POOL1.D64"
OUT = Path(__file__).resolve().parent.parent / "docs" / "87-item-templates.md"


def main() -> int:
    disk = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DISK
    names = load_item_names(disk)
    types = load_item_types(disk)
    templates = load_item_templates(disk, names)

    out: list[str] = []
    w = out.append
    w("# Item templates")
    w("")
    w("**Generated** — run `python3 tools/gentemplates.py`. Every distinct item")
    w("record on the eight game disks, read out of the `ITEMFILE*` shop and")
    w("encounter lists.")
    w("")
    w("Name any of these as a `template:` in a `wish` item entry and the whole")
    w("16-byte record is copied, then your fields are applied over it:")
    w("")
    w("```yaml")
    w("      - template: LONG SWORD +1")
    w("        readied: true")
    w("```")
    w("")
    w("This is the right way to add a magical item. Building one from `words`")
    w("and `type` leaves the bytes we do not understand at zero; a template")
    w("brings whatever the game actually puts there — including the effect")
    w("bytes at `+13`–`+15`, which on a scroll are its spells.")
    w("")
    w(f"{len(templates)} items.")
    w("")
    w("| Item | Cost | Weight | Effect |")
    w("|---|---|---|---|")
    for name in sorted(templates):
        it = Item(templates[name], names)
        kind = types.get(it.type_index)
        w(f"| {name} | {it.cost_gp} gp | {it.weight_lb} lb | "
          f"{kind.summary() if kind else '—'} |")
    w("")
    OUT.write_text(encoding="utf-8", data="\n".join(out) + "\n")
    print(f"wrote {OUT} ({len(out)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
