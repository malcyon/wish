"""`no_encounters`: area pokes before each move key, the rest byte, the save guard."""

import pytest
from conftest import load_tools_module

S = load_tools_module("session")
from goldbox import c64_port as G  # noqa: E402
from tools.curse_of_the_azure_bonds import curserun  # noqa: E402


class FakeMon:
    def __init__(self, mem, log):
        self.mem, self.log = mem, log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, addr, n, **kw):
        return bytes(self.mem.get(addr + i, 0) for i in range(n))

    def write(self, addr, data, **kw):
        self.log.append(("poke", addr, data[0]))
        for i, b in enumerate(data):
            self.mem[addr + i] = b

    def resume(self):
        pass


class Fake(S.Session):
    game = G.CURSE_OF_THE_AZURE_BONDS

    def __init__(self, area, on=True):
        self.mem = {S.AREA_BYTE[self.game.key].addr: area}
        self.events = []
        self.lines = []
        self.no_encounters = on
        self._restored_unattached = False

    def mon(self, timeout=5.0):
        return FakeMon(self.mem, self.events)

    def log(self, *a):
        self.lines.append(" ".join(map(str, a)))


def pokes(s):
    return [(a, v) for k, a, v in s.events if k == "poke"]


def test_listed_area_gets_its_pokes():
    s = Fake(0x03)
    s.suppress_encounters()
    assert pokes(s) == [(0x4C02, 8), (0x4C2A, 1)]


def test_nothing_is_written_when_off():
    s = Fake(0x03, on=False)
    s.suppress_encounters()
    s.suppress_rest_interruption(FakeMon(s.mem, s.events))
    assert s.events == []


@pytest.mark.parametrize("game,area,want", [
    (G.CURSE_OF_THE_AZURE_BONDS, 0x02, [(0x4C2C, 5)]),
    (G.CURSE_OF_THE_AZURE_BONDS, 0x01, [(0x4C0C, 6)]),
    (G.SECRET_OF_THE_SILVER_BLADES, 0x10, [(0x4C2D, 0)]),
    (G.POOL_OF_RADIANCE, 0x14, [(0x4A80, 15)]),
    (G.POOL_OF_RADIANCE, 0x06, [(0x4A64, 0)]),
])
def test_each_title_uses_its_own_area_byte_and_table(game, area, want):
    class T(Fake):
        pass
    T.game = game
    s = T(area)
    s.mem = {S.AREA_BYTE[game.key].addr: area}
    s.suppress_encounters()
    assert pokes(s) == want


def test_unlisted_area_is_logged_once_and_writes_nothing():
    s = Fake(0x07)
    s.suppress_encounters()
    s.suppress_encounters()
    assert pokes(s) == []
    assert len(s.lines) == 1 and "not suppressed" in s.lines[0]


def test_world_map_ambush_skip_is_opt_in():
    s = Fake(0x50)
    s.suppress_encounters()
    assert pokes(s) == []
    assert s.lines == []
    s.skip_world_map_ambushes = True
    s.suppress_encounters()
    assert (0x4C83, 1) in pokes(s) and (0x4C8E, 2) in pokes(s)


@pytest.mark.parametrize("game,addr", [
    (G.POOL_OF_RADIANCE, 0x6DD2), (G.CURSE_OF_THE_AZURE_BONDS, 0x7ED2),
    (G.SECRET_OF_THE_SILVER_BLADES, 0x7ED2)])
def test_rest_byte_is_zeroed(game, addr):
    class T(Fake):
        pass
    T.game = game
    s = T(1)
    s.mem[addr] = 40
    s.suppress_rest_interruption(FakeMon(s.mem, s.events))
    assert s.mem[addr] == 0


def test_save_is_rejected_once_pokes_were_written_even_after_turning_off():
    s = Fake(3)
    s._check_save_allowed()  # nothing written yet: allowed
    s.suppress_encounters()
    s.no_encounters = False
    for save in (S.Session.save_game, curserun.CurseSession.save_game):
        with pytest.raises(RuntimeError, match="pokes"):
            save(s)
    s._restored_unattached = True
    with pytest.raises(RuntimeError, match="snapshot was restored"):
        S.Session.save_game(s, allow_suppressed=True)


def test_a_flag_on_with_nothing_written_does_not_reject():
    s = Fake(0x50)  # world map: an entry with no pokes
    s.suppress_encounters()
    s._check_save_allowed()


def test_allow_suppressed_is_keyword_only():
    for save in (S.Session.save_game, curserun.CurseSession.save_game):
        with pytest.raises(TypeError):
            save(Fake(3), "x.d64", True)


def test_ambush_skip_works_alone_and_makes_a_save_reject():
    s = Fake(0x50, on=False)
    s.skip_world_map_ambushes = True
    s.suppress_encounters()
    assert (0x4C83, 1) in pokes(s)
    with pytest.raises(RuntimeError, match="pokes"):
        curserun.CurseSession.save_game(s)


def test_a_snapshot_records_pokes_and_a_restore_puts_the_value_back(tmp_path):
    from test_session_snapshot import Fake as SnapFake

    s = SnapFake(tmp_path)
    s.snapshot("clean")
    s._pokes_written = True
    s.snapshot("dirty")
    s.restore("clean")
    assert s._pokes_written is False
    s.restore("dirty")
    assert s._pokes_written is True
    s.discard_snapshot("dirty")
    import os
    assert not os.path.exists(s._pokes_record("dirty"))


def test_a_fresh_boot_clears_the_record(monkeypatch):
    s = Fake(3)
    s._pokes_written = True

    class Stop(Exception):
        pass

    def launch():
        raise Stop

    s.launch = launch
    with pytest.raises(Stop):
        s.boot()
    assert s._pokes_written is False


def test_a_title_missing_from_a_table_says_which(monkeypatch):
    class T(Fake):
        pass
    s = T(1)
    s.game = type("G", (), {"key": "no-such-title"})()
    with pytest.raises(KeyError, match="no-such-title"):
        s.suppress_encounters()
    with pytest.raises(KeyError, match="rest byte"):
        s.suppress_rest_interruption(FakeMon({}, []))


def test_outdoor_key_writes_pokes_before_the_digit():
    order = []

    class Screen:
        def row(self, r):
            return "1-8, RETURN OR BUTTON" if r == 24 else ""

    class Kbd:
        def key(self, *a):
            order.append("key")

    s = Fake(3)
    s.suppress_encounters = lambda: order.append("poke")
    s.kbd = Kbd()
    s.screen = lambda: Screen()
    assert s.outdoor_key("3")
    assert order == ["poke", "key"]


def test_curse_walk_writes_pokes_before_the_key(monkeypatch):
    class W(curserun.CurseSession):
        def __init__(self):
            self.__dict__.update(Fake(0x03).__dict__)
            self.trail = []

        def mon(self, timeout=5.0):
            return FakeMon(self.mem, self.events)

        def enter_move(self, answer_prompts=True):
            return True

        def steady_triple(self, seconds=None):
            return (1, 1, 0)

        def move_key(self, move, hold=0.15, gap=0.30):
            self.trail.append(("key", len(pokes(self))))

        def screen(self):
            return None

    w = W()
    monkeypatch.setattr(S.time, "sleep", lambda *_: None)
    w.walk_one("I", patience=0.01)
    assert w.trail == [("key", 2)]


def test_base_walk_writes_pokes_before_the_key():
    from test_session_walk_movebar import FakeSession

    order = []

    class W(FakeSession):
        def suppress_encounters(self):
            order.append("poke")

        def move_key(self, move, hold=0.15, gap=0.30):
            order.append("key")

    assert W().walk_one("I")
    assert order == ["poke", "key"]


def test_curse_save_is_rejected_after_a_restore():
    s = Fake(3, on=False)
    s._restored_unattached = True
    with pytest.raises(RuntimeError, match="snapshot was restored"):
        curserun.CurseSession.save_game(s)


# -- putting the gates back before a save ---------------------------------------


class Sticky(FakeMon):
    """A monitor whose writes to `stuck` addresses are lost."""

    def __init__(self, mem, log, stuck):
        super().__init__(mem, log)
        self.stuck = stuck

    def write(self, addr, data, **kw):
        if addr in self.stuck:
            self.log.append(("poke", addr, data[0]))
            return
        super().write(addr, data, **kw)


def test_restore_puts_back_every_original_reads_it_back_and_lifts_the_block():
    s = Fake(0x03)
    s.mem.update({0x4C02: 3, 0x4C2A: 0})
    s.suppress_encounters()
    s.suppress_encounters()
    assert (s.mem[0x4C02], s.mem[0x4C2A]) == (8, 1)
    with pytest.raises(RuntimeError, match="pokes"):
        s._check_save_allowed()
    rows = s.restore_encounter_gates()
    assert (s.mem[0x4C02], s.mem[0x4C2A]) == (3, 0)
    assert [(r["address"], r["original"], r["written"], r["action"],
             r["read_back"], r["verified"]) for r in rows] == [
        ("$4C02", 3, 8, "restored", 3, True),
        ("$4C2A", 0, 1, "restored", 0, True)]
    assert s.no_encounters is False
    s._check_save_allowed()  # verified: the save may run
    assert s.restore_encounter_gates() == []


def test_a_gate_that_reads_back_wrong_raises_and_the_save_stays_blocked():
    s = Fake(0x03)
    s.mem.update({0x4C02: 3, 0x4C2A: 0})
    s.suppress_encounters()
    s.mon = lambda timeout=5.0: Sticky(s.mem, s.events, {0x4C02})
    with pytest.raises(S.GateRestoreError, match=r"\$4C02 was not restored to 3") as e:
        s.restore_encounter_gates()
    bad = [r for r in e.value.rows if not r["verified"]]
    assert [(r["address"], r["read_back"]) for r in bad] == [("$4C02", 8)]
    with pytest.raises(RuntimeError, match="pokes"):
        S.Session.save_game(s)
    assert list(s._gates_held) == [0x4C02]


def test_a_value_the_game_wrote_while_held_is_not_overwritten_by_a_guess():
    s = Fake(0x03)
    s.mem.update({0x4C02: 3, 0x4C2A: 0})
    s.suppress_encounters()
    s.mem[0x4C02] = 5           # the game's own write
    s.suppress_encounters()     # forced back to 8; 5 is lost
    assert s.mem[0x4C02] == 8
    s.events.clear()
    with pytest.raises(S.GateRestoreError, match="the game wrote 5"):
        s.restore_encounter_gates()
    assert (0x4C02, 3) not in pokes(s)
    with pytest.raises(RuntimeError, match="pokes"):
        s._check_save_allowed()


def test_a_write_with_no_recorded_original_cannot_be_restored():
    s = Fake(0x03)
    s._pokes_written = True
    with pytest.raises(S.GateRestoreError, match="not recorded"):
        s.restore_encounter_gates()


def _travel(area=0x1A, script=None):
    class T(Fake):
        game = G.POOL_OF_RADIANCE
    s = T(area)
    roll = S.POOL_TRAVEL_ROLLS[area]
    for i, b in enumerate(S.POOL_TRAVEL_ROLL if script is None else script):
        s.mem[roll + i] = b
    return s, roll


@pytest.mark.parametrize("area", (0x19, 0x1A, 0x1B))
def test_the_travel_grid_check_compares_against_a_value_no_roll_returns(area):
    s, roll = _travel(area)
    zero = roll + S.POOL_TRAVEL_ROLL_ZERO
    assert s.mem[zero] == 0
    s.suppress_encounters()
    s.suppress_encounters()      # already poked: the guard still holds
    assert pokes(s) == [(zero, 0xFF), (zero, 0xFF)]
    rows = s.restore_encounter_gates()
    assert s.mem[zero] == 0
    assert rows[0]["action"] == "restored" and rows[0]["verified"]


def test_a_travel_gate_writes_nothing_over_another_script():
    other = bytes(len(S.POOL_TRAVEL_ROLL))
    s, roll = _travel(script=other)
    s.suppress_encounters()
    assert pokes(s) == []
    assert any("not suppressed" in line for line in s.lines)
    s._check_save_allowed()


def test_a_script_the_area_reloaded_over_the_poke_is_left_alone():
    s, roll = _travel()
    s.suppress_encounters()
    for i in range(len(S.POOL_TRAVEL_ROLL)):
        s.mem[roll + i] = 0x55      # another window's script
    s.events.clear()
    rows = s.restore_encounter_gates()
    assert pokes(s) == []
    assert rows[0]["action"] == "script replaced" and rows[0]["verified"]
    s._check_save_allowed()


def test_a_snapshot_keeps_the_originals_a_restore_needs(tmp_path):
    from test_session_snapshot import Fake as SnapFake

    s = SnapFake(tmp_path)
    s._pokes_written = True
    s._gates_held = {0x4C02: {"area": 3, "original": 3, "written": 8,
                              "guard": None, "game_changed": None}}
    s.snapshot("held")
    s._pokes_written, s._gates_held = False, None
    s.restore("held")
    assert s._pokes_written is True
    assert s._gates_held[0x4C02]["original"] == 3


def test_a_new_script_that_kept_the_poked_byte_is_not_verified():
    s, roll = _travel()
    zero = roll + S.POOL_TRAVEL_ROLL_ZERO
    s.suppress_encounters()
    s.mem[roll] = 0x55          # another script over the guard, not the poke
    assert s.mem[zero] == 0xFF
    s.events.clear()
    with pytest.raises(S.GateRestoreError, match="still holds the poke 255"):
        s.restore_encounter_gates()
    assert pokes(s) == []
    with pytest.raises(RuntimeError, match="pokes"):
        s._check_save_allowed()


def test_a_poke_left_in_memory_is_never_recorded_as_the_original():
    s, roll = _travel()
    zero = roll + S.POOL_TRAVEL_ROLL_ZERO
    s.mem[zero] = 0xFF          # left by a hold whose record is gone
    s.suppress_encounters()
    assert s._gates_held[zero]["original"] == 0
    s.restore_encounter_gates()
    assert s.mem[zero] == 0


def test_the_driving_guide_and_the_rule_give_the_same_save_condition():
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[2]
    guide = (repo / "docs/70-driving-the-game.md").read_text(encoding="utf-8")
    section = guide.split("## Suppressing encounters", 1)[1].split("\n## ", 1)[0]
    rule = (repo / ".claude/rules/emulator.md").read_text(encoding="utf-8")
    for text in (" ".join(section.split()), " ".join(rule.split())):
        assert "restore_encounter_gates()" in text
        assert "tools/c64/acceptance.py --no-encounters" in text
        assert "proves movement and saving, not combat" in text
        assert "leaves both off" not in text
