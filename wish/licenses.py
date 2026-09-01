"""Help > Licenses: who drew the icons Wish ships, and under what licence.

**Why this is a file and not a paragraph.** The game-icons.net glyphs are
CC BY 3.0, and attribution is the whole of what that licence asks for. An
attribution list that is wrong looks discharged and is not, so nothing here is
retyped: the list is built from `ui.icons.ARTISTS`, the table the program
actually draws from. Add a glyph without naming its artist there and
`tests/test_licenses.py` goes red.

`markdown()` writes `THIRD_PARTY_LICENSES.md` through `tools/genlicenses.py`;
`html()` fills the dialog. One source, two renderings, so the file on disk and
the box on screen cannot disagree.

Font Awesome is credited here too, because Wish ships both sets -- the
instruction to replace every Font Awesome icon was withdrawn on 2026-08-31.
Its licence text is not duplicated: `fontawesome-LICENSE.txt` is where it
lives, and this points at it.
"""

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QDialog, QMainWindow, QMenu, QWidget

from ui import icons

from .ui_licenses import Ui_LicensesDialog

#: The menu entry and the dialog's title. Donald's words.
MENU_LICENSES = "&Licenses"
TITLE = "Licenses"

SITE = "https://game-icons.net/"
CC_BY_3 = "https://creativecommons.org/licenses/by/3.0/"

#: Which Font Awesome Free the path data in `ui/icons.py` came from. The
#: README and the About box say the same number; `tests/test_licenses.py`
#: checks they still agree.
FONT_AWESOME_VERSION = "7.3.1"
FONT_AWESOME_SITE = "https://fontawesome.com"
FONT_AWESOME_LICENCE_FILE = "fontawesome-LICENSE.txt"


def page(name: str) -> str:
    """The artist's page for one glyph on game-icons.net."""
    return f"{SITE}1x1/{icons.ARTISTS[name].lower()}/{name}.html"


def title(name: str) -> str:
    """`death-skull` as the site titles it: *Death Skull*."""
    return name.replace("-", " ").title()


def by_artist() -> list[tuple[str, list[str]]]:
    """Every shipped game-icons.net glyph, grouped under whoever drew it.

    Artists come out in the order their first glyph was added to
    `ui.icons.ARTISTS`, which is the order Donald listed them in, and the
    glyphs under each keep that order too. A dict cannot hold the same name
    twice, which is what stops one glyph appearing under two artists.
    """
    groups: dict[str, list[str]] = {}
    for name in icons.GAME_ICONS:
        groups.setdefault(icons.ARTISTS[name], []).append(name)
    return list(groups.items())


def markdown() -> str:
    """`THIRD_PARTY_LICENSES.md`, generated."""
    out: list[str] = []
    add = out.append

    add("# Third-Party Assets")
    add("")
    add("## Game-icons.net")
    add("")
    add(f"Wish uses icons from [Game-icons.net]({SITE}), created by the artists "
        "listed below. These icons are used under the [Creative Commons "
        f"Attribution 3.0 Unported (CC BY 3.0) license]({CC_BY_3}).")
    add("")
    for artist, names in by_artist():
        add(f"### {artist}")
        add("")
        for name in names:
            add(f"* [{title(name)}]({page(name)})")
        add("")
    add("Game-icons.net is maintained by **Cathelineau** and provides these icons "
        "under the Creative Commons Attribution 3.0 Unported license. The original "
        "icon authors retain their respective copyrights.")
    add("")
    add("## Font Awesome")
    add("")
    add(f"Some icons are from **Font Awesome Free {FONT_AWESOME_VERSION}** by "
        f"Fonticons, Inc. (<{FONT_AWESOME_SITE}>) — icons licensed **CC BY 4.0**. "
        "Their path data is in `ui/icons.py`; the licence is in "
        f"[`{FONT_AWESOME_LICENCE_FILE}`]({FONT_AWESOME_LICENCE_FILE}).")
    add("")
    return "\n".join(out)


def html() -> str:
    """The same attributions as rich text, for the dialog."""
    out: list[str] = []
    add = out.append

    add("<h2>Game-icons.net</h2>")
    add(f'<p>Wish uses icons from <a href="{SITE}">Game-icons.net</a>, created by '
        "the artists listed below. These icons are used under the "
        f'<a href="{CC_BY_3}">Creative Commons Attribution 3.0 Unported '
        "(CC BY 3.0) license</a>.</p>")
    for artist, names in by_artist():
        add(f"<h3>{artist}</h3>")
        add("<ul>")
        for name in names:
            add(f'<li><a href="{page(name)}">{title(name)}</a></li>')
        add("</ul>")
    add("<p>Game-icons.net is maintained by <b>Cathelineau</b> and provides these "
        "icons under the Creative Commons Attribution 3.0 Unported license. The "
        "original icon authors retain their respective copyrights.</p>")
    add("<h2>Font Awesome</h2>")
    add(f'<p>Some icons are from <b>Font Awesome Free {FONT_AWESOME_VERSION}</b> by '
        f'Fonticons, Inc. (<a href="{FONT_AWESOME_SITE}">{FONT_AWESOME_SITE}</a>) — '
        "icons licensed <b>CC BY 4.0</b>. Their path data is in "
        f"<code>ui/icons.py</code>; the licence is in "
        f"<code>{FONT_AWESOME_LICENCE_FILE}</code>.</p>")
    return "\n".join(out)


class LicensesDialog(QDialog):
    """The attributions, scrollable, with every link clickable.

    Scrollable because the list grows with every glyph added: a fixed box would
    be a box that hides the newest attribution, which is the one most likely to
    be missing.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui = Ui_LicensesDialog()
        self.ui.setupUi(self)
        self.ui.content.setOpenExternalLinks(True)
        self.ui.content.setHtml(html())


def dialog(parent: QWidget | None = None) -> LicensesDialog:
    """The dialog, built and not shown, so a test can read what it says."""
    return LicensesDialog(parent)


def show(parent: QWidget | None = None) -> None:
    dialog(parent).exec()


def install(window: QMainWindow, menu: QMenu) -> QAction:
    """Add Licenses to an existing Help menu."""
    action = QAction(MENU_LICENSES, window)
    action.triggered.connect(lambda _checked=False: show(window))
    menu.addAction(action)
    return action
