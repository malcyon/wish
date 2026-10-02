"""An attached Amiga greys Fast Travel, Level up and any unbuilt Action with the approved sentence."""

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


_app = None


def window_on(target):
    global _app
    from PyQt6.QtWidgets import QApplication, QMainWindow
    # Held: a `QApplication` with no Python reference can be collected.
    _app = QApplication.instance() or QApplication([])

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
def test_fast_travel_and_level_up_name_their_own_title(key, title):
    window = ticked(window_on(FakeAmiga(memory(), amiga.MACHINES[key])))
    sentence = f"ERROR: Action unsupported on {title} (Amiga)."
    ft = window.fasttravel_bar
    controls = [ft.combo, ft.button, ft.back_button] + [
        card.level_up for card in window.roster.cards]
    assert len(controls) == 3 + 8
    for control in controls:
        assert control.toolTip() == sentence
        assert not control.isEnabled()
    assert all(not card.level_up.isVisible() for card in window.roster.cards)
    assert window.fasttravel_bar.target is None


def test_a_title_with_nothing_confirmed_greys_every_action_with_its_sentence():
    key, title = "pools-of-darkness", TITLES["pools-of-darkness"]
    window = ticked(window_on(FakeAmiga(memory(), amiga.MACHINES[key])))
    assert len(window.actions_bar.buttons) == 5
    for button in window.actions_bar.buttons.values():
        assert button.toolTip() == f"ERROR: Action unsupported on {title} (Amiga)."
        assert not button.isEnabled()


def test_no_emulator_attached_still_says_so():
    window = window_on(None)
    window.actions_bar.attach(None)
    window.fasttravel_bar.attach(None)
    for button in window.actions_bar.buttons.values():
        assert button.toolTip() == "no emulator attached"
        assert not button.isEnabled()
    ft = window.fasttravel_bar
    assert "Amiga" not in ft.button.toolTip()
    assert ft.unsupported is None and not ft.button.isEnabled()
    for card in window.roster.cards:
        assert card.level_up.toolTip() == card.level_up_default_tip


def test_a_c64_target_is_unchanged():
    window = ticked(window_on(MemoryTarget(memory())))
    assert window.actions_bar.unsupported is None
    assert window.fasttravel_bar.unsupported is None
    for button in window.actions_bar.buttons.values():
        assert "Amiga" not in button.toolTip()
        assert "unsupported" not in button.toolTip()


def ready_character():
    from automap import live
    classes = tuple(live.ClassProgress(name, 8, 100_000, 0.5, 90_000)
                    for name in ("magic-user", "cleric", "thief"))
    return live.Character(slot=0, name="LADY KATHERINE", classes=classes,
                          level=8, armour_class=-3, thac0=5, hp=41, hp_max=99,
                          experience=100_000)


def sentence_anywhere(window):
    return [b.objectName() for b in every_button(window) if "Amiga" in b.toolTip()]


def show_with_ancestors(widget, root):
    while widget is not None and widget is not root:
        widget.show()
        widget = widget.parentWidget()


@pytest.mark.parametrize("leave", ["c64", "wrong-game"])
def test_leaving_the_amiga_gives_all_three_controls_back_their_own_text(leave):
    key = "pool-of-radiance"
    window = ticked(window_on(FakeAmiga(memory(), amiga.MACHINES[key])))
    assert window.roster.unsupported
    window.mapper.target = MemoryTarget(memory())
    if leave == "wrong-game":
        from automap.area import NOT_OURS
        window.mapper.title_check = NOT_OURS
    window._refresh_roster()
    assert not sentence_anywhere(window)
    assert window.actions_bar.unsupported is None
    assert window.fasttravel_bar.unsupported is None
    assert not window.roster.unsupported
    for card in window.roster.cards:
        assert card.level_up.isEnabled()
        assert card.level_up.toolTip() == card.level_up_default_tip
    if leave == "wrong-game":
        for button in window.actions_bar.buttons.values():
            assert button.toolTip() == "no emulator attached"
    # And attaching again greys them once more.
    window.mapper.target = FakeAmiga(memory(), amiga.MACHINES[key])
    window._refresh_roster()
    assert window.fasttravel_bar.unsupported
    assert window.roster.unsupported


def test_a_ready_character_cannot_be_levelled_once_an_amiga_attaches(monkeypatch):
    from automap import actions

    window = ticked(window_on(MemoryTarget(memory())))
    card = window.roster.cards[0]
    card.show_character(ready_character())
    show_with_ancestors(card.level_up, window.root)
    assert card.level_up.isVisibleTo(window.root) and card.level_up.isEnabled()

    window.mapper.target = FakeAmiga(memory(), amiga.MACHINES["pool-of-radiance"])
    window._refresh_roster()
    asked = []
    window.roster.level_up_requested.connect(asked.append)
    assert not card.level_up.isVisibleTo(window.root)
    assert not card.level_up.isEnabled()
    card.level_up.click()
    assert asked == []

    def forbidden(*_a, **_k):
        raise AssertionError("C64 addresses were read off an Amiga")

    monkeypatch.setattr(actions, "read_party", forbidden)
    window._level_up(0)                 # the second guard


def test_the_wrong_game_path_on_a_c64_is_unchanged():
    from automap.area import NOT_OURS

    window = window_on(MemoryTarget(memory()))
    window.mapper.title_check = NOT_OURS
    window._refresh_roster()
    assert window.actions_bar.target is None
    assert window.actions_bar.unsupported is None
    assert window.fasttravel_bar.unsupported is None
    assert not window.roster.unsupported
    for button in window.actions_bar.buttons.values():
        assert button.toolTip() == "no emulator attached"
