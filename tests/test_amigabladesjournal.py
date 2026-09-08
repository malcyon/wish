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


def test_a_capture_is_rescaled_near_the_pitch_the_reader_asks_for(tmp_path):
    # `winvm shot` of WinUAE's 720-wide window puts the game's 8x8 character
    # cell at 16 pixels of a 1920x1080 desktop; the private reader was written
    # against FS-UAE, where the same cell is 30.64. Handing it the capture
    # unchanged is what made it read nothing at all.
    #
    # It is handed 32 rather than 30.64 -- the nearest whole number of pixels
    # per Amiga pixel, which is what `test_a_one_pixel_gap_is_the_same_width_
    # wherever_it_lands` is about -- so the geometry it is told to use is the
    # geometry that comes back here, and never its own.
    PIL_Image = pytest.importorskip("PIL.Image")
    source = _stripes(tmp_path / "src.png", [2, 4, 6])
    scaled = tmp_path / "out.png"
    x0, y0, pitch = journal.to_reader_scale(source, scaled, target_pitch=30.64)
    assert pitch == 32.0
    assert pitch % 8 == 0
    assert abs(pitch - 30.64) < 8
    # The origin comes back in the cut-out's own coordinates, and the cut-out
    # starts one cell above and left of it.
    assert (x0, y0) == (32.0, 32.0)
    # 42 cells wide and 27 tall, which is the 40x25 display plus the margin.
    assert PIL_Image.open(scaled).size == (42 * 32, 27 * 32)


def test_the_reader_is_handed_a_whole_number_of_pixels_per_amiga_pixel():
    # #371. The reader declares 30.64, which is 3.83 capture pixels for each
    # of the 8 pixels in a character cell, so building its image at that pitch
    # replicates some of the game's own pixels four times and others three.
    assert journal.reader_pitch(30.64) == 32.0
    for declared in (16.0, 24.0, 30.64, 31.9, 33.0, 40.0, 8.0, 3.0):
        pitch = journal.reader_pitch(declared)
        assert pitch % 8 == 0, declared
        assert pitch >= 8, declared
        # Never further from what the reader asked for than half a cell.
        assert abs(pitch - declared) <= 4 or declared < 8, declared


def test_a_one_pixel_gap_is_the_same_width_wherever_it_lands(tmp_path):
    """#371, as a property rather than as the digit it was found on.

    Every glyph in the game's font is drawn with one-pixel gaps, and the `6`
    that prompted the issue differs from the `8` by one of them.  What the
    reader has to be given is an image where every one of those gaps is the
    same width, because it normalises a cell to 8x8 by the ink's own bounding
    box: a gap that comes out three pixels wide beside one that comes out
    four does not survive that, and a closed gap in that place is a different
    digit.

    So this draws a comb -- alternate Amiga pixels inked, right across a
    character cell -- and measures the runs in what comes back.  A whole
    number of pixels per Amiga pixel makes them all equal; the fractional
    replication that shipped before makes them 3 and 4 mixed, which is
    asserted below on the same canvas so the test says what it is testing.
    """
    Image = pytest.importorskip("PIL.Image")
    x0, y0, pitch, row, col = 58.0, 59.0, 16, 6, journal.LEFT_MARGIN + 8
    image = Image.new("RGB", (1920, 1080), (0, 0, 0))
    pixels = image.load()
    for line_row in (2, 4):                     # anchors, for `fit_grid`
        top = int(y0 + line_row * pitch)
        for y in range(top, top + pitch - 2):
            for x in range(int(x0 + journal.LEFT_MARGIN * pitch),
                           int(x0 + (journal.LEFT_MARGIN + 16) * pitch)):
                pixels[x, y] = journal.GREEN
    amiga_px = pitch // 8
    top = int(y0 + row * pitch)
    # The comb: every other Amiga pixel, across sixteen character cells. One
    # cell is not enough -- a fractional replication repeats with a period far
    # wider than a cell, so a single cell can land inside a stretch where the
    # rounding happens to be even, and did while this test was being written.
    for k in range(0, 16 * 8, 2):
        left = int(x0 + col * pitch) + k * amiga_px
        for y in range(top, top + pitch):
            for x in range(left, left + amiga_px):
                pixels[x, y] = journal.GREEN
    source = tmp_path / "comb.png"
    image.save(source)

    scaled = tmp_path / "comb-out.png"
    _, _, out_pitch = journal.to_reader_scale(source, scaled, target_pitch=30.64)
    runs = _runs(Image.open(scaled), int(journal.MARGIN * out_pitch
                                         + row * out_pitch + out_pitch / 2))
    assert set(runs) == {out_pitch / 8}, runs

    # The replication that shipped before: the same samples, scaled by the
    # reader's own fractional pitch. Kept here rather than restored in the
    # tool, so this stays a test after the fix is in place. The whole-number
    # image above is recovered to one pixel per Amiga pixel first -- exactly,
    # since every Amiga pixel in it is a uniform 4x4 block -- so both arms
    # start from the same samples and differ only in how they are replicated.
    canonical = Image.open(scaled).resize((42 * 8, 27 * 8), Image.NEAREST)
    factor = 30.64 / 8
    before = _runs(canonical.resize((round(42 * 8 * factor),
                                     round(27 * 8 * factor)), Image.NEAREST),
                   int(30.64 + row * 30.64 + 30.64 / 2))
    assert len(set(before)) > 1, before


def _runs(image, y):
    """The lengths of the inked runs on row `y` of `image`."""
    mask = journal._ink_mask(image)
    row = [mask.getpixel((x, y)) for x in range(mask.size[0])]
    out, run = [], 0
    for value in row:
        if value:
            run += 1
        elif run:
            out.append(run)
            run = 0
    if run:
        out.append(run)
    return out


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


# `#371 (The Silver Blades journal reader misreads a 6 as an 8, so a boot is
# spent on a question the disk can answer)`.  The game's own font is the
# game's own art and stays out of this repository; the ten shapes below are
# invented for these tests alone, plain enough to be read at a glance and
# distinct enough from each other that a resample which blurs one stroke
# into the next would be caught, without needing the actual glyph that
# prompted the issue.
_DIGIT_FONT = {
    "0": ["..####..", ".#....#.", "#......#", "#......#",
          "#......#", "#......#", ".#....#.", "..####.."],
    "1": ["...##...", "..###...", "...##...", "...##...",
          "...##...", "...##...", "...##...", "..####.."],
    "2": [".####...", "#....#..", ".....#..", "....#...",
          "...#....", "..#.....", ".#......", "######.."],
    "3": [".####...", "#....#..", ".....#..", "..###...",
          ".....#..", "#....#..", ".####...", "........"],
    "4": ["....#...", "...##...", "..#.#...", ".#..#...",
          "######..", "....#...", "....#...", "........"],
    "5": ["######..", "#.......", "#####...", ".....#..",
          ".....#..", "#....#..", ".####...", "........"],
    "6": ["..###...", ".#......", "#.......", "#.###...",
          "##...#..", "#....#..", ".#####..", "........"],
    "7": ["######..", ".....#..", "....#...", "...#....",
          "..#.....", ".#......", ".#......", "........"],
    "8": [".#####..", "#.....#.", "#.....#.", ".#####..",
          "#.....#.", "#.....#.", ".#####..", "........"],
    "9": [".#####..", "#.....#.", "#.....#.", ".######.",
          ".....#..", "....#...", "..###...", "........"],
}


def _glyph_frame(path, bitmap, *, x0=58.0, y0=59.0, pitch=16.0,
                 size=(1920, 1080), row=6, col=None):
    """A capture like `_stripes()`'s, with one rendered digit on a third line.

    Two solid lines anchor `fit_grid`'s pitch and origin the same way
    `_stripes()` does; the third carries `bitmap`, drawn at sixteen times the
    cell's own resolution and blended down with `Image.BILINEAR` -- a real
    `winvm shot` capture is a scaled copy of the game's framebuffer, not a
    clean block of doubled pixels, and #371's defect only shows up once a
    stroke's edge is soft and the grid's own origin lands off a whole pixel
    of the capture, which is what `to_reader_scale`'s crop used to truncate
    away.
    """
    Image = pytest.importorskip("PIL.Image")
    col = journal.LEFT_MARGIN if col is None else col
    image = Image.new("RGB", size, (0, 0, 0))
    pixels = image.load()
    for line_row in (2, 4):
        top = int(y0 + line_row * pitch)
        for y in range(top, top + int(pitch) - 2):
            for x in range(int(x0 + journal.LEFT_MARGIN * pitch),
                           int(x0 + (journal.LEFT_MARGIN + 16) * pitch)):
                pixels[x, y] = journal.GREEN
    sub = 16
    hi = Image.new("RGB", (8 * sub, 8 * sub), (0, 0, 0))
    hi_px = hi.load()
    for j, line in enumerate(bitmap):
        for k, ch in enumerate(line):
            if ch != "#":
                continue
            for dy in range(sub):
                for dx in range(sub):
                    hi_px[k * sub + dx, j * sub + dy] = journal.GREEN
    amiga_px = pitch / 8.0
    small = hi.resize((round(8 * amiga_px), round(8 * amiga_px)),
                      Image.BILINEAR)
    left, top = x0 + col * pitch, y0 + row * pitch
    ix, iy = int(left), int(top)
    fx, fy = left - ix, top - iy
    if fx or fy:
        small = small.transform(small.size, Image.AFFINE,
                                (1, 0, -fx, 0, 1, -fy), resample=Image.BILINEAR)
    image.paste(small, (ix, iy))
    image.save(path)
    return path


def _read_cell(image, row, col, x0, y0, pitch):
    """Mirrors the private reader's own `cell()`: crop to ink, resize to 8x8.

    Reimplemented here from the algorithm `screen.py`'s module docstring and
    functions describe -- window margins, a crop to the ink's own bounding
    box, a resize to 8x8, a threshold at 110 -- and not by calling into the
    private repository, so this file's own claim of never touching it at
    test time stays true.
    """
    PILImage = pytest.importorskip("PIL.Image")
    y, x = round(y0 + row * pitch), round(x0 + col * pitch)
    box = image.crop((x + 3, max(0, y - 3),
                      x + round(pitch) - 1, y + round(pitch) + 3))
    mask = journal._ink_mask(box)
    bbox = mask.getbbox()
    if bbox is None:
        return [[0] * 8 for _ in range(8)]
    crop = mask.crop(bbox).resize((8, 8), PILImage.BILINEAR)
    return [[1 if crop.getpixel((cx, cy)) > 110 else 0 for cx in range(8)]
            for cy in range(8)]


def _l1(a, b):
    return sum(abs(a[j][k] - b[j][k]) for j in range(8) for k in range(8))


def _clean_template(tmp_path, digit, bitmap):
    """`bitmap`, normalised by the same crop-and-resize `_read_cell` applies.

    Drawn at a pitch divisible by 8 -- an exact 4 capture pixels per Amiga
    pixel -- so nothing here needs a resample to get it there, and the
    result is what a perfect read of that digit looks like.
    """
    PILImage = pytest.importorskip("PIL.Image")
    path = _glyph_frame(tmp_path / f"tmpl-{digit}.png", bitmap, pitch=32.0)
    image = PILImage.open(path).convert("RGB")
    return _read_cell(image, 6, journal.LEFT_MARGIN, 58.0, 59.0, 32.0)


def test_every_digit_reads_back_as_itself(tmp_path):
    # #371's own account: `winvm shot` puts 16 native pixels behind every
    # character cell, and a real desktop window can start at any of them --
    # so four sub-pixel origins, one on a whole pixel and three off it by a
    # different fraction, stand in for the phases a real capture can land
    # on.  40 renders checked (4 origins x the 10 digits 0-9), all synthetic:
    # no disk and no emulator are needed for this one.
    pytest.importorskip("PIL.Image")
    templates = {digit: _clean_template(tmp_path, digit, bitmap)
                for digit, bitmap in _DIGIT_FONT.items()}
    checked = 0
    for x0 in (58.0, 58.25, 58.5, 58.75):
        for digit, bitmap in _DIGIT_FONT.items():
            src = _glyph_frame(tmp_path / f"{digit}-{x0}.png", bitmap, x0=x0)
            out = tmp_path / f"{digit}-{x0}-out.png"
            geometry = journal.to_reader_scale(src, out, target_pitch=30.64)
            assert geometry is not None
            PILImage = pytest.importorskip("PIL.Image")
            got = _read_cell(PILImage.open(out).convert("RGB"), 6,
                             journal.LEFT_MARGIN, *geometry)
            best = min(templates, key=lambda k: _l1(got, templates[k]))
            assert best == digit, f"{digit!r} at x0={x0} read back as {best!r}"
            checked += 1
    assert checked == 40


def test_the_old_whole_crop_rescale_lost_a_digit_the_fix_keeps(tmp_path):
    """#371's own mechanism, reproduced without the game's font.

    Not literally the 6-and-8 pair the issue names -- that font is the
    game's own and stays out of this repository -- but the same defect on a
    digit of this file's own invented font: `3`, drawn with a soft
    (antialiased) edge at a sub-pixel origin, reads as `0` under the old
    whole-crop `Image.resize(..., Image.NEAREST)`, because the crop's own
    left edge truncated that origin to a whole pixel first.  Sampling each
    Amiga pixel's own centre out of the untouched capture, as
    `to_reader_scale` does now, reads it correctly at the same origin.
    """
    PILImage = pytest.importorskip("PIL.Image")
    templates = {digit: _clean_template(tmp_path, digit, bitmap)
                for digit, bitmap in _DIGIT_FONT.items()}
    src = _glyph_frame(tmp_path / "three.png", _DIGIT_FONT["3"], x0=58.5)

    out = tmp_path / "fixed.png"
    geometry = journal.to_reader_scale(src, out, target_pitch=30.64)
    got = _read_cell(PILImage.open(out).convert("RGB"), 6,
                     journal.LEFT_MARGIN, *geometry)
    assert min(templates, key=lambda k: _l1(got, templates[k])) == "3"

    # The old algorithm, kept here rather than restored in the tool, so this
    # regression test still runs after #371's fix is in place.
    image = PILImage.open(src).convert("RGB")
    x0, y0, pitch = journal.fit_grid(journal.text_bands(image))
    left = max(0, int(x0 - journal.MARGIN * pitch))
    top = max(0, int(y0 - journal.MARGIN * pitch))
    crop = image.crop((
        left, top,
        int(x0 + (journal.COLUMNS + journal.MARGIN) * pitch),
        int(y0 + (journal.LINES + journal.MARGIN) * pitch)))
    factor = 30.64 / pitch
    crop = crop.resize((round(crop.width * factor), round(crop.height * factor)),
                       PILImage.NEAREST)
    old_geometry = (x0 - left) * factor, (y0 - top) * factor, pitch * factor
    got_old = _read_cell(crop, 6, journal.LEFT_MARGIN, *old_geometry)
    assert min(templates, key=lambda k: _l1(got_old, templates[k])) == "0"
