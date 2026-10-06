"""`--fight-watch` on Pool's walk-fight: each command bar is recorded with the
watched character's combat state, from reads alone."""

from __future__ import annotations

import json
from types import SimpleNamespace

from goldbox.c64_port import POOL_OF_RADIANCE
from goldbox.savegame import ROSTER_SLOT_INDEX
from tools.c64 import acceptance as A

BOX = A.c64_save.CONTAINERS[POOL_OF_RADIANCE.key]
RECORD_SLOT, ROSTER_SLOT = 5, 2


class _Screen:
    def __init__(self, bar, panel):
        self.rows = [""] * 25
        self.rows[3] = panel
        self.rows[22] = "THE ORC MISSES"
        self.rows[24] = bar

    def row(self, r):
        return self.rows[r]


class _Monitor:
    """Reads and resume only: any write is an AttributeError."""

    def __init__(self, memory):
        self.memory = memory

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, address, length):
        return bytes(self.memory.get(address + i, 0) for i in range(length))

    def resume(self):
        pass


class _Keyboard:
    def screenshot(self, path):
        open(path, "wb").close()


def _memory(status=0x03):
    memory = {}
    for i, name in enumerate([b"ROLAND", b"", b"", b"", b"", b"BRUTUS"]):
        for j, c in enumerate(name):
            memory[BOX.slot_area_base + i * BOX.slot_stride + j] = c
    memory[BOX.slot_area_base + RECORD_SLOT * BOX.slot_stride + 0x0B8] = 0xFE
    memory[BOX.slot_area_base + RECORD_SLOT * BOX.slot_stride + 0x10C] = 0x41
    base = BOX.roster_base + ROSTER_SLOT * BOX.roster_stride
    memory[base] = status
    memory[base + ROSTER_SLOT_INDEX] = RECORD_SLOT
    return memory


def _who(name, index, on_map=True):
    return SimpleNamespace(name=name, index=index, x=index, y=2, slot=index,
                           on_map=on_map, hp=11, side=0, is_party=True)


class _Session:
    def __init__(self, bars, memory, combatants):
        self.bars, self.memory, self.kbd = bars, memory, _Keyboard()
        self.combatants, self.shown = combatants, None
        self.writes = 0

    def screen(self):
        return self.shown

    def battle(self):
        return SimpleNamespace(combatants=self.combatants, characters=self.combatants)

    def acting(self, battle, s=None):
        panel = s.row(3)
        return next(c for c in battle.characters if c.name in panel)

    def mon(self, timeout):
        return _Monitor(self.memory)

    def fight(self, budget, tactic, stop=None):
        for bar, panel in self.bars:
            self.shown = _Screen(bar, panel)
            tactic(self, A.S.CombatBar(A.S.BAR_COMMAND, bar))
        return A.S.FightResult(A.S.WON, len(self.bars), 1.0, [], [])


def _run(tmp_path, monkeypatch, combatants, watch="brutus"):
    sess = _Session([("VIEW MOVE DONE", "ROLAND"), ("VIEW MOVE DONE", "BRUTUS")],
                    _memory(), combatants)
    run = A.PoolRun(sess, A.Log(tmp_path), tmp_path, POOL_OF_RADIANCE, {})
    run.fight_watch = watch
    run.to_world = lambda: True
    run.position = lambda: [5, 5, 0]
    run.walk_side_prompts, run.walk_side_open = [], set()
    melee = []
    monkeypatch.setattr(A.S.Session, "melee_turn", lambda s, bar: melee.append(bar) or "MOVE")
    run._fight_out(0, [], [], False, A.S.ENCOUNTER_FIGHT, 0)
    run.log.close()
    events = [json.loads(line) for line in (tmp_path / "run.jsonl").read_text().splitlines()]
    return run, sess, melee, events


def test_each_bar_logs_screen_text_owner_and_the_three_reads(tmp_path, monkeypatch):
    party = [_who("ROLAND", 0), _who("BRUTUS", 5)]
    run, sess, melee, events = _run(tmp_path, monkeypatch, party)
    bars = [e for e in events if e.get("kind") == "fight-watch"]
    assert len(bars) == 2 and len(melee) == 2
    assert [b["owner"]["name"] for b in bars] == ["ROLAND", "BRUTUS"]
    for bar in bars:
        assert (tmp_path / f"{bar['screen']}.png").exists()
        assert "THE ORC MISSES" in bar["text"]
        assert (bar["found"], bar["record_slot"], bar["roster_slot"]) == (True, 5, 2)
        assert (bar["status"], bar["record_0b8"], bar["record_10c"]) == (3, 0xFE, 0x41)
    assert bars[0]["screen"] != bars[1]["screen"]


def test_placement_is_recorded_once_at_the_first_bar(tmp_path, monkeypatch):
    party = [_who("ROLAND", 0), _who("BRUTUS", 5, on_map=False)]
    _, _, _, events = _run(tmp_path, monkeypatch, party)
    placed = [e for e in events if e.get("kind") == "fight-watch-placement"]
    assert len(placed) == 1
    assert placed[0]["present"] is True and placed[0]["on_map"] is False


def test_a_name_not_in_the_party_is_recorded_as_not_found(tmp_path, monkeypatch):
    party = [_who("ROLAND", 0), _who("BRUTUS", 5)]
    _, _, _, events = _run(tmp_path, monkeypatch, party, watch="nobody")
    bars = [e for e in events if e.get("kind") == "fight-watch"]
    assert [b["found"] for b in bars] == [False, False]
    assert events[[e.get("kind") for e in events].index("fight-watch-placement")]["present"] is False


def test_without_the_option_the_fight_is_fought_with_melee_turn_alone(tmp_path, monkeypatch):
    sess = _Session([], {}, [])
    run = A.PoolRun(sess, A.Log(tmp_path), tmp_path, POOL_OF_RADIANCE, {})
    seen = []
    sess.fight = lambda budget, tactic, stop=None: (
        seen.append(tactic), A.S.FightResult(A.S.WON, 0, 1.0, [], []))[1]
    run.to_world = lambda: True
    run.position = lambda: [5, 5, 0]
    run.walk_side_prompts, run.walk_side_open = [], set()
    run._fight_out(0, [], [], False, A.S.ENCOUNTER_FIGHT, 0)
    assert seen == [A.S.Session.melee_turn]
