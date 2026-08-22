"""Where to keep settings, notes and the game disks, on any platform.

Nothing in here is Linux-specific. The project is developed on Linux but the
editor and the map are ordinary desktop programs, and a Windows user running
VICE has every reason to want them.
"""

from __future__ import annotations

import os
import pathlib
import sys

from por import games

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


def vice_settings_hint() -> str:
    """Where this platform keeps VICE's settings, for an error message."""
    if sys.platform == "win32":
        return r"%APPDATA%\vice\vice.ini"
    if sys.platform == "darwin":
        return "~/Library/Application Support/vice/vicerc"
    return ("~/.var/app/net.sf.VICE/config/vice/vicerc (Flatpak) "
            "or ~/.config/vice/vicerc")
