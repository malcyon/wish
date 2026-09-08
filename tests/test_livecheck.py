"""`tools/livecheck.py` -- the per-title validation runner for #34.

Three things about that tool can be wrong without any emulator noticing, and
each of them cost something real:

* **Where it puts the run's own notes.** The first version redirected
  `$XDG_DATA_HOME` to keep a validation run's explored squares out of the
  player's map notes. A Flatpak *user* installation lives under
  `$XDG_DATA_HOME/flatpak`, so `porlaunch.sh`'s `flatpak run net.sf.VICE`
  stopped finding the installed emulator, fell back to the system
  installation, defaulted to the `master` branch and wrote
  `app/net.sf.VICE/x86_64/master not installed` into the slot's `vice.log`.
  Three boots died that way on 2026-09-08 before anybody read that file.
* **Which memory it reads the screen out of.** The whole of `#421` is that
  `$D011`, `$D018` and `$DD00` have to come from the chips rather than from
  whatever the processor can see. A validation run taken through the
  processor's view would be validating the bug that was just removed.
* **Whether the live cards are compared against anything.** The cross-check
  against the same save read cold off the disk is what makes a matching name
  evidence rather than the reader agreeing with itself.

`FakeMonitor` is `tests/test_automapbanks.py`'s: a C64's banking over two
dictionaries of bytes, not a mock of the reader.
"""

from __future__ import annotations

import os
import pathlib

import pytest
from test_automapbanks import (  # noqa: E402
    CHIPS_OUT,
    JUNK_SCREEN,
    TRUE_SCREEN,
    a_machine,
)

livecheck = pytest.importorskip("tools.livecheck")


@pytest.fixture(autouse=True)
def _forget_banks():
    """The bank ids are cached per monitor; each test gets its own machine."""
    from automap import vice
    vice._BANKS.clear()
    yield
    vice._BANKS.clear()


class FakeSession:
    """Just enough `tools.session.Session` for a `SessionTarget`.

    `mon()` hands back the same machine every time, the way a real session
    hands back a fresh connection to the same emulator.
    """

    def __init__(self, mon):
        self._mon = mon
        self.opened = 0

    def mon(self, timeout: float = 5.0):
        self.opened += 1
        return self._mon


# -- where a run writes -------------------------------------------------------


def test_importing_the_tool_leaves_xdg_data_home_alone():
    """Assigning it is what stopped VICE launching at all.

    The variable is Flatpak's as much as it is ours: moving it hides the
    user installation the emulator is in. The tool redirects
    `automap.state._data_dir` instead, which is the one function the notes
    path goes through.
    """
    import importlib

    before = os.environ.get("XDG_DATA_HOME")
    importlib.reload(livecheck)
    assert os.environ.get("XDG_DATA_HOME") == before


def test_a_runs_explored_squares_do_not_land_in_the_players_notes(monkeypatch):
    """A validation run walks a map; those squares are not the player's.

    **The redirect is applied here rather than at import**, and undone when
    this test ends. It used to run at `tools/livecheck.py`'s module level, and
    this file imports that module at *its* module level -- so under
    `pytest -n auto`, where every worker collects every file, every worker got
    the redirection before any test ran, and eight note tests in
    `tests/test_automap.py` then shared one directory and read each other's
    notes. `#428 (Ten automapper note tests fail under parallel load but pass
    alone, so a green suite depends on how busy the machine is)`.
    """
    from automap import state as mapstate
    from automap.state import AutomapState

    monkeypatch.setattr(mapstate, "_data_dir", lambda: livecheck.RUN_DATA)
    state = AutomapState(area="GEO01", title="Curse of the Azure Bonds")
    where = state.notes_path()
    assert livecheck.RUN_DATA in where.parents, where
    # And still under the title, which is `#30`'s split: GEO01 is a different
    # place in every game and a run must not merge them either.
    assert where.parent.name == "curse-of-the-azure-bonds"
    assert pathlib.Path.home() / ".local/share/wish" not in where.parents


# -- which memory the screen comes out of -------------------------------------


def test_the_fix_reads_the_vic_registers_from_the_chips():
    """`SessionTarget.fix` answers the square the game is really showing.

    The machine here is `#336`'s: `$01 = $30`, the true `$D018`/`$DD00` in the
    chips putting the screen at `$CC00`, and a *plausible* wrong status line
    in the RAM under the screen the processor's view would compute. A reader
    that took the registers through `read` answers `9,9`; this one answers
    `5,2`.
    """
    mon = a_machine(port1=CHIPS_OUT)
    target = livecheck.SessionTarget(FakeSession(mon))
    fix = target.fix()
    assert fix is not None
    assert (fix.x, fix.y) == (5, 2)
    assert fix.source == "status"
    # The registers were asked of the io bank, id 3 on this machine.
    io = {bank for addr, _n, bank in mon.asked if addr in (0xD011, 0xD018)}
    assert io == {3}, mon.asked


def test_a_fix_taken_through_the_processors_view_would_be_the_wrong_square():
    """The control: the same machine, read the way the bug read it.

    Without this the test above passes on any machine where the two memories
    agree, and says nothing.
    """
    from automap.target import party_fix

    mon = a_machine(port1=CHIPS_OUT)
    assert party_fix(mon.read) is None or party_fix(mon.read).x == 9
    assert TRUE_SCREEN != JUNK_SCREEN


def test_no_named_banks_and_the_chips_out_answers_no_fix():
    """None is "the screen could not be located", not "the game is frozen".

    A VICE with no `CMD_BANKS_AVAILABLE` and `$01` with the chips banked out
    has nothing to read the registers from, and the caller keeps its last
    reading rather than believing an address computed off the RAM.
    """
    mon = a_machine(port1=CHIPS_OUT, banks={})
    assert livecheck.SessionTarget(FakeSession(mon)).fix() is None


def test_a_named_block_is_read_from_the_memory_it_names():
    """`read_blocks` honours `(addr, length, "io"|"ram")`.

    The combat log reads three chip registers in with the game's own bytes,
    and splitting those into a second burst would double the resume the burst
    exists to avoid.
    """
    mon = a_machine(port1=CHIPS_OUT)
    target = livecheck.SessionTarget(FakeSession(mon))
    blocks = [(0xD018, 1, "io"), (0xD018, 1, "ram"), (0x0400, 1)]
    out = target.read_blocks(blocks)
    assert out[0] != out[1], "the chips and the RAM under them read the same"
    banks = [bank for addr, _n, bank in mon.asked if addr == 0xD018]
    assert 3 in banks and 1 in banks, mon.asked


# -- the cross-check against the file -----------------------------------------


def test_a_card_that_disagrees_with_the_save_file_is_named():
    live = [{"slot": 0, "name": "BRUTUS", "hp_max": 11, "experience": 900}]
    cold = [{"slot": 0, "name": "BRUTUS", "hp_max": 11, "experience": 800}]
    agree, disagree = livecheck._cross(live, cold)
    assert agree == 2
    assert disagree == [{"slot": 0, "field": "experience",
                         "live": 900, "file": 800}]


def test_a_card_with_no_slot_in_the_file_is_a_disagreement():
    """The two sources must be about the same party, or the comparison is
    vacuous: an empty cold read would otherwise agree with everything."""
    live = [{"slot": 3, "name": "SILAS", "hp_max": 9, "experience": 1}]
    agree, disagree = livecheck._cross(live, [])
    assert agree == 0
    assert disagree and disagree[0]["field"] == "slot"


# -- the per-title table ------------------------------------------------------


def test_every_title_the_tool_offers_has_a_descriptor_and_a_boot():
    """Three titles, each with a `goldbox.games` descriptor of its own.

    A key that no longer resolves would give `games.by_key` None and every
    address the run reads would be `None`-derived, which is the failure
    `#29 (The live reader uses Pool of Radiance's addresses on every title)`
    exists to prevent.
    """
    assert set(livecheck.TITLES) == {"por", "curse", "ssb"}
    for key, title in livecheck.TITLES.items():
        assert title.game is not None, key
        assert title.game.mode_flag is not None, key
        assert title.game.live_position is not None, key
        assert title.boot is not livecheck.Title.boot, key


def test_the_area_row_helper_hands_back_the_tables_own_arrival():
    """`FastTravel` is given the row's own arrival square, not one made up."""
    from automap import actions as act

    rows = [r for r in act.area_rows("Pool of Radiance")
            if r.arrival is not None]
    assert rows, "no Pool of Radiance row carries an arrival square"
    row = rows[0]
    assert livecheck._arrival(row) == (row.arrival.x, row.arrival.y,
                                       row.arrival.facing)


def test_a_row_with_no_arrival_square_hands_back_none():
    class Row:
        arrival = None

    assert livecheck._arrival(Row()) is None
