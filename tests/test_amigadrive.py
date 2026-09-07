"""`tools/amigadrive.py`'s key table, and the two settings a party walks on.

No VM and no emulator: the `winvm` call is replaced, so what is under test is
the command line the driver would have sent.  Both tests here guard something
that failed silently for a fortnight -- a key that was pressed, reported `ok`,
and reached nothing.  `#361 (An Amiga party cannot be made to walk, because
the WinUAE driver sends only keystrokes)` has the run.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import amigadrive  # noqa: E402

#: The WinUAE machine the Amiga titles boot on.
CONFIG = pathlib.Path(__file__).resolve().parent.parent / "tools" / "goldbox-a500.uae"


@pytest.fixture
def sent(monkeypatch):
    """Collect the `winvm ssh` command lines `press` would have run."""
    lines: list[str] = []

    def _winvm(*args, timeout=180):
        lines.append(args[-1])
        return "ok pressed"

    monkeypatch.setattr(amigadrive, "_winvm", _winvm)
    monkeypatch.setattr(amigadrive.time, "sleep", lambda _s: None)
    return lines


def test_the_cursor_keys_go_in_extended(sent):
    """Without the flag `UP` is keypad 8, not the cursor key.

    `keybd_event` derives a scancode from the virtual key and does not add the
    `E0` prefix unless asked, so `VK_UP` arrives at WinUAE as `0x48` --
    `DIK_NUMPAD8`.  Drop `-Extended` and the driver has no way to press a
    cursor key at all, and says nothing about it.
    """
    for name in ("UP", "DOWN", "LEFT", "RIGHT"):
        amigadrive.press("holder", name, 0)
    assert all(" -Extended " in line for line in sent), sent


def test_the_keypad_goes_in_unextended(sent):
    """The keypad is what moves a party, and it is not an extended key."""
    amigadrive.press("holder", "NP8", 0)
    assert "key 68 " in sent[0], sent
    assert "-Extended" not in sent[0], sent


def test_every_keypad_digit_is_its_own_key():
    """`NP0`-`NP9` are `VK_NUMPAD0`-`VK_NUMPAD9`, in order and distinct."""
    codes = [amigadrive.KEYS[f"NP{d}"] for d in range(10)]
    assert codes == list(range(0x60, 0x6A))


def test_the_machine_leaves_amiga_port_two_empty():
    """A port set to a keyboard layout eats the keys the party walks on.

    WinUAE's own default is `kbd1` in Amiga port 2, which is Keyboard Layout A,
    which takes `DIK_NUMPAD4`, `6`, `8`, `2`, `0`, `5`, `DECIMAL` and
    `NUMPADENTER` for a joystick.  Twenty keys were pressed into that and
    reported as a finding about the game.
    """
    lines = CONFIG.read_text().splitlines()
    assert "joyport1=none" in lines, "Amiga port 2 must hold nothing"


def test_the_machine_emulates_the_audio_interrupts():
    """`sound_output=none` is "no Paula", and it deadlocks Silver Blades.

    Measured: the party's second turn writes the new facing and never redraws,
    and the game's process then waits for a signal nothing sends.
    `interrupts` makes no host sound and does not do that.
    """
    lines = CONFIG.read_text().splitlines()
    assert "sound_output=interrupts" in lines
    assert "sound_output=none" not in lines
