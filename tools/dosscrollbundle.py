#!/usr/bin/env python3
"""The four bytes at the end of a DOS Silver Blades item, and what hangs off them.

`#254 (Two DOS gaps the Amiga port gives a shape to: a 16-bit field in
gap_13c, and a pointer at the end of the Silver Blades item)`.  Silver Blades'
item is 67 bytes where the other titles' is 63, and the four extra at
`0x03F`-`0x042` are a **far pointer to another 67-byte item node**.  It is
used by one item type: `type_index` `0x49`, a bundle of scrolls made by the
JOIN command, whose `quantity` sub-scrolls hang off it, each node carrying
three more spell ids in its own `charges`, `effect` and `power`.

    tools/dosscrollbundle.py sites --game SECRET
    tools/dosscrollbundle.py census
    tools/dosscrollbundle.py read ~/wish-specimens/por-dos/WISH-SPEC-.../CHRDATD1.SAV

**The chain is on disk, not only in the heap.**  The `.STF` writer
(`SECRET GAME.OVR 0x24B29`) walks the character's item chain writing 67 bytes
per item and, when an item's `type_index` is `0x49`, writes its `quantity`
sub-nodes straight after it; the reader at `0x258D5` reads to end of file and
rebuilds the chain the same way.  `item_count` counts head items only -- the
routine that recomputes it (`0x3A2C7`) walks `next` at `0x02A` and never
`0x03F` -- so a file holding a bundle has **more 67-byte records than the
record's `item_count`**, and a reader that takes the first `item_count` of
them reads a bundle's spell nodes as items and loses that many real ones off
the end.  `walk` below is the engine's own shape; `slice_naively` is the other
one, and `census` reports where they disagree.

`sites` prints the code this rests on, with the five 63-byte titles as
controls: their items end at `0x03E`, so an `es:[di+0x3f]` there cannot be an
item field, and **none of the five loads a far pointer from that
displacement** where Silver Blades does it 41 times.  Read the far-pointer
column and not the raw count: Treasures of the Savage Frontier makes fifteen
byte and word accesses at `0x03F` belonging to some other structure, and how
a build spells `p := q^.next` differs between them -- Silver Blades emits
`les`, Curse and Pool of Radiance two word moves -- so a count of `les` is a
count of one compiler's habit as much as of a field.

Nothing here writes anything; the player's files are opened read only.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos_port  # noqa: E402
from tools import dosbox, dosfieldrefs  # noqa: E402

#: The item type whose `0x03F` pointer is a chain: a bundle of scrolls.  The
#: only place the engine writes this type is the JOIN routine
#: (`SECRET GAME.OVR 0x2951B`), which sets `quantity` to 1, zeroes the head's
#: own three spell bytes and hangs the joined scroll off the pointer.
SCROLL_BUNDLE = 0x49

#: The three item types the engine tests together -- `cmp es:[di+0x2e], 0x27`,
#: `0x28`, `0x49`, four times over in `SECRET GAME.OVR` (`0x293A6`, `0x29446`,
#: `0x295EE`, `0x32A9C`).  The first two are what the shipped `ITEM<n>.DAX`
#: templates carry: 39 on every `Mage Scroll` and 40 on every `Cler Scroll`,
#: and **no template is a bundle**, because a bundle is made in the game.
SCROLL_TYPES = {0x27: "mage scroll", 0x28: "cleric scroll",
                SCROLL_BUNDLE: "a joined bundle"}

#: Where the chain pointer sits in a 67-byte item, and how wide it is.  The
#: three 63-byte titles have neither.
CHAIN = 0x03F
CHAIN_SIZE = 4

#: Displacements to census, and what each one is in a 67-byte item.
DISPLACEMENTS = {0x02A: "next item, the main chain",
                 0x03F: "the scroll-bundle chain (Silver Blades only)",
                 0x041: "its segment half"}


def item_size(record_size: int) -> int:
    return dos_port.deltas_for(record_size).item_size


def walk(items: bytes, stride: int) -> list[dict]:
    """The item file as the engine reads it: heads, each with its sub-nodes.

    Returns one entry per **head** item, `{"offset", "type", "quantity",
    "subnodes"}`, where `subnodes` is the list of record indices the engine
    would hang off it.  Raises `ValueError` when the file runs out mid-chain,
    which is what a wrong stride looks like.
    """
    out: list[dict] = []
    n = len(items) // stride
    i = 0
    while i < n:
        head = items[i * stride:(i + 1) * stride]
        entry = {"index": i, "type": head[0x02E], "quantity": head[0x039],
                 "subnodes": []}
        i += 1
        if stride > 63 and head[0x02E] == SCROLL_BUNDLE:
            for _ in range(head[0x039]):
                if i >= n:
                    raise ValueError(
                        f"item {entry['index']} is a bundle of "
                        f"{entry['quantity']} and the file ends at {i}")
                entry["subnodes"].append(i)
                i += 1
        out.append(entry)
    return out


def slice_naively(items: bytes, stride: int, count: int) -> list[int]:
    """The first `count` records, which is what a flat reader takes."""
    return list(range(min(count, len(items) // stride)))


def spells_of(items: bytes, stride: int, entry: dict) -> list[int]:
    """A scroll's spell ids: its own three, or three per sub-node.

    The engine reads `node[0x3C]`, `[0x3D]`, `[0x3E]` with the top bit as a
    flag of its own (`SECRET GAME.OVR 0x1B2AA`, `0x2C0C8`), so the id is the
    low seven bits.  A zero is an empty slot -- `MAGE SCROLL 1 SPELL` is one
    id and two zeros.  Empty for anything that is not a scroll, where those
    three bytes are `charges`, `effect` and `power`.
    """
    if entry["type"] not in SCROLL_TYPES:
        return []
    nodes = entry["subnodes"] or [entry["index"]]
    out = []
    for index in nodes:
        node = items[index * stride:(index + 1) * stride]
        out += [b & 0x7F for b in node[0x03C:0x03F] if b]
    return out


def item_count(record: bytes) -> int:
    fields = {f.name: f for f in dos_port.layout_for(len(record))}
    return record[fields["item_count"].offset]


def siblings(root: pathlib.Path):
    """`(record path, record bytes, item bytes)` for every DOS record beneath
    `root` that has an item file beside it."""
    sizes = {285, 422, 439, 510}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.upper() not in (".SAV", ".CHA"):
            continue
        try:
            record = path.read_bytes()
        except OSError:
            continue
        if len(record) not in sizes:
            continue
        shape = dos_port.deltas_for(len(record))
        item_path = path.with_suffix(shape.item_suffix)
        if not item_path.is_file():
            continue
        yield path, record, item_path.read_bytes()


def default_roots() -> list[pathlib.Path]:
    from tools import specimens
    out = []
    tree = specimens.tree_root()
    if tree.is_dir():
        out.append(tree)
    if dosbox.ARCHIVES.is_dir():
        out.append(dosbox.ARCHIVES)
    return out


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_sites(args) -> int:
    from tools.dosxpaward import GAMES, find_game
    stems = [args.game] if args.game else sorted(GAMES)
    for stem in stems:
        try:
            game = find_game(stem)
        except FileNotFoundError as exc:
            print(f"=== {stem}: {exc}")
            continue
        ovr = (game / "GAME.OVR").read_bytes()
        stride = item_size(GAMES[stem])
        print(f"=== {stem}, a {stride}-byte item")
        for disp, what in DISPLACEMENTS.items():
            refs = dosfieldrefs.references(ovr, disp, prefixes=(0x26,))
            kinds = collections.Counter(r["mnem"] for r in refs)
            far = sum(1 for r in refs if r["mnem"].startswith(("les", "lds")))
            print(f"    {disp:#05x}  {len(refs):3} instructions, {far:3} of "
                  f"them a far-pointer load -- {what}")
            if kinds:
                print("           " + ", ".join(
                    f"{n} x {m}" for m, n in sorted(kinds.items())))
        gate = ovr.count(b"\x26\x80\x7d\x2e" + bytes([SCROLL_BUNDLE]))
        made = ovr.count(b"\x26\xc6\x45\x2e" + bytes([SCROLL_BUNDLE]))
        print(f"    type {SCROLL_BUNDLE:#04x}: {gate} comparisons, {made} "
              f"store{'' if made == 1 else 's'} of it into an item")
    return 0


def cmd_read(args) -> int:
    for name in args.roots:
        path = pathlib.Path(name)
        record = path.read_bytes()
        shape = dos_port.deltas_for(len(record))
        items = path.with_suffix(shape.item_suffix).read_bytes()
        stride = shape.item_size
        print(f"=== {path.name}: {len(items)} bytes at {stride}, "
              f"item_count {item_count(record)}")
        for entry in walk(items, stride):
            node = items[entry["index"] * stride:(entry["index"] + 1) * stride]
            text = node[1:1 + node[0]].decode("latin-1", "replace").strip()
            extra = (f"  bundle of {entry['quantity']} -> records "
                     f"{entry['subnodes']}" if entry["subnodes"] else "")
            spells = spells_of(items, stride, entry)
            print(f"  {entry['index']:3} type {entry['type']:3} "
                  f"qty {entry['quantity']:3}  {text:34}{extra}"
                  + (f"  spells {spells}" if spells else ""))
    return 0


def cmd_census(args) -> int:
    roots = [pathlib.Path(p) for p in args.roots] or default_roots()
    files = bundles = mismatched = exports = 0
    for root in roots:
        if not root.is_dir():
            print(f"  (no {root})")
            continue
        for path, record, items in siblings(root):
            stride = item_size(len(record))
            files += 1
            count = item_count(record)
            records = len(items) // stride
            try:
                entries = walk(items, stride)
            except ValueError as exc:
                print(f"  {path}: {exc}")
                continue
            here = [e for e in entries if e["subnodes"]]
            if here:
                bundles += len(here)
                print(f"  {path}: {len(here)} scroll bundle(s), "
                      f"{records} records against an item_count of {count}")
            if count == 0:
                # An export zeroes `item_count` and may sit beside an item
                # file from an earlier save; `goldbox.dos.read_character`
                # documents that and hands back no items.
                exports += 1
            elif records != count:
                mismatched += 1
                print(f"  {path}: {records} records, item_count {count}")
    print(f"{files} item files, {bundles} scroll bundles, {mismatched} where "
          f"the record count is not item_count, {exports} with an item_count "
          f"of zero (an export beside a stale item file)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("sites", "census", "read"))
    ap.add_argument("roots", nargs="*",
                    help="census: directories to sweep; read: record files")
    ap.add_argument("--game", default=None,
                    help="sites: one game directory stem instead of all six")
    args = ap.parse_args(argv)
    return {"sites": cmd_sites, "census": cmd_census,
            "read": cmd_read}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
