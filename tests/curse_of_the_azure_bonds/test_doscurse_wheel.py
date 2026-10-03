"""The `wheel` console command of `tools/curse_of_the_azure_bonds/doscurse.py`.

The reader and the arithmetic are faked: no real challenge or answer appears
here, and the assertions are about what the console types and logs.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.curse_of_the_azure_bonds import cursewheel, doscurse  # noqa: E402

SECRET = "Z"


class FakeSession:
    def __init__(self, tmp_path):
        self.dir = tmp_path
        (tmp_path / "shots").mkdir()
        self.keys: list[str] = []

    def shot(self, name):
        path = self.dir / "shots" / f"{name}.png"
        path.write_bytes(b"")
        return path

    def key(self, *keys):
        self.keys.extend(keys)


def _console(tmp_path):
    return doscurse.Console(FakeSession(tmp_path), tmp_path / "c.cmd",
                            tmp_path / "c.log")


def _reading(monkeypatch, ink=100, path=1):
    monkeypatch.setattr(cursewheel, "identify", lambda shot: {
        "espruar": [(1.0, 3)], "dethek": [(1.0, 4)],
        "espruar_ink": ink, "dethek_ink": ink, "path": path})
    seen = []

    def answer(box, e, d, p):
        seen.append((box, e, d, p))
        return "x", SECRET

    monkeypatch.setattr(cursewheel, "answer", answer)
    return seen


def test_wheel_types_the_answer_then_return(tmp_path, monkeypatch):
    seen = _reading(monkeypatch)
    con = _console(tmp_path)
    assert con.do("wheel 4") is True
    assert con.s.keys == [SECRET, "Return"]
    assert seen == [(4, 3, 4, 1)]
    log = (tmp_path / "c.log").read_text()
    assert "answered" in log
    assert SECRET not in log.replace("wheel", "")
    assert not list((tmp_path / "shots").glob("*.png"))


def test_wheel_stops_when_no_challenge_is_on_screen(tmp_path, monkeypatch):
    _reading(monkeypatch, ink=3)
    con = _console(tmp_path)
    with pytest.raises(RuntimeError, match="no code-wheel challenge"):
        con.do("wheel 4")
    assert con.s.keys == []


def test_wheel_stops_when_the_path_is_not_read(tmp_path, monkeypatch):
    _reading(monkeypatch, path=None)
    con = _console(tmp_path)
    with pytest.raises(RuntimeError, match="path could not be read"):
        con.do("wheel 4")
    assert con.s.keys == []


@pytest.mark.parametrize("line", ["wheel", "wheel x", "wheel 7"])
def test_wheel_needs_a_box_number(tmp_path, monkeypatch, line):
    _reading(monkeypatch)
    con = _console(tmp_path)
    with pytest.raises(RuntimeError, match="box number"):
        con.do(line)
    assert con.s.keys == []
