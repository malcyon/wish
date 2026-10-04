"""`WinGuest`'s screenshots and keys go through WinUAE's pipe verbs and never through the desktop.

No VM and no emulator: `_run` is replaced, so what is under test is the command the
guest would have been sent and what is done with the frame it returns.
"""

from __future__ import annotations

import base64
import io
import pathlib

import pytest
from PIL import Image

from tools.amiga import amigadrive, winuaesession

ROOT = pathlib.Path(winuaesession.__file__).resolve().parents[2]


class Guest(winuaesession.WinGuest):
    """A `WinGuest` whose guest calls are recorded and answered from `replies`."""

    def __init__(self, replies=()):
        super().__init__()
        self.sent: list[tuple] = []
        self.replies = list(replies)

    def _run(self, *args, timeout):  # type: ignore[override]
        self.sent.append(args)
        return self.replies.pop(0) if self.replies else "ok"


def _shot(counter=1, size=(752, 574), pid=4242):
    data = io.BytesIO()
    Image.new("RGB", size, (17, 34, 51)).save(data, "PNG")
    return "\n".join([f"ok shot pid={pid} counter={counter:03d} ms=500", "WINVM-SHOT-BEGIN",
                      base64.b64encode(data.getvalue()).decode(), "WINVM-SHOT-END"])


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        now = 1000.0
        slept: list[float] = []

    Clock.slept = []
    monkeypatch.setattr(amigadrive, "_last_counter", {})
    monkeypatch.setattr(winuaesession.time, "monotonic", lambda: Clock.now)

    def sleep(seconds):
        Clock.slept.append(seconds)
        Clock.now += seconds

    monkeypatch.setattr(winuaesession.time, "sleep", sleep)
    return Clock


def test_grab_asks_the_guest_for_a_pipe_shot_and_never_for_a_desktop_grab(tmp_path, clock):
    guest = Guest([_shot(counter=5)])
    guest.holder = "h"
    assert guest.grab("title", tmp_path / "r.png", tmp_path / "c.png", timeout=30) is True
    assert [args[0] for args in guest.sent] == ["ssh"]
    assert guest.sent[0][1].endswith(" shot -Holder h")
    assert Image.open(tmp_path / "c.png").size == (720, 568)
    assert guest.last_shot == {"source": "winuae-pipe", "pid": 4242, "counter": 5}


def test_a_grab_before_any_lane_action_does_not_know_whose_lane_to_shoot(tmp_path, clock):
    with pytest.raises(winuaesession.RouteError, match="no lane holder"):
        Guest().grab("title", tmp_path / "r.png", tmp_path / "c.png", timeout=30)


def test_a_lane_action_teaches_the_guest_its_holder(tmp_path, clock):
    guest = Guest(["ok claimed", _shot()])
    guest.claim("wish282-x", 5)
    guest.grab("title", tmp_path / "r.png", tmp_path / "c.png", timeout=30)
    assert guest.sent[1][1].endswith(" shot -Holder wish282-x")


def test_a_frame_of_any_other_size_is_blocked(tmp_path, clock):
    guest = Guest([_shot(size=(1920, 1080))])
    guest.holder = "h"
    with pytest.raises(winuaesession.RouteError, match="no known way to cut a 1920x1080 frame"):
        guest.grab("title", tmp_path / "r.png", tmp_path / "c.png", timeout=30)


def test_the_guests_failure_line_is_raised_as_a_route_error(tmp_path, clock):
    guest = Guest(["fail DBG sc wrote no file in C:\\x (reply 404, last counter 12)"])
    guest.holder = "h"
    with pytest.raises(winuaesession.RouteError, match="wrote no file"):
        guest.grab("title", tmp_path / "r.png", tmp_path / "c.png", timeout=30)


def test_the_thousandth_shot_fails_with_the_budget_message(tmp_path, clock):
    guest = Guest([_shot(999), "fail DBG sc wrote no file in C:\\x (reply 404, last counter 999)"])
    guest.holder = "h"
    guest.grab("a", tmp_path / "r.png", tmp_path / "c.png", timeout=30)
    with pytest.raises(winuaesession.RouteError, match="written its 999 screenshots"):
        guest.grab("b", tmp_path / "r.png", tmp_path / "c.png", timeout=30)


def test_the_journal_answerers_capture_is_the_same_pipe_shot(tmp_path, clock):
    guest = Guest([_shot()])
    capture, _press = guest.answer_io("h")
    capture(tmp_path / "j.png")
    assert guest.sent[0][1].endswith(" shot -Holder h")
    assert Image.open(tmp_path / "j.png").size == (720, 568)


@pytest.mark.parametrize("key, code", [("RET", "44"), ("ret", "44"), ("UP", "4C"), ("NP8", "3E"),
                                       ("ESC", "45"), ("a", "20")])
def test_a_key_is_sent_as_its_amiga_raw_code_through_the_press_verb(key, code):
    guest = Guest(["ok pressed"])
    guest.press("h", key, 30)
    assert guest.sent[0][1].endswith(f" press {code} -Holder h")


@pytest.mark.parametrize("key", ["F11", "F12", "NOPE"])
def test_a_key_the_pipe_cannot_press_is_blocked(key):
    guest = Guest()
    with pytest.raises(winuaesession.RouteError):
        guest.press("h", key, 30)
    assert guest.sent == []


@pytest.mark.parametrize("name", ["winuaesession", "amigadrive", "amigabladesjournal",
                                  "amigacursewheel", "route", "acceptance", "noencounters",
                                  "amigatarget", "winwish"])
def test_no_run_driver_names_a_desktop_grab_or_the_focus_verbs(name):
    source = (ROOT / "tools" / "amiga" / f"{name}.py").read_text()
    assert '"winvm", "shot"' not in source
    assert '_run("shot"' not in source
    assert "winuae.ps1 key" not in source and "} key " not in source
    assert "-Extended" not in source
    assert "winvmsettle" not in source


def test_a_failed_capture_shot_does_not_recrop_a_frame_left_by_an_earlier_capture(tmp_path, clock):
    raw, cropped = tmp_path / "r.png", tmp_path / "c.png"
    raw.write_bytes(base64.b64decode(_shot().split("\n")[2]))
    guest = Guest(["fail DBG sc wrote no file in C:\\x (reply 404, last counter 1)"])
    guest.holder = "h"
    with pytest.raises(winuaesession.RouteError, match="wrote no file"):
        guest.capture("title", raw, cropped, timeout=30)
    assert not cropped.exists()
