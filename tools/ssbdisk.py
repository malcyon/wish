#!/usr/bin/env python3
"""Build a *Secret of the Silver Blades* C64 save disk from a DOS save folder.

The third of three: `tools/dosdisk.py` writes Pool of Radiance's
`SAVEDGAME0`/`SAVEDGAME1` pair and `tools/cursedisk.py` writes Curse of the
Azure Bonds' single `SAVEAZURE`.  Silver Blades' container is Curse's byte for
byte under the name `SAVEDBASH` -- one 7424-byte file at `$4B00`, eight
character pages, a name table at `+$C00`, eight item pages, `ANIMATE00`'s
picture buffer at `+$1800` and the roster at `+$1C00` -- but three header rows
differ and the name table may be keyed the other way round, so the geometry
lives in `goldbox/c64_save.py` and this file is the runner (`#193 (Convert a Secret of
the Silver Blades DOS save into a C64 one, which the importer refuses today)`).

    tools/ssbdisk.py --folder work/curse/SSB-D-paine-memorised --slot D \\
        --out work/193/SSBD.D64 --report --sheet

**`enable_ssb()` is a reach-around and says so.** `goldbox.dos.CONVERTS` does
not carry Silver Blades: the refusal in `goldbox/dos.py` stands until a party
this tool built has been loaded in the running game and read off the screen,
which is `#193` step 3.  This tool puts the shape on `CONVERTS` **in its own
process only**, the same way `tools/cursedisk.py` did while `#192` was open.
When `CONVERTS` takes Silver Blades the call becomes a no-op and can stay.

`goldbox/areas.py` already carries this title's twenty-two rows, every one
CONFIRMED by a driven fast travel under `#20 (Build an area table for Silver
Blades)`, so there is no copy of the table here -- `--check-areas` re-derives
them off the disks and diffs them against `goldbox.areas` rather than against
a second copy that could go stale on its own.

No byte comes from another save: `goldbox.dos.new_save` refuses a payload with
an unsourced byte in it, and the one thing no DOS save can supply -- the
36-byte combat icon -- is composed from `SPELLE64` on the player's own sides
at run time.  **This title stages no `ANIMATE00` into the save**, because its
roster lives in the payload and there is no second file to put one in.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import gamedisks  # noqa: E402

from goldbox import areas, dos, dos_layout, games  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.iconparts import IconParts  # noqa: E402

SSB = games.SECRET_OF_THE_SILVER_BLADES


def enable_ssb() -> None:
    """Put Silver Blades on `CONVERTS`, in this process and nowhere else.

    Guarded on "is this already true", so it is a no-op on a checkout where
    `#193` step 4 has landed and a copy of this file still runs there.
    """
    if dos_layout.SECRET_OF_THE_SILVER_BLADES not in dos.CONVERTS:
        dos.CONVERTS = tuple(dos.CONVERTS) + (
            dos_layout.SECRET_OF_THE_SILVER_BLADES,)


def check_areas(disks: pathlib.Path) -> list[str]:
    """Re-derive the rows off the disks and diff them against `goldbox.areas`.

    `tools/areatable.py` walks each script's own control flow from its five
    entry `GOTO`s and reads the `LOADFILES` operands.  A table nothing ever
    re-derives is a table that quietly goes stale, and this one is consumed
    by `apply_file_cache` on every conversion.
    """
    import areatable

    _base, scripts = areatable.load_scripts(
        str(disks), SSB, areatable.Machine(str(disks), SSB))
    got = {s.id: (s.side, tuple(f"GEO{g:02X}" for g in s.geos()))
           for s in scripts.values()}
    want = {a.id: (a.disk, tuple(a.geos))
            for a in areas.areas_for(SSB.title)}
    out = []
    for id in sorted(set(got) | set(want)):
        if got.get(id) != want.get(id):
            out.append(f"  ${id:02X}: disks say {got.get(id)}, "
                       f"goldbox/areas.py says {want.get(id)}")
    return out


def combat_icon(disks: pathlib.Path) -> bytes:
    """The 36-byte icon the game's own character creation composes.

    `goldbox/iconparts.py` reads `SPELLE64` byte-identical in all three C64
    titles, so this is the same call Curse's and Pool of Radiance's tools
    make.  There is no default: a conversion that cannot read it would have
    to invent bytes, and it refuses instead.
    """
    for path in sorted(disks.glob("*.[dD]64")):
        try:
            return IconParts.load(str(path)).default_icon()
        except Exception:
            continue
    raise FileNotFoundError(
        f"no Silver Blades side under {disks} carries the icon tables")


def build(folder: pathlib.Path, slot: str, disks: pathlib.Path,
          out: pathlib.Path):
    """Write `out` and return `(payload, report)`.  Nothing else is touched."""
    icon = combat_icon(disks)
    save0, save1, report = dos.new_save(folder, slot, icon, animate=None,
                                        game=SSB)
    disk: D64 = dos.save_disk(bytes(save0), bytes(save1), game=SSB)
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
    compares.  The memorised count is this title's own width -- 74 slots at
    `0x01B`, the only measured title whose list does not start at `0x020`
    (`goldbox.c64_codec.memorised_span`) -- so how many spells each caster is
    holding is a number to carry to the memorise screen.
    """
    from goldbox import dos_savegame
    from goldbox.games import classes_to_names

    shape = dos_savegame.save_shape_for(SSB.key)
    savgam = (folder / f"SAVGAM{slot}{shape.suffix}").read_bytes()
    where = dos_savegame.position(savgam, shape)
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
            f"  {'/'.join(classes_to_names(v('class_bits'), SSB)).upper()}",
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
                   help="the DOS Silver Blades save directory, read and "
                        "never written")
    p.add_argument("--slot", default="D", help="the DOS save slot letter")
    p.add_argument("--disks", default=None,
                   help="where the player's Silver Blades sides are; read, "
                        "never written.  $SSB_DISKS, then the registry")
    p.add_argument("--out", default=None,
                   help="the .d64 to write (default work/193/SSB<slot>.D64)")
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

    enable_ssb()
    disks = pathlib.Path(
        args.disks or gamedisks.find("secret-of-the-silver-blades") or "")
    folder = pathlib.Path(args.folder)

    if args.check_areas:
        bad = check_areas(disks)
        print("\n".join(bad) if bad
              else f"the {len(areas.areas_for(SSB.title))} rows in "
                   f"goldbox/areas.py agree with the disks")
        if bad:
            return 1
    if args.no_write:
        print("\n".join(sheet(folder, args.slot)))
        return 0

    out = pathlib.Path(args.out) if args.out else (
        ROOT / "work" / "193" / f"SSB{args.slot}.D64")
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
