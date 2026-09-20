"""`tools/curse_of_the_azure_bonds/cursewheel.py`'s command line, which answers DOS Curse's code wheel
and says nothing about the challenge or the answer (#108's ruling).

Nothing here reads a real code-wheel prompt off a real screenshot -- that
would be a specimen of the very thing `#108` keeps out of this repository.
The frames below are built from plain shapes, enough ink in each rune tile
and a path band drawn at the exact per-cell geometry measured off three live
DOS Curse prompts on 2026-09-14 (`#537 (tools/curse_of_the_azure_bonds/cursewheel.py never recognises
a real DOS Curse code-wheel screenshot, so its own command line refuses every
prompt)`, both comments on that issue): a dot is a 3x3 diamond at columns
2-4, rows 4-6 of its 8x8 text cell; a dash is a 7px-wide bar across rows 2-3.
`identify()` runs its whole pipeline against the `codewheel` entry's reference
bitmaps without any frame corresponding to a real challenge; what is
asserted is the shape of the command line's own output, never which rune it
decided on.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.curse_of_the_azure_bonds import cursewheel  # noqa: E402

needs_wheel_repo = pytest.mark.skipif(
    not (cursewheel.wheel_repo() / "coab" / "images").is_dir(),
    reason="needs the codewheel entry, Donald's separate private repository; "
           "set WISH_CODEWHEEL or add it to gamedisks.yaml")

#: The row the frames below draw their path band in -- cell row 13, the same
#: row every real prompt measured for #537 used.
_BAND_TOP = 13 * 8

#: Text cells 3-11 carry `UNDER THE` and cells 25-28 carry `PATH` on a real
#: prompt; cell 29 carries the green period that ends it.  Nothing here reads
#: the words themselves, only that they are not marks -- so a solid green
#: block standing in for each letter is enough.
_TEXT_CELLS = tuple(range(3, 12)) + tuple(range(25, 29))
_PERIOD_CELL = 29


def _dot(px, cell: int) -> None:
    """The 3x3 diamond a real dot mark measures: single, triple, single."""
    x0 = cell * 8
    for dx, dy in ((2, 5), (3, 4), (3, 5), (3, 6), (4, 5)):
        px[x0 + dx, _BAND_TOP + dy] = (255, 255, 255)


def _dash(px, cell: int) -> None:
    """The 7px bar a real dash mark measures: rows 2-3, tapered at each end."""
    x0 = cell * 8
    for dx, dy in ((1, 3), (2, 2), (2, 3), (3, 2), (3, 3), (4, 2), (4, 3),
                   (5, 2), (5, 3), (6, 2), (6, 3), (7, 2)):
        px[x0 + dx, _BAND_TOP + dy] = (255, 255, 255)


def _text(px, cell: int) -> None:
    """A stand-in letter: a solid 7x7 block, the size a real one measures."""
    x0 = cell * 8
    for dx in range(7):
        for dy in range(7):
            px[x0 + dx, _BAND_TOP + dy] = (85, 255, 85)


def _synthetic_frame(tmp_path, pattern: str | None) -> pathlib.Path:
    """A 320x200 frame with ink in both rune tiles and, if `pattern` is
    given, a path band drawn in that pattern's measured geometry.

    `pattern` is `"dash"`, `"dot"`, `"mixed"` or `None` for a frame that
    carries the surrounding prose and the trailing period but no path band at
    all -- the case a real prompt's path could not be read.
    """
    #: After any skip above, never before. `pillow` became a declared
    #: dependency on 2026-09-11, so this no longer skips on CI for want
    #: of it -- which is how `test_a_blank_frame_says_no_challenge` came
    #: to run there and fail on a private repository CI has never had.
    #: `needs_wheel_repo` is the skip that matters; this only keeps an
    #: import at the top of the body from failing a test it should skip.
    Image = pytest.importorskip("PIL.Image")

    im = Image.new("RGB", (320, 200), (0, 0, 0))
    px = im.load()
    for box in cursewheel.TILES.values():
        left, top, w, h = box
        for x in range(left + 2, left + w - 2):
            for y in range(top + 2, top + h - 2):
                px[x, y] = (255, 255, 255)

    for cell in _TEXT_CELLS:
        _text(px, cell)
    _dot(px, _PERIOD_CELL)

    if pattern == "dot":
        for cell in range(14, 23):
            _dot(px, cell)
    elif pattern == "dash":
        for cell in (14, 16, 18, 20, 22):
            _dash(px, cell)
    elif pattern == "mixed":
        for i, cell in enumerate(range(14, 23)):
            (_dash if i % 3 == 0 else _dot)(px, cell)
    elif pattern is not None:
        raise ValueError(pattern)

    path = tmp_path / f"frame-{pattern}.png"
    im.save(path)
    return path


def _blank_frame(tmp_path) -> pathlib.Path:
    """A frame with no ink anywhere -- the main menu, or any other screen
    that is not the code-wheel prompt."""
    #: After any skip above, never before. `pillow` became a declared
    #: dependency on 2026-09-11, so this no longer skips on CI for want
    #: of it -- which is how `test_a_blank_frame_says_no_challenge` came
    #: to run there and fail on a private repository CI has never had.
    #: `needs_wheel_repo` is the skip that matters; this only keeps an
    #: import at the top of the body from failing a test it should skip.
    Image = pytest.importorskip("PIL.Image")

    path = tmp_path / "blank.png"
    Image.new("RGB", (320, 200), (0, 170, 0)).save(path)
    return path


@needs_wheel_repo
def test_a_blank_frame_says_no_challenge(tmp_path, capsys):
    rc = cursewheel.main(["--shot", str(_blank_frame(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 1
    assert out == "no challenge on screen\n"


@needs_wheel_repo
def test_the_dot_pattern_reads_as_1(tmp_path):
    """The regression: a real dot mark is a 3x3 diamond, three rows tall, and
    the reader this issue replaces only ever recognised a mark two rows tall
    -- so it returned `None` for every dot-pattern prompt, including the one
    real specimen on record (#537)."""
    im_path = _synthetic_frame(tmp_path, "dot")
    from PIL import Image  # noqa: PLC0415
    assert cursewheel.read_path(Image.open(im_path).convert("RGB")) == 1


@needs_wheel_repo
def test_the_dash_pattern_reads_as_0(tmp_path):
    """A dash prompt marks only every other cell of its nine -- 14, 16, 18,
    20, 22 -- not a contiguous run, which is what the run-detection has to
    tolerate to see one band rather than five isolated marks (#537)."""
    im_path = _synthetic_frame(tmp_path, "dash")
    from PIL import Image  # noqa: PLC0415
    assert cursewheel.read_path(Image.open(im_path).convert("RGB")) == 0


@needs_wheel_repo
def test_the_mixed_pattern_reads_as_2(tmp_path):
    im_path = _synthetic_frame(tmp_path, "mixed")
    from PIL import Image  # noqa: PLC0415
    assert cursewheel.read_path(Image.open(im_path).convert("RGB")) == 2


@needs_wheel_repo
def test_the_period_after_path_is_not_read_as_a_mark(tmp_path):
    """A frame with the prose and its trailing period, but no path band, is
    a prompt whose path could not be read -- not a one-mark dot band."""
    im_path = _synthetic_frame(tmp_path, None)
    from PIL import Image  # noqa: PLC0415
    assert cursewheel.read_path(Image.open(im_path).convert("RGB")) is None


@needs_wheel_repo
def test_a_challenge_with_no_box_is_not_answered(tmp_path, capsys):
    rc = cursewheel.main(["--shot", str(_synthetic_frame(tmp_path, "dot"))])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "challenge on screen, not answered\n"


@needs_wheel_repo
def test_a_challenge_whose_path_cannot_be_read_is_not_answered_rather_than_absent(
        tmp_path, capsys):
    """The other half of the regression: before #537's fix to `main()`, an
    unread path was folded into "no challenge on screen" -- contradicting the
    module's own docstring, which promises this frame reads as "challenge on
    screen, not answered" -- and fired before `--path` was ever read."""
    rc = cursewheel.main(["--shot", str(_synthetic_frame(tmp_path, None)),
                          "--box", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "challenge on screen, not answered\n"


@needs_wheel_repo
def test_path_overrides_an_unread_path(tmp_path, capsys):
    """`--path` exists to rescue exactly this frame: tile ink present, no
    path band, so `read_path()` alone gives up. Before #537's `main()` fix
    this override could never fire -- the ink/path refusal returned first."""
    rc = cursewheel.main(["--shot", str(_synthetic_frame(tmp_path, None)),
                          "--box", "3", "--path", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "challenge on screen, answered\n"


@needs_wheel_repo
def test_a_challenge_with_a_box_is_answered_and_nothing_else_is_printed(
        tmp_path, capsys):
    """The regression: before #108's fix to this file, this exact run
    printed both rune tiles' ranked indices and scores, the path name and
    the character the game wants -- none of which belongs in a transcript.
    """
    rc = cursewheel.main(["--shot", str(_synthetic_frame(tmp_path, "dot")),
                          "--box", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "challenge on screen, answered\n"
    # Neither a rune index/score pair ("espruar 3=0.96") nor a typed
    # character ("type 'U'") ever reaches stdout.
    for name in ("espruar", "dethek", "path", "type", "="):
        assert name not in out, out
