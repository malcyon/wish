"""Three Pool camp steps driven with keys alone and no memory write: `rest
offered`, `cast CASTER:SPELL[>TARGET]` from the memorised list, and Dispel
Magic picked from a list that holds other spells, on a fake of the screens the
game drew in the measuring boots (`~/.cache/wish/303/memorize/explore*` and
`~/.cache/wish/303/p3-driver/`)."""

from __future__ import annotations

import itertools
import pathlib

import pytest

from goldbox import c64_port, c64_save, dos_codec
from goldbox.savegame import SaveGame0, SaveGame1
from tools.c64 import acceptance as A

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"

CAMP = "ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT"
MAGIC = "CAST MEMORIZE SCRIBE DISPLAY REST EXIT"
REST_BAR = "REST  INCREASE  DECREASE  EXIT"
FIGHT_BAR = "MOVE VIEW AIM USE QUICK DONE"
#: The addresses the fake's memory answers, written out rather than taken
#: from the driver: the live record pages and the memorised list in a record,
#: the clock, CAMP's rest-time field, the interrupted marker and CAMP's rest
#: loop bytes.
RECORD_PAGES, RECORD_STRIDE, MEMORISED_AT = 0x4D00, 0x100, 0x020
CLOCK, REST_TIME, MARKER, CAMP_TICK = 0x49C6, 0x2898, 0x6DD3, 0x1E0F
CAMP_BYTES = bytes((0xAD, 0xD2, 0x6D, 0xF0, 0x20))
SLOT = 7
SPELL_IDS = {"BLESS": {1}, "CURE LIGHT WOUNDS": {3}, "SPIRITUAL HAMMER": {28},
             "ANIMATE DEAD": {36, 90}, "DISPEL MAGIC": {41}, "PRAYER": {42}}
NAMES = {ident: name for name, idents in SPELL_IDS.items() for ident in idents}
LEVELS = {1: 1, 3: 1, 28: 2, 36: 3, 41: 3, 42: 3}


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


def _whom() -> list[str]:
    """The target question as the party panel draws it, from column 17 under
    `NAME  AC HP`, with `THE WHOLE PARTY` and `EXIT` under the names."""
    rows = [" " * 40 for _ in range(24)]

    def put(r, text):
        rows[r] = rows[r][:17] + text.ljust(23)[:23]
    put(2, "NAME            AC HP")
    for i, name in enumerate(["BRUTUS", "DIRTEN", "THE WHOLE PARTY", "EXIT"]):
        put(4 + i, name.ljust(17) + ("6 5" if i < 2 else ""))
    return rows + ["CAST SPELL ON WHOM?".ljust(40)]


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

    def screenshot(self, path, timeout=None):
        return True


class _Mon:
    """Reads only: a write fails the test, since none of these steps may write."""

    def __init__(self, sess):
        self.sess = sess

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, addr, n):
        return self.sess.read(addr, n)

    def write(self, addr, data):
        raise AssertionError(f"wrote {bytes(data).hex()} at ${addr:04X}")

    def resume(self):
        pass


class CampFake:
    """Camp, the MAGIC bar, the cast list and its pick prompt, the target
    question, and the rest-time bar and the rest itself, moved by the keys the
    game takes; a key the game would not take fails the test."""

    def __init__(self, memorised, *, rest=(0, 6, 45), interrupt_after=None,
                 whom_spells=(41,), lost_returns=0, message_reads=2,
                 field=None, dispel_page=True):
        self.memorised = list(memorised)
        self.days, self.hours, self.minutes = rest
        self.field = list(field) if field is not None else [rest[2], rest[1], rest[0]]
        self.interrupt_after = interrupt_after
        self.whom_spells = set(whom_spells)
        self.lost_returns = lost_returns
        self.message_reads = message_reads
        self.dispel_page = dispel_page
        self.state, self.hot = "camp", 0
        self.clock = [0, 1, 5, 14, 21, 0]
        self.marker, self.camp_resident = 0, True
        self.passes, self.left = 0, 0
        self.queue: list[list[str]] = []
        self.sent: list = []
        self.dispelled = False
        self.kbd = _Keyboard(self)
        self.here = "/slot"

    # -- memory --------------------------------------------------------------------
    def read(self, addr, n):
        if addr == CLOCK and n == 6 and self.state == "resting":
            self._pass()
        mem = bytearray(0x10000)
        at = RECORD_PAGES + SLOT * RECORD_STRIDE + MEMORISED_AT
        mem[at:at + len(self.memorised)] = bytes(self.memorised)
        mem[CLOCK:CLOCK + 6] = bytes(self.clock)
        mem[REST_TIME:REST_TIME + 3] = bytes(self.field)
        mem[MARKER] = self.marker
        if self.camp_resident:
            mem[CAMP_TICK:CAMP_TICK + 5] = CAMP_BYTES
        return bytes(mem[addr:addr + n])

    def _pass(self):
        """One five-minute pass of the rest loop, on each clock read."""
        if self.passes == self.interrupt_after:
            self.state = "interrupted"
            self.marker, self.camp_resident = 0xFF, False
            self.memorised = [n for n in self.memorised if not n & 0x80]
            self.queue = [_window({18: "YOUR REST IS RUDELY INTERRUPTED!"}, REST_BAR)] * 2 \
                + [_window({17: "WHILE IN CAMP"}, REST_BAR)] \
                + [_window({17: "WHILE IN CAMP YOU ARE SUDDENLY",
                            18: "ATTACKED BY ORCS."}, REST_BAR)] * 2
            return
        self.passes += 1
        self.left -= 5
        units, tens, hour, day = (self.clock[1], self.clock[2], self.clock[3],
                                  self.clock[4])
        total = ((day * 24 + hour) * 60 + tens * 10 + units) + 5
        day, rest = divmod(total, 24 * 60)
        hour, rest = divmod(rest, 60)
        self.clock[1:5] = [rest % 10, rest // 10, hour, day]
        if self.left <= 0:
            self.memorised = [n & 0x7F for n in self.memorised]
            self.state = "camp"

    # -- the screens ---------------------------------------------------------------
    def _list_rows(self, bar, with_exit):
        lines, r, level = {2: "DIRTEN'S MEMORIZED SPELLS"}, 4, None
        names = []
        for n in self.memorised:
            if n & 0x80 or not n:
                continue
            if LEVELS[n] != level:
                level = LEVELS[n]
                if r > 4:
                    r += 1
                lines[r] = f"{level}{['ST', 'ND', 'RD'][level - 1]} LEVEL"
                r += 1
            lines[r] = f"  {NAMES[n]}"
            names.append(NAMES[n])
            r += 1
        if with_exit:
            lines[r] = "  EXIT"
        return _window(lines, bar), names

    def _castable(self):
        return [n for n in self.memorised if n and not n & 0x80]

    def _hot_row(self, rows):
        entries = [r for r in range(3, 23)
                   if rows[r][1:39].startswith("  ") and rows[r].strip("$ ")]
        return entries[self.hot]

    def screen(self):
        if self.queue:
            return _Screen(self.queue.pop(0))
        if self.state in ("camp",):
            return _Screen(_window({18: "YOU SET UP CAMP..."}, CAMP))
        if self.state == "magic":
            return _Screen(_window({}, MAGIC))
        if self.state == "list":
            return _Screen(self._list_rows("CAST EXIT", False)[0])
        if self.state == "pick":
            rows, _ = self._list_rows(A.PICK_SPELL, True)
            return _Screen(rows, self._hot_row(rows))
        if self.state == "whom":
            return _Screen(_whom())
        if self.state == "page":
            return _Screen(_window({18: "THE MAGIC IS DISPELLED"}, A.CONTINUE))
        if self.state == "resttime":
            return _Screen(_window({18: f"REST TIME = {self.days:2d} DAYS "
                                        f"{self.hours:2d} HRS {self.minutes:2d} MINS"},
                                   REST_BAR))
        if self.state == "resting":
            return _Screen(_window({18: "REST TIME =  0 DAYS  6 HRS 40 MINS"}, REST_BAR))
        assert self.state == "interrupted"
        # The fight's map, its frame running down the middle of rows 17-22.
        return _Screen(_window({r: " " * 21 + "$" for r in range(1, 23)}, FIGHT_BAR))

    def in_combat(self):
        return self.state == "interrupted" and not self.queue

    # -- the keys ------------------------------------------------------------------
    def _cast(self, ident, bar=A.PICK_SPELL):
        self.memorised.remove(ident)
        self.memorised.insert(0, 0)
        message = _window({17: "DIRTEN CASTS", 18: NAMES[ident]}, bar)
        self.queue = [message] * self.message_reads
        self.hot = len(self._castable())

    def go(self, what):
        self.sent.append(what)
        state = self.state
        if state == "pick" and what in (("key", "Down"), ("key", "Up")):
            count = len(self._castable()) + 1
            self.hot = (self.hot + (1 if what[1] == "Down" else -1)) % count
            return True
        if state == "pick" and what in (("key", "Return"), ("key", 0x0D)):
            if self.lost_returns:
                self.lost_returns -= 1
                return True
            castable = self._castable()
            if self.hot == len(castable):
                self.state = "list"
                return True
            ident = castable[self.hot]
            if ident in self.whom_spells:
                self.pending = ident
                self.state = "whom"
            else:
                self._cast(ident)
            return True
        if state == "whom" and what == ("key", "Return"):
            self._cast(self.pending, bar="")
            self.dispelled = True
            self.state = "page" if self.dispel_page else "pick"
            return True
        if state == "page" and what == ("key", 0x0D):
            self.queue = []
            self.state = "pick"
            return True
        if state == "resttime" and what == ("bar", "REST"):
            self.left = (self.days * 24 + self.hours) * 60 + self.minutes
            self.state = "resting"
            return True
        moves = {
            ("camp", ("bar", "MAGIC")): "magic",
            ("camp", ("bar", "REST")): "resttime",
            ("magic", ("bar", "CAST")): "list",
            ("magic", ("bar", "EXIT")): "camp",
            ("list", ("bar", "CAST")): "pick",
            ("list", ("bar", "EXIT")): "magic",
        }
        assert (state, what) in moves, f"no transition for {(state, what)}"
        self.state = moves[(state, what)]
        if self.state == "pick":
            self.hot = 0
        return True

    def select_bar(self, label, row=24, timeout=0):
        return self.go(("bar", label))

    def select_party(self, index, timeout=0):
        assert self.state in ("camp", "whom"), "the panel was moved off its bar"
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
    # Each read of the clock is a quarter of a second later, so a wait that
    # polls the clock ends without sleeping.
    run.clock = itertools.count(0, 0.25).__next__
    run.game = c64_port.by_key(title)
    run.box = c64_save.CONTAINERS[run.game.key]
    run._spell_ids = SPELL_IDS
    run.panel_index = lambda who: 0
    run.position = lambda: [14, 4, 2]
    run.reading = lambda: {"party": [{"slot": SLOT, "name": "DIRTEN",
                                      "memorised": [n for n in sess.memorised if n]}],
                           "effects": []}
    return run


def _after_memorize(run, entries=(0xA4,), held=(28, 3, 3)):
    """What `memorize` leaves for the rest straight after it, in that camp."""
    run.scribing = True
    run.scribe_square = [14, 4, 2]
    run.memorize_pending = {"who": "DIRTEN", "slot": SLOT, "entries": list(entries),
                            "learned_before": list(held)}


def _fixture_disk(tmp_path: pathlib.Path) -> pathlib.Path:
    payload = SaveGame0.from_prg((FIXTURES / "savedgame0.bin").read_bytes()).to_bytes()
    save1 = SaveGame1.from_prg((FIXTURES / "savedgame1.bin").read_bytes()).to_bytes()
    path = tmp_path / "fixture-source.d64"
    path.write_bytes(dos_codec.save_disk(payload, save1,
                                         c64_port.POOL_OF_RADIANCE).to_bytes())
    return path


# -- rest offered -----------------------------------------------------------------

def test_rest_offered_is_a_step_and_other_titles_stop_before_a_slot(tmp_path):
    steps = A.parse_steps(["load", "memorize DIRTEN>ANIMATE DEAD", "rest offered"])
    assert steps[2] == A.Step("rest", "offered")
    with pytest.raises(ValueError):
        A.parse_steps(["load", "rest offered8h"])
    with pytest.raises(SystemExit) as info:
        A.main(["--title", "curse", "--save", str(_fixture_disk(tmp_path)),
                "--stage-only", "--steps", "load", "rest offered",
                "--out", str(tmp_path / "out")])
    assert info.value.code == 2


def test_rest_offered_takes_the_games_time_writes_nothing_and_learns_the_pick(
        tmp_path):
    sess = CampFake([0xA4, 28, 3, 3])
    run = _run(tmp_path, sess)
    _after_memorize(run)
    got = run.rest("offered")
    assert sess.sent == [("bar", "REST"), ("bar", "REST")]
    assert got["offered"] == [0, 6, 45] and got["field"] == [45, 6, 0]
    assert got["offered_minutes"] == 405 and got["elapsed_minutes"] == 405
    assert got["rest_completed"] is True and got["ended"] == "completed"
    assert "wrote_nothing" not in got and got["stayed_in_camp"] is True
    assert got["memorised"]["learned"] is True
    assert got["memorised"]["after"] == [36, 28, 3, 3]
    assert sess.state == "camp"
    assert not run.scribing and run.memorize_pending is None


def test_rest_offered_reports_an_interruption_as_its_own_outcome(tmp_path):
    sess = CampFake([0xA4, 28, 3, 3], interrupt_after=4)
    run = _run(tmp_path, sess)
    _after_memorize(run)
    with pytest.raises(A.RestInterrupted, match="interrupted after 20 of 405 "
                       "minutes .*RUDELY INTERRUPTED.*then fight"):
        run.rest("offered")
    outcome = run.lost_reading["outcome"]
    assert outcome["ended"] == "interrupted" and outcome["then"] == "fight"
    assert outcome["text"] == ["YOUR REST IS RUDELY INTERRUPTED!",
                               "WHILE IN CAMP YOU ARE SUDDENLY", "ATTACKED BY ORCS."]
    assert outcome["memorised"]["after"] == [28, 3, 3]
    assert sess.sent == [("bar", "REST"), ("bar", "REST")]
    assert '"rest-outcome"' in (tmp_path / "run.jsonl").read_text()


def test_rest_offered_stops_before_resting_when_the_field_and_screen_disagree(
        tmp_path):
    sess = CampFake([0xA4, 28], field=(0, 8, 0))
    run = _run(tmp_path, sess)
    _after_memorize(run)
    with pytest.raises(A.StepFailed, match="CAMP's rest-time field holds"):
        run.rest("offered")
    assert sess.sent == [("bar", "REST")]


def test_rest_offered_stops_when_the_game_offers_no_time(tmp_path):
    sess = CampFake([28], rest=(0, 0, 0))
    run = _run(tmp_path, sess)
    _after_memorize(run, entries=())
    with pytest.raises(A.StepFailed, match="offered no rest time"):
        run.rest("offered")
    assert sess.sent == [("bar", "REST")]


def test_rest_offered_runs_on_pool_of_radiance_only(tmp_path):
    sess = CampFake([28])
    run = _run(tmp_path, sess, title="curse-of-the-azure-bonds")
    with pytest.raises(A.StepFailed, match="Pool of Radiance only"):
        run.rest("offered")
    assert sess.sent == []


# -- a cast with no target --------------------------------------------------------

DIRTEN = [1, 1, 3, 3, 3, 28, 42]


def test_cast_reads_a_spell_with_no_target():
    assert A.parse_cast("DIRTEN:prayer") == ("DIRTEN", "PRAYER", None)
    assert A.parse_steps(["load", "cast DIRTEN:PRAYER"])[1].arg == "DIRTEN:PRAYER"
    assert A.parse_cast("DIRTEN:cure light wounds>Brutus") == (
        "DIRTEN", "CURE LIGHT WOUNDS", "Brutus")
    for bad in ("DIRTEN:ANIMATE DEAD>BRUTUS", "SHARA:CURE BLINDNESS PHILIPPE",
                "ROLAND:DISPEL MAGIC", "DIRTEN:CURE LIGHT WOUNDS>"):
        with pytest.raises(ValueError):
            A.parse_cast(bad)


def test_pool_main_takes_a_cast_with_no_target(tmp_path):
    assert A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                   "--stage-only", "--steps", "load", "cast DIRTEN:PRAYER",
                   "--out", str(tmp_path / "prayer")]) == 0


def test_cast_prayer_walks_to_it_spends_it_and_ends_in_camp(tmp_path):
    sess = CampFake(DIRTEN)
    run = _run(tmp_path, sess)
    got = run.cast("DIRTEN:PRAYER")
    assert (got["spell"], got["spell_id"], got["key"]) == ("PRAYER", 42, "xtest-return")
    assert got["messages"] == ["DIRTEN CASTS", "PRAYER"]
    assert got["memorised_before"] == DIRTEN
    assert got["memorised_after"] == [1, 1, 3, 3, 3, 28]
    assert sess.sent.count(("key", "Down")) == 6
    assert sess.sent[:4] == [("party", 0), ("bar", "MAGIC"), ("bar", "CAST"),
                             ("bar", "CAST")]
    assert sess.sent[-3:] == [("key", "Return"), ("bar", "EXIT"), ("bar", "EXIT")]
    assert sess.state == "camp"


def test_cast_with_no_target_tries_the_kernal_return_when_return_was_lost(tmp_path):
    sess = CampFake(DIRTEN, lost_returns=1)
    run = _run(tmp_path, sess)
    got = run.cast("DIRTEN:PRAYER")
    assert got["key"] == "kernal-return" and got["spell_id"] == 42


def test_cast_with_no_target_fails_when_the_game_asks_whom(tmp_path):
    sess = CampFake(DIRTEN, whom_spells=(42,))
    run = _run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="asked CAST SPELL ON WHOM"):
        run.cast("DIRTEN:PRAYER")


def test_pool_main_takes_a_cast_with_a_target(tmp_path):
    assert A.main(["--title", "pool", "--save", str(_fixture_disk(tmp_path)),
                   "--stage-only", "--steps", "load",
                   "cast DIRTEN:CURE LIGHT WOUNDS>BRUTUS",
                   "--out", str(tmp_path / "cure")]) == 0


def test_cast_answers_the_target_question_with_the_named_member(tmp_path):
    sess = CampFake(DIRTEN, whom_spells=(3,), dispel_page=False)
    run = _run(tmp_path, sess)
    got = run.cast("DIRTEN:CURE LIGHT WOUNDS>DIRTEN")
    assert (got["spell"], got["target"], got["spell_id"]) == (
        "CURE LIGHT WOUNDS", "DIRTEN", 3)
    assert got["memorised_after"] == [1, 1, 3, 3, 28, 42]
    # The whom menu lists BRUTUS, then DIRTEN: the second row is chosen, after
    # the pick's Return, and chosen with a Return of its own.
    after_pick = sess.sent[sess.sent.index(("key", "Return")):]
    assert after_pick[1:3] == [("party", 1), ("key", "Return")]
    assert list(tmp_path.glob("*cast-whom.txt"))
    assert sess.state == "camp"


def test_cast_fails_when_the_target_is_not_on_the_whom_menu(tmp_path):
    sess = CampFake(DIRTEN, whom_spells=(3,), dispel_page=False)
    run = _run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="NOBODY could not be chosen"):
        run.cast("DIRTEN:CURE LIGHT WOUNDS>NOBODY")
    assert sess.state == "whom"


def test_cast_with_a_target_fails_when_the_game_never_asks_whom(tmp_path):
    sess = CampFake(DIRTEN, whom_spells=())
    run = _run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="without CAST SPELL ON WHOM, so "
                       "BRUTUS was never chosen"):
        run.cast("DIRTEN:CURE LIGHT WOUNDS>BRUTUS")


def test_cast_with_no_target_fails_before_any_key_without_the_spell_ready(tmp_path):
    sess = CampFake([1, 3, 0xAA])
    run = _run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="no PRAYER ready to cast"):
        run.cast("DIRTEN:PRAYER")
    assert sess.sent == []


def test_cast_with_no_target_fails_before_any_key_for_a_name_not_drawn(tmp_path):
    sess = CampFake(DIRTEN)
    run = _run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="FLAME STRIKE: no spell"):
        run.cast("DIRTEN:FLAME STRIKE")
    assert sess.sent == []


# -- Dispel Magic among other spells ----------------------------------------------

def _dispel_run(tmp_path, sess):
    run = _run(tmp_path, sess)
    rows = [[slot, 0, 0, 0, 0] for slot in range(64)]
    rows[63] = [63, 32, 5, 0, 5]

    def reading():
        held = [n for n in sess.memorised if n]
        effect_rows = [row.copy() for row in rows]
        if sess.dispelled and sess.state in ("magic", "camp"):
            effect_rows[63][1] = 0
        brutus = {"slot": 5, "name": "BRUTUS", "status": 0x03,
                  "traits": [0] * 9 + [32], "creature_type": 4}
        return {"party": [{"slot": SLOT, "name": "DIRTEN", "status": 1,
                           "cleric_level": 5, "memorised": held,
                           "traits": [0] * 10, "creature_type": 0}, brutus],
                "effects": [r for r in effect_rows if r[1]],
                "effect_rows": effect_rows}

    run.reading = reading
    return run


def test_dispel_is_picked_from_a_list_of_other_spells_and_aims_at_the_member(
        tmp_path):
    sess = CampFake([1, 3, 28, 41, 42])
    run = _dispel_run(tmp_path, sess)
    got = run.cast("DIRTEN:DISPEL MAGIC>BRUTUS")
    assert (got["spell_id"], got["target"], got["slot"]) == (41, "BRUTUS", 5)
    assert got["row_before"] == [63, 32, 5, 0, 5]
    assert got["row_after"] == [63, 0, 5, 0, 5]
    assert sess.sent.count(("key", "Down")) == 3
    assert ("party", 0) in sess.sent[sess.sent.index(("key", "Return")):]
    assert [n for n in sess.memorised if n] == [1, 3, 28, 42]
    assert sess.state == "magic"


def test_dispel_among_other_spells_leaves_the_pick_prompt_it_comes_back_to(
        tmp_path):
    sess = CampFake([1, 41, 42], dispel_page=False)
    run = _dispel_run(tmp_path, sess)
    got = run.cast("DIRTEN:DISPEL MAGIC>BRUTUS")
    assert got["row_after"] == [63, 0, 5, 0, 5]
    assert sess.sent[-2:] == [("key", "Return"), ("bar", "EXIT")]


def test_dispel_fails_before_any_key_when_the_caster_holds_no_dispel_magic(
        tmp_path):
    sess = CampFake([1, 3, 42])
    run = _dispel_run(tmp_path, sess)
    with pytest.raises(A.StepFailed, match="Dispel Magic id 41 memorised"):
        run.cast("DIRTEN:DISPEL MAGIC>BRUTUS")
    assert sess.sent == []


def test_an_interrupted_rest_is_also_a_result_of_the_run(tmp_path, monkeypatch):
    import json

    from tests.c64.test_c64acceptance import _drive, _Pool

    class Interrupted(_Pool):
        lost_reading = None

        def rest(self, arg):
            outcome = {"ended": "interrupted", "elapsed_minutes": 20,
                       "text": ["YOUR REST IS RUDELY INTERRUPTED!"], "then": "fight"}
            self.lost_reading = {"step": "rest offered", "outcome": outcome}
            raise A.RestInterrupted("the offered rest was interrupted")

    rc, _, out = _drive(tmp_path, monkeypatch, ["load", "rest offered"],
                        pool=Interrupted)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc != 0 and summary["completed"] is False
    last = summary["results"][-1]
    assert (last["step"], last["outcome"], last["minute"]) == (
        "rest offered", "interrupted", 20)
    assert last["interruption"] == "YOUR REST IS RUDELY INTERRUPTED!"
    assert summary["lost_reading"]["outcome"]["then"] == "fight"
