"""Reads a captured C64 screen: the item list a character's inventory shows and a name as the character set draws it."""

from __future__ import annotations

#: The item screen's own columns, from a Pool of Radiance capture kept in
#: `cited/252/probe4/screen.txt` and unchanged in Curse: a `YES`/`NO`
#: readied column at 1, then an optional count, then the name.
ITEM_ROWS = range(4, 23)
ITEM_COLUMN = 1
#: Column 39 is the window's own right-hand border.
ITEM_BORDER = 39


def item_list(rows: list[str]) -> list[str]:
    """The item screen's own rows, frame and blanks dropped.

    Column 39 is the window's right-hand border and is a graphic character
    that changes down the frame, so a row read to the end of the line is
    never blank and every empty slot on the list would come back as an item.
    """
    out = []
    for r in rows[ITEM_ROWS.start:ITEM_ROWS.stop]:
        text = r[ITEM_COLUMN:ITEM_BORDER].rstrip()
        if not text.strip():
            continue
        if text.strip() == "EXIT":
            break
        out.append(text.strip())
    return out


def as_drawn(name: str) -> str:
    """What the C64 draws for a name that has lower case in it.

    **This character set has no lower case**, and a lower-case letter is
    drawn as the glyph at its code minus `$40`: `Guy de Valois` comes out of
    the party panel as `G59 $% V!,/)3`, measured on
    `WISH-SPEC-ssb-d-engine-resave` in `issue139-a13/ssb-run1` (scratch, deleted).  A save
    converted from DOS keeps DOS's mixed-case name, so a run that looks for
    the name it read out of the record finds nobody at all.

    The rest of that block goes the same way: a backquote is drawn blank,
    `{ | } ~` as `; < = >`, and a backslash as `\u00a3`.
    """
    return "".join("\u00a3" if c == "\\"
                   else chr(ord(c) - 0x40) if "`" <= c <= "~" else c
                   for c in name)
