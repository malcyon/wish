"""`ssbsession.clear_messages` and `enter_world` take a Silver Blades party
that has not yet set out through the close of the opening scene (#801).

`PrologueGame` plays the screens as one live boot read them
(`~/.cache/wish/acceptance/432/sheetfix/probe1/`): pages answered by Return,
the starting-treasure bar with VIEW highlighted, the sheet VIEW opens with
ITEMS highlighted, `GO BACK LEAVE TREASURE` with GO BACK highlighted, three
more pages, the move sub-bar, the world bar. A key is taken at once, but the
screen it answered stays drawn for `lag` more reads, as a page does while
the next one loads; a second Return sent then reaches the next screen.
"""

from __future__ import annotations

import pytest
from support.partymenu import ENTRIES, menu_screen

from tools.secret_of_the_silver_blades import ssbresavewalk
from tools.secret_of_the_silver_blades import ssbsession as SSB

PAGE = "PRESS BUTTON OR RETURN TO CONTINUE."
SHARE = "PRESS (RETURN) OR BUTTON TO CONTINUE"
WORLD = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"
SUBBAR = "I,J,K,M, RETURN OR BUTTON"

#: Each bar's words in order, and where its highlight opens.
BARS = {
    "treasure": (["VIEW", "TAKE", "POOL", "SHARE", "EXIT"], "VIEW"),
    "sheet": (["ITEMS", "EXIT"], "ITEMS"),
    "leave": (["GO BACK", "LEAVE TREASURE"], "GO BACK"),
    "items": (["READY", "DROP", "EXIT"], "READY"),
}


class Screen:
    def __init__(self, body: str, bar: str):
        self.body, self.bar = body, bar

    def text(self) -> str:
        return f"{self.body}\n{self.bar}"

    def row(self, n: int) -> str:
        return self.bar if n == 24 else ""


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s


class PrologueGame:
    """The scene's close; `where` is the screen the game is really on."""

    def __init__(self, start="page", pages_before=3, pages_after=3, lag=2,
                 partial_share=0):
        self.pages_before, self.pages_after = pages_before, pages_after
        self.lag = lag
        #: How many reads of the share page catch it half drawn.
        self.partial_share = partial_share
        self.where, self.page, self.hl = start, 0, None
        if start in BARS:
            self.hl = BARS[start][1]
        self.shown_for = 0
        self.stale: Screen | None = None
        self.visited: list[str] = [start]
        self.kernal: list[int] = []
        self.xtest: list[str] = []
        self.took: list[str] = []
        self.logged: list[str] = []
        game = self

        class Kbd:
            def key(self, name, *a):
                game.xtest.append(name)
                if name == "Return":
                    game.choose()

        self.kbd = Kbd()

    # -- what the game draws --------------------------------------------
    def _draw(self) -> Screen:
        w = self.where
        if w == "page":
            return Screen(f"PROLOGUE PAGE {self.page}", PAGE)
        if w == "share":
            return Screen("EACH SHARE IS 2500 EXPERIENCE POINTS", SHARE)
        if w == "after":
            return Screen(f"CLOSING PAGE {self.page}", PAGE)
        if w == "subbar":
            return Screen("", SUBBAR)
        if w == "world":
            return Screen("PANEL", WORLD)
        if w == "unknown":
            return Screen("SOMETHING", "NOBODY KNOWS THIS BAR")
        words, _ = BARS[w]
        return Screen(f"{w} hl={self.hl}", " ".join(words))

    def screen(self):
        if self.stale is not None and self.shown_for < self.lag:
            self.shown_for += 1
            return self.stale
        self.stale = None
        if self.where == "share" and self.partial_share:
            self.partial_share -= 1
            return Screen("EACH SHARE", SHARE)
        return self._draw()

    def _go(self, where, hl=None, page=0):
        self.stale = self._draw()
        self.shown_for = 0
        self.where, self.hl, self.page = where, hl, page
        self.visited.append(where)

    # -- keys ------------------------------------------------------------
    def choose(self):
        w, hl = self.where, self.hl
        if w == "page":
            if self.page + 1 < self.pages_before:
                self._go("page", page=self.page + 1)
            else:
                self._go("share")
        elif w == "share":
            self._go("treasure", "VIEW")
        elif w == "treasure":
            if hl == "VIEW":
                self._go("sheet", "ITEMS")
            elif hl == "EXIT":
                self._go("leave", "GO BACK")
            else:
                self.took.append(hl)
        elif w == "sheet":
            if hl == "ITEMS":
                self._go("items", "READY")
            else:
                self._go("treasure", "VIEW")
        elif w == "leave":
            if hl == "GO BACK":
                self._go("treasure", "EXIT")
            else:
                self._go("after", page=0)
        elif w == "after":
            if self.page + 1 < self.pages_after:
                self._go("after", page=self.page + 1)
            else:
                self._go("subbar")
        elif w == "subbar":
            self._go("world")

    def press_kernal(self, code):
        self.kernal.append(code)
        if code == 0x0D:
            self.choose()

    def select_bar(self, label, **kw):
        if self.where not in BARS or label not in BARS[self.where][0]:
            return False
        self.hl = label
        self.kbd.key("Return")
        return True

    def handle_prompt(self, s=None):
        return False

    def log(self, *a):
        self.logged.append(" ".join(str(x) for x in a))


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(SSB.time, "time", c.time)
    monkeypatch.setattr(SSB.time, "sleep", c.sleep)
    return c


def test_the_opening_scene_reaches_the_world_bar_without_opening_a_sheet(
        clock):
    game = PrologueGame(lag=2)
    assert "ENCAMP" in SSB.clear_messages(game)
    assert game.where == "world"
    assert "sheet" not in game.visited and "items" not in game.visited
    assert game.took == []
    assert "Escape" not in game.xtest


def test_each_page_gets_one_return_while_it_is_still_drawn(clock):
    game = PrologueGame(pages_before=8, pages_after=3, lag=3)
    SSB.clear_messages(game)
    # 8 pages, the share page, 3 pages and the sub-bar: one Return each.
    assert game.kernal == [0x0D] * (8 + 1 + 3 + 1)


def test_a_page_read_half_drawn_gets_no_second_return(clock):
    """The half-drawn page finishing is not the page going: the Return sent
    then would reach the treasure bar's VIEW and open a sheet."""
    game = PrologueGame(lag=2, partial_share=2)
    assert "ENCAMP" in SSB.clear_messages(game)
    assert "sheet" not in game.visited


def test_a_sheet_already_open_is_left_through_exit_not_items(clock):
    game = PrologueGame(start="sheet", lag=2)
    assert "ENCAMP" in SSB.clear_messages(game)
    assert "items" not in game.visited
    assert game.visited[:3] == ["sheet", "treasure", "leave"]


def test_go_back_is_never_chosen(clock):
    game = PrologueGame(start="treasure", lag=1)
    SSB.clear_messages(game)
    assert game.visited == ["treasure", "leave", "after", "after", "after",
                            "subbar", "world"]


def test_an_unknown_bar_gets_no_key(clock):
    game = PrologueGame(start="unknown")
    out = SSB.clear_messages(game, timeout=60.0)
    assert out.startswith("(never got the command bar back")
    assert game.kernal == [] and game.xtest == []


@pytest.mark.parametrize("bar, kind", [
    ("VIEW TAKE POOL SHARE EXIT", "treasure"),
    ("GO BACK LEAVE TREASURE", "leave"),
    ("ITEMS EXIT", "sheet"),
    (WORLD, None),
    ("READY TRADE DROP EXIT", None),
    (PAGE, None),
])
def test_closing_screen_reads_the_measured_bars(bar, kind):
    assert SSB.closing_screen(Screen("", bar)) == kind


class MenuGame(PrologueGame):
    """The party menu first, as `enter_world` meets it; the mode byte is 0
    there, 1 on the pages and 5 on POST.COM's bars."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.where = "menu"
        self.visited = ["menu"]
        self.walked = False

    def _draw(self):
        if self.where == "menu":
            return menu_screen(ENTRIES.index("BEGIN ADVENTURING")
                               if self.walked else 3)
        return super()._draw()

    def choose(self):
        if self.where == "menu":
            self._go("page", page=0)
        else:
            super().choose()

    def select_row(self, label, **walk):
        self.walked = label == "BEGIN ADVENTURING"
        return self.walked

    def mode(self):
        if self.where == "menu":
            return 0
        return 5 if self.where in BARS or self.where == "share" else 1

    def iec_stall_check(self):
        return False

    def stall_capture(self):
        return "captured"


def test_enter_world_without_the_idle_exit_takes_the_scene_to_the_world(
        clock, monkeypatch):
    game = MenuGame(lag=2)
    monkeypatch.setattr(SSB, "overlay_mode",
                        lambda sess, addr, errors=None: game.mode())
    monkeypatch.setattr(SSB, "impossible_side", lambda *a, **k: None)
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: None)
    assert SSB.enter_world(game, object(), timeout=600.0, fix=False,
                           stop_at_idle=False) is True
    assert "sheet" not in game.visited and game.took == []


def test_the_resave_walk_arrives_through_the_opening_scene(clock,
                                                           monkeypatch):
    game = PrologueGame(lag=2)
    monkeypatch.setattr(SSB, "enter_world", lambda sess, addr, **kw: True)

    class Log:
        def say(self, *a):
            pass

    assert ssbresavewalk.arrive(game, object(), Log()) == "world"
