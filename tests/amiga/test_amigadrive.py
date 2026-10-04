"""`tools/amiga/amigadrive.py`: the keys and screenshots it sends over WinUAE's pipe, and the settings a party walks on.

No VM and no emulator: the `winvm` call is replaced, so what is under test is
the command line the driver would have sent.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import amigadrive  # noqa: E402

#: The WinUAE machine the Amiga titles boot on.
CONFIG = pathlib.Path(__file__).resolve().parents[2] / "tools" / "amiga" / "goldbox-a500.uae"


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


def test_a_key_goes_in_as_its_amiga_raw_code_over_the_pipe_and_never_as_a_virtual_key(sent):
    """`UP` and `NP8` are two Amiga keys with two raw codes.

    The old route sent virtual keys, where `VK_UP` without the extended flag
    arrived as keypad 8; a raw code cannot be confused that way.
    """
    for name, code in (("UP", "4C"), ("NP8", "3E"), ("RET", "44"), ("enter", "44"), ("a", "20")):
        amigadrive.press("holder", name, 0)
        assert sent[-1].endswith(f" press {code} -Holder holder"), (name, sent[-1])
    assert not any(" key " in line or "-Extended" in line for line in sent), sent


def test_every_keypad_digit_is_its_own_key(sent):
    """`NP0`-`NP9` are ten distinct codes."""
    for digit in range(10):
        amigadrive.press("holder", f"NP{digit}", 0)
    codes = [line.split(" press ")[1].split()[0] for line in sent]
    assert len(set(codes)) == 10


@pytest.mark.parametrize("name", ["F11", "F12"])
def test_an_emulator_key_is_not_pressed_as_an_amiga_key(sent, name):
    with pytest.raises(SystemExit, match="not an Amiga key"):
        amigadrive.press("holder", name, 0)
    assert sent == []


def test_a_key_with_no_row_names_the_keys_it_knows(sent):
    with pytest.raises(SystemExit, match="is not a key this knows"):
        amigadrive.press("holder", "NOPE", 0)
    assert sent == []


def _reply(counter=1, pid=77, ms=800, size=(752, 574)):
    """What `winuae.ps1 shot` prints: its `ok` line and the PNG between the markers."""
    import base64
    import io

    from PIL import Image

    data = io.BytesIO()
    Image.new("RGB", size, (1, 2, 3)).save(data, "PNG")
    return "\n".join([f"ok shot pid={pid} counter={counter:03d} ms={ms}", "WINVM-SHOT-BEGIN",
                      base64.b64encode(data.getvalue()).decode(), "WINVM-SHOT-END"])


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(amigadrive, "_last_counter", {})


def test_a_shot_asks_the_guest_for_its_own_screenshot_and_writes_the_frame_unchanged(
        tmp_path, clock):
    from PIL import Image

    calls = []

    def run(*args, timeout):
        calls.append((args, timeout))
        return _reply(counter=7, pid=4242, ms=910)

    info = amigadrive.shot("wish282-x", tmp_path / "out" / "frame.png", run=run, timeout=12)

    assert info == {"pid": 4242, "counter": 7, "ms": 910}
    assert calls == [(("ssh", f"{amigadrive.PS} shot -Holder wish282-x"), 12)]
    with Image.open(tmp_path / "out" / "frame.png") as frame:
        assert frame.size == (752, 574)


def test_a_shot_that_wrote_no_file_reports_the_guests_line(tmp_path, clock):
    def run(*args, timeout):
        return "fail DBG sc wrote no file in C:\\Amiga\\lanes\\1\\shots\\ (reply 404, last counter 12)"

    with pytest.raises(amigadrive.ShotError, match="wrote no file"):
        amigadrive.shot("a", tmp_path / "x.png", run=run)
    assert not (tmp_path / "x.png").exists()


def test_the_999th_screenshot_is_the_last_and_the_next_says_so(tmp_path, clock):
    amigadrive.shot("a", tmp_path / "x.png", run=lambda *args, timeout: _reply(counter=999))

    def spent(*args, timeout):
        return "fail DBG sc wrote no file in C:\\x (reply 404, last counter 999)"

    with pytest.raises(amigadrive.ShotError, match="written its 999 screenshots"):
        amigadrive.shot("a", tmp_path / "y.png", run=spent)


def test_the_guests_own_limit_message_becomes_the_budget_error(tmp_path, clock):
    def run(*args, timeout):
        raise RuntimeError("winvm ssh failed: fail WinUAE has written its 999 screenshots for pid=5")

    with pytest.raises(amigadrive.ShotError, match="restart the run"):
        amigadrive.shot("a", tmp_path / "y.png", run=run)


def test_the_shot_command_prints_where_the_frame_went(monkeypatch, tmp_path, capsys, clock):
    monkeypatch.setattr(amigadrive, "_winvm", lambda *args, timeout=180: _reply(counter=3, pid=9))
    assert amigadrive.main(["--holder", "h", "shot", str(tmp_path / "f.png")]) == 0
    assert capsys.readouterr().out.strip() == f"{tmp_path / 'f.png'} pid=9 counter=3"


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


def test_the_machine_requests_the_named_directdraw_renderer():
    """WinUAE 6.0.3 rejects numeric `gfx_api` values before selecting a renderer."""
    settings = [line for line in CONFIG.read_text().splitlines()
                if line.startswith("gfx_api=")]
    assert settings == ["gfx_api=directdraw"]


@pytest.mark.parametrize("verb", ["snapshot", "restore", "discard_snapshot"])
def test_the_snapshot_commands_call_the_pipe_with_the_name_and_holder(monkeypatch, capsys, verb):
    calls = []

    class Pipe:
        def __getattr__(self, attr):
            def call(name, holder):
                calls.append((attr, name, holder))
                return "ok done"
            return call

    monkeypatch.setattr(amigadrive, "WinuaePipe", Pipe)
    assert amigadrive.main(["--holder", "h1", verb, "before-walk"]) == 0
    assert calls == [(verb, "before-walk", "h1")]
    assert capsys.readouterr().out.strip() == "ok done"


def test_a_snapshot_failure_is_one_line_and_a_nonzero_exit(monkeypatch):
    from automap.amiga import SnapshotError

    class Pipe:
        def snapshot(self, name, holder):
            raise SnapshotError("The state file x did not appear within 15 s")

    monkeypatch.setattr(amigadrive, "WinuaePipe", Pipe)
    with pytest.raises(SystemExit, match="did not appear within 15 s"):
        amigadrive.main(["--holder", "h1", "snapshot", "before-walk"])
