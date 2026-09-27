"""Copy an Amiga Pool of Radiance save slot between disks without re-encoding it."""

from __future__ import annotations

import re

from goldbox import amiga_savegame
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError


def import_slot(dest: AmigaDisk, dest_letter: str, source: AmigaDisk,
                source_letter: str) -> bytes:
    """Replace one Pool slot with the source's original Save As files."""
    from tools.amiga.route_pool import _pool_slot_files

    source_drawer = amiga_savegame.por_save_drawer(source)
    dest_drawer = amiga_savegame.por_save_drawer(dest)
    source_name = amiga_savegame.por_savegame_filename(source_letter)
    source_path = amiga_savegame.por_save_path(source_name, source_drawer)
    savegame = source.read_file(source_path)
    slot_files = _pool_slot_files(source, source_letter) if not source_drawer else {
        entry.name: source.read_file(amiga_savegame.por_save_path(entry.name, source_drawer))
        for entry in source.entries(source.lookup(f"/{source_drawer}").block)
        if not entry.is_dir and re.fullmatch(
            rf"CHRDAT{re.escape(source_letter)}[1-6]\.(sav|itm|spc)",
            entry.name, re.IGNORECASE)}
    character_files = {
        name: data for name, data in slot_files.items()
        if re.fullmatch(rf"CHRDAT{re.escape(source_letter)}[1-6]\.(sav|itm|spc)",
                        name, re.IGNORECASE)}
    target_game = amiga_savegame.retarget_savegame(savegame, dest_letter)
    snapshot = dest.to_bytes()
    try:
        for name in _pool_slot_files(dest, dest_letter):
            dest.remove_file(amiga_savegame.por_save_path(name, dest_drawer))
        for name, data in character_files.items():
            target_name = name[:6] + dest_letter + name[7:]
            dest.write_file(amiga_savegame.por_save_path(target_name, dest_drawer), data)
        dest.write_file(amiga_savegame.por_save_path(
            amiga_savegame.por_savegame_filename(dest_letter), dest_drawer), target_game)
        dest.write_file(amiga_savegame.por_save_path(
            amiga_savegame.POR_SLOT_LIST_NAME, dest_drawer),
            amiga_savegame.slot_list_bytes(
                amiga_savegame.read_slot_list(dest, dest_drawer) + [dest_letter]))
        if dest_letter not in amiga_savegame.read_slot_list(dest, dest_drawer):
            raise AmigaDiskError(f"slot {dest_letter} is absent from the slot list")
        amiga_savegame.read_por_slot(dest, dest_letter, drawer=dest_drawer)
        amiga_savegame.read_por_characters(dest, dest_letter, drawer=dest_drawer)
    except BaseException:
        dest.restore(snapshot)
        raise
    return target_game
