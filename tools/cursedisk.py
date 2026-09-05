#!/usr/bin/env python3
"""Build a *Curse of the Azure Bonds* C64 save disk from a DOS save folder.

`tools/dosdisk.py` does this for Pool of Radiance and is that title's alone:
it writes `SAVEDGAME0`/`SAVEDGAME1` and never names a `Game`.  Curse's
container is one 7424-byte `SAVEAZURE` at `$4B00` with eight slots, a name
table, eight item pages, the explored map and the roster all inside the one
payload (`goldbox/c64_save.py`, `#192 (Convert a Curse of the Azure Bonds DOS
save into a C64 one, which the importer refuses today)` steps 1 and 2), so
the two tools differ by more than a flag and this is a second file rather
than a `--game` on the first.

    tools/cursedisk.py --folder work/curse/H-square-5-13 --slot H \\
        --out work/issue192/CURSESAVE.D64 --report --sheet

**Two things it reaches past deliberately, and both are step 4's to remove.**

* `goldbox.dos.CONVERTS` holds Pool of Radiance alone, so `to_neutral`
  refuses Curse.  This tool adds Curse to that tuple **in its own process**,
  the same way `tests/test_curseconvert.py`'s `converts_curse` fixture does.
  Nothing a user runs is changed: `File > Import` still refuses Curse until
  somebody edits `goldbox/dos.py`.
* `goldbox/areas.py` has no Curse rows.  `#192` step 0b measured all
  twenty-five off Curse's own `ECL` bytecode -- id, disk side and the maps
  each script loads -- and `goldbox/areas.py` belonged to another ticket the
  night they were measured, so they are carried here and injected into
  `areas.TABLES` for this process only.  `tools/areatable.py
  curse-of-the-azure-bonds --python` re-derives them from the disks, and
  `--check-areas` here runs that comparison rather than trusting the copy.

Everything else is the shipped conversion.  No byte comes from another save:
`goldbox.dos.new_save` refuses a payload with an unsourced byte in it, and
the two things no DOS save can supply -- the 36-byte combat icon and
`ANIMATE00` -- are read off the player's own Curse sides at run time.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from types import MappingProxyType

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import gamedisks  # noqa: E402

from goldbox import areas, dos, dos_layout, games  # noqa: E402
from goldbox.d64 import D64, load_payload  # noqa: E402
from goldbox.iconparts import IconParts  # noqa: E402

CURSE = games.CURSE_OF_THE_AZURE_BONDS
U = areas.Confidence.UNKNOWN

#: Curse's twenty-five areas: id, disk side, and the maps the script loads.
#:
#: Measured for `#192` step 0b by walking every `ECL` script's `LOADFILES`
#: operands from its five entry `GOTO`s, on both ports, and corroborated four
#: ways: a raw byte-pattern scan of the same operands agrees script for
#: script; the C64 sides and the DOS `GEO<n>.DAX` containers hold the same
#: sixteen maps; and the disk byte `$7F12` propagated forward to each
#: `NEWECL` agrees with the side the target script is on 23 times out of 23.
#: The `geos` column is CONFIRMED and is why the row cannot be derived from
#: the id: `ECL02` loads `GEO01`, `ECL22` loads `GEO21` and `ECL31` loads
#: `GEO32`, and five scripts load no map at all.
#:
#: No name and no arrival square: a conversion needs neither, and nobody has
#: named a Curse area.  `--check-areas` re-derives the whole table off the
#: disks and diffs it against this copy.
CURSE_AREAS: tuple[areas.Area, ...] = tuple(
    areas.Area(id=id, name=None, disk=disk, geos=geos, arrival=None,
               confidence=U, side_name="CURSE_{}")
    for id, disk, geos in (
        (0x01, 2, ("GEO01",)), (0x02, 2, ("GEO01",)), (0x03, 2, ("GEO03",)),
        (0x04, 2, ("GEO04",)), (0x10, 3, ("GEO10",)), (0x11, 3, ("GEO11",)),
        (0x12, 3, ()), (0x15, 3, ("GEO15",)), (0x1E, 1, ()),
        (0x20, 4, ("GEO20",)), (0x21, 4, ()), (0x22, 4, ("GEO21",)),
        (0x23, 4, ()), (0x25, 4, ("GEO25",)), (0x30, 5, ()),
        (0x31, 5, ("GEO32",)), (0x32, 5, ("GEO32",)), (0x33, 5, ("GEO33",)),
        (0x35, 5, ("GEO35",)), (0x40, 6, ("GEO40",)), (0x42, 6, ("GEO42",)),
        (0x43, 6, ("GEO43",)), (0x45, 6, ("GEO45",)), (0x50, 1, ()),
        (0x51, 1, ()),
    ))


def enable_curse() -> None:
    """Put Curse on `CONVERTS` and its areas in `TABLES`, in this process.

    Both are the header's two reach-arounds and neither is written to disk.
    `areas.TABLES` is what `areas_for`, `area_in` and `geos_in` all read, so
    replacing it is the whole injection -- `AREAS_BY_ID` stays Pool of
    Radiance's, which is right, because `areas.area()` is the C64-to-DOS
    direction and is not this tool's.
    """
    if dos_layout.CURSE_OF_THE_AZURE_BONDS not in dos.CONVERTS:
        dos.CONVERTS = tuple(dos.CONVERTS) + (
            dos_layout.CURSE_OF_THE_AZURE_BONDS,)
    if not areas.areas_for(CURSE.title):
        table = dict(areas.TABLES)
        table[CURSE.title] = CURSE_AREAS
        areas.TABLES = MappingProxyType(table)


def check_areas(disks: pathlib.Path) -> list[str]:
    """Re-derive the rows off the disks and say where the copy differs.

    `tools/areatable.py` walks each script's own control flow from its five
    entry `GOTO`s and reads the `LOADFILES` operands; this asks it for the
    same twenty-five rows and diffs the id, the side and the maps.  A copied
    table that nothing ever re-derives is a table that quietly goes stale.
    """
    import areatable

    _base, scripts = areatable.load_scripts(
        str(disks), CURSE, areatable.Machine(str(disks), CURSE))
    got = {s.id: (s.side, tuple(f"GEO{g:02X}" for g in s.geos()))
           for s in scripts.values()}
    want = {a.id: (a.disk, tuple(a.geos)) for a in CURSE_AREAS}
    out = []
    for id in sorted(set(got) | set(want)):
        if got.get(id) != want.get(id):
            out.append(f"  ${id:02X}: disks say {got.get(id)}, "
                       f"this table says {want.get(id)}")
    return out


def game_files(disks: pathlib.Path) -> tuple[bytes, bytes]:
    """The composed combat icon and `ANIMATE00`, off the player's own sides.

    Curse ships `SPELLE64` and `SPELLN64` the same way Pool of Radiance does
    -- `goldbox/iconparts.py` reads `SPELLE64` byte-identical in all three
    titles -- and `ANIMATE00` is on the sides that carry an area.  Neither
    can come from a DOS save and neither has a default: a conversion that
    cannot read them refuses rather than inventing bytes.
    """
    icon = animate = None
    for path in sorted(disks.glob("*.[dD]64")):
        if icon is None:
            try:
                icon = IconParts.load(str(path)).default_icon()
            except Exception:
                pass
        if animate is None:
            try:
                animate = load_payload(str(path), dos.ANIMATE_FILE)
            except Exception:
                pass
        if icon is not None and animate is not None:
            return icon, animate
    missing = [what for what, got in (("the icon tables", icon),
                                      ("ANIMATE00", animate)) if got is None]
    raise FileNotFoundError(f"no Curse side under {disks} carries "
                            + " or ".join(missing))


def build(folder: pathlib.Path, slot: str, disks: pathlib.Path,
          out: pathlib.Path):
    """Write `out` and return the report.  Nothing else is touched."""
    icon, animate = game_files(disks)
    save0, save1, report = dos.new_save(folder, slot, icon, animate,
                                        game=CURSE)
    disk: D64 = dos.save_disk(bytes(save0), bytes(save1), game=CURSE)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(disk.data)
    return save0, report


#: `60 - value`, the family's encoding for armour class and THAC0.  The sheet
#: shows the decoded number: the gap between the two is where an armour class
#: of 9 once reached a player as 51.
AC_BIAS = 60
SEXES = ("MALE", "FEMALE")
ALIGNMENTS = tuple(f"{law} {mood}"
                   for law in ("LAWFUL", "NEUTRAL", "CHAOTIC")
                   for mood in ("GOOD", "NEUTRAL", "EVIL"))


def sheet(folder: pathlib.Path, slot: str) -> list[str]:
    """The DOS party laid out the way the C64's `VIEW` screen shows it.

    Every line is something a person reads straight off the running game and
    compares.  Copied in shape from `tools/dosdisk.py`, with the memorised
    count added: Curse gives the list 69 slots where Pool of Radiance gives
    81 and `goldbox/layout.py` used to give 16
    (`#268 (A character with more than sixteen memorised spells loses the
    rest, because the layout gives the list sixteen bytes and the game gives
    it eighty-one)`), so how many spells each caster is holding is a number
    worth carrying to the memorise screen.
    """
    from goldbox import dos_savegame
    from goldbox.games import classes_to_names

    savgam = (folder / f"SAVGAM{slot}.DAT").read_bytes()
    where = dos_savegame.position(savgam)
    clock = dos_savegame.clock(savgam)
    out = [f"DOS slot {slot}: "
           + ("outdoors" if dos_savegame.outdoors(savgam) else "indoors")
           + f", square {where[0]},{where[1]} facing {where[2]}, "
             f"clock {clock[0]:02d}:{clock[1]:02d}, "
             f"area ${dos_savegame.current_area(savgam):02X}, "
             f"GEO{dos_savegame.geo_block(savgam):02X}"]
    for index, char in enumerate(dos.read_party(folder, slot)):
        n = dos.to_neutral(char).fields

        def v(name, default=0):
            return n[name].value if name in n else default

        coins = " ".join(f"{kind.upper()} {v(kind)}" for kind in
                         ("platinum", "gold", "electrum", "silver", "copper",
                          "gems", "jewelry") if v(kind))
        levels = ", ".join(f"{name} {count}" for name, count
                           in (v("levels", {}) or {}).items() if count)
        memorised = [s for s in (v("spells_memorised", []) or []) if s]
        out += [
            "",
            f"  {index + 1}. {v('name', '')}",
            f"     {SEXES[v('sex') & 1]} "
            f"{char.shape.race_numbers[v('race')].upper()} AGE {v('age')}"
            f"  {ALIGNMENTS[v('alignment')]}"
            f"  {'/'.join(classes_to_names(v('class_bits'), CURSE)).upper()}",
            f"     STR {v('strength')}"
            + (f"({v('exceptional_strength')})"
               if v("exceptional_strength") else "")
            + f" INT {v('intelligence')} WIS {v('wisdom')} "
              f"DEX {v('dexterity')} CON {v('constitution')} "
              f"CHR {v('charisma')}",
            f"     LEVEL {levels}  EXP {v('experience')}",
            f"     HITPOINTS {v('hp_current')} of {v('hp_max')}  "
            f"AC {AC_BIAS - v('armour_class')}  "
            f"THAC0 {AC_BIAS - v('thac0_current')}  "
            f"MOVE {v('movement_current')}",
            f"     {coins or 'no money'}",
            f"     {len(v('inventory', []) or [])} items, "
            f"{len(memorised)} spells memorised",
        ]
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--folder", required=True,
                   help="the DOS Curse save directory, read and never written")
    p.add_argument("--slot", default="H", help="the DOS save slot letter")
    p.add_argument("--disks", default=None,
                   help="where the player's Curse sides are; read, never "
                        "written.  $COAB_DISKS, then the gamedisks registry")
    p.add_argument("--out", default=None,
                   help="the .d64 to write (default "
                        "work/issue192/CURSE<slot>.D64)")
    p.add_argument("--report", action="store_true",
                   help="print the conversion's provenance summary")
    p.add_argument("--sheet", action="store_true",
                   help="print the DOS party the way the C64 VIEW screen "
                        "lays it out, to read against the running game")
    p.add_argument("--check-areas", action="store_true",
                   help="re-derive the area rows off the disks and diff them")
    p.add_argument("--no-write", action="store_true",
                   help="print only; build no disk")
    args = p.parse_args(argv)

    enable_curse()
    disks = pathlib.Path(
        args.disks or gamedisks.find("curse-of-the-azure-bonds") or "")
    folder = pathlib.Path(args.folder)

    if args.check_areas:
        bad = check_areas(disks)
        print("\n".join(bad) if bad
              else f"the {len(CURSE_AREAS)} rows agree with the disks")
        if bad:
            return 1
    if args.no_write:
        print("\n".join(sheet(folder, args.slot)))
        return 0

    out = pathlib.Path(args.out) if args.out else (
        ROOT / "work" / "issue192" / f"CURSE{args.slot}.D64")
    save0, report = build(folder, args.slot, disks, out)
    party = dos.read_party(folder, args.slot)
    print(f"Slot {args.slot}: {len(party)} characters -- "
          + ", ".join(c.name for c in party))
    print(f"Wrote {out} ({out.stat().st_size} bytes), "
          f"payload {len(save0)} bytes")
    print(f"Bytes left to the payload: {len(report.unwritten)}")
    if args.report:
        for line in report.summary_notes():
            print(line)
        for line in report.warnings:
            print(f"  warning: {line}")
    if args.sheet:
        print("\n".join(sheet(folder, args.slot)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
