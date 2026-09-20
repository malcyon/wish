"""Checks the key-list expansion and the per-press log of the DOS Curse
`MEMORIZE` page-turn driver, against a fake session.

`#574 (Camp.memorize's page-turn landing is stateful and not proven for page >
0)` needs four values after every keypress, and a run that stops pressing once
the grimoire is no longer showing.  Both are the parts of
`tools/curse_of_the_azure_bonds/cursememorize.py` that hold without an
emulator.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

pytest.importorskip("tools.curse_of_the_azure_bonds.cursememorize")
from tools.curse_of_the_azure_bonds import cursememorize as cm  # noqa: E402


class FakeScreen:
    """Only what `press_sequence` reads off a capture."""

    def __init__(self, row, bar="bar", digest="dig"):
        self._row, self._bar, self._digest = row, bar, digest

    def highlight_row(self, rect, **kw):
        return self._row

    def glyphs(self, rect=None):
        return self._bar

    def digest(self, rect=None):
        return self._digest


class FakeSession:
    """Records keys, hands out canned screens, writes no file."""

    def __init__(self, screens):
        self.screens = list(screens)
        self.keys: list[str] = []
        self.shots: list[str] = []

    def key(self, *keys, **kw):
        self.keys.extend(keys)

    def settle(self, **kw):
        return self.screens.pop(0) if self.screens else FakeScreen(None)

    def shot(self, name, allow_blank=False):
        self.shots.append(name)
        return pathlib.Path(f"{name}.png")


def test_expand_keys_splits_words_and_repeats():
    assert cm.expand_keys(["n End*3"]) == ["n", "End", "End", "End"]
    assert cm.expand_keys(["End", "n"]) == ["End", "n"]
    assert cm.expand_keys(["~0.5 Return"]) == ["~0.5", "Return"]


def test_shot_name_keeps_no_punctuation_from_a_keysym():
    assert cm.shot_name("t0", 3, "~0.5") == "t0-03-_0_5"
    assert cm.shot_name("t0", 3, "Return") == "t0-03-Return"


def test_press_sequence_logs_four_values_for_every_press():
    s = FakeSession([FakeScreen(10, "barA", "d0"), FakeScreen(1, "barA", "d1")])
    rows: list[dict] = []
    out = cm.press_sequence(s, ["n", "End"], rows.append, tag="t0")
    assert s.keys == ["n", "End"]
    assert [(r["key"], r["row"], r["bar"], r["digest"]) for r in out] == [
        ("n", 10, "barA", "d0"),
        ("End", 1, "barA", "d1"),
    ]
    assert rows == out and s.shots == ["t0-00-n", "t0-01-End"]


def test_press_sequence_stops_after_two_unhighlighted_screens():
    s = FakeSession([FakeScreen(4), FakeScreen(None), FakeScreen(None),
                     FakeScreen(4)])
    rows: list[dict] = []
    out = cm.press_sequence(s, ["End"] * 4, rows.append, tag="t1")
    assert s.keys == ["End"] * 3
    assert [r["row"] for r in out] == [4, None, None]
    assert rows[-1]["key"] == "<stop>"


def test_press_sequence_presses_through_blanks_when_asked():
    s = FakeSession([FakeScreen(None)] * 3)
    out = cm.press_sequence(s, ["e", "m", "m"], lambda r: None, tag="path",
                            blank_stop=0)
    assert [r["key"] for r in out] == ["e", "m", "m"]


def test_a_sleep_token_presses_nothing():
    s = FakeSession([FakeScreen(2)])
    cm.press_sequence(s, ["~0"], lambda r: None, tag="t2")
    assert s.keys == []


def test_sample_reads_the_entry_state_without_a_keypress():
    s = FakeSession([FakeScreen(10, "barA", "d0")])
    rows: list[dict] = []
    row = cm.sample(s, rows.append, tag="t0")
    assert s.keys == [] and row["n"] == -1 and row["key"] == ""
    assert (row["row"], row["bar"], row["digest"]) == (10, "barA", "d0")
    assert rows == [row]
