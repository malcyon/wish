#!/usr/bin/env python3
"""Install Wish's desktop entry and icon into the user's own XDG directories.

**Why this exists:** a Linux desktop draws the Alt-Tab and taskbar icon from
its *icon theme*, matched to the window by the application id.  Qt sets that
id -- `wish/window.py` calls `setDesktopFileName`, `setApplicationName` and
`setWindowIcon` already -- but if the desktop cannot find a `wish.desktop`
and a `wish` icon in `XDG_DATA_DIRS`, it has nothing to match and falls back
to a generic gear, **whatever `setWindowIcon` said**.  Donald,
2026-09-05: *"When I alt-tab in Linux to switch apps, Wish has a gear icon.
I think that should be the Wish pentagram."*

Nothing here is needed by a packaged build: a `.deb`, a Flatpak or a `pip
install` with a data-files hook puts the same two things in the same two
places.  It is for running Wish out of a working copy, which is how it is
run here.

**`Exec` is written at install time, not committed.** `assets/wish.desktop`
says `Exec=wish`, which is right for a packaged build and wrong for a
virtualenv, where the launcher is `<venv>/bin/wish`.  The path is worked out
from the interpreter running this script, so nobody's home directory ends up
in a committed file -- `tests/test_repository_contents.py` forbids that.

    .venv/bin/python tools/installdesktop.py            # install
    .venv/bin/python tools/installdesktop.py --check    # say what is there
    .venv/bin/python tools/installdesktop.py --remove   # take it out again

The icon is rendered from the artist's own `assets/logo/mark.svg` through
`ui.appicon`, at the sizes an icon theme expects, plus the SVG itself in
`scalable/` so a desktop that prefers vectors gets one.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap import paths  # noqa: E402

#: The sizes a freedesktop icon theme looks for.  A desktop picks the nearest
#: and scales, so the ones that matter most are the ones it will actually ask
#: for: 48 for Alt-Tab on most themes, 32 and 24 for a taskbar button.
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)

TEMPLATE = (pathlib.Path(__file__).resolve().parent.parent
            / "assets" / "wish.desktop")


def data_home() -> pathlib.Path:
    """`$XDG_DATA_HOME`, or the default the spec names when it is unset."""
    root = os.environ.get("XDG_DATA_HOME")
    return pathlib.Path(root) if root else pathlib.Path.home() / ".local/share"


def desktop_path() -> pathlib.Path:
    return data_home() / "applications" / f"{paths.APP}.desktop"


def icon_path(size: int | None) -> pathlib.Path:
    """Where one rendered size goes; `None` is the scalable SVG."""
    theme = data_home() / "icons" / "hicolor"
    if size is None:
        return theme / "scalable" / "apps" / f"{paths.APP}.svg"
    return theme / f"{size}x{size}" / "apps" / f"{paths.APP}.png"


def launcher() -> str:
    """The command the desktop entry should run.

    The `wish` script beside the interpreter running this, when there is one
    -- that is the virtualenv case and it is how Wish is run here.  Otherwise
    the bare name, which is right once Wish is installed on the path.
    """
    # `sys.prefix`, not `sys.executable`: a virtualenv's `bin/python` is a
    # symlink to the system interpreter, so resolving it walks out of the
    # environment and lands in `/usr/bin`, where there is no `wish` -- which
    # is how the first run of this wrote `Exec=wish` on a machine that has no
    # such command.
    beside = pathlib.Path(sys.prefix) / "bin" / paths.APP
    return str(beside) if beside.exists() else paths.APP


def entry_text() -> str:
    """`assets/wish.desktop` with its `Exec` line pointed at this checkout."""
    out = []
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        if line.startswith("Exec="):
            line = f"Exec={launcher()} %f"
        out.append(line)
    return "\n".join(out) + "\n"


def refresh(quiet: bool = False) -> None:
    """Ask the desktop to notice, where the tools for that exist."""
    for argv in (["update-desktop-database", str(desktop_path().parent)],
                 ["gtk-update-icon-cache", "-f", "-t",
                  str(data_home() / "icons" / "hicolor")]):
        if shutil.which(argv[0]) is None:
            continue
        try:
            subprocess.run(argv, check=False, capture_output=True, timeout=30)
        except OSError:
            pass
        if not quiet:
            print(f"  ran {argv[0]}")


def install() -> int:
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from ui import appicon

    path = desktop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(entry_text(), encoding="utf-8")
    path.chmod(0o755)
    print(f"wrote {path}")
    print(f"  Exec={launcher()} %f")

    for size in SIZES:
        where = icon_path(size)
        where.parent.mkdir(parents=True, exist_ok=True)
        if not appicon.image(size).save(str(where)):
            raise SystemExit(f"could not write {where}")
    print(f"wrote {len(SIZES)} icons under "
          f"{data_home() / 'icons' / 'hicolor'}")

    scalable = icon_path(None)
    scalable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(appicon.ASSET, scalable)
    print(f"wrote {scalable}")

    refresh()
    del app
    print("\nLog out and back in if the icon does not change straight away: "
          "some desktops read the theme once at start-up.")
    return 0


def check() -> int:
    ok = True
    path = desktop_path()
    if path.exists():
        exec_line = next((ln for ln in path.read_text(encoding="utf-8")
                          .splitlines() if ln.startswith("Exec=")), "Exec=?")
        print(f"desktop entry: {path}\n  {exec_line}")
    else:
        ok = False
        print(f"desktop entry: MISSING ({path})")
    found = [s for s in SIZES if icon_path(s).exists()]
    print(f"icons: {len(found)} of {len(SIZES)} "
          f"({', '.join(str(s) for s in found) or 'none'})")
    print(f"scalable: {'yes' if icon_path(None).exists() else 'MISSING'}")
    if not found:
        ok = False
    return 0 if ok else 1


def remove() -> int:
    for where in [desktop_path(), icon_path(None)] + [icon_path(s)
                                                      for s in SIZES]:
        if where.exists():
            where.unlink()
            print(f"removed {where}")
    refresh()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="say what is installed and exit nonzero if not")
    parser.add_argument("--remove", action="store_true",
                        help="take the entry and the icons out again")
    args = parser.parse_args(argv)
    if args.check and args.remove:
        raise SystemExit("give one of --check and --remove")
    if args.check:
        return check()
    if args.remove:
        return remove()
    return install()


if __name__ == "__main__":
    raise SystemExit(main())
