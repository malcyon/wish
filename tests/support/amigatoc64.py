"""Helpers `test_amigatoc64` shares with the test files that reuse them."""
from __future__ import annotations

import pytest

from goldbox import (
    amiga_por,
)
from goldbox.amiga_adf import AmigaDisk


def _pool_of_radiance_disk_1() -> AmigaDisk:
    """The player's Amiga Pool of Radiance disk 1, with slot A in its drawer.

    **Matched on the record's own size, not on the file names.** Amiga Curse
    of the Azure Bonds keeps its saves under the same `save/savgamA.dat` and
    `save/CHRDATA1.sav` names, and a search that stops at the first disk
    carrying those picks up the Curse save disk on this machine and then
    fails several calls down with a 428-byte record. 288 bytes is Pool of
    Radiance's own (`goldbox.amiga_shared.deltas_for`).
    """
    from automap import gamedisks
    from tools.amiga import amigasaves

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    for _name, data in amigasaves.images():
        # The whole open inside the guard: most of what this walks is not a
        # Gold Box disk at all, and a bootable image with no AmigaDOS root
        # block raises here rather than at the lookup.
        try:
            disk = AmigaDisk(bytearray(data))
            record = disk.read_file("/save/CHRDATA1.sav")
            disk.lookup("/save/savgamA.dat")
        except Exception:
            continue
        if len(record) == amiga_por.AMIGA_POR_RECORD_SIZE:
            return disk
    pytest.skip("no Amiga Pool of Radiance disk 1 here")
