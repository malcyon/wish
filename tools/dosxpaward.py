#!/usr/bin/env python3
"""What the three unattributed bytes before a DOS record's portrait hold.

`#254 (Two DOS gaps the Amiga port gives a shape to: a 16-bit field in
gap_13c, and a pointer at the end of the Silver Blades item)`.  Every DOS Gold
Box record has an undecoded run just before `portrait_head` -- Pool of
Radiance's `gap_0b8`, Curse's and Gateway's `gap_13c`, Silver Blades' `gap_14e`
-- and it is the **experience a creature is worth**: a `u16le` base and, in the
four earlier engines, a `u8` awarded per hit point.  Pools of Darkness and
Treasures of the Savage Frontier keep the base alone.

    tools/dosxpaward.py sites --game CURSE
    tools/dosxpaward.py monsters --game SECRET
    tools/dosxpaward.py census

`sites` is the engine's own evidence and there are two kinds of it.

* The **award sum**: one routine per title walks the creature list at the end
  of a fight and accumulates `base + hp_rolled * per_hp` into a 32-bit total,
  right beside the money it pools -- which is AD&D 1st edition's own way of
  writing an experience value.  In Pools of Darkness the multiply is gone and
  the base is added on its own.
* The **script property dispatcher**, which is what names the field rather
  than merely locating it.  Each title's `GAME.OVR` carries a chain of
  `cmp ax, <id> / mov ax,[bp+6] / les di,[<the current character>] /
  mov es:[di+<offset>], ax`, and **the ids are C64 record offsets**: `0x0BB`
  copper, `0x0C1` gold, `0x119` hit points current, and `0x0F7`/`0x0F9` for
  this pair -- which `docs/80-fields-wanted.md` already had as CONFIRMED on
  the C64, GOBLIN GUARD 10 with 1 per hit point.

`monsters` reads the shipped `MON<n>CHA.DAX` creature records and prints the
two numbers, which is the measurement: DOS Pool of Radiance's GOBLIN GUARD is
10 and 1, HOBGOBLIN 20 and 2, OGRE 90 and 5 -- the C64's numbers and the
published table's.

`census` sweeps every DOS character record it can find -- the specimen tree
and the player's archives -- and counts how many carry a non-zero award, which
is how "this is a monster field and reads zero in a player" is stated as a
number rather than as an impression.

Offsets come from `goldbox/dos_layout.py`: the field named `experience_award`
if somebody has since named it, otherwise the gap that ends where the portrait
or icon block begins.  Nothing here writes anything, and the game's bytes stay
in the player's own directories.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos_layout, dos_savegame  # noqa: E402
from goldbox import layout as c64_layout  # noqa: E402
from tools import dosbox, dosfieldrefs  # noqa: E402

#: The six DOS engines of the family, with the record size each one uses.
#: `find_game` locates a title by the stem of its game directory; the three
#: that are not reachable that way are found by walking the archives, because
#: their executable is not called `START.EXE`.
GAMES: dict[str, int] = {
    "POOLRAD": 285, "CURSE": 422, "GATEWAY": 422, "SECRET": 439,
    "DARKNESS": 510, "TREASURE": 510,
}

#: The two script property ids this is about, in the C64's own offset space:
#: a word for the base award and a byte for the per-hit-point rate.
PROPERTY_AWARD = 0x0F7
PROPERTY_PER_HP = 0x0F9

#: `cmp ax, imm16 / jne short / mov ax|al, [bp+6] / les di, [imm16] /
#: mov es:[di+disp16], ax|al` -- one arm of the script property dispatcher.
#: The wildcard is the `jne` displacement, which differs per arm.
SETTER = re.compile(
    rb"\x3d(..)\x75.(\x8b\x46\x06|\x8a\x46\x06)\xc4\x3e..\x26(\x89\x85|\x88\x85)(..)",
    re.S)


def find_game(stem: str) -> pathlib.Path:
    """The game directory for one of `GAMES`, inside the player's archives."""
    try:
        return dosbox.find_game(stem)
    except FileNotFoundError:
        pass
    if not dosbox.ARCHIVES.is_dir():
        raise FileNotFoundError(f"no archives at {dosbox.ARCHIVES}")
    for collection in sorted(dosbox.ARCHIVES.iterdir()):
        games = collection / "games"
        if not games.is_dir():
            continue
        for entry in sorted(games.iterdir()):
            inner = entry / "GAME" / stem
            if (inner / "GAME.OVR").is_file():
                return inner
    raise FileNotFoundError(f"no DOS {stem} under {dosbox.ARCHIVES}")


def award_offsets(size: int) -> tuple[int, int | None]:
    """`(base, per_hit_point)` for a record of `size` bytes.

    Read off `goldbox/dos_layout.py` rather than written down here, so that
    naming the fields there moves this tool with it.  Until that happens the
    pair is the unnamed run that ends where the portrait block begins --
    three bytes in the four earlier titles, two in the two later ones, which
    have no per-hit-point rate and no portrait either.
    """
    fields = dos_layout.layout_for(size)
    by_name = {f.name: f for f in fields}
    if "experience_award" in by_name:
        base = by_name["experience_award"]
        rate = by_name.get("experience_per_hit_point")
        return base.offset, (rate.offset if rate else None)
    anchor = by_name.get("portrait_head") or by_name["icon_head"]
    before = [f for f in fields if f.end == anchor.offset]
    if len(before) != 1 or not before[0].name.startswith("gap_"):
        raise ValueError(f"no unnamed run before {anchor.name} in {size} bytes")
    gap = before[0]
    if gap.size not in (2, 3):
        raise ValueError(f"the run before {anchor.name} is {gap.size} bytes")
    return gap.offset, (gap.offset + 2 if gap.size == 3 else None)


def award(record: bytes, size: int | None = None, hp: int | None = None) -> int:
    """What killing this creature is worth, by the engine's own arithmetic.

    `base + hp_rolled * per_hit_point`, which is how AD&D 1st edition writes
    an experience value and what the end-of-combat routine computes.
    """
    size = size or len(record)
    base_off, rate_off = award_offsets(size)
    by_name = {f.name: f for f in dos_layout.layout_for(size)}
    base = struct.unpack_from("<H", record, base_off)[0]
    if rate_off is None:
        return base
    if hp is None:
        hp = record[by_name["hp_rolled"].offset]
    return base + record[rate_off] * hp


def setter_sites(ovr: bytes) -> list[tuple[int, int, int, int]]:
    """`(file offset, property id, record offset, width)` for every arm of the
    script property dispatcher this pattern matches.

    A linear scan of a byte stream that is not all code, so it carries
    `tools/dosfieldrefs.py`'s caveats: a match is a lead, and an empty result
    is evidence rather than proof -- the two later engines match nothing here
    and that is a fact about this pattern, not about their dispatcher.
    """
    out = []
    for m in SETTER.finditer(ovr):
        ident = struct.unpack("<H", m.group(1))[0]
        width = 2 if m.group(2)[0] == 0x8B else 1
        disp = struct.unpack("<H", m.group(4))[0]
        out.append((m.start(), ident, disp, width))
    return out


def monsters(game: pathlib.Path, size: int):
    """Every creature record in the title's `MON<n>CHA.DAX` files.

    Yields `(file, block id, name, base, per hit point, hp_rolled)`.  A block
    that is not one whole record is skipped: the containers hold other things.
    """
    by_name = {f.name: f for f in dos_layout.layout_for(size)}
    base_off, rate_off = award_offsets(size)
    hp_off = by_name["hp_rolled"].offset
    for path in sorted(game.iterdir()):
        name = path.name.upper()
        if not (name.startswith("MON") and name.endswith("CHA.DAX")):
            continue
        for entry in dos_savegame.dax_blocks(path.read_bytes()):
            block_id, raw = entry if isinstance(entry, tuple) else (None, entry)
            record = bytes(raw)
            if len(record) != size:
                continue
            label = record[1:1 + record[0]].decode("latin-1", "replace")
            yield (path.name, block_id, label,
                   struct.unpack_from("<H", record, base_off)[0],
                   record[rate_off] if rate_off is not None else None,
                   record[hp_off])


def records_under(root: pathlib.Path):
    """Every DOS character record beneath `root`, as `(path, bytes)`.

    A record is named by its length, the way `goldbox.dos` names one, so a
    file of any other size is passed over rather than guessed at.
    """
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.upper() not in (
                ".SAV", ".CHA", ".GUY"):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if len(data) in set(GAMES.values()):
            yield path, data


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_sites(args) -> int:
    game = pathlib.Path(args.path) if args.path else find_game(args.game)
    size = args.record or GAMES[args.game]
    ovr = (game / "GAME.OVR").read_bytes()
    base_off, rate_off = award_offsets(size)
    c64 = {f.offset: f for f in c64_layout.LAYOUT}
    fields = {f.offset: f for f in dos_layout.layout_for(size)}
    print(f"=== {game.name}, a {size}-byte record")
    print(f"    award base {base_off:#05x}, per hit point "
          f"{rate_off:#05x}" if rate_off is not None else
          f"    award base {base_off:#05x}, no per-hit-point rate")

    print("  script property dispatcher (the id is a C64 record offset):")
    for at, ident, disp, width in setter_sites(ovr):
        field = fields.get(disp)
        theirs = c64.get(ident)
        mark = " <<<" if ident in (PROPERTY_AWARD, PROPERTY_PER_HP) else ""
        print(f"    {at:06X}  id {ident:#05x} -> {disp:#05x} "
              f"{(field.name if field else 'mid-field'):26} "
              f"C64 {theirs.name if theirs else '(inside a gap)'}{mark}")

    print("  every instruction addressing the pair:")
    for off in (base_off,) + ((rate_off,) if rate_off is not None else ()):
        refs = dosfieldrefs.references(ovr, off, prefixes=(0x26,))
        shape = "  ".join(f"{r['linear']:06X}:{r['mnem']}" for r in refs)
        print(f"    {off:#05x}: {len(refs)} -- {shape}")
    return 0


def cmd_monsters(args) -> int:
    game = pathlib.Path(args.path) if args.path else find_game(args.game)
    size = args.record or GAMES[args.game]
    rows = list(monsters(game, size))
    print(f"=== {game.name}, {len(rows)} creature records")
    for filename, block, name, base, rate, hp in rows:
        award_total = base + (rate or 0) * hp
        print(f"  {filename:12} {block if block is not None else -1:4} "
              f"{name:18} base {base:6}  per hp "
              f"{'-' if rate is None else rate:>3}  hp {hp:4}  "
              f"= {award_total}")
    return 0


def cmd_census(args) -> int:
    roots = [pathlib.Path(p) for p in args.roots] or default_roots()
    total = nonzero = 0
    for root in roots:
        if not root.is_dir():
            print(f"  (no {root})")
            continue
        for path, data in records_under(root):
            base_off, rate_off = award_offsets(len(data))
            base = struct.unpack_from("<H", data, base_off)[0]
            rate = data[rate_off] if rate_off is not None else 0
            total += 1
            if base or rate:
                nonzero += 1
                name = data[1:1 + data[0]].decode("latin-1", "replace")
                print(f"  {path}  {name:16} base {base} per hp {rate}")
    print(f"{nonzero} of {total} records carry a non-zero experience award")
    return 0


def default_roots() -> list[pathlib.Path]:
    """The specimen tree and the archives, when they are on this machine."""
    from tools import specimens
    out = []
    tree = specimens.tree_root()
    if tree.is_dir():
        out.append(tree)
    if dosbox.ARCHIVES.is_dir():
        out.append(dosbox.ARCHIVES)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("sites", "monsters", "census"))
    ap.add_argument("roots", nargs="*", help="census: directories to sweep")
    ap.add_argument("--game", default="CURSE", choices=sorted(GAMES),
                    help="game directory stem")
    ap.add_argument("--path", default=None, help="the game directory itself")
    ap.add_argument("--record", type=int, default=None,
                    help="record size, when --path names a title not in GAMES")
    args = ap.parse_args(argv)
    try:
        return {"sites": cmd_sites, "monsters": cmd_monsters,
                "census": cmd_census}[args.cmd](args)
    except FileNotFoundError as exc:
        print(exc)
        return 0


if __name__ == "__main__":
    sys.exit(main())
