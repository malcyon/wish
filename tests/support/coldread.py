"""Helpers `test_coldread` shares with the test files that reuse them."""
from __future__ import annotations

import pytest

from goldbox import c64_port  # noqa: E402
from support.silverblades import ssb_dir  # noqa: E402
from tests import gamedata  # noqa: E402

POOL = c64_port.POOL_OF_RADIANCE
CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS


def _root(game):
    """The directory holding a title's disks, or skip.

    Each title is found the way the rest of the suite finds it, so a machine
    with one game and not another runs exactly the tests it can.
    """
    if game is POOL:
        where = gamedata.disk_dir()
        env = "POR_DISKS"
    elif game is CURSE:
        where = gamedata.curse_dir()
        env = gamedata.CURSE_ENV
    else:
        where = ssb_dir()
        env = "SSB_DISKS"
    if where is None:
        pytest.skip(f"needs the {game.title} disks; set {env}")
    return str(where)
