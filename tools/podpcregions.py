#!/usr/bin/env python3
"""Decode the tail of an Amiga *Pools of Darkness* `Save/NAME.pc`.

The loader reads 404 bytes of character record, then twenty bytes per item,
then ten per effect (`docs/124-amiga-port.md` §1.16).  The twenty bytes land
at heap-node offset `0x2E`, which is where `goldbox.amiga_port`'s later-Amiga item
node keeps `type_index` -- so the hypothesis this tool tests is that the
twenty bytes are the same seventeen DOS item fields, in the same order,
through :data:`goldbox.amiga_port.AMIGA_LATER_ITEM_SHIFTS`.

It reads the `.pc` files out of the disk images `tools/amigasaves.py` finds,
read-only, and prints every item's fields beside the sanity each one has to
pass.  Nothing of the game's is written anywhere.

    tools/podpcregions.py                 # every .pc an Amiga disk holds
    tools/podpcregions.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga_later, amiga_pod, amiga_port, dos_port  # noqa: E402

RECORD = 404          # what the loader reads into the character record
ITEM_FILE_SIZE = 20   # one item, as the file holds it
EFFECT_FILE_SIZE = 10
ITEM_NODE_BASE = 0x2E  # where the twenty bytes land in the heap node
ITEM_COUNT = 0x08     # longword in the record
EFFECT_CHAIN = 0x04   # longword in the record
SCROLL_TYPE = 0x49    # `cmpi.b #$49` in the loader -- SSB's scroll type_index


def pc_files() -> dict[str, bytes]:
    """Every `Save/*.pc` on an Amiga disk image this machine can see."""
    from goldbox.amiga_adf import AmigaDisk, AmigaDiskError
    from tools import amigasaves

    out: dict[str, bytes] = {}
    for _label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
            entries = list(disk.walk())
        except (AmigaDiskError, ValueError):
            continue
        for path, _entry in entries:
            if path.lower().endswith(".pc"):
                name = path.rsplit("/", 1)[-1]
                out.setdefault(name, disk.read_file(path))
    return out


def item_fields(node20: bytes) -> dict[str, int]:
    """The twenty file bytes read as the later-Amiga item node's fields."""
    shape = amiga_port.SILVER_BLADES_DELTAS          # the shifts, not the title
    out: dict[str, int] = {}
    for f in dos_port.ITEM_LAYOUT:
        if f.offset < ITEM_NODE_BASE:
            continue                            # display text and `next`
        at = shape.item_offset(f.offset) - ITEM_NODE_BASE
        if at + f.size > len(node20):
            continue
        out[f.name] = int.from_bytes(node20[at:at + f.size], "big")
    return out


def item_pads(node20: bytes) -> dict[str, int]:
    """The three bytes no DOS item field maps onto."""
    return {f"pad_{off:#04x}": node20[off - ITEM_NODE_BASE]
            for off in amiga_later.AMIGA_LATER_ITEM_PADS}


def read_pc(name: str, data: bytes) -> dict:
    count = int.from_bytes(data[ITEM_COUNT:ITEM_COUNT + 4], "big")
    chain = int.from_bytes(data[EFFECT_CHAIN:EFFECT_CHAIN + 4], "big")
    tail = data[RECORD:]
    items, at = [], 0
    while at + ITEM_FILE_SIZE <= len(tail) and len(items) < count:
        node = tail[at:at + ITEM_FILE_SIZE]
        row = item_fields(node)
        row["_scroll"] = int(row.get("type_index") == SCROLL_TYPE)
        row.update(item_pads(node))
        items.append(row)
        at += ITEM_FILE_SIZE
    effects = []
    while at + EFFECT_FILE_SIZE <= len(tail):
        effects.append(list(tail[at:at + EFFECT_FILE_SIZE]))
        at += EFFECT_FILE_SIZE
    char = amiga_pod.PodCharacter.from_bytes(data)
    return {"file": name, "name": char.name, "size": len(data),
            "item_count": count, "effect_chain": chain,
            "tail_bytes": len(tail), "items": items, "effects": effects,
            "leftover": len(tail) - at}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=pathlib.Path,
                    help="write the whole reading here")
    args = ap.parse_args()

    found = pc_files()
    if not found:
        print("no .pc files on any Amiga disk image this machine can see",
              file=sys.stderr)
        return 1
    out = [read_pc(n, d) for n, d in sorted(found.items())]
    for row in out:
        print(f"{row['file']:<14} {row['name']:<16} {row['size']:4d}B  "
              f"items={row['item_count']} chain={row['effect_chain']:#x} "
              f"tail={row['tail_bytes']} leftover={row['leftover']}")
        for i, it in enumerate(row["items"]):
            print(f"    item {i}: " + " ".join(
                f"{k}={v}" for k, v in it.items()))
        for e in row["effects"]:
            print("    effect: " + " ".join(f"{b:02x}" for b in e))
    if args.json:
        args.json.write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
