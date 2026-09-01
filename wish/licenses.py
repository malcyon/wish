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

Font Awesome is not credited here any more. `#167` finished replacing every
icon it drew -- `person` for the Person note was the last -- so nothing in
the program renders a Font Awesome glyph, and `fontawesome-LICENSE.txt` came
out with the credit, and `ui.icons.FONT_AWESOME` is empty -- an
unused path is still somebody's work distributed without attribution.
bringing that icon back onto the screen means bringing the licence file and
this credit back too.
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


def page(name: str) -> str:
    """The artist's page for one glyph on game-icons.net."""
    return f"{SITE}1x1/{icons.ARTISTS[name].lower()}/{name}.html"


#: Glyphs whose page title is not their filename. game-icons.net's URL slug
#: for Lorc's *Embraced energy* misspells it, and Donald caught the credit
#: repeating the typo: attribution names a work as its author titled it, and
#: the author titled it "Embraced energy". The slug stays wrong in `page()`,
#: because that is the address that resolves.
TITLES = {"embrassed-energy": "Embraced Energy"}


def title(name: str) -> str:
    """`death-skull` as the site titles it: *Death Skull*.

    Except where the site's own filename disagrees with its page title -- see
    `TITLES`.
    """
    return TITLES.get(name) or name.replace("-", " ").title()


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
