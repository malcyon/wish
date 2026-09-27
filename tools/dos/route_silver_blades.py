"""The route through DOS Silver Blades' own screens: the command bars it draws and the steps between them.

`Route` reads the bar off the screen, waits for the one a step wants and
presses through the title, the party menu and the intro.  A wait bounded by a
`deadline` (`check`/`bound`) ends with the caller's route window; one without
takes its own timeout.
"""
from __future__ import annotations

import time

from tools.dos import dosbox

#: The party menu's highlight list: nine 8-pixel rows from y=96, read
#: between the left border and the mouse pointer the game parks at x=160.
MENU_RECT = (64, 96, 90, 72)
MENU_BEFORE = {"add": 1}
MENU_AFTER = {"view": 3, "save": 6, "begin": 7}

#: Command-bar digests (`Screen.glyphs(dosbox.BAR)`), measured off DOS Silver
#: Blades 1.30's own captures in the probe that mapped this route.  Each is one
#: bar at one highlight position.
BARS = {
    "87fc69d8225c82c7": "title",          # PLAY DEMO
    "9ea118ca48fdb5bb": "party_menu",     # CHOOSE A FUNCTION SELECT
    "927ce83f92814158": "add_from",       # ADD FROM WHERE? SECRET CURSE EXIT
    "e5d4ccb0f042e360": "add_list",       # ADD A CHARACTER: ADD EXIT
    "ff25bed811ead601": "add_list_added", # the same, EXIT highlighted
    "3be5f71ace63ae51": "pick_character", # PICK CHARACTER SELECT EXIT
    "35045663cfeb4dc5": "save_which",     # SAVE WHICH GAME: A B ... J
    "c1e280e0b635bf5b": "continue",       # PRESS <ENTER>/<RETURN> TO CONTINUE
    "0673632718086ca7": "treasure",       # VIEW TAKE POOL SHARE EXIT
    "ee8750d217378726": "treasure_left",  # (there is still treasure left) YES NO
    "daa8b33293560f31": "map",            # MOVE AREA CAST VIEW ENCAMP SEARCH LOOK
    "e61c9acccfc048ae": "move_mode",      # EXIT, after MOVE
    "190472fcf2345334": "camp",           # SAVE VIEW MAGIC REST ALTER FIX EXIT
    "1d00b47a4fdc6739": "camp",           # the same, VIEW highlighted
    "16b29f069ec9f8f7": "camp",           # the same, REST highlighted
    "0b48cd02f99dbdfd": "cure_anyway",    # (is not diseased) CURE ANYWAY: YES NO
    "a7e6e1e306491ae5": "rest_menu",      # REST DAYS HOURS MINS ADD SUBTRACT EXIT
    "7d9dc294ffc6763d": "quit_to_dos",    # QUIT TO DOS YES NO
    # The character sheet.  Where its highlight opens depends on the route
    # (HEAL from the party menu, the second word from camp), and whether CURE
    # is on it at all is what the experiment measures, so each is listed.
    "ad08d02bfc41ed3c": "sheet",          # HEAL CURE EXIT, HEAL highlighted
    "b12a60e0cba8e46d": "sheet",          # HEAL CURE EXIT, CURE highlighted
    "bd37ba2e14ba64cd": "sheet",          # HEAL EXIT, HEAL highlighted
    "570d9fcc5bf6d613": "sheet",          # HEAL EXIT, EXIT highlighted
}


class RouteLost(RuntimeError):
    """The game showed a screen the route did not expect."""


class Route:
    def __init__(self, session: dosbox.Session, note):
        self.s = session
        self.note = note
        self.n = 0

    def shot(self, label: str) -> str:
        self.n += 1
        name = f"{self.n:03d}-{label}"
        self.s.shot(name, allow_blank=True)
        return name

    def bar(self, screen: dosbox.Screen | None = None, deadline=None) -> str:
        """The bar's kind; a `deadline` (`check`/`bound`) cuts the settle to the route time left."""
        if screen is None:
            wait = 30.0 if deadline is None else deadline.bound(30.0, "reading the bar")
            screen = self.s.settle(quiet=0.6, timeout=wait)
        return BARS.get(screen.glyphs(dosbox.BAR), "?")

    def wait_bar(self, want: str, timeout: float = 45.0, deadline=None) -> dosbox.Screen:
        """Wait for the `want` bar; a `deadline` (`check`/`bound`) ends the wait with the route window."""
        label = f"waiting for the {want} bar"
        if deadline is not None:
            timeout = deadline.bound(timeout, label)
        end = time.time() + timeout
        screen = self.s.settle(quiet=0.6, timeout=timeout)
        while time.time() < end:
            if BARS.get(screen.glyphs(dosbox.BAR)) == want:
                return screen
            time.sleep(0.3)
            wait = max(1.0, end - time.time())
            if deadline is not None:
                wait = deadline.bound(wait, label)
            screen = self.s.settle(quiet=0.6, timeout=wait)
        if deadline is not None:
            deadline.check(label)
        name = self.shot(f"lost-waiting-for-{want}")
        raise RouteLost(f"expected the {want} bar, got {screen.glyphs(dosbox.BAR)} "
                        f"({BARS.get(screen.glyphs(dosbox.BAR), 'unknown')}); "
                        f"see {name}.png")

    def press(self, key: str, want: str | None = None, label: str = "",
              deadline=None) -> None:
        if deadline is not None:
            deadline.check(f"pressing {key}")
        self.s.key(key)
        if want:
            self.wait_bar(want, deadline=deadline)
        else:
            wait = 30.0 if deadline is None else deadline.bound(30.0, f"pressing {key}")
            self.s.settle(quiet=0.6, timeout=wait)
        if label:
            self.shot(label)

    def menu(self, row: int, label: str) -> None:
        """Move the party menu's highlight to `row` and select it."""
        got = self.s.walk_highlight(MENU_RECT, row, key="Down")
        if got != row:
            name = self.shot(f"lost-menu-{label}")
            raise RouteLost(f"party menu highlight reached {got}, wanted {row}; "
                            f"see {name}.png")
        self.s.key("Return")

    def to_party_menu(self, timeout: float = 120.0, deadline=None) -> None:
        end = time.time() + timeout
        while time.time() < end:
            if deadline is not None:
                deadline.check("reaching the PLAY DEMO screen")
            if self.bar(deadline=deadline) == "title":
                break
            self.s.key("Return")
        else:
            raise RouteLost("never reached the PLAY DEMO screen")
        self.press("p", "party_menu", "party-menu", deadline=deadline)

    def intro(self, limit: int = 60, deadline=None) -> None:
        """From BEGIN ADVENTURING to the map, answering what the intro shows.

        A `deadline` (`check`/`bound`) is checked at each screen and cuts its wait.
        """
        for i in range(limit):
            wait = 40.0
            if deadline is not None:
                wait = deadline.bound(wait, "the Silver Blades intro")
            screen = self.s.settle(quiet=1.0, timeout=wait)
            kind = self.bar(screen)
            if kind == "map":
                self.shot("map")
                return
            if kind == "continue":
                self.s.key("Return")
            elif kind == "treasure":
                self.shot("intro-treasure")
                self.s.key("e")
            elif kind == "treasure_left":
                self.s.key("n")
            elif kind == "move_mode":
                # `Escape` leaves it showing (#672's first run); `e` is PROBABLE.
                self.s.key("e")
            else:
                name = self.shot("lost-intro")
                raise RouteLost(f"intro showed bar {screen.glyphs(dosbox.BAR)}; "
                                f"see {name}.png")
        raise RouteLost(f"not on the map after {limit} intro screens")
