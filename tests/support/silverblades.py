"""Helpers `test_silverblades` shares with the test files that reuse them."""
from __future__ import annotations

import functools
import pathlib

import gamedata
import pytest

from goldbox import c64_port
from goldbox.d64 import D64
from goldbox.savegame import load_save

SSB = c64_port.SECRET_OF_THE_SILVER_BLADES


SSB_ENV = "SSB_DISKS"
SSB_KEY = "secret-of-the-silver-blades"


def _candidates():
    """`gamedisks.yaml`'s own search list for this title (#212).

    No candidate here may sit under a scratch directory: it has been deleted
    twice, so a default that resolved into it stopped resolving the day it was.
    """
    from automap import gamedisks
    return gamedisks.candidates(SSB_KEY)


@functools.lru_cache(maxsize=1)
def ssb_dir():
    """Where the player keeps their Silver Blades disks, or None."""
    for path in _candidates():
        try:
            if path.is_dir() and any(path.glob("SILVER*.[dD]64")):
                return path
        except OSError:
            continue
    gamedata.require_registered(SSB_KEY)
    return None


def ssb_disks():
    """Every readable Silver Blades side, skipping when there are none."""
    where = ssb_dir()
    if where is None:
        pytest.skip(f"needs the Silver Blades disks; set {SSB_ENV}")
    out = []
    for path in sorted(where.glob("SILVER*.[dD]64")):
        try:
            out.append(D64.open(str(path)))
        except Exception:
            continue                      # an error-byte rip is skipped, not failed
    if not out:
        pytest.skip("no readable Silver Blades disk here")
    return out


def _save_disk() -> pathlib.Path:
    """The side carrying a whole `SAVEDBASH`, or skip."""
    where = ssb_dir()
    if where is None:
        pytest.skip(f"needs the Silver Blades disks; set {SSB_ENV}")
    for path in sorted(where.glob("SILVER*.[dD]64")):
        try:
            prg = D64.open(str(path)).read_file(SSB.save_file)
        except Exception:
            continue
        if SSB.matches_payload(prg):
            return path
    pytest.skip("no Silver Blades side here carries a whole SAVEDBASH")


def _party():
    """The shipped pre-generated party, as a `SaveGame0`."""
    game, sg0, sg1 = load_save(D64.open(str(_save_disk())))
    assert game is SSB
    return sg0, sg1
