#!/usr/bin/env python3
"""Where DOS Gold Box keeps a dual-classed human's old class, measured twice.

`#234 (A dual-classed Curse or Silver Blades character converted to DOS loses
the class he trained out of)` asked whether the DOS record has a home for the
C64's `dual_class_slot`/`dual_class_level` pair.  It has two, and this is what
was used to find them:

* **`census`** reads every DOS character record on the machine -- 285, 422,
  439 and 510 bytes, `.SAV`, `.CHA` and `.GUY` alike -- deduplicates on the
  bytes, and prints `class_levels`, `former_class_levels` and the unnamed byte
  immediately after `level` for each.  Three characters in the whole corpus
  are dual-classed and all three are 510 bytes, so the counts matter: a field
  that is zero in all 52 Curse records is zero because no Curse character on
  this machine has ever trained out of a class.
* **`code`** counts every `es:[di+<offset>]` instruction in each title's own
  `GAME.OVR` that touches either level array, and disassembles the window
  around the single write to the former one.  Five of the six DOS Gold Box
  overlays on this machine carry **exactly one** writer and twenty-odd
  readers; Pool of Radiance has no such array at all, which is the DOS half of
  `#224 (0x0B9 and 0x0BA are documented both as an NPC marker and as the
  dual-class slot)`'s C64 census.

The reference scan is `tools/dosfieldrefs.py`'s, and its three limits apply
here too -- a displacement match is not proof the pointer is a character
record, an offset can be reached without a matching displacement, and nothing
checks that a match is an instruction.  What makes the answer sound is that
`code` disassembles the site it found and the routine reads as one: the
displacement census only says where to look.

    tools/dualclassdos.py census
    tools/dualclassdos.py census --dual-only work/curse
    tools/dualclassdos.py code
    tools/dualclassdos.py code --title curse-of-the-azure-bonds --window 60

The archives are the player's and are read only, the way `tools/dosbox.py`
finds them: `$FR_ARCHIVES`, then `gamedisks.toml`, then `~/Downloads`.  With
no archives both commands print nothing and exit 0, the way the tests skip.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import dosbox  # noqa: E402
from dosfieldrefs import references  # noqa: E402

from goldbox import dos, dos_layout  # noqa: E402

#: The suffixes a character record can wear.  A saved slot is `.SAV`; a
#: character exported from the party menu is `.CHA` in Pool of Radiance and
#: `.GUY` in Gateway to the Savage Frontier, and both are the same record.
SUFFIXES = (".SAV", ".CHA", ".GUY")

#: Class number -> name, which is how *both* level arrays are indexed on DOS.
#: The C64 indexes its own eight slots by the class *bit* instead, which is
#: the permutation `goldbox/dos.py` already carries.
CLASS_NAMES = dos_layout.CLASS_NUMBERS


def record_paths(extra: list[str]) -> list[pathlib.Path]:
    """Every file that could be a character record, archives first."""
    roots = [dosbox.ARCHIVES] + [pathlib.Path(p) for p in extra]
    out = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.upper() in SUFFIXES:
                out.append(path)
    return out


def read_records(extra: list[str]):
    """`(shape, character, paths)` for every distinct record, by bytes.

    The archives ship most save directories twice and a run under `work/`
    copies them again, so the same record turns up a dozen times.  One entry
    per distinct byte string, with every path it was found at.
    """
    by_size = {s.record_size: s for s in dos_layout.SHAPES}
    seen: dict[str, list] = {}
    for path in record_paths(extra):
        shape = by_size.get(path.stat().st_size)
        if shape is None:
            continue
        data = path.read_bytes()
        key = hashlib.sha1(data).hexdigest()
        if key in seen:
            seen[key][2].append(path)
            continue
        try:
            char = dos.DosCharacter(data, shape=shape)
            char.name                                  # raises on a non-record
        except Exception:
            continue
        seen[key] = [shape, char, [path]]
    return list(seen.values())


def former_of(char) -> list[int]:
    if "former_class_levels" not in char.fields:
        return []
    return list(char.raw("former_class_levels"))


def old_level_byte(char) -> int | None:
    """The byte immediately after `level`, which the trainer writes too.

    Unnamed in every shape -- `gap_0e6` in Curse, `gap_0ef` in Silver Blades,
    `gap_139` in Pools of Darkness -- and equal to the former class's level in
    all three dual-classed records this corpus holds.
    """
    level = char.fields.get("level")
    if level is None:
        return None
    at = level.offset + level.size
    raw = bytes(char)
    return raw[at] if at < len(raw) else None


def census(args: argparse.Namespace) -> int:
    records = read_records(args.paths)
    if not records:
        print("no DOS character records on this machine; set $FR_ARCHIVES")
        return 0
    by_title = collections.defaultdict(list)
    for shape, char, paths in records:
        by_title[shape.key].append((char, paths))
    for shape in dos_layout.SHAPES:
        rows = by_title.get(shape.key)
        if not rows:
            continue
        dual = [r for r in rows if any(former_of(r[0]))]
        print(f"=== {shape.title} ({shape.record_size} bytes): "
              f"{len(rows)} distinct record(s), {len(dual)} dual-classed")
        for char, paths in sorted(rows, key=lambda r: r[0].name):
            former = former_of(char)
            if args.dual_only and not any(former):
                continue
            after = old_level_byte(char)
            print(f"  {char.name:<15} class={char.get('char_class'):<3} "
                  f"level={char.get('level'):<3} after-level={after} "
                  f"levels={list(char.raw('class_levels'))} former={former}")
            if any(former):
                for n, v in enumerate(former):
                    if v:
                        name = (CLASS_NAMES[n] if n < len(CLASS_NAMES)
                                else f"slot {n}")
                        print(f"      was a {name} {v}, and the byte after "
                              f"level reads {after}")
                for p in paths[:2]:
                    print(f"      {p}")
        print()
    return 0


#: Each title's overlay, the directory it lives in, and the shape whose
#: offsets it is read against.  Pool of Radiance is in the list precisely
#: because it should come back empty.
#:
#: **Two of the six have no shape of their own**, and are read against the one
#: their record size names: Gateway to the Savage Frontier writes 422-byte
#: records like Curse and Treasures of the Savage Frontier 510-byte ones like
#: Pools of Darkness.  So `dos_layout`'s "the size names the title" holds
#: among the four it models and not on this machine, where six titles share
#: four sizes -- `#234 (A dual-classed Curse or Silver Blades character
#: converted to DOS loses the class he trained out of)`.  Borrowing the shape
#: is sound here and only here: the question is whether the same routine sits
#: at the same displacement, and the answer either agrees or it does not.
OVERLAYS = (("pool-of-radiance", "POOLRAD", "pool-of-radiance"),
            ("curse-of-the-azure-bonds", "CURSE", "curse-of-the-azure-bonds"),
            ("secret-of-the-silver-blades", "SECRET",
             "secret-of-the-silver-blades"),
            ("pools-of-darkness", "Pools of Darkness", "pools-of-darkness"),
            ("gateway-to-the-savage-frontier",
             "Gateway to the Savage Frontier", "curse-of-the-azure-bonds"),
            ("treasures-of-the-savage-frontier",
             "Treasures of the Savage Frontier", "pools-of-darkness"))


def find_overlay(stem: str) -> pathlib.Path | None:
    for path in sorted(dosbox.ARCHIVES.rglob("GAME.OVR")):
        if f"/{stem}/" in str(path):
            return path
    return None


def disassemble(image: bytes, site: int, window: int) -> list[str]:
    """A 16-bit listing that lands exactly on `site`.

    The overlay is a byte stream with no entry points to walk from, so the
    alignment is chosen rather than known: back up a byte at a time until a
    decode from there puts an instruction boundary on the site, then widen
    while keeping that boundary.  Every line printed is the true decode of
    those bytes from the chosen start; that the start is a real instruction
    boundary is what the site itself vouches for.
    """
    try:
        import capstone
    except ImportError:
        return ["  (capstone is not installed, so no listing)"]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    start = None
    for back in range(2, 120):
        at = site - back
        if any(i.address == site for i in md.disasm(image[at:site + 8], at)):
            start = at
            break
    if start is None:
        return ["  (no alignment within 120 bytes puts a boundary on the site)"]
    for at in range(site - window, start + 1):
        seen = {i.address for i in md.disasm(image[at:site + window], at)}
        if site in seen and start in seen:
            start = at
            break
    out = []
    for ins in md.disasm(image[start:site + window], start):
        mark = "   <<< the only write" if ins.address == site else ""
        out.append(f"  {ins.address:06X}  {ins.bytes.hex():<14} "
                   f"{ins.mnemonic} {ins.op_str}{mark}")
    return out


def code(args: argparse.Namespace) -> int:
    if not dosbox.ARCHIVES.is_dir():
        print("no DOS archives on this machine; set $FR_ARCHIVES")
        return 0
    for key, stem, shape_key in OVERLAYS:
        if args.title and key != args.title:
            continue
        path = find_overlay(stem)
        if path is None:
            print(f"{key}: no GAME.OVR here")
            continue
        image = path.read_bytes()
        fields = {f.name: f for f in dos_layout.layout_for(shape_key)}
        borrowed = "" if shape_key == key else f", read as {shape_key}"
        print(f"=== {key}  {path.name}, {len(image)} bytes{borrowed}")
        write_site = None
        for name in ("class_levels", "former_class_levels"):
            field = fields.get(name)
            if field is None:
                print(f"  {name}: this title has no such field")
                continue
            hits = references(image, field.offset)
            writes = [h for h in hits if h["kind"] in ("W", "RW")]
            print(f"  {name} at {field.offset:#05x}: {len(hits)} site(s), "
                  f"{len(writes)} write(s) "
                  f"{[hex(h['linear']) for h in writes]}")
            if name == "former_class_levels" and len(writes) == 1:
                write_site = writes[0]["linear"]
        if write_site is not None and args.window:
            print(f"  -- around {write_site:#07x}")
            for line in disassemble(image, write_site, args.window):
                print(line)
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    c = sub.add_parser("census", help="every DOS record's two level arrays")
    c.add_argument("paths", nargs="*", help="extra directories to sweep")
    c.add_argument("--dual-only", action="store_true",
                   help="print only records whose former array is set")
    c.set_defaults(func=census)

    d = sub.add_parser("code", help="who writes the former array, per title")
    d.add_argument("--title", default=None, help="one shape key only")
    d.add_argument("--window", type=int, default=80,
                   help="bytes of listing either side of the write; 0 for none")
    d.set_defaults(func=code)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
