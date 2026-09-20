"""Helpers `test_amiga` shares with the test files that reuse them."""
from __future__ import annotations

import functools
import pathlib
import tempfile

import pytest

from goldbox import (
    amiga_later,
    amiga_port,
    amiga_savegame,
)


def sample(**over):
    """One neutral character, built rather than read.

    Not a slice of any game file: every value here is chosen, which is what
    lets the edge cases below be tested where no disk is present.
    """
    from goldbox.neutral import NeutralCharacter

    values = {
        "name": "AELFRIC", "sex": 1, "race": 4, "age": 33, "alignment": 8,
        "strength": 18, "exceptional_strength": 0, "intelligence": 17,
        "wisdom": 16, "dexterity": 15, "constitution": 14, "charisma": 13,
        "hp_max": 55, "hp_rolled": 40, "hp_current": 55,
        "jewelry": 22, "gems": 11, "platinum": 200, "gold": 0, "electrum": 0,
        "silver": 0, "copper": 0,
        "movement": 12, "infravision": 0,
        "save_paralysis": 13, "save_petrification": 14, "save_wands": 12,
        "save_breath": 16, "save_spell": 15,
        "thief_pick_pockets": 60, "thief_open_locks": 45,
        "thief_find_traps": 40, "thief_move_silently": 50,
        "thief_hide_in_shadows": 43, "thief_hear_noise": 20,
        "thief_climb_walls": 92, "thief_read_languages": 20,
        "portrait_head": 3, "portrait_body": 4,
        "class_bits": 4, "char_class": 6,
        "levels": {"thief": 7, "fighter": 0, "cleric": 0, "magic-user": 0,
                   "knight": 0, "paladin": 0, "ranger": 0},
        "experience": 10000, "inventory": [],
        "level": 7, "npc": False, "spells_memorised": [], "spells_known": [],
    }
    values.update(over)
    char = NeutralCharacter("C64")
    for name, value in values.items():
        char.set(name, value, f"a built specimen's {name}")
    return char


@functools.lru_cache(maxsize=1)
def _extracted_records() -> tuple[pathlib.Path, ...]:
    """The twenty specimens, pulled out of the Amiga disks themselves.

    They are not loose files on any machine: six live in the `save/` drawer of
    Pool of Radiance disk 1 and fourteen in the Curse of the Azure Bonds save
    disk.  `tools/amiga/amigasaves.py` finds them from `gamedisks.yaml`'s
    `amiga` entry, and this unpacks them into a directory that lives as long
    as the test process.
    """
    from automap import gamedisks
    from tools.amiga import amigasaves
    if not gamedisks.candidates("amiga"):
        return ()
    tmp = tempfile.TemporaryDirectory(prefix="amiga-por-records-")
    _KEEP.append(tmp)                       # deleted when the process exits
    return tuple(amigasaves.extract(pathlib.Path(tmp.name)))


#: Temporary directories held open for the life of the test process, so that
#: `_extracted_records`'s paths stay readable after it returns.
_KEEP: list[tempfile.TemporaryDirectory] = []


def amiga_por_records() -> list[pathlib.Path]:
    """The 288-byte Pool of Radiance records, read out of the Amiga disk images
    (the `amiga` registry entry) and unpacked into a temporary directory."""
    found = list(_extracted_records())
    if not found:
        pytest.skip(
            "no Amiga Pool of Radiance records: set $AMIGA_DISKS at disks "
            "tools/amiga/amigasaves.py can read them out of")
    return found


# ---------------------------------------------------------------------------
# The item file, the effect file, and the neutral bridge (#27)
# ---------------------------------------------------------------------------
def amiga_por_with_items() -> list[pathlib.Path]:
    """The specimens that have a `.itm` beside them.

    Six of the twenty: the party shipped on Amiga disk 1.  The fourteen
    staged on the Curse save disk carry no item file, so a run whose disks
    hold only those skips rather than passing vacuously.
    """
    found = [p for p in amiga_por_records()
             if p.with_suffix(".itm").exists()]
    if not found:
        pytest.skip("no .itm beside any record under the Amiga disk images")
    return found


def synthetic_savegame(slot: str = "A") -> bytes:
    """A 13141-byte Amiga Pool of Radiance saved game, built not copied.

    Only the character table is filled in, because that is the only region
    `retarget_savegame` touches: six 41-byte entries at 12813 holding
    `CHRDAT<slot><n>` as eight plain bytes. `docs/124-amiga-port.md` §1.9a has
    the region map the rest of the file would follow.
    """
    save = bytearray(amiga_savegame.POR_SAVEGAME_SIZE)
    for n in range(amiga_savegame.POR_PARTY_MAX):
        at = amiga_savegame.POR_CHARACTER_TABLE + n * amiga_savegame.POR_CHARACTER_TABLE_STRIDE
        save[at:at + 8] = f"CHRDAT{slot.upper()}{n + 1}".encode("ascii")
    return bytes(save)


@functools.lru_cache(maxsize=1)
def _later_specimens() -> tuple[pathlib.Path, ...]:
    """The Curse and Silver Blades specimens, out of the disks themselves.

    None of them is a loose file on any machine: eleven are `SAVE/*.guy` on
    Amiga Curse disk 1 and the other ten are inside two saved games.
    `tools/amiga/amigarecords.py` reads them out through `gamedisks.yaml`'s `amiga`
    entry, into a directory that lives as long as the test process -- so the
    files are never only in a gitignored scratch directory, which has been lost.
    """
    from automap import gamedisks
    from tools.amiga import amigarecords
    if not gamedisks.candidates("amiga"):
        return ()
    tmp = tempfile.TemporaryDirectory(prefix="amiga-later-saves-")
    _KEEP.append(tmp)
    return tuple(amigarecords.extract(pathlib.Path(tmp.name)))


def _later_files():
    found = _later_specimens()
    if not found:
        pytest.skip("no Amiga Curse or Silver Blades disks; set $AMIGA_DISKS")
    return found


def curse_characters():
    """The fifteen Amiga Curse specimens: eleven pregens and four played."""
    out = []
    for path in _later_files():
        if path.suffix == ".guy":
            out.append(amiga_later.read_amiga_guy(path))
        elif path.name.startswith("CurseA-savgam"):
            out.extend(amiga_later.party_in_savegame(path.read_bytes(),
                                               amiga_port.CURSE_DELTAS))
    if not out:
        pytest.skip("no Amiga Curse records among the specimens")
    return out


def silver_blades_characters():
    """The six Amiga Silver Blades specimens, all inside one saved game."""
    out = []
    for path in _later_files():
        if path.name.startswith("Secret1-savgam"):
            out.extend(amiga_later.party_in_savegame(path.read_bytes(),
                                               amiga_port.SILVER_BLADES_DELTAS))
    if not out:
        pytest.skip("no Amiga Silver Blades records among the specimens")
    return out


# --- the ability pairs: a (base, current) pair here too, as on DOS ---------
def _ability_record(shape, name: str, first: int, second: int):
    """A record of `shape` holding one ability pair and nothing else.

    Built from `goldbox/dos_port.py`'s own table through the shape's shift
    map, the way `_later_record` builds a class mask above, so it belongs to
    this project and runs with no disks.
    """
    raw = bytearray(shape.record_size)
    raw[:6] = b"TESTER"
    at = shape.offset(shape.dos_field(name).offset)
    raw[at] = first
    raw[at + 1] = second
    return amiga_later.AmigaCharacter.from_bytes(bytes(raw), shape)
