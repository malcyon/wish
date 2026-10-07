"""`--fight-watch` on Pool's walk-fight: each command bar is recorded with the
watched character's combat state, from reads alone."""

from __future__ import annotations

import json
from types import SimpleNamespace

from goldbox.c64_port import POOL_OF_RADIANCE
from goldbox.savegame import ROSTER_COMBAT_SIDE, ROSTER_SLOT_INDEX
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
    # The byte a read at record + 0x10C would hit: the next record's 0x0C.
    memory[BOX.slot_area_base + (RECORD_SLOT + 1) * BOX.slot_stride + 0x0C] = 0x99
    base = BOX.roster_base + ROSTER_SLOT * BOX.roster_stride
    memory[base] = status
    memory[base + ROSTER_SLOT_INDEX] = RECORD_SLOT
    memory[base + ROSTER_COMBAT_SIDE] = 0x41
    return memory


def _who(name, index, on_map=True):
    return SimpleNamespace(name=name, index=index, x=index, y=2, slot=index,
                           on_map=on_map, hp=11, side=0, is_party=True)


class _Session:
    def __init__(self, bars, memory, combatants):
        self.bars, self.memory, self.kbd = bars, memory, _Keyboard()
        self.combatants, self.shown = combatants, None
        self.writes = 0
        self.polls, self.between, self.outcome = [], {}, A.S.WON

    def screen(self):
        return self.shown

    def battle(self):
        return SimpleNamespace(combatants=self.combatants, characters=self.combatants)

    def acting(self, battle, s=None):
        panel = s.row(3)
        return next(c for c in battle.characters if c.name in panel)

    def mon(self, timeout):
        return _Monitor(self.memory)

    def fight(self, budget, tactic, stop=None, poll=1.0):
        self.polls.append(poll)
        for bar, panel in self.bars:
            self.shown = _Screen(bar, panel)
            tactic(self, A.S.CombatBar(A.S.BAR_COMMAND, bar))
            # Messages the engine prints for a turn it runs, between two bars.
            for row in self.between.get(bar + panel, []):
                shown = _Screen("", "")
                shown.rows[20] = row
                stop(self, shown)
        return A.S.FightResult(self.outcome, len(self.bars), 1.0, ["VIEW MOVE DONE"],
                               ["BRUTUS HITS"])


def _run(tmp_path, monkeypatch, combatants, watch="brutus", between=None,
         outcome=A.S.WON):
    sess = _Session([("VIEW MOVE DONE", "ROLAND"), ("VIEW MOVE DONE", "BRUTUS")],
                    _memory(), combatants)
    sess.between = between or {}
    sess.outcome = outcome
    run = A.PoolRun(sess, A.Log(tmp_path), tmp_path, POOL_OF_RADIANCE, {})
    run.fight_watch = watch
    run.to_world = lambda: True
    run.position = lambda: [5, 5, 0]
    run.walk_side_prompts, run.walk_side_open = [], set()
    melee = []
    monkeypatch.setattr(A.S.Session, "melee_turn", lambda s, bar: melee.append(bar) or "MOVE")
    try:
        run._fight_out(0, [], [], False, A.S.ENCOUNTER_FIGHT, 0)
    except A.StepFailed:
        pass
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
        assert (bar["status"], bar["record_0b8"], bar["combat_side"]) == (3, 0xFE, 0x41)
        assert "record_10c" not in bar
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
    sess.fight = lambda budget, tactic, stop=None, **kw: (
        seen.append((tactic, kw)), A.S.FightResult(A.S.WON, 0, 1.0, [], []))[1]
    run.to_world = lambda: True
    run.position = lambda: [5, 5, 0]
    run.walk_side_prompts, run.walk_side_open = [], set()
    run._fight_out(0, [], [], False, A.S.ENCOUNTER_FIGHT, 0)
    assert seen == [(A.S.Session.melee_turn, {})]


def test_a_message_between_two_bars_is_logged_and_captured_at_the_faster_poll(
        tmp_path, monkeypatch):
    party = [_who("ROLAND", 0), _who("BRUTUS", 5)]
    between = {"VIEW MOVE DONEROLAND": ["BRUTUS HITS THE ORC", "THE ORC MISSES"]}
    run, sess, _, events = _run(tmp_path, monkeypatch, party, between=between)
    lines = [e for e in events if e.get("kind") == "fight-watch-line"]
    assert [(e["text"], e["after_bar"], e["named"]) for e in lines] == [
        ("BRUTUS HITS THE ORC", 0, True)]
    assert (tmp_path / f"{lines[0]['screen']}.png").exists()
    assert sess.polls == [A.WATCH_POLL_SECONDS] and A.WATCH_POLL_SECONDS < 1.0


def test_a_lost_fight_still_logs_its_lines_and_the_watched_hit_points(
        tmp_path, monkeypatch):
    party = [_who("ROLAND", 0), _who("BRUTUS", 5)]
    _, _, _, events = _run(tmp_path, monkeypatch, party, outcome=A.S.LOST)
    (end,) = [e for e in events if e.get("kind") == "fight-watch-end"]
    assert end["lines"] == ["BRUTUS HITS"] and end["outcome"] == A.S.LOST
    assert (end["hp"], end["status"]) == (11, 3)


def _hook_run(tmp_path, reads, inner=None):
    """Feed READS (lists of row-20 texts) to a watch_stop hook; return the
    run, the events and how many times `inner` was asked."""
    run = A.PoolRun(_Session([], {}, []), A.Log(tmp_path), tmp_path, POOL_OF_RADIANCE, {})
    run.fight_watch = "brutus"
    asked = []
    hook = run.watch_stop(lambda sess, screen: asked.append(screen) or False)
    for text in reads:
        shown = _Screen("", "")
        shown.rows[20] = text
        shown.rows[22] = ""
        hook(run.sess, shown)
    run.log.close()
    events = [json.loads(line) for line in (tmp_path / "run.jsonl").read_text().splitlines()]
    return run, events, asked


def _lines(events):
    return [e["text"] for e in events if e.get("kind") == "fight-watch-line"]


def test_a_row_unchanged_across_two_reads_is_logged_once(tmp_path):
    _, events, asked = _hook_run(tmp_path, ["THE ORC MISSES"] * 2)
    assert _lines(events) == ["THE ORC MISSES"] and len(asked) == 2


def test_an_alternating_row_is_logged_once_per_distinct_text(tmp_path):
    run, events, asked = _hook_run(
        tmp_path, ["BRUTUS HITS", "THE ORC MISSES", "BRUTUS HITS", "THE ORC MISSES"])
    assert _lines(events) == ["BRUTUS HITS", "THE ORC MISSES"]
    assert len(list((tmp_path).glob("*line*.png"))) == 1
    assert run.watch_counts == {"BRUTUS HITS": 2, "THE ORC MISSES": 2}
    assert len(asked) == 4


def test_an_error_inside_watch_read_is_logged_and_inner_still_runs(tmp_path, monkeypatch):
    run = A.PoolRun(_Session([], {}, []), A.Log(tmp_path), tmp_path, POOL_OF_RADIANCE, {})

    def boom(screen):
        raise OSError("disk full")

    monkeypatch.setattr(run, "watch_read", boom)
    asked = []
    hook = run.watch_stop(lambda sess, screen: asked.append(screen) or True)
    assert hook(run.sess, _Screen("", "")) is True and len(asked) == 1
    run.log.close()
    events = [json.loads(line) for line in (tmp_path / "run.jsonl").read_text().splitlines()]
    (err,) = [e for e in events if e.get("kind") == "fight-watch-error"]
    assert "OSError" in err["error"] and "disk full" in err["error"]
