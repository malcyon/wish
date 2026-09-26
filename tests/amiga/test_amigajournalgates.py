"""The Silver Blades journal gates: the reader preflight and the client crop before the grid fit.

Everything here is synthetic: a fake reader module and built desktops, no game pixels and no private files.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import amigabladesjournal as journal  # noqa: E402
from tools.amiga import amigasecretsave as drive  # noqa: E402
from tools.amiga import amigashots  # noqa: E402

AT = (137, 43)
TOPS = (48, 80, 112)


def _reader(tmp_path, monkeypatch, body):
    """A fake reader tree; the numpy/PIL import check is answered, the reader check really runs.

    The venv may carry neither numpy nor Pillow, and the reader check does not need them.
    """
    real = subprocess.run

    def run(argv, **kw):
        if argv[2:] == ["import numpy, PIL"]:
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        return real(argv, **kw)

    monkeypatch.setattr(drive.subprocess, "run", run)
    analysis = tmp_path / "ssb" / "analysis"
    analysis.mkdir(parents=True)
    (analysis / "amiga_tables.py").write_text("")
    (analysis / "screen.py").write_text(body)
    monkeypatch.setenv(journal.ENV, str(tmp_path))


@pytest.mark.parametrize("body", ["def load_digits():\n    return object()\n"])
def test_a_reader_that_loads_its_template_passes_silently(tmp_path, monkeypatch, body, capfd):
    _reader(tmp_path, monkeypatch, body)
    drive.journal_preflight(sys.executable)
    assert "ok" not in capfd.readouterr().out


@pytest.mark.parametrize("raises, name, text", [
    ("FileNotFoundError('no template')", "FileNotFoundError", "no template"),
    ("ValueError('malformed')", "ValueError", "malformed"),
])
def test_a_reader_that_cannot_load_its_template_is_refused_by_name(
        tmp_path, monkeypatch, raises, name, text):
    _reader(tmp_path, monkeypatch, f"def load_digits():\n    raise {raises}\n")
    with pytest.raises(drive.RouteError) as error:
        drive.journal_preflight(sys.executable)
    assert name in str(error.value) and text in str(error.value)
    assert len(str(error.value)) < 200 + drive.STDERR_LINES * (drive.STDERR_LINE_CHARS + 3)


def test_a_long_failure_is_bounded(tmp_path, monkeypatch):
    _reader(tmp_path, monkeypatch, "def load_digits():\n    raise ValueError('x' * 5000)\n")
    with pytest.raises(drive.RouteError) as error:
        drive.journal_preflight(sys.executable)
    assert len(str(error.value)) < 200 + drive.STDERR_LINES * (drive.STDERR_LINE_CHARS + 3)


def test_the_reader_check_is_not_reached_without_the_directory(tmp_path, monkeypatch):
    monkeypatch.setenv(journal.ENV, str(tmp_path))
    ran = []
    monkeypatch.setattr(drive.subprocess, "run",
                        lambda argv, **kw: ran.append(argv) or subprocess.CompletedProcess(argv, 0, b"", b""))
    with pytest.raises(drive.RouteError, match="not a directory"):
        drive.journal_preflight("py")
    assert ran == [["py", "-c", "import numpy, PIL"]]


def _desktop(tmp_path, extra=(), name="d.png", crop=False):
    Image = pytest.importorskip("PIL.Image")
    width, height = amigashots.CLIENT
    image = Image.new("RGB", (1920, 1080), (31, 98, 176))
    client = Image.new("RGB", (width, height), (0, 0, 34))
    for top in TOPS:
        client.paste(Image.new("RGB", (200, 12), journal.GREEN), (64, top))
    image.paste(client, AT)
    image.paste(Image.new("RGB", (width, 1), (215, 215, 215)), (AT[0], AT[1] + height))
    image.paste(Image.new("RGB", (width, 22), amigashots.STATUS_GREY), (AT[0], AT[1] + height + 1))
    for row in extra:
        image.paste(Image.new("RGB", (300, 4), journal.GREEN), (600, row))
    if crop:
        image = client
    path = tmp_path / name
    image.save(path)
    return path


def _scale(shot, out):
    grid = journal.to_reader_scale(shot, out, target_pitch=30.64)
    return grid, out.read_bytes()


def test_green_rows_outside_the_window_do_not_change_the_grid(tmp_path):
    clean = _scale(_desktop(tmp_path), tmp_path / "clean.png")
    dirty = _scale(_desktop(tmp_path, extra=(734, 752), name="dirty.png"), tmp_path / "dirty-out.png")
    assert clean[0] == (32.0, 32.0, 32.0)
    assert dirty == clean


def test_the_uncropped_fit_would_have_chosen_the_wrong_pitch(tmp_path):
    from PIL import Image

    image = Image.open(_desktop(tmp_path, extra=(734, 752), name="wrong.png"))
    assert journal.fit_grid(journal.text_bands(image))[2] == 9.0


def test_a_client_size_grab_still_works(tmp_path):
    clean = _scale(_desktop(tmp_path), tmp_path / "clean.png")
    small = _scale(_desktop(tmp_path, name="c.png", crop=True), tmp_path / "small.png")
    assert small == clean


def _bands_on(size, tops=(91, 123, 155), left=200):
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", size, (0, 0, 34))
    for top in tops:
        image.paste(Image.new("RGB", (200, 12), journal.GREEN), (left, top))
    return image


def _whole_image_result(image, tmp_path, name):
    """What fitting the untouched image gives, computed without `_client_of`."""
    shot = tmp_path / f"{name}.png"
    image.save(shot)
    return _scale(shot, tmp_path / f"{name}-out.png")


def test_a_desktop_with_no_window_is_fitted_whole(tmp_path, monkeypatch):
    image = _bands_on((1024, 768))
    with monkeypatch.context() as old:
        old.setattr(journal, "_client_of", lambda im: im)
        expected = _whole_image_result(image, tmp_path, "whole")
    assert expected[0] is not None
    assert _whole_image_result(image, tmp_path, "again") == expected


def test_a_desktop_with_no_window_is_not_refused_by_the_crop(tmp_path):
    image = _bands_on((1024, 768))
    grid, _ = _whole_image_result(image, tmp_path, "nowindow")
    assert grid == (32.0, 32.0, 32.0)


def test_a_window_partly_off_screen_is_never_padded(tmp_path, monkeypatch):
    image = _bands_on((1024, 768))
    expected = _whole_image_result(image, tmp_path, "whole")
    for offset in ((-10, 20), (20, -10)):
        monkeypatch.setattr(amigashots, "find_client", lambda im, offset=offset: offset)
        assert _whole_image_result(image, tmp_path, "off") == expected
    monkeypatch.setattr(amigashots, "find_client", lambda im: (400, 400))
    assert _whole_image_result(image, tmp_path, "past") == expected


def _fake_reader_stdout(monkeypatch, tmp_path, stdout):
    (tmp_path / "ssb" / "analysis").mkdir(parents=True)
    monkeypatch.setenv(journal.ENV, str(tmp_path))

    def run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, "" if argv[2] == "import numpy, PIL" else stdout, "")

    monkeypatch.setattr(drive.subprocess, "run", run)


def test_exit_zero_with_an_error_and_no_ok_is_refused(tmp_path, monkeypatch):
    _fake_reader_stdout(monkeypatch, tmp_path, "template missing\n")
    with pytest.raises(drive.RouteError, match="no ok line"):
        drive.journal_preflight("py")


def test_noise_before_the_last_ok_line_passes(tmp_path, monkeypatch):
    _fake_reader_stdout(monkeypatch, tmp_path, "chatter on import\n\nok\n\n")
    drive.journal_preflight("py")


def test_ok_that_is_not_the_last_line_is_refused(tmp_path, monkeypatch):
    _fake_reader_stdout(monkeypatch, tmp_path, "ok\nerror\n")
    with pytest.raises(drive.RouteError, match="no ok line"):
        drive.journal_preflight("py")
