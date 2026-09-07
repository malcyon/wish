"""A Curse or Silver Blades party in a dungeon is not on the travel grid (#360).

`Session.indoors()` read `$49E6` whatever title was running.  That is Pool of
Radiance's indoors flag: Curse of the Azure Bonds and Secret of the Silver
Blades load their save page at `$4B00`, so `$49E6` in those two is a byte of
`LIBRARY` code, it reads zero, and the driver concluded the party was on the
travel grid.  `walk_one` then dispatched to `walk_outdoors`, which threw the
direction letter away because `I` is not a compass digit -- so a party
standing in a corridor was sent no key at all and the step came back the same
`False` a wall gives.

Measured on pool slot 6 on 2026-09-07 with a Silver Blades party: the status
line read `S 0:09 3,12`, `$C04B` read `03 0c 02`, and `$49E6` read `00`.

Nothing here needs an emulator.  `FakeSession` is a `Session` whose monitor,
screen, status and bars are all fixed answers, so what is under test is which
address the driver decides to ask and what it does with the answer.
"""

from conftest import load_tools_module

from goldbox import games as G

S = load_tools_module("session")

#: The two addresses this file is about: Pool of Radiance's indoors flag, and
#: the live square triple every title in the family keeps at the same place.
INDOORS_AT = S.INDOORS_AT
LIVE_XY = G.CURSE_OF_THE_AZURE_BONDS.live_position


class FakeMonitor:
    """A monitor over a dict of bytes that records every address asked for."""

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


class FakeKeyboard:
    def __init__(self):
        self.sent: list[str] = []

    def key(self, name, hold=0.0, gap=0.0):
        self.sent.append(name)


class FakeSession(S.Session):
    """A driven party standing at the dungeon's own move sub-bar.

    `status` answers a different square on the second reading, which is what
    a step that lands looks like to `walk_one`.  The memory is all zeroes,
    which is exactly the state that misled the real driver: `$49E6` reads
    zero in a running Curse because nothing put anything there.
    """

    def __init__(self, game=G.CURSE_OF_THE_AZURE_BONDS,
                 memory: dict[int, int] | None = None):
        self.game = game
        self.kbd = FakeKeyboard()
        self.asked: list[int] = []
        self.memory = dict(memory or {})
        self.walk_refused = None
        self._statuses = iter([(1, 100, 3, 12), (1, 100, 3, 13)])
        self.messages: list[str] = []

    def mon(self, timeout: float = 5.0):
        return FakeMonitor(self.memory, self.asked)

    def screen(self):
        class Row:
            def row(self, r):
                return S.MOVE_SUBBAR + ", RETURN OR BUTTON" if r == 24 else ""
        return Row()

    def status(self):
        return next(self._statuses, (1, 100, 3, 13))

    def select_bar(self, label, row=24, timeout=30.0):
        return False        # `MOVE` is not on the sub-bar, and need not be

    def leave_move(self, tries: int = 8):
        return True

    def log(self, *a):
        self.messages.append(" ".join(str(x) for x in a))


def test_a_curse_party_reads_as_indoors_without_any_byte_being_asked_for():
    """Curse has no travel grid, so there is nowhere else the party can be.

    `goldbox.games.Game.travel_grid` is the fact -- neither later title
    carries `SQRDATA`, `SQRPACI` or `WALLS` on any side of any disk -- and it
    settles the question without a read, which is what makes it safe: the
    byte that used to be read means nothing in these two titles.
    """
    sess = FakeSession()
    assert sess.indoors() is True
    assert sess.asked == []


def test_a_curse_party_is_walked_with_the_letter_the_caller_gave():
    """The step that `#360` reported as a wall without pressing anything."""
    sess = FakeSession()
    assert sess.walk_one("I") is True
    assert sess.kbd.sent == ["i"]
    assert sess.walk_refused is None


def test_curse_reads_its_own_live_square_and_not_pool_of_radiances():
    """`$C04B`, which `tools/cursewarp.py` has driven this title from since
    `#19` -- not `$49C0`, which in Curse is not the party's square."""
    sess = FakeSession(memory={LIVE_XY: 3, LIVE_XY + 1: 12})
    assert sess.square_and_world() == (3, 12, True)
    assert sess.asked == [LIVE_XY]


def test_pool_of_radiance_still_reads_its_flag_and_still_refuses_a_letter():
    """The control, and the behaviour that is right where it applies.

    Pool of Radiance does have a travel grid, `$49E6` does say which world
    the party is in, and `I` out there is a caller's mistake.  What changed
    is that the mistake now says it pressed nothing rather than answering the
    same `False` a wall gives.
    """
    sess = FakeSession(game=G.POOL_OF_RADIANCE, memory={INDOORS_AT: 0})
    assert sess.indoors() is False
    assert sess.walk_one("I") is False
    assert sess.kbd.sent == []
    assert "pressed nothing" in (sess.walk_refused or "")
