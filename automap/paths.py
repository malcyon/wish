"""Where to keep settings, notes and the game disks, on any platform.

Nothing in here is Linux-specific. The project is developed on Linux but the
editor and the map are ordinary desktop programs, and a Windows user running
VICE has every reason to want them.
"""

from __future__ import annotations

import os
import pathlib
import sys

from goldbox import games

APP = "wish"


def _home() -> pathlib.Path:
    return pathlib.Path.home()


def config_dir() -> pathlib.Path:
    """Settings: small, hand-editable, worth backing up."""
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or _home() / "AppData/Roaming"
    elif sys.platform == "darwin":
        root = _home() / "Library/Application Support"
    else:
        root = os.environ.get("XDG_CONFIG_HOME") or _home() / ".config"
    return pathlib.Path(root) / APP


def data_dir() -> pathlib.Path:
    """Notes and explored squares: bulkier, regenerable, per-machine."""
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or _home() / "AppData/Local"
    elif sys.platform == "darwin":
        root = _home() / "Library/Application Support"
    else:
        root = os.environ.get("XDG_DATA_HOME") or _home() / ".local/share"
    return pathlib.Path(root) / APP


def disk_globs(game: games.Game | None = None) -> tuple[str, ...]:
    """The patterns matching one title's disk images.

    `Game.disk_glob` already covers `POOL1.D64` and `POOL1.d64`; the lowered
    copy is for a directory unpacked from an archive that lower-cased the whole
    name. No game means Pool of Radiance, as everywhere else.
    """
    glob = (game or games.DEFAULT).disk_glob
    return (glob, glob.lower()) if glob.lower() != glob else (glob,)


def _dir_names(game: games.Game | None) -> tuple[str, ...]:
    """Directory names somebody would actually give a title's disks."""
    out = []
    for title in ([game.title] if game else [g.title for g in games.GAMES]):
        out += [f"{title} Disks", title]
    if game is None or game is games.POOL_OF_RADIANCE:
        out.append("PoR")
    return tuple(dict.fromkeys(out))


# Where the game disks might be. `POR_DISKS` wins; otherwise look in the places
# somebody would actually put them, and finally the working directory. There is
# deliberately no absolute default -- an earlier version hard-coded one
# developer's home directory, which is useless to everybody else.
def disk_candidates(game: games.Game | None = None) -> list[pathlib.Path]:
    env = os.environ.get("POR_DISKS")
    if env:
        return [pathlib.Path(env)]
    here = _home()
    names = _dir_names(game)
    roots = [pathlib.Path.cwd(), here, here / "Documents", here / "Games",
             here / "c64", here / "roms", here / "Downloads"]
    # On Windows, Documents and Downloads are commonly redirected into
    # OneDrive, and then `~/Documents` does not exist at all. $OneDrive is set
    # by the client; the literal is for a profile where it is not running.
    if sys.platform == "win32":
        drive = os.environ.get("OneDrive")
        for base in ([pathlib.Path(drive)] if drive else []) + [here / "OneDrive"]:
            roots += [base, base / "Documents", base / "Downloads"]
    out = [r / n for r in roots for n in names]
    out += [pathlib.Path.cwd(), here]
    return out


def has_disks(path: pathlib.Path, game: games.Game | None = None) -> bool:
    """Does this directory hold that title's disks?"""
    try:
        if not path.is_dir():
            return False
        for pattern in disk_globs(game):
            if next(path.glob(pattern), None) is not None:
                return True
    except OSError:
        pass
    return False


def titles_in(path) -> list[games.Game]:
    """Every title whose disks sit in this directory, Pool of Radiance first."""
    path = pathlib.Path(path)
    return [g for g in games.GAMES if has_disks(path, g)]


def locate_disks(game: games.Game | None = None
                 ) -> tuple[pathlib.Path, games.Game] | None:
    """The first directory holding a title's disks, and which title that is.

    With no `game` every title is tried, Pool of Radiance first: a machine with
    only its disks searches exactly as it always did, and another title is
    found only when Pool of Radiance's are nowhere to be seen. That order is a
    fallback for when nothing says which game is wanted -- a caller that knows,
    because a save is open, passes it and gets no guessing at all.
    """
    for want in ([game] if game is not None else list(games.GAMES)):
        for path in disk_candidates(want):
            if has_disks(path, want):
                return path, want
    return None


def find_disks(game: games.Game | None = None) -> pathlib.Path | None:
    """The first directory that actually holds this title's disks."""
    hit = locate_disks(game)
    return hit[0] if hit is not None else None


# -- one precedence, in one place --------------------------------------------
#
# There used to be three orders: the editor's, the map's, and the roster's.
# `resolve_disks` is all of them. The rule, in one sentence: **the Game
# directory setting is the answer; a command-line option beats it for one run;
# nothing else does.**
#
# `$POR_DISKS` keeps working -- the test suite and `tools/` find the player's
# disks with it -- but it sits below the setting and is out of the user-facing
# documentation. Nobody who uses the window ever meets it.

FLAG = "--disks"
GAME_PREFERENCE = "preferences (this title)"
PREFERENCE = "preferences"
ENVIRONMENT = "$POR_DISKS"
BESIDE = "beside the save"
SEARCHED = "searched"
NOWHERE = "nothing found"


def resolve_disks(flag=None, beside=None, game: games.Game | None = None,
                  settings=None) -> tuple[pathlib.Path | None, str]:
    """Where to look for the game disks, and who said so.

    The second half of the answer is still read by people, just not in the
    Preferences dialog any more: `wish/__main__.py` prints it beside the folder
    on stderr, and `wish/window.py` writes it to the debug log a user attaches
    to a bug report. Tests use it too, to assert the precedence rules -- `#22
    (A disk folder setting per game, not one shared by all six)`'s per-title
    preference beating the shared one, for instance. A folder named by the flag
    or by the setting is returned whether or not it holds any disks --
    reporting an empty folder as empty is more use than silently searching
    somewhere else.

    `beside` is the open save, as a file or its directory, and is only taken
    when disks are actually there. `settings` lets a window pass the copy it
    holds; without one the file is read, which is a few hundred bytes.

    A title's own folder in `settings.game_folders` (#22) wins over the shared
    `disks` folder, but only when `game` says which title is wanted -- with no
    game there is nothing to look up, and the shared folder and the search are
    what they always were.
    """
    # Imported here, not at module scope: `config` imports this module, and the
    # reverse at the top of the file is a cycle. `live.py` does the same.
    from .config import Settings
    if flag:
        return pathlib.Path(flag), FLAG
    if settings is None:
        settings = Settings.load()
    if game is not None:
        per_game = getattr(settings, "game_folders", None) or {}
        own = (per_game.get(game.key, "") or "").strip()
        if own:
            return pathlib.Path(own), GAME_PREFERENCE
    chosen = (getattr(settings, "disks", "") or "").strip()
    if chosen:
        return pathlib.Path(chosen), PREFERENCE
    env = os.environ.get("POR_DISKS")
    if env:
        return pathlib.Path(env), ENVIRONMENT
    if beside:
        where = pathlib.Path(beside)
        where = where if where.is_dir() else where.parent
        if has_disks(where, game):
            return where, BESIDE
    found = locate_disks(game)
    if found is not None:
        return found[0], SEARCHED
    return None, NOWHERE


def vice_settings_hint() -> str:
    """Where this platform keeps VICE's settings, for an error message."""
    if sys.platform == "win32":
        return r"%APPDATA%\vice\vice.ini"
    if sys.platform == "darwin":
        return "~/Library/Application Support/vice/vicerc"
    return ("~/.var/app/net.sf.VICE/config/vice/vicerc (Flatpak) "
            "or ~/.config/vice/vicerc")
