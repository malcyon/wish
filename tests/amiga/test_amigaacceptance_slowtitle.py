"""The title wait of an accept run keeps going while the boot frame changes."""

from __future__ import annotations

from tests.amiga.test_amigaacceptance_accept import MapGuard
from tests.amiga.test_amigaacceptance_title import (
    STATES,
    TitleGuest,
    _run,
    clock,
    make_title,
)

__all__ = ["clock"]  # the fixture that replaces the driver's time and sleep


class CreditsGuest(TitleGuest):
    """Shows a credits page that changes every `page` seconds until the key presses begin."""

    def __init__(self, clock, page):
        super().__init__(clock)
        self.page, self.began = page, clock.now

    def grab(self, state, raw, cropped, timeout=None):
        shown = super().grab(state, raw, cropped, timeout)
        if not self.presses:
            cropped.write_bytes(f"credits {int((self.clock.now - self.began) // self.page)}".encode())
        return shown


def _title_after(clock, seconds):
    return lambda path: clock.now - 1000.0 >= seconds


def test_a_credits_boot_of_400_seconds_reaches_the_title(tmp_path, clock):
    guest = CreditsGuest(clock, page=20)
    guard = MapGuard(states=("title", *STATES), on={"title": _title_after(clock, 400)})
    _, result = _run(tmp_path, clock, title=make_title(title_limit=150.0), guest=guest,
                     guard=guard)
    assert "not recognized" not in result["error"], result["error"]
    assert clock.now - 1000.0 >= 400


def test_a_frozen_boot_frame_fails_after_the_title_limit(tmp_path, clock):
    guard = MapGuard(states=("title", *STATES), on={"title": lambda path: False})
    _, result = _run(tmp_path, clock, title=make_title(title_limit=150.0), guard=guard)
    assert "title screen was not recognized within 150s" in result["error"]
