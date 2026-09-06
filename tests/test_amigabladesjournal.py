"""`tools/amigabladesjournal.py`, which answers Amiga Silver Blades' journal
prompt and says nothing about it.

Nothing here touches the separate repository the tables live in, and nothing
here knows a challenge or an answer -- that is the point of the tool and it is
the point of these tests.  The frames below are plain coloured stripes on a
plain background: enough to fit a character grid on, and corresponding to no
real challenge screen.

What can be asserted without the private repository is the part that had to be
worked out here -- fitting the game's character grid inside a 1920x1080
desktop capture, and rescaling it to the pitch the private reader was written
for -- and the output discipline `#108 (Amiga Curse asks its code wheel, so
the title cannot be driven unattended)` set: `answered` or `no challenge on
screen`, and never either side of the exchange.
"""

from __future__ import annotations

import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import amigabladesjournal as journal  # noqa: E402


def _stripes(path: pathlib.Path, rows: list[int], *,
             x0: float = 58, y0: float = 59, pitch: int = 16,
             size: tuple[int, int] = (1920, 1080),
             left: int = journal.LEFT_MARGIN, width: int = 16,
             colour: tuple[int, int, int] = journal.GREEN) -> pathlib.Path:
    """A capture with one solid stripe on each of `rows`, on that grid.

    The stripes stand in for text lines: they are as tall as a character cell
    and they start at the same column the game's own lines do, which is all
    `fit_grid` reads.  Everything else on the frame is black.
    """
    #: Guarded, not imported: CI installs no Pillow, and an
    #: unguarded import fails the test where it should skip it.
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", size, (0, 0, 0))
    pixels = image.load()
    for row in rows:
        top = int(y0 + row * pitch)
        for y in range(top, top + pitch - 2):
            for x in range(int(x0 + left * pitch),
                           int(x0 + (left + width) * pitch)):
                pixels[x, y] = colour
    image.save(path)
    return path


def test_the_pitch_comes_from_the_closest_pair_of_lines():
    # A rule-book challenge is four lines on rows 2, 4, 6 and 8, so every gap
    # is two rows; a journal one is three lines and the same. What must not
    # happen is the first pair being taken on faith -- an extra blank line
    # anywhere would then double the pitch and every column index with it.
    bands = [(91, 104, 122, 375), (187, 200, 122, 455), (219, 232, 122, 423)]
    x0, y0, pitch = journal.fit_grid(bands)
    assert pitch == 16
    assert (x0, y0) == (122 - journal.LEFT_MARGIN * 16, 91 - 2 * 16)


def test_the_origin_is_the_leftmost_ink_on_the_whole_screen():
    # Glyphs sit differently inside their cells -- a bracket is inset where a
    # W fills the cell -- so the leftmost ink of any line is the one that
    # names the margin, not the leftmost ink of the first line.
    bands = [(91, 104, 130, 375), (123, 136, 122, 455), (155, 168, 126, 423)]
    x0, _, pitch = journal.fit_grid(bands)
    assert x0 == 122 - journal.LEFT_MARGIN * pitch


def test_too_few_lines_is_not_a_challenge():
    # The version screen has two lines of green text and no challenge on it.
    assert journal.fit_grid([(91, 104, 122, 375), (107, 120, 122, 455)]) is None
    assert journal.fit_grid([]) is None


def test_a_stripe_frame_gives_back_the_grid_it_was_drawn_on(tmp_path):
    PIL_Image = pytest.importorskip("PIL.Image")
    path = _stripes(tmp_path / "grid.png", [2, 4, 6])
    x0, y0, pitch = journal.fit_grid(journal.text_bands(PIL_Image.open(path)))
    assert (x0, y0, pitch) == (58, 59, 16)


def test_a_colour_the_game_does_not_draw_text_in_is_not_ink(tmp_path):
    # The input bar's echo is yellow and the party roster is cyan; only the
    # body colour counts, or a menu would fit a grid and be read as a prompt.
    PIL_Image = pytest.importorskip("PIL.Image")
    path = _stripes(tmp_path / "yellow.png", [2, 4, 6], colour=(255, 238, 85))
    assert journal.text_bands(PIL_Image.open(path)) == []


def test_rows_closer_than_the_band_gap_are_one_line(tmp_path):
    PIL_Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "gap.png"
    # Rows 20-25 and 29-35, three blank rows between them -- a hole inside a
    # glyph, not a blank line -- and a third band a whole cell away.
    #: Guarded, not imported: CI installs no Pillow, and an
    #: unguarded import fails the test where it should skip it.
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (400, 200), (0, 0, 0))
    pixels = image.load()
    for band in ((20, 26), (29, 36), (80, 86)):
        for y in range(*band):
            for x in range(100, 200):
                pixels[x, y] = journal.GREEN
    image.save(path)
    bands = journal.text_bands(PIL_Image.open(path))
    assert [(band[0], band[1]) for band in bands] == [(20, 35), (80, 85)]


def test_a_capture_is_rescaled_to_the_pitch_the_reader_asks_for(tmp_path):
    # `winvm shot` of WinUAE's 720-wide window puts the game's 8x8 character
    # cell at 16 pixels of a 1920x1080 desktop; the private reader was written
    # against FS-UAE, where the same cell is 30.64. Handing it the capture
    # unchanged is what made it read nothing at all.
    PIL_Image = pytest.importorskip("PIL.Image")
    source = _stripes(tmp_path / "src.png", [2, 4, 6])
    scaled = tmp_path / "out.png"
    x0, y0, pitch = journal.to_reader_scale(source, scaled, target_pitch=30.64)
    assert pitch == pytest.approx(30.64)
    # The origin comes back in the cut-out's own coordinates, and the cut-out
    # starts one cell above and left of it.
    assert x0 == pytest.approx(30.64, abs=1.0)
    assert y0 == pytest.approx(30.64, abs=1.0)
    # 42 cells wide and 27 tall, which is the 40x25 display plus the margin.
    assert PIL_Image.open(scaled).size[0] == pytest.approx(42 * 30.64, abs=40)


def test_a_frame_with_no_grid_on_it_is_rescaled_into_nothing(tmp_path):
    #: Guarded, not imported: CI installs no Pillow, and an
    #: unguarded import fails the test where it should skip it.
    Image = pytest.importorskip("PIL.Image")
    source = tmp_path / "blank.png"
    Image.new("RGB", (1920, 1080), (0, 0, 0)).save(source)
    assert journal.to_reader_scale(source, tmp_path / "unused.png",
                                   target_pitch=30.64) is None


def test_the_environment_names_the_repository_and_has_a_default(monkeypatch):
    monkeypatch.setenv(journal.ENV, "/somewhere/else")
    assert journal.wheel_repo() == pathlib.Path("/somewhere/else")
    monkeypatch.delenv(journal.ENV, raising=False)
    assert journal.wheel_repo().name == "goldbox-codewheel"


def test_a_machine_without_the_repository_is_told_where_it_looked(monkeypatch,
                                                                  tmp_path):
    monkeypatch.setenv(journal.ENV, str(tmp_path / "nothing"))
    with pytest.raises(SystemExit) as raised:
        journal._blades_modules()
    assert "nothing" in str(raised.value)
    assert journal.ENV in str(raised.value)


def test_a_disk_that_is_not_there_is_named(tmp_path):
    with pytest.raises(SystemExit) as raised:
        journal.find_disk(str(tmp_path / "no-such.adf"))
    assert "no-such.adf" in str(raised.value)


class _Screen:
    """Stands in for the private repository's reader."""

    X0 = Y0 = 0.0
    PITCH = 30.64

    def __init__(self, challenge):
        self._challenge = challenge

    def read_challenge(self, path):
        if self._challenge is None:
            raise ValueError("no challenge on this screen")
        return self._challenge


class _Tables:
    """Stands in for the private repository's table matcher."""

    def __init__(self, word):
        self._word = word

    def answer_for(self, challenge, table):
        if self._word is None:
            raise ValueError(f"challenge {challenge!r} matched 0 records")
        return types.SimpleNamespace(answer=self._word)


def _wire(monkeypatch, tmp_path, challenge, word):
    """`answer()` with the private repository and the emulator replaced."""
    screen, tables = _Screen(challenge), _Tables(word)
    monkeypatch.setattr(journal, "_blades_modules", lambda: (screen, tables))
    monkeypatch.setattr(journal, "tables", lambda adf: [])
    monkeypatch.setattr(journal, "to_reader_scale",
                        lambda shot, out, target_pitch=None:
                        None if challenge is None else (1.0, 2.0, 30.64))

    def _no_emulator(*args, **kwargs):
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(journal.subprocess, "run", _no_emulator)
    pressed: list[str] = []
    monkeypatch.setattr(journal.amigadrive, "press",
                        lambda holder, name, settle: pressed.append(name))
    return pressed


def test_a_screen_with_no_prompt_on_it_presses_nothing_and_says_so(
        monkeypatch, tmp_path, capsys):
    pressed = _wire(monkeypatch, tmp_path, None, None)
    assert journal.answer("holder", 0.0, tmp_path / "disk.adf") is False
    assert capsys.readouterr().out == "no challenge on screen\n"
    assert pressed == []


def test_the_word_is_typed_and_the_only_thing_printed_is_that_it_was(
        monkeypatch, tmp_path, capsys):
    # `TESTWORD` is not an answer to anything; it is here to be counted.
    pressed = _wire(monkeypatch, tmp_path, {"kind": "journal"}, "TESTWORD")
    assert journal.answer("holder", 0.0, tmp_path / "disk.adf") is True
    assert capsys.readouterr().out == "answered\n"
    assert pressed == list("TESTWORD") + ["RET"]


def test_a_challenge_the_tables_do_not_hold_is_reported_without_quoting_it(
        monkeypatch, tmp_path, capsys):
    # The matcher's own ValueError quotes the challenge in its message, and
    # `#108`'s ruling is that neither side of the exchange reaches this
    # repository -- an exception string included.
    challenge = {"kind": "journal", "word": 1, "entry": 40, "page": 35}
    pressed = _wire(monkeypatch, tmp_path, challenge, None)
    with pytest.raises(SystemExit) as raised:
        journal.answer("holder", 0.0, tmp_path / "disk.adf")
    assert "not in this disk's tables" in str(raised.value)
    for leak in ("40", "35", "entry", "word"):
        assert leak not in str(raised.value)
    assert pressed == []
