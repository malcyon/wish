#!/usr/bin/env python3
"""Display everything we can currently read from a Pool of Radiance save disk.

    tools/show.py "/mnt/media/roms/c64/Pool of Radiance Disks/PORSAVE.D64"

Fields are annotated with how much we trust them:
  (no mark) CONFIRMED   ~ PROBABLE   ? GUESS
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from por import layout
from por.d64 import D64
from por.items import items_for_slot, load_item_names
from por.layout import Confidence
from por.record import RECORD_SIZE, CharacterRecord
from por.savegame import SaveGame0

RACES = {1: "dwarf", 2: "elf", 3: "gnome", 4: "half-elf",
         5: "halfling", 6: "half-orc", 7: "human", 8: "monster"}
# The standard Gold Box class order -- NOT the order of the 6-entry creation
# menu at $3288, which misled an earlier version of this file into calling a
# magic-user a monk. Confirmed by saving throws: code 5 carries the AD&D 1e L1
# magic-user table exactly.
CLASSES = {0: "cleric", 1: "druid", 2: "fighter", 3: "paladin",
           4: "ranger", 5: "magic-user", 6: "thief", 7: "monk"}
ALIGNMENTS = ["lawful good", "lawful neutral", "lawful evil",
              "neutral good", "true neutral", "neutral evil",
              "chaotic good", "chaotic neutral", "chaotic evil"]
CLASS_BITS = [(1, "magic-user"), (2, "cleric"), (4, "thief"), (8, "fighter")]

MARK = {Confidence.CONFIRMED: " ", Confidence.PROBABLE: "~", Confidence.GUESS: "?"}


def conf(name: str) -> str:
    f = layout.field_by_name(name)
    return MARK.get(f.confidence, " ")


def u24(rec: CharacterRecord) -> int:
    raw = rec.get_raw("experience")
    return raw[0] | raw[1] << 8 | raw[2] << 16


def show_items(items) -> None:
    if not items:
        return
    total = sum(i.weight_lb * max(i.quantity, 1) for i in items)
    print(f"      carrying ({total:.1f} lb):")
    for i in items:
        qty = f" x{i.quantity}" if i.quantity else ""
        rdy = " (readied)" if i.readied else ""
        print(f"        {i.name}{qty}{rdy}")


def show_record(rec: CharacterRecord, where: str) -> None:
    race = RACES.get(rec.race, f"?{rec.race}")
    # class_bits is authoritative and handles multi-class; char_class is the
    # single-class code and cannot express combinations.
    cls = "/".join(name for bit, name in CLASS_BITS if rec.class_bits & bit) \
          or CLASSES.get(rec.char_class, f"code {rec.char_class}")
    align = ALIGNMENTS[rec.alignment] if rec.alignment < 9 else f"?{rec.alignment}"
    sex = "female" if rec.sex else "male"
    stren = f"{rec.strength}"
    if rec.strength == 18 and rec.exceptional_strength:
        stren = f"18/{rec.exceptional_strength:02d}"

    print(f"  {where}  {rec.name}")
    print(f"      {sex} {race} {cls}, {align}, age {rec.age}")
    print(f"      STR {stren:<6} INT {rec.intelligence:<3} WIS {rec.wisdom:<3} "
          f"DEX {rec.dexterity:<3} CON {rec.constitution:<3} CHA {rec.charisma}")
    # hp_current lives at 0x119, past the 256 bytes a save slot stores, so it
    # only reads from an exported .chr. Show max alone rather than a false 0.
    hp = (f"{rec.hp_current}/{rec.hp_max}{conf('hp_max')}"
          if rec.hp_current else f"{rec.hp_max}{conf('hp_max')}")
    print(f"      hp {hp}"
          f"   move {rec.movement}   infravision {rec.infravision * 10}ft"
          f"   thac0 {rec.thac0}{conf('thac0')}")
    if rec.class_bits & 4:
        print(f"      thief  pick {rec.thief_pick_pockets}%  locks "
              f"{rec.thief_open_locks}%  traps {rec.thief_find_traps}%  "
              f"silent {rec.thief_move_silently}%  hide {rec.thief_hide_in_shadows}%"
              f"  hear {rec.thief_hear_noise}%  climb {rec.thief_climb_walls}%"
              f"  langs {rec.thief_read_languages}%")
    print(f"      saves  para {rec.save_paralysis}  petr {rec.save_petrification}  "
          f"wand {rec.save_wands}  breath {rec.save_breath}  spell {rec.save_spell}")
    coins = [("cp", rec.copper), ("sp", rec.silver), ("ep", rec.electrum),
             ("gp", rec.gold), ("pp", rec.platinum),
             ("gems", rec.gems), ("jewelry", rec.jewelry)]
    money = "  ".join(f"{v} {k}" for k, v in coins if v) or "nothing"
    print(f"      money{conf('gold')} {money}     xp{conf('experience')} {u24(rec)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    args = ap.parse_args()

    names = None
    # GAME_DISK was a name that never existed, so this loop had always raised
    # NameError before it could find anything.
    for candidate in (os.environ.get("POR_GAME_DISK"), "work/POOL1.D64.orig"):
        if not candidate:
            continue
        try:
            names = load_item_names(candidate)
            break
        except Exception:
            continue          # item names need a readable game disk
    img = D64.open(args.path)
    print(f"{args.path}")
    print(f"disk {img.disk_name!r}  id {img.disk_id!r}   {len(img.directory())} files\n")

    print("Directory")
    for e in img.directory():
        print(f"  {e.block_count:4d} blk  {e.type_name}  {e.display_name}")
    print()

    for entry in img.directory():
        name = bytes(entry.raw_name).rstrip(b"\xa0")
        if name == b"SAVEDGAME0":
            sg = SaveGame0.from_prg(img.read_file(entry))
            occupied = sg.characters
            print(f"SAVEDGAME0 — party ({len(occupied)} of 6 slots in use)\n")
            for slot in sg.slots:
                if slot.occupied:
                    show_record(slot.record, f"slot {slot.index} ${slot.address:04X}")
                    try:
                        show_items(items_for_slot(sg.to_bytes(), slot.index, names))
                    except Exception:
                        pass
                    print()
                else:
                    nz = sum(1 for b in slot.window if b)
                    extra = f"  ({nz} stale non-zero bytes)" if nz else ""
                    print(f"  slot {slot.index} ${slot.address:04X}  -empty-{extra}\n")
        elif name.startswith(b"\x01"):
            blob = img.read_file(entry)
            if len(blob) == RECORD_SIZE + 2:
                print(f"Exported character file {entry.display_name}\n")
                show_record(CharacterRecord.from_prg(blob), "file")
                print()

    cov = layout.coverage()
    print(f"Understood {cov.known} of {cov.total} record bytes "
          f"({cov.known / cov.total * 100:.0f}%); "
          f"{cov.by_confidence.get(Confidence.CONFIRMED, 0)} CONFIRMED. "
          f"Marks: ~ probable, ? guess.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
