#!/usr/bin/env python3
"""Read Amiga *Pools of Darkness*' own Silver Blades importer, field by field.

Amiga Pools of Darkness carries a routine that turns an Amiga *Secret of the
Silver Blades* character record into one of its own.  It is a straight
field-by-field copy -- sixty-odd `move.b $src(a3), $dst(a2)` and six block
copies -- and `goldbox.amiga.SILVER_BLADES_DELTAS` already names every source
offset, because `#55 (Decode the Amiga Curse and Silver Blades records)`
decoded that record.  So the routine reads as a table of "Silver Blades'
*name* lives at Pools of Darkness' `0xY`", written by the engine itself.

That is what decoded the rest of the `.pc` for
`#462 (Decode the rest of the Amiga Pools of Darkness .pc: 37 of 75 neutral
fields have no home in it, so a converted character loses his spells and
possessions)`, including the two regions no specimen could ever have shown:
the spellbook, which the importer plants at `0x159`, and the combat block,
which Pools of Darkness splits between `0x5E`-`0x5F` and `0x184`-`0x185`.

    tools/podimportmap.py                 # the map, as the engine writes it
    tools/podimportmap.py --check         # against goldbox.amiga's constants
    tools/podimportmap.py --json out.json

The executable is read out of the player's own disk images, read-only, and
nothing is written anywhere but `--json`.  Needs `capstone`.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga, dos_layout  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools import amiga68k, amigasaves  # noqa: E402

#: The importer, found by `tools/amigarecordrefs.py 159` and read from its own
#: `movem.l` prologue.  It is entered as `f(silver_blades, pools_of_darkness)`
#: and begins by zeroing 0x194 bytes of the destination, which is where the
#: 404-byte record length comes from.
IMPORTER = (0x26000, 0x262E0)

#: The executable, on disk 1 of the Amiga release.
EXECUTABLE = "Pools of Darkness"

_MOVE = re.compile(
    r"^(?P<at>[0-9a-f]+): .*\bmove\.(?P<size>[bwl])\s+"
    r"\$(?P<src>[0-9a-f]+)\(a3\), (\$(?P<dst>[0-9a-f]+))?\(a2\)")
#: The name is copied from the top of the record, so the source is the bare
#: register rather than a displacement off it.
_BARE = re.compile(r"^(?P<at>[0-9a-f]+): .*\bmove\.l\s+a3, -\(a7\)")
_LEA = re.compile(r"^(?P<at>[0-9a-f]+): .*\blea\.l\s+"
                  r"\$(?P<off>[0-9a-f]+)\((?P<reg>a[23])\), a0")
_LEN = re.compile(r"^(?P<at>[0-9a-f]+): .*\bmove\.w\s+#\$(?P<len>[0-9a-f]+), -\(a7\)")
_SIZES = {"b": 1, "w": 2, "l": 4}


def executable(quiet: bool = False) -> bytes:
    """The Pools of Darkness Amiga executable, off the player's own disks.

    Six disk-1 images on this machine carry one, and they are **not** all the
    same file: three agree, one is a shorter build a cracker made, and two
    more differ from the three by a patch.  So the build taken is the one the
    most images agree on, and the counts are printed rather than hidden --
    a run against a single odd rip should say so rather than look like a
    finding about the game.
    """
    seen: dict[bytes, list[str]] = {}
    for label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
            paths = [p for p, _ in disk.walk()]
        except (AmigaDiskError, ValueError):
            continue
        for path in paths:
            if path.rsplit("/", 1)[-1] == EXECUTABLE:
                seen.setdefault(disk.read_file(path), []).append(label)
    if not seen:
        raise SystemExit(f"no Amiga {EXECUTABLE!r} on any disk image here")
    blob = max(seen, key=lambda b: (len(seen[b]), len(b)))
    if not quiet:
        print(f"{EXECUTABLE}: {len(blob)} bytes, on {len(seen[blob])} of "
              f"{sum(len(v) for v in seen.values())} disk images that hold one",
              file=sys.stderr)
    return blob


def _silver_blades_field(offset: int) -> tuple[str, int]:
    """The Silver Blades field covering an Amiga record offset, and its index.

    The spellbook is the one field `AmigaDeltas` does not place, because the
    Amiga packs 117 spell ids into fifteen bytes where DOS spends 117.  It
    sits where DOS puts it, immediately after `hp_max`, and the shape's own
    `spellbook_bytes` says how wide it is.
    """
    shape = amiga.SILVER_BLADES_DELTAS
    fields = {f.name: f for f in dos_layout.layout_for(shape.dos)}
    book = shape.offset(fields["hp_max"].offset) + 1
    if book <= offset < book + shape.spellbook_bytes:
        return "spellbook", offset - book
    for field in dos_layout.layout_for(shape.dos):
        if not field.size or field.name == "spellbook":
            continue
        at = shape.offset(field.offset)
        if at is None:
            continue
        if at <= offset < at + field.size:
            return field.name, offset - at
    return "?", 0


def moves(listing: list[str]) -> list[dict]:
    """Every copy the importer makes, as `(field, index, size, destination)`."""
    out: list[dict] = []
    pending_len: int | None = None
    pending_dst: int | None = None
    for line in listing:
        got = _MOVE.search(line)
        if got:
            src = int(got["src"], 16)
            name, index = _silver_blades_field(src)
            out.append({"at": int(got["at"], 16), "src": src, "field": name,
                        "index": index, "size": _SIZES[got["size"]],
                        "dst": int(got["dst"] or "0", 16), "block": False})
            continue
        got = _LEN.search(line)
        if got:
            pending_len = int(got["len"], 16)
            pending_dst = None
            continue
        got = _BARE.search(line)
        if got and pending_len is not None and pending_dst is not None:
            name, index = _silver_blades_field(0)
            out.append({"at": int(got["at"], 16), "src": 0, "field": name,
                        "index": index, "size": pending_len,
                        "dst": pending_dst, "block": True})
            pending_len = pending_dst = None
            continue
        got = _LEA.search(line)
        if got and pending_len is not None:
            off = int(got["off"], 16)
            if got["reg"] == "a2":
                pending_dst = off
            elif pending_dst is not None:
                name, index = _silver_blades_field(off)
                out.append({"at": int(got["at"], 16), "src": off,
                            "field": name, "index": index,
                            "size": pending_len, "dst": pending_dst,
                            "block": True})
                pending_len = pending_dst = None
    return out


def read(quiet: bool = False) -> list[dict]:
    data = executable(quiet)
    exe = amiga68k.Executable.parse(data)
    listing = amiga68k.disassemble(exe, *IMPORTER)
    return moves(listing)


#: What `goldbox/amiga.py` says, for `--check`.  A name here is the module's
#: constant and the value is the Silver Blades field and index the importer
#: reads it from, plus how far back from that instruction's destination the
#: constant sits -- which is zero everywhere but `ROSTER_TAIL`, whose first
#: byte the importer copies inside a two-byte block with `armour_class`.
CHECKED: dict[str, tuple] = {
    "NAME": ("name_length", 0),
    "ABILITIES": ("strength", 0),
    "EXCEPTIONAL_STRENGTH": ("exceptional_strength", 0),
    "THAC0_BASE": ("thac0_base", 0),
    "RACE": ("race", 0),
    "CLASS": ("char_class", 0),
    "PALADIN_CURES": ("paladin_cures", 0),
    "AGE": ("age", 0),
    "HP_MAX": ("hp_max", 0),
    "ICON_DIMENSION": ("icon_dimension", 0),
    "SAVING_THROWS": ("save_paralysis", 0),
    "MOVEMENT": ("movement", 0),
    "LEVEL": ("level", 0),
    "FORMER_LEVEL": ("former_level", 0),
    "TURN_CLASS": ("turn_class", 0),
    "THIEF_SKILLS": ("thief_pick_pockets", 0),
    "EFFECT_CHAIN": ("effect_chain", 0),
    "PLATINUM": ("platinum", 0),
    "CLASS_LEVELS": ("class_levels", 0),
    "SEX": ("sex", 0),
    "ALIGNMENT": ("alignment", 0),
    "ATTACK_FORMS": ("attack_forms", 0),
    "ARMOUR_CLASS": ("armour_class_base", 0),
    "STRENGTH_BONUS": ("strength_bonus", 0),
    "UNNAMED_0AB": ("unnamed_0ab", 0),
    "EXPERIENCE": ("experience", 0),
    "CLASS_BITS": ("class_bits", 0),
    "HP_ROLLED": ("hp_rolled", 0),
    "EXPERIENCE_AWARD": ("experience_award", 0),
    "PORTRAIT_HEAD": ("portrait_head", 0),
    "PORTRAIT_BODY": ("portrait_body", 0),
    "ICON_HEAD": ("icon_head", 0),
    "ICON_BODY": ("icon_body", 0),
    "COMBAT_FIGURE": ("combat_figure", 0),
    "SIZE": ("size", 0),
    "ICON_COLOURS": ("icon_colours", 0),
    "ITEM_COUNT_CACHE": ("item_count", 0),
    "ITEM_CHAIN": ("item_chain", 0),
    "HANDS_USED": ("hands_used", 0),
    "ENCUMBRANCE": ("encumbrance", 0),
    "STATUS": ("field_10c_10f", 0),
    "ACTIVE": ("field_10c_10f", 1),
    "HOSTILE": ("field_10c_10f", 2),
    "QUICKFIGHT": ("field_10c_10f", 3),
    "THAC0_CURRENT": ("thac0_current", 0),
    "ARMOUR_CLASS_CURRENT": ("armour_class", 0),
    "ROSTER_TAIL": ("roster_tail", 1, 1),
    "HP_CURRENT": ("hp_current", 0),
    "MOVEMENT_CURRENT": ("movement_current", 0),
    "FORMER_CLASS_LEVELS": ("former_class_levels", 0),
    "SPELLBOOK": ("spellbook", 0),
}


def check(found: list[dict]) -> int:
    """Every constant in :data:`CHECKED` against the instruction that sets it."""
    by_source = {(m["field"], m["index"]): m["dst"] for m in found}
    bad = 0
    for constant, row in sorted(CHECKED.items()):
        field, index, *rest = row
        back = rest[0] if rest else 0
        key = (field, index)
        want = getattr(amiga, constant, None)
        got = by_source.get(key)
        if got is not None:
            got -= back
        if want is None:
            print(f"  MISSING goldbox.amiga.{constant}")
            bad += 1
        elif got is None:
            print(f"  {constant}: the importer copies no {key[0]}[{key[1]}]")
            bad += 1
        elif want != got:
            print(f"  {constant} = {want:#05x}, the importer writes {got:#05x}")
            bad += 1
    print(f"{len(CHECKED) - bad} of {len(CHECKED)} constants match the engine")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="compare goldbox.amiga's constants with the engine")
    ap.add_argument("--json", type=pathlib.Path, help="write the map here")
    args = ap.parse_args()

    found = read()
    if args.json:
        args.json.write_text(json.dumps(found, indent=1))
    if args.check:
        return check(found)
    print(f"{'Silver Blades field':<30} {'idx':>3} {'len':>4}  "
          f"{'SSB':>6} {'PoD':>6}")
    for move in found:
        print(f"{move['field']:<30} {move['index']:>3} {move['size']:>4}  "
              f"{move['src']:#06x} {move['dst']:#06x}"
              f"{'  block' if move['block'] else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
