"""`tools/amiga/amigacampsave.py`, the camp-save loop for #449.

No VM and no emulator: `press`, `settle_fn` and `capture` are all replaced, so
what is under test is the loop's own branching -- how many times it presses
the save keys, when it stops, and that a challenge screen is kept rather than
overwritten by the next save attempt.
"""

from __future__ import annotations

import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import amigabladesjournal as journal  # noqa: E402
from tools.amiga import amigacampsave  # noqa: E402


def _blank(path: pathlib.Path, size=(1920, 1080)):
    Image = pytest.importorskip("PIL.Image")
    Image.new("RGB", size, (0, 0, 0)).save(path)
    return path


def _challenge_frame(path: pathlib.Path, *, x0=58, y0=59, pitch=16,
                     left=journal.LEFT_MARGIN, width=16,
                     colour=journal.GREEN, size=(1920, 1080)):
    """A frame `fit_grid` reads as a challenge: three inked text rows."""
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", size, (0, 0, 0))
    pixels = image.load()
    for row in (2, 4, 6):
        top = int(y0 + row * pitch)
        for y in range(top, top + pitch - 2):
            for x in range(int(x0 + left * pitch), int(x0 + (left + width) * pitch)):
                pixels[x, y] = colour
    image.save(path)
    return path


def _rig(monkeypatch, tmp_path, frames):
    """`camp_save_loop` with every hook replaced; `frames` is one path per
    settle call, consumed in order."""
    pytest.importorskip("PIL.Image")
    pressed: list[str] = []
    calls = {"n": 0}

    def settle_fn(path):
        source = frames[calls["n"]]
        calls["n"] += 1
        path.write_bytes(pathlib.Path(source).read_bytes())
        return True

    def capture(path):
        # journal.answer() calls this itself, for the screen it is about to
        # answer -- the last one the loop's own settle_fn wrote.
        source = frames[calls["n"] - 1]
        pathlib.Path(path).write_bytes(pathlib.Path(source).read_bytes())

    monkeypatch.setattr(journal, "_blades_modules", lambda: (_FakeScreen(), _FakeTables()))
    monkeypatch.setattr(journal, "tables", lambda adf: [])
    return pressed, settle_fn, capture


class _FakeScreen:
    X0 = Y0 = 0.0
    PITCH = 30.64

    def read_challenge(self, path):
        return {"kind": "rule-book"}


class _FakeTables:
    def answer_for(self, challenge, table):
        return types.SimpleNamespace(answer="TESTWORD")


def test_no_challenge_presses_n_and_tries_again(monkeypatch, tmp_path):
    frames = [_blank(tmp_path / "b1.png"), _blank(tmp_path / "b2.png"),
             _blank(tmp_path / "b3.png")]
    pressed, settle_fn, capture = _rig(monkeypatch, tmp_path, frames)
    attempt, shot = amigacampsave.camp_save_loop(
        "holder", tmp_path / "disk.adf", "A", 3, tmp_path / "out",
        settle_fn=settle_fn, capture=capture, press=pressed.append)
    assert attempt is None
    assert shot is None
    # Three full attempts: E, S, A, RET, N each time.
    assert pressed == ["E", "S", "A", "RET", "N"] * 3


def test_max_saves_is_the_hard_bound(monkeypatch, tmp_path):
    frames = [_blank(tmp_path / f"b{i}.png") for i in range(5)]
    pressed, settle_fn, capture = _rig(monkeypatch, tmp_path, frames)
    amigacampsave.camp_save_loop(
        "holder", tmp_path / "disk.adf", "A", 5, tmp_path / "out",
        settle_fn=settle_fn, capture=capture, press=pressed.append)
    # E S A RET N is five keys per attempt; five attempts and no more.
    assert pressed.count("E") == 5


def test_a_challenge_screen_stops_the_loop_and_is_preserved(monkeypatch, tmp_path):
    frames = [_blank(tmp_path / "b1.png"),
             _challenge_frame(tmp_path / "chal.png"),
             _blank(tmp_path / "after.png")]
    pressed, settle_fn, capture = _rig(monkeypatch, tmp_path, frames)
    out = tmp_path / "out"
    attempt, shot = amigacampsave.camp_save_loop(
        "holder", tmp_path / "disk.adf", "A", 5, out,
        settle_fn=settle_fn, capture=capture, press=pressed.append)
    assert attempt == 2
    assert shot == out / "save02-challenge.png"
    assert shot.exists()
    # First attempt: an ordinary save, dismissed with N. Second: the save
    # keys again, then the challenge is answered instead of dismissed.
    assert pressed == (
        ["E", "S", "A", "RET", "N"]
        + ["E", "S", "A", "RET"] + list("TESTWORD") + ["RET"])


def test_build_config_rewrites_only_floppy0(tmp_path):
    original = amigacampsave.CONFIG_TEMPLATE.read_text()
    out = amigacampsave.build_config("C:/Amiga/Disks/issue449/party.adf")
    lines = out.read_text().splitlines()
    floppy0 = [line for line in lines if line.startswith("floppy0=")]
    assert floppy0 == [r"floppy0=C:\Amiga\Disks\issue449\party.adf"]
    original_floppy1 = [line for line in original.splitlines()
                        if line.startswith("floppy1=")]
    assert [line for line in lines if line.startswith("floppy1=")] == original_floppy1


def test_scratch_copy_never_touches_the_source(tmp_path):
    source = tmp_path / "SecretOfTheSilverBlades_A.adf"
    source.write_bytes(b"original bytes")
    copy = amigacampsave.scratch_copy(source)
    assert copy != source
    assert copy.read_bytes() == b"original bytes"
    copy.write_bytes(b"changed")
    assert source.read_bytes() == b"original bytes"
