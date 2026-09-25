"""`tools/dos/dospod.py`, the Pools of Darkness drive (#175).

Driving the game needs DOSBox, an X display and about a minute a boot, so
what is tested here is the part that decides what a run *does* -- the step
grammar, where the game directory is found, and how the journal question is
known and answered, on synthetic frames. A mis-parsed step is the one
failure that wastes a whole boot and does not look like a failure: `!C`
pressed as a key rather than snapshotting produces a run with no saves in it
and a log that reads as if everything worked.
"""

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.dos import dosbox, dospod  # noqa: E402

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


# --- the copy-protection question ------------------------------------------


class _Screen:
    def __init__(self, text: str):
        self.text = text

    def digest(self, rect=None) -> str:
        return self.text


class _Boot:
    """Title screens that Escape dismisses, then either the question -- which
    draws each typed key and takes Return -- or the party menu, where a digit
    does nothing and Return would pick `Create New Character`."""

    def __init__(self, question: bool, refuses: bool = False):
        self.titles, self.question, self.refuses = 2, question, refuses
        self.typed, self.keys, self.created = "", [], False

    def screen(self) -> str:
        if self.titles:
            return f"title{self.titles}"
        return f"question:{self.typed}" if self.question else "menu"

    def key(self, k: str) -> None:
        self.keys.append(k)
        if self.titles:
            self.titles -= k == "Escape"
        elif self.question and k == "Return":
            self.question, self.typed = self.refuses, ""
        elif self.question and k != "Escape":
            self.typed += k
        elif k == "Return":
            self.created = True

    def settle(self, quiet=0.5, timeout=8.0):
        return _Screen(self.screen())

    def wait_for(self, pred, timeout=30.0) -> bool:
        return bool(pred(_Screen(self.screen())))


@pytest.fixture
def _no_sleep(monkeypatch):
    monkeypatch.setattr(dospod.time, "sleep", lambda s: None)


@pytest.mark.parametrize("question", [False, True])
def test_the_party_menu_is_reached_and_return_is_never_pressed_on_it(
        _no_sleep, question):
    boot = _Boot(question)
    answered = dospod.to_party_menu(boot)
    assert boot.screen() == "menu" and not boot.created
    assert len(answered) == int(question)
    assert [k for k in boot.keys if k != "Escape"] == (
        [dospod.PROTECTION_PROBE, "Return"] if question else []) + [
        dospod.PROTECTION_PROBE]


def test_a_question_that_keeps_coming_back_stops_the_boot(_no_sleep):
    boot = _Boot(True, refuses=True)
    with pytest.raises(TimeoutError, match="still answering"):
        dospod.to_party_menu(boot, questions=2)
    assert boot.keys.count("Return") == 2


# --- the journal question after Begin Adventuring --------------------------


def _journal_screen(typed: int = 0, prompt: bool = True, line: bool = True):
    """A synthetic frame: sparse ink in the prompt's six cells and on the
    question's first line, and one lit cell per typed letter to the right of
    the prompt.  It stands in for the game's screen by construction; the
    committed digests are replaced with this frame's own in `_journal`."""
    w, h = 320, 200
    px = bytearray(w * h * 3)

    def lit(x, y):
        px[(y * w + x) * 3:(y * w + x) * 3 + 3] = b"\x55\xff\x55"

    rect = dospod.JOURNAL_PROMPT_RECT
    for cell in range(6 + typed):
        if cell < 6 and not prompt:
            continue
        for dy in range(rect[3]):
            lit(cell * 8 + (dy + cell) % 8, rect[1] + dy)
    if line:
        x0, y0, lw, lh = dospod.JOURNAL_LINE_RECT
        for x in range(x0, x0 + lw, 3):
            lit(x, y0 + x % lh)
    return dosbox.Screen(w, h, bytes(px))


@pytest.fixture
def _journal(monkeypatch):
    frame = _journal_screen()
    monkeypatch.setattr(dospod, "JOURNAL_PROMPT",
                        frame.glyphs(dospod.JOURNAL_PROMPT_RECT))
    monkeypatch.setattr(dospod, "JOURNAL_LINE",
                        frame.glyphs(dospod.JOURNAL_LINE_RECT))


class _Question:
    """The question as `GAME.OVR` 0x3603 draws it: each typed key is drawn,
    `Return` with something typed leaves for the map.  `swallow` drops the
    first key; `refuses` never leaves."""

    def __init__(self, showing=True, swallow=False, refuses=False):
        self.showing, self.swallow, self.refuses = showing, swallow, refuses
        self.typed, self.keys = 0, []

    def capture(self):
        if self.showing:
            return _journal_screen(self.typed)
        return dosbox.Screen(320, 200, bytes(320 * 200 * 3))

    def key(self, k):
        self.keys.append(k)
        if self.swallow:
            self.swallow = False
        elif k == "Return" and self.typed and not self.refuses:
            self.showing = False
        elif len(k) == 1:
            self.typed += 1

    def wait_for(self, pred, timeout=30.0):
        return bool(pred(self.capture()))


def test_the_question_is_known_by_both_digests_and_nothing_else(_journal):
    """Typing does not hide it; either recogniser alone is not enough."""
    for typed in (0, 1, 5):
        assert dospod.journal_question(_journal_screen(typed))
    assert not dospod.journal_question(_journal_screen(line=False))
    assert not dospod.journal_question(_journal_screen(prompt=False))
    assert not dospod.journal_question(dosbox.Screen(320, 200, bytes(320 * 200 * 3)))


def test_the_committed_recognisers_are_digests_not_words():
    for digest in (dospod.JOURNAL_PROMPT, dospod.JOURNAL_LINE):
        assert len(digest) == 16 and int(digest, 16) >= 0


def test_the_question_gets_one_letter_and_return(_journal):
    game = _Question()
    assert dospod.answer_journal(game)
    assert game.keys == [dospod.JOURNAL_ANSWER, "Return"] and not game.showing


def test_a_swallowed_letter_is_typed_again_while_the_question_stays(_journal):
    game = _Question(swallow=True)
    assert dospod.answer_journal(game)
    assert game.keys == [dospod.JOURNAL_ANSWER, "Return"] * 2


def test_a_question_that_never_goes_stops_after_its_tries(_journal):
    game = _Question(refuses=True)
    with pytest.raises(TimeoutError, match="still showing after 2"):
        dospod.answer_journal(game, tries=2)
    assert game.keys == [dospod.JOURNAL_ANSWER, "Return"] * 2


def test_nothing_is_pressed_when_the_question_is_not_showing(_journal):
    game = _Question(showing=False)
    assert not dospod.answer_journal(game)
    assert game.keys == []
