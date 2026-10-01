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


def test_save_is_refused_once_pokes_were_written_even_after_turning_off():
    s = Fake(3)
    s._refuse_save()  # nothing written yet: allowed
    s.suppress_encounters()
    s.no_encounters = False
    for save in (S.Session.save_game, curserun.CurseSession.save_game):
        with pytest.raises(RuntimeError, match="pokes"):
            save(s)
    s._restored_unattached = True
    with pytest.raises(RuntimeError, match="snapshot was restored"):
        S.Session.save_game(s, allow_suppressed=True)


def test_a_flag_on_with_nothing_written_does_not_refuse():
    s = Fake(0x50)  # world map: an entry with no pokes
    s.suppress_encounters()
    s._refuse_save()


def test_allow_suppressed_is_keyword_only():
    for save in (S.Session.save_game, curserun.CurseSession.save_game):
        with pytest.raises(TypeError):
            save(Fake(3), "x.d64", True)


def test_ambush_skip_works_alone_and_makes_a_save_refuse():
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


def test_curse_save_is_refused_after_a_restore():
    s = Fake(3, on=False)
    s._restored_unattached = True
    with pytest.raises(RuntimeError, match="snapshot was restored"):
        curserun.CurseSession.save_game(s)
