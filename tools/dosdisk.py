#!/usr/bin/env python3
"""Build a C64 save disk from a DOS save folder, owing nothing to another save.

This is the command-line form of what `File > Import` does after #118: read a
DOS *Pool of Radiance* save slot, write all 9216 bytes of `SAVEDGAME0` and
`SAVEDGAME1` from two zeroed buffers, and put them on a `D64.blank()`.  No
existing `.d64` is opened at any point.

    tools/dosdisk.py --slot J --out work/NEWJ.D64

Two bytes of the result cannot be computed from the DOS save and are read off
the player's own game disks at run time, which is Donald's ruling of
2026-08-27 -- *"We should never attempt to write a save file if we don't have
the game disks and we need them.  That would mean making up data, which we
will not do."*:

* the 36-byte combat icon each character gets, composed by
  `goldbox.iconparts.IconParts.default_icon` off `SPELLE64`/`SPELLN64`;
* `ANIMATE00`'s 852 payload bytes, which sit at `$8400` in `SAVEDGAME1`.

So it refuses without them rather than inventing either.

The DOS folder is found the way `tools/dosbox.py` finds it -- `$FR_ARCHIVES`,
then `~/Downloads/fr-archives` -- and the game disks the way every other tool
here does: `$POR_DISKS`, then `automap.paths.find_disks()`.  Both are read and
never written; the output goes wherever `--out` says, which should be under
`work/`.

`--report` prints the conversion's own provenance summary, which is the check
that matters: a from-nothing save has `unwritten` empty, and `new_save` raises
rather than returning one with a byte in it.

`--sheet` prints the DOS party the way the C64's own `VIEW` screen lays it
out, which is what #119 asks a person to compare the running game against.
Bytes matching is necessary and not sufficient: an AC of 9 displayed as 51, a
dropped combat tail and a garbage weapon line are three faults this project
has shipped that passed every byte-level check that existed.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

from automap.paths import find_disks  # noqa: E402
from goldbox import dos  # noqa: E402
from goldbox.d64 import D64, load_payload  # noqa: E402
from goldbox.iconparts import IconParts  # noqa: E402

#: Where the player keeps the C64 game disks.  Read only.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")


def dos_folder() -> pathlib.Path:
    """The DOS save directory inside the player's archives.

    `tools/dosbox.py` already knows how to find a game tree and this reuses
    it rather than spelling a second search out; the saves live in `SAVE`
    beside `START.EXE`.
    """
    import dosbox

    return dosbox.find_game("POOLRAD") / "SAVE"


def game_files(disks: pathlib.Path) -> tuple[bytes, bytes]:
    """The composed icon and `ANIMATE00`, off whichever disk carries each.

    `ANIMATE00` is byte-identical on all eight `POOL` sides and the icon
    tables are on `POOL3`, so this walks the directory rather than naming a
    side -- the same shape as `EditorWindow._find_disk`.
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
    raise FileNotFoundError(f"no game disk under {disks} carries "
                            + " or ".join(missing))


def build(folder: pathlib.Path, slot: str, disks: pathlib.Path,
          out: pathlib.Path) -> dos.C64SaveReport:
    """Write `out` and return the report.  Nothing else is touched."""
    icon, animate = game_files(disks)
    save0, save1, report = dos.new_save(folder, slot, icon, animate)
    disk: D64 = dos.save_disk(bytes(save0), bytes(save1))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(disk.data)
    return report


#: `60 - value` is the family's encoding for both armour class and THAC0 --
#: `goldbox/dos_layout.py` 0x111 and 0x110, where SILAS' 63 is AC -3.  The
#: sheet shows the decoded number, and the gap between the two is where an
#: AC of 9 once reached a player as 51.
AC_BIAS = 60

#: What the C64 sheet calls the two sexes and the nine alignments, in the
#: game's own order -- `goldbox/layout.py` 0x0E9 and `goldbox/dos_layout.py`
#: 0x0A0, both 0-based on the table at `$32B3`.
SEXES = ("MALE", "FEMALE")
ALIGNMENTS = tuple(f"{law} {mood}"
                   for law in ("LAWFUL", "NEUTRAL", "CHAOTIC")
                   for mood in ("GOOD", "NEUTRAL", "EVIL"))


def sheet(folder: pathlib.Path, slot: str) -> list[str]:
    """The DOS party laid out the way the C64's `VIEW` screen shows it.

    Every line here is something a person can read straight off the running
    game and compare, which is the check #119 exists for.  The numbers are
    the DOS save's own: `armour_class` and `thac0_current` are decoded
    through `60 - value` because that is what both ports display, and the
    money and experience are printed unrounded.
    """
    from goldbox import dos_layout, dos_savegame
    from goldbox.games import classes_to_names

    savgam = (folder / f"SAVGAM{slot}.DAT").read_bytes()
    where = dos_savegame.position(savgam)
    clock = dos_savegame.clock(savgam)
    out = [f"DOS slot {slot}: "
           + ("outdoors" if dos_savegame.outdoors(savgam) else "indoors")
           + f", square {where[0]},{where[1]} facing {where[2]}, "
             f"clock {clock[0]:02d}:{clock[1]:02d}"]
    for index, char in enumerate(dos.read_party(folder, slot)):
        n = dos.to_neutral(char).fields

        def v(name, default=0):
            return n[name].value if name in n else default

        coins = " ".join(f"{kind.upper()} {v(kind)}" for kind in
                         ("platinum", "gold", "electrum", "silver", "copper",
                          "gems", "jewelry") if v(kind))
        levels = ", ".join(f"{name} {count}" for name, count
                           in (v("levels", {}) or {}).items() if count)
        out += [
            "",
            f"  {index + 1}. {v('name', '')}",
            f"     {SEXES[v('sex') & 1]} "
            f"{dos_layout.RACE_NUMBERS[v('race')].upper()} AGE {v('age')}"
            f"  {ALIGNMENTS[v('alignment')]}"
            f"  {'/'.join(classes_to_names(v('class_bits'))).upper()}",
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
            f"     {len(v('inventory', []) or [])} items",
        ]
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--slot", default="J", help="the DOS save slot letter")
    p.add_argument("--folder", default=None,
                   help="the DOS save directory; found in the archives if not "
                        "given")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's C64 disks are; read, never written")
    p.add_argument("--out", default=None,
                   help="the .d64 to write (default work/dosdisk/NEW<slot>.D64)")
    p.add_argument("--report", action="store_true",
                   help="print the conversion's provenance summary")
    p.add_argument("--sheet", action="store_true",
                   help="print the DOS party the way the C64 VIEW screen "
                        "lays it out, to read against the running game")
    p.add_argument("--no-write", action="store_true",
                   help="print only; build no disk")
    args = p.parse_args(argv)

    folder = pathlib.Path(args.folder) if args.folder else dos_folder()
    if args.no_write:
        print("\n".join(sheet(folder, args.slot)))
        return 0
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "work" / "dosdisk" / f"NEW{args.slot}.D64")
    report = build(folder, args.slot, pathlib.Path(args.disks), out)
    party = dos.read_party(folder, args.slot)
    print(f"Slot {args.slot}: {len(party)} characters -- "
          + ", ".join(c.name for c in party))
    print(f"Wrote {out} ({out.stat().st_size} bytes)")
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
