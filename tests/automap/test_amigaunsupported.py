"""An attached Amiga greys every Action button with the approved sentence."""

import os

import pytest
from gamedata import synthetic_geo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automap import amiga, c64
from automap.area import RESIDENT_GEO
from automap.state import Automapper
from automap.target import MemoryTarget
from goldbox.geo import Geo

TITLES = {
    "pool-of-radiance": "Pool of Radiance",
    "curse-of-the-azure-bonds": "Curse of the Azure Bonds",
    "secret-of-the-silver-blades": "Secret of the Silver Blades",
    "pools-of-darkness": "Pools of Darkness",
}


class FakeAmiga(MemoryTarget):
    c64_memory = False

    def __init__(self, memory, layout):
        super().__init__(memory)
        self.layout = layout


def window_on(target):
    from PyQt6.QtWidgets import QApplication, QMainWindow
    QApplication.instance() or QApplication([])

    from automap.window import AutomapBinding
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    geo = Geo(synthetic_geo())
    return AutomapBinding(root, Automapper(target, {"GEO00": geo}))


def memory():
    geo = Geo(synthetic_geo())
    return {0xD011: bytes([0x1B]), 0xD018: bytes([0x15]), 0xDD00: bytes([0x17]),
            c64.DEFAULT.live_position: bytes((4, 5, 0)),
            RESIDENT_GEO: geo.to_bytes()}


@pytest.fixture(autouse=True)
def notes_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))


def ticked(window, times=24):
    for _ in range(times):
        window.tick()
    return window


def every_button(window):
    bar, ft = window.actions_bar, window.fasttravel_bar
    return (list(bar.buttons.values()) + [ft.combo, ft.button, ft.back_button]
            + [card.level_up for card in window.roster.cards])


@pytest.mark.parametrize("key, title", sorted(TITLES.items()))
def test_every_greyed_button_names_its_own_title(key, title):
    window = ticked(window_on(FakeAmiga(memory(), amiga.MACHINES[key])))
    sentence = f"ERROR: Action unsupported on {title} (Amiga)."
    buttons = every_button(window)
    assert len(buttons) == 5 + 3 + 8
    for button in buttons:
        assert button.toolTip() == sentence
        if button not in [c.level_up for c in window.roster.cards]:
            assert not button.isEnabled()
    assert window.actions_bar.target is None
    assert window.fasttravel_bar.target is None


def test_no_emulator_attached_still_says_so():
    window = window_on(None)
    window.actions_bar.attach(None)
    for button in window.actions_bar.buttons.values():
        assert button.toolTip() == "no emulator attached"
        assert not button.isEnabled()


def test_a_c64_target_is_unchanged():
    window = ticked(window_on(MemoryTarget(memory())))
    assert window.actions_bar.unsupported is None
    assert window.fasttravel_bar.unsupported is None
    for button in window.actions_bar.buttons.values():
        assert "Amiga" not in button.toolTip()
        assert "unsupported" not in button.toolTip()
