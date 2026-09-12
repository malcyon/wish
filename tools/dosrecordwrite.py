#!/usr/bin/env python3
"""Write DOS character records for every title `goldbox.dos_codec` can write, and
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

from goldbox import c64_codec, dos_codec, dos_port, items  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402

#: Specimen directories holding **this project's own writer's output from
#: before a fix**, and what the fix was.  A round trip against one of these
#: measures the distance between two versions of our writer, not a fault in
#: today's; `.claude/rules/testing.md` says a record our own writers produced
#: is never evidence about the game, and a *dated* one is not evidence about
#: the writer either.
#:
#: The worked example, and why the list exists: on 2026-09-07 the round trip
#: reported `char_class` differing in 8 of 56 Curse records, which reads like
#: a live defect and is not.  `curse-234-converted-party` was built on
#: 2026-09-05 by the writer as it stood *before* `#310` taught it to check a
#: class code against the class mask, so it holds 0 (cleric) for MATHEW the
#: paladin 6, TRAVIS the fighter 5 / thief 6 and LEDERA the fighter 5 /
#: magic-user 5 -- the very symptom `goldbox.dos_codec`' `char_class` comment
#: describes, "that drew CLERIC on a dwarf thief 6 / fighter 5 in the running
#: game".  `curse-234-engine-resave` is DOS Curse's own `SAVE CURRENT GAME`
#: over those records and holds the same wrong bytes, which is the separate
#: finding that **the DOS engine does not recompute `char_class` on load**.
#: The engine-written specimen of the same six characters,
#: `curse-131-four-items-readied`, holds 3, 14, 13 -- and that is what today's
#: writer produces.
STALE_OUR_OUTPUT: dict[str, str] = {
    "WISH-SPEC-curse-234-converted-party":
        "our own writer, 2026-09-05, before #310's class-code repair: it "
        "copied char_class @0x75 straight off a C64 record whose trainer had "
        "stopped maintaining it, so three characters read 0 (cleric) and "
        "dual-classed PHILIPPE reads 6, which is the level he left "
        "magic-user at rather than any class code",
    "WISH-SPEC-curse-234-engine-resave":
        "DOS Curse's resave of the specimen above, which kept its char_class "
        "byte -- the engine does not recompute it",
}


def stale_reason(path: pathlib.Path) -> str | None:
    """Why a difference against `path` is our own older output, or None."""
    parts = set(path.parts)
    return next((why for name, why in STALE_OUR_OUTPUT.items()
                 if name in parts), None)


def masked(shape: dos_port.DosDeltas) -> set[int]:
    """The offsets the writer itself says it does not take from the source.

    The round trip's mask comes from the writer's own declarations --
    `WRITE_UNSOURCED`, `WRITE_UNSOURCED_LATER`, `WRITE_DEFAULTS` and
    `WRITE_DERIVED` -- and never from whatever happened to differ, which is
    the rule `.claude/rules/conversions.md` states and the reason a new
    difference shows up here instead of being absorbed.

    `field_10c_10f` is the one `WRITE_DEFAULTS` entry left unmasked: it is a
    default only for a source that carries none of status, the active flag,
    the combat side and quickfight, and every DOS record carries all four.

    **`WRITE_CONSTANTS` is not masked either, and that is the point of it
    being a list.**  A constant is a value we chose, so a record disagreeing
    with one is something to look at rather than to hide: 108 of the 136 Pool
    of Radiance records in `~/wish-specimens` and 3 of the 50 Silver Blades
    ones differ here at `field_83_87`'s treasure-share byte alone, which is
    the split `#304` measured and closed -- the share is 1 for a character
    the player has taken through MODIFY and 0 for one he has not.
    """
    table = dos_port.FIELDS_BY_NAME_FOR[shape.key]
    out: set[int] = set()
    named = ([n for n, _ in dos_codec.WRITE_UNSOURCED + dos_codec.WRITE_UNSOURCED_LATER]
             + [n for n, _, _, _ in dos_codec.WRITE_DEFAULTS
                if n != "field_10c_10f"]
             + [n for n, _ in dos_codec.WRITE_DERIVED])
    for name in named:
        if name in table:
            out.update(range(table[name].offset, table[name].end))
    return out


def name_padding(shape: dos_port.DosDeltas, original: bytes) -> set[int]:
    """The name bytes past the count byte, which the writer zeroes.

    The neutral record carries a *name*, so what the engine happened to leave
    in the bytes after it does not survive -- Curse's shipped TRAVIS has a
    space at the seventh byte over a count of six.  Masking only the bytes
    past the count keeps every byte of the name itself under test.
    """
    table = dos_port.FIELDS_BY_NAME_FOR[shape.key]
    text = table["name_text"]
    count = original[table["name_length"].offset]
    return set(range(text.offset + count, text.end))


def field_at(shape: dos_port.DosDeltas, offset: int) -> str:
    for f in dos_port.LAYOUTS[shape.key]:
        if f.offset <= offset < f.end:
            return f.name
    return "?"


def compare(shape: dos_port.DosDeltas, original: bytes, written: bytes,
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
        if path.stat().st_size in dos_port.DELTAS_BY_SIZE:
            yield path


def roundtrip(root: pathlib.Path) -> int:
    """Read every record under `root`, write it back, and say what moved.

    Records under a `STALE_OUR_OUTPUT` specimen are read and compared like
    any other, and reported in their own paragraph with the reason, rather
    than counted as faults: a difference there is the distance between two
    dates of our own writer.  They are still shown, because a list that
    silently drops records is a mask taken from the diff.
    """
    totals: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    faults: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    named: dict[str, list[str]] = collections.defaultdict(list)
    stale: list[str] = []
    stale_by_key: collections.Counter = collections.Counter()
    for path in _records_under(root):
        try:
            char = dos_codec.read_character(path)
        except dos_codec.DosRecordError as exc:
            print(f"  unreadable {path}: {exc}")
            continue
        if char.shape not in dos_codec.WRITES:
            continue
        key = char.shape.key
        totals[key][1] += 1
        try:
            rec, itm, spc, _report = dos_codec.write(dos_codec.to_neutral(char))
        except (dos_codec.DosRecordError, ValueError) as exc:
            faults[key][f"{type(exc).__name__}"] += 1
            named[key].append(f"{char.name}: {exc}")
            continue
        differs = compare(char.shape, char.to_bytes(), rec)
        if not differs:
            totals[key][0] += 1
        why = stale_reason(path)
        for field, offsets in differs.items():
            where = " ".join(hex(i) for i in offsets)
            if why is not None:
                stale.append(f"{char.name} ({path.parent.name}/{path.name}): "
                             f"{field} {where} -- {why}")
                stale_by_key[key] += 1
                continue
            faults[key][field] += 1
            named[key].append(
                f"{char.name} ({path.name}): {field} {where}")
        want = len(char.items) * char.shape.item_size
        if len(itm) != want:
            faults[key]["item file length"] += 1
        if len(spc) % dos_port.EFFECT_SIZE:
            faults[key]["effect file length"] += 1
    bad = 0
    for key in sorted(totals):
        ok, seen = totals[key]
        ours = stale_by_key[key]
        print(f"{key}: {ok}/{seen} records identical outside the writer's "
              f"own mask"
              + (f", and {ours} of the {seen - ok} that differ are this "
                 f"project's own older output, listed at the end"
                 if ours else ""))
        for field, n in faults[key].most_common():
            print(f"    {field}: {n}")
            bad += n
        for line in named[key][:12]:
            print(f"      {line}")
    if stale:
        print(f"{len(stale)} record(s) differ only against output this "
              f"project's own writer made before a fix, and are not counted "
              f"above:")
        for line in stale:
            print(f"    {line}")
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

    **The records only**, so that a fault in them can be seen without the
    container in the way.  Nothing here writes `SAVGAM<slot>.DAT`, which is
    what the DOS game loads a party *from*, so this mode leaves a directory
    the DOS engine cannot be pointed at.

    That is a property of this mode and no longer of the library:
    `goldbox.dos_codec.new_dos_save` builds the whole save from nothing for all
    three titles `goldbox.dos_codec.WRITES` names -- Pool of Radiance's 13137-byte
    container, Curse's 13149 with its `ECL<n>.DAX` script staged, and Silver
    Blades' 5469 without one -- and both later ones have been loaded and
    played in DOSBox (`#299`).
    """
    game, party = _c64_party(disk)
    out.mkdir(parents=True, exist_ok=True)
    if not force and any(out.glob("CHRDAT*")):
        print(f"{out} already holds CHRDAT files; pass --force to replace")
        return 1
    shape = dos_codec.write_shape(party[0])
    # DOS lists the party from the other end: the C64 shows the highest slot
    # first and DOS shows CHRDAT<slot>1 first, so the file order is the
    # reverse of the slot order -- the same reversal `write_dos_save` makes.
    party = list(reversed(party))
    order = dos_port.FIELDS_BY_NAME_FOR[shape.key]["combat_figure"].offset
    for n, char in enumerate(party, start=1):
        rec, itm, spc, report = dos_codec.write(char)
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
    print("No SAVGAM was written, and the DOS engine loads a party from one: "
          "this mode measures the records alone. goldbox.dos_codec.new_dos_save "
          "builds the whole save for every title this writer writes (#299)")
    return 0


def loop(disk: pathlib.Path, folder: pathlib.Path, slot: str) -> int:
    """The full loop: DOS records, out to the C64, back from the C64 save the
    engine wrote, and compared with where they started."""
    game, party = _c64_party(disk)
    shape = dos_codec.write_shape(party[0])
    party = list(reversed(party))
    print(f"{disk.name}: {shape.title}, {len(party)} characters")
    bad = 0
    for n, char in enumerate(party, start=1):
        source = folder / f"CHRDAT{slot}{n}.SAV"
        if not source.exists():
            print(f"  CHRDAT{slot}{n}.SAV is not in {folder}")
            bad += 1
            continue
        original = dos_codec.read_character(source)
        rec, _itm, _spc, _report = dos_codec.write(char)
        differs = compare(shape, original.to_bytes(), rec)
        # `combat_figure` -- the combat-icon slot, #305 -- is renumbered by
        # the file position on the way out, which is the reversal above and
        # not a loss; the DOS loader re-allocates it in file order anyway.
        table = dos_port.FIELDS_BY_NAME_FOR[shape.key]
        rec = bytearray(rec)
        rec[table["combat_figure"].offset] = original.get("combat_figure")
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
