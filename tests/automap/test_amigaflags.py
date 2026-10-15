"""Amiga action buttons, Level up and Fast Travel each need their own flag.

The backend decides whether mapping is offered at all; these two decide
whether the writes are, so a title can be mapped while its actions and trips
stay off.
"""

import os

import pytest
from test_amigafasttravelbar import (
    CURSE,
    FIRE_KNIFE,
    GUILD,
    SEWERS,
    TILVERTON,
    lengths,  # noqa: F401 -- a fixture
)
from test_amigafasttravelbar import attached as attached_trip
from test_amigawindow import (
    enabled,
    fighter,
    level_up_shown,
    pod_window,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automap import amigaactions
from automap import amigatrip as trips

POD = "pools-of-darkness"
TICKED = (TILVERTON, GUILD, SEWERS, FIRE_KNIFE)
OFF = ["", "0", "off", "no", "false"]


@pytest.fixture(autouse=True)
def flags_unset(monkeypatch):
    monkeypatch.delenv(amigaactions.ACTIONS_ENV, raising=False)


def test_the_actions_flag_is_off_by_default():
    assert not amigaactions.enabled()


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_the_actions_flag_turns_on_by_its_variable(monkeypatch, value):
    monkeypatch.setenv(amigaactions.ACTIONS_ENV, value)
    assert amigaactions.enabled()


@pytest.mark.parametrize("value", [None, *OFF])
def test_actions_and_level_up_stay_hidden_unless_their_flag_is_on(
        monkeypatch, value):
    if value is not None:
        monkeypatch.setenv(amigaactions.ACTIONS_ENV, value)
    window, _ = pod_window([fighter(8), fighter(8)])
    assert enabled(window) == set()
    assert not level_up_shown(window, 0)
    assert window.actions_bar.unsupported == amigaactions.unsupported(
        "Pools of Darkness")


def test_actions_and_level_up_show_with_their_flag(monkeypatch):
    monkeypatch.setenv(amigaactions.ACTIONS_ENV, "1")
    window, _ = pod_window([fighter(8), fighter(8)])
    assert enabled(window)
    assert level_up_shown(window, 0)


def test_a_confirmed_trip_shows_with_no_flag_set(lengths):  # noqa: F811
    window, _ = attached_trip(CURSE, GUILD, ticked=TICKED)
    assert trips.ROWS[CURSE].confirmed
    assert window.fasttravel_bar.combo.isEnabled()
    assert enabled(window) == set()
