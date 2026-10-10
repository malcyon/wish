"""The Pools of Darkness `train N` step on Elminster's menu: its keys, its guard states and its title."""

from __future__ import annotations

import pytest

from tools.amiga import guardmaps, route_camp, route_darkness, screens
from tools.amiga.winuaesession import RouteError
from tools.registry import scratch

_LEAD = (
    ("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
    ("B", "disk2_prompt", "key"), route_darkness.DISK2_INSERT,
    ("V", "sheet", "key"), ("E", "loaded_menu", "key"),
    ("S", "save_picker", "key"), ("F", "loaded_menu", "write"),
    ("B", "journal", "key"), ("X", "journal_answer", "key"),
    ("RET", "elminster_menu", "key"))
_TAIL = (("R", "camp", "key"), ("S", "camp_save_picker", "key"),
         ("G", "exit_game", "write"), ("N", "camp", "key"))

# Line 3 of six: NP2 moves Elminster's highlight, his TRAIN opens the party menu with TRAIN
# CHARACTER offered, whose T asks DO YOU WISH TO TRAIN?, Y trains and puts the highlight on line 4,
# NP8 puts it back, and BEGIN ADVENTURING returns to Elminster's menu, assumed to keep line 3.
_TRAIN_3_OF_6 = (
    ("NP2", "elminster_row", "key"), ("NP2", "elminster_row", "key"),
    ("T", "train_menu", "key"), ("T", "train_prompt", "key"), ("Y", "train_menu", "key"),
    ("NP8", "train_menu", "key"), ("B", "elminster_menu", "key"),
    ("NP8", "elminster_row", "key"), ("NP8", "elminster_row", "key"))


def test_train_three_of_six_presses_the_measured_keys_and_leaves_line_one_highlighted():
    assert route_darkness.train_steps(3, 6) == _TRAIN_3_OF_6


def test_train_one_moves_no_highlight_on_elminsters_menu():
    assert route_darkness.train_steps(1, 6) == (
        ("T", "train_menu", "key"), ("T", "train_prompt", "key"), ("Y", "train_menu", "key"),
        ("NP8", "train_menu", "key"), ("B", "elminster_menu", "key"))


@pytest.mark.parametrize("text, line", [("train 3", 3), ("TRAIN 1", 1), ("  train   7 ", 7)])
def test_the_step_text_names_a_party_line(text, line):
    assert route_darkness.parse_train(text) == line


@pytest.mark.parametrize("text", ["train", "train 0", "train x", "train 3 4", "train -1",
                                  "train 03", "trian 3", "train 3h"])
def test_step_text_that_is_not_train_n_builds_nothing(text):
    with pytest.raises(RouteError, match="train N"):
        route_darkness.parse_train(text)


@pytest.mark.parametrize("line, size", [(0, 6), (6, 6), (7, 6), (1, 1), (2, 9), (1, 0)])
def test_a_line_outside_the_party_or_the_last_line_builds_no_steps(line, size):
    with pytest.raises(RouteError):
        route_darkness.train_steps(line, size)


def test_the_last_line_is_blocked_because_the_highlight_after_its_training_is_unmeasured():
    with pytest.raises(RouteError, match="last line"):
        route_darkness.train_steps(6, 6)


def test_the_train_title_runs_the_steps_between_elminsters_menu_and_the_camp_save():
    title = route_darkness.train_title(3, 6)
    assert title.route == (*_LEAD, *_TRAIN_3_OF_6, *_TAIL)
    assert title.measure_route == (*title.route[:7], *title.route[9:len(title.route) - 2])
    assert title.control_letter == "F" and title.after_letter == "G"
    # Every key of the step goes out on a screen its guard recognised, Y included.
    assert {"elminster_menu", "elminster_row", "train_menu", "train_prompt", "camp"} <= title.strict
    assert "world" not in title.strict
    assert title.interstitials == (route_darkness.DARKNESS_INTRO,)
    assert title.min_waits["elminster_row"] == route_camp.ROW_WAIT
    assert title.min_waits["train_menu"] == title.min_waits["train_prompt"] == 10.0
    assert title.plain_keys == (("E", "loaded_menu"),)


def test_the_train_title_takes_the_line_and_party_size_it_validates():
    with pytest.raises(RouteError):
        route_darkness.train_title(6, 6)


def test_the_vault_title_is_unchanged_by_the_shared_elminster_route():
    vault = route_darkness.vault_title(3, False)
    assert vault.route == (
        *_LEAD, ("S", "vault_bar", "key"), ("T", "vault_items", "key"),
        ("NP2", "vault_row", "key"), ("NP2", "vault_row", "key"),
        ("E", "vault_bar", "key"), ("E", "elminster_menu", "key"), *_TAIL)
    assert "train_menu" not in vault.strict and "elminster_row" not in vault.strict


def test_the_committed_darkness_map_guards_every_train_state():
    spec = guardmaps._load(guardmaps.pathlib.Path(guardmaps.__file__).parent, "darkness")
    for state in {s for _, s, _ in route_darkness.train_steps(3, 6)}:
        assert state in spec["guards"], state


_SHOTS = "WISH-2/train-measure/measure1/shots/"
_SEEN = {
    "elminster_menu": ["14-elminster", "25-begin", "26-begin-b"],
    "elminster_row": ["15-elm-np2", "16-elm-np2-marit"],
    "train_menu": ["17-train", "19-train-yes", "21-np8-marit", "24-menu-esc", "30-train-yvonne"],
    "train_prompt": ["18-train-char"],
}
_OTHERS = ["07-loaded", "11-trond-hl", "09-marit-sheet", "27-rest-camp"]


def test_the_train_guards_match_their_measured_screens_and_not_the_neighbours(tmp_path):
    """Reads the crops kept from the measuring boot, so it skips on a machine without them."""
    root = scratch.cache_dir("acceptance")
    crops = [*(c for names in _SEEN.values() for c in names), *_OTHERS]
    if not all((root / f"{_SHOTS}{c}.png").is_file() for c in crops):
        pytest.skip("the kept train measure crops are not on this machine")
    maps = guardmaps.pathlib.Path(guardmaps.__file__).parent
    out = tmp_path / "darkness"
    assert guardmaps.main(["--maps", str(maps), "export", "--title", "darkness",
                           "--out", str(out)]) == 0
    guard = screens.PixelGuards(out / "guards.json")
    # Elminster's highlight moves draw the same bar as his menu, so each guard names the other.
    alike = {"elminster_menu": {"elminster_row"}, "elminster_row": {"elminster_menu"}}
    for state, names in _SEEN.items():
        for name in names:
            assert guard(state, root / f"{_SHOTS}{name}.png"), (state, name)
        for other, other_names in _SEEN.items():
            if other == state or other in alike.get(state, set()):
                continue
            for name in other_names:
                assert not guard(state, root / f"{_SHOTS}{name}.png"), (state, name)
        for name in _OTHERS:
            assert not guard(state, root / f"{_SHOTS}{name}.png"), (state, name)
