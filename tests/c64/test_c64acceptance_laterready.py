"""The C64 acceptance driver's `ready` step on Curse's and Silver Blades' item
screen, driven against frames transcribed from the WISH-413 capture boots
(`~/.cache/wish/acceptance/WISH-413/cap-curse` and `cap-ssb`): ALIAS's list
on the WISH-407 converted Curse disk and GUY DE VALOIS's on
`WISH-SPEC-ssb-d-engine-resave-walked`.

What the boots measured, and what each fake below reproduces: the item bar
holds the highlight in colour 1 with no row highlighted; one Return on READY
adds an `EXIT` row, turns READY colour 7 and puts the cursor (colour 1) on the
first row; XTEST Down and Up move it; one Return toggles the row's YES/NO
after a redraw with no cursor; a rejection replaces row 24 with
`TOO MANY OF THAT TYPE` for a moment; Return on the `EXIT` row gives the bar
back.  Colour RAM under a blank cell keeps whatever was drawn there before,
so the frames carry a stray colour-1 cell under a space.
"""

from __future__ import annotations

import pytest

from automap.screen import Screen
from goldbox import c64_save
from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS as CURSE
from goldbox.c64_port import SECRET_OF_THE_SILVER_BLADES as SILVER
from goldbox.items import ITEM_BLOCK_STRIDE
from tools.c64 import acceptance as A

CURSE_NAME = "ALIAS"
CURSE_ITEMS = ["YES 82 ARROW(S)", "YES COMPOSITE SHORT BOW", "NO  LONG SWORD",
               "NO  SHIELD", "YES PLATE MAIL"]
CURSE_BAR = "READY USE DROP HALVE JOIN EXIT"

SSB_NAME = "G59 $% V!,/)3"
SSB_ITEMS = ["NO  PLATE MAIL +1", "NO  SHIELD +2", "NO  LONG SWORD +1",
             "NO  MACE +1", "NO  HALBERD +2", "NO  BRACERS AC 6",
             "NO  WAND OF ICE STORM", "NO  GAUNTLETS OF OGRE POWER",
             "NO  SCALE MAIL +2", "NO  LEATHER ARMOR +1", "NO  30 ARROW +1",
             "NO  MAGE SCROLL 3 SPELLS"]
SSB_BAR = "READY USE TRADE DROP HALVE JOIN EXIT"

REJECTION = "TOO MANY OF THAT TYPE"


def _code(ch: str) -> int:
    if "A" <= ch <= "Z":
        return ord(ch) - 0x40
    if ch == "@":
        return 0
    return ord(ch)


def frame(name: str, items: list[str], bar: str, *, cursor: int | None = None,
          exit_row: bool = False, bar_colour: int = 1, bar_word: str = "READY",
          row24: str | None = None) -> Screen:
    """One item-list frame: CURSOR is the list row (0 first, `len(items)` for
    `EXIT`) drawn in colour 1, and BAR_WORD the bar word drawn in BAR_COLOUR."""
    lines = {1: name, 3: "EQUIPPED ITEM"}
    for i, text in enumerate(items):
        lines[5 + i] = " " + text
    if exit_row:
        lines[5 + len(items)] = " EXIT"
    codes = bytearray(0x20 for _ in range(1000))
    colours = bytearray(5 for _ in range(1000))
    for r in (0, 23):
        for c in range(40):
            codes[r * 40 + c] = _code("@")
            colours[r * 40 + c] = 1
    for r in range(1, 23):
        codes[r * 40] = codes[r * 40 + 39] = _code("%")
        for i, ch in enumerate(lines.get(r, "")):
            codes[r * 40 + 1 + i] = _code(ch)
    for c in range(1, 39):
        colours[1 * 40 + c] = 3
    # A stray colour-1 cell under a space, below the list, as the captures have.
    below = 5 + len(items) + (2 if exit_row else 1)
    colours[below * 40 + A.LATER_ITEM_COLUMN] = 1
    text24 = bar if row24 is None else row24
    for i, ch in enumerate(text24):
        codes[24 * 40 + i] = _code(ch)
    if row24 is None:
        at = bar.find(bar_word)
        for c in range(at, at + len(bar_word)):
            colours[24 * 40 + c] = bar_colour
    if cursor is not None:
        for c in range(1, 39):
            colours[(5 + cursor) * 40 + c] = 1
    return Screen(bytes(codes), bytes(colours), 0xCC00)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Keys:
    def __init__(self, screen):
        self.screen = screen

    def key(self, name, *timing):
        self.screen.keys.append(name)
        self.screen.press(name)

    def screenshot(self, path, **kw):
        return True


class ItemScreen:
    """The item screen as the captures showed it, driven by keys."""

    def __init__(self, name, items, bar, *, reject=(), hang=(), dead=(), late=0):
        self.name, self.items, self.bar = name, list(items), bar
        self.words = bar.split()
        self.reject, self.hang = set(reject), set(hang)
        # DEAD rows ignore the Return; LATE is how many reads after a Return
        # still show the list from before it.
        self.dead, self.late = set(dead), late
        self.mode, self.cursor, self.bar_at = "sheet", 0, 0
        self.pending: list[Screen] = []
        self.keys: list[str] = []
        self.kernal: list[int] = []
        self.kbd = Keys(self)

    def frame(self, **kw):
        return frame(self.name, self.items, self.bar, **kw)

    def screen(self):
        if self.pending:
            return self.pending.pop(0)
        if self.mode == "bar":
            return self.frame(bar_word=self.words[self.bar_at])
        if self.mode == "list":
            return self.frame(cursor=self.cursor, exit_row=True, bar_colour=7)
        if self.mode == "unknown":
            return frame("", [], "", row24="INSERT SIDE # 3, AND PRESS ANY KEY.")
        return frame(self.name, [], "ITEMS EXIT")

    def press(self, name):
        if self.mode == "bar":
            if name == "Right":
                self.bar_at = min(self.bar_at + 1, len(self.words) - 1)
            elif name == "Left":
                self.bar_at = max(self.bar_at - 1, 0)
            elif name == "Return" and self.words[self.bar_at] == "READY":
                self.mode, self.cursor = "list", 0
        elif self.mode == "list":
            if name == "Down":
                self.cursor = min(self.cursor + 1, len(self.items))
            elif name == "Up":
                self.cursor = max(self.cursor - 1, 0)
            elif name == "Return":
                self.choose()

    def choose(self):
        at = self.cursor
        if at == len(self.items):
            self.mode, self.bar_at = "bar", 0
            return
        if at in self.hang:
            self.mode = "unknown"
            return
        if at in self.dead:
            return
        self.pending += [self.frame(cursor=at, exit_row=True, bar_colour=7)] * self.late
        # The redraw: the list with no cursor, as Silver Blades drew it.
        self.pending.append(self.frame(exit_row=True, bar_colour=7))
        if at in self.reject:
            self.pending += [self.frame(cursor=at, exit_row=True,
                                        row24=REJECTION)] * 2
            return
        text = self.items[at]
        self.items[at] = ("NO  " + text[4:]) if text.startswith("YES") else (
            "YES " + text[4:])

    def press_kernal(self, code):
        self.kernal.append(code)

    def handle_prompt(self, s=None):
        return False


class Log:
    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))

    def say(self, text):
        pass


def _run(tmp_path, monkeypatch, game, screen):
    clock = Clock()
    monkeypatch.setattr(A.time, "sleep", clock.sleep)
    box = c64_save.CONTAINERS[game.key]
    run = A.SilverRun.__new__(A.SilverRun) if game is SILVER else (
        A.CurseRun.__new__(A.CurseRun))
    run.sess, run.game, run.box = screen, game, box
    run.log, run.out, run.shots, run.deadline = Log(), tmp_path, 0, None
    run.clock = clock.time
    run.left = []

    def open_sheet(who):
        screen.mode = "sheet"
        return [screen.screen().row(r) for r in range(25)]

    def choose_bar(word, timeout):
        if word == "ITEMS" and screen.mode == "sheet":
            screen.mode = "bar"
            return True
        return False

    def leave_item_list():
        run.left.append(screen.mode)
        screen.mode = "world"

    readings = []

    def ready_reading(m):
        n = len(readings)
        readings.append(n)
        records = [bytes(box.slot_stride) for _ in range(8)]
        items = [bytes(ITEM_BLOCK_STRIDE) for _ in range(8)]
        if n:                                       # the readied bit, slot 1
            items[1] = bytes([0x80]) + bytes(ITEM_BLOCK_STRIDE - 1)
        roster = [bytes(box.roster_stride) for _ in range(8)]
        return records, None, items, roster

    class Mon:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def resume(self):
            pass

    screen.mon = lambda timeout=5.0: Mon()
    run.open_sheet, run.choose_bar = open_sheet, choose_bar
    run.leave_item_list, run.ready_reading = leave_item_list, ready_reading
    return run


# --- reading the recorded frames ---------------------------------------------------

@pytest.mark.parametrize("name,items,bar", [(CURSE_NAME, CURSE_ITEMS, CURSE_BAR),
                                            (SSB_NAME, SSB_ITEMS, SSB_BAR)])
def test_the_item_screen_modes_read_off_both_titles_frames(name, items, bar):
    assert A.later_item_mode(frame(name, items, bar)) == "bar"
    listed = frame(name, items, bar, cursor=1, exit_row=True, bar_colour=7)
    assert A.later_item_mode(listed) == "list"
    assert A.later_item_cursor(listed) == 6
    on_exit = frame(name, items, bar, cursor=len(items), exit_row=True, bar_colour=7)
    assert A.later_item_cursor(on_exit) == 5 + len(items)
    # The redraw after a toggle, a rejection on row 24 and the sheet are none.
    assert A.later_item_mode(frame(name, items, bar, exit_row=True, bar_colour=7)) is None
    assert A.later_item_mode(frame(name, items, bar, cursor=1, exit_row=True,
                                   row24=REJECTION)) is None
    assert A.later_item_mode(frame(name, [], "ITEMS EXIT")) is None


def test_a_label_names_one_entry_or_the_step_says_why_not():
    rows = [frame(CURSE_NAME, CURSE_ITEMS, CURSE_BAR).row(r) for r in range(25)]
    assert A.later_ready_target(rows, "COMPOSITE SHORT BOW") == (1, "")
    assert A.later_ready_target(rows, "BOW") == (1, "")
    assert A.later_ready_target(rows, "#5") == (4, "")
    assert A.later_ready_target(rows, "#6")[0] is None
    assert "not on the list" in A.later_ready_target(rows, "DAGGER")[1]
    ssb = [frame(SSB_NAME, SSB_ITEMS, SSB_BAR).row(r) for r in range(25)]
    assert "matches 2 rows" in A.later_ready_target(ssb, "MAIL")[1]
    assert A.later_ready_target(ssb, "SCALE MAIL +2") == (8, "")


# --- driving the step ----------------------------------------------------------------

def test_curse_unreadies_the_bow_with_one_xtest_return_on_ready(tmp_path, monkeypatch):
    screen = ItemScreen(CURSE_NAME, CURSE_ITEMS, CURSE_BAR)
    run = _run(tmp_path, monkeypatch, CURSE, screen)
    got = run.ready("ALIAS>COMPOSITE SHORT BOW")
    assert got["outcome"] == "unreadied"
    assert (got["row"], got["row_was"], got["row_now"]) == (
        2, "YES COMPOSITE SHORT BOW", "NO  COMPOSITE SHORT BOW")
    assert got["message"] is None and got["screen_changed"] is True
    # Return on READY, Down to the bow, Return, Down x4 to EXIT, Return.
    assert screen.keys == ["Return", "Down", "Return"] + ["Down"] * 4 + ["Return"]
    # No KERNAL Return anywhere: one on the list would toggle the arrows.
    assert screen.kernal == []
    assert screen.items[0] == "YES 82 ARROW(S)"
    assert run.left == ["bar"]
    assert got["memory_changed"] is True and got["roster_diff"][1] == []
    assert got["item_diff"][1][0]["now"] == 0x80


def test_curse_re_readies_by_row_number(tmp_path, monkeypatch):
    items = list(CURSE_ITEMS)
    items[1] = "NO  COMPOSITE SHORT BOW"
    screen = ItemScreen(CURSE_NAME, items, CURSE_BAR)
    got = _run(tmp_path, monkeypatch, CURSE, screen).ready("ALIAS>#2")
    assert got["outcome"] == "readied"
    assert got["row_now"] == "YES COMPOSITE SHORT BOW"


def test_silver_blades_reports_the_rejection_row_24_showed(tmp_path, monkeypatch):
    screen = ItemScreen(SSB_NAME, SSB_ITEMS, SSB_BAR, reject={8})
    got = _run(tmp_path, monkeypatch, SILVER, screen).ready("1>SCALE MAIL +2")
    assert got["outcome"] == "rejected"
    assert got["message"] == REJECTION
    assert got["row_was"] == got["row_now"] == "NO  SCALE MAIL +2"
    assert screen.kernal == []


def test_the_bar_highlight_is_walked_back_onto_ready(tmp_path, monkeypatch):
    screen = ItemScreen(SSB_NAME, SSB_ITEMS, SSB_BAR)
    run = _run(tmp_path, monkeypatch, SILVER, screen)
    orig_choose = run.choose_bar

    def choose_bar(word, timeout):
        ok = orig_choose(word, timeout)
        screen.bar_at = 2                 # the bar opens with TRADE highlighted
        return ok
    run.choose_bar = choose_bar
    got = run.ready("1>LONG SWORD +1")
    assert got["outcome"] == "readied"
    assert screen.keys[:3] == ["Left", "Left", "Return"]


def test_an_unknown_screen_stops_the_step_with_no_further_key(tmp_path, monkeypatch):
    screen = ItemScreen(CURSE_NAME, CURSE_ITEMS, CURSE_BAR, hang={1})
    run = _run(tmp_path, monkeypatch, CURSE, screen)
    with pytest.raises(A.StepFailed, match="did not come back"):
        run.ready("ALIAS>COMPOSITE SHORT BOW")
    assert screen.keys == ["Return", "Down", "Return"]
    assert run.left == []
    assert list(tmp_path.glob("*lost-ready.txt"))


def test_a_missing_item_stops_before_any_key(tmp_path, monkeypatch):
    screen = ItemScreen(CURSE_NAME, CURSE_ITEMS, CURSE_BAR)
    run = _run(tmp_path, monkeypatch, CURSE, screen)
    with pytest.raises(A.StepFailed, match="DAGGER is not on the list"):
        run.ready("ALIAS>DAGGER")
    assert screen.keys == []


def test_main_accepts_ready_for_silver_blades(tmp_path, capsys):
    with pytest.raises(SystemExit):
        A.main(["--title", "ssb", "--save", str(tmp_path / "x.d64"),
                "--steps", "load", "ready A>B", "--out", str(tmp_path / "o")])
    err = capsys.readouterr().err
    assert "ready step" not in err
    assert "no save disk" in err


def test_a_late_redraw_is_waited_for_not_read_as_unchanged(tmp_path, monkeypatch):
    # 24 reads 0.05 s apart (1.2 s, Curse's measured bound) of the list as it
    # was before the Return, then the redraw.
    screen = ItemScreen(CURSE_NAME, CURSE_ITEMS, CURSE_BAR, late=24)
    got = _run(tmp_path, monkeypatch, CURSE, screen).ready("ALIAS>COMPOSITE SHORT BOW")
    assert got["outcome"] == "unreadied"
    assert got["row_now"] == "NO  COMPOSITE SHORT BOW"


def test_a_row_that_never_changes_fails_the_step(tmp_path, monkeypatch):
    screen = ItemScreen(SSB_NAME, SSB_ITEMS, SSB_BAR, dead={2})
    run = _run(tmp_path, monkeypatch, SILVER, screen)
    with pytest.raises(A.StepFailed, match="still reads 'NO  LONG SWORD \\+1'"):
        run.ready("1>LONG SWORD +1")
    assert run.left == []
    assert screen.keys == ["Return", "Down", "Down", "Return"]
