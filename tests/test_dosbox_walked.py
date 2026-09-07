"""`tools.dosbox.judge_step` and `run_walked`: telling a walk from a wall
from a driver that pressed nothing (#341 (A DOS run reports a party that
walked into another area as never having walked)).

Every case here is decided from recorded readings -- digests, areas and
squares handed in as plain values -- so none of it starts an emulator.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import dosbox  # noqa: E402


def describe(area: int, x: int, y: int, facing: int) -> dict:
    """A `describe()`/`describe_dos()`-shaped dict, with only what
    `run_walked` reads."""
    return {"area": area, "square": [x, y, facing]}


# -- judge_step ---------------------------------------------------------

def test_a_step_within_an_area_is_a_walk():
    # The status digest differs; no area readings are available (as in the
    # per-step loop, which has only a screen digest to compare).
    kind, reason = dosbox.judge_step(True, True)
    assert kind == "walked"
    assert reason is None


def test_an_area_change_is_a_walk_even_when_the_digest_did_not_move():
    # This is the case #341 is about: the status line lagged the redraw, so
    # the digest read before and after a step that crossed into another area
    # compare equal (`changed=False`) -- and the area itself, read from a
    # save file rather than the screen, says otherwise.
    kind, reason = dosbox.judge_step(True, False, area_before=0, area_after=20)
    assert kind == "walked"
    assert reason is None


def test_an_area_change_reported_as_a_walk_fails_without_reading_the_area():
    # Proves the assertion above is not vacuous: with only the (lagged)
    # digest to go on, the same step reads as blocked.  This is the bug.
    kind, _ = dosbox.judge_step(True, False)
    assert kind == "blocked"


def test_no_movement_is_blocked():
    kind, reason = dosbox.judge_step(True, False, area_before=0, area_after=0)
    assert kind == "blocked"
    assert reason is None


def test_the_driver_pressing_nothing_is_a_driver_error_not_a_wall():
    # Even handed an area change and a changed digest, a step the driver
    # never sent a key for is never a wall -- #360 (The session driver will
    # not walk a Curse or Silver Blades party in a dungeon, because it reads
    # Pool of Radiance's indoors flag)'s `Session.walk_refused` distinction,
    # carried into this harness's own vocabulary.
    kind, reason = dosbox.judge_step(False, True, area_before=0, area_after=20)
    assert kind == "refused"
    assert reason == "the driver pressed nothing"


# -- run_walked -----------------------------------------------------------

def test_run_walked_true_for_a_step_within_the_area():
    built = describe(0, 5, 13, 1)
    resaved = describe(0, 7, 13, 1)
    assert dosbox.run_walked(built, resaved) is True


def test_run_walked_true_for_a_crossed_area_even_with_the_same_square():
    # The reported bug: New Phlan (0,4) facing west to the Slums (0,4)
    # facing west would read as no movement by square alone -- the area is
    # what proves it, and it must be checked before the square is.
    built = describe(0, 0, 4, 3)
    resaved = describe(20, 0, 4, 3)
    assert dosbox.run_walked(built, resaved) is True


def test_run_walked_false_when_nothing_moved():
    built = describe(0, 5, 13, 1)
    resaved = describe(0, 5, 13, 1)
    assert dosbox.run_walked(built, resaved) is False


def test_run_walked_ignores_a_facing_only_change():
    # The loop turns the party in place to recover from a wall; a facing
    # change alone is not a walk.
    built = describe(0, 5, 13, 1)
    resaved = describe(0, 5, 13, 3)
    assert dosbox.run_walked(built, resaved) is False
