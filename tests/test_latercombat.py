"""Reading a Curse or Silver Blades fight, at those titles' own addresses.

`#334 (The session driver cannot fight in Curse or Silver Blades, and says the
party is not in a fight while it is standing on the combat floor)`. The symptom
is a silent false negative, which is the expensive kind: a driver that asks
"am I fighting" and is told no looks exactly like a save that failed to enter
combat, and that is how a working conversion gets written up as broken.

So the two tests that matter are a pair. One builds a machine laid out the way
a running Curse is and asserts the new reader finds the fight; the other hands
the same machine to the reader as it was and asserts it finds nothing, which is
the bug as it stood. Neither needs an emulator or a display.

**The bytes are Pool of Radiance's own**, out of `tests/gamedata.py`'s
`synthetic_arena`, moved to the addresses Curse holds them at. That is
deliberate and is not a shortcut: what is being tested is which addresses get
read, and using the same content for both titles is what makes the addresses
the only difference between the two cases.
"""

import pytest
from conftest import load_tools_module
from gamedata import COMBAT_MAP, synthetic_arena

from automap import combat
from automap.target import MemoryTarget
from goldbox import games

session = load_tools_module("session")
latercombat = load_tools_module("latercombat")

Session = session.Session

CURSE = games.CURSE_OF_THE_AZURE_BONDS
SILVER = games.SECRET_OF_THE_SILVER_BLADES
POOL = games.POOL_OF_RADIANCE

#: Where the two fighters `synthetic_arena` puts on the floor stand.
PARTY_AT = (25, 13)
MONSTER_AT = (30, 13)


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


# -- what a fight is read as ------------------------------------------------

@pytest.mark.parametrize("game", [CURSE, SILVER])
def test_a_later_titles_fight_is_read_at_its_own_addresses(game):
    """The party and the monster come back off `$CB00`, `$6700` and `$92E8`."""
    target = MemoryTarget(later_arena())
    battle = latercombat.read_battle(target, game)
    assert battle is not None, "no fight was read at all"
    assert battle.shape.positions == 0xCB00
    assert battle.shape.map_base == 0x6F00
    assert [(c.index, c.x, c.y) for c in battle.party] == [(0, *PARTY_AT)]
    assert [(c.index, c.x, c.y) for c in battle.enemies] == [(8, *MONSTER_AT)]


def test_the_reader_as_it_stood_finds_no_fight_on_a_curse_machine():
    """The bug, kept as a test: Pool of Radiance's addresses answer None.

    `automap.combat.read_battle` reads `$6E11` for the mode, and in a running
    Curse that byte belongs to something else -- so a party standing on the
    combat floor is reported as not fighting, `porcmd battle` says `not in a
    fight`, and `Session.fight` returns `not fighting` with zero turns
    (`#334`). This is what `tools/session.py` used to call.
    """
    assert combat.read_battle(MemoryTarget(later_arena())) is None


def test_pool_of_radiance_is_still_read_exactly_where_it_always_was():
    """The new reader must be the old one for the title it already worked on."""
    memory = synthetic_arena()
    was = combat.read_battle(MemoryTarget(memory))
    now = latercombat.read_battle(MemoryTarget(memory), POOL)
    assert was is not None
    assert now is not None
    assert [(c.index, c.x, c.y, c.hp) for c in now.combatants] == \
           [(c.index, c.x, c.y, c.hp) for c in was.combatants]
    assert (now.shape, now.camera, now.terrain) == \
           (was.shape, was.camera, was.terrain)


def test_a_title_nobody_has_run_under_a_monitor_is_refused():
    """Champions of Krynn has no measured addresses, so it gets no battle.

    **Not a fall back to Pool of Radiance's.** An unmeasured address reads as a
    plausible fight rather than as an error, which is the whole failure this
    ticket is about with the titles swapped round.
    """
    assert latercombat.memory_for(games.CHAMPIONS_OF_KRYNN) is None
    target = MemoryTarget(synthetic_arena())
    assert latercombat.read_battle(target, games.CHAMPIONS_OF_KRYNN) is None
    assert target.reads == [], "it read the machine before refusing"


def test_the_ranges_read_are_this_titles_and_not_the_other_ones():
    """A read of `$8300` or `$A380` on a Curse machine is the old bug back."""
    target = MemoryTarget(later_arena())
    latercombat.read_battle(target, CURSE)
    asked = {addr for addr, _length in target.reads}
    assert 0x7F11 in asked and 0x6E11 not in asked
    assert 0x6700 in asked and combat.ROSTER not in asked
    assert 0x92E8 in asked and combat.INITIATIVE not in asked
    assert 0xCB00 in asked and 0x8B00 not in asked
    # And the two that are the same address in every title.
    assert latercombat.PARAMS in asked and latercombat.CAMERA in asked


def test_the_two_later_titles_are_written_out_separately():
    """Curse and Silver Blades agree today, and must be able to disagree.

    They were derived from each title's own binary independently and came out
    the same. Sharing one row would make a future disagreement invisible.
    """
    assert latercombat.BY_KEY[CURSE.key] == latercombat.BY_KEY[SILVER.key]
    assert latercombat.BY_KEY[CURSE.key] is not latercombat.BY_KEY[SILVER.key]


# -- the driver's own mode byte ---------------------------------------------

class FakeMonitor:
    """Records what was read, and answers `$00` for anything else."""

    def __init__(self, memory, log):
        self.memory, self.log = memory, log

    def read(self, addr, length):
        self.log.append((addr, length))
        return bytes(self.memory.get(addr + i, 0) for i in range(length))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ModeSession(Session):
    """A `Session` with a monitor and nothing else. No VICE, no X, no disk."""

    def __init__(self, game, memory):
        self.game = game
        self.memory = memory
        self.reads: list[tuple[int, int]] = []

    def mon(self, timeout=5.0):
        return FakeMonitor(self.memory, self.reads)


@pytest.mark.parametrize("game,flag", [(POOL, 0x6E11), (CURSE, 0x7F11),
                                       (SILVER, 0x7F11)])
def test_the_driver_asks_this_titles_own_mode_flag(game, flag):
    """`in_combat` on a combat floor, whichever title is being driven.

    Before `#334` this read `$6E11` on all three, so a Curse party in a fight
    answered whatever that byte happened to hold -- `1`, in the run at
    `work/issue131-m2/curse-brawl`, with `MOVE VIEW AIM TURN QUICK DONE` on
    row 24 and six figures on the floor.
    """
    sess = ModeSession(game, {flag: 2})
    assert sess.mode() == 2
    assert sess.in_combat() is True
    # Two calls, two reads, and both of them of this title's byte and nothing
    # else -- a read of any other address is the bug back.
    assert sess.reads == [(flag, 1), (flag, 1)]


def test_a_title_with_no_measured_mode_flag_is_not_asked_at_all():
    """None, and no read: an unmeasured address answers `not combat` forever.

    That is a gate that is open rather than a gate that is missing, so the
    driver says it does not know instead of asking a byte it cannot read.
    """
    sess = ModeSession(games.CHAMPIONS_OF_KRYNN, {0x6E11: 2, 0x7F11: 2})
    assert sess.mode() is None
    assert sess.in_combat() is False
    assert sess.reads == []
