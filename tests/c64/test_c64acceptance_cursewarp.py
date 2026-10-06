"""The Curse `warp` step goes through `FastTravel.run`, the path a player's
Fast Travel takes, and Pool of Radiance and Silver Blades keep their own."""

from __future__ import annotations

import pytest

from automap import c64, fasttravel
from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS as CURSE
from goldbox.c64_port import SECRET_OF_THE_SILVER_BLADES as SILVER
from tools.c64 import acceptance as A

ADDR = fasttravel.CURSE_OF_THE_AZURE_BONDS
HERE, THERE = 0x10, 0x01


class FakeTarget:
    """A machine's memory: the key-wait loop of a Curse party in area `HERE`,
    indoors, with `DUNGEON` resident."""

    def __init__(self, sess):
        self.sess = sess
        self.memory = sess.memory

    def read(self, addr, length):
        return bytes(self.memory.get(addr + i, 0) for i in range(length))

    def write(self, addr, data):
        for i, b in enumerate(bytes(data)):
            self.memory[addr + i] = b

    def pc(self):
        return self.sess.pc

    def set_pc(self, address):
        self.sess.jumps.append(address)
        self.sess.pc = address


class FakeSession:
    def __init__(self):
        self.memory = {c64.machine_for(CURSE).mode_flag: 1,
                       ADDR.slot: HERE, ADDR.indoors: 1}
        self.pc = ADDR.key_wait[0]
        self.jumps = []

    def settle(self, seconds=0):
        pass


def _run(tmp_path, monkeypatch, game=CURSE):
    sess = FakeSession()
    monkeypatch.setattr(A, "SessTarget", FakeTarget)
    # `program_counter` asks the target for its own `pc`.
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess, run.game = sess, game
    run.to_world = lambda tries=10: True
    run._wait_idle = lambda need=6: True
    run.capture = lambda tag, rows=None: []
    run.position = lambda: [0, 0, 0]
    run.log = type("L", (), {"say": staticmethod(lambda text: None)})()
    run.fail = lambda tag, why: A.StepFailed(why)
    return run, sess


def test_curse_warp_runs_fast_travel_and_reports_its_outcome(tmp_path, monkeypatch):
    run, sess = _run(tmp_path, monkeypatch)
    ran = []
    real = A.auto_actions.FastTravel.run

    def run_recording(self, target, area=None, **kw):
        ran.append((self.game.title, area.id))
        return real(self, target, area=area, **kw)

    monkeypatch.setattr(A.auto_actions.FastTravel, "run", run_recording)
    got = run.warp(str(THERE))
    assert ran == [(CURSE.title, THERE)]
    assert got["area"] == THERE and got["areas_seen"] == [HERE, THERE]
    assert got["outcome"].startswith("Traveling to")
    assert got["jump"] == sess.jumps == [ADDR.tail]
    assert any(w.startswith(f"${ADDR.slot:04X}=") for w in got["writes"])


def test_curse_warp_the_game_refuses_stops_before_any_write(tmp_path, monkeypatch):
    run, sess = _run(tmp_path, monkeypatch)
    sess.pc = 0x0000                    # not in the key-wait loop
    with pytest.raises(A.StepFailed):
        run.warp(str(THERE))
    assert sess.jumps == [] and sess.memory[ADDR.slot] == HERE


def test_curse_warp_fails_when_the_area_byte_is_not_the_destination(
        tmp_path, monkeypatch):
    run, sess = _run(tmp_path, monkeypatch)
    monkeypatch.setattr(
        A.auto_actions.FastTravel, "run",
        lambda self, target, area=None, **kw: A.auto_actions.Outcome(
            True, "Traveling.", ()))
    with pytest.raises(A.StepFailed, match=rf"read {HERE} after the trip"):
        run.warp(str(THERE))


def test_silver_blades_warp_is_still_rejected(tmp_path, monkeypatch):
    run, sess = _run(tmp_path, monkeypatch, game=SILVER)
    with pytest.raises(A.StepFailed, match="Pool of Radiance and Curse"):
        run.warp("1")
    assert sess.jumps == []


def test_pool_warp_parse_is_unchanged_and_curse_ids_use_the_curse_table():
    assert A.parse_warp("10") == 10
    assert A.parse_warp("1", CURSE.title) == 1
    with pytest.raises(ValueError, match="not an area"):
        A.parse_warp("99", CURSE.title)
