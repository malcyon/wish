"""A disk prompt is answered with a disk, not with a keystroke (#336).

`INSERT SIDE # 3, AND PRESS ANY KEY.` carries the word `PRESS`, and
`Session.combat_state` classified anything carrying it as `BAR_PRESS` -- the
`PRESS <RETURN> OR BUTTON TO CONTINUE` bar an arrival scene puts up.  So
`wait_for_world` took the `BAR_PRESS` branch, injected a Return, waited for
row 24 to change, and went round again **without ever reaching
`handle_prompt`**: the side the game asked for was never put in the drive, the
game asked again, and `begin_adventuring` returned False after its whole
240-second budget.

Driven on pool slot 0 on 2026-09-07, `work/screenblind/run3`: the reader saw
`INSERT SIDE # 3, AND PRESS ANY KEY.` on row 24 of 38 of the run's last 40
polls -- so the screen reader was not blind at all in that run -- and the run
still ended `arrived=False` with two disks attached where the working runs
attached three.

Nothing here needs an emulator.  `FakeSession` is a `Session` whose screen and
drive are dictionaries, so what is under test is what the driver decides to do
with a row 24 it can read perfectly well.
"""

from __future__ import annotations

from conftest import load_tools_module

S = load_tools_module("session")

SIDE_PROMPT = "INSERT SIDE # 3, AND PRESS ANY KEY."
SAVE_PROMPT = "INSERT SAVE GAME DISK, PRESS ANY KEY"
CONTINUE_BAR = "PRESS <RETURN> OR BUTTON TO CONTINUE"
WORLD_BAR = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"


def screen_of(row24: str, rows: dict[int, str] | None = None):
    """A `Screen` with *row24* on the bottom row and nothing else."""
    codes = bytearray(0x20 for _ in range(1000))
    for row, text in {**(rows or {}), 24: row24}.items():
        for i, ch in enumerate(text.upper()):
            codes[row * 40 + i] = ord(ch) - 0x40 if "A" <= ch <= "Z" else ord(ch)
    from automap.screen import Screen
    return Screen(bytes(codes), bytes(1000), 0xCC00)


class FakeSession(S.Session):
    """A driver whose screen, drive and keyboard are lists."""

    def __init__(self, screens):
        self.screens = list(screens)
        self.attached = "/slot/SIDE1.D64"
        self.here = "/slot"
        self.save_disk = "/slot/SIDE0.D64"
        self._last_prompt = 0.0
        self.attaches: list[str] = []
        self.keys: list[str] = []
        self.kernal: list[int] = []
        self.said: list[str] = []

        class Kbd:
            def key(kself, name, hold=0.0, gap=0.0):
                self.keys.append(name)

        self.kbd = Kbd()

    # -- the machine, faked ----------------------------------------------

    def screen(self):
        if len(self.screens) > 1:
            return self.screens.pop(0)
        return self.screens[0]

    def attach(self, path, unit: int = 8, settle=None) -> None:
        self.attaches.append(path)
        self.attached = path

    def press_kernal(self, code: int) -> None:
        self.kernal.append(code)

    def await_change(self, text, timeout=6.0) -> bool:
        return False

    def log(self, *a) -> None:
        self.said.append(" ".join(str(x) for x in a))


# -- the classification ------------------------------------------------------


def test_a_side_prompt_is_a_disk_prompt_and_not_a_continue_bar():
    sess = FakeSession([screen_of(SIDE_PROMPT)])
    assert sess.combat_state().kind == S.BAR_DISK


def test_a_save_game_disk_prompt_is_a_disk_prompt_too():
    sess = FakeSession([screen_of(SAVE_PROMPT)])
    assert sess.combat_state().kind == S.BAR_DISK


def test_the_continue_bar_is_still_a_press_bar():
    """The bar an arrival scene puts up, which *is* answered with a key --
    `THE BOAT DISEMBARKS YOU AT SOKAL KEEP.` and this underneath it (#182)."""
    sess = FakeSession([screen_of(CONTINUE_BAR)])
    assert sess.combat_state().kind == S.BAR_PRESS


def test_a_disk_prompt_still_counts_as_the_move_sub_bar_having_gone():
    """It was `BAR_PRESS`, which is in `AFTER_MOVE`, so leaving it out would
    make a waiter that used to see the sub-bar go sit out its whole timeout."""
    assert S.BAR_DISK in S.AFTER_MOVE


# -- what the driver does with it --------------------------------------------


def test_waiting_for_the_world_puts_the_disk_in_rather_than_pressing_return():
    """The run that failed: the prompt on the screen, and nothing attached."""
    sess = FakeSession([screen_of(SIDE_PROMPT), screen_of(WORLD_BAR)])
    assert sess.wait_for_world(timeout=5.0, interval=0.0) is True
    assert sess.attaches == ["/slot/SIDE3.D64"]
    assert sess.keys == ["space"]
    assert sess.kernal == [], "a Return at a disk prompt leaves the drive wrong"


def test_waiting_for_the_world_still_answers_an_arrival_scene():
    """`PRESS <RETURN> OR BUTTON TO CONTINUE` is answered through the KERNAL
    buffer and attaches nothing (#182)."""
    sess = FakeSession([screen_of(CONTINUE_BAR), screen_of(WORLD_BAR)])
    assert sess.wait_for_world(timeout=5.0, interval=0.0) is True
    assert sess.kernal == [0x0D]
    assert sess.attaches == []


def test_a_disk_prompt_off_row_24_is_still_answered():
    """The game asks in three wordings on two rows, and `combat_state` only
    ever sees row 24."""
    sess = FakeSession([screen_of("", {12: SIDE_PROMPT}), screen_of(WORLD_BAR)])
    assert sess.wait_for_world(timeout=5.0, interval=0.0) is True
    assert sess.attaches == ["/slot/SIDE3.D64"]


def test_a_prompt_the_driver_cannot_read_is_not_answered_as_a_bar():
    """A blank row 24 is a blank row 24: nothing is pressed and nothing is
    attached, which is the state `wait_for_world` should wait through."""
    sess = FakeSession([screen_of(""), screen_of(WORLD_BAR)])
    assert sess.wait_for_world(timeout=5.0, interval=0.0) is True
    assert sess.attaches == []
    assert sess.kernal == []
