#!/usr/bin/env python3
"""Six Silver Blades characters SSI wrote twice, converted and diffed (#193).

Secret of the Silver Blades ships the same party on both ports: DOS
`CHRDAT<slot>1`-`6` and the C64 `SAVEDBASH` on `SILVER-6.D64` hold GUY DE
VALOIS, EPONA, PAINE, DOMINIC, MALACHITE and MORGAINE.  So the DOS record and
the C64 record of one character are two descriptions of the same character
written by the same publisher, and running the conversion on the first and
diffing against the second says which fields a converted Silver Blades record
gets wrong -- **before any of it is loaded in the game**.

    ssbtwins.py                              the field-by-field table
    ssbtwins.py --folder work/curse/SSB-C-items --slot A
    ssbtwins.py --bytes                      every differing byte run

**This is a consistency check and not proof.**  `.claude/rules/testing.md`:
a save found on a disk has no chain of custody, so neither side is evidence
about the game on its own.  What it is good for is the *shape* of the
disagreement -- a field this project calls DIRECT differing on all six is a
wrong offset or a wrong encoding, and that is a defect in our table rather
than a fact about SSI's party.

It reaches past `goldbox.dos.CONVERTS` **in its own process only**, the same
way `tests/test_curseconvert.py` did while `#192` was open, so that the
refusal in `goldbox/dos.py` can stay where it is until a run in the game has
earned its removal.

Nothing here prints a name, a spell or an item text of the game's: the
output is field names, offsets and byte values.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos, dos_layout, games, layout  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402
from goldbox.savegame import SaveGame0, SaveGame1  # noqa: E402
from tools import gamedisks  # noqa: E402

GAME = games.SECRET_OF_THE_SILVER_BLADES
SHIPPED_SIDE = "SILVER-6.D64"
SHIPPED_DOS = ("Forgotten Realms The Archives - Collection Two/games/SECRET/"
               "Default files/Saves")


def shipped_c64(disks: pathlib.Path | None) -> bytes:
    """The `SAVEDBASH` payload off the player's own side 6."""
    if disks is None:
        raise SystemExit("no Silver Blades disks: set $SSB_DISKS or add a row "
                         "to gamedisks.local.toml")
    side = pathlib.Path(disks) / SHIPPED_SIDE
    if not side.is_file():
        matches = sorted(pathlib.Path(disks).glob("*6.[dD]64"))
        if not matches:
            raise SystemExit(f"no {SHIPPED_SIDE} under {disks}")
        side = matches[0]
    disk = D64(side.read_bytes())
    _, payload = split_load_address(disk.read_file(GAME.save_file))
    return bytes(payload)


def c64_twins(payload: bytes) -> dict[str, CharacterRecord]:
    """The shipped party's records, by name, with roster and items joined on.

    A save slot stores 256 of the 580 bytes; the rest is the roster block, the
    item page and the icon.  `goldbox.dos.convert_save` writes exactly those
    four regions, so this rebuilds the same four to compare like with like.
    """
    save = SaveGame0(payload, GAME)
    roster = SaveGame1(save.roster_page(), GAME)
    out: dict[str, CharacterRecord] = {}
    for index, slot in enumerate(save.slots):
        if not slot.occupied:
            continue
        whole = bytearray(layout.RECORD_SIZE)
        whole[:0x100] = slot.record_bytes[:0x100]
        whole[0x100:0x120] = roster.roster(index).raw
        page = payload[0x1000 + index * 0x100:0x1000 + (index + 1) * 0x100]
        whole[0x120:0x220] = page
        icon = payload[0x2E0 + index * 36:0x2E0 + (index + 1) * 36]
        whole[0x220:0x244] = icon
        rec = CharacterRecord(bytes(whole))
        out[rec.get("name").upper().strip()] = rec
    return out


#: Fields that cannot agree between two ports of one character and are not
#: findings.  Each is a number one engine rolled and the other rolled
#: separately, or a value only one port keeps.
ROLLED = {
    "hp_rolled", "hp_max", "hp_current", "age", "saving_throws",
    "thief_skills", "exceptional_strength", "money_platinum", "money_gold",
    "money_electrum", "money_silver", "money_copper", "money_gems",
    "money_jewelry", "encumbrance",
}
PORT_ONLY = {
    "icon_head", "icon_body", "icon_colours", "portrait_head",
    "portrait_body", "unnamed_0ec", "identity_pair", "party_order",
    "combat_icon",
}


def compare(dos_rec: CharacterRecord, c64_rec: CharacterRecord
            ) -> list[tuple[str, str, str]]:
    rows = []
    for field in layout.iter_fields():
        if field.name.startswith("gap_"):
            continue
        a = dos_rec.get_raw(field.name)
        b = c64_rec.get_raw(field.name)
        if a != b:
            rows.append((field.name, a.hex(" "), b.hex(" ")))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--folder", default=None,
                    help="a DOS Silver Blades save directory")
    ap.add_argument("--slot", default="A")
    ap.add_argument("--disks", default=None, help="the C64 sides")
    ap.add_argument("--bytes", action="store_true",
                    help="also print each differing field's bytes")
    args = ap.parse_args(argv)

    folder = args.folder
    if folder is None:
        archives = gamedisks.find("dos-archives")
        if archives is None:
            raise SystemExit("no DOS archives: set $FR_ARCHIVES or pass "
                             "--folder")
        folder = pathlib.Path(archives) / SHIPPED_DOS
    disks = args.disks or gamedisks.find("secret-of-the-silver-blades")

    # In this process only: the refusal in goldbox/dos.py stands until a run
    # in the running game has earned its removal (#193 step 3).
    if dos_layout.SECRET_OF_THE_SILVER_BLADES not in dos.CONVERTS:
        dos.CONVERTS = dos.CONVERTS + (dos_layout.SECRET_OF_THE_SILVER_BLADES,)

    twins = c64_twins(shipped_c64(pathlib.Path(disks) if disks else None))
    party = dos.read_party(folder, args.slot)
    print(f"{len(party)} DOS records from {folder} slot {args.slot}")
    print(f"{len(twins)} C64 records from the shipped {GAME.save_file.decode()}")
    print()
    total = 0
    for char in party:
        rec, _report = dos.to_c64_record(char, icon=bytes(36))
        name = char.name.upper().strip()
        twin = twins.get(name)
        if twin is None:
            print(f"{name}: no C64 twin of that name")
            continue
        rows = compare(rec, twin)
        total += len(rows)
        print(f"{name}: {len(rows)} fields differ")
        for field, a, b in rows:
            tag = ("rolled" if field in ROLLED else
                   "port-only" if field in PORT_ONLY else "**")
            if args.bytes:
                print(f"    {tag:10} {field:26} ours {a}  |  theirs {b}")
            else:
                print(f"    {tag:10} {field}")
    print()
    print(f"{total} differing fields over {len(party)} characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
