"""`tools/dos/acceptance.py`'s Curse `fight`: the walk to Tilverton's tavern
and its bar.

The fake draws the map bar, the status line's `x,y facing clock` and the
tavern's `PUNCH BARKEEP HAVE A DRINK LEAVE` as text in a stand-in font, as
DOS Curse draws them at 3,14 and at 6,10.  What is pinned: the walk follows
the area's map to the tavern and bans an edge it could not cross; the
tavern's bar is answered with `PUNCH BARKEEP` only once its text has been
read, with `LEAVE` once a fight has been met; and a bar whose text is
anything else is never answered and stops the step.
"""

from __future__ import annotations

import pytest

from tools.dos import acceptance as da
from tools.dos import dosbox

W, H = 320, 200
#: A stand-in font: glyph i lights row 1 with i + 1 and row 2 with 0x81.
_FONT_BLOCK = b"".join(bytes((0, i + 1, 0x81, 0, 0, 0, 0, 0))
                       for i in range(da.FONT_GLYPHS))
_FONT = da.font_table(_FONT_BLOCK)
_WHITE, _GREEN = b"\xff\xff\xff", b"\x55\xff\x55"

MAP_BAR = "AREA CAST VIEW ENCAMP SEARCH LOOK"
TAVERN_BAR = "PUNCH BARKEEP HAVE A DRINK LEAVE"
#: What `GAME.OVR` draws after the brawl begins, in the fake: some bar the
#: driver has no answer for.
AFTER_BAR = "ASK ABOUT INJURIES IGNORE THEM"
STEP = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}


def _draw(px: bytearray, row: int, col: int, text: str, ink: bytes) -> None:
    for i, ch in enumerate(text):
        glyph = _FONT_BLOCK[(ord(ch.upper()) % 0x40) * 8:][:8]
        for dy, bits in enumerate(glyph):
            for dx in range(8):
                if bits & (0x80 >> dx):
                    at = (((row * 8) + dy) * W + (col + i) * 8 + dx) * 3
                    px[at:at + 3] = ink


class OpenGeo:
    """A 16 by 16 map open everywhere but at `walls`, (x, y, facing)."""

    def __init__(self, walls=()):
        self.walls = set(walls)

    def is_passable(self, x, y, facing):
        return (x, y, facing) not in self.walls


class FakeTavern:
    """Tilverton from 3,14 facing east: arrows turn, `Up` steps unless the
    edge is in `doors` (a locked door the map draws open), and the step onto
    6,10 shows the tavern's bar.  `p` there starts what follows (`after`);
    `l` returns to the map.  `bar` replaces the tavern's text."""

    def __init__(self, tmp_path, doors=(), bar=TAVERN_BAR, after=AFTER_BAR):
        self.x, self.y, self.f = 3, 14, 1
        self.doors = set(doors)
        self.state = "map"
        self.tavern_bar, self.after_bar = bar, after
        self.keys: list[str] = []
        self.dir = tmp_path / "session"
        (self.dir / "shots").mkdir(parents=True)
        self.save_dir = self.dir / "SAVE"

    def frame(self) -> dosbox.Screen:
        px = bytearray(W * H * 3)
        bar = {"map": MAP_BAR, "tavern": self.tavern_bar,
               "after": self.after_bar}[self.state]
        _draw(px, da.BAR_ROW, 0, bar, _GREEN if self.state == "map" else _WHITE)
        _draw(px, da.STATUS_ROW, da.STATUS_CELLS[0] + 1,
              f"{self.x},{self.y} {'NESW'[self.f]} 01:15", _WHITE)
        return dosbox.Screen(W, H, bytes(px))

    def capture(self):
        return self.frame()

    def grab(self):
        return self.frame()

    def settle(self, quiet=0.6, timeout=30.0):
        return self.frame()

    def wait_until_ink(self, rect, want, timeout=30.0):
        return self.frame().ink(rect) == want

    def wait_while_ink(self, rect, same, timeout=30.0):
        return self.frame().ink(rect) != same

    def wait_while_glyphs(self, rect, same, timeout=30.0):
        return self.frame().glyphs(rect) != same

    def shot(self, name, allow_blank=False):
        path = self.dir / "shots" / f"{name}.png"
        path.write_bytes(b"x")
        return path

    def key(self, *keys, gap=0.35):
        for k in keys:
            self.keys.append(k)
            if self.state == "map" and k in ("Left", "Right"):
                self.f = (self.f + (1 if k == "Right" else -1)) % 4
            elif self.state == "map" and k == "Up":
                if (self.x, self.y, self.f) in self.doors:
                    continue
                dx, dy = STEP[self.f]
                self.x, self.y = self.x + dx, self.y + dy
                if (self.x, self.y) == da.CURSE_TAVERN:
                    self.state = "tavern"
            elif self.state == "tavern" and k == "p":
                self.state = "after"
            elif self.state == "tavern" and k == "l":
                self.state = "map"

    def attach(self):
        return True

    def run(self):
        pass


@pytest.fixture
def clock(monkeypatch):
    """A clock that moves a second each time the step reads it."""
    now = [1000.0]

    def tick():
        now[0] += 1.0
        return now[0]

    monkeypatch.setattr(da.time, "time", tick)


@pytest.fixture
def font(monkeypatch):
    monkeypatch.setattr(da.Driver, "display_font", lambda self: _FONT, raising=False)


def _driver(game, monkeypatch, geo=None):
    d = da.Driver(game, lambda **k: None, "A", "curse", party_size=5)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.record_world(game.capture())
    d.where = "map"
    monkeypatch.setattr(d, "_tavern_geo", lambda: (("GEO2.DAX block 1", geo) if geo
                                                    else ("in area 4", None)))
    return d


def _events(d, name):
    return [e for e in d.logged if e.get("event") == name]


def test_the_status_line_reads_as_a_square_and_a_facing(tmp_path):
    game = FakeTavern(tmp_path)
    assert da.status_place(game.frame(), _FONT) == (3, 14, 1)
    game.x, game.y, game.f = 12, 0, 3
    assert da.status_place(game.frame(), _FONT) == (12, 0, 3)
    blank = dosbox.Screen(W, H, bytes(W * H * 3))
    assert da.status_place(blank, _FONT) is None


def test_the_walk_follows_the_map_to_the_tavern_and_punches_the_barkeep(
        tmp_path, monkeypatch, font, clock):
    game = FakeTavern(tmp_path)
    d = _driver(game, monkeypatch, OpenGeo())
    with pytest.raises(da.StepFailed, match="stayed 60 s"):
        d.fight(600)
    # Seven squares, three north and four east in some order, then `p` once
    # at the tavern's bar and nothing at the bar after it.
    assert game.keys.count("Up") == 7 and game.keys[-1] == "p"
    assert game.keys.count("p") == 1 and game.state == "after"
    assert [(e["answer"], e["bar"]) for e in _events(d, "tavern")] == [
        ("punch", TAVERN_BAR)]
    assert _events(d, "fight-route")[0]["route"] is True
    kinds = [e["kind"] for e in _events(d, "fight-screen")]
    assert kinds[:2] == ["tavern", None]


def test_a_door_the_map_draws_open_is_banned_and_the_walk_goes_round(
        tmp_path, monkeypatch, font, clock):
    # North from 3,13 is the shortest way on an open map; the door there
    # never opens, so the walk bans it and plans again.
    game = FakeTavern(tmp_path, doors={(3, 13, 0)})
    d = _driver(game, monkeypatch, OpenGeo())
    with pytest.raises(da.StepFailed, match="stayed 60 s"):
        d.fight(600)
    assert game.state == "after" and game.keys.count("p") == 1


def test_without_the_area_map_the_walk_explores_as_before(tmp_path, monkeypatch, font):
    game = FakeTavern(tmp_path)
    d = _driver(game, monkeypatch, None)
    walker = d._fight_walker()
    assert type(walker) is da.Explorer
    assert _events(d, "fight-route") == [
        {"event": "fight-route", "route": False, "why": "in area 4", "target": None}]


def _tick_at(game, d):
    state = d._fight_state(True, None)
    walker = da.Explorer()
    return state, lambda: d._fight_tick(walker, da.status_column("curse"), None, state)


def test_the_tavern_bar_is_answered_with_punch_only_once_its_text_is_read(
        tmp_path, monkeypatch, clock):
    game = FakeTavern(tmp_path)
    d = _driver(game, monkeypatch)
    game.state = "tavern"
    reads = []
    monkeypatch.setattr(da.Driver, "display_font",
                        lambda self: reads.append(len(game.keys)) or _FONT, raising=False)
    _, tick = _tick_at(game, d)
    tick()
    assert game.keys == ["p"] and game.state == "after"
    assert reads and reads[0] == 0


def test_after_a_fight_the_tavern_bar_is_left(tmp_path, monkeypatch, font):
    game = FakeTavern(tmp_path)
    d = _driver(game, monkeypatch)
    game.state = "tavern"
    state, tick = _tick_at(game, d)
    state["met"] = True
    tick()
    assert game.keys == ["l"] and game.state == "map"
    assert _events(d, "tavern")[0]["answer"] == "leave"


@pytest.mark.parametrize("bar", [
    AFTER_BAR,                          # the bar after a won brawl, in the fake
    "PUNCH BARKEEP HAVE A DRINK",       # the tavern's words, but not all of them
    "PUNCH BARKEEP HAVE A DRINK LEAVE NOW",
])
def test_any_other_bar_is_never_answered_and_stops_the_step(tmp_path, monkeypatch,
                                                           font, clock, bar):
    game = FakeTavern(tmp_path, bar=bar)
    d = _driver(game, monkeypatch)
    game.state = "tavern"
    _, tick = _tick_at(game, d)
    with pytest.raises(da.StepFailed, match=f"stayed {da.FIGHT_PATIENCE:.0f} s"):
        for _ in range(200):
            tick()
    assert game.keys == [] and _events(d, "tavern") == []


def test_another_title_never_reads_a_bar_as_the_tavern(tmp_path, monkeypatch):
    game = FakeTavern(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "ssb", party_size=5)
    game.state = "tavern"

    def no_font(self):
        raise AssertionError("the font was read for Silver Blades")

    monkeypatch.setattr(da.Driver, "display_font", no_font, raising=False)
    assert d._tavern_kind(game.frame()) is None
