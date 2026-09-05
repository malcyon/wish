#!/usr/bin/env python3
"""Write DOS character records for every title `goldbox.dos` can write, and
measure how well they came out.

The measuring half of
`#299 (goldbox.dos.write builds only Pool of Radiance's record, so nothing can
be converted to DOS for the later titles)`.  Three modes, each answering a
different question about the same writer:

| mode | question |
|---|---|
| `roundtrip` | does a DOS record read into the neutral middle and written back come out byte for byte? |
| `from-c64` | does a C64 save convert into that title's DOS records and siblings at all? |
| `loop` | does a party that went **through the C64 engine** come back as the DOS record it started as? |

`loop` is the one worth having.  `~/wish-specimens/por-c64` holds C64 saves the
C64 engine itself wrote after loading a party this project converted from DOS,
so pointing `loop` at one of those and at the DOS folder it came from puts the
game in the middle of the measurement:

    DOS record -> neutral -> C64 record -> **the C64 game loaded and saved it**
    -> neutral -> DOS record

Every byte that differs at the end is a byte one of the two conversions or the
engine changed, and the report says which field it was in.

Nothing here writes to the player's own directories: `from-c64` needs `--out`
and refuses a directory that already holds a `CHRDAT` file unless `--force`.

Examples
--------

    tools/dosrecordwrite.py roundtrip ~/wish-specimens/por-dos
    tools/dosrecordwrite.py from-c64 \\
        ~/wish-specimens/por-c64/WISH-SPEC-ssb-d-engine-resave.D64 \\
        --out work/299/ssb-back --slot D
    tools/dosrecordwrite.py loop \\
        ~/wish-specimens/por-c64/WISH-SPEC-ssb-d-engine-resave.D64 \\
        work/curse/SSB-D-paine-memorised D
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import c64_codec, dos, dos_layout, items  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402


def masked(shape: dos_layout.DosShape) -> set[int]:
    """The offsets the writer itself says it does not take from the source.

    The round trip's mask comes from the writer's own declarations --
    `WRITE_UNSOURCED`, `WRITE_UNSOURCED_LATER`, `WRITE_DEFAULTS` and
    `WRITE_DERIVED` -- and never from whatever happened to differ, which is
    the rule `.claude/rules/conversions.md` states and the reason a new
    difference shows up here instead of being absorbed.

    `field_10c_10f` is the one `WRITE_DEFAULTS` entry left unmasked: it is a
    default only for a source that carries none of status, the active flag,
    the combat side and quickfight, and every DOS record carries all four.
    """
    table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
    out: set[int] = set()
    named = ([n for n, _ in dos.WRITE_UNSOURCED + dos.WRITE_UNSOURCED_LATER]
             + [n for n, _, _, _ in dos.WRITE_DEFAULTS
                if n != "field_10c_10f"]
             + [n for n, _ in dos.WRITE_DERIVED])
    for name in named:
        if name in table:
            out.update(range(table[name].offset, table[name].end))
    return out


def name_padding(shape: dos_layout.DosShape, original: bytes) -> set[int]:
    """The name bytes past the count byte, which the writer zeroes.

    The neutral record carries a *name*, so what the engine happened to leave
    in the bytes after it does not survive -- Curse's shipped TRAVIS has a
    space at the seventh byte over a count of six.  Masking only the bytes
    past the count keeps every byte of the name itself under test.
    """
    table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
    text = table["name_text"]
    count = original[table["name_length"].offset]
    return set(range(text.offset + count, text.end))


def field_at(shape: dos_layout.DosShape, offset: int) -> str:
    for f in dos_layout.LAYOUTS[shape.key]:
        if f.offset <= offset < f.end:
            return f.name
    return "?"


def compare(shape: dos_layout.DosShape, original: bytes, written: bytes,
            skip_name_padding: bool = True) -> dict[str, list[int]]:
    """Offsets that differ, grouped by the field they land in, after the
    writer's own mask."""
    mask = masked(shape)
    if skip_name_padding:
        mask |= name_padding(shape, original)
    out: dict[str, list[int]] = collections.defaultdict(list)
    for i in range(min(len(original), len(written))):
        if original[i] != written[i] and i not in mask:
            out[field_at(shape, i)].append(i)
    return dict(out)


def _records_under(root: pathlib.Path):
    """Every file under `root` whose size is one of the four record sizes."""
    for path in sorted(root.rglob("*") if root.is_dir() else [root]):
        if not path.is_file():
            continue
        if path.stat().st_size in dos_layout.SHAPES_BY_SIZE:
            yield path


def roundtrip(root: pathlib.Path) -> int:
    """Read every record under `root`, write it back, and say what moved."""
    totals: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    faults: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    named: dict[str, list[str]] = collections.defaultdict(list)
    for path in _records_under(root):
        try:
            char = dos.read_character(path)
        except dos.DosRecordError as exc:
            print(f"  unreadable {path}: {exc}")
            continue
        if char.shape not in dos.WRITES:
            continue
        key = char.shape.key
        totals[key][1] += 1
        try:
            rec, itm, spc, _report = dos.write(dos.to_neutral(char))
        except (dos.DosRecordError, ValueError) as exc:
            faults[key][f"{type(exc).__name__}"] += 1
            named[key].append(f"{char.name}: {exc}")
            continue
        differs = compare(char.shape, char.to_bytes(), rec)
        if not differs:
            totals[key][0] += 1
        for field, offsets in differs.items():
            faults[key][field] += 1
            named[key].append(
                f"{char.name} ({path.name}): {field} "
                f"{' '.join(hex(i) for i in offsets)}")
        want = len(char.items) * char.shape.item_size
        if len(itm) != want:
            faults[key]["item file length"] += 1
        if len(spc) % dos_layout.EFFECT_SIZE:
            faults[key]["effect file length"] += 1
    bad = 0
    for key in sorted(totals):
        ok, seen = totals[key]
        print(f"{key}: {ok}/{seen} records identical outside the writer's "
              f"own mask")
        for field, n in faults[key].most_common():
            print(f"    {field}: {n}")
            bad += n
        for line in named[key][:12]:
            print(f"      {line}")
    return bad


def _c64_party(path: pathlib.Path):
    """`(game, [neutral character])` for a C64 save disk."""
    disk = D64.open(str(path))
    game, sg0, sg1 = load_save(disk)
    out = []
    for slot in sg0.characters:
        block = sg1.roster(slot.index) if sg1 is not None else None
        inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(), slot.index)]
        out.append(c64_codec.read(slot.record, roster=block, inventory=inv,
                                  game=game,
                                  source=f"{path.name} slot {slot.index}"))
    return game, out


def from_c64(disk: pathlib.Path, out: pathlib.Path, slot: str,
             force: bool = False) -> int:
    """Convert a C64 save disk into that title's DOS records and siblings.

    **The records only.**  Nothing here writes `SAVGAM<slot>.DAT`, which is
    what the DOS game loads a party *from*: for Pool of Radiance that is
    `goldbox.dos.write_dos_save`'s job and for the later titles nobody has
    written one at all.  So this produces a party the DOS engine cannot yet
    be pointed at, which is exactly the state `#299` reports.
    """
    game, party = _c64_party(disk)
    out.mkdir(parents=True, exist_ok=True)
    if not force and any(out.glob("CHRDAT*")):
        print(f"{out} already holds CHRDAT files; pass --force to replace")
        return 1
    shape = dos.write_shape(party[0])
    # DOS lists the party from the other end: the C64 shows the highest slot
    # first and DOS shows CHRDAT<slot>1 first, so the file order is the
    # reverse of the slot order -- the same reversal `write_dos_save` makes.
    party = list(reversed(party))
    order = dos_layout.FIELDS_BY_NAME_FOR[shape.key]["party_order"].offset
    for n, char in enumerate(party, start=1):
        rec, itm, spc, report = dos.write(char)
        rec = bytearray(rec)
        rec[order] = n - 1
        stem = out / f"CHRDAT{slot}{n}"
        stem.with_suffix(".SAV").write_bytes(bytes(rec))
        if itm:
            stem.with_suffix(shape.item_suffix).write_bytes(itm)
        if spc:
            stem.with_suffix(shape.effect_suffix).write_bytes(spc)
        print(f"  {stem.name}{'':2s} {char.get('name'):16s} "
              f"{len(rec)} + {len(itm)} + {len(spc)} bytes, "
              f"{len(report.dropped)} reported")
    print(f"{shape.title}: {len(party)} records in {out}")
    print("No SAVGAM was written -- the DOS engine loads a party from one, "
          "and only Pool of Radiance's can be built today (#299)")
    return 0


def loop(disk: pathlib.Path, folder: pathlib.Path, slot: str) -> int:
    """The full loop: DOS records, out to the C64, back from the C64 save the
    engine wrote, and compared with where they started."""
    game, party = _c64_party(disk)
    shape = dos.write_shape(party[0])
    party = list(reversed(party))
    print(f"{disk.name}: {shape.title}, {len(party)} characters")
    bad = 0
    for n, char in enumerate(party, start=1):
        source = folder / f"CHRDAT{slot}{n}.SAV"
        if not source.exists():
            print(f"  CHRDAT{slot}{n}.SAV is not in {folder}")
            bad += 1
            continue
        original = dos.read_character(source)
        rec, _itm, _spc, _report = dos.write(char)
        differs = compare(shape, original.to_bytes(), rec)
        # `party_order` -- the combat-icon slot, #305 -- is renumbered by the
        # file position on the way out, which is the reversal above and not a
        # loss; the DOS loader re-allocates it in file order anyway.
        table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
        rec = bytearray(rec)
        rec[table["party_order"].offset] = original.get("party_order")
        differs = compare(shape, original.to_bytes(), bytes(rec))
        if differs:
            bad += 1
        print(f"  {source.name} {original.name:16s} "
              + ("identical outside the mask" if not differs else
                 ", ".join(f"{k} @{' '.join(hex(i) for i in v)}"
                           for k, v in differs.items())))
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="mode", required=True)

    rt = sub.add_parser("roundtrip", help="read and write back every record")
    rt.add_argument("root", type=pathlib.Path)

    fc = sub.add_parser("from-c64", help="a C64 save disk to DOS records")
    fc.add_argument("disk", type=pathlib.Path)
    fc.add_argument("--out", type=pathlib.Path, required=True)
    fc.add_argument("--slot", default="A")
    fc.add_argument("--force", action="store_true")

    lp = sub.add_parser("loop", help="compare a C64 resave with its DOS origin")
    lp.add_argument("disk", type=pathlib.Path)
    lp.add_argument("folder", type=pathlib.Path)
    lp.add_argument("slot")

    args = ap.parse_args(argv)
    if args.mode == "roundtrip":
        return 1 if roundtrip(args.root) else 0
    if args.mode == "from-c64":
        return from_c64(args.disk, args.out, args.slot, args.force)
    return 1 if loop(args.disk, args.folder, args.slot) else 0


if __name__ == "__main__":
    raise SystemExit(main())
