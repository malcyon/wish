"""Reads what a DOS Gold Box screen shows: the command bar, the status-line square, the roster and sheet names and the `ITEMS` list.

Each reader takes a `dosbox.Screen` and returns a digest or a row number, and
decides nothing about the run; `acceptance.py` compares them with what a step
expects.
"""
from __future__ import annotations

import hashlib

from tools.dos import dosbox

#: One character cell of the command bar.
CELL = 8

#: The readied column, one 8-pixel band a row: a row is drawn when a pixel of
#: its band has r+g+b above `ITEM_INK`.  Read right on 14 of 14 captures.
ITEM_READIED_COLUMN = (16, 40, 24, 144)

ITEM_INK = 60

#: The list's rows, for `Screen.highlight_row`.  The highlighted row lights
#: 629-1,114 near-white pixels and the mouse arrow at most 22, so a minimum of
#: 100 separates them (measured on 14 captures).
ITEM_LIST_RECT = (16, 40, 288, 144)

ITEM_HIGHLIGHT_PIXELS = 100

#: The first five cells of the `ITEMS` bar, its word `READY`, by
#: `bar_signature`.  The rest of that bar changes with the item under the
#: highlight, so only its head names the screen: the same value on 26 `ITEMS`
#: captures of six characters, and never on a sheet, whose bar opens `ITEMS`.
ITEMS_BAR_HEAD = "cdea54ada656e489"

ITEMS_BAR_HEAD_CELLS = 5

#: Pool of Radiance's whole `ITEMS` bar, `READY USE TRADE DROP HALVE JOIN
#: EXIT`, by `bar_signature`: the same value on 5 lists of 3 members, whichever
#: item the highlight was on.  Its head is not `ITEMS_BAR_HEAD`.
POOL_ITEMS_BAR = "0a653b8b1d7793d7"

#: The `ITEMS` bar's words in the order the game draws them.  The game leaves
#: words out by member and item, so a list shows `READY`, then some of the rest
#: in this order, then `EXIT`.
POOL_ITEMS_WORDS = ("READY", "USE", "TRADE", "DROP", "HALVE", "JOIN", "EXIT")

#: One bar cell's `Screen.glyphs` digest to its letter, read from DOSBox
#: captures.  A glyph not in the table refuses the whole bar, on purpose: an
#: unknown screen fails closed rather than being read as some other word.
BAR_LETTERS = {
    "9438e360f578e12c": " ", "61d526bdf060e4d9": "A", "d2010e88777efb2d": "D",
    "3c4e0a6ef6df68d8": "E", "6c3f96b5a5c86a50": "H", "6963fe05b95f59e2": "I",
    "b99bc1cff9722066": "J", "2c37990702770f67": "L", "6fb6dfe89e0e1771": "N",
    "0ebdd6919269dab4": "O", "4d53ed56ade1ed6e": "P", "e0cd04fc8849b16a": "R",
    "8a64d5cbd1632147": "S", "974a3a83590c13c9": "T", "88e88c986ceefa26": "U",
    "e683c5b140b929c2": "V", "0ad63b5b828025a6": "X", "afbc7d76cbef0794": "Y",
}

#: Text column 17, where the status line's text starts; the cell at x 128 is
#: the viewport's frame.
STATUS_TEXT_X = 136

#: Where each title's status line starts its `x,y` token, by title key.  Pool
#: of Radiance, Silver Blades and Pools of Darkness share 136 (104 captures).
#: Curse of the Azure Bonds is 136 too, CONFIRMED on its own 12 captures over 2
#: boots and 4 squares (`3,12`, `2,12`, `5,13`, `6,13`); every one is a
#: four-character token, so a three- or five-character Curse token is
#: unmeasured (`status_square` stops at the first blank cell either way).
STATUS_COLUMNS = {"pool": STATUS_TEXT_X, "curse": STATUS_TEXT_X,
                  "ssb": STATUS_TEXT_X, "darkness": STATUS_TEXT_X}

#: Where the roster's first name is drawn: text column 1 at the party menu
#: and its prompts, 17 in camp, from text row 4, one row per member
#: (0x34825).  The current character's name is drawn in colour 15, white,
#: and every other name in 11, 12, 13 or 14 by its status (0x35AC0), so the
#: one near-white line is the highlight.  Measured on #650's captures: 5 party
#: menus and 7 camp screens, each read with the highlight on line 1.
POD_ROSTER = {"party": (8, 32), "camp": (136, 32)}

#: Where the sheet draws the character's name: text column 1, row 1.  On 5
#: sheets of two parties (#650 runs `88eac43064-run1-cleric` and
#: `840311866e-run0-control`) its signature equals roster line 1's and no
#: other line's.
POD_SHEET_NAME = (8, 8)

#: A name's cells: 15 characters, 7 pixel rows of ink in each.
POD_NAME_CELLS = 15

POD_NAME_ROWS = 7

#: The signature of fifteen empty cells: a roster line with nobody on it.
BLANK_NAME = hashlib.sha1(
    dosbox.Screen(CELL, POD_NAME_ROWS, bytes(CELL * POD_NAME_ROWS * 3)).glyphs().encode()
    * POD_NAME_CELLS).hexdigest()[:16]


def name_signature(screen: dosbox.Screen, x: int, y: int) -> str:
    """The name drawn at `(x, y)`, one character cell at a time.

    Each cell is `Screen.glyphs` against its own paper, as `bar_signature`
    reads the bar, so the white of the current character and the cyan of
    the others give the same bits for the same letters.
    """
    sha = hashlib.sha1()
    for i in range(POD_NAME_CELLS):
        sha.update(screen.glyphs((x + CELL * i, y, CELL, POD_NAME_ROWS)).encode())
    return sha.hexdigest()[:16]


def status_square(screen: dosbox.Screen, column: int = STATUS_TEXT_X) -> str | None:
    """The `x,y` token that opens the status line, or None while it is blank.

    Read cell by cell from `column` (`status_column` gives a title's) up to
    the first blank cell, so the facing letter and the clock after it never
    enter the value.
    """
    x0, y, w, h = dosbox.STATUS
    sha = hashlib.sha1()
    cells = 0
    for x in range(column, x0 + w, CELL):
        cell = (x, y, CELL, h)
        if screen.flat(cell):
            break
        sha.update(screen.glyphs(cell).encode())
        cells += 1
    return sha.hexdigest()[:16] if cells else None


def roster_name(screen: dosbox.Screen, where: str, line: int) -> str:
    """Roster line `line`'s name (from 1), at the party menu or in camp."""
    x, y = POD_ROSTER[where]
    return name_signature(screen, x, y + CELL * (line - 1))


def roster_line(screen: dosbox.Screen, where: str, size: int) -> int | None:
    """The roster line drawn highlighted, from 1, or None if none is."""
    x, y = POD_ROSTER[where]
    row = screen.highlight_row((x, y, CELL * POD_NAME_CELLS, CELL * size))
    return None if row is None else row + 1


def sheet_name(screen: dosbox.Screen) -> str:
    """The name on a character sheet, comparable with `roster_name`."""
    return name_signature(screen, *POD_SHEET_NAME)


def bar_signature(screen: dosbox.Screen, cells: int | None = None) -> str:
    """The command bar's words, blind to which word is highlighted.

    `Screen.glyphs` over the whole bar changes when the game moves its
    highlight block from one word to another, because the block's paper
    differs from the bar's.  Taken **one character cell at a time**, each
    cell measures its own paper, so a letter knocked out of the block and
    the same letter lit on black give the same bits.
    """
    x0, y, w, h = dosbox.BAR
    sha = hashlib.sha1()
    for x in range(x0, x0 + (w if cells is None else cells * CELL), CELL):
        sha.update(screen.glyphs((x, y, CELL, h)).encode())
    return sha.hexdigest()[:16]


def bar_words(screen: dosbox.Screen) -> list[str] | None:
    """The command bar's words, or None when a cell is not a letter of
    `BAR_LETTERS`.  Read cell by cell like `bar_signature`, so the highlighted
    word reads the same as the others."""
    x0, y, w, h = dosbox.BAR
    text = []
    for x in range(x0, x0 + w, CELL):
        letter = BAR_LETTERS.get(screen.glyphs((x, y, CELL, h)))
        if letter is None:
            return None
        text.append(letter)
    return "".join(text).split()


def is_pool_items_bar(screen: dosbox.Screen) -> bool:
    """Whether the bar is Pool's `ITEMS` bar in any of its forms: `READY`, an
    in-order subset of the middle words, `EXIT`."""
    words = bar_words(screen)
    if not words or words[0] != POOL_ITEMS_WORDS[0] or words[-1] != POOL_ITEMS_WORDS[-1]:
        return False
    rest = iter(POOL_ITEMS_WORDS)
    return all(word in rest for word in words)


def on_items_list(screen: dosbox.Screen) -> bool:
    """Whether `screen` is a DOS `ITEMS` list: Pools of Darkness' by its bar
    head, and the `READY ... EXIT` bar (whole, or by its words) that Pool of
    Radiance, Silver Blades and Curse of the Azure Bonds draw.  A sheet reads as a one-row list with its highlight on band 12,
    so the readers below ask this first."""
    return (bar_signature(screen, ITEMS_BAR_HEAD_CELLS) == ITEMS_BAR_HEAD
            or bar_signature(screen) == POOL_ITEMS_BAR
            or is_pool_items_bar(screen))


def item_rows(screen: dosbox.Screen) -> int | None:
    """How many rows the `ITEMS` list draws, or None off an `ITEMS` list: the
    8-pixel bands of the readied column, from the top, that hold ink, up to
    the first empty one."""
    if not on_items_list(screen):
        return None
    x, y, w, h = ITEM_READIED_COLUMN
    rows = 0
    while rows < h // CELL:
        band = screen.rows((x, y + rows * CELL, w, CELL))
        if not any(band[i] + band[i + 1] + band[i + 2] > ITEM_INK
                   for i in range(0, len(band), 3)):
            break
        rows += 1
    return rows


def item_highlight(screen: dosbox.Screen) -> int | None:
    """The `ITEMS` row (from 0) drawn highlighted, or None off an `ITEMS` list
    or with no row highlighted."""
    if not on_items_list(screen):
        return None
    return screen.highlight_row(ITEM_LIST_RECT, minimum=ITEM_HIGHLIGHT_PIXELS)
