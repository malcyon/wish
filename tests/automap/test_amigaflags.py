"""Amiga action buttons, Level up and Fast Travel each need their own flag.

The backend flags decide whether mapping is offered at all; these two decide
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

from automap import amigaactions, amigafasttravel
from automap import amigatrip as trips

POD = "pools-of-darkness"
TICKED = (TILVERTON, GUILD, SEWERS, FIRE_KNIFE)
OFF = ["", "0", "off", "no", "false"]


@pytest.fixture(autouse=True)
def flags_unset(monkeypatch):
    monkeypatch.delenv(amigaactions.ACTIONS_ENV, raising=False)
    monkeypatch.delenv(amigafasttravel.FAST_TRAVEL_ENV, raising=False)


def test_the_flags_are_off_by_default():
    assert not amigaactions.enabled()
    assert not amigafasttravel.enabled()


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_each_flag_turns_on_by_its_own_variable(monkeypatch, value):
    monkeypatch.setenv(amigaactions.ACTIONS_ENV, value)
    assert amigaactions.enabled() and not amigafasttravel.enabled()
    monkeypatch.delenv(amigaactions.ACTIONS_ENV)
    monkeypatch.setenv(amigafasttravel.FAST_TRAVEL_ENV, value)
    assert amigafasttravel.enabled() and not amigaactions.enabled()


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


@pytest.mark.parametrize("value", [None, *OFF])
def test_a_confirmed_trip_stays_hidden_unless_its_flag_is_on(
        monkeypatch, lengths, value):  # noqa: F811
    if value is not None:
        monkeypatch.setenv(amigafasttravel.FAST_TRAVEL_ENV, value)
    window, _ = attached_trip(CURSE, GUILD, ticked=TICKED)
    bar = window.fasttravel_bar
    assert trips.ROWS[CURSE].confirmed
    assert bar.unsupported == amigaactions.unsupported("Curse of the Azure Bonds")
    assert not bar.combo.isEnabled()


def test_a_confirmed_trip_shows_with_its_flag(monkeypatch, lengths):  # noqa: F811
    monkeypatch.setenv(amigafasttravel.FAST_TRAVEL_ENV, "1")
    window, _ = attached_trip(CURSE, GUILD, ticked=TICKED)
    assert window.fasttravel_bar.combo.isEnabled()


def test_the_flags_do_not_turn_each_other_on(monkeypatch, lengths):  # noqa: F811
    monkeypatch.setenv(amigaactions.ACTIONS_ENV, "1")
    window, _ = attached_trip(CURSE, GUILD, ticked=TICKED)
    assert not window.fasttravel_bar.combo.isEnabled()
    monkeypatch.delenv(amigaactions.ACTIONS_ENV)
    monkeypatch.setenv(amigafasttravel.FAST_TRAVEL_ENV, "1")
    window, _ = attached_trip(CURSE, GUILD, ticked=TICKED)
    assert enabled(window) == set()
