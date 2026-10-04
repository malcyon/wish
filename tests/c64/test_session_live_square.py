"""`Session.live_square`: where a walking party stands, out of memory.

Pool of Radiance keeps two copies of the dungeon square.  `$49C0`-`$49C2` is
written only when the game saves, so it holds the square of the last save
while the party walks; `$C04B`-`$C04D` moves on the key.  On the travel grid
the square is the pair `$49C3`/`$49C4`.  No emulator: a monitor over a dict.
"""

from conftest import load_tools_module

from goldbox import c64_port as G

S = load_tools_module("session")

LIVE_XY = 0xC04B


class FakeMonitor:
    def __init__(self, memory: dict[int, int], asked: list):
        self.memory = memory
        self.asked = asked

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, addr: int, length: int) -> bytes:
        self.asked.append(addr)
        return bytes(self.memory.get(addr + i, 0) for i in range(length))


class FakeSession(S.Session):
    def __init__(self, memory: dict[int, int], game=G.POOL_OF_RADIANCE):
        self.game = game
        self.memory = memory
        self.asked: list[int] = []
        self.messages: list[str] = []

    def mon(self, timeout: float = 5.0):
        return FakeMonitor(self.memory, self.asked)

    def log(self, *a):
        self.messages.append(" ".join(str(x) for x in a))


def _put(memory, addr, values):
    for i, v in enumerate(values):
        memory[addr + i] = v


def _indoors_after_a_step():
    """New Phlan after one step south from 9,13: the save copy still holds
    9,13 and the live triple 9,14."""
    memory: dict[int, int] = {S.INDOORS_AT: 1}
    _put(memory, S.DUNGEON_XY, (9, 13, 2))
    _put(memory, LIVE_XY, (9, 14, 2))
    return memory


def test_a_pool_party_indoors_stands_on_the_live_square(monkeypatch):
    monkeypatch.setattr(S.time, "sleep", lambda _s: None)
    sess = FakeSession(_indoors_after_a_step())
    assert sess.live_square() == (9, 14, 2)
    assert S.DUNGEON_XY not in sess.asked


def test_square_still_answers_the_save_copy_indoors(monkeypatch):
    """The control: `square()` is the last save's square indoors."""
    monkeypatch.setattr(S.time, "sleep", lambda _s: None)
    sess = FakeSession(_indoors_after_a_step())
    assert sess.square() == (9, 13)


def test_a_pool_party_on_the_travel_grid_stands_on_the_travel_pair():
    memory: dict[int, int] = {S.INDOORS_AT: 0}
    _put(memory, S.TRAVEL_XY, (7, 28))
    _put(memory, LIVE_XY, (15, 1, 0))
    sess = FakeSession(memory)
    assert sess.live_square() == (7, 28, None)
    assert LIVE_XY not in sess.asked


def test_a_curse_party_stands_on_the_live_triple(monkeypatch):
    monkeypatch.setattr(S.time, "sleep", lambda _s: None)
    memory: dict[int, int] = {}
    _put(memory, LIVE_XY, (3, 12, 1))
    sess = FakeSession(memory, G.CURSE_OF_THE_AZURE_BONDS)
    assert sess.live_square() == (3, 12, 1)
    assert S.INDOORS_AT not in sess.asked
