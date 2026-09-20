"""Helpers `test_dossave` shares with the test files that reuse them."""
from __future__ import annotations

import functools

import pytest
from gamedata import (
    specimen_files,
)

#: The 285-byte Pool of Radiance record. Offsets confirmed in
#: `reports/dos-saves.md` (scratch, deleted) section 3.
RECORD_SIZE = 285


def _candidates():
    """`gamedisks.yaml`'s own search list for the DOS archives (#212)."""
    from automap import gamedisks
    return gamedisks.candidates("dos-archives")


@functools.lru_cache(maxsize=1)
def _save_dir():
    """The directory holding a played DOS Pool of Radiance party, or None.

    Steam redirects the game's save directory into `SavesDir`, so the party is
    not under the game folder. Recognise it by the files rather than the path,
    and by the record size rather than by the file names: every title in the
    family writes `CHRDAT??.SAV` beside a `SAVGAM?.DAT`, and only Pool of
    Radiance writes 285 bytes. Count the `.CHA` files beside the `.SAV` ones,
    since a played party is both. Rank a folder with the game's own files above
    it ahead of the save count, so the installed copy beats a shipped
    `Default files/Saves` and a Steam `SavesDir` folder that has no game beside
    it, and walk in sorted order so a tie is the same folder on every machine.
    """
    best = None
    for root in _candidates():
        try:
            if not root.is_dir():
                continue
            folders = sorted({p.parent for p in root.rglob("SAVGAM[ABJ].DAT")})
            for folder in folders:
                records = [p for p in (*folder.glob("CHRDAT*.SAV"),
                                       *folder.glob("*.CHA"))
                           if p.stat().st_size == RECORD_SIZE]
                if not records:
                    continue
                game = any((folder.parent / name).is_file()
                           for name in ("START.EXE", "ECL1.DAX"))
                rank = (game, len(records))
                if best is None or rank > best[0]:
                    best = (rank, folder)
        except OSError:
            continue
    return best[1] if best else None


@functools.lru_cache(maxsize=1)
def _game_dirs():
    """`Default files/Saves` for every DOS Gold Box title present, by title."""
    out = {}
    for root in _candidates():
        if not root.is_dir():
            continue
        for path in root.glob("*/games/*/Default files/Saves"):
            if path.is_dir():
                out.setdefault(path.parent.parent.name, path)
    return out


def _records():
    """Every 285-byte Pool of Radiance record, saved and exported, by name."""
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES to the archives")
    out = {}
    for path in sorted(where.glob("*.SAV")) + sorted(where.glob("*.CHA")):
        data = path.read_bytes()
        if len(data) == RECORD_SIZE:
            out[path.name] = data
    if not out:
        pytest.skip("no DOS Pool of Radiance character records here")
    return out


needs_dos_saves = pytest.mark.skipif(
    _save_dir() is None, reason="needs a DOS save; set FR_ARCHIVES")


#: The `#249` party, in three states: as the game wrote it to slot C at the
#: roster, as it wrote it to slot E after the New Phlan tour, and as the six
#: loose `.CHA` records that existed for one moment between CREATE NEW
#: CHARACTER and ADD CHARACTER TO PARTY. Six characters, eighteen records,
#: covering human fighter, human cleric, elf magic-user, halfling thief, dwarf
#: fighter/thief and half-elf cleric/fighter/magic-user.
CLEAN_PARTY = ("por-party-l1", "por-party-l1-intown", "por-party-l1-rolled")

#: `#84`'s eight rolls, one per race: three gnomes, a dwarf, a halfling, an
#: elf, a human and a half-elf. Exports, so no items and no `.ITM`.
CLEAN_ROLLS = ("gnomf1", "gnomt2", "gnomft3", "dwarfc4", "halfl5", "elf6",
               "human7", "halfe8")

#: The two states of the training run. Their experience, gold and encumbrance
#: went in as *ours* -- `tools/dos/dostrainprobe.py`'s `install` writes all three --
#: so nothing money-shaped in them is the game's arithmetic. Everything the
#: trainer itself wrote is: level, the per-class levels, hit points, the spell
#: slots, and the experience it left behind.
CLEAN_TRAINED = ("por-party-trained-c2", "por-train-clamp")


def _clean_records(*groups):
    """Every 285-byte record in the named specimen groups, keyed
    `<specimen>/<filename>`.

    Defaults to the corpus a layout claim may rest on: the `#249` party in its
    three states plus `#84`'s eight rolls -- 26 records over 14 distinct
    characters.
    """
    names = []
    for group in (groups or (CLEAN_PARTY, CLEAN_ROLLS)):
        names += list(group) if isinstance(group, tuple) else [group]
    return specimen_files(names, (".SAV", ".CHA"), size=RECORD_SIZE)
