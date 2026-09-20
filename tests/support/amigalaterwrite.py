"""Helpers `test_amigalaterwrite` shares with the test files that reuse them."""
from __future__ import annotations

import pathlib

import pytest
from gamedata import specimen_root

from goldbox import amiga_later, amiga_port

#: Saved games in the specimen tree **this project wrote**, not the engine.
#: Each is named in its own `provenance.toml`, and each is excluded from any
#: claim about what the game holds -- the same exclusion
#: `tools/dos/dostailcensus.py` makes by name, for the same reason: our bytes read
#: back as the engine's is how a measurement quietly becomes circular.
OURS = {
    # `--strip-items 2`: IILANDA's item chain emptied, and her stored
    # encumbrance left at what it was with three items in it.
    "WISH-SPEC-coab-amiga-resave/savgamD.dat",
    # `--keep 4 --rename 0=TALWYN`
    "WISH-SPEC-ssb-amiga-resave/savgamB.sav",
    # `--square 5,9,6`
    "WISH-SPEC-ssb-amiga-moved/savgamC.sav",
}

#: Which shape each specimen drawer's saved games are.
_DRAWERS = (("coab-amiga", amiga_port.CURSE_DELTAS, ".dat"),
            ("ssb-amiga", amiga_port.SILVER_BLADES_DELTAS, ".sav"))


def _verified(where: pathlib.Path) -> None:
    """Fail if a specimen no longer hashes to what its manifest recorded."""
    from tools.registry import specimens

    prov = where / "provenance.toml"
    if not prov.is_file():
        pytest.fail(f"{where}: no provenance.toml -- not a specimen")
    for filename, expected in specimens.read_provenance(prov).get(
            "sha256", {}).items():
        path = where / filename
        if not path.is_file():
            pytest.fail(f"{where.name}: {filename} is missing; "
                        f"run tools/registry/specimens.py check")
        actual = specimens.sha256_file(path)
        if actual != expected:
            pytest.fail(f"{where.name}: {filename} has changed -- recorded "
                        f"{expected[:12]}, now {actual[:12]}; it is no longer "
                        f"evidence. Run tools/registry/specimens.py check")


def engine_written_parties():
    """`(label, character)` for every Amiga later character the engine wrote.

    Empty rather than skipping, so a caller can add it to the disk corpus on
    a machine that has one and not the other.
    """
    root = specimen_root()
    if root is None:
        return []
    out = []
    for drawer, shape, suffix in _DRAWERS:
        for where in sorted((root / drawer).glob("WISH-SPEC-*")):
            if not where.is_dir():
                continue
            _verified(where)
            for path in sorted(where.glob(f"savgam*{suffix}")):
                if f"{where.name}/{path.name}" in OURS:
                    continue
                for char in amiga_later.party_in_savegame(path.read_bytes(), shape):
                    out.append((f"{where.name}/{path.name}", char))
    return out
