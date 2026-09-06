"""`tools/cursewheel.py`'s command line, which answers DOS Curse's code wheel
and says nothing about the challenge or the answer (#108's ruling).

Nothing here reads a real code-wheel prompt off a real screenshot -- that
would be a specimen of the very thing `#108` keeps out of this repository.
The frame below is built from plain shapes, enough ink in each rune tile and
a readable path pattern, so `identify()` runs its whole pipeline against
`$WISH_CODEWHEEL`'s reference bitmaps without the frame corresponding to any
real challenge; what is asserted is the shape of the command line's own
output, never which rune it decided on.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import cursewheel  # noqa: E402

needs_wheel_repo = pytest.mark.skipif(
    not (cursewheel.wheel_repo() / "coab" / "images").is_dir(),
    reason="needs $WISH_CODEWHEEL, Donald's separate private repository")


def _synthetic_frame(tmp_path) -> pathlib.Path:
    """A 320x200 frame with ink in both rune tiles and a readable path.

    Solid black inside each of `cursewheel.TILES`' boxes is enough to pass
    the ink threshold -- black is not one of `cursewheel.BACKGROUND`'s two
    greens or two greys, and `declutter` keeps every interior pixel of a
    block that size.  The path is three separated five-column marks in one
    8-row band, each lit at the same two adjacent rows, which is what
    `read_path` calls the all-middle pattern.
    """
    from PIL import Image

    im = Image.new("RGB", (320, 200), (0, 0, 0))
    px = im.load()
    for box in cursewheel.TILES.values():
        left, top, w, h = box
        for x in range(left, left + w):
            for y in range(top, top + h):
                px[x, y] = (0, 0, 0)
    top = 80
    for start in (40, 60, 80):
        for x in range(start, start + 5):
            for y in (top + 2, top + 3):
                px[x, y] = (255, 255, 255)
    path = tmp_path / "frame.png"
    im.save(path)
    return path


def _blank_frame(tmp_path) -> pathlib.Path:
    """A frame with no ink anywhere -- the main menu, or any other screen
    that is not the code-wheel prompt."""
    from PIL import Image

    path = tmp_path / "blank.png"
    Image.new("RGB", (320, 200), (0, 170, 0)).save(path)
    return path


def test_a_blank_frame_says_no_challenge(tmp_path, capsys):
    rc = cursewheel.main(["--shot", str(_blank_frame(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 1
    assert out == "no challenge on screen\n"


@needs_wheel_repo
def test_a_challenge_with_no_box_is_not_answered(tmp_path, capsys):
    rc = cursewheel.main(["--shot", str(_synthetic_frame(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "challenge on screen, not answered\n"


@needs_wheel_repo
def test_a_challenge_with_a_box_is_answered_and_nothing_else_is_printed(
        tmp_path, capsys):
    """The regression: before #108's fix to this file, this exact run
    printed both rune tiles' ranked indices and scores, the path name and
    the character the game wants -- none of which belongs in a transcript.
    """
    rc = cursewheel.main(["--shot", str(_synthetic_frame(tmp_path)),
                          "--box", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "challenge on screen, answered\n"
    # Neither a rune index/score pair ("espruar 3=0.96") nor a typed
    # character ("type 'U'") ever reaches stdout.
    for name in ("espruar", "dethek", "path", "type", "="):
        assert name not in out, out
