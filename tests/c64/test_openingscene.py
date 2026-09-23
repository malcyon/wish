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
    f = Fake([a, a, b, screen("MOVE ENCAMP")])
    assert f.watch(wait=100) == "world"
    assert f.events == [("save", 1), ("act", "return"), ("save", 2),
                        ("act", "return"), ("save", 3)]


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
             screen("INSERT SIDE # 2, AND PRESS ANY KEY."), screen("", "STORY")]
    assert openingscene.first_opening_text(texts) == texts[2]
    assert openingscene.first_opening_text(texts[:2]) is None


def test_the_game_s_own_silver_blades_party_reads_by_name():
    from automap import gamedisks
    disks = gamedisks.find("secret-of-the-silver-blades")
    disk = disks / "SILVER-6.D64" if disks else None
    if disk is None or not disk.exists():
        pytest.skip("no Silver Blades disks")
    got = openingscene.experience_map(disk)
    assert len(got) == 6
    assert got["GUY DE VALOIS"] == 200000 and got["MALACHITE"] == 100000
