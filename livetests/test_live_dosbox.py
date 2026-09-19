"""The obstacle-2 experiment: drive DOSBox one step and read the save back."""

import pytest
from needs import fail_if_missing_tools, fail_if_save_missing, find_game_or_fail

from tools.dos import dosbox

# Shares a group with tests/test_instance.py, which claims emulator-pool slots
# by a fixed display number, so a parallel run keeps these in one worker.
pytestmark = pytest.mark.xdist_group(name="emulator-pool")


def test_driving_the_game_one_step_moves_the_square_and_nothing_else():
    """Boots DOSBox, takes one step, and reads the party's square before and after."""
    fail_if_missing_tools(dosbox.missing_tools())
    fail_if_save_missing(find_game_or_fail(), "A")
    out = dosbox.one_step(load="A", before="C", after="D", turns=2)
    bx, by, _ = out["before"]
    ax, ay, af = out["after"]
    assert (ax, ay) != (bx, by) or af != out["before"][2]
    assert out["area_id"][0] == out["area_id"][1]
    assert dosbox.POS_X in out["changed_in_struct"] + out["changed_in_array"] or (
        dosbox.POS_Y in out["changed_in_struct"]
    )
