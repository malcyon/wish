"""`tools/c64/openingscene.py`'s pure parts, offline: the row-24 classifier,
the save-before-press loop, the stop conditions and the experience comparison."""

import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.c64 import openingscene  # noqa: E402


def screen(row24: str = "", body: str = "") -> str:
    rows = [body] + [""] * 23 + [row24]
    return "\n".join(rows)


def test_a_side_prompt_is_a_disk_prompt_not_a_press_prompt():
    assert openingscene.opening_step(
        "INSERT SIDE # 2, AND PRESS ANY KEY.", "", disk_wanted=True) == "disk"


@pytest.mark.parametrize("row24,step", [
    ("MOVE VIEW CAST AREA ENCAMP SEARCH LOOK", "world"),
    ("PRESS BUTTON OR RETURN TO CONTINUE.", "return"),
    ("VIEW TAKE POOL SHARE EXIT", "exit"),
    ("YES NO", "no"),
    ("EXIT" + " " * 36, "exit"),
    ("", "wait"),
])
def test_opening_step_reads_each_bar(row24, step):
    assert openingscene.opening_step(row24, row24, disk_wanted=False) == step


class Fake:
    """A scripted machine: `read` walks through `screens`, one per call."""

    def __init__(self, screens):
        self.screens, self.i, self.t = list(screens), 0, 0.0
        self.events = []

    def read(self):
        s = self.screens[min(self.i, len(self.screens) - 1)]
        self.i += 1
        return s

    def save(self, n, text):
        self.events.append(("save", n))

    def act(self, step, text):
        self.events.append(("act", step))

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def watch(self, **kw):
        return openingscene.watch(
            self.read, self.save, self.act, lambda t: False,
            clock=self.clock, sleep=self.sleep, **kw)


def test_each_new_screen_is_saved_before_anything_is_pressed():
    a, b = screen("PRESS BUTTON OR RETURN TO CONTINUE.", "ONE"), \
        screen("PRESS BUTTON OR RETURN TO CONTINUE.", "TWO")
    # The game blanks row 24 between story pages (the m2-ssb run,
    # `~/.cache/wish/i653/m2-ssb/`, screens 10 to 20: PRESS, then blank, then
    # PRESS), so the fake pages have a blank-row-24 screen between them.
    blank = screen("", "ONE")
    f = Fake([a, a, blank, b, screen("MOVE ENCAMP")])
    assert f.watch(wait=100) == "world"
    assert f.events == [("save", 1), ("act", "return"), ("save", 2),
                        ("save", 3), ("act", "return"), ("save", 4)]


def test_a_redraw_under_an_unchanged_prompt_is_not_answered_again():
    prompt = "PRESS (RETURN) OR BUTTON TO CONTINUE"
    f = Fake([screen(prompt, "EACH SHARE IS 2500 EXPERIENCE POINTS"),
              screen(prompt, "PARTY PANEL"), screen("VIEW TAKE POOL SHARE EXIT")])
    f.watch(wait=5)
    assert [e[1] for e in f.events if e[0] == "act"] == ["return", "exit"]


def test_an_unchanged_screen_presses_nothing_until_the_repeat_time():
    a = screen("PRESS BUTTON OR RETURN TO CONTINUE.")
    f = Fake([a])
    f.watch(wait=9)
    assert f.events == [("save", 1), ("act", "return")]


def test_the_action_is_repeated_and_then_the_run_is_stuck():
    f = Fake([screen("PRESS ANY KEY")])
    assert f.watch(wait=1000) == "stuck"
    assert [e for e in f.events if e[0] == "act"] == [("act", "return")] * 4


def test_a_screen_nothing_recognises_is_saved_and_left_until_timeout():
    f = Fake([screen("", "STORY")])
    assert f.watch(wait=20) == "timeout"
    assert f.events == [("save", 1)]


def test_the_screen_limit_stops_the_run():
    f = Fake([screen("", str(i)) for i in range(10)])
    assert f.watch(wait=1000, max_screens=3) == "screens"
    assert f.events == [("save", 1), ("save", 2), ("save", 3)]


def test_a_bitmap_is_not_a_screen():
    f = Fake([None, None, screen("MOVE ENCAMP")])
    assert f.watch(wait=100) == "world"
    assert f.events == [("save", 1)]


def test_experience_is_matched_by_name_not_by_slot():
    rows = openingscene.experience_delta({"A": 200000, "B": 100000},
                                         {"B": 101250, "A": 202750})
    assert {r["name"]: r["delta"] for r in rows} == {"A": 2750, "B": 1250}


def test_a_character_on_one_side_only_is_kept():
    rows = openingscene.experience_delta({"A": 1, "B": 2}, {"A": 5, "C": 7})
    by = {r["name"]: r for r in rows}
    assert by["B"]["after"] is None and by["B"]["delta"] is None
    assert by["C"]["before"] is None and by["C"]["after"] == 7
    assert by["A"]["delta"] == 4


def test_the_first_opening_text_skips_the_menu_and_disk_prompts():
    texts = [screen("", "CREATE NEW CHARACTER"),
             screen("ONWARD BOUND ..."),
             screen("INSERT SIDE # 2, AND PRESS ANY KEY."), screen("", "STORY")]
    assert openingscene.first_opening_text(texts) == texts[3]
    assert openingscene.first_opening_text(texts[:3]) is None


def test_the_game_s_own_silver_blades_party_reads_by_name():
    from automap import gamedisks
    disks = gamedisks.find("secret-of-the-silver-blades")
    disk = disks / "SILVER-6.D64" if disks else None
    if disk is None or not disk.exists():
        pytest.skip("no Silver Blades disks")
    got = openingscene.experience_map(disk)
    assert len(got) == 6
    assert got["GUY DE VALOIS"] == 200000 and got["MALACHITE"] == 100000


class Bar:
    def __init__(self, row24="TAKE EXIT"):
        self.row24, self.pressed = row24, []

    def row(self, r):
        return self.row24


class Sess:
    def __init__(self, again):
        self.again, self.pressed = again, []

    def select_bar(self, word, timeout):
        pass

    def screen(self):
        return self.again

    def press_kernal(self, code):
        self.pressed.append(code)


@pytest.mark.parametrize("before,after", [(None, Bar()), (Bar(), None),
                                          (None, None)])
def test_a_bitmap_at_a_bar_is_waited_out_not_fatal(before, after):
    sess = Sess(after)
    openingscene.answer_bar(sess, "exit", before, sleep=lambda s: None)
    assert sess.pressed == []


def test_an_unchanged_bar_gets_return_and_a_changed_one_does_not():
    same, moved = Sess(Bar("TAKE EXIT")), Sess(Bar("MOVE ENCAMP"))
    openingscene.answer_bar(same, "no", Bar("TAKE EXIT"), sleep=lambda s: None)
    openingscene.answer_bar(moved, "no", Bar("TAKE EXIT"), sleep=lambda s: None)
    assert same.pressed == [0x0D] and moved.pressed == []


class Closer:
    def __init__(self, log, name, fail=False):
        self.log, self.name, self.fail = log, name, fail

    def _do(self, what):
        self.log.append(what)
        if self.fail:
            raise RuntimeError(what)

    def close(self):
        self._do("close")

    def teardown(self):
        self._do("teardown")

    def release(self):
        self.log.append("release")


@pytest.mark.parametrize("failing", ["close", "teardown"])
def test_the_summary_and_release_run_when_closing_raises(failing):
    log = []

    class S(Closer):
        def close(self):
            self._do("close") if failing == "close" else self.log.append("close")

    class Sl(Closer):
        def teardown(self):
            self._do("teardown") if failing == "teardown" \
                else self.log.append("teardown")

    sess, slot = S(log, "s", fail=True), Sl(log, "l", fail=True)
    with pytest.raises(RuntimeError):
        openingscene.shut_down(sess, slot, lambda: log.append("summary"))
    assert "summary" in log and log[-1] == "release"


def test_two_characters_with_one_name_keep_both_rows():
    got = openingscene.keyed_by_name([("AL", 1), ("BO", 2), ("AL", 3)])
    assert got == {"AL": 1, "BO": 2, "AL (2)": 3}


class World:
    def __init__(self, saved=True):
        self.log, self.saved = [], saved

    def settle(self, s):
        self.log.append(("settle", s))

    def save_game(self):
        self.log.append("save_game")
        return self.saved

    def screen(self):
        return Bar("--SAVE ERROR--")


@pytest.mark.parametrize("saved", [True, False])
def test_the_world_bar_settles_before_camping_and_a_shot_follows(saved):
    w, notes = World(saved), []
    got = openingscene.save_at_world(
        w, lambda tag: w.log.append(("shot", tag)),
        lambda **kw: notes.append(kw))
    assert got is saved
    assert w.log == [("settle", 4), "save_game", ("shot", "after-save")]
    assert notes == [{"event": "save", "ok": saved, "row24": "--SAVE ERROR--"}]


def resave(outcomes):
    """Run `copy_resave` with a copy that returns or raises each outcome in turn."""
    calls, notes, seen = [], [], []

    def copy(src, dest, **kw):
        calls.append(kw)
        seen.append(kw)
        out = outcomes[len(seen) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    def detach():
        calls.append("detach")

    return calls, notes, lambda: openingscene.copy_resave(
        copy, detach, "s", "d", lambda **kw: notes.append(kw))


def test_a_disk_that_closes_while_polled_is_copied_without_a_detach():
    calls, notes, go = resave(["d"])
    assert go() == "d"
    assert calls == [{"attempts": 120, "backoff": 0.5}]
    assert [n["ok"] for n in notes] == [True]


def test_a_disk_still_open_after_polling_is_detached_and_copied_again():
    calls, notes, go = resave([RuntimeError("open"), "d"])
    assert go() == "d"
    assert calls == [{"attempts": 120, "backoff": 0.5}, "detach", {}]
    assert [(n["stage"], n["ok"]) for n in notes] == [
        ("polled", False), ("after-detach", True)]


def test_a_disk_open_even_after_the_detach_is_refused():
    calls, notes, go = resave([RuntimeError("a"), RuntimeError("b")])
    with pytest.raises(RuntimeError, match="b"):
        go()
    assert calls.count("detach") == 1
