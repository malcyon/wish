"""Settings that survive closing the window.

Small and hand-editable on purpose: a JSON file you can look at and fix. An
unreadable or half-written file is treated as "no settings yet" rather than as
an error -- losing a preference is not worth refusing to start over.
"""

from __future__ import annotations

import json
import logging
import pathlib
from dataclasses import asdict, dataclass, fields

from .paths import config_dir, titles_in

FILE = "automap.json"

#: A child of the `wish` logger, so `wish/debuglog.py`'s handler takes these
#: when the log is on and its level swallows them when it is off.
_log = logging.getLogger("wish.automap.config")


#: Ticked on a fresh config: New Phlan, The Slums, Sokol Keep -- `goldbox/areas.py`
#: ids 0, 20 and 21. The three a party has almost certainly walked in by the
#: time it wants to travel anywhere, so the list starts safe rather than long.
#: **A Pool of Radiance fact**, which is why it is keyed like one below.
DEFAULT_FAST_TRAVEL_TARGETS: tuple[int, ...] = (0, 20, 21)

#: `goldbox.games.Game.key` for the one title with an area table. Spelled out
#: rather than imported: this module is the settings file and has no other
#: business with the game descriptors.
POOL_OF_RADIANCE = "pool-of-radiance"

#: What a title gets before anybody has ticked anything. Every title but Pool
#: of Radiance gets nothing, because `goldbox.areas.areas_for_title` has nothing to
#: offer it -- an id ticked for a title with no area table would be an id from
#: another game's list.
DEFAULT_FAST_TRAVEL_BY_GAME: dict[str, tuple[int, ...]] = {
    POOL_OF_RADIANCE: DEFAULT_FAST_TRAVEL_TARGETS,
}


def game_key(game=None) -> str:
    """The key to file a fast-travel choice under.

    Takes a `goldbox.games.Game`, a key string, or None -- and None is Pool of
    Radiance, because every choice made before this setting was keyed at all
    was Pool of Radiance's. A `Game.title` is **not** accepted: the file is
    keyed by the stable identifier, never by display text.
    """
    key = getattr(game, "key", game)
    return key if isinstance(key, str) and key else POOL_OF_RADIANCE


def migrate_game_folder(folder: str) -> dict[str, str]:
    """What `Settings.disks` becomes once there is a folder per title (#22).

    `titles_in` names every title actually found in `folder`, in the same
    order `locate_disks` searches it -- Pool of Radiance first -- so the first
    one is the title this single shared folder was always answering for. A
    folder that no longer exists, is empty, or holds nothing this project
    recognises migrates to nothing: there is no title to key it under, and
    `disks` stays exactly as it was, still tried as the fallback.
    """
    if not folder:
        return {}
    found = titles_in(pathlib.Path(folder))
    return {found[0].key: folder} if found else {}


#: Keys an older build wrote, and the field each is now called. Read, never
#: written: a file saved by this build carries the new name only, so the rename
#: finishes rather than being carried forever. The cost of that is one-way --
#: an older build reading a new file sees no choice and offers its own three --
#: which beats a settings file with two names for one setting in it.
RENAMED = {"fasttravel_areas": "fast_travel_targets"}

#: The largest number a widget width may be -- Qt's own `QWIDGETSIZE_MAX`,
#: spelled out rather than imported because this module is the settings file
#: and builds no widgets. It is here as a guard rather than as a layout
#: opinion: a hand-edited width above it does not clamp when it reaches
#: `QSplitter.setSizes`, it raises, and a settings file must not be able to
#: stop the window opening.
WIDTH_CEILING = 16777215


def whole_sizes(raw, count: int) -> list[int] | None:
    """A remembered row of widget sizes, or None for "nobody chose these".

    None is what a hand-edited file gets: a size that is negative, is not a
    number, is above `WIDTH_CEILING`, or a row of the wrong length after the
    layout changed. **The whole row is refused rather than mended**, because a
    mended row is part somebody's and part ours, and a window laid out from
    that is harder to explain than one that opened at its defaults.

    Zero passes, because zero is what a pane dragged shut is worth.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) != count:
        return None
    sizes = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if value != int(value) or not 0 <= value <= WIDTH_CEILING:
            return None
        sizes.append(int(value))
    return sizes


@dataclass
class Settings:
    """Everything the map remembers between runs."""

    # On by default -- discovering the map is the point -- but the choice is
    # remembered, so turning it off stays off.
    reveal: bool = True
    # 0 means "the backend's own" -- 200 ms for VICE's loopback monitor, 500
    # for a device on a network cable. A number here is a deliberate override
    # and is honoured for both.
    interval_ms: int = 0
    # Which live backend to prefer when more than one answers. Empty means
    # "whichever is there"; a name settles the tie for somebody with both a
    # running emulator and a device on the desk.
    backend: str = ""
    # Wide enough for the roster column beside the map: the map alone is
    # 596 px at the fixed cell size, and the cards are 270.
    window_width: int = 940
    window_height: int = 820
    sight: int = 4
    # Where the game disks are. The answer, unless a command-line option
    # overrides it for one run -- see `paths.resolve_disks`, which is the only
    # thing that reads this.
    disks: str = ""
    # The folder `File > Open` last opened a save from, so the daily
    # navigation through several subdirectories is only ever done once (#66).
    # Read by `editor.files.open_start_dir`, which is also where the fallback
    # for a folder that has since been moved or deleted lives -- this field
    # only ever holds what was last seen to work, never a guess.
    last_save_folder: str = ""
    # Where `File > Open` should start, if the player has chosen one (#66
    # steps 2 and 3). A deliberate choice, unlike `last_save_folder` above --
    # once set it wins over both the currently open save's own folder and
    # the remembered one, the same way `disks` beats `paths.resolve_disks`'s
    # search beside the open save. Empty means nobody has set one, and
    # `editor.files.open_start_dir` falls back to the automatic behaviour.
    saves_folder: str = ""
    # Per-title disk folders, keyed by `Game.key` (#22): the shared `disks`
    # folder above answers "Pool of Radiance" for a machine that holds several
    # titles, whatever is actually being played, because that title is first
    # in `games.GAMES`. Optional per title -- `paths.resolve_disks` tries a
    # title's own entry first, then `disks`, then the search, so a player who
    # keeps every title in one folder is no worse off. `None` is a file from
    # before this existed; `load` migrates `disks` into it once, for whichever
    # title's disks that folder turns out to hold.
    game_folders: dict[str, str] | None = None
    # The Commodore 64 Ultimate's host, or `host:port`. Empty means "no device
    # named", which is what keeps a network with no Ultimate on it from being
    # probed at all. The *password* is deliberately not here: this file is
    # documented as one you can read and hand-edit, and a secret does not
    # belong in it -- `$POR_ULTIMATE_PASSWORD` stays the only way to give one.
    ultimate_host: str = ""
    # Where a copy of the save goes before the editor overwrites it, and which
    # of its **two states** it is in. Blank and unchosen is a fresh config:
    # nowhere to put a backup, so there are no backups and no saves either
    # (`editor/files.py`). Opening a save fills it in with `backups/` under
    # that save's folder and it keeps following whatever save is opened next.
    # Typing or browsing to one in the dialog sets `backup_folder_chosen`, and
    # from then on it is used for every save and **nothing changes it
    # automatically again**. Clearing the box is the way back: it unsets the
    # flag, and the next save opened fills it in.
    backup_folder: str = ""
    backup_folder_chosen: bool = False
    # `QWidget.saveGeometry()`, base64. Size, position and which screen, which
    # is what makes a window restored from a monitor that is no longer attached
    # land somewhere visible instead of off the edge. `window_width` and
    # `window_height` above are kept written for an older build reading this
    # file, and are the fallback on the first run after the upgrade.
    geometry: str = ""
    # Whether the debug log is on. Remembered from 2026-08 at Donald's
    # request, reversing "off at every start". The reason for the original
    # decision has not gone away -- a log you forget is on grows for months --
    # so while it is on the window says so in its title and in the status bar.
    # Named `diagnostics` rather than `debug_log` because
    # `tests/test_debuglog.py` still asserts no settings field carries "log";
    # that test encodes the superseded decision and is Donald's to retire.
    diagnostics: bool = False
    # Whether to clear quickfight after a fight ends.
    clear_quickfight: bool = False
    # The automapper tab's three columns in pixels, left to right -- the
    # roster, the map, and the Quest Log / Notes / Messages -- as the user
    # last dragged a divider (#162). Written only when a divider is dragged,
    # so a session that never touched one leaves whatever was there alone,
    # and a window squeezed narrow for an afternoon does not overwrite the
    # width somebody chose.
    #
    # **Zero is a legitimate width.** Donald ruled that a column may be
    # dragged shut, so what has to survive a restart is not a usable width but
    # a grabbable divider; `automap.panel.ColumnSplitter` is where that is
    # kept true. `None`, and anything that does not read as a row of whole
    # widths from 0 to `WIDTH_CEILING`, means nobody has dragged anything and
    # the columns open at their defaults.
    automap_columns: list[int] | None = None
    # The character editor tab's two rows in pixels, top to bottom -- the
    # roster and Character above, the Stats / Inventory / Spells tabs below --
    # as the user last dragged the divider (#97). The rules are
    # `automap_columns`' rules: written only on a drag, zero is a row dragged
    # shut and is kept, and anything that does not read as a row of whole
    # heights means nobody has dragged anything.
    editor_rows: list[int] | None = None
    # Which areas the Fast Travel dropdown offers, by `goldbox/areas.py` id, and
    # **keyed by `goldbox.games.Game.key`** -- an area id means nothing without a
    # title, and fasttraveling on Pool of Radiance's ids in another game's machine is
    # what issue #14 was.
    #
    # Three "nothing here" states and they are three different answers:
    # **None** means nobody has ticked anything ever, and every title gets its
    # own default; a **key absent** from the dict means nobody has ticked
    # anything *for that title*, and it gets that title's default; a key
    # present with **`[]`** is a player who unticked everything and is kept.
    # Anything else in the file -- a number, a string, a hand-edited mess --
    # reads as "not chosen".
    #
    # Called `fasttravel_areas` until 2026-08 (`RENAMED` reads that), and a bare list
    # until 2026-08 as well -- `load` migrates one to
    # `{"pool-of-radiance": [...]}`, because Pool of Radiance is the only title
    # that ever had one.
    fast_travel_targets: dict[str, list[int]] | None = None

    def chosen_areas(self, game=None) -> tuple[int, ...]:
        """The area ids the Fast Travel dropdown may offer for this title."""
        key = game_key(game)
        default = DEFAULT_FAST_TRAVEL_BY_GAME.get(key, ())
        if not isinstance(self.fast_travel_targets, dict):
            return default
        chosen = self.fast_travel_targets.get(key)
        if not isinstance(chosen, (list, tuple)):
            return default
        ids = []
        for value in chosen:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue        # a hand-edited file; drop the row, keep the rest
        return tuple(sorted(set(ids)))

    def set_chosen_areas(self, ids, game=None) -> None:
        """Record the choice for one title, empty included.

        Only that title's entry is touched: ticking in a Curse session must
        not disturb the Pool of Radiance list somebody spent a while building.
        """
        table = dict(self.fast_travel_targets) \
            if isinstance(self.fast_travel_targets, dict) else {}
        table[game_key(game)] = sorted({int(i) for i in ids})
        self.fast_travel_targets = table

    def column_widths(self, count: int) -> list[int] | None:
        """The remembered automapper column widths, or None for "use the
        defaults".

        None is what a hand-edited file gets: a width that is negative, is not
        a number, is above `WIDTH_CEILING`, or a row of the wrong length after
        the layout changed. **The whole row is refused rather than mended**,
        because a mended row is three widths of which one is somebody's and
        two are ours, and a window laid out from that is harder to explain
        than one that opened at its defaults.

        Zero passes, because zero is what a column dragged shut is worth.
        """
        return whole_sizes(self.automap_columns, count)

    def row_heights(self, count: int) -> list[int] | None:
        """The remembered character-editor row heights, or None for "use the
        defaults".

        The same rule as `column_widths` above and for the same reasons: a
        hand-edited number that is not a whole size between zero and
        `WIDTH_CEILING`, or a row of the wrong length after the layout
        changed, refuses the whole row rather than mending part of it. Zero
        passes, because zero is what a row dragged shut is worth.
        """
        return whole_sizes(self.editor_rows, count)

    @classmethod
    def load(cls) -> "Settings":
        path = config_dir() / FILE
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in raw.items() if k in known}
        for old, new in RENAMED.items():
            if old in raw and new not in values:
                values[new] = raw[old]
        # A bare list is Pool of Radiance's, because it is the only title that
        # ever had one. `fasttravel_areas` feeds in above first, so a file written
        # before 2026-08 migrates twice in this one read and comes out right.
        if isinstance(values.get("fast_travel_targets"), list):
            values["fast_travel_targets"] = {
                POOL_OF_RADIANCE: values["fast_travel_targets"]}
        # A file from before `game_folders` existed has no key for it at all,
        # which `values.get` reads as `None` -- distinct from `{}`, a player
        # who has used the per-title folders and cleared every one of them.
        # Only the former migrates.
        if values.get("game_folders") is None and values.get("disks"):
            values["game_folders"] = migrate_game_folder(values["disks"])
        return cls(**values)

    def save(self) -> None:
        path = config_dir() / FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=1) + "\n",
                            encoding="utf-8")
        except OSError:
            pass            # a read-only home should not take the window down


# -- window geometry ---------------------------------------------------------
#
# Qt's own encoding, not a width and a height: it carries the position and the
# screen too, and `restoreGeometry` knows how to refuse one saved on a monitor
# that is no longer attached. The clamp is ours -- Qt will happily restore a
# window larger than the screen it lands on, and the automapper is 1875 px wide
# by default, which is wider than plenty of laptops.

#: What to assume a title bar and a resize border cost while the window has
#: never been shown. Before `show()` there is no frame, so `frameGeometry()`
#: equals `geometry()` and the chrome measures as nothing -- which is how a
#: 1030 px window passed a clamp against a 1032 px work area on Windows and
#: then opened 39 px taller than the screen, with the status bar off the
#: bottom. Windows 11 draws a 32 px caption, GNOME about 37; 48 is above both
#: and is only ever a first-run estimate, because `clamp_to_screen` runs again
#: after `show()` with the real numbers.
UNSHOWN_CHROME = (16, 48)


def remember_geometry(window, settings: Settings) -> None:
    """Note where and how big this window is, for the next run."""
    settings.geometry = bytes(window.saveGeometry().toBase64()).decode("ascii")
    settings.window_width = window.width()
    settings.window_height = window.height()


def restore_geometry(window, settings: Settings,
                     floor: tuple[int, int] | None = None,
                     space=None) -> bool:
    """Put a window back where it was. True if a saved geometry was used.

    With nothing saved -- a first run, or a settings file from before this --
    the remembered width and height are used instead, raised to `floor` if the
    caller has one. Either way the result is clamped to the screen: **the floor
    never wins over the display**, or a laptop gets a window it cannot see the
    bottom of.

    `space` is the available work area, for a test that has to fake a screen
    the offscreen platform will not give it.
    """
    from PyQt6.QtCore import QByteArray

    done = False
    if settings.geometry:
        try:
            done = window.restoreGeometry(
                QByteArray.fromBase64(settings.geometry.encode("ascii")))
        except Exception:               # a hand-edited file, or another build
            _log.exception("the remembered geometry would not restore")
            done = False
    if not done:
        w, h = settings.window_width, settings.window_height
        if floor:
            w, h = max(w, floor[0]), max(h, floor[1])
        window.resize(w, h)
    clamp_to_screen(window, space)
    return done


def hold_geometry(window, space=None):
    """Stand by the size we just asked for, if the platform overrides it.

    A Wayland compositor answers the first `show()` with a size of its own and
    Qt takes it: on cosmic-comp, Donald's desktop, a bare `QMainWindow` that
    asks for 1875x1030 is 1280x662 one frame later -- measured with a plain
    window and no code of ours in it, so it is the platform. Everything set
    before `show()` is thrown away that way, which is what "the window doesn't
    remember its size on Linux" was: the compositor's size was then what
    closing remembered, so the next run opened at it and the size before it was
    gone for good.

    The same size asked for again *after* that first configure is honoured, so
    that is what this does. The first resize the program did not ask for is
    undone once, and then the watcher stands down -- every later one is the
    user dragging an edge, and fighting that would be far worse than the bug.
    The re-assertion is clamped like any other, so a platform shrinking a
    window because it genuinely does not fit still wins.

    Nothing happens on X11 or Windows, where no such configure arrives. The
    watcher is parented to the window; the return is for a test to hold.
    """
    from PyQt6.QtCore import QEvent, QObject

    class _Hold(QObject):
        def __init__(self):
            super().__init__(window)
            self.wanted = window.size()

        def eventFilter(self, obj, event):
            if obj is window and event.type() == QEvent.Type.Resize:
                if event.size() != self.wanted:
                    window.removeEventFilter(self)     # never twice
                    if not (window.isMaximized() or window.isFullScreen()):
                        window.resize(self.wanted)
                        clamp_to_screen(window, space)
            return False

    watcher = _Hold()
    window.installEventFilter(watcher)
    return watcher


def clamp_to_screen(window, space=None) -> None:
    """Never bigger than the display, never off the edge of it.

    `space` overrides the screen's work area, which is how a test fakes a
    display smaller than the one it is running on.
    """
    from PyQt6.QtGui import QGuiApplication

    if window.isMaximized() or window.isFullScreen():
        # The window manager owns the size; resizing it here un-maximises it.
        return
    if space is None:
        screen = window.screen() or QGuiApplication.primaryScreen()
        if screen is None:              # no display at all; nothing to clamp to
            return
        space = screen.availableGeometry()
    # The frame is what has to fit: a window sized to the whole work area and
    # then given a title bar is taller than the screen by the height of it.
    frame = window.frameGeometry()
    inner = window.geometry()
    chrome_w = frame.width() - inner.width()
    chrome_h = frame.height() - inner.height()
    if not window.isVisible() and (chrome_w, chrome_h) == (0, 0):
        # Never shown, so there is no frame to measure yet and the chrome
        # reads as nothing. Assume some, or the first run sizes itself to the
        # whole work area and the title bar pushes the bottom off the screen.
        chrome_w, chrome_h = UNSHOWN_CHROME
    w = min(inner.width(), max(space.width() - chrome_w, 1))
    h = min(inner.height(), max(space.height() - chrome_h, 1))
    if (w, h) != (inner.width(), inner.height()):
        window.resize(w, h)
    frame = window.frameGeometry()
    # Pull the far edge inside the work area first, then the near one -- and in
    # that order, because a window that still does not fit has to overflow
    # *downwards*. The other order aligned its bottom to the bottom of the
    # screen and pushed the title bar and the menu bar off the top, which is
    # what "the window is too big and I cannot see the menus" was on Windows:
    # the resize above cannot shrink a window past its minimum size, so on a
    # 1032 px work area a window whose layout will not go below about 1100 px
    # stayed 1100 px and then moved to y=-68.
    x = max(min(frame.x(), space.right() - frame.width() + 1), space.x())
    y = max(min(frame.y(), space.bottom() - frame.height() + 1), space.y())
    if (x, y) != (frame.x(), frame.y()):
        window.move(x, y)
