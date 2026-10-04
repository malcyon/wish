#!/usr/bin/env python3
"""The four bytes at the end of a DOS Silver Blades item, and what hangs off them.

`#254 (Two DOS gaps the Amiga port gives a shape to: a 16-bit field in
gap_13c, and a pointer at the end of the Silver Blades item)`.  Silver Blades'
item is 67 bytes where the other titles' is 63, and the four extra at
`0x03F`-`0x042` are a **far pointer to another 67-byte item node**.  It is
used by one item type: `type_index` `0x49`, a bundle of scrolls made by the
JOIN command, whose `quantity` sub-scrolls hang off it, each node carrying
three more spell ids in its own `charges`, `effect` and `power`.

    tools/dos/dosscrollbundle.py sites --game SECRET
    tools/dos/dosscrollbundle.py sweep
    tools/dos/dosscrollbundle.py read ~/wish-specimens/por-dos/WISH-SPEC-.../CHRDATD1.SAV

**The chain is on disk, not only in the heap.**  The `.STF` writer
(`SECRET GAME.OVR 0x24B29`) walks the character's item chain writing 67 bytes
per item and, when an item's `type_index` is `0x49`, writes its `quantity`
sub-nodes straight after it; the reader at `0x258D5` reads to end of file and
rebuilds the chain the same way.  `item_count` counts head items only -- the
routine that recomputes it (`0x3A2C7`) walks `next` at `0x02A` and never
`0x03F` -- so a file holding a bundle has **more 67-byte records than the
record's `item_count`**, and a reader that takes the first `item_count` of
them reads a bundle's spell nodes as items and loses that many real ones off
the end.  `walk` below is the engine's own form; `slice_naively` is the other
one, and `sweep` reports where they disagree.

`sites` prints the code this rests on, with the five 63-byte titles as
controls: their items end at `0x03E`, so an `es:[di+0x3f]` there cannot be an
item field, and **none of the five loads a far pointer from that
displacement** where Silver Blades does it 41 times.  Read the far-pointer
column and not the raw count: Treasures of the Savage Frontier makes fifteen
byte and word accesses at `0x03F` belonging to some other structure, and how
a build spells `p := q^.next` differs between them -- Silver Blades emits
`les`, Curse and Pool of Radiance two word moves -- so a count of `les` is a
count of one compiler's habit as much as of a field.

`stage` writes a copy of one Silver Blades slot whose members carry the
joined and loose scrolls asked for, for a DOSBox run to load:

    tools/dos/dosscrollbundle.py stage --slot A --out DIR \\
        --pack 2=j10*12,s*2,staff --pack 1=s*3 --pack 3=s*2

Only `stage` writes, and only into `--out`; the player's files are opened
read only.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos_codec, dos_port  # noqa: E402
from goldbox.neutral import ScrollBundle  # noqa: E402
from tools.dos import dosbox, dosfieldrefs  # noqa: E402

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

#: Displacements to sweep, and what each one is in a 67-byte item.
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
        deltas = dos_port.deltas_for(len(record))
        item_path = path.with_suffix(deltas.item_suffix)
        if not item_path.is_file():
            continue
        yield path, record, item_path.read_bytes()


def default_roots() -> list[pathlib.Path]:
    from tools.registry import specimens
    out = []
    tree = specimens.tree_root()
    if tree.is_dir():
        out.append(tree)
    if dosbox.ARCHIVES.is_dir():
        out.append(dosbox.ARCHIVES)
    return out


# --------------------------------------------------------------------------
# Staging a pack
# --------------------------------------------------------------------------

#: The items `stage` can put in a pack, by the item type it takes from the
#: title's own `ITEM<n>.DAX` templates (`item_templates`).  `scroll` is a mage
#: scroll, the only scroll JOIN has been seen to join.
ITEM_TYPES = {"scroll": 0x27, "staff": 0x0F, "darts": 0x05, "arrows": 0x1E}
ORDINARY = tuple(k for k in ITEM_TYPES if k != "scroll")
#: A template's stride: `ITEM<n>.DAX` blocks hold 63-byte records in every
#: title, Silver Blades included.
TEMPLATE_SIZE = 63
#: The head items a member may hold: a TRADE onto a member of 15 made 16 and
#: no more, and the Amiga port's limit is 16 (`/Secret` `0x24B50`), so a pack
#: of 17 is a state only an editor makes and `stage` blocks it.
MOST_HEADS = 16
#: The most scrolls `stage` puts in one joined scroll.  `GAME.OVR` holds
#: `Bundles are limited to <n> scrolls.`, the number filled in at run time
#: and not yet read; ten is PROBABLE until a JOIN onto a joined scroll of ten
#: is seen.
MOST_JOINED = 10
#: Silver Blades' spell table: `START.EXE` `DS:449D`, sixteen bytes an id,
#: byte 0 the class, 3 being magic-user, and byte 1 the level
#: (`tools/dos/dosspellslots.py --game SECRET sweep --verbose`).  Id 109 is a
#: magic-user spell of level 0, which no scroll is known to carry, so a staged
#: scroll takes only levels 1 to 9: 53 ids.
SPELL_TABLE, MAGIC_USER, SPELL_IDS = 0x449D, 3, range(1, 118)

_TOKEN = re.compile(r"(j(\d+)|s|[a-z]+)(?:\*(\d+))?")


def parse_pack(text: str) -> list[tuple[str, int]]:
    """A pack spec, comma separated, into `(kind, n)` in pack order.

    `jK` is a joined scroll of K scrolls, `s` a loose mage scroll, and a name
    of `ORDINARY` that item; `*N` repeats a token N times.
    `j10*12,s*2,staff` is twelve joined scrolls of ten, two loose scrolls
    and a quarter staff.
    """
    out: list[tuple[str, int]] = []
    for token in (t.strip() for t in text.split(",")):
        m = _TOKEN.fullmatch(token.lower())
        if m is None:
            raise ValueError(f"not a pack item: {token!r} (jK, s, or one of "
                             f"{', '.join(ORDINARY)}, each with an optional *N)")
        times = int(m.group(3) or 1)
        if m.group(2) is not None:
            k = int(m.group(2))
            if not 2 <= k <= MOST_JOINED:
                raise ValueError(f"a joined scroll holds 2 to {MOST_JOINED} "
                                 f"scrolls, not {k}")
            unit = ("joined", k)
        elif m.group(1) == "s":
            unit = ("scroll", 1)
        elif m.group(1) in ORDINARY:
            unit = (m.group(1), 1)
        else:
            raise ValueError(f"no item called {m.group(1)!r}: "
                             f"{', '.join(ORDINARY)}")
        if times < 1:
            raise ValueError(f"{token!r} repeats nothing")
        out += [unit] * times
    if len(out) > MOST_HEADS:
        raise ValueError(f"{len(out)} items; a member holds at most {MOST_HEADS}")
    return out


def scroll_spells(k: int, ids: list[int]) -> bytes:
    """Three different spell ids for the party's `k`th staged scroll, from 0.

    The first is `ids[k % n]` and the second the one `1 + k // n` places
    after it, so the ordered pair names `k` and no two scrolls carry the same
    ids while `k < n * (n - 1)`; the third is the next id not already used.
    """
    n = len(ids)
    if n < 3 or k >= n * (n - 1):
        raise ValueError(f"scroll {k}: {n} ids tell at most {n * (n - 1)} "
                         "scrolls apart")
    a = k % n
    b = (a + 1 + k // n) % n
    c = next(i % n for i in range(b + 1, b + 3) if i % n != a)
    return bytes((ids[a], ids[b], ids[c]))


def joined_head(scrolls: list[bytes]) -> bytes:
    """The sixteen bytes JOIN makes for `scrolls`, as a game-written save
    holds them: type 0x49, names 0x27, the count and 0x4D, the scrolls'
    plus, weight and quantity the count, value their sum, no spells.  The
    weight of a joined scroll of more than two is PROBABLE."""
    k = len(scrolls)
    value = sum(int.from_bytes(s[11:13], "little") for s in scrolls)
    return (bytes((dos_codec.SCROLL_BUNDLE_TYPE, 0x27, k, 0x4D, scrolls[0][4],
                   0, 0, 0)) + k.to_bytes(2, "little") + bytes((k,))
            + min(value, 0xFFFF).to_bytes(2, "little") + bytes(3))


def compose_pack(units: list[tuple[str, int]], ids: list[int], first: int,
                 items: dict[str, bytes]
                 ) -> tuple[list[bytes], tuple[ScrollBundle, ...], int]:
    """The neutral `inventory` and `scroll_bundles` for `units`, from the
    sixteen-byte `items` of `item_templates`, numbering scrolls from
    `first`; returns the next number too.  Only a scroll's three spell ids
    differ from its template."""
    inventory: list[bytes] = []
    bundles: list[ScrollBundle] = []
    k = first
    for kind, n in units:
        if kind in ORDINARY:
            inventory.append(items[kind])
            continue
        scrolls = []
        for _ in range(n):
            scrolls.append(items["scroll"][:13] + scroll_spells(k, ids))
            k += 1
        if kind == "joined":
            bundles.append(ScrollBundle(len(inventory), n, joined_head(scrolls)))
        inventory += scrolls
    return inventory, tuple(bundles), k


def item_templates(game: pathlib.Path) -> dict[str, bytes]:
    """One template of each `ITEM_TYPES` kind from the title's `ITEM<n>.DAX`,
    as sixteen bytes.

    Of each type, an unenchanted one (plus 0); of the scrolls, one carrying
    three spells, an unidentified one (hidden 4) first.  Ties go to the
    lowest bytes, so the choice does not depend on file order.
    """
    from goldbox import dos_savegame
    found: dict[str, list[bytes]] = {k: [] for k in ITEM_TYPES}
    for path in sorted(game.glob("ITEM*.DAX")):
        data = path.read_bytes()
        for entry in dos_savegame.dax_index(data):
            block = dos_savegame.dax_block(data, entry[0], path.name)
            if len(block) % TEMPLATE_SIZE:
                continue
            for i in range(len(block) // TEMPLATE_SIZE):
                item = dos_codec.item_to_c64(
                    bytes(block[i * TEMPLATE_SIZE:(i + 1) * TEMPLATE_SIZE]))
                for kind, type_index in ITEM_TYPES.items():
                    if item[0] != type_index:
                        continue
                    if kind == "scroll" and all(item[13:16]):
                        found[kind].append(item)
                    elif kind != "scroll" and item[4] == 0:
                        found[kind].append(item)
    missing = [k for k, v in found.items() if not v]
    if missing:
        raise FileNotFoundError(f"no {', '.join(missing)} template in "
                                f"{game}/ITEM*.DAX")
    return {k: min(v, key=lambda b: (b[6] & 0x07 != 4, b)) for k, v in found.items()}


def mage_spell_ids(game: pathlib.Path) -> list[int]:
    """Silver Blades' magic-user spell ids, read from its own spell table."""
    from tools.dos import dosspellslots
    image = dosspellslots.image_of(game, "START.EXE")
    base = dosspellslots.data_segment(image) * 16 + SPELL_TABLE
    return [i for i in SPELL_IDS if image[base + 16 * i] == MAGIC_USER
            and 1 <= image[base + 16 * i + 1] <= 9]


def stage(save: pathlib.Path, slot: str, packs: dict[int, list[tuple[str, int]]],
          out: pathlib.Path, ids: list[int], items: dict[str, bytes]) -> dict:
    """Copy slot `slot` of `save` into `out`, roster line N holding `packs[N]`.

    Each staged member is read, its pack replaced on the neutral record and
    written by `dos_codec.write`; the item file, `item_count` and
    `encumbrance` are taken from what it writes, and every other byte of the
    record is the slot's own.  Roster line N is the Nth `CHRDAT<slot><n>`
    file, which is the order the party menu draws.
    """
    slot = slot.upper()
    deltas = dos_port.SECRET_OF_THE_SILVER_BLADES
    party = dos_codec.read_party(save, slot)
    if any(c.deltas != deltas for c in party):
        raise ValueError(f"slot {slot} of {save} is not a Silver Blades party")
    for line in packs:
        if not 1 <= line <= len(party):
            raise ValueError(f"line {line} is not in a party of {len(party)}")
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError(f"{out} is not empty")
    for p in sorted(save.iterdir()):
        name = p.name.upper()
        if name == f"SAVGAM{slot}.DAT" or name.startswith(f"CHRDAT{slot}"):
            (out / name).write_bytes(p.read_bytes())
    fields = dos_port.FIELDS_BY_NAME_FOR[deltas.key]
    taken = [fields["item_count"], fields["encumbrance"]]
    k, report = 0, {"slot": slot, "from": str(save), "lines": {}}
    for line in sorted(packs):
        char = party[line - 1]
        inventory, bundles, k_next = compose_pack(packs[line], ids, k, items)
        neutral = dos_codec.to_neutral(char)
        neutral.set("inventory", inventory, "staged by dosscrollbundle.py stage")
        neutral.set("scroll_bundles", bundles, "staged by dosscrollbundle.py stage")
        record, itm, _spc, _rep = dos_codec.write(neutral, deltas=deltas)
        path = pathlib.Path(char.source)
        rec = bytearray(path.read_bytes())
        changed = []
        for f in taken:
            span = slice(f.offset, f.offset + f.size)
            if rec[span] != record[span]:
                changed.append(f"{f.name} {rec[span].hex()}->{record[span].hex()}")
            rec[span] = record[span]
        (out / path.name.upper()).write_bytes(bytes(rec))
        (out / path.with_suffix(deltas.item_suffix).name.upper()).write_bytes(itm)
        report["lines"][line] = {
            "file": path.name.upper(), "name": char.name.strip(),
            "items": len(packs[line]), "records": len(itm) // deltas.item_size,
            "scrolls": k_next - k, "first_scroll": k, "changed": changed,
            "joined": [b.count for b in bundles]}
        k = k_next
    return report


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_sites(args) -> int:
    from tools.dos.dosxpaward import GAMES, find_game
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
        deltas = dos_port.deltas_for(len(record))
        items = path.with_suffix(deltas.item_suffix).read_bytes()
        stride = deltas.item_size
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


def cmd_sweep(args) -> int:
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
                # file from an earlier save; `goldbox.dos_codec.read_character`
                # documents that and hands back no items.
                exports += 1
            elif records != count:
                mismatched += 1
                print(f"  {path}: {records} records, item_count {count}")
    print(f"{files} item files, {bundles} scroll bundles, {mismatched} where "
          f"the record count is not item_count, {exports} with an item_count "
          f"of zero (an export beside a stale item file)")
    return 0


def parse_packs(texts: list[str]) -> dict[int, list[tuple[str, int]]]:
    """`--pack N=SPEC` values into roster line -> pack."""
    packs: dict[int, list[tuple[str, int]]] = {}
    for text in texts:
        line, sep, spec = text.partition("=")
        if not sep or not re.fullmatch(r"[1-8]", line.strip()):
            raise ValueError(f"--pack {text!r}: say N=SPEC, N a roster line 1 to 8")
        if int(line) in packs:
            raise ValueError(f"--pack names line {line} twice")
        packs[int(line)] = parse_pack(spec)
    return packs


def cmd_stage(args) -> int:
    if not args.out or not args.pack:
        print("stage needs --out and at least one --pack", file=sys.stderr)
        return 2
    packs = parse_packs(args.pack)
    game = dosbox.find_game("SECRET")
    save = pathlib.Path(args.save_from) if args.save_from else game / "SAVE"
    report = stage(save, args.slot, packs, pathlib.Path(args.out),
                   mage_spell_ids(game), item_templates(game))
    print(json.dumps(report, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("sites", "sweep", "read", "stage"))
    ap.add_argument("roots", nargs="*",
                    help="sweep: directories to sweep; read: record files")
    ap.add_argument("--game", default=None,
                    help="sites: one game directory stem instead of all six")
    ap.add_argument("--from", dest="save_from", default=None,
                    help="stage: the save folder (default the archives' "
                         "Silver Blades SAVE)")
    ap.add_argument("--slot", default="A", help="stage: the slot letter")
    ap.add_argument("--out", default=None, help="stage: an empty folder to write")
    ap.add_argument("--pack", action="append", default=[],
                    help="stage: N=SPEC, roster line N's whole pack "
                         "(jK, s, staff, darts, arrows, each with *N)")
    args = ap.parse_args(argv)
    try:
        return {"sites": cmd_sites, "sweep": cmd_sweep, "read": cmd_read,
                "stage": cmd_stage}[args.cmd](args)
    except (ValueError, FileNotFoundError) as e:
        print(f"{args.cmd}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
