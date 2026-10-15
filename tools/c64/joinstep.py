"""Answer a C64 join site's script screens by their text, one guarded key at a time.

`tools/c64/acceptance.py`'s `join` step walks the party onto a join square and
hands the screens the square's script puts up to `JoinAnswerer`; its
`join-arrival` step travels into an area whose arrival script asks, and hands
those screens over the same way.  Every key is
pressed only on a screen whose text is the one the site's script draws next
(`JOIN_SITES`, read from the area script with `tools/areas/ecllist.py --walk`
and `tools/areas/ecltext.py`); any other screen stops the step with nothing
pressed on it.  The bar the walk left up (the world bar or the move sub-bar)
stands while the script prints its first text, and gets no key.  Keys go into the KERNAL buffer, the codes `LIBRARY $31F1`
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
#: Seconds the bar the walk left up (the world bar, or the move sub-bar) may
#: stand unchanged after the last move before the square's first screen is
#: drawn.  The script loads its picture and prints its text under that bar
#: (`ECL11 $89EC`-`$8A6B`: 144 characters before the first continue bar), so
#: the wait counts from the last change anywhere on the screen, never past
#: `SCREEN_SECONDS` in all.
FIRST_SCREEN_GRACE = 15.0
#: The dungeon's move sub-bar, word for word: the walk's last move is a key on
#: it, and it stays drawn while the square's script prints, and comes back when
#: the script ends (`tools/c64/session.py`, `MOVE_SUBBAR`).
MOVE_BAR = ("I,J,K,M,", "RETURN", "OR", "BUTTON")
#: The one-option bar the script's continue subroutine draws (`ECL11 $96A7`).
SCRIPT_CONTINUE = ("PRESS", "BUTTON", "OR", "RETURN", "TO", "CONTINUE.")
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
    `DUNGEON $0BF0`), matched only on a row holding the prompt alone; Return
    takes the highlighted member.  The pick is the party panel with an `EXIT`
    row under the last name, and it stays drawn under the `PARLAY:` bar that
    follows."""
    prompt: str = "PICK SPEAKER"


@dataclasses.dataclass(frozen=True)
class Listing:
    """A vertical menu (opcode `$15`): its heading and a fragment of each line.
    `LIBRARY $3DD3` draws it with the highlight on the first line, so Return
    on a list no key has touched chooses line 0, the only line this answers,
    and only once the colour RAM shows the highlight on that line alone."""
    header: str
    lines: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class JoinSite:
    """One join: the title, area and script, who joins, and the screens.

    `arrival` marks a join the area's entry 4 starts when the party arrives
    from another area, reached by a trip rather than by a step onto a square;
    `first_visit` is the `(address, mask)` whose bits the script sets as the
    scene starts, so the scene plays only while they read clear."""
    title: str
    area: int
    script: str
    joins: tuple[str, ...]
    screens: tuple
    arrival: bool = False
    first_visit: tuple[int, int] | None = None


#: Curse `ECL11`, entry 1, square id 5 (`$89DC`; squares 1,4 11,13 9,15
#: 11,15), gated on `$4C2E` = 0 and `$4C5B` = 0.  In order: text and a
#: continue bar (`$96A7`); text and the opening menu at `$8A9B` (PARLAY,
#: index 4, to `$8B6B`); `PARLAY` (`$2C`) draws the speaker pick and then its
#: own bar `PARLAY:HAUGHTY SLY NICE MEEK ABUSIVE`, whose operands give 1 only
#: for ABUSIVE; text and a continue bar; the list at `$8C0B` (line 0 or 1 to
#: `$8C73`); text and a continue bar; the yes/no at `$96CB` (index 1, YES, to
#: `$8CF0`); `ADDNPC` 22 and 23 at `$8D0F`, text and a continue bar; `EXIT` at
#: `$85A2`.  No opcode on this path draws row 24's move sub-bar, so it comes
#: back only after that `EXIT` or after an early one (`$8589`, `$8597`).
JOIN_SITES = (
    JoinSite("curse-of-the-azure-bonds", 0x11, "ECL11", ("ALIAS", "DRAGONBAIT"), (
        Bar(("COMBAT", "ADVANCE", "WAIT", "FLEE", "PARLAY"), "PARLAY"),
        Speaker(),
        Bar(("HAUGHTY", "SLY", "NICE", "MEEK", "ABUSIVE"), "NICE"),
        Listing("WHAT DO YOU DO?", ("YOUR STORY", "CULTISTS", "AFFAIR")),
        Bar(("NO", "YES"), "YES"),
    )),
    # Silver Blades `ECL44` (the Compound), entry 4 at `$8014`, the same bytes
    # in the DOS block `$44`.  It returns at once when the came-from `$4BF2`
    # is `$44` or when `$4C9E` bit 0 is set, and otherwise sets that bit,
    # places the party at 7,15 north and prints the scene.  In order: the
    # menu at `$80CE` (index 0, BE FRIENDLY, to `$80FA`); text and the
    # one-option continue bar (`$9949`); text and the yes/no at `$9970`
    # (index 0, YES, to `$8168`); `ADDNPC` 78 at `$8168`, then `$9931` clears
    # the text and the script ends.  The only `NEWECL 68` is `ECL40 $8187`.
    JoinSite("secret-of-the-silver-blades", 0x44, "ECL44", ("SIR DERIC",), (
        Bar(("BE", "FRIENDLY", "ATTACK", "FLEE"), "BE FRIENDLY"),
        Bar(("YES", "NO"), "YES"),
    ), arrival=True, first_visit=(0x4C9E, 0x01)),
)


def site_for(title: str, area: int) -> JoinSite | None:
    """The join site in AREA of TITLE (a game key), or None."""
    for site in JOIN_SITES:
        if site.title == title and site.area == area:
            return site
    return None


def tokens(row: str) -> list[tuple[str, int]]:
    """ROW's words with the column each starts at.  A heading ending in `:`
    is a word of its own even when the next word follows it with no blank, as
    the `PARLAY` bar draws it: `PARLAY:HAUGHTY SLY NICE MEEK ABUSIVE`."""
    out, col = [], 0
    for word in row.split():
        col = row.index(word, col)
        head, colon, rest = word.partition(":")
        if not out and colon and head and rest:
            out += [(head + colon, col), (rest, col + len(head) + 1)]
        else:
            out.append((word, col))
        col += len(word)
    return out


def bar_words(screen) -> tuple[str, ...]:
    """Row 24's words, a leading heading ending in `:` dropped."""
    words = tuple(word for word, _ in tokens(screen.row(24)))
    if words and words[0].endswith(":"):
        words = words[1:]
    return words


def word_at(row: str, label: str) -> int:
    """The column LABEL's words start at on ROW, whole words only, or -1."""
    want = label.upper().split()
    found = tokens(row)
    words = [word for word, _ in found]
    for i in range(len(words) - len(want) + 1):
        if words[i:i + len(want)] == want:
            return found[i][1]
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
    """The script's own continue bar, word for word, with no disk prompt."""
    return (tuple(screen.row(24).split()) == SCRIPT_CONTINUE
            and not is_prompt(screen))


def text_window(screen) -> list[str]:
    """Rows 17-22, where the script prints, stripped: logged with every
    continue bar answered."""
    return [screen.row(r).strip() for r in range(17, 23)]


def line_at(screen, fragment: str) -> int | None:
    """The row holding FRAGMENT, or None."""
    hit = screen.find(fragment)
    return None if hit is None else hit[0]


def lit(screen, fragment: str, colour: int = 1) -> bool:
    """Whether every visible cell of FRAGMENT is drawn in the highlight."""
    hit = screen.find(fragment)
    if hit is None:
        return False
    r, c = hit
    cells = [r * 40 + c + i for i, ch in enumerate(fragment) if ch != " "]
    return all(screen.colours[i] == colour for i in cells)


def is_prompt(screen) -> bool:
    return "INSERT" in screen.text()


def is_world(screen) -> bool:
    row = screen.row(24)
    return "ENCAMP" in row and "ENCAMP:" not in row


def is_move_bar(screen) -> bool:
    """Row 24 is the move sub-bar, word for word."""
    return tuple(screen.row(24).split()) == MOVE_BAR


def matches(screen, want) -> bool:
    """Whether SCREEN is the one WANT describes, by its text alone."""
    if isinstance(want, Bar):
        return bar_words(screen) == want.words
    if isinstance(want, Speaker):
        return any(row.strip() == want.prompt for row in screen.rows())
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
    """Drive one join site from the square's first screen to the world bar
    or the move sub-bar.

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
        elif isinstance(want, Listing):
            first, *rest = want.lines
            if not lit(screen, first) or any(lit(screen, line) for line in rest):
                raise JoinStopped(f"{describe(want)}: the highlight is not on "
                                  f"its first line alone", screen)
            self._key(RETURN, screen)
            self._changed(screen, describe(want))
        else:
            self._key(RETURN, screen)
            self._changed(screen, describe(want))

    def run(self, site: JoinSite) -> dict:
        """Answer SITE's screens in order, then wait for the world bar or
        the move sub-bar."""
        presses = 0
        queue = list(site.screens)
        until = self.clock() + SCREEN_SECONDS
        odd_since = None
        last, changed = None, self.clock()
        while True:
            screen = self.screen()
            if screen is not None and (last is None
                                       or screen.codes != last.codes
                                       or screen.colours != last.colours):
                last, changed = screen, self.clock()
            if screen is None:
                if self.clock() >= until:
                    raise JoinStopped(f"the screen could not be read before "
                                      f"{self._next(queue[0] if queue else None)}")
                self.sleep(POLL)
                continue
            want = queue[0] if queue else None
            if want is not None and matches(screen, want):
                self._answer(screen, want)
                queue.pop(0)
                presses, odd_since = 0, None
                until = self.clock() + SCREEN_SECONDS
                continue
            if want is None and (is_world(screen) or is_move_bar(screen)):
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
                                  "row24": screen.row(24).strip(),
                                  "text": text_window(screen)})
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
            if is_world(screen) or is_move_bar(screen):
                which = "world bar" if is_world(screen) else "move bar"
                if not self.keys:
                    if self.clock() >= until:
                        raise JoinStopped(f"the {which} stood "
                                          f"{SCREEN_SECONDS:.0f} s and "
                                          f"{self._next(want)} never came "
                                          f"up", screen)
                    if self.clock() - changed < FIRST_SCREEN_GRACE:
                        self.sleep(POLL)
                        continue
                    raise JoinStopped(f"the {which} stood unchanged "
                                      f"{FIRST_SCREEN_GRACE:.0f} s before "
                                      f"{self._next(want)}", screen)
                # After a key the script has drawn over row 24; the move
                # sub-bar is redrawn only once it has ended (`JOIN_SITES`).
                raise JoinStopped(f"the {which} came back before "
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
        return ("the world bar or the move bar" if want is None
                else describe(want))
