"""`tools/amiga/amigacursewheel.py`, which answers Amiga Curse's prompt and says nothing.

Nothing here knows a challenge or an answer -- that is the point of the tool
and it is the point of these tests.  What is asserted is the part that had to
be worked out here: the whole-number rescale that makes a `winvm shot` of
WinUAE's window readable by a reader written against FS-UAE, and that a
machine with no such repository is told so rather than crashing.  One test
hands the separate repository's tile finder a picture of plain green blocks,
and skips where that repository is not on the machine.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automap import gamedisks  # noqa: E402
from tools.amiga import amigacursewheel  # noqa: E402


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
    assert amigacursewheel.wheel_repo() in gamedisks.candidates("codewheel")


def test_a_machine_without_the_repository_is_told_where_it_looked(monkeypatch,
                                                                  tmp_path):
    monkeypatch.setenv(amigacursewheel.ENV, str(tmp_path / "nothing"))
    with pytest.raises(SystemExit) as raised:
        amigacursewheel._wheel_modules()
    assert "nothing" in str(raised.value)
    assert amigacursewheel.ENV in str(raised.value)


#: The tile's own background, which the separate repository's finder looks for.
GREEN = (0, 153, 0)


def _tiles_png(path, pitch, gap_row=None):
    """Two rune-sized green blocks at `pitch` captured pixels per Amiga pixel.

    Each block covers the 20 x 22 Amiga pixels a rune tile's background does.
    `gap_row` blanks one Amiga row right across the top block, as a rune that
    crosses its whole tile does.  Nothing else is drawn.
    """
    width, height = int(320 * pitch), int(200 * pitch)
    image = np.zeros((height, width, 3), np.uint8)
    for top in (60, 92):
        rows = [r for r in range(22) if not (top == 60 and r == gap_row)]
        for row in rows:
            y = int((top + row) * pitch)
            x = int(150 * pitch)
            image[y:y + int(pitch), x:x + int(20 * pitch)] = GREEN
    Image.fromarray(image).save(path)
    return width, height


class _Screen:
    """A stand-in for the reader that reports grids it was told to."""

    def __init__(self, grids):
        self.grids = grids

    def find_runes(self, _image):
        return self.grids


@pytest.mark.parametrize("pitch, factor", [(2.0, 2), (4.0, 1)])
def test_only_the_width_is_enlarged(tmp_path, pitch, factor):
    # The reader fits the column pitch and measures the row pitch, so a
    # WinUAE capture at 2.0 is widened and keeps its rows, and an FS-UAE one
    # at 4.0 is left as it was.
    shot = tmp_path / "shot.png"
    width, height = _tiles_png(shot, pitch)
    grids = [(60 * pitch, 148 * pitch, pitch, pitch),
             (92 * pitch, 148 * pitch, pitch, pitch)]
    scaled = amigacursewheel._to_reader_scale(shot, _Screen(grids))
    assert scaled.shape == (height, width * factor, 3)


def test_the_narrowest_column_pitch_sets_the_factor(tmp_path):
    shot = tmp_path / "shot.png"
    width, height = _tiles_png(shot, 2.0)
    grids = [(120, 296, 2.0, 4.0), (184, 296, 2.0, 2.0)]
    scaled = amigacursewheel._to_reader_scale(shot, _Screen(grids))
    assert scaled.shape == (height, width * 2, 3)


def test_a_tile_crossed_by_its_rune_is_still_one_tile_after_scaling(tmp_path):
    # A rune that crosses its whole tile on one Amiga row leaves two captured
    # rows without green at 2.0.  Doubled rows made that four, the finder
    # split the tile there, and the top tile came back at half its row pitch.
    if not (amigacursewheel.wheel_repo() / "coab" / "analysis").is_dir():
        pytest.skip("the separate code-wheel repository is not on this machine")
    screen = amigacursewheel._wheel_modules()[0]
    shot = tmp_path / "shot.png"
    _tiles_png(shot, 2.0, gap_row=11)
    grids = screen.find_runes(amigacursewheel._to_reader_scale(shot, screen))
    assert [(g[2], g[3]) for g in grids] == [(2.0, 4.0), (2.0, 4.0)]
