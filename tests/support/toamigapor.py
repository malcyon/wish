"""Helpers `test_toamigapor` shares with the test files that reuse them."""
from __future__ import annotations

import pathlib

import gamedata
import pytest


def _por_disk_2(tmp_path: pathlib.Path) -> pathlib.Path:
    """A Pool of Radiance disk 2 image, or a skip.

    Needed since `#316 (Write the Amiga Pool of Radiance saved game from the
    source save, so a converted party arrives where it was standing)`: the
    saved game is built rather than copied, and the one part of it no
    character record holds is the area's own 7680-byte ECL script, which the
    Amiga keeps in a single `ecl.dax` on the `POOLDATA` volume.  Identified by
    carrying that file rather than by its name, which differs between rips.
    """
    from automap import gamedisks
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import amigasaves

    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    for _name, data in amigasaves.images():
        try:
            AmigaDisk(bytearray(data)).read_file("/ecl.dax")
        except Exception:
            continue
        where = tmp_path / "por2.adf"
        where.write_bytes(bytes(data))
        return where
    pytest.skip("no Amiga Pool of Radiance disk 2; set $AMIGA_DISKS")


def _c64_specimen(name: str) -> pathlib.Path:
    """A C64 specimen disk, which is one file rather than a directory."""
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/registry/specimens.py")
    found = sorted((root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    return found[0]
