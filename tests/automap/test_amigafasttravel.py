"""Amiga Fast Travel and Return, on the real trip table and a fake machine."""

import dataclasses
import logging
import struct
from types import SimpleNamespace

import pytest

from automap import actions as engine
from automap import amiga, amigaactions
from automap import amigafasttravel as aft
from automap import amigatrip as trips
from automap.target import NotConnected

CURSE = "curse-of-the-azure-bonds"
POD = "pools-of-darkness"
POOL = "pool-of-radiance"
BLADES = "secret-of-the-silver-blades"
UNSUPPORTED = "ERROR: Action unsupported on Curse of the Azure Bonds (Amiga)."
BASE = 0x10000
BUFFER = 0x30000
ENTRY = 0x8137
SMALL = 0x100


class Machine:
    """A flat memory with a data hunk at `BASE`: what `AmigaTarget` offers
    `amigatrip`, plus `can_write`."""

    can_write = True
    data_base = BASE

    def __init__(self):
        self.memory = bytearray(0x50000)
        self.fail_write = False
        #: An address whose write raises, and what runs after any later write.
        self.fail_at = None
        self.on_write = None

    def read(self, addr, length):
        return bytes(self.memory[addr:addr + length])

    def read_blocks(self, blocks):
        return [self.read(a, n) for a, n in blocks]

    def write(self, addr, data, verify=True):
        if self.fail_write or addr == self.fail_at:
            raise NotConnected("the emulator went away")
        self.memory[addr:addr + len(data)] = data
        if self.on_write is not None:
            self.on_write(addr, bytes(data))

    def at(self, offset, data):
        self.memory[BASE + offset:BASE + offset + len(data)] = data


def machine(key, area=5, stale=False):
    """A title at its world menu in `area`; the script is made up."""
    row = trips.ROWS[key]
    m = Machine()
    m.memory[BUFFER:BUFFER + 0x1000] = b"\xee" * 0x1000
    if stale:
        m.memory[BUFFER + 0x1000:BUFFER + trips.BUFFER_SIZE] = (
            b"\x77" * (trips.BUFFER_SIZE - 0x1000))
    m.at(row.buffer_pointer, struct.pack(">I", BUFFER - row.buffer_bias))
    m.at(row.area, bytes([area]))
    m.at(row.mode, bytes([row.world_mode]))
    m.at(row.step_entry, ENTRY.to_bytes(2, "big"))
    m.at(row.menu_kind, b"\x00\x01")
    m.at(row.menu_at, row.menu_text + b"\0")
    m.at(row.key_buffer, b"\x00\x0d")
    return m


def area(id, name="Shadowdale", **kw):
    return SimpleNamespace(id=id, name=name, **kw)


@pytest.fixture
def disks(monkeypatch):
    """Every area's script is 0x1000 bytes long, so every tail is free."""
    table = {i: 0x1000 for i in range(0x80)}
    monkeypatch.setattr(trips, "script_lengths", lambda row, d: dict(table))
    return table


def travel(key=CURSE, disks_=object()):
    t = aft.AmigaFastTravel(key, disks_)
    t._row = lambda id: area(id, "Tilverton")
    return t


def finish(t, m, key, new_area):
    """The game changes area; the poll sees it."""
    row = trips.ROWS[key]
    m.at(row.area, bytes([new_area]))
    m.at(row.key_buffer, b"\x00\x0d")      # the game took the key
    if row.clears_buffer:                  # and the loader cleared the buffer
        m.memory[BUFFER + 0x1000:BUFFER + trips.BUFFER_SIZE] = bytes(
            trips.BUFFER_SIZE - 0x1000)
    return t.continue_pending(m)


def test_an_offered_trip_arms_and_says_the_c64_sentence(disks):
    m = machine(CURSE)
    before = bytes(m.memory)
    out = travel().apply(m, area(7, arrival=(1, 2, 0)))
    assert out.ok and out.message == "Traveling to Shadowdale."
    assert out.writes and bytes(m.memory) != before
    assert m.read(BASE + trips.ROWS[CURSE].key_buffer, 2) == trips.FORWARD_KEY


def test_tilverton_is_held_and_so_is_an_unconfirmed_title(disks):
    """Curse's Tilverton waits on a decision; Silver Blades has no menu text
    read yet, so its row is unconfirmed."""
    for key, to, m in ((CURSE, 1, machine(CURSE)), (BLADES, 7, Machine())):
        verdict = travel(key).legality(m, area(to))
        assert not verdict
        assert verdict.reason == amigaactions.unsupported(
            aft.amiga.MACHINES[key].title)


def test_return_is_offered_on_curse_and_held_on_pools_of_darkness(disks):
    for key in (CURSE, POD):
        m = machine(key)
        t = aft.AmigaFastTravel(key, object())
        t._row = lambda id: area(id, "Tilverton")
        assert t.apply(m, area(0x30 if key == POD else 7,
                               arrival=(1, 1, 0))).ok
        assert finish(t, m, key, 0x30 if key == POD else 7) is None
        out = t.apply_back(m)
        if key == CURSE:
            assert out.ok
            continue
        assert not out.ok
        assert out.message == amigaactions.unsupported(
            aft.amiga.MACHINES[key].title)


def test_a_decided_difference_is_offered(disks, monkeypatch):
    row = trips.ROWS[CURSE]
    decided = tuple(d if d.name != "tilverton" else
                    dataclasses.replace(d, offered=True)
                    for d in row.differences)
    monkeypatch.setitem(trips.ROWS, CURSE,
                        dataclasses.replace(row, differences=decided))
    assert travel().apply(machine(CURSE), area(1)).ok


def test_an_unconfirmed_row_no_disks_or_no_write_is_unsupported(disks, monkeypatch):
    m = machine(CURSE)
    assert travel(disks_=None).legality(m, area(7)).reason == UNSUPPORTED
    ro = machine(CURSE)
    ro.can_write = False
    assert travel().legality(ro, area(7)).reason == UNSUPPORTED
    monkeypatch.delitem(trips.ROWS, CURSE)
    assert travel().legality(m, area(7)).reason == UNSUPPORTED


def test_a_tier_three_area_is_unsupported(disks):
    disks[5] = 0x1DF8
    out = travel().apply(machine(CURSE), area(7))
    assert not out.ok and out.message == UNSUPPORTED


def test_a_trip_the_title_has_no_target_for_is_unsupported(disks):
    out = travel().apply(machine(CURSE), area(7, outdoors=True, overland=(1, 1)))
    assert not out.ok and out.message == UNSUPPORTED


def test_the_disks_are_read_once(disks, monkeypatch):
    calls = []
    monkeypatch.setattr(trips, "script_lengths",
                        lambda row, d: calls.append(1) or dict(disks))
    t = travel()
    m = machine(CURSE)
    t.legality(m, area(7))
    t.legality(m, area(8))
    assert len(calls) == 1


def test_the_c64_sentences_are_reused(disks):
    t = travel()
    m = machine(CURSE)
    assert t.legality(None, area(7)).reason == engine.NO_EMULATOR
    shut = machine(CURSE)
    shut.at(trips.ROWS[CURSE].menu_kind, b"\x00\x00")
    assert t.legality(shut, area(7)).reason == engine.FASTTRAVEL_BUSY
    assert t.legality(m, None).reason == "choose an area"
    assert t.legality(m, area(5)).reason == "the party is already in that area"
    assert t.legality(m, area(9, fasttravelable=False)).reason == (
        engine.FastTravel.ATTRACT_TRAP)
    assert t.back_verdict(m).reason.startswith("nothing to go back to")
    assert aft.NOT_HAPPENED is engine.FASTTRAVEL_FAILED
    assert (t.name, t.label) == ("fasttravel", "Fast Travel")
    assert t.game is None and t.addresses is None


def test_an_unreadable_area_is_unsupported_and_never_armed(disks, monkeypatch):
    monkeypatch.setattr(trips, "area_id", lambda target, row: None)
    armed = []
    monkeypatch.setattr(trips, "arm", lambda *a: armed.append(a))
    t = travel()
    m = machine(CURSE)
    assert t.legality(m, area(7)).reason == UNSUPPORTED
    assert t.apply(m, area(7)).message == UNSUPPORTED
    assert not armed


def test_return_is_recognised_by_a_waypoints_area(disks):
    m = machine(CURSE, area=7)
    t = travel()
    t.back = engine.Waypoint(5, None, (1, 1, 0))
    t._row = lambda id: None
    assert t.back_verdict(m)
    assert t.legality(m, SimpleNamespace(area=7)).reason == (
        "the party is already in that area")


def test_when_the_area_byte_changes_the_trip_is_tidied_silently(disks):
    key = POD
    m = machine(key, area=0x15, stale=True)
    t = travel(key)
    assert t.apply(m, area(0x30, arrival=(1, 1, 0))).ok
    statements = BUFFER + trips.BUFFER_SIZE - 21
    assert m.read(statements, 21) != bytes(21)
    disks[0x30] = 0x1000
    assert finish(t, m, key, 0x30) is None
    assert m.read(statements, 21) == bytes(21)
    assert t.trip is None and t.back is not None


def test_when_it_does_not_change_the_trip_is_put_back(disks, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(aft.time, "monotonic", lambda: now[0])
    m = machine(CURSE)
    before = bytes(m.memory)
    t = travel()
    t.apply(m, area(7))
    assert bytes(m.memory) != before
    assert t.continue_pending(m) is None
    now[0] += aft.FIRE_SECONDS + 0.1
    out = t.continue_pending(m)
    assert not out.ok and out.message == aft.NOT_HAPPENED
    assert bytes(m.memory) == before
    assert t.back is None and t.trip is None


def test_an_area_that_changed_just_before_the_put_back_is_tidied(disks, monkeypatch):
    """`fired` says not yet; `disarm` finds the area has changed after all."""
    now = [100.0]
    monkeypatch.setattr(aft.time, "monotonic", lambda: now[0])
    key = POD
    m = machine(key, area=0x15, stale=True)
    t = travel(key)
    t.apply(m, area(0x30, arrival=(1, 1, 0)))
    real = trips.fired
    calls = []

    def first_blind(target, armed):
        calls.append(1)
        return None if len(calls) == 1 else real(target, armed)

    monkeypatch.setattr(trips, "fired", first_blind)
    m.at(trips.ROWS[key].area, b"\x30")
    now[0] += aft.FIRE_SECONDS + 0.1
    assert t.continue_pending(m) is None
    assert t.trip is None and t.back is not None
    assert m.read(BUFFER + trips.BUFFER_SIZE - 21, 21) == bytes(21)
    monkeypatch.setattr(trips, "fired", real)


def test_a_failed_return_keeps_the_waypoint(disks, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(aft.time, "monotonic", lambda: now[0])
    monkeypatch.setitem(trips.ROWS, CURSE, dataclasses.replace(
        trips.ROWS[CURSE], differences=()))
    t = travel()
    m = machine(CURSE)
    t.apply(m, area(7))
    finish(t, m, CURSE, 7)
    t.apply_back(m)
    now[0] += 10
    t.continue_pending(m)
    assert t.back is not None and t.back.area == 5


def test_a_pending_trip_holds_every_other_trip(disks):
    t = travel()
    m = machine(CURSE)
    assert t.apply(m, area(7)).ok
    for out in (t.apply(m, area(8)), t.run(m, area(8)), t.apply_back(m)):
        assert not out.ok and out.message == engine.FASTTRAVEL_BUSY
    assert t.legality(m, area(8)).reason == engine.FASTTRAVEL_BUSY
    finish(t, m, CURSE, 7)
    assert t.apply(m, area(8)).ok


def test_a_raising_disarm_keeps_the_trip_and_logs_a_warning(disks, monkeypatch, caplog):
    now = [100.0]
    monkeypatch.setattr(aft.time, "monotonic", lambda: now[0])
    t = travel()
    m = machine(CURSE)
    t.apply(m, area(7))
    real = trips.disarm

    def boom(target, armed):
        raise NotConnected("gone")

    monkeypatch.setattr(trips, "disarm", boom)
    now[0] += aft.FIRE_SECONDS + 1
    with caplog.at_level(logging.WARNING, logger="wish.automap.amigafasttravel"):
        assert t.continue_pending(m) is None
    assert t.trip is not None
    assert any(r.levelname == "WARNING" for r in caplog.records)
    monkeypatch.setattr(trips, "disarm", real)
    assert t.continue_pending(m).message == aft.NOT_HAPPENED
    assert t.trip is None


def test_a_write_error_while_arming_reports_the_failure(disks, caplog):
    m = machine(CURSE)
    before = bytes(m.memory)
    m.fail_write = True
    t = travel()
    with caplog.at_level(logging.WARNING):
        out = t.apply(m, area(7))
    assert not out.ok and out.message == aft.NOT_HAPPENED
    assert t.trip is None and t.back is None and bytes(m.memory) == before


def test_an_arm_that_raises_is_reported_and_logged(disks, monkeypatch, caplog):
    def boom(target, row, plan):
        raise RuntimeError("could not put back")

    monkeypatch.setattr(trips, "arm", boom)
    t = travel()
    with caplog.at_level(logging.WARNING, logger="wish.automap.amigafasttravel"):
        out = t.apply(machine(CURSE), area(7))
    assert out.message == aft.NOT_HAPPENED and t.trip is None
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_an_error_reading_the_area_waits_for_the_deadline(disks, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(aft.time, "monotonic", lambda: now[0])
    t = travel()
    m = machine(CURSE)
    t.apply(m, area(7))

    real = trips.fired
    calls = []

    def boom_once(target, armed):
        calls.append(1)
        if len(calls) == 1:
            raise NotConnected("gone")
        return real(target, armed)

    monkeypatch.setattr(trips, "fired", boom_once)
    assert t.continue_pending(m) is None
    now[0] += aft.FIRE_SECONDS + 1
    assert t.continue_pending(m).message == aft.NOT_HAPPENED


def test_an_error_while_tidying_still_ends_the_trip(disks, monkeypatch):
    def boom(*a):
        raise NotConnected("gone")

    monkeypatch.setattr(trips, "tidy", boom)
    t = travel()
    m = machine(CURSE)
    t.apply(m, area(7))
    assert finish(t, m, CURSE, 7) is None
    assert t.trip is None


def test_a_trip_the_game_took_during_a_failed_arm_is_in_progress(disks):
    """The key write fails; while the earlier writes are put back the game
    changes area. `arm` returns the `Armed` and the trip is pending, not
    failed."""
    row = trips.ROWS[CURSE]
    m = machine(CURSE)
    m.fail_at = BASE + row.key_buffer

    def game_takes_it(addr, data):
        m.memory[BASE + row.area] = 7

    m.on_write = game_takes_it
    t = travel()
    out = t.apply(m, area(7, arrival=(1, 2, 0)))
    assert out.ok and out.message == "Traveling to Shadowdale."
    assert t.trip is not None and t.back is not None
    assert t.continue_pending(m) is None and t.trip is None
    assert t.back is not None


@pytest.mark.parametrize("key", [CURSE, POD])
def test_a_disarm_that_finds_the_area_changed_tidies(disks, monkeypatch, key):
    """`disarm` False means the trip happened: tidy runs and nothing is
    reported or restored."""
    now = [100.0]
    monkeypatch.setattr(aft.time, "monotonic", lambda: now[0])
    m = machine(key, area=0x15 if key == POD else 5)
    t = travel(key)
    assert t.apply(m, area(0x30, arrival=(1, 1, 0))).ok
    tidied = []
    monkeypatch.setattr(trips, "fired", lambda target, armed: None)
    monkeypatch.setattr(trips, "disarm", lambda target, armed: False)
    monkeypatch.setattr(trips, "tidy", lambda *a: tidied.append(a) or 0)
    before = t.back
    now[0] += aft.FIRE_SECONDS + 1
    assert t.continue_pending(m) is None
    assert len(tidied) == 1 and t.trip is None and t.back is before


@pytest.mark.parametrize("error", [NotConnected, amiga.GuestError])
def test_a_dropped_connection_is_an_outcome_not_an_exception(disks, monkeypatch, error):
    def drop(*a):
        raise error("gone")

    t = travel()
    m = machine(CURSE)
    monkeypatch.setattr(trips, "gate", drop)
    out = t.apply(m, area(7))
    assert not out.ok and out.message == "the machine is not readable right now"
    t.back = engine.Waypoint(5, None, (1, 1, 0))
    out = t.apply_back(m)
    assert not out.ok and out.message == "the machine is not readable right now"
    assert t.trip is None
