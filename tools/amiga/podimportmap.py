#!/usr/bin/env python3
"""Read Amiga *Pools of Darkness*' own Silver Blades importer, field by field.

Amiga Pools of Darkness carries a routine that turns an Amiga *Secret of the
Silver Blades* character record into one of its own.  It is a straight
field-by-field copy -- sixty-odd `move.b $src(a3), $dst(a2)` and six block
copies -- and `goldbox.amiga_port.SILVER_BLADES_DELTAS` already names every source
offset, because `#55 (Decode the Amiga Curse and Silver Blades records)`
decoded that record.  So the routine reads as a table of "Silver Blades'
*name* lives at Pools of Darkness' `0xY`", written by the engine itself.

That is what decoded the rest of the `.pc` for
`#462 (Decode the rest of the Amiga Pools of Darkness .pc: 37 of 75 neutral
fields have no home in it, so a converted character loses his spells and
possessions)`, including the two regions no specimen could ever have shown:
the spellbook, which the importer plants at `0x159`, and the combat block,
which Pools of Darkness splits between `0x5E`-`0x5F` and `0x184`-`0x185`.

    tools/amiga/podimportmap.py                 # the map, as the engine writes it
    tools/amiga/podimportmap.py --check         # against goldbox.amiga_pod's constants
    tools/amiga/podimportmap.py --thac0         # the attack table, and every reference to it
    tools/amiga/podimportmap.py --json out.json

`--thac0` answers the one field the importer could not: **this title keeps no
`attack_level`**.  The two routines that derive `thac0_base` index one attack
table with a class level, and the arithmetic reproduces the stored byte of
every `.pc` on the player's disks -- see :func:`thac0_table`,
:func:`dual_class_level_counts` and :func:`check_thac0` -- and no other
routine reaches the table through the small-data register, which
:func:`attack_table_sites` searches for.  `--thac0` combines
with `--check` and `--json`, and the exit status is non-zero if any of them
disagrees with the engine.

The executable is read out of the player's own disk images, read-only, and
nothing is written anywhere but `--json`.  Needs `capstone`.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import amiga_pod, amiga_port, dos_port  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools.amiga import amiga68k, amigasaves  # noqa: E402

#: The importer, found by `tools/amiga/amigarecordrefs.py 159` and read from its own
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
    shape = amiga_port.SILVER_BLADES_DELTAS
    fields = {f.name: f for f in dos_port.layout_for(shape.dos)}
    book = shape.offset(fields["hp_max"].offset) + 1
    if book <= offset < book + shape.spellbook_bytes:
        return "spellbook", offset - book
    for field in dos_port.layout_for(shape.dos):
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


#: What `goldbox/amiga_pod.py` says, for `--check`.  A name here is the module's
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
        want = getattr(amiga_pod, constant, None)
        got = by_source.get(key)
        if got is not None:
            got -= back
        if want is None:
            print(f"  MISSING goldbox.amiga_pod.{constant}")
            bad += 1
        elif got is None:
            print(f"  {constant}: the importer copies no {key[0]}[{key[1]}]")
            bad += 1
        elif want != got:
            print(f"  {constant} = {want:#05x}, the importer writes {got:#05x}")
            bad += 1
    print(f"{len(CHECKED) - bad} of {len(CHECKED)} constants match the engine")
    return 1 if bad else 0


#: The attack table, as a displacement off the small-data register: the two
#: routines that derive `thac0_base` both reach it with `lea.l -$621e(a4), a0`,
#: which is `data + 0x1DE0`.  Seven rows, one a class slot, twenty-two bytes
#: each -- one a level, indexed from 1, with the engine's own cap of 21 --
#: and every entry is the family's stored `60 - THAC0`.
THAC0_TABLE = 0x1DE0
THAC0_TABLE_STRIDE = 0x16
THAC0_TABLE_CAP = 0x15
#: The two routines that derive `thac0_base`, at the instruction in each that
#: stores the table entry: `0x03C294` rebuilds a character's derived fields
#: and `0x00EFDC` is character creation.  Both index the same table with a
#: class level and nothing else, which is what says this title has no
#: `attack_level` byte.
THAC0_SITES = (0x03C294, 0x00EFDC)
#: The race the gate at `0x03CFB2` tests for, `cmpi.b #$5, $58(a2)`: the
#: human, which is the only race AD&D lets dual-class.
DUAL_CLASS_RACE = amiga_pod.RACES.index("HUMAN")
#: How far before the store in :data:`THAC0_SITES` its routine may reach the
#: table: the earliest reference in either routine is 0x30 bytes before its
#: store, and 0x40 is the window that holds both with room for a rebuild.
THAC0_SITE_WINDOW = 0x40


def thac0_table(data: bytes) -> list[list[int]]:
    """The attack table off the player's own executable, a row a class slot.

    Read at run time rather than committed: it is the game's own data table.
    """
    exe = amiga68k.Executable.parse(data)
    hunk = exe.small_data
    if hunk is None:
        raise SystemExit("this build is not a small-data program")
    at = hunk.file_offset + THAC0_TABLE
    rows = len(amiga_pod.CLASS_LEVEL_SLOTS)
    if not 0 <= at or at + rows * THAC0_TABLE_STRIDE > len(data):
        raise SystemExit(
            f"the attack table would run from {at:#x} to "
            f"{at + rows * THAC0_TABLE_STRIDE:#x} in a {len(data)}-byte "
            f"executable: this is not the build the displacement was read in")
    return [list(data[at + n * THAC0_TABLE_STRIDE:
                      at + (n + 1) * THAC0_TABLE_STRIDE])
            for n in range(rows)]


def dual_class_level_counts(char: "amiga_pod.PodCharacter") -> bool:
    """Whether the engine lets this character's former class levels count.

    `0x03D046` asks `0x03D020` before it reads the former array, and the
    answer is two tests, both read off the listing:

    * `0x03CFB2` returns 0 unless the record's race byte at `0x58` is
      :data:`DUAL_CLASS_RACE`; for a human it returns the level in the first
      non-zero class slot, scanning slots 0 to 5 and falling through to slot 6.
    * `0x03D020` returns 1 only when that level is **greater than** the byte
      at `0x8A`, which is the level he left his old class at.

    When it returns 0 the former array contributes nothing at all, which is
    what makes this a gate rather than a bare `max` of the two arrays.

    **Read from the listing and not measured**: `former_class_levels` is zero
    in all nineteen `.pc` files on the Amiga disks, so no record on this
    machine exercises either test.
    """
    if char.race != DUAL_CLASS_RACE:
        return False
    levels = char.class_levels
    current = next((level for level in levels[:6] if level), levels[6])
    return current > char.former_level


def thac0_base(table: list[list[int]],
               char: "amiga_pod.PodCharacter") -> int:
    """What the engine derives into `thac0_base`, from the class levels.

    `0x03C238` walks the seven class slots, asks `0x03D046` for each one's
    level, caps it at 21 and keeps the best row entry.  That level is the
    slot's own `class_levels` entry, and the `former_class_levels` entry as
    well when :func:`dual_class_level_counts` says the engine's gate lets it
    in.  No byte of the record takes part but the two level arrays, the race
    and `former_level`, which is the whole finding.
    """
    dual = dual_class_level_counts(char)
    best = 0
    for n, row in enumerate(table):
        level = char.class_levels[n]
        if dual:
            level = max(level, char.former_class_levels[n])
        if level:
            best = max(best, row[min(level, THAC0_TABLE_CAP)])
    return best


def check_thac0(table: list[list[int]], records: dict[str, bytes]) -> int:
    """The arithmetic against the `thac0_base` byte of every `.pc` given."""
    bad = 0
    for name, raw in sorted(records.items()):
        char = amiga_pod.PodCharacter.from_bytes(raw)
        want = thac0_base(table, char)
        if want != char.thac0_base:
            print(f"  {name}: the class levels give {want}, the record holds "
                  f"{char.thac0_base}")
            bad += 1
    print(f"{len(records) - bad} of {len(records)} records' thac0_base is "
          f"what the class levels alone give")
    return 1 if bad else 0


def attack_table_sites(data: bytes, start: int = 0,
                       end: int | None = None) -> list[tuple[int, str]]:
    """`(file offset, instruction)` for every `d16(a4)` that lands anywhere in
    the attack table, so that a routine reaching a row by any offset is found.

    The same candidate-and-decode search as `amigarecordrefs.sites`, which
    matches a positive displacement off an arbitrary register; a small-data
    global is a **negative** displacement off `a4`, so it cannot be reused
    and this decodes the same window and looks for `-$xxxx(a4)` instead.
    It sees only that addressing mode: a pointer to the table stored in a
    global, or an absolute address relocated by the loader, would not appear.
    """
    # Imported here because `amigarecordrefs` imports `capstone`, which is not
    # a declared dependency, and the rest of this module runs without it.
    import capstone

    from tools.amiga import amigarecordrefs

    end = len(data) if end is None else end
    first = THAC0_TABLE - amiga68k.SMALL_DATA_BIAS
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    found: dict[int, str] = {}
    for displacement in range(
            first, first + len(amiga_pod.CLASS_LEVEL_SLOTS) * THAC0_TABLE_STRIDE):
        word = struct.pack(">h", displacement)
        at = start - 1
        while True:
            at = data.find(word, at + 1, end)
            if at < 0:
                break
            if at % 2:
                continue
            for back in amigarecordrefs.BACK:
                begin = at - back
                if begin < start:
                    continue
                try:
                    one = next(md.disasm(data[begin:begin + 12], begin, count=1))
                except StopIteration:
                    continue
                if (f"-${-displacement:x}(a4)" in one.op_str
                        and one.size >= back + 2):
                    found[begin] = f"{one.mnemonic} {one.op_str}"
                    break
    return sorted(found.items())


def check_attack_table_sites(sites: list[tuple[int, str]]) -> int:
    """Whether every reference to the table sits in one of the two routines
    :data:`THAC0_SITES` names, which is what "no third" rests on."""
    stray = [(at, text) for at, text in sites
             if not any(0 <= site - at <= THAC0_SITE_WINDOW
                        for site in THAC0_SITES)]
    for at, text in stray:
        print(f"  {at:06x}: {text} -- outside both routines")
    print(f"{len(sites) - len(stray)} of {len(sites)} references to the attack "
          f"table are in the two routines that derive thac0_base")
    return 1 if stray or not sites else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="compare goldbox.amiga_pod's constants with the engine")
    ap.add_argument("--thac0", action="store_true",
                    help="the attack table, against every .pc on the disks, "
                         "and every place the engine reaches it")
    ap.add_argument("--json", type=pathlib.Path, help="write the map here")
    args = ap.parse_args()

    bad = 0
    if args.thac0:
        table = thac0_table(executable())
        print("the attack table at data + "
              f"{THAC0_TABLE:#x}, indexed by class level, read at "
              + " and ".join(f"{site:#08x}" for site in THAC0_SITES) + ":")
        for name, row in zip(amiga_pod.CLASS_LEVEL_SLOTS, table):
            print(f"{name:<11} " + " ".join(f"{b:3d}" for b in row))
        from tools.amiga.podpcregions import pc_files

        bad |= check_thac0(table, pc_files())
        from tools.amiga import amigarecordrefs

        data = executable(quiet=True)
        start, end = amigarecordrefs.code_range(data)
        bad |= check_attack_table_sites(attack_table_sites(data, start, end))

    if not (args.check or args.json) and args.thac0:
        return bad
    found = read()
    if args.json:
        args.json.write_text(json.dumps(found, indent=1))
    if args.check:
        return bad | check(found)
    print(f"{'Silver Blades field':<30} {'idx':>3} {'len':>4}  "
          f"{'SSB':>6} {'PoD':>6}")
    for move in found:
        print(f"{move['field']:<30} {move['index']:>3} {move['size']:>4}  "
              f"{move['src']:#06x} {move['dst']:#06x}"
              f"{'  block' if move['block'] else ''}")
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
