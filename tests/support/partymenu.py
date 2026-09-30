"""A real `automap.screen.Screen` of the C64 party menu, for `load_started`.

Only the cells the reading depends on are drawn: the menu entries, the window
frame, the white heading row above them and row 24. On a healthy menu waiting
for a key one entry is white in the column the labels start in (the cursor
starts on VIEW CHARACTER, not on BEGIN ADVENTURING); once the game has taken
the choice none is, and row 24 reads `ONWARD BOUND`.
"""

from __future__ import annotations

from automap.screen import SCREEN_COLS, SCREEN_ROWS, Screen

ENTRIES = ("CREATE NEW CHARACTER", "DROP CHARACTER", "MODIFY CHARACTER",
           "VIEW CHARACTER", "ADD CHARACTER TO PARTY",
           "REMOVE CHARACTER FROM PARTY", "SAVE CURRENT GAME",
           "HUMAN CHANGE CLASS", "BEGIN ADVENTURING")
FIRST_ROW = 13
BEGIN_ROW = FIRST_ROW + len(ENTRIES) - 1
COLUMN = 2

_TO_CODE = {" ": 0x20, "@": 0x00}


def _codes(text: str) -> list[int]:
    return [_TO_CODE.get(c, ord(c) - 64 if c.isalpha() else ord(c))
            for c in text]


def menu_screen(cursor: int | None, row24: str = "") -> Screen:
    """The menu with entry index `cursor` white (None: no entry white)."""
    codes = [0x20] * (SCREEN_COLS * SCREEN_ROWS)
    colours = [5] * (SCREEN_COLS * SCREEN_ROWS)

    def put(row: int, col: int, text: str) -> None:
        at = row * SCREEN_COLS + col
        codes[at:at + len(text)] = _codes(text)

    # The heading is white at the label column too, and the frame is white.
    put(2, COLUMN, "NAME")
    for c in range(COLUMN, COLUMN + 4):
        colours[2 * SCREEN_COLS + c] = 1
    for i, label in enumerate(ENTRIES):
        put(FIRST_ROW + i, COLUMN, label)
    for r in range(1, 23):
        put(r, 0, "$")
        colours[r * SCREEN_COLS] = 1
    if cursor is not None:
        colours[(FIRST_ROW + cursor) * SCREEN_COLS + COLUMN] = 1
    put(24, 0, row24)
    return Screen(bytes(codes), bytes(colours), 0x0400)
