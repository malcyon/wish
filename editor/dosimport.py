"""Turning a DOS save into a C64 one, with what happened on screen first.

`goldbox/dos_codec.py` does the conversion and this is the window over it. The one
thing this file exists for is the order of events: the conversion is
**rehearsed** in memory first, and only then is there a button to press --
never a write the player cannot see coming. The file the write goes to is
named in this window, on the bottom row, before Convert is pressed --
Donald's own wording, 2026-08-27: *"when the user clicks the Convert button,
it does what the user expects. it converts."* The write itself is still the
editor's own Save, so the backup guarantee in `editor/files.py` covers this
the way it covers every other write.

`DosImportDialog`, below, is `File ▸ Import ▸ DOS save folder…`'s own window,
and it carries no pane either: Donald approved removing it directly, in this
session, on 2026-09-14, the way `editor/convert.py`'s dialog lost its own on
2026-09-10 (`#52 (File ▸ Import and File ▸ Export for every direction the
library supports)`). It drew `pane_text` -- `C64SaveReport.messages`, then every
`C64SaveReport.losses` line, unfiltered -- from 2026-09-06 until then; that
window was removed once before (2026-09-07, `375bf07`) on the belief that
`editor/convert.py`'s dialog already did its job in full. That dialog sits
behind `WISH_EXPERIMENTAL_CONVERT`, so the removal had in fact left a player
running Wish as it ships with no import path at all; Donald put this window
back on 2026-09-10 for that reason, and it stays until the flag is lifted
(`editor/convert.py`'s own condition 7).

**What a player is shown here now is two modals and nothing else**, ported
from `editor/convert.py`'s own `_maybe_warn`: one of the refusals below, or a
name DOS's own fifteen-character field could not hold whole
(`name_warnings`). Everything else that used to reach the pane --
`C64SaveReport.messages` entirely, and `C64SaveReport.losses` beyond the one
name-length kind -- goes to the debug log instead (`log_unshown_losses`, and
this dialog's own `report.dropped` logging in `_attempt`), never a player of
this window. Two of those losses are Donald's own examples of why: a
magic-user memorising more spells than the destination title's own slots and
a spell id outside the destination's own book are both **bugs** (#508, #509),
not platform limits, and a modal reporting a bug instead of it getting fixed
is the pattern this window is now kept narrow to stop, the same ruling
`editor/convert.py`'s own docstring quotes -- *"the agents find a bug, and
instead of fixing it, they want to write an excuse to the player and then
they never fix it... We need it to be correct."*

**`goldbox.dos_codec.NOT_SET_OUT` and `C64SaveReport.messages` stay,
unshortened, in `goldbox/dos_codec.py`.** Removing this window's pane does not
make either dead: `dos_codec.convert_save`'s own contract -- a never-set-out
party is converted to the start of the story and `report.messages` says so --
is pinned directly against real specimens in `tests/test_dosconvert.py` and
`tests/test_curseconvert.py`, independent of any window, and `report.summary()`
still puts the sentence in front of whoever runs a driven tool with
`--report`. Only *this window's own display of it* is gone, the way
`editor/convert.py`'s pane stopped drawing it on 2026-09-10 while the
constant and the field it fills stayed exactly where they were.

**`report.warnings` is not shown wholesale, and never has been** -- most of
it is this project's own bookkeeping (a quest-flag byte count, a party's
roster slots left empty), which fires on every conversion and is not a fact
about anything the player owns.  `losses` is the hand-picked subset
`write_c64_save` already knows is the player's own loss; see its docstring
in `goldbox/dos_codec.py` for which lines those are -- and `name_warnings` below
for the one kind of those Donald ruled real.

**There is no template any more** (#118). The dialog used to make the user
pick an existing `.d64` to convert *onto*, and every byte the conversion did
not explicitly set kept the value it had in somebody else's saved game -- a
different party, in a different place, at a different time. `goldbox.dos_codec`
now writes all 9216 bytes of both payloads and `D64.blank()` carries them, so
what the user gets is theirs and nothing else's.

What that costs is the player's own game disks at the moment the import
runs: the combat icon is composed out of `SPELLE64`/`SPELLN64` and `$8400`
is `ANIMATE00`, and neither may be stored here. Donald's ruling, 2026-08-27
-- *"We should never attempt to write a save file if we don't have the game
disks and we need them. That would mean making up data, which we will not
do."* -- so `editor/window.py` checks for both before the folder picker
opens and refuses with a pop-up.  The third thing a Pool of Radiance
conversion once read off the disks, the creation menu in `GEN`, is
twenty-six integers and is stored (`goldbox.portraits.POOL_OF_RADIANCE_MENU`,
2026-09-06), so a sheet portrait needs no disk and nothing here refuses for
its lack.

A DOS save is a *directory* of loose files and a C64 save is one `.d64`, so
the two are never told apart by sniffing: the first picker asks for a folder.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
from typing import Any

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QWidget,
)

from goldbox import c64_port, dos_codec
from goldbox.iconparts import IconParts
from goldbox.portraits import PortraitTables
from goldbox.savegame import SaveGame0, SaveGame1

from .ui_dosimport import Ui_DosImportDialog

#: A child of the `wish` logger, so `wish/debuglog.py`'s handler takes these
#: whenever `WISH_DEBUG` is on -- the same pattern `editor/convert.py` and
#: `editor/window.py` already use, rather than importing `wish.debuglog`
#: directly.
_log = logging.getLogger("wish.editor.dosimport")
# Every string below is Donald's -- approved 2026-08-24, and the refusal
# 2026-08-27. Changing one is his call, not a refactor.

#: The File menu entry and the submenu it hangs under.
MENU_IMPORT = "&Import"
#: The entry says **Folder** because the picker behind it asks for one -- a
#: DOS save is a dozen loose files with no single one to point at, and
#: "DOS…" read as a file chooser.  Donald's wording, approved 2026-08-26.
MENU_DOS_SAVE = "&DOS Save Folder…"

#: The folder picker, and what is said when the folder holds no DOS save.
FOLDER_TITLE = "Choose a DOS save folder"
NO_SLOTS_TITLE = "No DOS save here"
NO_SLOTS = "{folder} holds no DOS Pool of Radiance save."

#: The conversion window.
DIALOG_TITLE = "Import a DOS save"
LABEL_FOLDER = "DOS save"
LABEL_SLOT = "Slot"
BUTTON_CONVERT = "Convert"

#: The destination row, from the mock-up Donald picked on #118: a full path,
#: filled in before he touches it, and a button beside it. *"when the user
#: clicks the Convert button, it does what the user expects. it converts."*
#: -- so there is no Save As after this window any more.
LABEL_DESTINATION = "Save as"
BUTTON_BROWSE = "Browse…"

#: What the path is suggested as. The C64 game's own save name with the DOS
#: slot letter in it, so importing slot J offers `PORSAVEJ.D64`. The letter is
#: the slot's, so the box is rebuilt every time the slot changes or it goes on
#: naming a slot nobody is converting -- but never over a path the user typed
#: or browsed to, which is theirs.
DEFAULT_NAME = "PORSAVE{slot}.D64"

#: The heading over a list of what a converted character loses, Donald's
#: wording of 2026-09-05 (`09027bb`).  **Nothing draws it any more**: the
#: pane stopped carrying the drop list at all on 2026-09-08, when the
#: accounting moved to the debug log (`pane_text` below), and before that it
#: sat under `Conversion Info` with no heading of its own (2026-09-06); this
#: window's own pane never drew it either, both before and after that date.
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
             files: GameFiles) -> Conversion:
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
                                              game=game)
    sg0 = SaveGame0.from_bytes(bytes(payload0), game)
    sg1 = SaveGame1(bytes(payload1), game) if payload1 else None
    disk = dos_codec.save_disk(bytes(payload0), bytes(payload1), game)
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
    value is `tests/test_dosimport.py`, pinning the join-and-blank-line logic
    on its own.
    """
    if report.dropped:
        _log.info("Not converted: %s", "; ".join(report.dropped))
    halves = [list(getattr(report, "messages", ())),
              list(getattr(report, "losses", ()))]
    return "\n\n".join("\n".join(half) for half in halves if half)


#: The one substring of a `C64SaveReport.losses` line Donald ruled real,
#: 2026-09-10: a name DOS's own fifteen-character field could not hold in
#: full. `goldbox.dos_codec.write`'s own words, kept verbatim rather than
#: reworded here -- *"do not 'improve' either of the two warning
#: strings"* governs this one too, even though it is the one that is shown.
NAME_TRUNCATED_MARKER = "is longer than the DOS "


def name_warnings(report: dos_codec.Report) -> list[str]:
    """`report.losses` filtered to the one kind of loss Donald ruled a
    player is entitled to see: a name too long for DOS's own field.

    Everything else on that list -- a magic-user memorising more spells
    than the destination title's own slots, a spell id outside the
    destination's own book -- is a bug (#508, #509) rather than a platform
    limit, so it is not returned here; `log_unshown_losses` below is where
    it goes instead. Matched by substring because `goldbox.dos_codec.write`
    appends all three kinds to the one list, `rep.warnings`, with no marker
    of which is which beyond the sentence itself, and that sentence is not
    this function's to reword (`.claude/rules/conversions.md`, 2026-09-10:
    "do not... delete the code that raises them... only their destination
    changes").
    """
    return [line for line in getattr(report, "losses", ())
           if NAME_TRUNCATED_MARKER in line]


def log_unshown_losses(report: dos_codec.Report) -> None:
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


class DosImportDialog(QDialog):
    """The folder, the slot, what the conversion did, and where it goes.

    Every change to the slot re-runs `rehearse`, and Convert is disabled
    unless there is a rehearsal behind it and a path in front of it.

    The bottom row is the destination, and it is why there is no Save As after
    this window any more: the file is named before Convert is pressed, so
    Convert converts.

    `files` is the icon and `ANIMATE00`, already read: `editor/window.py`
    refuses the whole import before this window is built when they cannot be
    found, so by the time anything here runs they exist.

    **Carries no pane, since 2026-09-14.** What a player is told is two
    modals (`_maybe_warn`) -- ported from `editor/convert.py`'s own dialog,
    which lost its pane the same way on 2026-09-10.
    """

    def __init__(self, folder: str | pathlib.Path, files: GameFiles,
                 parent: QWidget | None = None, start_dir: str = ""):
        super().__init__(parent)
        self.ui = Ui_DosImportDialog()
        self.ui.setupUi(self)
        self.folder = pathlib.Path(folder)
        self.files = files
        self.conversion: Conversion | None = None
        #: Where a suggested path is put. `editor/window.py` hands over what
        #: `editor/files.py`'s `open_start_dir` answered -- the saves folder
        #: preference if one is set, otherwise beside the open save, or the
        #: folder one was last opened from -- so an import and a `File > Open`
        #: start in the same place rather than under two rules. That answer is
        #: empty when none of those apply, and a field that has to show a path
        #: cannot be empty, so the home directory is the last resort.
        self.start_dir = start_dir or str(pathlib.Path.home())
        #: The user has typed a path or browsed to one, and the slot must stop
        #: rewriting it.
        self._named = False

        self._folder_label = self.ui.dos_folder
        self._folder_label.setText(str(self.folder))

        self.slots = self.ui.dos_slot
        self.slots.addItems(dos_codec.slots_available(self.folder))
        self.slots.currentTextChanged.connect(lambda _t: self._rehearse())

        self.destination = self.ui.dos_destination
        self.destination.textEdited.connect(self._typed)
        self.destination.textChanged.connect(lambda _t: self._settle_button())

        self.browse_button = self.ui.dos_browse
        self.browse_button.clicked.connect(self.browse)

        self.buttons = self.ui.buttons
        self.buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText(BUTTON_CONVERT)

        #: Set by `_attempt`. `(title, text)` for why Convert cannot go, or
        #: `None` -- `editor/convert.py`'s own `_blocked`, ported rather than
        #: reinvented.
        self._blocked: tuple[str, str] | None = None
        #: A name DOS's own fifteen-character field could not hold whole
        #: (`name_warnings`), or `None` -- the one thing left in
        #: `report.losses` a player is shown.
        self._name_warning: str | None = None
        #: What `_maybe_warn` last actually showed, so rehearsing again
        #: after an unrelated change does not repeat an identical modal the
        #: player has already read. Unset here, so the constructor's own
        #: first `_rehearse()` below shows a real refusal too -- unlike
        #: `editor/convert.py`'s `ConvertDialog`, whose construction-time
        #: `replan()` opens on a blank `From` row and takes an early return
        #: before setting a real `_blocked`, this dialog's first rehearsal
        #: is always against a real slot the player did not choose blank
        #: (`#52 (File ▸ Import and File ▸ Export for every direction the
        #: library supports)`). Gating this call the way `ConvertDialog`
        #: gates its own left a folder with only one slot stuck open with
        #: Convert disabled and no explanation, escapable only with Cancel.
        self._last_blocked_shown: tuple[str, str] | None = None
        self._last_name_warning_shown: str | None = None

        self._rehearse()

    # -- the parts ---------------------------------------------------------

    @property
    def slot(self) -> str:
        return self.slots.currentText()

    def target(self) -> str:
        """The file Convert writes, as the user has left it."""
        return self.destination.text().strip()

    # -- where it goes -----------------------------------------------------

    def _typed(self, _text: str) -> None:
        """Anything the user types in the box is theirs from then on."""
        self._named = True

    def _suggest(self) -> None:
        """Fill the destination in from the slot, over nothing the user chose.

        The name is the slot's -- `PORSAVEJ.D64` for slot J -- so it has to be
        rebuilt whenever the slot changes or it goes on naming a slot that is
        no longer being converted.
        """
        if self._named:
            return
        self.destination.setText(
            str(pathlib.Path(self.start_dir)
                / DEFAULT_NAME.format(slot=self.slot or "")))

    def browse(self) -> None:
        """The editor's own Save As picker, with its own title and filter.

        Imported here rather than worded again: it is the same picker doing
        the same job, and two copies of an approved string is how they drift.
        """
        from PyQt6.QtWidgets import QFileDialog

        from .window import DISK_FILTER, SAVE_AS_TITLE

        path, _ = QFileDialog.getSaveFileName(self, SAVE_AS_TITLE,
                                              self.target(), DISK_FILTER)
        if path:
            self._named = True
            self.destination.setText(path)

    def refuse(self, text: str) -> None:
        """Report a failed write with a modal, since this dialog no longer
        carries a pane to put it in -- `editor/convert.py`'s own `refuse`,
        ported rather than reinvented (2026-09-10 there, 2026-09-14 here).

        The window stays open on the path that did not work, which is the one
        thing the user has to change -- and it is a sentence rather than the
        traceback that reaches `wish/debuglog.py`.
        """
        QMessageBox.critical(self, DIALOG_TITLE, text)

    # -- the rehearsal -----------------------------------------------------

    def _rehearse(self) -> None:
        """Build the save in memory, and set what to tell the player, if
        anything.

        Failures are shown, not raised: a refusal reaches the user as its own
        modal (`_maybe_warn`) while the log keeps the traceback.
        """
        self.conversion = None
        self._blocked = None
        self._name_warning = None
        self._attempt()
        self._suggest()
        self._settle_button()
        self._maybe_warn()

    def _maybe_warn(self) -> None:
        """Tell the player the one or two things left to say, now that
        `_rehearse` has no pane to draw a running status on: why the save
        could not be read (`self._blocked`), or a name DOS's own field could
        not hold whole (`self._name_warning`) -- `editor/convert.py`'s own
        `_maybe_warn`, ported rather than reinvented.

        Not gated on whether the window has been shown yet: unlike
        `ConvertDialog`, whose construction-time rehearsal is always inert
        (`__init__`'s own comment above), this dialog's very first
        rehearsal already ran against a real slot, and a refusal there is a
        refusal the player has to be told about even though the window has
        not appeared yet -- the same pattern `editor/window.py` already
        uses for `NO_DISKS`, a critical modal that fires before any window
        does. Deduplicated against what was last actually shown, so
        rehearsing again after an unrelated change -- typing in the
        destination box, say -- does not repeat a modal the player has
        already read.
        """
        if self._blocked != self._last_blocked_shown:
            self._last_blocked_shown = self._blocked
            if self._blocked is not None:
                title, text = self._blocked
                QMessageBox.critical(self, title, text)
        if self._name_warning != self._last_name_warning_shown:
            self._last_name_warning_shown = self._name_warning
            if self._name_warning:
                QMessageBox.warning(self, DIALOG_TITLE, self._name_warning)

    def _settle_button(self) -> None:
        """Convert is pressable when there is a conversion and somewhere to
        put it. Clearing the box is the one way a user can leave it with
        nowhere, and a disabled button says so without a sentence saying it."""
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.conversion is not None and bool(self.target()))

    def _attempt(self) -> None:
        # No slot is not a state the user can reach: `import_dos_save` refuses
        # a folder with no DOS save in it before this window is built. Nothing
        # said rather than a sentence, because a sentence about a state
        # nobody can be in is a sentence nobody should have to read.
        if not self.slot:
            return
        try:
            self.conversion = rehearse(self.folder, self.slot, self.files)
        except dos_codec.DosRecordError as exc:
            # The exception text is written for the tracker and may carry an
            # issue number, an address or a source file name; a player reads
            # `player_message` instead -- `WrongTitleError`'s own sentence, or
            # `dos_codec.CANNOT_CONVERT` for every other refusal (#176, #195).
            _log.exception("could not convert %s slot %s",
                           self.folder, self.slot)
            self._blocked = (DIALOG_TITLE, exc.player_message)
            return
        except Exception:
            # Anything `DosRecordError` does not cover is still not a
            # developer's traceback in front of a player (#195).
            _log.exception("could not convert %s slot %s",
                           self.folder, self.slot)
            self._blocked = (DIALOG_TITLE, dos_codec.CANNOT_CONVERT)
            return
        # For whoever is debugging with `WISH_DEBUG` and no window in front
        # of them -- `report.messages` (never shown here, or anywhere, any
        # more) is not repeated here, since nothing but `NOT_SET_OUT` has
        # ever written to it and that sentence names no offset worth a log
        # line of its own.
        for line in self.conversion.report.dropped:
            _log.debug("not converted, %s slot %s: %s",
                       self.folder, self.slot, line)
        # `report.losses` split in two, the same ruling `editor/convert.py`
        # follows: a name DOS's own field could not hold whole is real and
        # goes to the player; a magic-user memorising more spells than the
        # destination title's own slots (#508) and a spell id outside the
        # destination's own book (#509) are bugs, not platform limits, and
        # go to the debug log instead (`log_unshown_losses`).
        names = name_warnings(self.conversion.report)
        self._name_warning = "\n".join(names) if names else None
        log_unshown_losses(self.conversion.report)
