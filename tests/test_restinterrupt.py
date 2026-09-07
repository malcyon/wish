"""The C64 rest-interruption gate, checked against the player's own disks.

`docs/207-c64-rest-interruption.md` rests on three claims about bytes that are
not in this repository and never will be: the gate in `CAMP`, the ENCAMP
prologue in `DUNGEON`, and what each area script's entry 2 leaves in `$6DD2`.
All three are read off the disks at run time, so these fail if a disk is
replaced with another build rather than passing on a description of one.

Everything here skips cleanly with no disks -- see `tests/gamedata.py`.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tests.gamedata import disk_dir, game_file, needs_disks  # noqa: E402
from tools import c64restinterrupt as R  # noqa: E402


def _root() -> str:
    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    return str(where)


# -- the gate ---------------------------------------------------------------


@needs_disks
def test_the_rest_loop_skips_the_whole_check_when_the_interval_is_zero():
    """`CAMP $1E0F` is `LDA $6DD2 / BEQ`, so zero means no check is ever made.

    The five bytes are the whole of `#250 (Does a C64 party resting in the
    Slums ever get interrupted without the murder flag?)`'s answer, so they are
    asserted rather than described.
    """
    camp = game_file("CAMP")   # `load_payload` has already dropped the header
    at = R.TICK - 0x0800
    assert camp[at:at + 5] == R.TICK_BYTES


@needs_disks
def test_encamp_zeroes_the_pair_before_it_runs_the_area_script():
    """`DUNGEON $10A1`: zero both, then `JSR $19F5`, which is entry 2.

    The order is what makes the script the only thing that can open the gate.
    Reversed, the engine would wipe whatever the script had just written.
    """
    dungeon = game_file("DUNGEON")
    at = R.ENCAMP_HANDLER - 0x0800
    assert dungeon[at:at + len(R.ENCAMP_BYTES)] == R.ENCAMP_BYTES


@needs_disks
def test_no_overlay_ever_stores_a_non_zero_interval():
    """Every absolute write to `$6DD2` in the whole game stores zero.

    If one did not, a script's word would not be final and the census below
    would mean nothing. Swept over every distinct file of the eight sides.
    """
    from goldbox import games
    from tools import absrefsweep

    game = next(g for g in games.GAMES if g.key == "pool-of-radiance")
    _, hits = absrefsweep.sweep(_root(), game, R.INTERVAL, R.INTERVAL)
    code = [h for h in hits if not absrefsweep.is_art(h.file)]
    assert code, "no file names $6DD2 at all, so the sweep found nothing"
    stores = [h for h in code if h.op.startswith(("STA", "STX", "STY"))]
    assert len(stores) == 3, (
        "expected the three zeroing stores in DUNGEON, INIT and POST.COM, "
        f"got {[(h.file, hex(h.at)) for h in stores]}")
    for hit in stores:
        # All three sit at the end of a run of `STA abs`, and what loaded the
        # accumulator in front of that run is `LDA #$00` -- in `POST.COM` five
        # stores earlier, which is why the run is walked rather than the two
        # bytes in front of the store being read.
        body = R.overlay_bytes(hit.file, _root())[1]
        i = hit.at - 0x0800
        while i >= 3 and body[i - 3] == 0x8D:
            i -= 3
        assert body[i - 2:i] == b"\xa9\x00", (
            f"{hit.file} ${hit.at:04X} is not part of a run of stores fed by "
            f"LDA #$00: {body[i - 2:i].hex(' ')} at ${0x0800 + i - 2:04X}")


# -- what the scripts leave there -------------------------------------------


@needs_disks
def test_the_slums_open_the_gate_only_for_the_murder_flag():
    """`ECL14` entry 2 reaches `$6DD2` = 24 only through the `$4A0B` test.

    The two tests below that one jump to `$9A2F` and fall through to `$9A2F`,
    so neither decides anything; this asserts the outcome of that rather than
    the shape, because the shape is what could be misread.
    """
    values, lines = R._intervals("ECL14", _root())
    assert values == {0, 24}
    assert lines[0]["at"] == 0x9A0E
    assert "$4A0B" in lines[0]["text"] and "255" in lines[0]["text"]


@needs_disks
def test_both_arms_below_the_murder_test_reach_the_same_statement():
    """The Slums' second and third tests are conditionals with one outcome.

    `$9A19` and `$9A24` each jump to `$9A2F`, and `$9A2F` is also what follows
    them, so the branch is inert whichever way the `IF` reads. That is the
    defect `goldbox-bugs.md` 13 describes, and it is asserted here from the
    script's own targets rather than from a listing somebody read once.
    """
    script, _ = R._script("ECL14", _root())
    reached = {st.address: st for st in R.entry2_statements(script)}
    gotos = [st for a, st in reached.items()
             if 0x9A19 <= a < 0x9A2F and st.name == "GOTO"]
    assert len(gotos) == 2, [hex(g.address) for g in gotos]
    assert all(g.target() == 0x9A2F for g in gotos)
    # And every path *out* of the second test writes zero, jump or no jump.
    seen, work, wrote = set(), [0x9A19 - 0x9900], set()
    while work:
        i = work.pop()
        if i in seen or i not in script.statements:
            continue
        seen.add(i)
        st = script.statements[i]
        if st.name == "SAVE" and st.operands[-1][1] == R.INTERVAL:
            wrote.add(st.operands[0][1])
        for successor, _unused in script._successors(st):
            work.append(successor)
    assert wrote == {0}, f"a path below $9A19 reaches $6DD2 = {wrote}"


@needs_disks
@pytest.mark.parametrize("name", ["ECL07", "ECL0F", "ECL10", "ECL13",
                                  "ECL17", "ECL1E"])
def test_six_areas_can_never_interrupt_a_rest(name):
    """Entry 2 leaves `$6DD2` at zero on every path it can reach."""
    values, _ = R._intervals(name, _root())
    assert values == {0}


@needs_disks
@pytest.mark.parametrize("name,expected", [("ECL0D", {1, 96}),
                                           ("ECL18", {1, 4})])
def test_two_areas_always_interrupt_a_rest(name, expected):
    """Entry 2 leaves `$6DD2` non-zero on every path it can reach."""
    values, _ = R._intervals(name, _root())
    assert values == expected
    assert 0 not in values


@needs_disks
def test_the_four_measured_pairs_are_the_scripts_own_words():
    """The pairs `#218` measured over 21 DOS containers, back out of the C64.

    New Phlan (1, 101), the Slums (24, 24), Sokol Keep (2, 1), the overland
    (96, 10) -- `docs/163-dos-vm-address-map.md`. Only the interval is
    asserted, since that is what the gate reads.
    """
    for name, interval in (("ECL00", 1), ("ECL14", 24),
                           ("ECL15", 2), ("ECL1A", 96)):
        values, _ = R._intervals(name, _root())
        assert interval in values, f"{name} never leaves $6DD2 at {interval}"


@needs_disks
def test_only_the_slums_has_a_camping_test_that_decides_nothing():
    """Two of two in `ECL14`, and none in the other twenty-nine scripts.

    This is what says the block is a mistake rather than a design: a
    conditional whose two arms arrive at the same single statement is not
    something these scripts otherwise contain. `ECL1C $B628` is the near miss
    and is a real branch -- both arms reach the same three statements, and
    tests below it pick a different one on each arm -- so it is asserted here
    as *not* deciding nothing, to keep the test honest about the distinction.
    """
    from tools import eclwalk

    eclwalk.DISKS = pathlib.Path(_root())
    dead, near = [], []
    for name in sorted(eclwalk.scripts()):
        for found in R.inert_tests(name, _root()):
            (dead if found["decides_nothing"] else near).append(
                (name, found["at"]))
    assert dead == [("ECL14", 0x9A1F), ("ECL14", 0x9A2A)]
    assert near == [("ECL1C", 0xB628)]


# -- the pieces that need no disks ------------------------------------------


def test_the_clock_counts_minutes_across_an_hour_and_a_day():
    """`$49C6`-`$49CB` is sub-minute, minute units, minute tens, hour, day,
    month, and the tool turns it into one running count so a rest's length can
    be checked against the game's own clock rather than only the checkpoint.
    """
    assert R.clock_minutes(bytes((0, 8, 1, 1, 3, 0))) == 18 + 60 + 3 * 1440
    two_hours = (R.clock_minutes(bytes((0, 8, 1, 3, 3, 0)))
                 - R.clock_minutes(bytes((0, 8, 1, 1, 3, 0))))
    assert two_hours == 120
    midnight = (R.clock_minutes(bytes((0, 0, 0, 0, 4, 0)))
                - R.clock_minutes(bytes((0, 5, 5, 23, 3, 0))))
    assert midnight == 5


def test_every_named_phase_stages_something_the_drive_can_use():
    """The three camp sessions, and the one that makes a check countable.

    `flag-set-no-win` holds the chance at zero so `$1E22` can never succeed,
    which is what lets 13 checks be counted instead of stopping at the first
    interruption. A phase table that lost that would quietly halve the run's
    evidence.
    """
    assert set(R.PHASES) == {"flag-clear", "flag-set-no-win", "flag-set"}
    assert R.PHASES["flag-clear"]["murder"] == 0
    assert R.PHASES["flag-set"]["chance"] is None
    assert R.PHASES["flag-set-no-win"]["chance"] == 0
