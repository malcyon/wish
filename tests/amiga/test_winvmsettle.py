"""`tools/amiga/winvmsettle.py`, which waits for the guest's screen to hold still.

No VM and no emulator: `winvm shot` is replaced by a function that writes
whatever bytes the test wants next, so the thing under test is the only thing
being tested -- when it decides a screen has settled, what it keeps when it
never does, and what it says when there is no screen at all.
"""

from __future__ import annotations

import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import winvmsettle  # noqa: E402


def _grabs(monkeypatch, frames: list[bytes] | None, returncode: int = 0,
           stderr: str = ""):
    """Make `winvm shot` hand back `frames` in order.  Returns the call log.

    `None` means a screen that never repeats itself, however long it is
    watched -- an animation, which is what `--limit` exists for.
    """
    calls: list[str] = []

    def _run(args, **kwargs):
        calls.append(args[-1])
        if returncode == 0:
            grab = (str(len(calls)).encode() if frames is None
                    else frames[min(len(calls) - 1, len(frames) - 1)])
            pathlib.Path(args[-1]).write_bytes(grab)
        return types.SimpleNamespace(returncode=returncode, stdout="",
                                     stderr=stderr)

    monkeypatch.setattr(winvmsettle.subprocess, "run", _run)
    return calls


def test_two_identical_grabs_are_what_settles_it(monkeypatch, tmp_path, capsys):
    # Three different frames and then a repeat: a screen still painting must
    # not be photographed, which is the whole reason this exists.
    calls = _grabs(monkeypatch, [b"one", b"two", b"three", b"three"])
    out = tmp_path / "shot.png"
    assert winvmsettle.settle(out, limit=30, interval=0) is True
    assert out.read_bytes() == b"three"
    assert len(calls) == 4
    assert capsys.readouterr().out.startswith("settled after ")


def test_a_screen_that_never_holds_still_keeps_the_last_grab(monkeypatch,
                                                             tmp_path, capsys):
    # An animation runs for as long as the emulator is up, so giving up has to
    # leave a photograph rather than nothing -- a demo loop is still evidence.
    _grabs(monkeypatch, None)
    out = tmp_path / "shot.png"
    assert winvmsettle.settle(out, limit=0.05, interval=0) is False
    assert out.exists()
    assert "not settled" in capsys.readouterr().out


def test_the_working_file_is_gone_either_way(monkeypatch, tmp_path):
    _grabs(monkeypatch, [b"same", b"same"])
    out = tmp_path / "shot.png"
    winvmsettle.settle(out, limit=30, interval=0)
    assert list(tmp_path.iterdir()) == [out]


def test_a_vm_that_is_not_running_is_said_in_the_guests_own_words(
        monkeypatch, tmp_path):
    # The traceback this replaced read as a defect in this file, where the
    # actual message says exactly what is wrong.
    _grabs(monkeypatch, [], returncode=1,
           stderr="error: Requested operation is not valid: "
                  "domain is not running")
    with pytest.raises(SystemExit) as raised:
        winvmsettle.settle(tmp_path / "shot.png", limit=30, interval=0)
    assert "domain is not running" in str(raised.value)


def test_the_directory_is_made_rather_than_demanded(monkeypatch, tmp_path):
    # A run's shots go somewhere that does not exist yet, and
    # failing on that after waiting a minute for the screen is a poor trade.
    _grabs(monkeypatch, [b"same", b"same"])
    out = tmp_path / "run" / "shots" / "shot.png"
    assert winvmsettle.settle(out, limit=30, interval=0) is True
    assert out.exists()


Image = pytest.importorskip("PIL.Image", reason="Pillow reads the grabs")


def _png(clock: int = 0, screen: int = 0) -> bytes:
    """A desktop with WinUAE's status bar under a screen; `clock` is outside it."""
    import io

    from tools.amiga import amigashots

    width, height = amigashots.CLIENT
    image = Image.new("RGB", (1920, 1080), (31, 98, 176))
    image.paste(Image.new("RGB", (width, height), (0, 0, 34 + screen)),
                (137, 43))
    image.paste(Image.new("RGB", (width, 22), amigashots.STATUS_GREY),
                (137, 43 + height + 1))
    image.putpixel((1900, 1070), (clock, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_a_change_outside_the_emulator_screen_still_settles(monkeypatch,
                                                            tmp_path):
    # The taskbar clock ticks while the game holds still.
    _grabs(monkeypatch, [_png(clock=1), _png(clock=2), _png(clock=3)])
    out = tmp_path / "shot.png"
    assert winvmsettle.settle(out, limit=30, interval=0) is True
    assert out.read_bytes() == _png(clock=2)


def test_a_change_inside_the_emulator_screen_never_settles(monkeypatch,
                                                           tmp_path):
    # Two screens alternating: no two consecutive grabs are ever alike.
    _grabs(monkeypatch, [_png(screen=1), _png(screen=2)] * 500)
    assert winvmsettle.settle(tmp_path / "shot.png", limit=0.05,
                              interval=0) is False
