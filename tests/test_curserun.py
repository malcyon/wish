from __future__ import annotations

import contextlib
import os
import pathlib
from types import SimpleNamespace

import pytest
from conftest import load_tools_module

C = load_tools_module("curserun")

SLOT = pathlib.Path("/slot").resolve()


class FakeMonitor:
    def __init__(self, side: int, reads: list[tuple[int, int]]):
        self.side = side
        self.reads = reads

    def read(self, address: int, size: int) -> bytes:
        self.reads.append((address, size))
        return bytes([self.side])


class FakeSession(C.CurseSession):
    def __init__(self, side: int, attached: str = str(SLOT / "SIDE0.D64")):
        self.here = SLOT
        self.attached = attached
        self.side = side
        self.reads: list[tuple[int, int]] = []
        self.events: list[tuple[str, str | int]] = []
        self._last_prompt = 0.0
        self.save_disk = str(SLOT / "SIDE0.D64")

    def mon(self, timeout: float = 5.0):
        return contextlib.nullcontext(FakeMonitor(self.side, self.reads))

    def log(self, message: str) -> None:
        self.events.append(("log", message))

    def attach(self, path: str) -> None:
        self.events.append(("attach", path))
        self.attached = os.path.abspath(path)

    def press_kernal(self, code: int, timeout: float = 3.0) -> bool:
        self.events.append(("kernal", code))
        return True


def base_begin(session: FakeSession) -> bool:
    session.events.append(("begin", session.attached))
    return True


def test_begin_adventuring_mounts_the_saved_side_before_entering(monkeypatch):
    monkeypatch.setattr(C.por.Session, "begin_adventuring", base_begin)
    session = FakeSession(side=2)

    assert session.begin_adventuring()

    assert session.reads == [(0x4BEE, 1)]
    assert ("attach", str(SLOT / "SIDE2.D64")) in session.events
    assert session.events[-1] == ("begin", str(SLOT / "SIDE2.D64"))


@pytest.mark.parametrize("side", [0, len(C.SIDES) + 1])
def test_begin_adventuring_leaves_an_invalid_saved_side_to_the_prompt(
        monkeypatch, side):
    monkeypatch.setattr(C.por.Session, "begin_adventuring", base_begin)
    session = FakeSession(side=side)

    assert session.begin_adventuring()

    assert not [event for event in session.events if event[0] == "attach"]
    assert session.events[-1] == ("begin", str(SLOT / "SIDE0.D64"))


def test_begin_adventuring_does_not_remount_the_current_side(monkeypatch):
    monkeypatch.setattr(C.por.Session, "begin_adventuring", base_begin)
    session = FakeSession(side=2, attached=str(SLOT / "SIDE2.D64"))

    assert session.begin_adventuring()

    assert not [event for event in session.events if event[0] == "attach"]
    assert session.events[-1] == ("begin", str(SLOT / "SIDE2.D64"))


def test_disk_prompt_uses_the_key_path_the_game_reads():
    session = FakeSession(side=2)
    screen = SimpleNamespace(text=lambda: "INSERT SIDE # 2, AND PRESS ANY KEY.")

    assert session.handle_prompt(screen)

    assert ("attach", str(SLOT / "SIDE2.D64")) in session.events
    assert session.events[-1] == ("kernal", 0x20)
