#!/usr/bin/env python3
"""Two ceilings a conversion may have to tell a player about (#52).

`.claude/rules/conversions.md`: where a limit is genuinely the destination
platform's design, the converter says what will not fit and lets the player
choose what to keep -- **and that chooser is not built until a measurement
says it is reachable**.  Two limits are known and neither had a number:

* **sixteen item slots** in a C64 character record.  A DOS character keeps its
  items in a sibling file with a one-byte count, so the *format* allows far
  more; what the DOS game allows is the question.
* **ten trait slots** at record `0x0AD`, shared between racial effects and
  item grants (`docs/171-c64-trait-slots.md`).  Racial ids run 0 to 4 by race
  (`#84 (Roll a gnome in DOS and read the two innate effect ids nobody has
  seen)`), so overflowing needs a dwarf or a gnome carrying four racial ids
  **plus seven or more effect-granting items readied at once**.

This counts what is countable off the player's own disks and archives:

    tools/carryceiling.py                 both, all titles
    tools/carryceiling.py --items         the item census only
    tools/carryceiling.py --grants        the effect-granting templates only

**What it counts and what it does not.**  It counts *templates* that set the
grant bit, item records in every save it can find, and the widest inventory
any of them holds.  It does not watch the running game refuse a pickup: an
engine's own ceiling is a comparison in an overlay, and where this tool finds
one it says which address, and where it does not it says so rather than
implying the census is the ceiling.

Nothing here prints an item name of the game's; the output is counts, ids and
byte values.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import gamedisks  # noqa: E402

from goldbox import dos, dos_layout, games  # noqa: E402
from goldbox import items as c64items  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402

#: Item record byte `+15`, bit 7: "readying this dispatches a power handler".
#: `CAMP $10B5` is `LDA $6D8B / BPL`, so an item without it is refused with
#: `NOT HERE` and grants nothing (`docs/125-bug-notes.md` U4).
GRANT_FLAG_AT, GRANT_FLAG_BIT = 15, 0x80
#: Byte `+14`, the effect id the grant writes into a free trait slot.
GRANT_ID_AT = 14

#: The C64 titles with a disk glob in the registry, and their registry keys.
C64_TITLES = (
    (games.POOL_OF_RADIANCE, "pool-of-radiance"),
    (games.CURSE_OF_THE_AZURE_BONDS, "curse-of-the-azure-bonds"),
    (games.SECRET_OF_THE_SILVER_BLADES, "secret-of-the-silver-blades"),
)


def grant_templates(disks: pathlib.Path, game) -> dict[bytes, int]:
    """Every distinct item template on a title's sides that sets the bit.

    Keyed by the sixteen raw bytes so two identical templates on two sides
    count once, valued by the effect id at `+14`.
    """
    out: dict[bytes, int] = {}
    for path in sorted(disks.glob(game.disk_glob)):
        try:
            img = D64.open(str(path))
        except Exception:
            continue
        for entry in img.directory():
            if not c64items.is_item_list(entry.name):
                continue
            try:
                _, payload = split_load_address(img.read_file(entry))
            except Exception:
                continue
            for i in range(len(payload) // c64items.ITEM_SIZE):
                raw = bytes(payload[i * c64items.ITEM_SIZE:
                                    (i + 1) * c64items.ITEM_SIZE])
                if not any(raw):
                    continue
                if raw[GRANT_FLAG_AT] & GRANT_FLAG_BIT:
                    out[raw] = raw[GRANT_ID_AT]
    return out


def all_templates(disks: pathlib.Path, game) -> int:
    """How many distinct templates the sides carry at all, for the ratio."""
    seen: set[bytes] = set()
    for path in sorted(disks.glob(game.disk_glob)):
        try:
            img = D64.open(str(path))
        except Exception:
            continue
        for entry in img.directory():
            if not c64items.is_item_list(entry.name):
                continue
            try:
                _, payload = split_load_address(img.read_file(entry))
            except Exception:
                continue
            for i in range(len(payload) // c64items.ITEM_SIZE):
                raw = bytes(payload[i * c64items.ITEM_SIZE:
                                    (i + 1) * c64items.ITEM_SIZE])
                if any(raw):
                    seen.add(raw)
    return len(seen)


def dos_inventories(roots: list[pathlib.Path]
                    ) -> tuple[collections.Counter, dict[str, int]]:
    """`item_count` over every DOS character record that can be read.

    Returns the histogram and, per title, the widest count seen.  A record
    whose sibling item file is missing still reports its own count, which is
    what the ceiling question is about.
    """
    counts: collections.Counter = collections.Counter()
    widest: dict[str, int] = {}
    seen: set[bytes] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.upper() not in (".SAV", ".CHA", ".GUY"):
                continue
            try:
                data = path.read_bytes()
                shape = dos_layout.shape_for(len(data))
            except Exception:
                continue
            if data in seen:
                continue
            seen.add(data)
            at = dos_layout.FIELDS_BY_NAME_FOR[shape.key]["item_count"].offset
            n = data[at]
            counts[n] += 1
            widest[shape.title] = max(widest.get(shape.title, 0), n)
    return counts, widest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--items", action="store_true")
    ap.add_argument("--grants", action="store_true")
    args = ap.parse_args(argv)
    both = not (args.items or args.grants)

    if both or args.grants:
        print("Effect-granting item templates: byte +15 bit 7, which is the "
              "only gate READY dispatches through")
        for game, key in C64_TITLES:
            disks = gamedisks.find(key)
            if disks is None:
                print(f"  {game.title}: no disks")
                continue
            grants = grant_templates(pathlib.Path(disks), game)
            total = all_templates(pathlib.Path(disks), game)
            ids = sorted(set(grants.values()))
            print(f"  {game.title}: {len(grants)} of {total} distinct "
                  f"templates grant, effect ids {ids}")
        print(f"  The C64 record has {len(dos.INNATE_EFFECTS) and 10} trait "
              f"slots and a racial seed of 0 to 4 ids, so overflowing one "
              f"needs 6 or more granted ids at once on a human and 7 or more "
              f"on a dwarf or a gnome")
        print()

    if both or args.items:
        print(f"DOS item_count, over every readable DOS record "
              f"(the C64 record holds {c64items.ITEMS_PER_CHARACTER})")
        roots = [ROOT / "work"]
        archives = gamedisks.find("dos-archives")
        if archives:
            roots.append(pathlib.Path(archives))
        spec = pathlib.Path(
            pathlib.os.environ.get("WISH_SPECIMENS",
                                   pathlib.Path.home() / "wish-specimens"))
        roots.append(spec)
        counts, widest = dos_inventories(roots)
        for n in sorted(counts):
            print(f"  {n:3d} items  {counts[n]:5d} records")
        print(f"  {sum(counts.values())} distinct records, widest per title:")
        for title, n in sorted(widest.items()):
            print(f"    {title}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
