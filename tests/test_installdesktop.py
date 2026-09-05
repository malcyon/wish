"""`tools/installdesktop.py`: the desktop entry and the icon theme entries.

A Linux desktop draws the Alt-Tab icon by matching the window to a `.desktop`
entry and then looking the icon up **by name** in its icon theme.  With
neither installed it draws a generic gear, whatever `setWindowIcon` said, and
that is what Donald saw on 2026-09-05.  A wheel ships both into
`<prefix>/share`, which the desktop searches for a `pip install --user` and
not for a virtualenv or a `pipx` install -- so `ensure` installs them into the
user's own directory the first time it finds none.

**Everything here redirects `$XDG_DATA_HOME` at `tmp_path` first.**  A test
that installed into the person's real home directory would be a worse bug than
the one this file is about.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import installdesktop  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A data directory of our own, and a search path that holds only it."""
    where = tmp_path / "share"
    monkeypatch.setenv("XDG_DATA_HOME", str(where))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "nowhere"))
    monkeypatch.delenv("WISH_NO_DESKTOP_INSTALL", raising=False)
    return where


def test_the_entry_and_the_icons_land_where_a_desktop_looks(home):
    """The two halves, in the two places the freedesktop spec names."""
    assert installdesktop.install(quiet=True) == 0
    entry = home / "applications" / "wish.desktop"
    assert entry.is_file(), entry
    text = entry.read_text(encoding="utf-8")
    assert "Icon=wish" in text
    assert "StartupWMClass=wish" in text
    for size in installdesktop.SIZES:
        icon = home / f"icons/hicolor/{size}x{size}/apps/wish.png"
        assert icon.is_file(), icon
    assert (home / "icons/hicolor/scalable/apps/wish.svg").is_file()


def test_the_exec_line_names_a_launcher_that_exists(home):
    """`Exec=wish` is right for a packaged build and wrong for a virtualenv.

    The path is worked out at install time from `sys.prefix`, **not** from
    `sys.executable`: a virtualenv's `bin/python` is a symlink to the system
    interpreter, so resolving it walks out of the environment into `/usr/bin`
    where there is no `wish` at all.  The first run of this tool wrote
    `Exec=wish` on a machine with no such command for exactly that reason.
    """
    installdesktop.install(quiet=True)
    line = next(ln for ln in (home / "applications" / "wish.desktop")
                .read_text(encoding="utf-8").splitlines()
                if ln.startswith("Exec="))
    command = line[len("Exec="):].removesuffix(" %f")
    assert command == "wish" or pathlib.Path(command).exists(), line


def test_nothing_is_written_when_an_entry_is_already_on_the_path(
        home, tmp_path, monkeypatch):
    """A distribution package, a Flatpak or a `pip install --user` puts one
    there, and writing over somebody else's is the way this goes wrong."""
    system = tmp_path / "system"
    (system / "applications").mkdir(parents=True)
    (system / "applications" / "wish.desktop").write_text("[Desktop Entry]\n",
                                                          encoding="utf-8")
    monkeypatch.setenv("XDG_DATA_DIRS", str(system))
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(sys, "platform", "linux")
    assert installdesktop.ensure() is None
    assert not (home / "applications").exists()


def test_an_offscreen_run_installs_nothing(home, monkeypatch):
    """`tests/conftest.py` forces offscreen, so this is what keeps the suite
    out of the person's home directory -- including this file's own run."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(sys, "platform", "linux")
    assert installdesktop.ensure() is None
    assert not (home / "applications").exists()


def test_a_headless_run_installs_nothing(home, monkeypatch):
    """Over ssh with no display there is no desktop to tell."""
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert installdesktop.ensure() is None
    assert not (home / "applications").exists()


def test_the_environment_variable_turns_it_off(home, monkeypatch):
    monkeypatch.setenv("WISH_NO_DESKTOP_INSTALL", "1")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert installdesktop.ensure() is None
    assert not (home / "applications").exists()


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_no_other_platform_is_touched(home, monkeypatch, platform):
    """Windows takes its icon from the executable's resource and macOS from
    the bundle, both of which `wish.spec` already carries."""
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    assert installdesktop.ensure() is None
    assert not (home / "applications").exists()


def test_ensure_installs_when_there_is_nothing_at_all(home, monkeypatch):
    """The case it exists for: a virtualenv, where the wheel's own data files
    landed somewhere no desktop searches."""
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    written = installdesktop.ensure()
    assert written == home / "applications" / "wish.desktop"
    assert written.is_file()


def test_remove_takes_back_everything_install_wrote(home):
    installdesktop.install(quiet=True)
    assert installdesktop.remove() == 0
    assert not (home / "applications" / "wish.desktop").exists()
    for size in installdesktop.SIZES:
        assert not (home / f"icons/hicolor/{size}x{size}/apps/wish.png").exists()


def test_a_failure_never_stops_the_window(home, monkeypatch):
    """`ensure` is called while the application is starting, so a window that
    failed to open because an icon could not be filed would be far worse than
    the gear it is fixing."""
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(installdesktop, "install",
                        lambda quiet=False: (_ for _ in ()).throw(OSError("no")))
    assert installdesktop.ensure() is None
