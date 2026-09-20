"""Helpers `test_latercombat` shares with the test files that reuse them."""

from conftest import load_tools_module
from gamedata import COMBAT_MAP, synthetic_arena

from automap import combat
from goldbox import c64_port

latercombat = load_tools_module("latercombat")


CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS


def later_arena(fighters=((0, 25, 13), (8, 30, 13))) -> dict[int, bytes]:
    """`synthetic_arena`, laid out the way a running Curse holds a fight.

    Six blocks move and two do not. The parameter block stays at `$0600` and
    the camera at `$037E` -- which is a reading rather than an assumption:
    `GDRIVE00` names the same twenty addresses in all three binaries -- and the
    block's *contents* are rewritten, because in the later titles `COM.PREP`
    writes them as immediate constants naming `$6F00` and `$CB00`.

    The position table is the one that is not simply relocated.
    `synthetic_arena` returns it stuck on the end of the roster block, because
    in Pool of Radiance `$8B00` is the byte after the sixty-fourth roster
    entry. In Curse the roster is at `$6700` and the map at `$6F00` -- so the
    positions are somewhere else entirely, at `$CB00` -- and splitting them
    here is what stops this fixture quietly assuming they are adjacent.
    """
    old = synthetic_arena(fighters)
    roster_and_positions = old[combat.ROSTER]
    span = 64 * combat.ROSTER_STRIDE
    roster, positions = (roster_and_positions[:span],
                         roster_and_positions[span:])
    where = latercombat.BY_KEY[CURSE.key]
    params = bytearray(old[latercombat.PARAMS])
    params[0x02], params[0x03] = 0x00, 0x6F           # the combat map
    params[0x04], params[0x05] = 0x00, 0xCB           # the position table
    # The save head has to be a whole `$1000` block: `read_battle` refuses a
    # short one, and the records sit `$400` into it.
    head = bytearray(where.save_head_length)
    records = old[combat.RECORDS]
    at = where.records - where.save_head
    head[at:at + len(records)] = records
    return {
        where.mode: bytes([combat.COMBAT]),
        latercombat.PARAMS: bytes(params),
        latercombat.CAMERA: old[combat.CAMERA],
        0x6F00: old[COMBAT_MAP],
        where.roster: roster,
        0xCB00: positions,
        where.initiative: old[combat.INITIATIVE],
        where.save_head: bytes(head),
    }
