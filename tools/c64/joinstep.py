"""Answer a C64 join site's script screens by their text, one guarded key at a time.

`tools/c64/acceptance.py`'s `join` step walks the party onto a join square and
hands the screens the square's script puts up to `JoinAnswerer`.  Every key is
pressed only on a screen whose text is the one the site's script draws next
(`JOIN_SITES`, read from the area script with `tools/areas/ecllist.py --walk`
and `tools/areas/ecltext.py`); any other screen stops the step with nothing
pressed on it.  Keys go into the KERNAL buffer, the codes `LIBRARY $31F1`
compares: `$0D` chooses, `$1D` and `$9D` move a bar's highlight right and left.
"""
from __future__ import annotations

import dataclasses
import time

#: The PETSCII codes the menu key handler (`LIBRARY $31F1`) compares.
RETURN, RIGHT, LEFT = 0x0D, 0x1D, 0x9D

#: Seconds an expected screen may take to come up before the step stops.
SCREEN_SECONDS = 45.0
#: Seconds a screen the site does not expect may stand before the step stops;
#: long enough for a bar the game is still drawing to finish.
UNEXPECTED_SECONDS = 4.0
#: Seconds a key may take to change the screen it was pressed on; a key that
#: changes nothing is never pressed again.
KEY_SECONDS = 8.0
#: Continue bars answered between two expected screens before the step stops.
PRESSES_BETWEEN = 8
#: Game-side disk prompts answered in one join.
PROMPTS = 2
POLL = 0.3


class JoinStopped(RuntimeError):
    """The join met a screen it does not answer, or a key changed nothing."""

    def __init__(self, why: str, screen=None):
        super().__init__(why)
        self.screen = screen


@dataclasses.dataclass(frozen=True)
class Bar:
    """A menu on row 24: its words in order (a heading ending in `:` before
    them is allowed) and the word or words to choose."""
    words: tuple[str, ...]
    answer: str


@dataclasses.dataclass(frozen=True)
class Speaker:
    """The party-member pick a `PARLAY` opens (`LIBRARY $4486`, prompt at
    `DUNGEON $0BF0`); Return takes the highlighted member."""
    prompt: str = "PICK SPEAKER"


@dataclasses.dataclass(frozen=True)
class Listing:
    """A vertical menu (opcode `$15`): its heading and a fragment of each line.
    `LIBRARY $3DD3` draws it with the highlight on the first line, so Return
    on a list no key has touched chooses line 0, the only line this answers."""
    header: str
    lines: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class JoinSite:
    """One join: the title, area and script, who joins, and the screens."""
    title: str
    area: int
    script: str
    joins: tuple[str, ...]
    screens: tuple


#: Curse `ECL11`, entry 1, square id 5 (`$89DC`; squares 1,4 11,13 9,15
#: 11,15), gated on `$4C2E` = 0 and `$4C5B` = 0: the opening menu at `$8A9B`
#: (PARLAY, index 4, to `$8B6B`), `PARLAY` (`$2C`, whose operands give 1 only
#: for ABUSIVE), the list at `$8C0B` (line 0 or 1 to `$8C73`), the yes/no at
#: `$96CB` (index 1, YES, to `$8CF0`), then `ADDNPC` 22 and 23 at `$8D0F`.
JOIN_SITES = (
    JoinSite("curse-of-the-azure-bonds", 0x11, "ECL11", ("ALIAS", "DRAGONBAIT"), (
        Bar(("COMBAT", "ADVANCE", "WAIT", "FLEE", "PARLAY"), "PARLAY"),
        Speaker(),
        Bar(("HAUGHTY", "SLY", "NICE", "MEEK", "ABUSIVE"), "NICE"),
        Listing("WHAT DO YOU DO?", ("YOUR STORY", "CULTISTS", "AFFAIR")),
        Bar(("NO", "YES"), "YES"),
    )),
)


def site_for(title: str, area: int) -> JoinSite | None:
    """The join site in AREA of TITLE (a game key), or None."""
    for site in JOIN_SITES:
        if site.title == title and site.area == area:
            return site
    return None


def bar_words(screen) -> tuple[str, ...]:
    """Row 24's words, a leading heading ending in `:` dropped."""
    words = tuple(screen.row(24).split())
    if words and words[0].endswith(":"):
        words = words[1:]
    return words


def word_at(row: str, label: str) -> int:
    """The column LABEL's words start at on ROW, whole words only, or -1."""
    want = label.upper().split()
    words, cols, col = [], [], 0
    for word in row.split():
        col = row.index(word, col)
        words.append(word)
        cols.append(col)
        col += len(word)
    for i in range(len(words) - len(want) + 1):
        if words[i:i + len(want)] == want:
            return cols[i]
    return -1


def highlight(screen, row: int = 24, colour: int = 1) -> int | None:
    """The first column of the highlighted run on ROW, from the screen's own
    colour RAM, blanks ignored; None when nothing is highlighted."""
    base = row * 40
    for i in range(40):
        if (screen.colours[base + i] == colour
                and screen.codes[base + i] not in (0x20, 0x00)):
            return i
    return None


def is_press(screen) -> bool:
    """A `PRESS ... CONTINUE` bar that is not a disk prompt."""
    row = screen.row(24).split()
    return ("PRESS" in row and any(w.startswith("CONTINUE") for w in row)
            and not is_prompt(screen))


def is_prompt(screen) -> bool:
    return "INSERT" in screen.text()


def is_world(screen) -> bool:
    row = screen.row(24)
    return "ENCAMP" in row and "ENCAMP:" not in row


def matches(screen, want) -> bool:
    """Whether SCREEN is the one WANT describes, by its text alone."""
    if isinstance(want, Bar):
        return bar_words(screen) == want.words
    if isinstance(want, Speaker):
        return screen.find(want.prompt) is not None
    if isinstance(want, Listing):
        return (screen.find(want.header) is not None
                and all(screen.find(line) is not None for line in want.lines)
                and not is_press(screen) and not is_world(screen))
    raise TypeError(want)


def describe(want) -> str:
    if isinstance(want, Bar):
        return f"the bar {' '.join(want.words)}"
    if isinstance(want, Speaker):
        return want.prompt
    return f"the list {want.header}"


class JoinAnswerer:
    """Drive one join site from the square's first screen to the world bar.

    SCREEN returns the current screen (or None), PRESS puts one PETSCII code in
    the KERNAL buffer, PROMPT answers a game-side disk prompt and returns
    whether it did.  `keys` records every code pressed with the screen's
    row 24, and `seen` every screen answered."""

    def __init__(self, screen, press, *, prompt=None, clock=time.monotonic,
                 sleep=time.sleep, log=lambda text: None):
        self.screen, self.press = screen, press
        self.prompt, self.clock, self.sleep, self.log = prompt, clock, sleep, log
        self.keys: list[tuple[int, str]] = []
        self.seen: list[dict] = []
        self.prompts = 0

    def _key(self, code: int, screen) -> None:
        self.keys.append((code, screen.row(24).strip()))
        self.press(code)

    def _changed(self, before, what: str) -> None:
        """Wait for the screen to differ from BEFORE; stop when it does not."""
        until = self.clock() + KEY_SECONDS
        while self.clock() < until:
            self.sleep(POLL)
            now = self.screen()
            if now is not None and (now.codes != before.codes
                                    or now.colours != before.colours):
                return
        raise JoinStopped(f"{what}: the screen did not change", before)

    def _choose(self, screen, want: Bar) -> None:
        """Walk the highlight onto WANT's answer, re-reading the bar before
        every key, then Return."""
        for _ in range(len(want.words) + 1):
            row = screen.row(24)
            col = word_at(row, want.answer)
            at = highlight(screen)
            if col < 0 or at is None:
                raise JoinStopped(f"{describe(want)}: {want.answer} or the "
                                  f"highlight is not on row 24", screen)
            if at == col:
                self._key(RETURN, screen)
                self._changed(screen, f"{want.answer} chosen")
                return
            self._key(RIGHT if at < col else LEFT, screen)
            self._changed(screen, f"{describe(want)}: the highlight move")
            screen = self.screen()
            if screen is None or not matches(screen, want):
                raise JoinStopped(f"{describe(want)} changed while the "
                                  f"highlight moved", screen)
        raise JoinStopped(f"{describe(want)}: the highlight never reached "
                          f"{want.answer}", screen)

    def _answer(self, screen, want) -> None:
        self.seen.append({"screen": describe(want),
                          "row24": screen.row(24).strip()})
        if isinstance(want, Bar):
            self._choose(screen, want)
        else:
            self._key(RETURN, screen)
            self._changed(screen, describe(want))

    def run(self, site: JoinSite) -> dict:
        """Answer SITE's screens in order, then wait for the world bar."""
        presses = 0
        queue = list(site.screens)
        until = self.clock() + SCREEN_SECONDS
        odd_since = None
        while True:
            screen = self.screen()
            if screen is None:
                self.sleep(POLL)
                continue
            want = queue[0] if queue else None
            if want is not None and matches(screen, want):
                self._answer(screen, want)
                queue.pop(0)
                presses, odd_since = 0, None
                until = self.clock() + SCREEN_SECONDS
                continue
            if want is None and is_world(screen):
                return {"site": site.script, "area": site.area,
                        "joins": list(site.joins), "screens": self.seen,
                        "keys": [{"key": f"${k:02X}", "row24": r}
                                 for k, r in self.keys],
                        "prompts": self.prompts}
            if is_press(screen):
                if presses >= PRESSES_BETWEEN:
                    raise JoinStopped(f"more than {PRESSES_BETWEEN} continue "
                                      f"bars before {self._next(want)}", screen)
                presses += 1
                self.seen.append({"screen": "continue",
                                  "row24": screen.row(24).strip()})
                self._key(RETURN, screen)
                self._changed(screen, "the continue bar")
                odd_since = None
                until = self.clock() + SCREEN_SECONDS
                continue
            if is_prompt(screen):
                text = screen.text().upper()
                if (self.prompt is None or "SAVE" in text
                        or self.prompts >= PROMPTS or not self.prompt(screen)):
                    raise JoinStopped("a disk prompt the join does not "
                                      "answer", screen)
                self.prompts += 1
                continue
            if is_world(screen):
                raise JoinStopped(f"the world bar came back before "
                                  f"{self._next(want)}", screen)
            if screen.row(24).strip():
                odd_since = self.clock() if odd_since is None else odd_since
                if self.clock() - odd_since >= UNEXPECTED_SECONDS:
                    raise JoinStopped(f"a screen the join does not expect "
                                      f"before {self._next(want)}: "
                                      f"{screen.row(24).strip()!r}", screen)
            else:
                odd_since = None
            if self.clock() >= until:
                raise JoinStopped(f"{self._next(want)} never came up", screen)
            self.sleep(POLL)

    @staticmethod
    def _next(want) -> str:
        return "the world bar" if want is None else describe(want)
