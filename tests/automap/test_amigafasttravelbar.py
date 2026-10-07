"""The Fast Travel row on an attached Amiga, through the real window.

The trip table is the real `automap/amigatrip.py` and the action is the real
`automap/amigafasttravel.py`; the machine is made up. Each title's world menu
is laid out at the table's own offsets, and the player's disks are replaced by
a table in which every script leaves room for a trip, so what these tests pin
is which trips the row offers and what it does with the answers.
"""

import dataclasses
import os
import struct
from types import SimpleNamespace

import pytest
from test_amigawindow import (
    BASE,
    SLOW,
    FakeAmiga,
    c64_memory,
    lay_party,
    window_on,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automap import actionbar, amigaactions, amigafasttravel, amigatrip
from automap import actions as engine
from automap import amigatrip as trips
from automap.target import MemoryTarget

CURSE = "curse-of-the-azure-bonds"
POOL = "pool-of-radiance"
BLADES = "secret-of-the-silver-blades"
POD = "pools-of-darkness"
BUFFER = SLOW + 0x30000
ENTRY = 0x8137
TILVERTON, SEWERS, FIRE_KNIFE, GUILD = 1, 3, 4, 2


def sentence(key):
    return amigaactions.unsupported(trips.ROWS[key].title)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """An armed trip's deadline never passes on a slow runner; a test moves the
    returned list's one entry to pass it. Only amigafasttravel sees the held
    clock, so a real wait loop elsewhere still runs."""
    now = [1000.0]
    monkeypatch.setattr(amigafasttravel, "time",
                        SimpleNamespace(monotonic=lambda: now[0]))
    return now


@pytest.fixture
def lengths(monkeypatch):
    """Every area's script is 0x1000 bytes long, so every tail is free. The
    calls are kept: `(row key, disks)`."""
    calls = []

    def read(row, disks):
        calls.append((row.key, disks))
        return {i: 0x1000 for i in range(0x100)}

    monkeypatch.setattr(trips, "script_lengths", read)
    return calls


def at_world_menu(target, key, area):
    """The title standing at its world menu in `area`, nothing pending."""
    row = trips.ROWS[key]

    def put(offset, data):
        target.put(BASE + offset, data)

    target.put(BUFFER, b"\xee" * 0x1000)
    put(row.buffer_pointer, struct.pack(">I", BUFFER - row.buffer_bias))
    put(row.area, bytes([area]))
    put(row.mode, bytes([row.world_mode]))
    put(row.step_entry, ENTRY.to_bytes(2, "big"))
    if row.window_pointer is not None:          # Pool: a window and its port
        window, port = SLOW + 0x40000, SLOW + 0x41000
        put(row.window_pointer, window.to_bytes(4, "big"))
        target.put(window + trips.WINDOW_USERPORT, port.to_bytes(4, "big"))
        target.put(port + trips.PORT_LIST, trips.empty_list(port))
        put(row.view, bytes([row.world_view]))
        gadgets = trips.gadget_layout(row.menu_text)
        first = SLOW + 0x42000
        target.put(window + trips.WINDOW_FIRST_GADGET, first.to_bytes(4, "big"))
        for i, (gid, left, width) in enumerate(gadgets):
            at = first + 0x40 * i
            following = at + 0x40 if i + 1 < len(gadgets) else 0
            target.put(at, following.to_bytes(4, "big"))
            target.put(at + trips.GADGET_LEFT_EDGE, left.to_bytes(2, "big"))
            target.put(at + trips.GADGET_WIDTH, width.to_bytes(2, "big"))
            target.put(at + trips.GADGET_ID, gid.to_bytes(2, "big"))
        return
    put(row.menu_kind, b"\x00\x01")
    if row.menu_text is not None:            # Silver Blades' was never read
        put(row.menu_at, row.menu_text + b"\0")
    put(row.key_buffer, b"\x00\x0d")


def tick_away(target, key, area):
    """The game takes the trip: the area changes and the key is consumed."""
    row = trips.ROWS[key]
    target.put(BASE + row.area, bytes([area]))
    target.put(BASE + row.key_buffer, b"\x00\x0d")
    if row.clears_buffer:
        target.put(BUFFER + 0x1000, bytes(trips.BUFFER_SIZE - 0x1000))


def attached(key, area, ticked=(), disks="the player's disks", can_write=True):
    target = FakeAmiga(c64_memory(), key, can_write)
    lay_party(target, key, mode=trips.ROWS[key].world_mode)
    at_world_menu(target, key, area)
    window = window_on(target)
    window.disks = disks
    window.settings.set_chosen_areas(ticked, key)
    window._refresh_roster()
    window.fasttravel_bar.reload_areas()
    return window, target


def pick(window, area_id):
    bar = window.fasttravel_bar
    bar.combo.setCurrentIndex([r.id for r in bar.rows].index(area_id))


def labels(window):
    combo = window.fasttravel_bar.combo
    return [combo.itemText(i) for i in range(combo.count())]


# -- which trips are offered -----------------------------------------------------

def test_the_combo_and_button_enable_only_for_an_offered_trip(lengths):
    window, _ = attached(CURSE, GUILD, ticked=(TILVERTON, GUILD, SEWERS, FIRE_KNIFE))
    bar = window.fasttravel_bar
    assert bar.combo.isEnabled()
    pick(window, SEWERS)
    assert bar.button.isEnabled() and bar.button.toolTip() == actionbar.DANGER
    pick(window, FIRE_KNIFE)
    assert bar.button.isEnabled()
    pick(window, TILVERTON)
    assert bar.button.isEnabled()
    # The area the party is in: the button says why, the dropdown stays open
    # so another area can be picked.
    pick(window, GUILD)
    assert not bar.button.isEnabled()
    assert bar.button.toolTip() == "The party is already in that area"
    assert bar.combo.isEnabled()


def test_with_nothing_offered_the_dropdown_closes_too(lengths, monkeypatch):
    row = trips.ROWS[CURSE]
    held = trips.Difference("held", "a made-up open question",
                            lambda here, to, back: to == TILVERTON)
    monkeypatch.setitem(trips.ROWS, CURSE,
                        dataclasses.replace(row, differences=(held,)))
    window, _ = attached(CURSE, GUILD, ticked=(TILVERTON,))
    bar = window.fasttravel_bar
    assert not bar.combo.isEnabled() and not bar.button.isEnabled()
    assert bar.combo.toolTip() == bar.button.toolTip() == sentence(CURSE)


def test_a_game_that_is_not_at_its_world_menu_offers_nothing(lengths):
    window, target = attached(CURSE, GUILD, ticked=(SEWERS,))
    assert window.fasttravel_bar.button.isEnabled()
    target.put(BASE + trips.ROWS[CURSE].menu_kind, b"\x00\x00")
    window._refresh_roster()
    bar = window.fasttravel_bar
    assert not bar.combo.isEnabled() and not bar.button.isEnabled()
    assert bar.button.toolTip() == engine.FASTTRAVEL_BUSY


def test_a_target_that_cannot_write_offers_nothing(lengths):
    window, _ = attached(CURSE, GUILD, ticked=(SEWERS,), can_write=False)
    bar = window.fasttravel_bar
    assert not bar.combo.isEnabled() and not bar.button.isEnabled()
    assert bar.button.toolTip() == sentence(CURSE)


def test_without_the_players_disks_no_trip_is_offered(lengths):
    window, _ = attached(CURSE, GUILD, ticked=(SEWERS,), disks=None)
    assert not window.fasttravel_bar.button.isEnabled()
    assert window.fasttravel_bar.button.toolTip() == sentence(CURSE)
    assert lengths == []


def test_the_windows_disks_are_what_the_scripts_are_read_from(lengths):
    window, _ = attached(CURSE, GUILD, ticked=(SEWERS,), disks="somewhere")
    assert window.fasttravel_bar.fasttravel.disks == "somewhere"
    assert lengths == [(CURSE, "somewhere")]
    window._refresh_roster()
    assert len(lengths) == 1                      # read once, not every poll
    window.disks = "elsewhere"
    window._refresh_roster()
    assert window.fasttravel_bar.fasttravel.disks == "elsewhere"
    assert lengths[-1] == (CURSE, "elsewhere")


def test_pool_of_radiance_offers_every_trip_from_an_area_with_doors(lengths):
    """Area 14 was greyed out for every destination while its doors were
    held; every trip goes straight now."""
    window, _ = attached(POOL, 14, ticked=(0, 1, 2))
    bar = window.fasttravel_bar
    assert labels(window) == [r.name for r in bar.rows] and len(bar.rows) == 3
    for row in bar.rows:
        pick(window, row.id)
        assert bar.button.isEnabled()
        assert bar.button.toolTip() != sentence(POOL)
    assert bar.combo.isEnabled()


@pytest.mark.parametrize("here", [0, 2, 3, 9, 14, 18, 21, 22, 23])
def test_pool_of_radiance_is_not_greyed_out_in_an_area_with_doors(lengths, here):
    to = 1 if here != 1 else 4
    window, _ = attached(POOL, here, ticked=(to,))
    bar = window.fasttravel_bar
    pick(window, to)
    assert bar.button.isEnabled()


def test_an_unconfirmed_title_greys_the_whole_row_with_the_sentence(lengths):
    window, _ = attached(BLADES, 33, ticked=(3, 16))
    bar = window.fasttravel_bar
    for widget in (bar.combo, bar.button, bar.back_button):
        assert not widget.isEnabled() and widget.toolTip() == sentence(BLADES)
    assert bar.target is None


def test_a_title_with_no_area_table_says_so(lengths, monkeypatch):
    """No real Amiga title lacks a table now, so the premise is made."""
    from goldbox import areas
    monkeypatch.setattr(areas, "TABLES", {
        title: table for title, table in areas.TABLES.items()
        if title != areas.POOLS_OF_DARKNESS})
    window, _ = attached(POD, 0x30)
    bar = window.fasttravel_bar
    assert labels(window) == ["No areas are known for Pools of Darkness."]
    assert not bar.combo.isEnabled() and not bar.button.isEnabled()


def test_pools_of_darkness_offers_its_own_ticks_not_pools(lengths):
    window, _ = attached(POD, 48, ticked=(33,))
    window.settings.set_chosen_areas((20, 21), POOL)
    window.fasttravel_bar.reload_areas()
    assert labels(window) == ["Aerie"]


def test_pools_ticks_alone_leave_pools_of_darkness_with_nothing_ticked(lengths):
    window, _ = attached(POD, 48)
    window.settings.set_chosen_areas((0, 20, 21), POOL)
    window.fasttravel_bar.reload_areas()
    assert labels(window) == [actionbar.NOTHING_TICKED]


def test_pools_of_darkness_does_not_list_an_area_with_no_map(lengths):
    window, _ = attached(POD, 48, ticked=(33, 41, 84))
    assert labels(window) == ["Aerie"]


def test_the_dropdown_lists_the_machines_title_not_the_windows(lengths):
    """The window was set up for Pool of Radiance; a Curse machine is attached."""
    window, _ = attached(CURSE, GUILD, ticked=(SEWERS,))
    assert window.state.title != "Curse of the Azure Bonds"
    assert labels(window) == ["Tilverton sewers"]


def test_no_c64_address_is_read_or_written(lengths, monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("the C64's machinery was used on a 68000")

    monkeypatch.setattr(engine, "program_counter", forbidden)
    monkeypatch.setattr(actionbar, "ResidentGeo", forbidden)
    monkeypatch.setattr(actionbar.FastTravelBar, "wait_for_key_wait", forbidden)
    window, target = attached(CURSE, GUILD, ticked=(SEWERS,))
    pick(window, SEWERS)
    window.fasttravel_bar.button.click()
    assert window.fasttravel_bar.last.ok
    assert window.fasttravel_bar._pending is None
    assert all(a >= SLOW or a == 0 for a, _ in target.writes)


def test_a_refresh_reads_the_gate_once_however_many_areas_are_listed(lengths):
    window, target = attached(CURSE, GUILD, ticked=(TILVERTON, SEWERS, FIRE_KNIFE, GUILD))
    assert len(window.fasttravel_bar.rows) == 4
    menu = BASE + trips.ROWS[CURSE].menu_at
    target.ram_reads.clear()
    window.fasttravel_bar.refresh()
    assert [r for r in target.ram_reads if r[0] == menu] == [
        (menu, len(trips.ROWS[CURSE].menu_text) + 1)]


def test_a_read_that_fails_is_the_machine_not_being_readable(lengths):
    window, target = attached(CURSE, GUILD, ticked=(SEWERS,))
    target.fail_at.add(BASE + trips.ROWS[CURSE].mode)
    window.fasttravel_bar.refresh()                    # does not raise
    bar = window.fasttravel_bar
    assert not bar.button.isEnabled()
    assert bar.button.toolTip() == "The machine is not readable right now"


# -- a trip that fires, and one that does not -----------------------------------

def test_a_trip_that_fires_updates_the_window(lengths):
    window, target = attached(CURSE, GUILD, ticked=(SEWERS, FIRE_KNIFE))
    bar = window.fasttravel_bar
    pick(window, SEWERS)
    bar.button.click()
    assert bar.last.ok and bar.last.message == "Traveling to Tilverton sewers."
    assert bar.fasttravel.trip is not None
    # Armed: the key is waiting, so the row is busy and cannot arm a second.
    assert not bar.button.isEnabled()
    assert bar.button.toolTip() == engine.FASTTRAVEL_BUSY
    assert not bar.combo.isEnabled()

    tick_away(target, CURSE, SEWERS)
    window._refresh_roster()                           # the ordinary poll
    assert bar.fasttravel.trip is None
    assert bar.fasttravel.back.area == GUILD
    assert bar.combo.isEnabled()
    pick(window, FIRE_KNIFE)
    assert bar.button.isEnabled()
    pick(window, SEWERS)                               # now where the party is
    assert bar.button.toolTip() == "The party is already in that area"
    # Curse's Return is no longer a held trip.
    assert bar.back_button.isEnabled()
    # Only the arming line was said; a trip that happened adds none.
    assert bar.last.message == "Traveling to Tilverton sewers."


def test_a_trip_stays_armed_until_the_clock_passes_its_deadline(
        lengths, frozen_clock):
    window, target = attached(CURSE, GUILD, ticked=(SEWERS, FIRE_KNIFE))
    bar = window.fasttravel_bar
    before = bytes(target.ram)
    pick(window, SEWERS)
    bar.button.click()
    frozen_clock[0] += amigafasttravel.FIRE_SECONDS
    window._refresh_roster()
    assert bar.fasttravel.trip is not None
    frozen_clock[0] += 0.001
    window._refresh_roster()
    assert bar.fasttravel.trip is None
    assert bytes(target.ram) == before


def test_a_trip_that_does_not_fire_puts_everything_back(lengths):
    window, target = attached(CURSE, GUILD, ticked=(SEWERS, FIRE_KNIFE))
    bar = window.fasttravel_bar
    said = []
    bar.say = lambda text, detail="", alarm=False: said.append((text, alarm))
    before = bytes(target.ram)
    pick(window, SEWERS)
    bar.button.click()
    assert bytes(target.ram) != before and bar.fasttravel.trip is not None

    window._refresh_roster()                           # inside the deadline
    assert bar.fasttravel.trip is not None
    bar.fasttravel.trip.deadline = 0                   # and now past it
    window._refresh_roster()
    assert bar.fasttravel.trip is None
    assert bytes(target.ram) == before
    assert bar.fasttravel.back is None
    assert said[-1] == (engine.FASTTRAVEL_FAILED, True)
    assert bar.last.message == engine.FASTTRAVEL_FAILED
    pick(window, SEWERS)
    assert bar.button.isEnabled()


def test_a_trip_whose_machine_goes_away_is_forgotten(lengths):
    window, target = attached(CURSE, GUILD, ticked=(SEWERS,))
    pick(window, SEWERS)
    window.fasttravel_bar.button.click()
    assert window.fasttravel_bar.fasttravel.trip is not None
    window.mapper.target = None
    window.fasttravel_bar.attach(None)
    assert window.fasttravel_bar.fasttravel.trip is None


# -- switching machines -----------------------------------------------------------

def test_switching_to_a_c64_restores_the_c64_row(lengths):
    window, amiga_target = attached(CURSE, GUILD, ticked=(SEWERS,))
    bar = window.fasttravel_bar
    c64_action = bar._c64_fasttravel
    c64_rows = bar._c64_title
    assert isinstance(bar.fasttravel, amigafasttravel.AmigaFastTravel)
    assert labels(window) == ["Tilverton sewers"]

    c64_target = MemoryTarget(c64_memory())
    window.mapper.target = c64_target
    window._refresh_roster()
    assert bar.fasttravel is c64_action
    assert type(bar.fasttravel) is engine.FastTravel
    assert (bar.title, bar.game) == c64_rows
    assert bar.target is c64_target
    assert bar.unsupported is None
    assert "Tilverton sewers" not in labels(window)
    assert {r.id for r in bar.rows} == set(window.settings.chosen_areas(bar.game))
    assert "Amiga" not in bar.button.toolTip() + bar.combo.toolTip()

    window.mapper.target = amiga_target
    window._refresh_roster()
    assert isinstance(bar.fasttravel, amigafasttravel.AmigaFastTravel)
    assert labels(window) == ["Tilverton sewers"]


def test_a_title_change_on_an_amiga_keeps_the_machines_areas(lengths):
    window, _ = attached(CURSE, GUILD, ticked=(SEWERS,))
    window.state.title = "Pool of Radiance"
    window._apply_title()
    assert labels(window) == ["Tilverton sewers"]
    assert window.fasttravel_bar._c64_title[0] == "Pool of Radiance"


def test_a_c64_window_is_unchanged(lengths):
    target = MemoryTarget(c64_memory())
    window = window_on(target)
    for _ in range(24):
        window.tick()
    bar = window.fasttravel_bar
    assert type(bar.fasttravel) is engine.FastTravel
    assert bar.target is target and not bar._amiga
    assert type(bar._idle_poll()) is actionbar._NotAskingThePC
    assert amigatrip.ROWS            # the Amiga table exists and was not used
    assert lengths == []


# -- a trip dropped while it is armed ---------------------------------------------

def armed(lengths):
    window, target = attached(CURSE, GUILD, ticked=(SEWERS,))
    before = bytes(target.ram)
    pick(window, SEWERS)
    window.fasttravel_bar.button.click()
    assert window.fasttravel_bar.fasttravel.trip is not None
    assert bytes(target.ram) != before
    return window, target, before


def test_a_wrong_game_while_a_trip_is_armed_puts_it_back(lengths):
    from automap.area import NOT_OURS
    window, target, before = armed(lengths)
    window.mapper.title_check = NOT_OURS
    window._refresh_roster()
    bar = window.fasttravel_bar
    assert bytes(target.ram) == before
    assert bar.fasttravel.trip is None and bar.fasttravel.back is None
    assert bar.unsupported


def test_attaching_nothing_while_a_trip_is_armed_puts_it_back(lengths):
    window, target, before = armed(lengths)
    window.fasttravel_bar.attach(None)
    assert bytes(target.ram) == before
    assert window.fasttravel_bar.fasttravel.trip is None


def test_leaving_the_amiga_while_a_trip_is_armed_puts_it_back(lengths):
    window, target, before = armed(lengths)
    window.mapper.target = MemoryTarget(c64_memory())
    window._refresh_roster()
    assert bytes(target.ram) == before


def test_an_unreadable_machine_leaves_the_writes_and_says_so(lengths, caplog):
    import logging
    window, target, before = armed(lengths)
    target.fail_at.add(BASE + trips.ROWS[CURSE].area)
    with caplog.at_level(logging.WARNING, logger="wish.automap.fasttravel"):
        window.fasttravel_bar.attach(None)
    assert window.fasttravel_bar.fasttravel.trip is None
    assert bytes(target.ram) != before
    assert any("left in the game" in r.getMessage() for r in caplog.records)


def test_a_trip_that_fired_is_not_put_back_when_dropped(lengths):
    window, target, _ = armed(lengths)
    tick_away(target, CURSE, SEWERS)
    window.fasttravel_bar.attach(None)
    assert window.fasttravel_bar.fasttravel.trip is None
    assert target.ram[BASE - SLOW + trips.ROWS[CURSE].area] == SEWERS


# -- the C64's two-hop trip does not survive a visit to the Amiga ----------------

def test_a_c64_two_hop_trip_is_forgotten_when_an_amiga_attaches(lengths):
    window = window_on(MemoryTarget(c64_memory()))
    c64_action = window.fasttravel_bar.fasttravel
    c64_action.pending = object()
    amiga_target = FakeAmiga(c64_memory(), CURSE)
    lay_party(amiga_target, CURSE, mode=trips.ROWS[CURSE].world_mode)
    at_world_menu(amiga_target, CURSE, GUILD)
    window.disks = "disks"
    window.mapper.target = amiga_target
    window._refresh_roster()
    assert c64_action.pending is None
    window.mapper.target = MemoryTarget(c64_memory())
    window._refresh_roster()
    assert window.fasttravel_bar.fasttravel is c64_action
    assert c64_action.pending is None


@pytest.mark.parametrize("title", ["Curse of the Azure Bonds",
                                   "Secret of the Silver Blades"])
def test_a_c64_back_watches_for_the_attached_titles_area(title):
    """Area 0x21 is an area in each of these titles and means something else
    (or nothing) in Pool of Radiance's table."""
    watched = []
    back = SimpleNamespace(area=0x21)
    stub = SimpleNamespace(
        title=title, _amiga=False, target=object(),
        fasttravel=SimpleNamespace(
            back=back, back_verdict=None,
            apply_back=lambda target: engine.Outcome(True, "ok")),
        _asked=lambda call, *args: engine.Verdict(True),
        _idle_poll=lambda: None,
        _ready=lambda verdict: verdict,
        _expect=watched.append,
        _report=lambda *args: None)
    assert actionbar.FastTravelBar.run_back(stub).ok
    assert watched == [engine.area_by_id(0x21, title)]
    assert watched[0] is not None


def test_the_back_tooltip_opens_with_a_capital(lengths):
    window, _ = attached(CURSE, GUILD, ticked=(TILVERTON, GUILD))
    tip = window.fasttravel_bar.back_button.toolTip()
    assert tip and tip[0].isupper()


def test_the_combo_and_go_button_tooltips_open_with_a_capital(lengths):
    window, _ = attached(CURSE, GUILD, ticked=(TILVERTON, GUILD))
    bar = window.fasttravel_bar
    pick(window, GUILD)
    assert bar.button.toolTip()[0].isupper()
    bar.attach_unsupported("not this game")
    assert bar.combo.toolTip()[0].isupper()


def test_the_combo_gate_tooltip_opens_with_a_capital(lengths):
    window, target = attached(CURSE, GUILD, ticked=(SEWERS,))
    target.fail_at.add(BASE + trips.ROWS[CURSE].mode)
    window.fasttravel_bar.refresh()
    assert window.fasttravel_bar.combo.toolTip()[0].isupper()
