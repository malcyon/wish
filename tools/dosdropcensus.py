#!/usr/bin/env python3
"""Does any record on this machine set a field the conversion cannot convert?

`#192 (Convert a Curse of the Azure Bonds DOS save into a C64 one, which the
importer refuses today)` step 0c is the ticket. `.claude/rules/conversions.md`
says every field is converted or is on a short list with a tested reason -- so
before writing the conversion, somebody has to say which of Curse's extra
fields any record on this machine actually uses. A field nothing sets still
has to be converted; the difference is whether there is a specimen to test the
conversion against, or whether one has to be made.

    dosdropcensus.py curse-of-the-azure-bonds
    dosdropcensus.py secret-of-the-silver-blades --records

Each column is a **question with an answer per record**, not a byte partition:
"is the second byte of an ability pair different from the first", "how many
spell ids are in the memorised list", "is the druid slot array non-zero". A
partition of an 84-byte field says nothing a reader can act on;
`tools/dostailcensus.py --field` is the tool for that and this one calls its
finder so the two censuses are over the same corpus.

**Provenance caps every grade this produces.** `tools/dostailcensus.py` marks
what this project wrote and excludes it, which is necessary and not sufficient:
`.claude/rules/testing.md` says a specimen is evidence only if we watched it
being written, and `tools/specimens.py list` holds no Curse record at all. So a
non-zero column here is a claim that *something on this machine* holds that
value, and a zero column is a claim that nothing does -- neither is a claim
about what the game writes. The header says so on every run.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos_layout as dl  # noqa: E402
from tools import dostailcensus  # noqa: E402

#: The seven (base, current) ability pairs, in record order.
ABILITIES = ("strength", "intelligence", "wisdom", "dexterity",
             "constitution", "charisma", "exceptional_strength")

#: The spell-slot arrays a title may carry, and the levels a conversion to
#: Pool of Radiance's three-byte C64 array would have room for.
SLOT_ARRAYS = ("spells_castable_cleric", "spells_castable_druid",
               "spells_castable_magic_user")


def field(spec, name: str) -> bytes:
    """The bytes a named field holds in this record's own shape, or b""."""
    f = dl.FIELDS_BY_NAME_FOR[spec.shape.key].get(name)
    if f is None:
        return b""
    return spec.data[f.offset:f.offset + f.size]


def ability_pairs(spec) -> list[tuple[str, int, int]]:
    """`(ability, base, current)` for every pair that is two bytes wide."""
    out = []
    for name in ABILITIES:
        raw = field(spec, name)
        if len(raw) == 2:
            out.append((name, raw[0], raw[1]))
    return out


def memorised_ids(spec) -> int:
    """How many non-zero entries the memorised list holds."""
    return sum(1 for b in field(spec, "spells_memorised") if b)


def columns(spec) -> dict[str, str]:
    """One answer per question, for one record."""
    pairs = ability_pairs(spec)
    differing = [n for n, base, cur in pairs if base != cur]
    former = field(spec, "former_class_levels")
    out = {
        "abilities differ": ",".join(n[:3] for n in differing) or "-",
        "0x0E6": f"{field(spec, 'gap_0e6')[0]:02X}"
                 if field(spec, "gap_0e6") else "-",
        "former": former.hex() if any(former) else "-",
        "memorised": str(memorised_ids(spec)),
    }
    for name in SLOT_ARRAYS:
        raw = field(spec, name)
        short = name.rsplit("_", 1)[-1][:6]
        if not raw:
            out[short] = "-"
            continue
        out[short] = raw.hex()
    tail = field(spec, "field_10c_10f")
    out["10C-10F"] = tail.hex() if tail else "-"
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("title", help="a goldbox.dos_layout shape key")
    parser.add_argument("roots", nargs="*", type=pathlib.Path,
                        help="directories to sweep; the default is "
                             "tools/dostailcensus.py's")
    parser.add_argument("--records", action="store_true",
                        help="one row per record as well as the summary")
    parser.add_argument("--built", action="store_true",
                        help="include records this project wrote")
    args = parser.parse_args(argv)

    roots = list(args.roots)
    if not roots:
        archives = dostailcensus.archives()
        if archives:
            roots.append(archives)
        roots.append(ROOT / "work")
    specs = [s for s in dostailcensus.collect(roots, args.built)
             if s.shape.key == args.title]
    if not specs:
        raise SystemExit(f"No {args.title} records under {roots}.")

    print(f"{args.title}: {len(specs)} distinct records")
    print("  Provenance: none of these was watched being written. "
          "A value here is a claim about this machine's files, "
          "not about what the game writes.")

    rows = [(s, columns(s)) for s in specs]
    keys = list(rows[0][1])

    if args.records:
        width = max(len(s.who) for s, _ in rows)
        print()
        print("  " + f"{'record':{width}}  "
              + "  ".join(f"{k:>12}" for k in keys))
        for spec, row in sorted(rows, key=lambda r: r[0].who):
            print("  " + f"{spec.who:{width}}  "
                  + "  ".join(f"{row[k]:>12}" for k in keys))

    print("\n  how many records answer each question:")
    for key in keys:
        values: dict[str, int] = {}
        for _spec, row in rows:
            values[row[key]] = values.get(row[key], 0) + 1
        blank = values.get("-", 0) + values.get("0", 0)
        live = len(rows) - blank
        shown = sorted(values.items(), key=lambda kv: -kv[1])[:6]
        print(f"    {key:16} {live:>3} of {len(rows)} non-empty; "
              + ", ".join(f"{v or '(empty)'} x{n}" for v, n in shown))

    print("\n  the ability pairs, per ability:")
    for name in ABILITIES:
        differ = sum(1 for s in specs
                     for n, base, cur in ability_pairs(s)
                     if n == name and base != cur)
        have = sum(1 for s in specs if len(field(s, name)) == 2)
        print(f"    {name:22} {differ:>3} of {have} records have "
              f"base != current")

    print("\n  the spell-slot arrays, per byte:")
    for name in SLOT_ARRAYS:
        raws = [field(s, name) for s in specs]
        raws = [r for r in raws if r]
        if not raws:
            print(f"    {name:26} not in this shape")
            continue
        width = len(raws[0])
        counts = [sum(1 for r in raws if r[i]) for i in range(width)]
        print(f"    {name:26} " + "  ".join(
            f"level {i + 1}: {c:>3}" for i, c in enumerate(counts)))

    print("\n  the memorised list:")
    lengths = [memorised_ids(s) for s in specs]
    width = len(field(specs[0], "spells_memorised"))
    over = sum(1 for n in lengths if n > 16)
    print(f"    field is {width} bytes; the widest list is {max(lengths)} "
          f"ids; {over} of {len(specs)} records hold more than 16")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
