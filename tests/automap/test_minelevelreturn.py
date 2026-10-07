"""The Return control's reason on a Silver Blades mine level.

A trip cannot enter mine levels 1-8 (`goldbox/areas.py`, rows `$31` and
`$32`), so a party that rode the wheel lift down, Fast Travelled out and now
asks to return is told how to get back in. The sentence is for those two rows
of that title and nowhere else.
"""

import dataclasses
import os

import pytest
from support.debugmachine import WORLD

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automap import actions, c64, fasttravel
from automap.target import MemoryTarget
from goldbox import c64_port

SENTENCE = "Use the wheel lift to return to this mine level."
BLADES = c64_port.SECRET_OF_THE_SILVER_BLADES
POOL = c64_port.POOL_OF_RADIANCE


class _Machine(MemoryTarget):
    def __init__(self, memory, pc):
        super().__init__(memory)
        self._pc = pc

    def pc(self) -> int:
        return self._pc

    def set_pc(self, address: int) -> None:
        self._pc = address


def _ready(game, addr, area_id: int):
    """`game`'s machine idle in the world, standing in area `area_id`."""
    pool = fasttravel.POOL_OF_RADIANCE
    addr = dataclasses.replace(
        addr, after_step=pool.after_step, forward_key=pool.forward_key,
        redraw=pool.redraw, saved_sp=pool.saved_sp,
        main_loop_return=pool.main_loop_return)
    ft = actions.FastTravel(game)
    ft.addresses = addr
    target = _Machine({
        c64.machine_for(game).mode_flag: bytes([WORLD]),
        addr.slot: bytes([area_id]), addr.disk: bytes([3]),
        addr.indoors: bytes([1]), addr.live_square: bytes([5, 6, 1]),
        addr.saved_sp: bytes([0xF0])}, pc=addr.key_wait[0])
    return ft, target


def _returning_to(game, addr, back_area: int, here: int = 0x20):
    ft, target = _ready(game, addr, here)
    ft.back = actions.Waypoint(back_area, 3, (3, 3, 1))
    return ft, target


@pytest.mark.parametrize("level", [0x31, 0x32])
def test_the_way_back_to_a_mine_level_says_to_use_the_wheel_lift(level):
    ft, target = _returning_to(BLADES, fasttravel.SECRET_OF_THE_SILVER_BLADES,
                               level)
    verdict = ft.back_verdict(target)
    assert not verdict
    assert verdict.reason == SENTENCE


def test_a_silver_blades_area_that_is_not_a_mine_level_gets_no_such_sentence():
    ft, target = _returning_to(BLADES, fasttravel.SECRET_OF_THE_SILVER_BLADES,
                               0x33)
    assert ft.back_verdict(target).reason != SENTENCE
    # Nor does a forward trip that names a mine level: the sentence is for
    # the Return control only.
    row = next(a for a in actions.area_rows(BLADES.title) if a.id == 0x31)
    assert ft.legality(target, row).reason != SENTENCE


def test_another_title_with_the_same_id_gets_no_such_sentence():
    ft, target = _returning_to(POOL, fasttravel.POOL_OF_RADIANCE, 0x31)
    assert ft.back_verdict(target).reason != SENTENCE
    ft, target = _returning_to(POOL, fasttravel.POOL_OF_RADIANCE, 30)
    assert ft.back_verdict(target).reason == actions.FastTravel.ATTRACT_TRAP
