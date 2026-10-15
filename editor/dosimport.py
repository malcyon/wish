"""Turning a DOS save into a C64 one -- `editor/convert.py`'s own helper.

`goldbox/dos_codec.py` does the conversion and this is the library over it.
The one thing this file exists for is the order of events: the conversion is
**rehearsed** in memory first, and only then is there anything to write --
never a write the player cannot see coming. `editor/convert.py` imports
`GameFiles`, `rehearse`, `pane_text`, `log_unshown_losses`, `NO_DISKS` and
`NO_DISKS_TITLE` from here, as do several tools and test files.

No window shows the report. `C64SaveReport.messages` and every
`C64SaveReport.losses` line, name truncation included, go to the debug log
(`log_unshown_losses`): a loss does not become acceptable by being shown to a
player rather than fixed, and a modal reporting a bug in place of a fix is the
pattern this module is kept narrow to prevent.

`goldbox.dos_codec.NOT_SET_OUT` and `C64SaveReport.messages` stay in
`goldbox/dos_codec.py`: `dos_codec.convert_save` converts a never-set-out Pool
of Radiance party to the start of the story and records that in `report.messages`,
while a Curse or Silver Blades one is written as the C64's own pre-adventure
save and adds no message. `tests/convert/test_dosconvert.py` and
`tests/convert/test_curseconvert.py` pin that against real specimens, and
`report.summary()` puts the sentence in front of whoever runs a driven tool
with `--report`.

`report.warnings` is not shown wholesale -- most of it is bookkeeping (a
quest-flag byte count, a party's roster slots left empty) that fires on every
conversion and says nothing about what the player owns. `losses` is the
hand-picked subset `write_c64_save` knows is the player's own loss; see its
docstring in `goldbox/dos_codec.py`.

There is no template. `goldbox.dos_codec` writes all 9216 bytes of both
payloads and `D64.blank()` carries them, so the result holds nothing from
anybody else's saved game.

That needs the player's own game disks when a conversion runs: the combat icon
is composed out of `SPELLE64`/`SPELLN64` and `$8400` is `ANIMATE00`, and
neither may be stored here, so Save As checks for both and does not convert
rather than make either up (`NO_DISKS` above). The creation menu in `GEN` is
twenty-six integers and is stored (`goldbox.portraits.POOL_OF_RADIANCE_MENU`),
so a sheet portrait needs no disk.

A DOS save is a *directory* of loose files and a C64 save is one `.d64`;
`rehearse` below takes the folder directly, as Save As resolves it.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
from collections.abc import Collection, Mapping
from typing import Any

from goldbox import c64_port, dos_codec, titles
from goldbox.companions import JOINABLE, Companions
from goldbox.d64 import D64, D64Error
from goldbox.iconparts import IconParts
from goldbox.portraits import PortraitTables
from goldbox.savegame import SaveGame0, SaveGame1

from . import saveplan

#: A child of the `wish` logger, so `wish/debuglog.py`'s handler takes these
#: whenever `WISH_DEBUG` is on -- the same pattern `editor/convert.py` and
#: `editor/window.py` already use, rather than importing `wish.debuglog`
#: directly.
_log = logging.getLogger("wish.editor.dosimport")
# Every string below is Donald's -- approved 2026-08-24, and the rejection
# 2026-08-27. Changing one is his call, not a refactor.

#: The rejection when the player's game disks cannot be found, which is the one
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

    Held together because the rejection is one question -- can this import read
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
    #: `ITEMS` read off the player's own disk (side 1 for Pool of Radiance),
    #: `None` for Silver Blades or when no disk answers.  Without it a Pool
    #: of Radiance character's movement is copied, not computed, and a Pool or
    #: Curse character's THAC0 ignores his readied weapon.
    item_types: dict | None = None
    #: The title's companion table, read off its game sides, or `None` for a
    #: title that has none and when a side cannot be read.  Without it a
    #: companion keeps the picture he arrived with and gets no story byte,
    #: and one who joined on the C64 arrives with no picture.
    companions: Companions | None = None


def load_companions(key: str, candidates: Collection[str | pathlib.Path]
                    ) -> Companions | None:
    """The companion table for title `key` read off the disk images in
    `candidates`, or `None` when the title has none or they cannot give it.

    A candidate that is not a readable disk image is left out, because a
    folder's glob can match a save disk or a damaged copy beside the game
    sides; the table needs every `MON` file, so a title whose sides are
    incomplete or damaged gets `None` too, and the other game files are
    unaffected.
    """
    if key not in JOINABLE:
        return None
    sides = []
    for candidate in candidates:
        try:
            sides.append(D64.open(str(candidate)))
        except Exception as exc:
            _log.debug("%s is not a readable disk image: %s", candidate, exc)
    try:
        return Companions.load(key, sides)
    except (ValueError, D64Error, OSError) as exc:
        _log.debug("no companion table for %s: %s", key, exc)
        return None


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
             leave: "Mapping[int, Collection[int]] | None" = None,
             names: "Mapping[int, str] | None" = None,
             leave_effects: "Mapping[int, Collection[int]] | None" = None
             ) -> Conversion:
    """Build the save and the disk in memory and report, writing nothing.

    The DOS files are read, the game files in `files` were read before this
    was called, and the result exists only as the returned `Conversion`.
    Anything `goldbox.dos_codec.new_save` blocks raises from in here, which is what
    the dialog turns into a sentence.

    **The title comes from the save itself, not from an assumption.** A
    character's own record length names its deltas (`goldbox.dos_port.deltas_for`),
    so a Curse or Silver Blades folder converts into its own title rather than
    being written out as a Pool of Radiance save it never was (#192). A
    Curse save has no separate roster file -- its roster lives inside the one
    payload `goldbox/c64_save.py` describes -- so `save1` stays `None` rather
    than an empty `SaveGame1`, which the constructor would block anyway.
    """
    party = dos_codec.read_party(folder, slot)
    try:
        game = c64_port.by_key(party[0].deltas.key)
    except titles.UnknownTitleError:
        # Pools of Darkness is the one title this reads and `goldbox/c64_port.py`
        # does not list, because there is no C64 port to convert it to. Before
        # the title came from the save, that folder ran on into `to_neutral`
        # and got Donald's own sentence for exactly this case (#176). Without
        # this, `UnknownTitleError` is not a `DosRecordError`, so the dialog
        # falls through to "This save cannot be converted." and the player is
        # told less than we know.
        raise dos_codec.WrongTitleError(
            f"{party[0].deltas.title} has no C64 port to convert to, so "
            f"goldbox/c64_port.py has no entry for it (#176)",
            party[0].deltas.title) from None
    # The records are `DosCharacter`s, not a neutral party, so the names are
    # checked here and the player's choices go on to the writer.
    chosen = saveplan.check_names([c.name for c in party], "c64", game.key,
                                  names)
    payload0, payload1, report = dos_codec.new_save(folder, slot,
                                              files.icon, files.animate,
                                              portraits=files.portraits,
                                              game=game, leave=leave,
                                              item_types=files.item_types,
                                              names=chosen,
                                              leave_effects=leave_effects,
                                              companions=files.companions)
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
