"""`tools/amigacursewheel.py`, which answers Amiga Curse's prompt and says nothing.

Nothing here touches the separate repository the arithmetic lives in, and
nothing here knows a challenge or an answer -- that is the point of the tool
and it is the point of these tests.  What can be asserted without it is the
part that had to be worked out here: the whole-number rescale that makes a
`winvm shot` of WinUAE's window readable by a reader written against FS-UAE,
and that a machine with no such repository is told so rather than crashing.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import amigacursewheel  # noqa: E402


def test_a_winuae_capture_is_scaled_up_to_the_readers_range():
    # `winvm shot` of the 720-wide window puts the 320-pixel Amiga screen at
    # exactly 2.0 captured pixels each, and the reader's fit searches 3.60 to
    # 4.00, so it returned "not a challenge" on a capture whose runes both
    # identified at 1.000.
    assert amigacursewheel.scale_factor(2.0) == 2
    assert 2.0 * 2 >= amigacursewheel.PITCH_MIN


def test_a_capture_already_in_range_is_left_alone():
    # FS-UAE's own scale, which the reader was written against.
    assert amigacursewheel.scale_factor(3.8) == 1
    assert amigacursewheel.scale_factor(4.0) == 1


def test_every_factor_reaches_the_range_and_none_overshoots_by_a_whole_step():
    for tenths in range(5, 81):
        pitch = tenths / 10
        factor = amigacursewheel.scale_factor(pitch)
        assert pitch * factor >= amigacursewheel.PITCH_MIN
        assert factor == 1 or pitch * (factor - 1) < amigacursewheel.PITCH_MIN


def test_the_environment_names_the_repository_and_has_a_default(monkeypatch):
    monkeypatch.setenv(amigacursewheel.ENV, "/somewhere/else")
    assert amigacursewheel.wheel_repo() == pathlib.Path("/somewhere/else")
    monkeypatch.delenv(amigacursewheel.ENV, raising=False)
    assert amigacursewheel.wheel_repo().name == "goldbox-codewheel"


def test_a_machine_without_the_repository_is_told_where_it_looked(monkeypatch,
                                                                  tmp_path):
    monkeypatch.setenv(amigacursewheel.ENV, str(tmp_path / "nothing"))
    with pytest.raises(SystemExit) as raised:
        amigacursewheel._wheel_modules()
    assert "nothing" in str(raised.value)
    assert amigacursewheel.ENV in str(raised.value)
