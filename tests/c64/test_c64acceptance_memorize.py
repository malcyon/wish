"""The Pool `memorize` step drives camp `MAGIC > MEMORIZE` with keys alone and
judges each pick by the member's memorised list, on a fake of the screens the
game drew in the measuring boots (`~/.cache/wish/303/memorize/explore*`)."""

from __future__ import annotations

import pytest

from goldbox import c64_port, c64_save
from tools.c64 import acceptance as A

CAMP = "ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT"
MAGIC = "CAST MEMORIZE SCRIBE DISPLAY REST EXIT"
#: Two pages of DIRTEN's book, each spell with its id and level.
PAGES = [
    [("1ST LEVEL", None, 1), ("BLESS", 1, 1), ("CURSE", 2, 1),
     ("CURE LIGHT WOUNDS", 3, 1)],
    [("2ND LEVEL", None, 2), ("SPIRITUAL HAMMER", 28, 2), ("3RD LEVEL", None, 3),
     ("ANIMATE DEAD", 36, 3), ("DISPEL MAGIC", 41, 3), ("PRAYER", 42, 3)],
]
#: Where the live record pages start and their stride, and where the
#: memorised list sits in a Pool record, written out rather than taken from
#: the driver.
RECORD_PAGES, RECORD_STRIDE, MEMORISED_AT = 0x4D00, 0x100, 0x020
SLOT = 7
SPELL_IDS = {"BLESS": {1}, "CURSE": {2}, "CURE LIGHT WOUNDS": {3},
             "SPIRITUAL HAMMER": {28}, "ANIMATE DEAD": {36, 90},
             "DISPEL MAGIC": {41}, "PRAYER": {42},
             "HIGH SPELL 6": {16}}
#: A first page as long as a full cleric's: eight first-level spells, a blank
#: row, six second-level ones, so the pick prompt's `EXIT` is the fifteenth
#: row of the list, fourteen Downs from the top.
LONG_PAGES = [
    [("1ST LEVEL", None, 1), ("BLESS", 1, 1)]
    + [(f"LOW SPELL {n}", n, 1) for n in range(2, 9)]
    + [("", None, 1), ("2ND LEVEL", None, 2)]
    + [(f"HIGH SPELL {n}", 10 + n, 2) for n in range(1, 7)],
    PAGES[1],
]


def _window(lines: dict[int, str], bar: str) -> list[str]:
    rows = []
    for r in range(25):
        if r in (0, 23):
            rows.append("@" + "[" * 38 + "@")
        elif r == 24:
            rows.append(bar.ljust(40))
        else:
            rows.append("$" + lines.get(r, "").ljust(38) + "$")
    return rows


class _Screen:
    def __init__(self, rows, hot=None):
        self._rows = rows
        self.colours = bytearray([5] * 1000)
        if hot is not None:
            self.colours[hot * 40 + 3] = 1

    def row(self, r):
        return self._rows[r]


class _Keyboard:
    def __init__(self, sess):
        self.sess = sess

    def key(self, name, *timing):
        self.sess.go(("key", name))

    def screenshot(self, path):
        return True


class _Mon:
    def __init__(self, sess):
        self.sess = sess

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, addr, n):
        mem = bytearray(0x10000)
        at = RECORD_PAGES + SLOT * RECORD_STRIDE + MEMORISED_AT
        mem[at:at + len(self.sess.memorised)] = bytes(self.sess.memorised)
        return bytes(mem[addr:addr + n])

    def resume(self):
        pass


class MemorizeFake:
    """The camp, MAGIC bar, book, pick prompt, chosen spells and confirmation,
    moved by the keys the game takes. A pick adds the spell's id with bit 7
    when a slot of its level is free, shows the game's message for a read or
    two, then the pick prompt while any slot is left or the book when none
    is; a key the game would not take fails the test."""

    def __init__(self, free, memorised=(28, 26, 3, 3), lost_returns=0,
                 message_reads=2, pages=PAGES):
        self.pages = pages
        self.free = dict(free)
        self.memorised = list(memorised)
        self.lost_returns = lost_returns
        self.message_reads = message_reads
        self.state, self.page, self.hot = "camp", 0, 0
        self.queue: list[list[str]] = []
        self.sent: list = []
        self.kbd = _Keyboard(self)
        self.here = "/slot"

    # -- the screens -------------------------------------------------------------
    def _entries(self):
        return [(name, ident, level) for name, ident, level in self.pages[self.page]
                if ident is not None]

    def _page_rows(self, title, bar, with_exit):
        lines, r = {2: title}, 4
        for name, ident, _ in self.pages[self.page]:
            lines[r] = name if ident is None else f"  {name}"
            r += 1
        if with_exit:
            lines[r] = "  EXIT"
        return _window(lines, bar)

    def _book_bar(self):
        words = ["MEMORIZE"]
        if self.page + 1 < len(self.pages):
            words.append("NEXT")
        if self.page > 0:
            words.append("PREV")
        return " ".join(words + ["EXIT"])

    def _hot_row(self):
        names = [n for n, _, _ in self._entries()] + ["EXIT"]
        rows = self._page_rows("", "", True)
        return next(r for r in range(3, 23) if rows[r][1:39].strip() == names[self.hot])

    def screen(self):
        if self.queue:
            return _Screen(self.queue.pop(0))
        if self.state in ("camp", "camp2"):
            return _Screen(_window({18: "YOU SET UP CAMP..."}, CAMP))
        if self.state == "magic":
            return _Screen(_window({}, MAGIC))
        if self.state == "book":
            return _Screen(self._page_rows("DIRTEN'S BOOK OF SPELLS",
                                           self._book_bar(), False))
        if self.state == "pick":
            return _Screen(self._page_rows("DIRTEN'S BOOK OF SPELLS",
                                           A.PICK_MEMORIZE, True), self._hot_row())
        chosen = {2: "DIRTEN'S CHOSEN SPELLS"}
        r = 4
        for _, ident, _ in [e for p in self.pages for e in p if e[1] is not None]:
            for entry in self.memorised:
                if entry == ident | 0x80:
                    chosen[r] = f"  {next(n for p in self.pages for n, i, _ in p if i == ident)}"
                    r += 1
        if self.state == "chosen":
            return _Screen(_window(chosen, "EXIT"))
        assert self.state == "confirm"
        return _Screen(_window({**chosen, 18: "ARE YOU SURE ABOUT",
                                19: "YOUR CHOICE OF SPELLS?"}, "CONFIRM: OKAY  CANCEL"))

    def _message(self, first, second):
        return _window({16: "[" * 38, 18: first, 19: second,
                        20: "SPELLS LEFT TO MEMORIZE: "
                        + "  ".join(str(self.free.get(n, 0)) for n in (1, 2, 3))},
                       A.PICK_MEMORIZE)

    # -- the keys ----------------------------------------------------------------
    def go(self, what):
        self.sent.append(what)
        state = self.state
        if state == "pick" and what in (("key", "Down"), ("key", "Up")):
            count = len(self._entries()) + 1
            self.hot = (self.hot + (1 if what[1] == "Down" else -1)) % count
            return True
        if state == "pick" and what in (("key", "Return"), ("key", 0x0D)):
            if self.lost_returns:
                self.lost_returns -= 1
                return True
            if self.hot == len(self._entries()):
                self.state = "book"
                return True
            name, ident, level = self._entries()[self.hot]
            if self.free.get(level, 0) > 0:
                self.free[level] -= 1
                self.memorised.append(ident | 0x80)
                self.queue = [self._message("DIRTEN WILL MEMORIZE", name)] \
                    * self.message_reads
            else:
                self.queue = [self._message("DIRTEN CAN'T MEMORIZE", name)]
            self.state = "pick" if sum(self.free.values()) else "book"
            return True
        moves = {
            ("camp", ("bar", "MAGIC")): "magic",
            ("magic", ("bar", "MEMORIZE")): ("chosen" if any(
                n & 0x80 for n in self.memorised) else "book"),
            ("magic", ("bar", "EXIT")): "camp2",
            ("book", ("bar", "MEMORIZE")): "pick",
            ("book", ("bar", "EXIT")): "chosen",
            ("chosen", ("bar", "EXIT")): "confirm",
            ("confirm", ("bar", "OKAY")): "magic",
        }
        if state == "book" and what in (("bar", "NEXT"), ("bar", "PREV")):
            assert what[1] in self._book_bar().split(), f"{what} not on the bar"
            self.page += 1 if what[1] == "NEXT" else -1
            return True
        assert (state, what) in moves, f"no transition for {(state, what)}"
        self.state = moves[(state, what)]
        if self.state == "pick":
            self.hot = 0
        if self.state == "magic" and state == "confirm":
            self.memorised.sort(key=lambda n: -(n & 0x7F))
        return True

    def select_bar(self, label, row=24, timeout=0):
        return self.go(("bar", label))

    def select_party(self, index, timeout=0):
        assert self.state == "camp", "the panel was moved off the camp bar"
        self.sent.append(("party", index))
        return True

    def press_kernal(self, code):
        return self.go(("key", code))

    def mon(self, timeout=0):
        return _Mon(self)

    def settle(self, seconds=0):
        pass

    def handle_prompt(self, s=None):
        return False


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(A.time, "sleep", lambda seconds: None)


def _run(tmp_path, sess, title="pool-of-radiance"):
    run = A.PoolRun.__new__(A.PoolRun)
    run.sess, run.out, run.log, run.shots = sess, tmp_path, A.Log(tmp_path), 0
    run.game = c64_port.by_key(title)
    run.box = c64_save.CONTAINERS[run.game.key]
    run._spell_ids = SPELL_IDS
    run.panel_index = lambda who: 0
    run.position = lambda: [14, 4, 2]
    run._scribe_selected = lambda who, index: {"record_name": who}
    run.reading = lambda: {"party": [{"slot": SLOT, "name": "DIRTEN",
                                      "memorised": list(sess.memorised)}]}
    return run


# -- the argument -----------------------------------------------------------------

@pytest.mark.parametrize("arg, want", [
    ("DIRTEN>ANIMATE DEAD", ("DIRTEN", ["ANIMATE DEAD"])),
    ("Dirten > animate dead , dispel magic",
     ("Dirten", ["ANIMATE DEAD", "DISPEL MAGIC"])),
])
def test_memorize_reads_the_member_and_each_spell(arg, want):
    steps = A.parse_steps(["load", f"memorize {arg}", "rest 8h"])
    assert steps[1].verb == "memorize"
    assert A.parse_memorize(steps[1].arg) == want


@pytest.mark.parametrize("arg", ["DIRTEN", ">ANIMATE DEAD", "DIRTEN>",
                                 "DIRTEN>ANIMATE DEAD,", "7>ANIMATE DEAD"])
def test_memorize_without_a_name_and_spells_is_rejected(arg):
    with pytest.raises(ValueError, match="say memorize WHO>SPELL|name the member"):
        A.parse_steps(["load", f"memorize {arg}"])


# -- the step ---------------------------------------------------------------------

def test_memorize_turns_to_the_spell_picks_it_confirms_and_ends_in_camp(tmp_path):
    sess = MemorizeFake(free={3: 1})
    run = _run(tmp_path, sess)
    got = run.memorize("DIRTEN>ANIMATE DEAD")
    assert got["picks"] == [{"spell": "ANIMATE DEAD", "entry": 0xA4, "id": 36,
                             "key": "xtest-return",
                             "messages": ["DIRTEN WILL MEMORIZE", "ANIMATE DEAD",
                                          "SPELLS LEFT TO MEMORIZE: 0  0  0"],
                             "after": "book", "pages_turned": 1}]
    assert got["chosen"] == ["ANIMATE DEAD"]
    assert got["memorised_before"] == [28, 26, 3, 3]
    assert sorted(got["memorised_after"]) == sorted([28, 26, 3, 3, 0xA4])
    assert sess.state == "camp2"
    assert ("bar", "NEXT") in sess.sent
    assert sess.sent.count(("key", "Down")) == 1
    assert run.scribing and run.memorize_pending == {
        "who": "DIRTEN", "slot": SLOT, "entries": [0xA4],
        "learned_before": [28, 26, 3, 3]}


def test_memorize_leaves_the_pick_prompt_to_turn_the_page_for_the_next_spell(
        tmp_path):
    sess = MemorizeFake(free={1: 2, 3: 1})
    run = _run(tmp_path, sess)
    got = run.memorize("DIRTEN>BLESS,ANIMATE DEAD")
    assert [p["entry"] for p in got["picks"]] == [0x81, 0xA4]
    assert [p["after"] for p in got["picks"]] == ["pick", "pick"]
    assert [p["pages_turned"] for p in got["picks"]] == [0, 1]
    assert sorted(got["chosen"]) == ["ANIMATE DEAD", "BLESS"]
    assert sess.state == "camp2"


def test_memorize_walks_a_full_page_to_its_exit_row_to_turn_the_page(tmp_path):
    sess = MemorizeFake(free={1: 2, 3: 1}, pages=LONG_PAGES)
    run = _run(tmp_path, sess)
    got = run.memorize("DIRTEN>BLESS,ANIMATE DEAD")
    assert [p["entry"] for p in got["picks"]] == [0x81, 0xA4]
    assert [p["pages_turned"] for p in got["picks"]] == [0, 1]
    # BLESS needs no key; EXIT under fourteen spells is fourteen Downs.
    first_page = sess.sent[:sess.sent.index(("bar", "NEXT"))]
    assert first_page.count(("key", "Down")) == 14
    assert ("key", "Up") not in sess.sent
    assert sess.state == "camp2"


def test_memorize_walks_to_the_last_spell_of_a_full_page(tmp_path):
    sess = MemorizeFake(free={1: 1, 2: 1}, pages=LONG_PAGES)
    run = _run(tmp_path, sess)
    got = run.memorize("DIRTEN>HIGH SPELL 6")
    assert got["picks"][0]["entry"] == 0x80 | 16
    assert sess.sent.count(("key", "Down")) == 14
    assert sess.state == "camp2"


def test_memorize_fails_on_the_games_rejection(tmp_path):
    sess = MemorizeFake(free={3: 1})
    run = _run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="CAN'T MEMORIZE DISPEL MAGIC"):
        run.memorize("DIRTEN>ANIMATE DEAD,DISPEL MAGIC")
    assert list(tmp_path.glob("*memorize-rejected.txt"))


def test_memorize_tries_the_kernal_return_when_the_first_key_changed_nothing(
        tmp_path):
    sess = MemorizeFake(free={3: 1}, lost_returns=1)
    run = _run(tmp_path, sess)
    got = run.memorize("DIRTEN>ANIMATE DEAD")
    assert got["picks"][0]["key"] == "kernal-return"
    assert ("key", 0x0D) in sess.sent


def test_memorize_fails_before_any_key_when_a_choice_is_already_pending(tmp_path):
    sess = MemorizeFake(free={3: 0}, memorised=(0xA4, 28))
    run = _run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="already has a choice pending"):
        run.memorize("DIRTEN>ANIMATE DEAD")
    assert sess.sent == []


def test_memorize_fails_for_a_spell_on_no_page_of_the_book(tmp_path):
    sess = MemorizeFake(free={3: 1})
    run = _run(tmp_path, sess)
    run._spell_ids = {**SPELL_IDS, "FIREBALL": {50}}
    with pytest.raises(A.StepFailed, match="FIREBALL is on no page"):
        run.memorize("DIRTEN>FIREBALL")


def test_memorize_fails_for_a_name_the_spell_table_does_not_draw(tmp_path):
    sess = MemorizeFake(free={3: 1})
    run = _run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="FIRE BOLT"):
        run.memorize("DIRTEN>FIRE BOLT")
    assert sess.sent == []


def test_memorize_runs_on_pool_of_radiance_only(tmp_path):
    sess = MemorizeFake(free={3: 1})
    run = _run(tmp_path, sess, title="curse-of-the-azure-bonds")
    with pytest.raises(A.StepFailed, match="Pool of Radiance only"):
        run.memorize("DIRTEN>ANIMATE DEAD")
    assert sess.sent == []


# -- the rest after it ------------------------------------------------------------

def test_the_rest_reports_the_memorized_spells_learned(tmp_path):
    sess = MemorizeFake(free={}, memorised=(36, 28, 26, 3, 3))
    run = _run(tmp_path, sess)
    got = run._memorize_learned({"who": "DIRTEN", "slot": SLOT, "entries": [0xA4]},
                                in_camp=True, completed=True)
    assert got == {"who": "DIRTEN", "pending_before": [0xA4],
                   "after": [36, 28, 26, 3, 3], "learned": True, "still_pending": []}


def test_a_full_rest_in_camp_that_leaves_a_spell_pending_fails(tmp_path):
    sess = MemorizeFake(free={}, memorised=(0xA4, 28))
    run = _run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="without \\[36\\] learned"):
        run._memorize_learned({"who": "DIRTEN", "slot": SLOT, "entries": [0xA4]},
                              in_camp=True, completed=True)


def test_an_interrupted_rest_records_the_lost_choice_without_failing(tmp_path):
    sess = MemorizeFake(free={}, memorised=(28,))
    run = _run(tmp_path, sess)
    got = run._memorize_learned({"who": "DIRTEN", "slot": SLOT, "entries": [0xA4]},
                                in_camp=True, completed=False)
    assert got["learned"] is False and got["after"] == [28]


def test_a_pick_left_pending_does_not_pass_as_the_spell_already_learned(tmp_path):
    sess = MemorizeFake(free={}, memorised=(0x24, 0xA4, 28))
    run = _run(tmp_path, sess)
    pending = {"who": "DIRTEN", "slot": SLOT, "entries": [0xA4],
               "learned_before": [0x24, 28]}
    with pytest.raises(A.StepFailed, match="without \\[36\\] learned"):
        run._memorize_learned(pending, in_camp=True, completed=True)


def test_a_pick_that_became_learned_passes_beside_the_same_spell_held_before(
        tmp_path):
    sess = MemorizeFake(free={}, memorised=(0x24, 0x24, 28))
    run = _run(tmp_path, sess)
    pending = {"who": "DIRTEN", "slot": SLOT, "entries": [0xA4],
               "learned_before": [0x24, 28]}
    assert run._memorize_learned(pending, in_camp=True, completed=True)["learned"]


# -- the pick's own check ---------------------------------------------------------

class _DuplicatingFake(MemorizeFake):
    """A first Return the game took late: the pick shows once, then a second
    copy lands on the second read of the list after it."""

    reads = None

    def go(self, what):
        before = len(self.memorised)
        done = super().go(what)
        if len(self.memorised) > before:
            self.reads = 0
        return done

    def mon(self, timeout=0):
        if self.reads is not None:
            self.reads += 1
            if self.reads == 2:
                self.memorised.append(self.memorised[-1])
        return super().mon(timeout)


def test_a_pick_taken_twice_fails_naming_the_duplicate(tmp_path):
    sess = _DuplicatingFake(free={3: 2})
    run = _run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="added \\[164, 164\\].*taken twice"):
        run.memorize("DIRTEN>ANIMATE DEAD")


def test_a_pick_that_adds_nothing_and_draws_no_message_fails(tmp_path):
    sess = MemorizeFake(free={3: 1}, lost_returns=2)
    run = _run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="neither Return picked ANIMATE DEAD"):
        run.memorize("DIRTEN>ANIMATE DEAD")
