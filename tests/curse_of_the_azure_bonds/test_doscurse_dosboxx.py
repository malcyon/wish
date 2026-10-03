"""The DOSBox-X branches of `tools/curse_of_the_azure_bonds/doscurse.py`'s console.

The session is a real `dosboxx.XSession` with `subprocess.run` faked, so its
own `capture()`, `halve()`, `key()` and `shot()` run against frames built
here: a 320x200 picture doubled to the 640x400 DOSBox-X draws, and the same
picture torn between two blits.  No code-wheel challenge or answer appears.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.curse_of_the_azure_bonds import cursewheel, doscurse  # noqa: E402
from tools.dos import dosbox, dosboxx  # noqa: E402

SECRET = "QXJ7"
W, H = 320, 200


def picture() -> bytes:
    """A 320x200 RGB frame with a different colour in every row band."""
    rows = []
    for y in range(H):
        rows.append(bytes(((x * 7) & 0xFF, (y * 5) & 0xFF, (x ^ y) & 0xFF)[c]
                          for x in range(W) for c in range(3)))
    return b"".join(rows)


def doubled(px: bytes) -> bytes:
    """`px` as DOSBox-X draws it: every pixel a 2x2 block."""
    out = bytearray()
    for y in range(H):
        row = px[y * W * 3:(y + 1) * W * 3]
        wide = b"".join(row[i:i + 3] * 2 for i in range(0, len(row), 3))
        out += wide + wide
    return bytes(out)


def torn(px: bytes) -> bytes:
    """`doubled(px)` with each odd line of the lower half from another frame."""
    out = bytearray(doubled(px))
    stride = 2 * W * 3
    for y in range(H, 2 * H, 2):
        start = (y + 1) * stride
        out[start:start + stride] = bytes(b ^ 0x55 for b in out[start:start + stride])
    return bytes(out)


def ppm(raw: bytes) -> bytes:
    return f"P6\n{2 * W} {2 * H}\n255\n".encode() + raw


class FakeX(dosboxx.XSession):
    """An `XSession` with no emulator behind it; `subprocess.run` is faked."""

    CAPTURE_RETRY_GAP = 0.0

    def __init__(self, tmp_path: pathlib.Path, raw: bytes):
        self.dir = tmp_path
        (tmp_path / "shots").mkdir()
        self.window = "0x1"
        self.display = ":99"
        self.raw = raw

    def _env(self) -> dict[str, str]:
        return {}


class Calls(list):
    """The faked `subprocess.run` calls, by argv, and the session they grab."""

    session: FakeX


@pytest.fixture
def calls(monkeypatch):
    """Every faked `subprocess.run`, by argv; `import` returns the frame."""
    seen = Calls()

    def run(argv, *args, **kwargs):
        argv = [str(a) for a in argv]
        seen.append(argv)
        out = b""
        if argv[0] == "import" and argv[-1] == "ppm:-":
            out = ppm(seen.session.raw)
        elif argv[0] == "import":
            from PIL import Image
            Image.frombytes("RGB", (2 * W, 2 * H), seen.session.raw).save(argv[-1])
        return subprocess.CompletedProcess(argv, 0, out, b"")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    return seen


def _console(tmp_path, calls, raw):
    s = FakeX(tmp_path, raw)
    calls.session = s
    return doscurse.Console(s, tmp_path / "c.cmd", tmp_path / "c.log")


def _log(tmp_path):
    return (tmp_path / "c.log").read_text()


def test_a_shot_is_halved_to_320x200(tmp_path, calls):
    from PIL import Image
    con = _console(tmp_path, calls, doubled(picture()))
    con.shoot("view")
    out = tmp_path / "shots" / "000-view.png"
    im = Image.open(out)
    assert im.size == (W, H)
    assert im.convert("RGB").tobytes() == picture()
    assert "torn frame" not in _log(tmp_path)
    assert not any(a[0] == "import" and a[-1].endswith(".png") for a in calls)


def test_a_torn_shot_is_halved_loosely(tmp_path, calls):
    from PIL import Image
    con = _console(tmp_path, calls, torn(picture()))
    with pytest.raises(dosboxx.NotLineDoubled):
        dosboxx.XSession.capture(con.s)
    con.shoot("torn")
    im = Image.open(tmp_path / "shots" / "000-torn.png")
    assert im.size == (W, H)
    assert im.convert("RGB").tobytes() == picture()
    assert "torn frame, halved loosely" in _log(tmp_path)


def test_describe_reads_a_torn_frame(tmp_path, calls):
    con = _console(tmp_path, calls, torn(picture()))
    con.describe()
    whole = dosbox.Screen(W, H, picture())
    log = _log(tmp_path)
    assert "torn frame, halved loosely" in log
    assert f"frame={whole.digest()} " in log
    assert f"bar.glyphs={whole.glyphs(dosbox.BAR)}" in log


def test_type_focuses_then_types_without_window(tmp_path, calls):
    con = _console(tmp_path, calls, doubled(picture()))
    con.do("type ALDO")
    typed = [a for a in calls if a[0] == "xdotool"]
    assert typed[:2] == [["xdotool", "windowfocus", "0x1"],
                         ["xdotool", "type", "--clearmodifiers", "ALDO"]]


def test_wheel_types_the_answer_through_xtest(tmp_path, calls, monkeypatch):
    from PIL import Image
    read = []

    def identify(shot):
        read.append(Image.open(shot).size)
        return {"espruar": [(1.0, 3)], "dethek": [(1.0, 4)],
                "espruar_ink": 100, "dethek_ink": 100, "path": 1}

    monkeypatch.setattr(cursewheel, "identify", identify)
    monkeypatch.setattr(cursewheel, "answer", lambda box, e, d, p: ("x", SECRET))
    con = _console(tmp_path, calls, doubled(picture()))
    assert con.do("wheel 4") is True
    assert read == [(2 * W, 2 * H)]
    keys = [a for a in calls if a[0] == "xdotool"]
    assert keys == [["xdotool", "windowfocus", "0x1"],
                    ["xdotool", "key", "--clearmodifiers", SECRET],
                    ["xdotool", "windowfocus", "0x1"],
                    ["xdotool", "key", "--clearmodifiers", "Return"]]
    log = _log(tmp_path)
    assert "answered" in log
    assert SECRET not in log
    assert not list((tmp_path / "shots").glob("wheel*.png"))
