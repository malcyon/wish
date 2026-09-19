"""What a live test needs from this machine, and what it does when it is not there.

The emulators, the game disks and the specimens are installed on the machine
that runs these tests, so one that is missing is a broken environment and the
test fails with the path.  Only a device that is switched off skips.
"""

import pytest

from automap import gamedisks
from tools.dos import dosbox


def fail_if_missing_tools(absent):
    """Fail, naming each executable `absent` lists."""
    if absent:
        names = ", ".join("import (from ImageMagick)" if t == "import" else t for t in absent)
        pytest.fail(f"the DOS emulator harness needs these on PATH; not installed: {names}")


def find_game_or_fail(stem="POOLRAD"):
    """The game directory, or a failure naming the registry or the folder that is missing."""
    try:
        return dosbox.find_game(stem)
    except gamedisks.RegistryMissing as e:
        pytest.fail(f"{e}; expected at {gamedisks.REGISTRY}")
    except gamedisks.RegistryError as e:
        pytest.fail(f"{gamedisks.REGISTRY} cannot be read: {e}")
    except FileNotFoundError as e:
        pytest.fail(str(e))


def fail_if_save_missing(game, letter):
    """Fail, naming the path, unless slot `letter` exists in `game`'s SAVE folder."""
    slot = game / "SAVE" / f"SAVGAM{letter}.DAT"
    if not slot.is_file():
        pytest.fail(f"the save specimen {slot} is missing")
