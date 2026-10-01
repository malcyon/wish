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
    # A sheet whose bar has no ITEMS on it, and one that never closes.
    "sheet_bare": (["VIEW:EXIT"], "VIEW:EXIT"),
    "stuck_sheet": (["ITEMS", "EXIT"], "ITEMS"),
    # A bar with EXIT on it that is none of the treasure screens.
    "shop": (["BUY", "VIEW", "APPRAISE", "EXIT"], "BUY"),
}
SHEETS = ("sheet", "sheet_bare", "stuck_sheet")
SHEET_BODY = "GUY DE VALOIS  HIT POINTS 95/95  ARMOR CLASS 6"


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
                 partial_share=0, opening=True, then="share",
                 walk_fails=False, drop_on=None):
        self.pages_before, self.pages_after = pages_before, pages_after
        self.lag = lag
        #: How many reads of the share page catch it half drawn.
        self.partial_share = partial_share
        #: What `enter_world` would have read off the save: the opening
        #: scene is due. False is a party already in the world.
        self.opening_scene = opening
        #: The screen the first run of pages leads to.
        self.then = then
        self.walk_fails = walk_fails
        #: The screen whose first XTEST Return the game never sees.
        self.drop_on = drop_on
        self.bars: list[str] = []
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
                if name == "Return" and game.drop_on == game.where:
                    game.drop_on = None
                elif name == "Return":
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
        body = SHEET_BODY if w in SHEETS else w
        # Text only, as `Screen.text()` reads it: the highlight is colour.
        return Screen(body, " ".join(words))

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
                self._go(self.then, BARS.get(self.then, (None, None))[1])
        elif w == "share":
            self._go("treasure", "VIEW")
        elif w == "treasure":
            if hl == "VIEW":
                self._go("sheet", "ITEMS")
            elif hl == "EXIT":
                self._go("leave", "GO BACK")
            else:
                self.took.append(hl)
        elif w == "sheet_bare":
            self._go("treasure", "VIEW")
        elif w == "shop":
            self.took.append(f"shop {hl}")
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
        self.bars.append(label)
        if self.walk_fails or self.where not in BARS \
                or label not in " ".join(BARS[self.where][0]):
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


@pytest.mark.parametrize("body, bar, kind", [
    ("", "VIEW TAKE POOL SHARE EXIT", "treasure"),
    ("", "GO BACK LEAVE TREASURE", "leave"),
    (SHEET_BODY, "ITEMS EXIT", "sheet"),
    (SHEET_BODY, "EXIT", "sheet"),
    (SHEET_BODY, "VIEW:ITEMS EXIT", "sheet"),
    (SHEET_BODY, "VIEW:EXIT", "sheet"),
    ("", "ITEMS EXIT", None),
    ("", WORLD, None),
    ("", "READY TRADE DROP EXIT", None),
    ("", "BUY VIEW APPRAISE EXIT", None),
    ("", PAGE, None),
])
def test_closing_screen_reads_the_measured_bars(body, bar, kind):
    assert SSB.closing_screen(Screen(body, bar)) == kind


def test_a_treasure_bar_outside_the_opening_scene_is_not_left(clock):
    """A won fight's treasure: leaving it would discard what the party has
    not taken, so nothing is pressed and the call says why."""
    game = PrologueGame(start="treasure", opening=False)
    out = SSB.clear_messages(game)
    assert out.startswith("(stopped at 'VIEW TAKE POOL SHARE EXIT'")
    assert "discard" in out
    assert game.visited == ["treasure"]
    assert game.bars == [] and game.kernal == [] and game.xtest == []


def test_the_leave_question_outside_the_opening_scene_goes_back(clock):
    game = PrologueGame(start="leave", opening=False)
    out = SSB.clear_messages(game)
    assert game.bars == ["GO BACK"]
    assert game.visited == ["leave", "treasure"]
    assert out.startswith("(stopped at 'VIEW TAKE POOL SHARE EXIT'")


def test_the_opening_is_spent_once_its_treasure_is_left(clock):
    game = PrologueGame(start="treasure", lag=1)
    SSB.clear_messages(game)
    assert game.opening_scene is False


def test_a_sheet_with_no_items_on_its_bar_is_left_through_exit(clock):
    game = PrologueGame(start="sheet_bare", lag=1)
    assert "ENCAMP" in SSB.clear_messages(game)
    assert game.visited[:3] == ["sheet_bare", "treasure", "leave"]


def test_a_sheet_that_never_closes_stops_after_a_few_tries(clock):
    game = PrologueGame(start="stuck_sheet", lag=0)
    out = SSB.clear_messages(game)
    assert game.bars == ["EXIT"] * SSB.MAX_CLOSING_TRIES
    assert out.startswith("(stopped at 'ITEMS EXIT'")


def test_a_bar_that_cannot_be_walked_stops_after_a_few_tries(clock):
    game = PrologueGame(start="treasure", walk_fails=True)
    out = SSB.clear_messages(game)
    assert game.bars == ["EXIT"] * SSB.MAX_CLOSING_TRIES
    assert out.startswith("(stopped at")


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
        return 5 if self.where in ("share", "treasure", "leave", *SHEETS) \
            else 1

    def iec_stall_check(self):
        return False

    def stall_capture(self):
        return "captured"


def _menu_game(monkeypatch, due: bool, **kw) -> MenuGame:
    game = MenuGame(**kw)
    monkeypatch.setattr(SSB, "overlay_mode",
                        lambda sess, addr, errors=None: game.mode())
    monkeypatch.setattr(SSB, "impossible_side", lambda *a, **k: None)
    monkeypatch.setattr(SSB, "idle_in_key_window", lambda sess, addr: None)
    monkeypatch.setattr(SSB, "opening_scene_due", lambda sess: due,
                        raising=False)
    return game


def test_enter_world_without_the_idle_exit_takes_the_scene_to_the_world(
        clock, monkeypatch):
    game = _menu_game(monkeypatch, True, lag=2)
    assert SSB.enter_world(game, object(), timeout=600.0, fix=False,
                           stop_at_idle=False) is True
    assert "sheet" not in game.visited and game.took == []
    assert "after" in game.visited


def test_enter_world_stops_at_treasure_when_no_opening_is_due(
        clock, monkeypatch):
    game = _menu_game(monkeypatch, False, lag=2)
    assert SSB.enter_world(game, object(), timeout=600.0, fix=False,
                           stop_at_idle=False) is False
    assert "leave" not in game.visited and "after" not in game.visited
    assert any("discard" in line for line in game.logged)


def test_enter_world_presses_nothing_at_an_unrecognised_exit_bar(
        clock, monkeypatch):
    """A shop or camp bar in the world carries EXIT too; it is not one of
    the screens `enter_world` knows, so no EXIT is chosen there."""
    game = _menu_game(monkeypatch, True, then="shop")
    SSB.enter_world(game, object(), timeout=120.0, fix=False,
                    stop_at_idle=False)
    assert game.where == "shop"
    assert game.bars == [] and game.took == []


def test_opening_scene_due_reads_the_save_in_the_drive(tmp_path):
    from support.silverblades import _save_disk
    shipped = _save_disk()          # SSI's own party, not yet set out
    sess = type("S", (), {"save_disk": str(shipped)})()
    assert SSB.opening_scene_due(sess) is True
    sess.save_disk = str(tmp_path / "missing.D64")
    assert SSB.opening_scene_due(sess) is False


def test_opening_scene_due_is_false_for_a_party_already_out(tmp_path):
    import gamedata
    root = gamedata.specimen_root()
    found = sorted((root / "por-c64").glob(
        "WISH-SPEC-ssb-d-engine-resave-walked.[dD]64")) if root else []
    if not found:
        pytest.skip("needs the C64 specimen WISH-SPEC-ssb-d-engine-resave-"
                    "walked (a party the engine saved after walking)")
    sess = type("S", (), {"save_disk": str(found[0])})()
    assert SSB.opening_scene_due(sess) is False


def test_the_resave_walk_arrives_through_the_opening_scene(clock,
                                                           monkeypatch):
    game = PrologueGame(lag=2)
    monkeypatch.setattr(SSB, "enter_world", lambda sess, addr, **kw: True)

    class Log:
        def say(self, *a):
            pass

    assert ssbresavewalk.arrive(game, object(), Log()) == "world"


def test_a_dropped_return_on_leave_treasure_is_answered_again(clock):
    """The question still up after LEAVE TREASURE is still the opening's:
    it gets LEAVE TREASURE again, never GO BACK."""
    game = PrologueGame(start="treasure", lag=1, drop_on="leave")
    assert "ENCAMP" in SSB.clear_messages(game)
    assert game.bars.count(SSB.LEAVE_TREASURE) == 2
    assert SSB.GO_BACK not in game.bars


def test_a_save_that_cannot_be_read_is_logged_with_its_path(tmp_path):
    logged: list[str] = []
    where = tmp_path / "missing.D64"
    sess = type("S", (), {"save_disk": str(where),
                          "log": lambda self, line: logged.append(line)})()
    assert SSB.opening_scene_due(sess) is False
    assert len(logged) == 1 and str(where) in logged[0]


def test_walk_proof_walks_nothing_when_the_world_bar_never_came(monkeypatch):
    from tools.secret_of_the_silver_blades import ssbwarp
    stopped = ("(stopped at 'VIEW TAKE POOL SHARE EXIT': a treasure bar "
               "outside the opening scene; leaving it would discard the "
               "treasure, so nothing was pressed)")
    monkeypatch.setattr(ssbwarp, "clear_messages", lambda sess: stopped)

    class Sess:
        def __getattr__(self, name):
            raise AssertionError(f"walk_proof touched sess.{name}")

    out = ssbwarp.walk_proof(Sess())
    assert out["refused"] == stopped and out["moved"] is False
