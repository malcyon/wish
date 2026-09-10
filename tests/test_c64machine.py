"""`automap.c64.C64Machine`: the C64's live addresses, one row per title.

Built for `#470 (Give the project a neutral title beside its neutral character
record, with one port per platform a title shipped on)`'s stage 6, which took
the two live addresses off `goldbox.c64_port.Game` and gave the C64 a machine
beside the Amiga's `AmigaMachine`.

Two things here are the point and the rest is arithmetic:

* **Three titles answer None for both live addresses**, and nothing pinned
  that before this file. Champions of Krynn, Death Knights of Krynn and
  Gateway to the Savage Frontier have never been run under a monitor, and a
  row that quietly acquired `$C04B` or `$6E11` would send every action and
  every automapper read at another game's memory -- `#29 (The live reader uses
  Pool of Radiance's addresses on every title)` is what that cost.
* **The machine and `Game` agree about every save-image address**, for all
  six titles. They compute them separately for one stage -- `goldbox/` may not
  import `automap` (`tests/test_wish.py::test_goldbox_imports_no_transport`)
  and `goldbox/savegame.py` reads them -- so this is what keeps the two from
  drifting until stage 7 merges them into `C64Container`.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap import actions, c64  # noqa: E402
from automap.target import MemoryTarget  # noqa: E402
from goldbox import c64_port, c64_save, titles  # noqa: E402

#: The three nobody has run under a monitor.
UNMEASURED = ("champions-of-krynn", "death-knights-of-krynn",
              "gateway-to-the-savage-frontier")

#: The three whose live addresses were measured, each in its own session.
MEASURED = ("pool-of-radiance", "curse-of-the-azure-bonds",
            "secret-of-the-silver-blades")


# --- the refusal ------------------------------------------------------------

@pytest.mark.parametrize("key", UNMEASURED)
def test_an_unrun_title_has_neither_live_address(key):
    """Both None, for each of the three, and never another title's number.

    `goldbox/c64_port.py` carried the comment saying so beside each row and
    no test read it. The failure it prevents is silent: a Champions party
    would be read at Pool of Radiance's `$C04B`, which answers *a* square
    rather than an error.
    """
    machine = c64.MACHINES[key]
    assert machine.live_position is None, key
    assert machine.mode_flag is None, key


@pytest.mark.parametrize("key", MEASURED)
def test_a_measured_title_has_both(key):
    """The other side of it, so the assertion above cannot pass by emptiness."""
    machine = c64.MACHINES[key]
    assert machine.live_position == c64.LIVE_POSITION_GOLDBOX, key
    assert machine.mode_flag in (c64.MODE_FLAG_POOL, c64.MODE_FLAG_LATER), key


@pytest.mark.parametrize("key", UNMEASURED)
def test_every_action_refuses_on_a_title_with_no_mode_flag(key):
    """`actions.mode` answers None, and an action says so rather than writing.

    This is the refusal the move had to keep. `mode()` reading an unmeasured
    address would answer whatever byte happened to be there, and an action
    would take "not 2" for "not in combat" and write into a fight.
    """
    game = c64_port.BY_KEY[key]
    target = MemoryTarget({c64.MODE_FLAG_POOL: bytes([1])})
    assert actions.mode(target, game) is None
    refused = actions.RestoreSpells(game=game).legality(target)
    assert not refused.ok
    assert refused.reason == actions.UNSUPPORTED.format(title=game.title)
    # And the same target does let Pool of Radiance through, so the refusal
    # above is the missing flag rather than an unreadable machine.
    assert actions.RestoreSpells().legality(target).ok


# --- the machine and the container agree ------------------------------------

BASES = ("slot_area_base", "item_area_base", "icon_table_base",
         "save_position_base", "indoors_flag_base", "travel_position_base",
         "roster_base")


@pytest.mark.parametrize("game", c64_port.GAMES, ids=lambda g: g.key)
def test_the_machine_answers_what_game_answers(game):
    """Every save-image address, both ways, for all six titles.

    The two computations are separate for one stage and this is what keeps
    them equal. `Game.clock_base` is compared against `shown_clock_base`,
    which is the same address under the name stage 6 gave it.
    """
    machine = c64.machine_for(game)
    for name in BASES:
        assert getattr(machine, name) == getattr(game, name), name
    assert machine.shown_clock_base == game.clock_base


@pytest.mark.parametrize("key", MEASURED)
def test_the_shown_clock_is_one_past_the_clock_the_container_names(key):
    """`+$C7` is the second of the six digits at `container.clock`, `+$C6`.

    The first is a sub-minute tick nothing prints. Two facts, two names, and
    this is the arithmetic that ties them: `#470`'s comment of 2026-09-09 read
    the tick loop and the status-line printer in all three titles.
    """
    machine = c64.MACHINES[key]
    container = c64_save.CONTAINERS[key]
    assert c64_port.SHOWN_CLOCK_OFFSET == container.clock + 1
    assert (machine.shown_clock_base
            == machine.save_load_address + container.clock + 1)


@pytest.mark.parametrize("game", c64_port.GAMES, ids=lambda g: g.key)
def test_a_machine_carries_its_titles_own_rules(game):
    """`C64Machine.title` is the `Title` row, by identity rather than by name.

    The first annotated `Title` field in the tree, and the reason this stage
    exists: before it, nothing said in the types that a machine belongs to a
    title.
    """
    machine = c64.machine_for(game)
    assert machine.title is titles.BY_KEY[game.key]


# --- the travel grid --------------------------------------------------------

def test_only_pool_of_radiance_answers_a_travel_square():
    """`travel_grid` is a `Title` fact now, and it still gates both addresses.

    Curse and Silver Blades carry no `SQRDATA`, `SQRPACI` or `WALLS`, so
    `$49E6` there is a byte of `LIBRARY` code that happens to read zero --
    `#360 (The session driver will not walk a Curse or Silver Blades party in
    a dungeon, because it reads Pool of Radiance's indoors flag)`.
    """
    grid = {key for key, m in c64.MACHINES.items() if m.title.travel_grid}
    assert grid == {"pool-of-radiance"}
    for key, machine in c64.MACHINES.items():
        wanted = key == "pool-of-radiance"
        assert (machine.indoors_flag_base is not None) is wanted, key
        assert (machine.travel_position_base is not None) is wanted, key


def test_the_pre_470_spelling_still_answers_on_game():
    """`Game.travel_grid` reads through to `Title.travel_grid` until stage 9."""
    assert c64_port.POOL_OF_RADIANCE.travel_grid is True
    assert c64_port.CURSE_OF_THE_AZURE_BONDS.travel_grid is False
    # A `Game` whose key `goldbox/titles.py` does not know answers False,
    # which is what an unregistered row answered when this was a field.
    made_up = c64_port.Game(key="untabled", title="Untabled",
                            save_file=b"SAVEX", save_load_address=0x4B00,
                            save_size=0x1D00)
    assert made_up.travel_grid is False


# --- the lookup -------------------------------------------------------------

def test_machine_for_takes_what_container_for_takes():
    """A `Game`, a `Title`, a key, a machine, or None."""
    pool = c64.MACHINES["pool-of-radiance"]
    assert c64.machine_for(None) is pool
    assert c64.machine_for("pool-of-radiance") is pool
    assert c64.machine_for(c64_port.POOL_OF_RADIANCE) is pool
    assert c64.machine_for(titles.BY_KEY["pool-of-radiance"]) is pool
    assert c64.machine_for(pool) is pool


def test_a_key_nobody_knows_raises_rather_than_answering_pool_of_radiance():
    """The refusal `#460` is about, one class over: no silent fallback."""
    with pytest.raises(KeyError):
        c64.machine_for("pools-of-darkness")


def test_a_game_outside_the_registry_keeps_its_own_geometry():
    """A row nobody registered answers its addresses and no live one.

    `tests/test_pertitle_ui.py` builds one, and `Game`'s own `_base`
    properties have always answered for it. The machine does the same rather
    than refusing, so the two stay equal for every `Game` there is.
    """
    made_up = c64_port.Game(key="untabled", title="Untabled",
                            save_file=b"SAVEX", save_load_address=0x4B00,
                            save_size=0x1D00)
    machine = c64.machine_for(made_up)
    assert machine.slot_area_base == made_up.slot_area_base
    assert machine.container is None
    assert machine.live_position is None
    assert machine.mode_flag is None
    assert machine.title.races is None
