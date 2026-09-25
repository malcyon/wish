"""Turning a DOS save into a C64 one -- `editor/convert.py`'s own helper.

`goldbox/dos_codec.py` does the conversion and this is the library over it.
The one thing this file exists for is the order of events: the conversion is
**rehearsed** in memory first, and only then is there anything to write --
never a write the player cannot see coming.

**This was a window in its own right, `File ▸ Import ▸ DOS Save Folder…`,
from 2026-08-24 until 2026-09-14, when Donald authorised lifting
`WISH_EXPERIMENTAL_CONVERT` and removing that menu entry in the same commit**
(`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)`): `editor/convert.py`'s `ConvertDialog` was the only route once
the flag came off, and two menu items reaching the same conversion was
always the state the flag's own removal was meant to end, condition 7. The
module **keeps its name**: `editor/convert.py` imports `GameFiles`,
`rehearse`, `pane_text`, `log_unshown_losses`, `NO_DISKS`,
`NO_DISKS_TITLE` and `DROPPED_HEADING` from it at module load, and so do
several tools and test files, so renaming the file to match what it now is
would touch every one of them for no behaviour change. What is gone is only
`class DosImportDialog` and the strings only it used.

`DosImportDialog` carried no pane in its last form either: Donald approved
removing it directly, on 2026-09-14, the way `editor/convert.py`'s dialog
lost its own on 2026-09-10. It drew `pane_text` -- `C64SaveReport.messages`,
then every `C64SaveReport.losses` line, unfiltered -- from 2026-09-06 until
then. What it showed instead, in its last form, was one modal and nothing
else, ported from `editor/convert.py`'s own `_maybe_warn`: one of the
refusals below. `C64SaveReport.messages` and every `C64SaveReport.losses`
line, name truncation included, went to the debug log instead
(`log_unshown_losses`) -- a loss does not become acceptable by being shown
to a player rather than fixed, and the name-truncation consent modal this
paragraph once described (`name_warnings`) is retired for the same reason
(#619, `docs/227-editor-open-save-as.md`). Two of those losses are Donald's
own examples of why: a magic-user memorising more spells than the
destination title's own slots and a spell id outside the destination's own
book are both **bugs** (#508, #509), not platform limits, and a modal
reporting a bug instead of it getting fixed is the pattern that dialog was
kept narrow to stop, the same ruling `editor/convert.py`'s own docstring
quotes -- *"the agents find a bug, and instead of fixing it, they want to
write an excuse to the player and then they never fix it... We need it to
be correct."*

**`goldbox.dos_codec.NOT_SET_OUT` and `C64SaveReport.messages` stay,
unshortened, in `goldbox/dos_codec.py`.** Removing this dialog does not make
either dead: `dos_codec.convert_save`'s own contract -- a never-set-out
Pool of Radiance party is converted to the start of the story and
`report.messages` says so, while a Curse or Silver Blades one is written as
the C64's own pre-adventure save and adds no message -- is pinned directly against real specimens in `tests/convert/test_dosconvert.py` and
`tests/convert/test_curseconvert.py`, independent of any window, and `report.summary()`
still puts the sentence in front of whoever runs a driven tool with
`--report`. Only the display of it is gone, the way `editor/convert.py`'s
pane stopped drawing it on 2026-09-10 while the constant and the field it
fills stayed exactly where they were.

**`report.warnings` is not shown wholesale, and never has been** -- most of
it is this project's own bookkeeping (a quest-flag byte count, a party's
roster slots left empty), which fires on every conversion and is not a fact
about anything the player owns.  `losses` is the hand-picked subset
`write_c64_save` already knows is the player's own loss; see its docstring
in `goldbox/dos_codec.py` for which lines those are. Every one of them goes
to the debug log (`log_unshown_losses` below) and none is shown to a player
(#619).

**There is no template any more** (#118). The dialog used to make the user
pick an existing `.d64` to convert *onto*, and every byte the conversion did
not explicitly set kept the value it had in somebody else's saved game -- a
different party, in a different place, at a different time. `goldbox.dos_codec`
now writes all 9216 bytes of both payloads and `D64.blank()` carries them, so
what the user gets is theirs and nothing else's.

What that costs is the player's own game disks at the moment a conversion
runs: the combat icon is composed out of `SPELLE64`/`SPELLN64` and `$8400`
is `ANIMATE00`, and neither may be stored here. Donald's ruling, 2026-08-27
-- *"We should never attempt to write a save file if we don't have the game
disks and we need them. That would mean making up data, which we will not
do."* -- so `editor/convert.py`'s `ConvertDialog` checks for both and leaves
Convert disabled rather than making up either (`NO_DISKS` above). The third
thing a Pool of Radiance conversion once read off the disks, the creation
menu in `GEN`, is twenty-six integers and is stored
(`goldbox.portraits.POOL_OF_RADIANCE_MENU`, 2026-09-06), so a sheet portrait
needs no disk and nothing here refuses for its lack.

A DOS save is a *directory* of loose files and a C64 save is one `.d64`;
`rehearse` below takes the folder directly, as `ConvertDialog`'s own source
row resolves it.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
from collections.abc import Collection, Mapping
from typing import Any

from goldbox import c64_port, dos_codec
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
#: sat under `Conversion Info` with no heading of its own (2026-09-06); the
#: now-deleted `DosImportDialog`'s own pane never drew it either, both
#: before and after that date.
#: It stays defined because `editor/convert.py` still imports the name at
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
    #: or `None` -- and `None` costs nobody a face: `goldbox.dos_codec.to_neutral`
    #: uses the stored menu for a title that draws one (Pool of Radiance),
    #: and Curse and Silver Blades draw none (#300).  So this is the one
    #: field here without which a conversion still goes ahead.
    portraits: PortraitTables | None = None


@dataclasses.dataclass
class Conversion:
    """A converted save, held in memory. Nothing here has been written."""

    #: A `.d64` built by `goldbox.dos_codec.save_disk` and carrying nothing but the
    #: two files this conversion wrote -- so `disk.to_bytes()` is what a save
    #: would write, and every byte of it is this party's.
    disk: Any
    game: Any
    save0: SaveGame0
    save1: SaveGame1 | None
    report: dos_codec.Report
    folder: pathlib.Path
    slot: str


def rehearse(folder: str | pathlib.Path, slot: str,
             files: GameFiles,
             leave: "Mapping[int, Collection[int]] | None" = None
             ) -> Conversion:
    """Build the save and the disk in memory and report, writing nothing.

    The DOS files are read, the game files in `files` were read before this
    was called, and the result exists only as the returned `Conversion`.
    Anything `goldbox.dos_codec.new_save` refuses raises from in here, which is what
    the dialog turns into a sentence.

    **The title comes from the save itself, not from an assumption.** A
    character's own record length names its shape (`goldbox.dos_port.deltas_for`),
    so a Curse or Silver Blades folder converts into its own title rather than
    being written out as a Pool of Radiance save it never was (#192). A
    Curse save has no separate roster file -- its roster lives inside the one
    payload `goldbox/c64_save.py` describes -- so `save1` stays `None` rather
    than an empty `SaveGame1`, which the constructor would refuse anyway.
    """
    party = dos_codec.read_party(folder, slot)
    try:
        game = c64_port.by_key(party[0].deltas.key)
    except c64_port.UnknownGameError:
        # Pools of Darkness is the one title this reads and `goldbox/c64_port.py`
        # does not list, because there is no C64 port to convert it to. Before
        # the title came from the save, that folder ran on into `to_neutral`
        # and got Donald's own sentence for exactly this case (#176). Without
        # this, `UnknownGameError` is not a `DosRecordError`, so the dialog
        # falls through to "This save cannot be converted." and the player is
        # told less than we know.
        raise dos_codec.WrongTitleError(
            f"{party[0].deltas.title} has no C64 port to convert to, so "
            f"goldbox/c64_port.py has no entry for it (#176)",
            party[0].deltas.title) from None
    payload0, payload1, report = dos_codec.new_save(folder, slot,
                                              files.icon, files.animate,
                                              portraits=files.portraits,
                                              game=game, leave=leave)
    sg0 = SaveGame0.from_bytes(bytes(payload0), game)
    sg1 = SaveGame1(bytes(payload1), game) if payload1 else None
    disk = dos_codec.save_disk(bytes(payload0), bytes(payload1), game)
    # Save As reads only `dropped` and `losses` off the report, so this is
    # where a warning such as the experience clamp reaches the debug log.
    if report.warnings:
        _log.info("Conversion warnings: %s", "; ".join(report.warnings))
    return Conversion(disk, game, sg0, sg1, report,
                      pathlib.Path(folder), slot)


def pane_text(report: dos_codec.Report) -> str:
    """The messages, then the losses, joined -- what `DosImportDialog`'s own
    pane drew, unfiltered, from 2026-09-06 until that pane was removed,
    2026-09-14, and what `editor/convert.py`'s pane drew before that pane
    was removed outright, 2026-09-10.

    **No dialog reads the string this returns any more.** `editor/convert.py`
    still calls this on every rehearsal, for `report.dropped`'s own logging
    below -- the only way `report.dropped` reaches the debug log there
    without duplicating this function's own logic -- and discards the
    return value; `DosImportDialog` no longer calls it at all, since its own
    `_attempt` logs `report.dropped` itself. What is left reading the return
    value is `tests/convert/test_dosimport.py`, pinning the join-and-blank-line logic
    on its own.
    """
    if report.dropped:
        _log.info("Not converted: %s", "; ".join(report.dropped))
    halves = [list(getattr(report, "messages", ())),
              list(getattr(report, "losses", ()))]
    return "\n\n".join("\n".join(half) for half in halves if half)


def log_unshown_losses(report: dos_codec.Report) -> None:
    """Every `report.losses` line, to the debug log and nowhere a player
    reads.

    Until 2026-09-22 (#619) one kind of loss -- a name too long for DOS's
    own field -- was filtered out of here and shown in a modal instead,
    matched by the substring `"is longer than the DOS "`
    (`NAME_TRUNCATED_MARKER`). That consent path is retired
    (`docs/227-editor-open-save-as.md`: "a loss does not become acceptable
    by being classified outside the drop list"), so every loss line, name
    truncation included, is evidence for the bug that produced it rather
    than a fact a player is asked to accept.
    """
    losses = list(report.losses)
    if losses:
        _log.info("Not shown to the player: %s", "; ".join(losses))
