"""Where to keep settings, notes and the game disks, on any platform.

Nothing in here is Linux-specific. The project is developed on Linux but the
editor and the map are ordinary desktop programs, and a Windows user running
VICE has every reason to want them.
"""

from __future__ import annotations

import os
import pathlib
import sys

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


# Where the game disks might be. `POR_DISKS` wins; otherwise look in the places
# somebody would actually put them, and finally the working directory. There is
# deliberately no absolute default -- an earlier version hard-coded one
# developer's home directory, which is useless to everybody else.
def disk_candidates() -> list[pathlib.Path]:
    env = os.environ.get("POR_DISKS")
    if env:
        return [pathlib.Path(env)]
    here = _home()
    names = ("Pool of Radiance Disks", "Pool of Radiance", "PoR")
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


def find_disks() -> pathlib.Path | None:
    """The first directory that actually holds `POOL*.D64`."""
    for path in disk_candidates():
        try:
            if path.is_dir() and any(path.glob("POOL*.D64")):
                return path
            if path.is_dir() and any(path.glob("POOL*.d64")):
                return path
        except OSError:
            continue
    return None


def vice_settings_hint() -> str:
    """Where this platform keeps VICE's settings, for an error message."""
    if sys.platform == "win32":
        return r"%APPDATA%\vice\vice.ini"
    if sys.platform == "darwin":
        return "~/Library/Application Support/vice/vicerc"
    return ("~/.var/app/net.sf.VICE/config/vice/vicerc (Flatpak) "
            "or ~/.config/vice/vicerc")
