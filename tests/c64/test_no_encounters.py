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
        self.mem = {S.AREA_BYTE[self.game.key]: area}
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
    s.mem = {S.AREA_BYTE[game.key]: area}
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


def test_save_is_refused_while_on_and_the_override_gets_past():
    s = Fake(3)
    with pytest.raises(RuntimeError, match="no_encounters"):
        S.Session.save_game(s)
    with pytest.raises(RuntimeError, match="no_encounters"):
        curserun.CurseSession.save_game(s)
    s._restored_unattached = True
    with pytest.raises(RuntimeError, match="snapshot was restored"):
        S.Session.save_game(s, allow_suppressed=True)


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


def test_curse_save_is_refused_after_a_restore_with_encounters_off():
    s = Fake(3, on=False)
    s._restored_unattached = True
    with pytest.raises(RuntimeError, match="snapshot was restored"):
        curserun.CurseSession.save_game(s)
