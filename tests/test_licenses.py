"""What Wish credits, against what Wish draws.

The failure this file exists to catch is the quiet one: somebody adds a glyph
to `ui/icons.py` and does not add its artist to `THIRD_PARTY_LICENSES.md`.
game-icons.net's glyphs are CC BY 3.0, and attribution is the whole of what
that licence asks for -- so an attribution file with a gap in it looks
discharged and is not, and nothing in a running program says so.

The list is generated from `ui.icons.ARTISTS` by `tools/genlicenses.py`, so the
tests here are about the two ends of that: what ships is credited, and nothing
is credited that does not ship.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

from ui import icons
from wish import licenses

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILE = ROOT / "THIRD_PARTY_LICENSES.md"

#: Donald's archive. Not in the repository and not on CI -- it is the game
#: artists' work, 4180 SVGs, and it is read only where it happens to be.
ARCHIVE = pathlib.Path.home() / "Downloads" / "game-icons.net.svg" / "icons"

#: `https://game-icons.net/1x1/<artist>/<name>.html`
LINK = re.compile(r"https://game-icons\.net/1x1/([a-z0-9]+)/([a-z0-9-]+)\.html")


def credited() -> dict[str, str]:
    """Every glyph the file names, and the artist it names for it."""
    text = FILE.read_text(encoding="utf-8")
    return {name: artist for artist, name in LINK.findall(text)}


def test_every_game_icon_that_ships_is_credited():
    """Add a glyph and forget the attribution, and this is what says so."""
    assert set(credited()) == set(icons.GAME_ICONS)


def test_the_file_credits_no_icon_that_does_not_ship():
    """The other direction: a list that over-claims is also a list nobody trusts."""
    assert set(credited()) <= set(icons.GAME_ICONS)


def test_each_icon_is_credited_to_the_artist_the_program_says_drew_it():
    assert credited() == {n: a.lower() for n, a in icons.ARTISTS.items()}


def test_every_shipped_icon_has_an_artist():
    """`ARTISTS` is the only thing standing between a glyph and a wrong credit."""
    assert set(icons.ARTISTS) == set(icons.GAME_ICONS)


def test_the_file_is_what_the_generator_would_write():
    """It is generated; a hand edit is a difference that will be overwritten."""
    result = subprocess.run([sys.executable, "tools/genlicenses.py", "--check"],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, (
        f"{result.stdout}{result.stderr}\nRun tools/genlicenses.py to update it.")


def test_font_awesome_is_credited_and_says_where_its_licence_is():
    """Wish ships both sets, so the file has to name both."""
    text = FILE.read_text(encoding="utf-8")
    assert "Font Awesome Free 7.3.1" in text
    assert "fontawesome-LICENSE.txt" in text
    assert (ROOT / "fontawesome-LICENSE.txt").exists()


def test_the_font_awesome_version_agrees_with_the_readme_and_the_about_box():
    """Three places say the version; a bump that misses one is a wrong credit."""
    from wish import about
    version = licenses.FONT_AWESOME_VERSION
    assert f"Font Awesome Free {version}" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Font Awesome Free {version}" in about.TEXT


@pytest.mark.skipif(not ARCHIVE.is_dir(),
                    reason="the game-icons.net archive is not on this machine")
def test_the_artist_is_the_one_the_archive_files_the_glyph_under():
    """A wrong artist is the failure an attribution file exists to prevent.

    Read against the archive rather than the site, and against every folder the
    name appears in: `dragon-head` is drawn by both Faithtoken and Lorc, so
    "the folder it is in" is not by itself an answer.
    """
    for name, artist in icons.ARTISTS.items():
        drew = {p.parent.name for p in ARCHIVE.rglob(f"{name}.svg")}
        assert drew, f"{name} is not in the archive at all"
        assert artist.lower() in drew, f"{name}: archive says {sorted(drew)}, we say {artist}"


# --- Help > Licenses --------------------------------------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from wish.session import Session
    from wish.window import WishWindow
    return WishWindow(maps={}, session=Session(find=lambda pref=None: None))


def help_menu(window):
    for action in window.menuBar().actions():
        if action.menu() is not None and "Help" in action.text():
            return action.menu()
    raise AssertionError("no Help menu")


def test_help_has_a_licenses_item(window):
    labels = [a.text() for a in help_menu(window).actions()]
    assert licenses.MENU_LICENSES in labels


def test_the_licenses_item_opens_the_dialog(app):
    """Built, not shown -- so what it says can be read without a modal window."""
    box = licenses.dialog()
    assert box.windowTitle() == licenses.TITLE
    said = box.ui.content.toPlainText()
    for name in icons.GAME_ICONS:
        assert licenses.title(name) in said, name
    assert "Font Awesome" in said
    box.deleteLater()


def test_the_dialog_can_be_scrolled_and_the_links_open(app):
    """Thirty-odd links in a box that cannot scroll is a box that hides them."""
    from PyQt6.QtCore import Qt
    box = licenses.dialog()
    assert box.ui.content.verticalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert box.ui.content.openExternalLinks()
    box.deleteLater()


def test_the_dialog_fits_a_720_high_screen(app):
    """`#97` and `#100` are open about exactly this: it has to fit Donald's screen."""
    box = licenses.dialog()
    assert box.sizeHint().height() <= 720
    assert box.minimumSizeHint().height() <= 720
    box.deleteLater()
