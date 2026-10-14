"""The Quickfight and Fast Travel buttons keep their whole labels beside a long dropdown."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QPushButton

from automap import actionbar
from goldbox import areas
from wish.session import Session
from wish.window import WishWindow

BUTTONS = ("action_clear_qf", "ft_button")


def longest_entry() -> str:
    """The longest line the Fast Travel dropdown can hold, whichever title is attached."""
    lines = [actionbar.NOTHING_TICKED]
    for title in (None, "pool-of-radiance", "curse-of-the-azure-bonds",
                  "secret-of-the-silver-blades", "pools-of-darkness"):
        lines.append(actionbar.no_areas(title))
        lines.extend(actionbar.FastTravelBar._label(row)
                     for row in areas.areas_for_title(title))
    return max(lines, key=len)


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    win = WishWindow(None, maps={}, session=Session(find=lambda pref=None: None))
    bar = win.map.fasttravel_bar
    # Before the first show, as the real window fills it: the box asks for the
    # width of whatever it holds.
    bar.combo.clear()
    bar.combo.addItem(longest_entry() + " - a long second line, GEO00 GEO01 GEO02, POOL3")
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    yield win, app
    win.close()


@pytest.mark.parametrize("size", [None, (1024, 711)], ids=["at-minimum", "1024x711"])
def test_both_buttons_show_their_whole_label(window, size):
    win, app = window
    width, height = size or (win.minimumSizeHint().width(), 720)
    win.resize(width, height)
    win.show()
    app.processEvents()
    for name in BUTTONS:
        button = win.findChild(QPushButton, name)
        assert button.text(), name
        assert button.width() >= button.sizeHint().width(), (
            f"{name} {button.text()!r} is {button.width()}px of the "
            f"{button.sizeHint().width()}px its label asks for")
