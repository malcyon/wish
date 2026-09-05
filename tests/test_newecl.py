"""The addresses `FastTravel` writes, re-derived off the player's own disks.

`automap/actions.py` carries Pool of Radiance's `NEWECL` tail, key-wait window
and key fetcher as constants, and every one of them was measured once and
written down. A constant written down is a claim nothing checks: it stays
believed through a differently-cracked release, a wrong `--base`, and a paste
error, and the first symptom is a `JMP` into somebody else's code.

So these re-derive them from the game's bytes, by the procedure
`tools/newecl.py` uses -- find the script VM by its **self-modifying dispatch**
(a `JSR` whose own operand bytes two `STA`s elsewhere write), take entry `$20`
of the tables it builds, and read the routine -- and check the answers against
what the code ships. Nothing is compared against a number typed into this file
except the ones `automap/actions.py` already publishes.

`#19 (Can Curse be fast-travelled at all, or is the mechanism Pool of
Radiance's alone?)` is where the procedure came from, and Curse and Silver
Blades are checked here as well where their disks are present: not for a
particular address, which no shipped code uses yet, but for the **shape** --
that the mechanism is there at all, which is what that ticket answered.

Game data comes off the player's disks at run time (`tests/gamedata.py`'s rule)
and every test here skips when they are not there.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

# The real `wish` package first, before anything reaches into `tools/`, for
# the reason `tests/test_arrivalscene.py` spells out: `tools/wish.py` shares
# the package's name and a bare `import wish` that resolves to it stays
# resolved for the whole process.
import wish  # noqa: F401
from automap.actions import KEY_FETCH, KEY_WAIT, NEWECL_TAIL
from automap.paths import find_disks
from goldbox import games

TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools"


def _newecl():
    spec = importlib.util.spec_from_file_location(
        "_newecl_under_test", TOOLS / "newecl.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_newecl_under_test", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def newecl():
    return _newecl()


def _disks(game):
    root = find_disks(game)
    if root is None:
        pytest.skip(f"no {game.title} disks on this machine")
    return str(root)


def _read(newecl, game, base=0x0800):
    """`(handler, tail, key-wait window, key-fetch window)` for one title."""
    root = _disks(game)
    _, body = newecl.load("DUNGEON", root, game)
    _, lo_t, hi_t, _ = newecl.dispatch_tables(body, base)
    at = newecl.handler(body, base, lo_t, hi_t, newecl.NEWECL_OPCODE)
    lines = newecl.instructions(body, base, at, 0x40)
    tail = newecl.newecl_tail(lines)
    test = newecl.find_window(body, base, newecl.KEY_WAIT_SIG, "key-wait")
    wait = newecl.loop_start(body, base, test) if test else None
    _, lib = newecl.load("LIBRARY", root, game)
    called = next(int(t[5:], 16) for _, _, t
                  in newecl.instructions(body, base, wait[0], 0x10)
                  if t.startswith("JSR $"))
    off = lib.find(newecl.KEY_FETCH_SIG)
    fetch = (called, newecl.reachable_end(lib, called - off, called))
    return at, tail, wait, fetch, lines


def test_the_shipped_pool_of_radiance_addresses_are_what_the_disk_says(newecl):
    """`NEWECL_TAIL`, `KEY_WAIT` and `KEY_FETCH` against the game's own bytes.

    These three are what a fast travel jumps to and what it will accept a PC
    from, so a drift in any of them is the difference between a warp and a
    crash. `KEY_WAIT` and `KEY_FETCH` were measured from 400 program-counter
    samples of an idle party; this reaches the same two windows from the
    static side, which is the corroboration that measurement never had.
    """
    at, tail, wait, fetch, _ = _read(newecl, games.POOL_OF_RADIANCE)
    assert at == 0x2011                      # `docs/118-debug-mode.md` §3
    assert tail == NEWECL_TAIL
    assert wait == KEY_WAIT
    assert fetch == KEY_FETCH


def test_the_handler_is_the_routine_the_writes_were_copied_from(newecl):
    """The five writes, in the order `automap/actions.py` makes them.

    `FastTravel.run` is a copy of this routine with the operand fetch removed.
    If the routine ever reads differently -- another release, another crack --
    the copy is wrong and the tooltip that says the writes are the game's own
    is a lie, so the shape is asserted rather than the addresses alone.
    """
    from automap.actions import (
        FASTTRAVEL_FROM,
        FASTTRAVEL_SCRATCH,
        FASTTRAVEL_SLOT,
    )
    _, _, _, _, lines = _read(newecl, games.POOL_OF_RADIANCE)
    text = [t for _, _, t in lines]
    assert text[0] == f"LDA ${FASTTRAVEL_SLOT:04X}"
    assert text[1] == "AND #$7F"
    assert text[2] == f"STA ${FASTTRAVEL_FROM:04X}"
    assert f"STA ${FASTTRAVEL_SCRATCH:04X},X" in text
    assert f"STA ${FASTTRAVEL_SLOT:04X}" in text
    assert "JMP $0809" in text               # restart the overlay


@pytest.mark.parametrize("key,handler,tail", [
    ("curse-of-the-azure-bonds", 0x21BA, 0x21DD),
    ("secret-of-the-silver-blades", 0x20E6, 0x210C),
])
def test_the_later_titles_have_the_same_mechanism(newecl, key, handler, tail):
    """Curse and Silver Blades have a `NEWECL` whose tail can be entered.

    The answer to `#19 (Can Curse be fast-travelled at all, or is the
    mechanism Pool of Radiance's alone?)`, pinned. The addresses are here
    because they are the finding, not because anything ships them: no code
    reads these yet, and a change in either is a change in what that ticket
    concluded.
    """
    game = next(g for g in games.GAMES if g.key == key)
    at, got, wait, fetch, lines = _read(newecl, game)
    assert (at, got) == (handler, tail)
    assert wait[0] < wait[1]
    assert fetch[0] < fetch[1]
    text = [t for _, _, t in lines]
    # The save-relative writes moved by `save_load_address`, and the live
    # triple did not move at all -- which is the whole reason a Pool of
    # Radiance square can be written into a Curse machine.
    assert text[1] == "AND #$7F"
    assert any(t.startswith("STA $4BF2") for t in text)
    assert any(t.startswith("STA $4C00,X") for t in text)
    assert "JMP $0809" in text
