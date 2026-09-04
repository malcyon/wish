"""`tools/dospod.py`, the Pools of Darkness drive (#175).

Driving the game needs DOSBox, an X display and about a minute a boot, so
what is tested here is the part that decides what a run *does* -- the step
grammar and where the game directory is found. A mis-parsed step is the one
failure that wastes a whole boot and does not look like a failure: `!C`
pressed as a key rather than snapshotting produces a run with no saves in it
and a log that reads as if everything worked.
"""

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import dospod  # noqa: E402

# --- the step grammar --------------------------------------------------------


def test_a_bare_keysym_is_pressed():
    for key in ("Return", "Escape", "Up", "c", "1"):
        assert dospod.step_kind(key) == ("key", key)


def test_a_bang_snapshots_and_does_not_press_anything():
    """The saves are the whole point of a run, and this is the prefix that
    takes them."""
    assert dospod.step_kind("!C") == ("snapshot", "C")
    assert dospod.step_kind("!before-the-step") == ("snapshot", "before-the-step")


def test_an_at_sign_is_a_double_click_at_a_screen_pixel():
    """320x200, so a pixel in a capture is a pixel here -- the tool sets
    `output=surface` with `scaler=none` for exactly that."""
    assert dospod.step_kind("@110,155") == ("click", (110, 155))
    assert dospod.step_kind("@0,0") == ("click", (0, 0))


def test_a_click_with_no_comma_is_refused_rather_than_pressed_as_a_key():
    """Falling back to "press it as a key" would swallow the typo and leave
    the run looking like it worked."""
    with pytest.raises(ValueError):
        dospod.step_kind("@110")


# --- finding the game --------------------------------------------------------


def test_the_launcher_looked_for_is_the_batch_file_not_the_exe():
    """This title ships `STARTUP.EXE` and a `START.BAT`, so the shared
    `dosbox.find_game`, which looks for `START.EXE`, finds nothing here."""
    assert dospod.STEM == "DARKNESS"
    source = pathlib.Path(dospod.__file__).read_text()
    assert 'START.BAT' in source
    assert 'exe="START.BAT"' in source


def test_a_missing_archive_directory_is_named_rather_than_searched(monkeypatch,
                                                                   tmp_path):
    monkeypatch.setattr(dospod.dosbox, "ARCHIVES", tmp_path / "nowhere")
    with pytest.raises(FileNotFoundError) as raised:
        dospod.find_game()
    assert "nowhere" in str(raised.value)


def test_a_game_tree_is_found_by_its_batch_file(monkeypatch, tmp_path):
    """The layout inside the archives is
    `<collection>/games/<title>/GAME/<stem>/`, which is two levels of
    directory nobody would guess from the title alone."""
    inner = tmp_path / "Collection Two" / "games" / "Pools of Darkness" \
        / "GAME" / dospod.STEM
    inner.mkdir(parents=True)
    (inner / "START.BAT").write_text("@echo off\n")
    monkeypatch.setattr(dospod.dosbox, "ARCHIVES", tmp_path)
    assert dospod.find_game() == inner


def test_a_tree_without_the_batch_file_is_not_mistaken_for_the_game(monkeypatch,
                                                                    tmp_path):
    inner = tmp_path / "Collection Two" / "games" / "Something" / "GAME" \
        / dospod.STEM
    inner.mkdir(parents=True)
    (inner / "STARTUP.EXE").write_bytes(b"MZ")
    monkeypatch.setattr(dospod.dosbox, "ARCHIVES", tmp_path)
    with pytest.raises(FileNotFoundError):
        dospod.find_game()
