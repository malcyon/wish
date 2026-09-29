"""`tools/pool_of_radiance/tavernbrawl.py`: the byte check, the prediction, the staging and the trap.

Nothing here boots an emulator.  `Machine` is one fake C64 behind every
`FakeMon` connection: a 64 K memory, the checkpoints set on it and the stops
the test queues.  The byte check reads the player's own disks when they exist
and a fake loader otherwise; no game bytes are copied into this file except
the seven short runs the driver checks for, which are already in the tool.
"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, ".")

from automap import gamedisks  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.pool_of_radiance import tavernbrawl as tb  # noqa: E402
from tools.pool_of_radiance.ohlowatch import SQUARE  # noqa: E402

# -- fakes ----------------------------------------------------------------


class Machine:
    def __init__(self):
        self.mem = bytearray(0x10000)
        self.checkpoints: dict[int, dict] = {}
        self.hits: dict[int, int] = {}
        self.next_cp = 1
        self.stops: list[int] = []      # PCs `wait_stopped` will answer, in order
        self.pc = 0
        self.calls: list[str] = []
        self.writes: list[tuple[int, bytes]] = []
        self.cleared = 0

    def store(self, address, pc=0):
        """A write to `address` under whatever store checkpoints watch it."""
        self.pc = pc
        for n, cp in self.checkpoints.items():
            if cp["store"] and cp["start"] == address:
                self.hits[n] = self.hits.get(n, 0) + 1

    def exec_at(self, address):
        for n, cp in self.checkpoints.items():
            if cp["exec"] and cp["start"] == address:
                self.hits[n] = self.hits.get(n, 0) + 1

    def exec_checkpoints(self):
        return [cp for cp in self.checkpoints.values() if cp["exec"]]


class FakeMon:
    def __init__(self, machine):
        self.m = machine

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, start, length, bank=0):
        return bytes(self.m.mem[start:start + length])

    def peek(self, addr, bank=0):
        return self.m.mem[addr]

    def write(self, start, data, bank=0):
        self.m.writes.append((start, bytes(data)))
        self.m.mem[start:start + len(data)] = data

    def registers(self):
        return {3: self.m.pc}

    def checkpoint_set(self, start, end=None, *, load=False, store=False,
                       exec_=False, stop=True, temporary=False):
        n = self.m.next_cp
        self.m.next_cp += 1
        self.m.checkpoints[n] = {"start": start, "store": store, "exec": exec_,
                                 "stop": stop}
        self.m.calls.append(f"set {'store' if store else 'exec'} ${start:04X}")
        return n

    def checkpoint_delete(self, n):
        self.m.checkpoints.pop(n, None)
        self.m.calls.append("delete")

    def checkpoint_hits(self, n):
        return self.m.hits.get(n, 0)

    def checkpoints_clear(self):
        self.m.cleared += 1
        self.m.checkpoints.clear()

    def resume(self):
        self.m.calls.append("resume")

    def wait_stopped(self, timeout=20.0):
        if not self.m.stops:
            return None
        pc = self.m.stops.pop(0)
        self.m.pc = pc
        self.m.exec_at(pc)
        self.m.calls.append(f"stopped ${pc:04X}")
        return pc


class FakeLog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def say(self, text):
        pass

    closed = False

    def close(self):
        self.closed = True

    def kinds(self, kind):
        return [kw for k, kw in self.events if k == kind]


class FakeScreen:
    def __init__(self, row24=""):
        self.row24 = row24

    def row(self, r):
        return self.row24 if r == 24 else ""


class FakeSession:
    def __init__(self, machine=None):
        self.machine = machine or Machine()
        self.machine.mem[tb.ARRIVED] = 1
        self.script: list[str | None] = []
        self.picked: list[str] = []
        self.returns = 0
        self.shots: list[str] = []
        self.turns: list[str] = []
        self.terminated = False
        self.fight_hook = lambda tactic: None
        self.combat = False
        self.save_disk = "/nonexistent/save.d64"

    def mon(self, timeout=5.0):
        return FakeMon(self.machine)

    def screen(self):
        if not self.script:
            return FakeScreen("MOVE")
        row = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        return None if row is None else FakeScreen(row)

    def handle_prompt(self, s=None):
        return False

    def in_combat(self):
        return self.combat

    def press_kernal(self, code):
        self.returns += 1

    def select_bar(self, label, row=24, timeout=30.0):
        self.picked.append(label)
        return True

    def boot(self):
        return True

    load_save = begin_adventuring = boot

    fight_battle = None
    #: What `melee_turn` saw as the enemies, one list per call.
    aimed_at: list

    def battle(self):
        return self.fight_battle

    def melee_turn(self, state):
        self.turns.append("melee")
        b = self.battle()
        self.aimed_at = getattr(self, "aimed_at", []) + [
            None if b is None else [c.index for c in b.enemies]]
        return "melee"

    no_taken = True

    def combat_bar(self, label, timeout=30.0):
        self.picked.append(label)
        return self.no_taken

    def await_bar(self, kinds, timeout=6.0, interval=0.4):
        return self.bar_after_no

    bar_after_no = None

    def combat_state(self, s=None):
        return S.Session.combat_state(self, s)

    def combat_turn(self):
        self.turns.append("combat_turn")
        return "done"

    def character_sheet(self, index=None, timeout=30.0, shot=None):
        self.shots.append(f"sheet{index}")
        return ["SHEET"]

    def fight(self, budget=300.0, tactic=None, poll=1.0, stop=None):
        self.fight_hook(tactic)
        return S.FightResult("WON", 1, 1.0, {}, [], 0, [])

    def terminate(self):
        self.terminated = True

    class kbd:
        shots: list[str] = []

        timeouts: list = []

        @staticmethod
        def screenshot(path, timeout=None):
            FakeSession.kbd.shots.append(path)
            FakeSession.kbd.timeouts.append(timeout)
            return True


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(tb, "pause", lambda s: None)
    monkeypatch.setattr(tb.A, "pc_register", lambda m: 3)
    monkeypatch.setattr(tb, "read_screen", lambda m: FakeScreen("EXIT"))
    FakeSession.kbd.shots = []
    FakeSession.kbd.timeouts = []


def args(**kw):
    base = dict(mode="win", stay=None, charm=None, charm_form="monster",
                wound_allies=False, stage_6de3=None, stage_item=None,
                force_roll=False, force_destination=None, max_entries=3,
                budget=1.0, slot=None, quiet=True, disks="/nonexistent-disks",
                save="/nonexistent/save.d64")
    base.update(kw)
    return SimpleNamespace(**base)


def blocks(**put):
    """64 combatant blocks; `put` maps n -> (status, side[, skip])."""
    data = bytearray(tb.BLOCKS * tb.STRIDE)
    for n, spec in put.items():
        n = int(n[1:])
        data[n * tb.STRIDE] = spec[0]
        data[n * tb.STRIDE + tb.SIDE] = spec[1]
        if len(spec) > 2:
            data[n * tb.STRIDE + tb.SKIP] = spec[2]
    return bytes(data)


def installed(machine=None, **kw):
    sess = FakeSession(machine)
    traps = tb.Traps(sess, FakeLog(), pathlib.Path("/nonexistent-out"), args(**kw))
    traps.install()
    return sess, traps


def connect(sess):
    with sess.mon(5):
        pass


# -- 1. the byte check --------------------------------------------------------


def fake_loader(alter=None):
    bodies = {}
    for name, at, want in tb.CODE_ROWS:
        body = bodies.setdefault(name, bytearray(0x3000))
        body[at - tb.LINKER_BASE:at - tb.LINKER_BASE + len(bytes.fromhex(want))] = bytes.fromhex(want)
    if alter:
        name, at = alter
        bodies[name][at - tb.LINKER_BASE] ^= 0xFF

    def load(name, root):
        return "FAKE.D64", 0x1000, bytes(bodies[name])
    return load


def test_the_byte_check_accepts_a_disk_that_holds_every_row():
    lines = []
    assert tb.check_code("root", load=fake_loader(), out=lines.append) == 0
    assert len(lines) == len(tb.CODE_ROWS) + len(tb.CODE_SHOWN)


@pytest.mark.parametrize("name,at", [(n, a) for n, a, _ in tb.CODE_ROWS])
def test_the_byte_check_refuses_a_disk_that_differs_at_any_of_the_seven_addresses(name, at):
    lines = []
    assert tb.check_code("root", load=fake_loader((name, at)), out=lines.append) == 1
    assert sum("DIFFERS" in line for line in lines) == 1


def test_the_byte_check_matches_the_players_own_disks():
    root = gamedisks.find("pool-of-radiance")
    if root is None:
        pytest.skip("no Pool of Radiance disks")
    lines = []
    assert tb.check_code(str(root), out=lines.append) == 0, lines


def test_the_byte_check_refuses_the_players_disks_with_one_byte_altered():
    root = gamedisks.find("pool-of-radiance")
    if root is None:
        pytest.skip("no Pool of Radiance disks")

    def altered(name, root):
        disk, declared, body = tb.overlay(name, root)
        if name == "DUNGEON":
            body = bytearray(body)
            body[0x17DA - tb.LINKER_BASE] ^= 0xFF
        return disk, declared, bytes(body)

    assert tb.check_code(str(root), load=altered, out=lambda line: None) == 1


# -- 2. the prediction --------------------------------------------------------

RUN, DOWN, OK = 0x86, 0x83, 0x01


def test_a_standing_party_member_is_a_win():
    assert tb.predicted_result(blocks(n0=(OK, 0), n1=(RUN, 0))) == 0


def test_a_standing_ally_holds_the_fight_open_when_the_party_has_left():
    assert tb.predicted_result(blocks(n0=(RUN, 0), n1=(RUN, 0), n41=(OK, 0x80))) == 0


def test_all_party_side_down_or_running_with_one_runner_is_the_flight_result():
    assert tb.predicted_result(blocks(n0=(RUN, 0), n1=(DOWN, 0), n41=(DOWN, 0x80))) == 0x81


def test_the_same_with_nobody_running_is_a_loss():
    assert tb.predicted_result(blocks(n0=(DOWN, 0), n1=(DOWN, 0))) == 0x80


def test_a_standing_monster_side_charmed_member_does_not_stop_the_flight_result():
    assert tb.predicted_result(blocks(n0=(RUN, 0), n1=(DOWN, 0), n2=(OK, 0xC1))) == 0x81


def test_a_standing_party_side_charmed_member_alone_is_a_loss():
    assert tb.predicted_result(blocks(n2=(OK, 0xC0), n0=(DOWN, 0))) == 0x80


def test_a_running_monster_with_a_party_member_standing_is_the_second_win_result():
    assert tb.predicted_result(blocks(n0=(OK, 0), n9=(RUN, 0x81))) == 1


def test_status_zero_and_the_skip_bit_are_not_counted():
    assert tb.predicted_result(blocks(n0=(OK, 0, 0x80), n1=(0, 0), n2=(RUN, 0))) == 0x81


# -- 3. the charm -------------------------------------------------------------


def test_the_monster_form_writes_the_row_and_the_side_byte():
    machine = Machine()
    got = tb.stage_charm(FakeMon(machine), 2, "monster", acting=0)
    assert got["row"] == 0x3F
    assert bytes(machine.mem[tb.CHARM_ID_AT + 0x3F:][:1]) == b"\x0b"
    assert machine.mem[tb.CHARM_OWNER_AT + 0x3F] == 2
    assert machine.mem[tb.CHARM_DURATION_AT + 0x3F] == 0
    assert machine.mem[tb.CHARM_MAGNITUDE_AT + 0x3F] == 0x87
    assert machine.mem[tb.COMBATANTS + 0x20 * 2 + tb.SIDE] == 0xC1
    assert not any(a >= tb.WORK and a < tb.WORK + 0x20 for a, _ in machine.writes)


def test_the_party_form_writes_the_other_magnitude_and_side():
    machine = Machine()
    tb.stage_charm(FakeMon(machine), 2, "party", acting=0)
    assert machine.mem[tb.CHARM_MAGNITUDE_AT + 0x3F] == 0x86
    assert machine.mem[tb.COMBATANTS + 0x20 * 2 + tb.SIDE] == 0xC0


def test_the_highest_free_row_is_taken():
    machine = Machine()
    machine.mem[tb.CHARM_ID_AT + 0x3F] = 0x05
    got = tb.stage_charm(FakeMon(machine), 2, "monster", acting=0)
    assert got["row"] == 0x3E


def test_a_slot_that_already_has_a_charm_row_is_refused_and_nothing_is_written():
    machine = Machine()
    machine.mem[tb.CHARM_ID_AT + 5] = tb.CHARM
    machine.mem[tb.CHARM_OWNER_AT + 5] = 2
    with pytest.raises(tb.Exit) as exit_:
        tb.stage_charm(FakeMon(machine), 2, "monster", acting=0)
    assert exit_.value.code == 6
    assert machine.writes == []


def test_the_working_copy_is_written_only_when_the_slot_is_acting():
    machine = Machine()
    tb.stage_charm(FakeMon(machine), 2, "monster", acting=2)
    assert (tb.WORK + tb.SIDE, b"\xc1") in machine.writes
    other = Machine()
    tb.stage_charm(FakeMon(other), 2, "monster", acting=3)
    assert all(a != tb.WORK + tb.SIDE for a, _ in other.writes)


# -- 4. the allies ------------------------------------------------------------


def test_allies_are_found_by_content_not_by_index():
    data = blocks(n0=(OK, 0), n20=(OK, 0x80), n45=(OK, 0), n10=(OK, 0x81),
                  n30=(DOWN, 0x80), n31=(0, 0))
    assert tb.allies_of(data) == [20, 45]


def test_wound_allies_writes_one_hit_point_to_each_ally_and_nothing_else():
    machine = Machine()
    data = blocks(n0=(OK, 0), n20=(OK, 0x80), n45=(OK, 0), n10=(OK, 0x81))
    machine.mem[tb.COMBATANTS:tb.COMBATANTS + len(data)] = data
    sess = FakeSession(machine)
    tactic = tb.Tactic(sess, FakeLog(), args(wound_allies=True))
    with sess.mon() as m:
        tactic.first(m, acting=0)
    assert machine.writes == [(tb.COMBATANTS + 0x20 * 20 + tb.HP_AT, b"\x01\x00"),
                              (tb.COMBATANTS + 0x20 * 45 + tb.HP_AT, b"\x01\x00")]


# -- 5. the exec stops arrive with the result ---------------------------------


def test_the_post_stops_are_armed_only_inside_the_result_handler_and_deleted_after_their_hit():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm_result()
    assert machine.exec_checkpoints() == []
    machine.stops = [tb.ITEM_TALLY_CALL, tb.ITEM_TALLY_BACK, tb.SHARE,
                     tb.EMPTY_PILE, tb.TREASURE]
    machine.store(tb.RESULT, pc=tb.RESULT_STORE_NEXT)
    connect(sess)
    stopped = [c for c in machine.calls if c.startswith("stopped")]
    assert len(stopped) == 5
    assert len(traps.readings["item_tally_call"]) == 1
    assert len(traps.readings["treasure"]) == 1
    # Each armed stop was deleted once handled; only the two hit counters remain.
    left = machine.exec_checkpoints()
    assert sorted(cp["start"] for cp in left) == [tb.NO_ITEMS_SKIP, tb.ITEM_LOOP]
    assert all(not cp["stop"] for cp in left)


def test_a_stop_at_an_unexpected_address_is_resumed_and_logged_not_handled():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm_result()
    machine.stops = [0x1234, tb.ITEM_TALLY_CALL]
    machine.store(tb.RESULT, pc=tb.RESULT_STORE_NEXT)
    connect(sess)
    assert traps.log.kinds("wrong_stop")
    assert len(traps.readings["item_tally_call"]) == 1


def test_everything_is_cleared_when_the_fight_raises(monkeypatch, tmp_path):
    machine = Machine()
    sess = FakeSession(machine)

    def boom(tactic):
        raise RuntimeError("the fight fell over")

    sess.fight_hook = boom
    run_with(monkeypatch, sess, tmp_path)
    assert machine.cleared >= 1
    assert machine.checkpoints == {}
    assert sess.terminated


def run_with(monkeypatch, sess, tmp_path, **kw):
    monkeypatch.setattr(S, "claim_slot", lambda *a, **k: SimpleNamespace(
        n=1, display=":1", teardown=lambda: None, release=lambda: None))
    monkeypatch.setattr(S, "stage_disks", lambda *a, **k: "x")
    monkeypatch.setattr(S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(S, "Session", lambda *a, **k: sess)
    monkeypatch.setattr(tb, "to_world", lambda *a, **k: True)
    monkeypatch.setattr(tb, "resident_area", lambda s, log=None: kw.get("area", 0))
    monkeypatch.setattr(tb, "trigger", lambda sess, traps, *a, **k: traps.brawl_started() or 1)
    monkeypatch.setattr(tb, "after_fight", lambda *a, **k: None)
    return tb.run(args(out=str(tmp_path / "out"), **{
        k: v for k, v in kw.items() if k != "area"}))


def test_a_run_arms_the_trigger_stops_and_the_result_stop_before_the_fight(
        monkeypatch, tmp_path):
    machine = Machine()
    sess = FakeSession(machine)
    seen = {}
    sess.fight_hook = lambda tactic: seen.update(
        armed=sorted(cp["start"] for cp in machine.checkpoints.values()))
    assert run_with(monkeypatch, sess, tmp_path) == 0
    assert seen["armed"] == [tb.RESULT]        # the trigger's own stop was dropped at the brawl


# -- 6. $6DE3 -----------------------------------------------------------------


def test_stage_6de3_writes_zero_when_the_brawl_sets_it():
    machine = Machine()
    sess, traps = installed(machine, stage_6de3=0)
    traps.arm_trigger()
    machine.mem[tb.NO_ITEMS] = 1
    machine.store(tb.MERCY)
    connect(sess)
    assert machine.mem[tb.NO_ITEMS] == 0
    assert traps.readings["mercy_store"][0]["read_back"] == 0


def test_without_stage_6de3_the_brawl_flag_is_left_alone():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm_trigger()
    machine.mem[tb.NO_ITEMS] = 1
    machine.store(tb.MERCY)
    connect(sess)
    assert machine.mem[tb.NO_ITEMS] == 1
    assert machine.writes == []
    assert traps.readings["mercy_store"][0]["no_items"] == 1


# -- 7. the two forced random rolls -------------------------------------------


def test_force_roll_writes_one_only_at_the_random_store():
    machine = Machine()
    sess, traps = installed(machine, force_roll=True)
    traps.arm_trigger()
    machine.store(tb.GAMBLE_ROLL, pc=0x1234)
    connect(sess)
    assert machine.mem[tb.GAMBLE_ROLL] == 0
    machine.store(tb.GAMBLE_ROLL, pc=tb.RANDOM_STORE_NEXT)
    connect(sess)
    assert machine.mem[tb.GAMBLE_ROLL] == 1


def test_no_force_roll_means_no_gamble_stop_at_all():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm_trigger()
    assert [cp["start"] for cp in machine.checkpoints.values()] == [tb.MERCY]


def test_force_destination_writes_only_at_the_random_store():
    machine = Machine()
    sess, traps = installed(machine, force_destination=4)
    traps.arm("destination", tb.DESTINATION, traps.on_destination, store=True, once=False)
    machine.store(tb.DESTINATION, pc=0x1234)
    connect(sess)
    assert machine.mem[tb.DESTINATION] == 0
    assert traps.destination_at is None
    machine.store(tb.DESTINATION, pc=tb.RANDOM_STORE_NEXT)
    connect(sess)
    assert machine.mem[tb.DESTINATION] == 4
    assert traps.destination_at is not None


# -- 8. the staged item -------------------------------------------------------

ITEM = bytes(range(1, 17))


def test_stage_item_writes_the_template_after_the_pile_and_counts_it():
    machine = Machine()
    machine.mem[tb.PILE_COUNT] = 2
    sess, traps = installed(machine, item=None)
    traps.item = ITEM
    with sess.mon() as m:
        traps.on_item_tally_call(m)
    assert bytes(machine.mem[tb.PILE + 32:tb.PILE + 48]) == ITEM
    assert machine.mem[tb.PILE_COUNT] == 3
    assert traps.readings["item_tally_call"][0]["count"] == 2
    assert traps.readings["item_tally_call"][0]["count_after"] == 3


def test_without_an_item_the_pile_is_only_read():
    machine = Machine()
    sess, traps = installed(machine)
    with sess.mon() as m:
        traps.on_item_tally_call(m)
    assert machine.writes == []


@pytest.mark.parametrize("plus", [0, 0x80])
def test_an_item_with_no_usable_plus_is_refused_with_exit_seven(monkeypatch, plus):
    record = bytearray(ITEM)
    record[tb.PLUS_AT] = plus
    monkeypatch.setattr(tb, "load_item_templates", lambda disk, *a, **k: {"X": bytes(record)})
    with pytest.raises(tb.Exit) as exit_:
        tb.resolve_item("X", "/disks")
    assert exit_.value.code == 7


def test_a_missing_item_is_refused_before_any_slot_is_claimed(monkeypatch, tmp_path):
    monkeypatch.setattr(tb, "load_item_templates", lambda disk, *a, **k: {})

    def claimed(*a, **k):
        raise AssertionError("a slot was claimed")

    monkeypatch.setattr(S, "claim_slot", claimed)
    assert tb.run(args(out=str(tmp_path / "o"), stage_item="NOPE")) == 7


def test_a_usable_item_resolves_to_its_bytes(monkeypatch):
    monkeypatch.setattr(tb, "load_item_templates", lambda disk, *a, **k: {"X": ITEM})
    assert tb.resolve_item("X", "/disks") == ITEM


# -- 9. answering the tavern --------------------------------------------------


@pytest.mark.parametrize("row,want", [
    ("IGNORE GRAB", "GRAB"), (" YES  NO ", "NO"), ("STAY RUN", "RUN"),
    ("PRESS <RETURN> OR BUTTON TO CONTINUE", "RETURN"), ("MOVE  VIEW", "MOVE"),
    ("        ", "BLANK"), ("SOMETHING ELSE", "UNKNOWN")])
def test_row_24_calls_for_the_right_answer(row, want):
    assert tb.classify(row) == want


def test_the_loop_answers_grab_no_run_and_return_and_stops_at_a_quiet_world(tmp_path):
    sess = FakeSession()
    sess.script = ["IGNORE GRAB", " YES  NO ", "STAY RUN", "PRESS <RETURN>", "MOVE", "MOVE"]
    met = tb.answer_until(sess, FakeLog(), tmp_path, "t", stop_on_combat=True)
    assert met["outcome"] == "quiet"
    assert sess.picked == ["GRAB", "NO", "RUN"]
    assert sess.returns == 1


def test_the_loop_reports_a_brawl_when_combat_starts(tmp_path):
    sess = FakeSession()
    sess.combat = True
    assert tb.answer_until(sess, FakeLog(), tmp_path, "t", stop_on_combat=True)["outcome"] == "brawl"


def test_an_unrecognised_row_held_four_reads_stops_the_run_with_exit_five(tmp_path):
    sess = FakeSession()
    sess.script = ["SOMETHING ELSE"]
    with pytest.raises(tb.Exit) as exit_:
        tb.answer_until(sess, FakeLog(), tmp_path, "t", stop_on_combat=True)
    assert exit_.value.code == 5
    assert sess.kbd.shots


def test_a_picture_gets_a_return_every_eighth_read(tmp_path):
    sess = FakeSession()
    sess.script = [None] * 8 + ["MOVE", "MOVE"]
    tb.answer_until(sess, FakeLog(), tmp_path, "t", stop_on_combat=False)
    assert sess.returns == 1


def trigger_with(monkeypatch, met_rows, entries=4):
    placed = []
    monkeypatch.setattr(tb, "step_on", lambda s, where, out, label: placed.append(where) or {})
    monkeypatch.setattr(tb, "answer_until",
                        lambda *a, **k: {"outcome": "quiet", "rows": met_rows.pop(0) if met_rows else []})
    sess, traps = installed()
    with pytest.raises(tb.Exit) as exit_:
        tb.trigger(sess, traps, FakeLog(), pathlib.Path("/nonexistent-out"),
                   args(max_entries=entries))
    return placed, exit_.value


def test_no_brawl_within_the_cap_is_exit_three(monkeypatch):
    placed, exit_ = trigger_with(monkeypatch, [])
    assert exit_.code == 3
    assert len(placed) == 4


def test_two_entries_with_no_tavern_screen_switch_every_later_entry_to_the_outside(monkeypatch):
    placed, _ = trigger_with(monkeypatch, [])
    assert placed == [tb.TAVERN_OUTSIDE, tb.TAVERN_BOUNCE[0], tb.TAVERN_OUTSIDE, tb.TAVERN_OUTSIDE]


def test_a_tavern_screen_keeps_the_bounce_placements(monkeypatch):
    placed, _ = trigger_with(monkeypatch, [["MOVE"], ["PRESS <RETURN>"], ["MOVE"]])
    assert placed == [tb.TAVERN_OUTSIDE, tb.TAVERN_BOUNCE[0], tb.TAVERN_BOUNCE[1], tb.TAVERN_BOUNCE[0]]


def test_the_brawl_drops_the_trigger_stops(monkeypatch):
    machine = Machine()
    sess, traps = installed(machine, force_roll=True)
    traps.arm_trigger()
    monkeypatch.setattr(tb, "step_on", lambda *a, **k: {})
    monkeypatch.setattr(tb, "answer_until", lambda *a, **k: {"outcome": "brawl", "rows": []})
    assert tb.trigger(sess, traps, FakeLog(), pathlib.Path("/nonexistent-out"), args()) == 1
    assert machine.checkpoints == {}


# -- 10. the wrong place ------------------------------------------------------


@pytest.mark.parametrize("area,arrived", [(20, 1), (0, 0)])
def test_a_save_outside_new_phlan_or_before_arrival_exits_one_with_no_step(
        monkeypatch, tmp_path, area, arrived):
    machine = Machine()
    sess = FakeSession(machine)
    machine.mem[tb.ARRIVED] = arrived
    stepped = []
    monkeypatch.setattr(tb, "step_on", lambda *a, **k: stepped.append(1))
    monkeypatch.setattr(S, "claim_slot", lambda *a, **k: SimpleNamespace(
        n=1, display=":1", teardown=lambda: None, release=lambda: None))
    monkeypatch.setattr(S, "stage_disks", lambda *a, **k: "x")
    monkeypatch.setattr(S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(S, "Session", lambda *a, **k: sess)
    monkeypatch.setattr(tb, "to_world", lambda *a, **k: True)
    monkeypatch.setattr(tb, "resident_area", lambda s, log=None: area)
    assert tb.run(args(out=str(tmp_path / "out"))) == 1
    assert stepped == []


# -- 11. the flee tactic ------------------------------------------------------


class Flee:
    def __init__(self):
        self.calls = 0

    def __call__(self, sess, state):
        self.calls += 1
        return "flight"


def test_the_stay_and_charm_slots_pass_their_turns_and_everyone_else_flees():
    machine = Machine()
    sess = FakeSession(machine)
    flee = Flee()
    tactic = tb.Tactic(sess, FakeLog(), args(mode="flee", stay=1, charm=2), flee)
    for acting in (0, 1, 2, 3):
        machine.mem[tb.ACTING] = acting
        tactic.calls = 1                       # past the staging call
        tactic(sess, None)
    assert sess.turns == ["combat_turn", "combat_turn"]
    assert flee.calls == 2


def test_win_mode_fights_every_turn_with_the_melee_tactic():
    machine = Machine()
    sess = FakeSession(machine)
    tactic = tb.Tactic(sess, FakeLog(), args())
    tactic(sess, None)
    assert sess.turns == ["melee"]


def test_the_first_bar_stages_the_stay_slot_and_the_charm_and_reads_the_charm_back():
    machine = Machine()
    sess = FakeSession(machine)
    log = FakeLog()
    tactic = tb.Tactic(sess, log, args(mode="flee", stay=1, charm=2), Flee())
    tactic(sess, None)
    tactic(sess, None)
    assert (tb.COMBATANTS + 0x20 + tb.HP_AT, b"\x01\x00") in machine.writes
    assert machine.mem[tb.COMBATANTS + 0x40 + tb.SIDE] == 0xC1
    assert log.kinds("charm_staged")
    assert log.kinds("charm_readback")[0]["side"] == 0xC1


# -- 12. every handled stop is followed by a resume ---------------------------


def test_a_handled_store_stop_is_followed_by_a_resume():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm_trigger()
    machine.store(tb.MERCY)
    machine.calls.clear()
    connect(sess)
    assert machine.calls[-1] == "resume"


def test_every_stop_the_result_handler_waits_for_is_preceded_by_a_resume():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm_result()
    machine.stops = [tb.ITEM_TALLY_CALL, tb.ITEM_TALLY_BACK, tb.SHARE,
                     tb.EMPTY_PILE, tb.TREASURE]
    machine.store(tb.RESULT, pc=tb.RESULT_STORE_NEXT)
    connect(sess)
    calls = machine.calls
    for i, call in enumerate(calls):
        if call.startswith("stopped"):
            assert calls[i - 1] == "resume"
    assert calls[-1] == "resume"


# -- 13. off the map ----------------------------------------------------------


def after(monkeypatch, tmp_path, square):
    machine = Machine()
    machine.mem[SQUARE:SQUARE + 3] = bytes(square)
    sess = FakeSession(machine)
    monkeypatch.setattr(tb, "answer_until", lambda *a, **k: {"outcome": "quiet", "rows": []})
    log = FakeLog()
    traps = tb.Traps(sess, log, tmp_path, args())
    tb.after_fight(sess, traps, log, tmp_path, args(), [
        {"slot": i, "experience": 0, "flags": 0} for i in range(8)])
    return sess, log


def test_a_party_off_the_map_is_logged_and_the_panel_and_sheet_are_skipped(monkeypatch, tmp_path):
    sess, log = after(monkeypatch, tmp_path, (16, 3, 0))
    assert log.kinds("off_map")
    assert sess.kbd.shots == [] and sess.shots == []


def test_a_party_on_the_map_gets_its_panel_and_sheet(monkeypatch, tmp_path):
    sess, log = after(monkeypatch, tmp_path, (7, 3, 0))
    assert not log.kinds("off_map")
    assert [pathlib.Path(p).name for p in sess.kbd.shots] == ["panel.png"]
    assert sess.shots == ["sheet0"]


def test_a_y_of_sixteen_is_off_the_map_too(monkeypatch, tmp_path):
    sess, log = after(monkeypatch, tmp_path, (3, 16, 0))
    assert log.kinds("off_map")


# -- arguments ----------------------------------------------------------------


@pytest.mark.parametrize("kw", [
    dict(mode="flee"),
    dict(charm=1), dict(stay=0), dict(wound_allies=True),
    dict(mode="flee", stay=1, stage_6de3=0),
    dict(mode="flee", stay=1, stage_item="X"),
    dict(mode="flee", stay=1, charm=1),
    dict(mode="flee", stay=6),
    dict(force_destination=5)])
def test_refused_argument_combinations(kw):
    assert tb.check_args(args(**kw)) is not None


def test_accepted_argument_combinations():
    assert tb.check_args(args()) is None
    assert tb.check_args(args(mode="flee", stay=1, charm=2, wound_allies=True)) is None
    assert tb.check_args(args(stage_6de3=0, stage_item="X", force_destination=4)) is None


# -- the review's findings ----------------------------------------------------


def test_a_store_to_the_result_byte_at_another_pc_is_logged_and_ignored():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm_result()
    machine.stops = [tb.ITEM_TALLY_CALL]
    machine.store(tb.RESULT, pc=0x1234)
    connect(sess)
    assert traps.readings["result_store_ignored"][0]["pc"] == 0x1234
    assert "result" not in traps.readings
    assert not traps.result_done
    assert machine.exec_checkpoints() == []         # no POST.COM stop was armed
    assert [cp["start"] for cp in machine.checkpoints.values()] == [tb.RESULT]
    machine.store(tb.RESULT, pc=tb.RESULT_STORE_NEXT)  # the real one is still caught
    connect(sess)
    assert traps.result_done and "result" in traps.readings


def test_a_mercy_hit_pending_when_the_trigger_stops_are_dropped_still_runs_its_handler():
    machine = Machine()
    sess, traps = installed(machine, stage_6de3=0)
    traps.arm_trigger()
    machine.mem[tb.NO_ITEMS] = 1
    machine.store(tb.MERCY)                         # fired; no connection has seen it
    traps.drop("mercy", "gamble")
    assert machine.mem[tb.NO_ITEMS] == 0
    assert traps.readings["mercy_store"][0]["read_back"] == 0
    assert machine.checkpoints == {}


def test_an_exec_stop_pending_when_the_post_stops_are_retired_still_runs_its_handler():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm("line_drawn", tb.LINE_DRAWN, traps.on_line_drawn)
    machine.exec_at(tb.LINE_DRAWN)
    traps.retire_exec()
    assert len(traps.readings["line_drawn"]) == 1
    assert machine.exec_checkpoints() == []


def test_a_handler_that_raises_leaves_nothing_armed_and_lets_the_machine_run():
    machine = Machine()
    sess, traps = installed(machine)

    def boom(m):
        raise OSError("the handler fell over")

    traps.arm("boom", 0x1234, boom, store=True, once=False)
    machine.store(0x1234)
    machine.calls.clear()
    connect(sess)
    assert traps.degraded
    assert machine.checkpoints == {}
    assert machine.calls[-1] == "resume"


def test_the_post_stop_wait_has_an_overall_deadline(monkeypatch):
    machine = Machine()
    sess, traps = installed(machine)
    ticks = iter(range(0, 10_000, 20))
    monkeypatch.setattr(tb, "clock", lambda: float(next(ticks)))
    traps.arm_result()
    machine.stops = [0x1234] * 50                   # a stop that keeps recurring
    machine.store(tb.RESULT, pc=tb.RESULT_STORE_NEXT)
    connect(sess)
    timeout = traps.log.kinds("stop_timeout")
    assert timeout and timeout[0]["why"] == "deadline"
    assert len(machine.stops) > 40                  # it gave up long before the 50


def test_a_missing_disk_file_is_a_clear_error_from_the_byte_check():
    def missing(name, root):
        raise SystemExit(f"No file called {name} on any disk under {root}")

    lines = []
    assert tb.check_code("root", load=missing, out=lines.append) == 2
    assert "cannot read POST.COM" in lines[0]


def test_an_unreadable_item_disk_is_exit_seven_not_a_traceback(monkeypatch, tmp_path):
    def gone(disk, *a, **k):
        raise FileNotFoundError(disk)

    monkeypatch.setattr(tb, "load_item_templates", gone)
    with pytest.raises(tb.Exit) as exit_:
        tb.resolve_item("X", "/disks")
    assert exit_.value.code == 7
    assert "cannot read" in exit_.value.why


def fake_slot(torn):
    return SimpleNamespace(n=1, display=":1", teardown=lambda: torn.append(1),
                           release=lambda: None)


def patch_run(monkeypatch, torn, log, **over):
    monkeypatch.setattr(tb, "Log", lambda out, quiet=False: log)
    monkeypatch.setattr(S, "claim_slot", lambda *a, **k: fake_slot(torn))
    monkeypatch.setattr(S, "stage_disks", over.get("stage_disks", lambda *a, **k: "x"))
    monkeypatch.setattr(S, "stage_writable", over.get("stage_writable", lambda *a, **k: None))
    monkeypatch.setattr(S, "Session", over.get("Session", lambda *a, **k: FakeSession()))


def test_the_slot_is_torn_down_when_the_session_cannot_be_built(monkeypatch, tmp_path):
    torn, log = [], FakeLog()

    def fail(*a, **k):
        raise RuntimeError("no session")

    patch_run(monkeypatch, torn, log, Session=fail)
    assert tb.run(args(out=str(tmp_path / "o"))) == 2
    assert torn == [1]
    assert log.closed


def test_the_slot_is_torn_down_when_staging_the_disks_fails(monkeypatch, tmp_path):
    torn, log = [], FakeLog()

    def fail(*a, **k):
        raise OSError("disk full")

    patch_run(monkeypatch, torn, log, stage_disks=fail)
    assert tb.run(args(out=str(tmp_path / "o"))) == 2
    assert torn == [1]
    assert log.closed


def test_the_log_is_closed_when_staging_fails_before_a_slot_is_claimed(monkeypatch, tmp_path):
    torn, log = [], FakeLog()

    def fail(*a, **k):
        raise OSError("read-only")

    patch_run(monkeypatch, torn, log, stage_writable=fail)
    assert tb.run(args(out=str(tmp_path / "o"))) == 2
    assert torn == []
    assert log.closed


def test_a_terminate_that_fails_still_closes_the_log_and_tears_the_slot_down(monkeypatch, tmp_path):
    torn, log = [], FakeLog()
    sess = FakeSession()

    def bad_terminate():
        raise OSError("kill failed")

    sess.terminate = bad_terminate
    patch_run(monkeypatch, torn, log, Session=lambda *a, **k: sess)
    monkeypatch.setattr(tb, "to_world", lambda *a, **k: True)
    monkeypatch.setattr(tb, "resident_area", lambda s, log=None: 20)   # ends the run early
    assert tb.run(args(out=str(tmp_path / "o"))) == 1
    assert torn == [1]
    assert log.closed


def stalled_run(monkeypatch, tmp_path, screen=None, stall=None, shot=None):
    """A run whose `begin_adventuring` fails, with the three readings replaceable."""
    torn, log = [], FakeLog()
    sess = FakeSession()
    sess.begin_adventuring = lambda: False
    sess.screen = screen or (lambda: SimpleNamespace(rows=lambda: ["", " BEGIN ADVENTURING  "]))
    sess.stall_capture = stall or (lambda: "C64 PC 1234")
    calls = []

    def screenshot(path, **kw):
        calls.append((path, kw))
        return True if shot is None else shot()

    sess.kbd = SimpleNamespace(screenshot=screenshot)
    patch_run(monkeypatch, torn, log, Session=lambda *a, **k: sess)
    assert tb.run(args(out=str(tmp_path / "o"))) == 2
    assert torn == [] and sess.terminated and log.closed
    [failed] = log.kinds("step_failed")
    assert failed["step"] == "begin_adventuring"
    return failed, calls, log


def raises(*a, **k):
    raise OSError("the monitor went away")


def test_a_failed_setup_step_logs_the_screen_the_stall_and_a_picture(monkeypatch, tmp_path):
    failed, calls, _ = stalled_run(monkeypatch, tmp_path)
    assert failed["rows"] == [" BEGIN ADVENTURING"]
    assert failed["stall"] == "C64 PC 1234"
    [(path, kw)] = calls
    assert pathlib.Path(path).name == "begin_adventuring-failed.png"
    assert kw == {"timeout": tb.STALL_SHOT_TIMEOUT}
    assert failed["shot"] == path


def test_a_failed_step_with_no_text_screen_says_so(monkeypatch, tmp_path):
    failed, _, _ = stalled_run(monkeypatch, tmp_path, screen=lambda: None)
    assert failed["rows"] == "no readable text screen"


def test_a_failed_step_whose_screen_read_raises_still_ends_the_run(monkeypatch, tmp_path):
    failed, _, _ = stalled_run(monkeypatch, tmp_path, screen=raises)
    assert failed["rows"].startswith("unreadable: OSError")
    assert failed["stall"] == "C64 PC 1234"


def test_a_failed_step_whose_stall_capture_raises_still_ends_the_run(monkeypatch, tmp_path):
    failed, _, _ = stalled_run(monkeypatch, tmp_path, stall=raises)
    assert failed["stall"].startswith("unreadable: OSError")
    assert failed["rows"] == [" BEGIN ADVENTURING"]


def test_a_failed_step_whose_screenshot_raises_logs_shot_failed(monkeypatch, tmp_path):
    failed, _, log = stalled_run(monkeypatch, tmp_path, shot=raises)
    assert failed["shot"] is None
    [bad] = log.kinds("shot_failed")
    assert bad["label"] == "begin_adventuring-failed" and "OSError" in bad["error"]


def test_a_failed_step_whose_screenshot_is_refused_names_no_picture(monkeypatch, tmp_path):
    failed, _, log = stalled_run(monkeypatch, tmp_path, shot=lambda: False)
    assert failed["shot"] is None
    assert not log.kinds("shot_failed")


def test_a_refused_argument_combination_closes_the_log(monkeypatch, tmp_path):
    torn, log = [], FakeLog()
    patch_run(monkeypatch, torn, log)
    assert tb.run(args(out=str(tmp_path / "o"), mode="flee")) == 1
    assert log.closed


# -- the last review ----------------------------------------------------------


def boom(m):
    raise OSError("the handler fell over")


def test_nothing_is_armed_once_the_trap_has_degraded():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm("boom", 0x1234, boom, store=True, once=False)
    machine.store(0x1234)
    connect(sess)                                   # the trigger phase fails
    assert traps.degraded
    traps.arm_result()
    assert machine.checkpoints == {}
    assert traps.log.kinds("arm_skipped")


def test_a_handler_failure_while_retiring_releases_the_machine_and_degrades():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm("boom", 0x1234, boom)
    machine.exec_at(0x1234)
    machine.calls.clear()
    traps.retire_exec()
    assert traps.degraded
    assert machine.checkpoints == {}
    assert machine.calls[-1] == "resume"


def test_a_run_whose_retire_failed_does_not_exit_zero(monkeypatch, tmp_path):
    machine = Machine()
    sess = FakeSession(machine)

    def retire_with_a_failure(sess_, traps, *a, **k):
        traps.arm("boom", 0x1234, boom)
        machine.exec_at(0x1234)
        traps.retire_exec()

    monkeypatch.setattr(S, "claim_slot", lambda *a, **k: fake_slot([]))
    monkeypatch.setattr(S, "stage_disks", lambda *a, **k: "x")
    monkeypatch.setattr(S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(S, "Session", lambda *a, **k: sess)
    monkeypatch.setattr(tb, "to_world", lambda *a, **k: True)
    monkeypatch.setattr(tb, "resident_area", lambda s, log=None: 0)
    monkeypatch.setattr(tb, "trigger", lambda s, traps, *a, **k: traps.brawl_started() or 1)
    monkeypatch.setattr(tb, "after_fight", retire_with_a_failure)
    assert tb.run(args(out=str(tmp_path / "o"))) == 4


def test_retiring_deletes_the_result_stop_too():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm_result()
    traps.retire_exec()
    assert machine.checkpoints == {}


def test_ignored_result_stores_are_logged_a_few_times_then_counted():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm_result()
    for _ in range(10):
        machine.store(tb.RESULT, pc=0x1234)
        connect(sess)
    assert len(traps.readings["result_store_ignored"]) == tb.IGNORED_LOGGED
    traps.finish()
    assert traps.readings["result_store_ignored_total"][0]["count"] == 10


def run_main(monkeypatch, capsys, checked, lines):
    def fake_check(root, load=None, out=print):
        for line in lines:
            out(line)
        return checked

    monkeypatch.setattr(tb, "check_code", fake_check)
    monkeypatch.setattr(tb.runlog, "catch_signals", lambda: None)
    monkeypatch.setattr(tb, "run", lambda a: 0)
    rc = tb.main(["run", "--save", "x.d64", "--disks", "/d"])
    return rc, capsys.readouterr().err


def test_main_says_why_when_a_disk_file_cannot_be_read(monkeypatch, capsys):
    rc, err = run_main(monkeypatch, capsys, 2, ["cannot read POST.COM under /d: nope"])
    assert rc == 1
    assert "cannot read POST.COM under /d: nope" in err
    assert "differs" not in err


def test_main_says_the_disks_differ_on_a_mismatch(monkeypatch, capsys):
    rc, err = run_main(monkeypatch, capsys, 1, ["POST.COM $091B ..."])
    assert rc == 1
    assert "differs" in err


def test_main_runs_when_the_disks_match(monkeypatch, capsys):
    rc, err = run_main(monkeypatch, capsys, 0, [])
    assert rc == 0 and err == ""


# -- 15. the brawl's allies ---------------------------------------------------


def brawl_battle():
    """Party member 4 at (5,5), an ally (index 41) beside it, a monster (20) three squares off."""
    from automap.combat import Battle, Combatant, MapGeometry
    shape = MapGeometry(map_base=0x1000, stride=16, width=16, height=16,
                        positions=0x2000, count=64)
    people = tuple(Combatant(index=i, x=x, y=5, slot=0, pose=0, on_map=True,
                             initiative=1, hp=10)
                   for i, x in ((4, 5), (41, 6), (20, 9)))
    return Battle(shape=shape, terrain=bytes(256), combatants=people, camera=(0, 0))


def brawl_machine():
    machine = Machine()
    for n, side in ((4, 0), (41, 0), (20, 1)):
        machine.mem[tb.COMBATANTS + n * tb.STRIDE] = 1
        machine.mem[tb.COMBATANTS + n * tb.STRIDE + tb.SIDE] = side
    machine.mem[tb.ACTING] = 4
    return machine


def test_win_mode_never_aims_at_a_combatant_on_the_party_side():
    sess = FakeSession(brawl_machine())
    sess.fight_battle = brawl_battle()
    assert [c.index for c in sess.battle().enemies] == [41, 20]   # the game's own reading
    tactic = tb.Tactic(sess, FakeLog(), args())
    tactic(sess, None)
    tactic(sess, None)
    assert sess.aimed_at == [[20], [20]]
    assert "battle" not in vars(sess)                               # put back after the turn


def test_an_attack_ally_prompt_is_answered_no_and_the_turn_is_passed():
    sess = FakeSession(brawl_machine())
    sess.fight_battle = brawl_battle()
    log = FakeLog()
    sess.script = ["ATTACK ALLY: YES NO"]
    tactic = tb.Tactic(sess, log, args())
    assert tactic(sess, None) == "done"
    assert sess.picked == ["NO"]
    assert sess.turns == ["melee", "combat_turn"]
    assert log.kinds("attack_ally_refused")


def test_no_prompt_leaves_the_melee_answer_alone():
    sess = FakeSession(brawl_machine())
    sess.fight_battle = brawl_battle()
    tactic = tb.Tactic(sess, FakeLog(), args())
    assert tactic(sess, None) == "melee"
    assert sess.picked == []


@pytest.mark.parametrize("outcome", [S.BUDGET, "WON"])
def test_the_fight_end_gets_a_picture_and_a_prediction_on_every_outcome(
        monkeypatch, tmp_path, outcome):
    machine = brawl_machine()
    sess = FakeSession(machine)
    log = FakeLog()
    monkeypatch.setattr(tb, "Log", lambda out, quiet=False: log)
    sess.fight = lambda **k: S.FightResult(outcome, 372, 901.0, [], [], 0, [])
    run_with(monkeypatch, sess, tmp_path)
    [end] = log.kinds("fight_end")
    assert end["outcome"] == outcome
    assert end["predicted"] == 0                     # side 0 stands, nobody ran
    assert end["standing"] == {0: 2, 1: 1}
    assert pathlib.Path(end["shot"]).name == "fight-end.png"
    assert FakeSession.kbd.timeouts[FakeSession.kbd.shots.index(end["shot"])] \
        == tb.STALL_SHOT_TIMEOUT


def test_a_fight_end_with_unreadable_blocks_says_why_there_is_no_prediction(tmp_path):
    sess = FakeSession()
    log = FakeLog()

    def gone(timeout=5.0):
        raise OSError("monitor gone")

    sess.mon = gone
    tb.fight_end(sess, log, tmp_path, S.BUDGET)
    [end] = log.kinds("fight_end")
    assert end["predicted"] is None and "OSError" in end["predicted_why"]


def test_an_experience_delta_with_no_share_reading_says_why(monkeypatch, tmp_path):
    _, log = after(monkeypatch, tmp_path, (7, 3, 0))
    deltas = log.kinds("experience_delta")
    assert all(d["predicted"] is None for d in deltas)
    assert all(d["predicted_why"].startswith("no share reading") for d in deltas)


def still_after(monkeypatch, tmp_path, row24):
    machine = Machine()
    machine.mem[SQUARE:SQUARE + 3] = bytes((76, 47, 197))
    sess = FakeSession(machine)
    sess.combat = True
    sess.script = [row24]
    answered = []

    def answer(*a, **k):
        answered.append(1)
        sess.combat = False
        return {"outcome": "quiet", "rows": [row24]}

    monkeypatch.setattr(tb, "answer_until", answer)
    log = FakeLog()
    tb.after_fight(sess, tb.Traps(sess, log, tmp_path, args()), log, tmp_path, args(), [
        {"slot": i, "experience": 0, "flags": 0} for i in range(8)])
    return sess, log, answered


@pytest.mark.parametrize("row24,kind", [
    ("VIEW AIM USE QUICK DONE", S.BAR_COMMAND),
    ("MOVE/ATTACK, MOVE LEFT = 3", S.BAR_MOVE),
    ("GUARD DELAY QUIT SPEED EXIT", S.BAR_DONE)])
def test_a_party_still_on_a_turn_bar_is_not_read_as_off_the_map(
        monkeypatch, tmp_path, row24, kind):
    sess, log, answered = still_after(monkeypatch, tmp_path, row24)
    assert answered == []                  # its unknown-row exit would end the run with 5
    assert not log.kinds("off_map")
    assert log.kinds("still_fighting") == [{"row24": row24, "bar": kind}]
    assert len(log.kinds("experience_delta")) == 8
    assert sess.shots == []


@pytest.mark.parametrize("row24", ["VIEW TAKE POOL SHARE EXIT", "GO BACK LEAVE TREASURE"])
def test_the_treasure_bars_in_combat_mode_are_still_walked(monkeypatch, tmp_path, row24):
    sess, log, answered = still_after(monkeypatch, tmp_path, row24)
    assert answered == [1]
    assert not log.kinds("still_fighting")
    assert log.kinds("after_fight")


def test_battle_is_put_back_when_melee_turn_raises():
    sess = FakeSession(brawl_machine())
    sess.fight_battle = brawl_battle()

    def boom(state):
        raise OSError("the monitor went away")

    sess.melee_turn = boom
    tactic = tb.Tactic(sess, FakeLog(), args())
    with pytest.raises(OSError):
        tactic(sess, None)
    assert "battle" not in vars(sess)
    assert sess.battle() is sess.fight_battle


def test_a_no_that_cannot_be_selected_leaves_the_prompt_to_the_fight_loop():
    sess = FakeSession(brawl_machine())
    sess.fight_battle = brawl_battle()
    sess.no_taken = False
    log = FakeLog()
    sess.script = ["ATTACK ALLY: YES NO"]
    assert tb.Tactic(sess, log, args())(sess, None) == ""
    assert sess.picked == ["NO"]
    assert sess.turns == ["melee"] and sess.returns == 0
    assert log.kinds("attack_ally_refused")[0]["answered"] is False


def test_after_no_the_move_sub_bar_is_backed_out_of_before_the_turn_is_passed():
    sess = FakeSession(brawl_machine())
    sess.fight_battle = brawl_battle()
    sess.bar_after_no = S.CombatBar(S.BAR_MOVE, "MOVE/ATTACK, MOVE LEFT = 3", 3)
    sess.script = ["ATTACK ALLY: YES NO"]
    assert tb.Tactic(sess, FakeLog(), args())(sess, None) == "done"
    assert sess.returns == 1
    assert sess.turns == ["melee", "combat_turn"]


def test_flee_mode_reads_no_combatant_blocks_for_sides():
    machine = brawl_machine()
    sess = FakeSession(machine)
    tactic = tb.Tactic(sess, FakeLog(), args(mode="flee", stay=1), Flee())
    tactic.calls = 1
    reads = []
    real = FakeMon.read
    FakeMon.read = lambda self, a, n: reads.append((a, n)) or real(self, a, n)
    try:
        tactic(sess, None)
    finally:
        FakeMon.read = real
    assert (tb.COMBATANTS, tb.BLOCKS * tb.STRIDE) not in reads


REAL_FIGHT = S.Session.fight


class WatchSession(FakeSession):
    """A fight over, the world not back, and row 24 on the city watch's question."""

    def __init__(self, machine=None):
        super().__init__(machine)
        self.combat = True
        self.script = ["STAY RUN"]

    def mode(self):
        return S.COMBAT

    def screen(self):
        s = super().screen()
        if s is not None:
            s.text = lambda: s.row(24)
        return s

    def idle(self, seconds):
        self.idled = getattr(self, "idled", 0) + 1
        if self.idled > 50:
            raise AssertionError("the fight kept polling the city watch's row")

    def fight(self, budget=300.0, tactic=None, poll=1.0, stop=None):
        return REAL_FIGHT(self, budget=budget, tactic=tactic, poll=poll, stop=stop)


def test_the_fight_ends_at_the_city_watch_row_once_the_result_is_stored(monkeypatch, tmp_path):
    machine = brawl_machine()
    sess = WatchSession(machine)
    log = FakeLog()
    monkeypatch.setattr(tb, "Log", lambda out, quiet=False: log)
    monkeypatch.setattr(tb.Traps, "arm_result", lambda self: setattr(self, "result_done", True))
    run_with(monkeypatch, sess, tmp_path)
    [end] = log.kinds("fight_end")
    assert end["outcome"] == S.ENDED
    assert [r["outcome"] for r in log.kinds("fight_result")] == [S.ENDED]


def test_the_city_watch_row_before_the_result_is_stored_does_not_end_the_fight():
    sess = FakeSession()
    traps = tb.Traps(sess, FakeLog(), pathlib.Path("."), args())
    assert not traps.result_done
    assert not tb.watch_prompt_up(traps, FakeScreen("STAY RUN"))
    traps.result_done = True
    assert tb.watch_prompt_up(traps, FakeScreen("STAY RUN"))
    assert not tb.watch_prompt_up(traps, FakeScreen("VIEW AIM USE QUICK DONE"))
    assert not tb.watch_prompt_up(traps, None)


def test_a_failed_trap_still_ends_the_fight_at_the_city_watch_row(monkeypatch, tmp_path):
    machine = brawl_machine()
    machine.mem[tb.COMBATANTS + 20 * tb.STRIDE] = 0x90        # the monster side is down
    sess = WatchSession(machine)
    log = FakeLog()
    monkeypatch.setattr(tb, "Log", lambda out, quiet=False: log)
    monkeypatch.setattr(tb.Traps, "arm_result", lambda self: setattr(self, "degraded", True))
    run_with(monkeypatch, sess, tmp_path)
    [end] = log.kinds("fight_end")
    assert end["outcome"] == S.ENDED
    assert "result_unread" in end


def test_a_working_trap_leaves_no_unread_result_note(tmp_path):
    sess = FakeSession()
    log = FakeLog()
    traps = tb.Traps(sess, log, tmp_path, args())
    traps.result_done = True
    tb.fight_end(sess, log, tmp_path, S.ENDED, traps)
    assert "result_unread" not in log.kinds("fight_end")[0]


def test_a_transient_timeout_reading_the_hit_count_is_retried():
    machine = Machine()
    sess, traps = installed(machine)
    seen = []
    traps.arm("boom", 0x1234, lambda m: seen.append(1), store=True, once=False)
    machine.store(0x1234)
    real = FakeMon.checkpoint_hits
    fails = [1]

    def flaky(self, n):
        if fails:
            fails.pop()
            raise TimeoutError("timed out")
        return real(self, n)

    FakeMon.checkpoint_hits = flaky
    try:
        connect(sess)
    finally:
        FakeMon.checkpoint_hits = real
    assert not traps.degraded
    assert seen == [1]
    assert len(traps.log.kinds("trap_retry")) == 1


def test_a_persistent_timeout_reading_the_hit_count_degrades_the_trap():
    machine = Machine()
    sess, traps = installed(machine)
    traps.arm("boom", 0x1234, lambda m: None, store=True, once=False)

    def dead(self, n):
        raise TimeoutError("timed out")

    real = FakeMon.checkpoint_hits
    FakeMon.checkpoint_hits = dead
    try:
        connect(sess)
    finally:
        FakeMon.checkpoint_hits = real
    assert traps.degraded
    assert len(traps.log.kinds("trap_retry")) == tb.HITS_RETRIES - 1


def test_a_failed_trap_does_not_end_a_fight_with_both_sides_standing():
    sess = WatchSession(brawl_machine())
    traps = tb.Traps(sess, FakeLog(), pathlib.Path("."), args())
    traps.degraded = True
    assert not tb.watch_prompt_up(traps, FakeScreen("STAY RUN"), sess)
    sess.machine.mem[tb.COMBATANTS + 20 * tb.STRIDE] = 0x90
    assert tb.watch_prompt_up(traps, FakeScreen("STAY RUN"), sess)
