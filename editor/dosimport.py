"""Turning a DOS save into a C64 one, with what happened on screen first.

`goldbox/dos.py` does the conversion; this file is the library a window sits
over rather than a window of its own -- `File ▸ Import ▸ DOS Save Folder…`
was that window until `#52 (File ▸ Import and File ▸ Export for every
direction the library supports)`'s step 5 removed it, and `editor/convert.py`'s
`File ▸ Convert…` is the only one left, reaching `rehearse`, `pane_text`,
`GameFiles`, `NO_DISKS`/`NO_DISKS_TITLE` and `DROPPED_HEADING` here. The one
thing that shape gives every caller is the order of events: the conversion is
**rehearsed** in memory, what it did to the player's own save is put on
screen -- `C64SaveReport.messages`, a party that had not set out being
started at the beginning of the story -- and only then is there a button to
press. `editor/convert.py`'s own destination row follows the same rule the
old window did -- Donald's shape, 2026-08-27: *"when the user clicks the
Convert button, it does what the user expects. it converts."* The write
itself is still the editor's own Save, so the backup guarantee in
`editor/files.py` covers this the way it covers every other write.

**`editor/convert.py` carries no pane at all as of 2026-09-10** -- Donald,
seeing the two that had stood in for it in turn: *"the box under it has to
be removed, too. That was the entire point."* What a player is shown now is
two modals and nothing else: one of the refusals below, or a name DOS's own
fifteen-character field could not hold whole (`name_warnings`). Everything
else that used to reach the pane -- `C64SaveReport.messages` entirely, and
`C64SaveReport.losses` beyond the one name-length kind -- goes to the debug
log instead (`log_unshown_losses`, `pane_text`'s own `report.dropped`
logging), never a player. Two of those losses are Donald's own examples of
why: a magic-user memorising more spells than the destination title's slots
and a spell id outside the destination's own book are both **bugs** (#508,
#509), not platform limits, and a modal reporting a bug instead of it
getting fixed is the pattern this file is being kept narrow to stop --
*"the agents find a bug, and instead of fixing it, they want to write an
excuse to the player and then they never fix it... We need it to be
correct."*

**`report.warnings` is not shown wholesale, and never has been** -- most of
it is this project's own bookkeeping (a quest-flag byte count, a party's
roster slots left empty), which fires on every conversion and is not a fact
about anything the player owns.  `losses` is the hand-picked subset
`write_c64_save` already knows is the player's own loss; see its docstring
in `goldbox/dos.py` for which lines those are -- and `name_warnings` below
for the one kind of those Donald ruled real.

**There is no template any more** (#118). The old window used to make the
user pick an existing `.d64` to convert *onto*, and every byte the
conversion did not explicitly set kept the value it had in somebody else's
saved game -- a different party, in a different place, at a different time.
`goldbox.dos` now writes all 9216 bytes of both payloads and `D64.blank()`
carries them, so what the user gets is theirs and nothing else's.

What that costs is the player's own game disks at the moment the conversion
runs: the combat icon is composed out of `SPELLE64`/`SPELLN64` and `$8400`
is `ANIMATE00`, and neither may be stored here. Donald's ruling, 2026-08-27
-- *"We should never attempt to write a save file if we don't have the game
disks and we need them. That would mean making up data, which we will not
do."* -- so whichever window calls `rehearse` checks for both before
offering the player a folder or file to pick and refuses with a pop-up if
either is missing.  The third thing a Pool of Radiance conversion once read
off the disks, the creation menu in `GEN`, is twenty-six integers and is
stored (`goldbox.portraits.POOL_OF_RADIANCE_MENU`, 2026-09-06), so a sheet
portrait needs no disk and nothing here refuses for its lack.

A DOS save is a *directory* of loose files and a C64 save is one `.d64`, so
the two are never told apart by sniffing: whichever picker starts a DOS
conversion asks for a folder, never a file.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
from typing import Any

from goldbox import dos, games
from goldbox.iconparts import IconParts
from goldbox.portraits import PortraitTables
from goldbox.savegame import SaveGame0, SaveGame1

#: A child of the `wish` logger, so `wish/debuglog.py`'s handler takes these
#: whenever `WISH_DEBUG` is on -- the same pattern `editor/convert.py` and
#: `editor/window.py` already use, rather than importing `wish.debuglog`
#: directly.
_log = logging.getLogger("wish.editor.dosimport")

# Every string below is Donald's -- approved 2026-08-24, and the refusal
# 2026-08-27. Changing one is his call, not a refactor.

#: The heading over a list of what a converted character loses, Donald's
#: wording of 2026-09-05 (`09027bb`).  **Nothing draws it any more**: the
#: pane stopped carrying the drop list at all on 2026-09-08, when the
#: accounting moved to the debug log (`pane_text` below), and before that it
#: sat under `Conversion Info` with no heading of its own (2026-09-06). It
#: stays defined because `editor/convert.py` still imports the name at
#: module load (`DROPPED_HEADING = dosimport.DROPPED_HEADING`); deleting it
#: here would break that import.
DROPPED_HEADING = "Wish cannot currently convert these fields:"

#: The refusal when the player's game disks cannot be found, which is the one
#: thing the conversion cannot do without: the combat icon comes out of
#: `SPELLE64` and `$8400` out of `ANIMATE00`, and neither may be stored here.
#: Donald's wording. The title is his of 2026-08-27; the line was replaced by
#: him on 2026-09-05, because the first version had gone stale in three ways
#: at once -- it named `File ▸ Import`, which `#52 (File ▸ Import and
#: File ▸ Export for every direction the library supports)` replaces with
#: `File ▸ Convert…`; it said "a character" where a conversion moves a
#: whole party; and it said "the Game Disk folder" as though there were one,
#: when `#22 (A disk folder setting per game, not one shared by all six)`
#: gives each title its own and `#342 (A Curse or Silver Blades save cannot
#: be converted unless its C64 sides sit in the Pool of Radiance disk
#: folder)` taught the conversion to read them. A player who had set Curse's
#: folder was being told to do the thing they had already done.
#:
#: A title and one line and no more. It fires **before** the folder picker,
#: so nothing has been chosen and no dialog is left standing behind the
#: error.
NO_DISKS_TITLE = "Game disks not found"
NO_DISKS = ('Please set your "Game disks" folders in Preferences before '
            "converting a save.")

#: The status line when a conversion reaches the window with no file behind
#: it. Convert names one and writes it, so what a user sees after an import is
#: `editor/files.py`'s own line about the file it wrote; this is what is left
#: for a caller that adopts a conversion without a path.
CONVERTED = "converted DOS slot {slot} - not saved yet"
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class GameFiles:
    """The two things off the player's game disks a conversion cannot do
    without.

    Held together because the refusal is one question -- can this import read
    the player's disks? -- and answering it twice in two places is how the two
    halves drift apart.

    **Which disk each came from is not kept.** It was, and nothing ever read
    it: the one place the disks have to be named is the log line
    `editor/window.py` writes when the second read fails, and that runs where
    there is no `GameFiles` to have named them.
    """

    #: `SPELLE64`/`SPELLN64`, read into an `IconParts` (#130): each converted
    #: character gets the combat figure his own DOS record names, through
    #: `IconParts.dos_icon`.
    icon: bytes | IconParts
    #: `ANIMATE00`'s 852-byte payload, which goes at `$8400`.
    animate: bytes
    #: The creation menu's two tables (#57) read off the player's own disks,
    #: or `None` -- and `None` costs nobody a face: `goldbox.dos.to_neutral`
    #: uses the stored menu for a title that draws one (Pool of Radiance),
    #: and Curse and Silver Blades draw none (#300).  So this is the one
    #: field here without which a conversion still goes ahead.
    portraits: PortraitTables | None = None


@dataclasses.dataclass
class Conversion:
    """A converted save, held in memory. Nothing here has been written."""

    #: A `.d64` built by `goldbox.dos.save_disk` and carrying nothing but the
    #: two files this conversion wrote -- so `disk.to_bytes()` is what a save
    #: would write, and every byte of it is this party's.
    disk: Any
    game: Any
    save0: SaveGame0
    save1: SaveGame1 | None
    report: dos.Report
    folder: pathlib.Path
    slot: str


def rehearse(folder: str | pathlib.Path, slot: str,
             files: GameFiles) -> Conversion:
    """Build the save and the disk in memory and report, writing nothing.

    The DOS files are read, the game files in `files` were read before this
    was called, and the result exists only as the returned `Conversion`.
    Anything `goldbox.dos.new_save` refuses raises from in here, which is what
    the dialog turns into a sentence.

    **The title comes from the save itself, not from an assumption.** A
    character's own record length names its shape (`goldbox.dos.shape_for`),
    so a Curse or Silver Blades folder converts into its own title rather than
    being written out as a Pool of Radiance save it never was (#192). A
    Curse save has no separate roster file -- its roster lives inside the one
    payload `goldbox/c64_save.py` describes -- so `save1` stays `None` rather
    than an empty `SaveGame1`, which the constructor would refuse anyway.
    """
    party = dos.read_party(folder, slot)
    try:
        game = games.by_key(party[0].shape.key)
    except games.UnknownGameError:
        # Pools of Darkness is the one title this reads and `goldbox/games.py`
        # does not list, because there is no C64 port to convert it to. Before
        # the title came from the save, that folder ran on into `to_neutral`
        # and got Donald's own sentence for exactly this case (#176). Without
        # this, `UnknownGameError` is not a `DosRecordError`, so the dialog
        # falls through to "This save cannot be converted." and the player is
        # told less than we know.
        raise dos.WrongTitleError(
            f"{party[0].shape.title} has no C64 port to convert to, so "
            f"goldbox/games.py has no entry for it (#176)",
            party[0].shape.title) from None
    payload0, payload1, report = dos.new_save(folder, slot,
                                              files.icon, files.animate,
                                              portraits=files.portraits,
                                              game=game)
    sg0 = SaveGame0.from_bytes(bytes(payload0), game)
    sg1 = SaveGame1(bytes(payload1), game) if payload1 else None
    disk = dos.save_disk(bytes(payload0), bytes(payload1), game)
    return Conversion(disk, game, sg0, sg1, report,
                      pathlib.Path(folder), slot)


def pane_text(report: dos.Report) -> str:
    """The messages, then the losses, joined the way `editor/convert.py`'s
    pane used to draw them -- until 2026-09-10, when that pane was removed
    outright and nothing calls this for its returned text any more.

    **Still called, for `report.dropped`'s own logging below.** Every
    field the conversion did not convert, in the words
    `goldbox.dos.DROPPED_PLAYER_TEXT` gives each, is the accounting a route
    is judged perfect or not by, and it stays that: a test reads it and
    every driven tool still prints it with `--report`. A player has never
    been shown it; `_log` carries it to `WISH_DEBUG`'s file instead, so a
    bug report can still say what a conversion left behind.

    `C64SaveReport.messages` and `C64SaveReport.losses` beyond a truncated
    name are no longer shown to a player at all, `editor/convert.py`'s own
    `_rehearse_and_report` and `dosimport.log_unshown_losses` -- Donald,
    2026-09-10, of two `losses` lines a player had been shown: *"the agents
    find a bug, and instead of fixing it, they want to write an excuse to
    the player and then they never fix it... We need it to be correct."*
    This function's own joining of the two lists into one string is dead
    weight now rather than a defect -- nobody reads what it returns -- and
    is left in place the way `dropped_text` below is.
    """
    if report.dropped:
        _log.info("Not converted: %s", "; ".join(report.dropped))
    halves = [list(getattr(report, "messages", ())),
              list(getattr(report, "losses", ()))]
    return "\n\n".join("\n".join(half) for half in halves if half)


#: The one substring of a `C64SaveReport.losses` line Donald ruled real,
#: 2026-09-10: a name DOS's own fifteen-character field could not hold in
#: full. `goldbox.dos.write`'s own words, kept verbatim rather than
#: reworded here -- *"do not 'improve' either of the two warning
#: strings"* governs this one too, even though it is the one that is shown.
NAME_TRUNCATED_MARKER = "is longer than the DOS "


def name_warnings(report: dos.Report) -> list[str]:
    """`report.losses` filtered to the one kind of loss Donald ruled a
    player is entitled to see: a name too long for DOS's own field.

    Everything else on that list -- a magic-user memorising more spells
    than the destination title's own slots, a spell id outside the
    destination's own book -- is a bug (#508, #509) rather than a platform
    limit, so it is not returned here; `log_unshown_losses` below is where
    it goes instead. Matched by substring because `goldbox.dos.write`
    appends all three kinds to the one list, `rep.warnings`, with no marker
    of which is which beyond the sentence itself, and that sentence is not
    this function's to reword (`.claude/rules/conversions.md`, 2026-09-10:
    "do not... delete the code that raises them... only their destination
    changes").
    """
    return [line for line in getattr(report, "losses", ())
           if NAME_TRUNCATED_MARKER in line]


def log_unshown_losses(report: dos.Report) -> None:
    """Every `report.losses` line `name_warnings` does not return, to the
    debug log instead of a player -- evidence for #508 and #509 without
    putting an excuse in front of somebody. Donald, 2026-09-10, on being
    shown two such lines: *"Things like this are WHY we have to remove the
    Convert dialog... It's not okay. We need it to be correct."*
    """
    unshown = [line for line in getattr(report, "losses", ())
              if NAME_TRUNCATED_MARKER not in line]
    if unshown:
        _log.info("Not shown to the player (#508, #509): %s",
                  "; ".join(unshown))


def dropped_text(report: dos.Report) -> str:
    """The losses, one to a line, under a heading -- or nothing at all.

    **Nobody calls this today.** `File ▸ Import ▸ DOS Save Folder…`, which
    this file used to build, drew `pane_text` rather than this, and
    `editor/convert.py`'s pane stopped calling it too once `#416 (The live
    Convert dialog never shows a DOS→C64 conversion's own messages or
    capacity-ceiling warnings)` moved onto `pane_text`. Left in place --
    deleting it was not `#52 (File ▸ Import and File ▸ Export for every
    direction the library supports)`'s step 5's to do, and is recorded there
    as a separate finding.

    Empty when nothing was dropped (#338): the heading says something was
    lost, and a heading over no lines told a player that with nothing to
    back it up. A caller that puts more text after this one must not glue a
    blank line onto an empty string either.
    """
    if not report.dropped:
        return ""
    return "\n".join([DROPPED_HEADING, ""]
                     + [f"  {d}" for d in report.dropped])
