"""The Curse `warp` step goes through `FastTravel.run`, the path a player's
Fast Travel takes, and Pool of Radiance and Silver Blades keep their own."""

from __future__ import annotations

import pytest

from automap import c64, fasttravel
from goldbox import c64_save
from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS as CURSE
from goldbox.c64_port import SECRET_OF_THE_SILVER_BLADES as SILVER
from goldbox.items import ITEM_AREA_BASE, ITEM_BLOCK_STRIDE
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


def test_a_curse_warp_the_game_does_not_take_stops_before_any_write(tmp_path, monkeypatch):
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


# --- ready ---------------------------------------------------------------------

class ReadMonitor:
    """A monitor that can only read, and logs every address it is asked for:
    each `(address, length)` queues a before and an after reading."""

    def __init__(self, script):
        self.script = script
        self.asked = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, addr, length):
        self.asked.append((addr, length))
        return self.script[(addr, length)].pop(0)

    def resume(self):
        pass


def _curse_ready(tmp_path, monkeypatch):
    box = c64_save.CONTAINERS[CURSE.key]
    script = {}
    for slot in range(8):
        rec = box.slot_area_base + slot * box.slot_stride
        item = box.item_area_base + slot * ITEM_BLOCK_STRIDE
        ros = box.roster_base + slot * box.roster_stride
        before = {rec: bytearray(box.slot_stride), item: bytearray(ITEM_BLOCK_STRIDE),
                  ros: bytearray(box.roster_stride)}
        after = {k: v.copy() for k, v in before.items()}
        if slot == 4:
            after[rec][0x1A] = 5            # a record byte the rebuild changed
            after[item][6] = 0x80           # the item's readied bit
            after[ros][0x0E] = 3            # a roster byte (armour class)
        for addr, data in before.items():
            script[(addr, len(data))] = [bytes(data), bytes(after[addr])]
    monitor = ReadMonitor(script)
    sess = FakeSession()
    sess.mon = lambda timeout=5.0: monitor
    run = A.CurseRun.__new__(A.CurseRun)
    run.sess, run.game, run.box = sess, CURSE, box
    run.capture_ready = False
    run.log = type("L", (), {"say": staticmethod(lambda text: None)})()
    run.to_world = lambda tries=10: True
    monkeypatch.setattr(A.route_pool, "open_items", lambda *a: True)
    monkeypatch.setattr(A.route_pool, "toggle_item", lambda *a, **k: True)
    monkeypatch.setattr(A.route_pool, "leave_items", lambda *a: None)
    sess.settle = lambda seconds=0: None
    got = run.ready("ARIEL>PLATE MAIL")
    return got, monitor, box


def test_curse_ready_reads_curses_own_record_item_and_roster_blocks(
        tmp_path, monkeypatch):
    got, monitor, box = _curse_ready(tmp_path, monkeypatch)
    rec = box.slot_area_base + 4 * box.slot_stride
    ros = box.roster_base + 4 * box.roster_stride
    item = box.item_area_base + 4 * ITEM_BLOCK_STRIDE
    assert got["record_diff"][4] == [{"addr": rec + 0x1A, "was": 0, "now": 5}]
    assert got["item_diff"][4] == [{"addr": item + 6, "was": 0, "now": 0x80}]
    assert got["roster_diff"][4] == [{"addr": ros + 0x0E, "was": 0, "now": 3}]
    assert got["memory_changed"] is True and got["effects_diff"] == []
    pool = (A.route_pool.SLOT_BASE, ITEM_AREA_BASE, A.route_pool.EFFECTS[0])
    assert not [a for a, _ in monitor.asked if a in pool]
    assert len(monitor.asked) == 2 * 3 * 8      # before and after, nothing else


def test_ready_is_still_rejected_for_silver_blades(tmp_path, capsys):
    with pytest.raises(SystemExit) as info:
        A.main(["--title", "ssb", "--save", str(tmp_path / "x.d64"),
                "--steps", "load", "ready A>B", "--out", str(tmp_path / "o")])
    assert info.value.code == 2
