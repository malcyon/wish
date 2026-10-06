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

    geo_blob = None

    def geo(self):
        return self.geo_blob


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


def test_an_unconfirmed_title_is_held(disks):
    """Silver Blades has no menu text read yet, so its row is unconfirmed."""
    verdict = travel(BLADES).legality(Machine(), area(7))
    assert not verdict
    assert verdict.reason == amigaactions.unsupported(
        aft.amiga.MACHINES[BLADES].title)


def test_curse_trips_into_tilverton_are_offered(disks):
    """Both a Fast Travel from the sewers and a Return from Tilverton's own
    neighbour were held on the opening replaying; the came-from write
    lifts that."""
    assert not trips.ROWS[CURSE].differences
    assert travel().legality(machine(CURSE), area(1))
    assert travel().legality(machine(CURSE, area=3), area(1))
    t = aft.AmigaFastTravel(CURSE, object())
    t._row = lambda id: area(id, "Tilverton")
    m = machine(CURSE, area=3)
    assert t.apply(m, area(1, arrival=(1, 2, 0))).ok
    assert finish(t, m, CURSE, 1) is None
    # Out of Tilverton and back: the Return goes into area 1.
    t = aft.AmigaFastTravel(CURSE, object())
    t._row = lambda id: area(id, "Tilverton")
    m = machine(CURSE, area=1)
    assert t.apply(m, area(7, arrival=(1, 1, 0))).ok
    assert finish(t, m, CURSE, 7) is None
    assert t.apply_back(m).ok


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
    held = trips.Difference("held", "a made-up open question",
                            lambda here, to, back: to == 1)
    monkeypatch.setitem(trips.ROWS, CURSE,
                        dataclasses.replace(row, differences=(held,)))
    assert not travel().legality(machine(CURSE), area(1))
    decided = (dataclasses.replace(held, offered=True),)
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


def test_an_area_the_disks_have_no_script_for_is_held_and_never_armed(disks):
    m = machine(CURSE)
    del disks[3]
    t = travel()
    verdict = t.legality(m, area(3))
    assert not verdict and verdict.reason == t.not_built
    assert t.legality(m, area(2))


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


# -- doors, on Pool of Radiance ----------------------------------------------

from automap import (
    amigaparty,  # noqa: E402
    fasttravel,  # noqa: E402
)

WINDOW = 0x40000
PORT = 0x40100
POOL_ENTRY = 0xA000
#: What `entry_words` reads on the fixture: the entry, then four zero words.
POOL_WORDS = POOL_ENTRY.to_bytes(2, "big") + bytes(8)
DOOR_NAME = "Phlan"
BOAT_EXIT = b"".join(trips.boat_exit_groups())


@pytest.fixture
def pool_gate(monkeypatch):
    """The world menu's gadgets are not laid out here; the gate reads true."""
    monkeypatch.setattr(trips, "gate", lambda target, row: True)


def pool(area_id=13, entry=POOL_ENTRY):
    row = trips.ROWS[POOL]
    m = Machine()
    m.geo_blob = bytes(1024)
    m.at(row.buffer_pointer, struct.pack(">I", BUFFER - row.buffer_bias))
    m.at(row.area, bytes([area_id]))
    m.at(row.mode, bytes([row.world_mode]))
    m.at(row.step_entry, entry.to_bytes(2, "big"))
    m.at(row.window_pointer, struct.pack(">I", WINDOW))
    m.memory[WINDOW + trips.WINDOW_USERPORT:WINDOW + trips.WINDOW_USERPORT + 4] = \
        struct.pack(">I", PORT)
    take_key(m)
    return m


def take_key(m):
    m.memory[PORT + trips.PORT_LIST:PORT + trips.PORT_LIST + 12] = \
        trips.empty_list(PORT)


def key_waiting(m):
    return m.read(PORT + trips.PORT_LIST, 12) != trips.empty_list(PORT)


def clear_buffer(m):
    m.memory[BUFFER + 0x1000:BUFFER + trips.BUFFER_SIZE] = bytes(
        trips.BUFFER_SIZE - 0x1000)


def stood(m):
    return trips.square(m, trips.ROWS[POOL])


def pool_travel(monkeypatch, offered=()):
    """Pool's differences, less the ones named in `offered`."""
    row = trips.ROWS[POOL]
    monkeypatch.setitem(trips.ROWS, POOL, dataclasses.replace(
        row, differences=tuple(d for d in row.differences
                               if d.name not in offered)))
    t = aft.AmigaFastTravel(POOL, object())
    t._row = lambda id: area(id, DOOR_NAME)
    return t


def test_a_direct_door_stands_on_the_square_sends_the_key_and_says_the_c64_sentence(
        disks, pool_gate, monkeypatch):
    m = pool(13)
    t = pool_travel(monkeypatch)
    out = t.run(m, area(27, "Wilderness"))
    assert out.ok
    assert out.message == engine.FastTravel.WALKING_OUT_DIRECT.format(
        name="Wilderness")
    assert not out.message.startswith("Traveling to")
    assert stood(m) == (6, 15, 2) and key_waiting(m)
    assert t.pending is None and t.trip.door and t.trip.hop is None
    assert (t.back.area, t.back.square) == (13, (0, 0, 0))


def test_a_new_trip_supersedes_a_hop_still_waiting(disks, pool_gate, monkeypatch):
    m = pool(13)
    t = pool_travel(monkeypatch)
    t.pending = aft._Hop(7, 5, area(9), None, POOL_WORDS, deadline=1e18)
    assert t.run(m, area(27)).ok
    assert t.pending is None


def test_a_door_key_not_taken_in_time_is_put_back_and_return_is_forgiven(
        disks, pool_gate, monkeypatch):
    m = pool(13)
    before = bytes(m.memory)
    t = pool_travel(monkeypatch)
    t.back = engine.Waypoint(2, None, (1, 1, 0))
    previous = t.back
    t.run(m, area(27))
    t.trip.deadline = 0.0
    out = t.continue_pending(m)
    assert not out.ok and out.message == aft.NOT_HAPPENED
    assert bytes(m.memory) == before
    assert t.trip is None and t.back == previous


def test_a_direct_door_is_finished_once_its_key_is_taken(disks, pool_gate, monkeypatch):
    m = pool(13)
    t = pool_travel(monkeypatch)
    t.run(m, area(27))
    assert t.continue_pending(m) is None and t.trip is not None
    take_key(m)
    assert t.continue_pending(m) is None
    assert t.trip is None and t.pending is None
    assert t.back.area == 13


def test_a_door_answered_no_leaves_nothing_in_the_buffer_to_block_the_next_trip(
        disks, pool_gate, monkeypatch):
    m = pool(13)
    t = pool_travel(monkeypatch)
    t.run(m, area(27))
    take_key(m)                    # the game took the key, and the area stayed
    t.continue_pending(m)
    at, message = trips.layout(trips.ROWS[POOL], 0)
    assert m.read(BUFFER + message, trips.MESSAGE_SIZE) == bytes(trips.MESSAGE_SIZE)
    assert t.run(m, area(27)).ok


def _hop_trip(monkeypatch, entry=POOL_ENTRY):
    """Valjevo Castle (7): the door out of it that cannot fight leads to 5."""
    m = pool(7, entry)
    t = pool_travel(monkeypatch)
    out = t.run(m, area(9, "Far place", arrival=(1, 2, 0)), arrival=(1, 2, 0))
    return m, t, out


def test_a_two_hop_walks_out_of_the_chosen_door_and_sets_a_pending_hop(
        disks, pool_gate, monkeypatch):
    m, t, out = _hop_trip(monkeypatch)
    assert out.ok and out.message == engine.FastTravel.WALKING_OUT_DETOUR.format(
        name="Far place")
    assert stood(m) == (5, 7, 3) and key_waiting(m)
    assert t.trip.hop.through == 5 and t.trip.hop.entry == m.read(
        BASE + trips.ROWS[POOL].step_entry, 2 * trips.ENTRY_WORDS)
    take_key(m)
    assert t.continue_pending(m) is None
    assert t.trip is None and t.pending.through == 5


def _through(m, t, new_entry=None):
    take_key(m)
    t.continue_pending(m)
    m.at(trips.ROWS[POOL].area, bytes([5]))
    clear_buffer(m)
    if new_entry is not None:
        m.at(trips.ROWS[POOL].step_entry, new_entry.to_bytes(2, "big"))


def test_the_second_hop_waits_until_the_step_entry_word_changes(
        disks, pool_gate, monkeypatch):
    m, t, _ = _hop_trip(monkeypatch)
    _through(m, t)
    # The area byte already reads 5, but 5's script has not run yet.
    assert t.continue_pending(m) is None and t.trip is None
    assert t.pending is not None
    m.at(trips.ROWS[POOL].step_entry, (POOL_ENTRY + 2).to_bytes(2, "big"))
    out = t.continue_pending(m)
    assert out.ok and out.message == "Traveling to Far place."
    assert trips.newecl(9) in b"".join(d for _a, d in out.writes)
    assert t.pending is None and t.trip is not None and not t.trip.door
    assert t.back.area == 7                    # Return goes to where it began


def _second_hop(monkeypatch, start, through, to):
    """A two-hop from `start` to `to`, taken to the point where the second
    hop has armed its statements."""
    m = pool(start)
    t = pool_travel(monkeypatch)
    t.run(m, area(to, "Far place", arrival=(9, 14, 2)), arrival=(9, 14, 2))
    assert t.trip.hop.through == through
    take_key(m)
    t.continue_pending(m)
    m.at(trips.ROWS[POOL].area, bytes([through]))
    clear_buffer(m)
    m.at(trips.ROWS[POOL].step_entry, (POOL_ENTRY + 2).to_bytes(2, "big"))
    return t.continue_pending(m)


def test_a_second_hop_off_a_grid_window_runs_the_prologue_first(
        disks, pool_gate, monkeypatch):
    out = _second_hop(monkeypatch, 13, 27, 0)
    assert out.ok
    statements = next(d for _a, d in out.writes if BOAT_EXIT in d)
    assert statements.startswith(BOAT_EXIT) and statements.endswith(
        trips.newecl(0))


def test_a_second_hop_that_stays_off_the_grid_has_no_prologue(
        disks, pool_gate, monkeypatch):
    out = _second_hop(monkeypatch, 7, 5, 9)
    assert out.ok and BOAT_EXIT not in b"".join(d for _a, d in out.writes)


def test_a_leg_the_prologue_alone_pushes_past_its_script_is_held_up_front(
        disks, pool_gate, monkeypatch):
    # Window 27's script fits the trip without the boat-exit prologue and not
    # with it.
    disks[27] = 7573
    m = pool(13)
    before = bytes(m.memory)
    t = pool_travel(monkeypatch)
    out = t.run(m, area(0))
    assert not out.ok and out.message == t.not_built
    assert bytes(m.memory) == before and t.trip is None


def test_a_direct_trip_from_a_window_and_a_return_stay_held(
        disks, pool_gate, monkeypatch):
    t = pool_travel(monkeypatch)
    assert t.legality(pool(26), area(0)).reason == t.not_built
    t.back = engine.Waypoint(0, None, (1, 1, 0))
    assert not t.legality(pool(26), area(0), back=True)


def test_every_door_able_to_fight_makes_the_script_trip_the_menu_offered(
        disks, pool_gate, monkeypatch):
    fight = fasttravel.ExitRoute(1, (3, 8), combat=True)
    monkeypatch.setattr(fasttravel, "EXIT_ROUTES", {(7, 0): fight, (7, 3): fight})
    m = pool(7)
    t = pool_travel(monkeypatch)
    assert t.legality(m, area(9))
    out = t.run(m, area(9))
    assert out.ok and t.trip is not None and not t.trip.door
    assert trips.newecl(9) in b"".join(d for _a, d in out.writes)


def test_kovel_takes_the_26_door_when_the_24_door_leaves_no_room_for_the_second_leg(
        disks, pool_gate, monkeypatch):
    disks[24] = trips.BUFFER_SIZE - 26   # 26 free bytes: no room for a trip
    m = pool(14)
    t = pool_travel(monkeypatch)
    to = area(0, "New Phlan", arrival=(1, 2, 0))
    assert t.legality(m, to)
    out = t.run(m, to, arrival=(1, 2, 0))
    assert out.ok and t.trip.hop.through == 26


def test_kovel_trips_are_held_when_no_door_can_make_the_second_leg(
        disks, pool_gate, monkeypatch):
    disks[24] = trips.BUFFER_SIZE - 26
    disks[26] = trips.BUFFER_SIZE - 26
    m = pool(14)
    before = bytes(m.memory)
    t = pool_travel(monkeypatch)
    assert t.legality(m, area(0)).reason == t.not_built
    out = t.run(m, area(0))
    assert not out.ok and bytes(m.memory) == before and t.trip is None


def test_a_door_that_can_make_the_trip_is_kept_though_unproven_and_stays_held(
        disks, pool_gate, monkeypatch):
    m = pool(2)
    t = pool_travel(monkeypatch)
    assert t.legality(m, area(0)).reason == t.not_built
    # The proven door out of area 2 is not swapped in for it.
    assert trips.door_route(trips.ROWS[POOL], 2, 0, disks)[0] == 15


@pytest.mark.parametrize("here, to", [
    (26, 0), (27, 13),                          # a grid window
    (21, 0), (2, 18),                           # a stand nobody has run
    (0, 8),                                     # entry 1, no facing known
])
def test_a_grid_departure_and_an_unplaced_door_stay_held(
        disks, pool_gate, monkeypatch, here, to):
    m = pool(here)
    t = aft.AmigaFastTravel(POOL, object())
    t._row = lambda id: area(id, DOOR_NAME)
    assert t.legality(m, area(to)).reason == t.not_built


def test_a_proven_door_is_offered(disks, pool_gate):
    m = pool(13)
    t = aft.AmigaFastTravel(POOL, object())
    t._row = lambda id: area(id, DOOR_NAME)
    assert t.legality(m, area(27))


def test_return_makes_the_normal_trip_even_from_an_area_with_doors(
        disks, pool_gate, monkeypatch):
    m = pool(13)
    t = pool_travel(monkeypatch, offered=("return_landing",))
    t.back = engine.Waypoint(2, None, (1, 1, 0))
    out = t.apply_back(m)
    assert out.ok and out.message == "travelled back to " + DOOR_NAME
    assert not t.trip.door
    assert trips.newecl(2) in b"".join(d for _a, d in out.writes)


def _pending_hop(monkeypatch, area_now):
    m = pool(7)
    t = pool_travel(monkeypatch)
    t.pending = aft._Hop(7, 5, area(9, "Far place"), None,
                         POOL_WORDS, deadline=1e18)
    m.at(trips.ROWS[POOL].area, bytes([area_now]))
    return m, t


def test_a_fight_in_the_first_area_extends_the_wait(disks, monkeypatch):
    m, t = _pending_hop(monkeypatch, 7)
    t.pending.deadline = 0.0
    m.at(trips.ROWS[POOL].mode, bytes([amigaparty.ROWS[POOL].combat_value]))
    assert t.continue_pending(m) is None
    assert t.pending.deadline > 1.0


def test_a_party_that_never_leaves_hears_the_c64_sentence_at_the_deadline(
        disks, monkeypatch):
    m, t = _pending_hop(monkeypatch, 7)
    t.pending.deadline = 0.0
    out = t.continue_pending(m)
    assert not out.ok
    assert out.message == engine.FastTravel.NEVER_LEFT.format(name="Far place")
    assert t.pending is None


def test_a_party_that_leaves_by_another_door_is_told_and_return_is_forgotten(
        disks, monkeypatch):
    m, t = _pending_hop(monkeypatch, 0)         # 7 -> 0 is another of its doors
    t.back = engine.Waypoint(7, None, (1, 1, 0))
    out = t.continue_pending(m)
    assert not out.ok
    assert out.message == engine.FastTravel.LEFT_ANOTHER_WAY.format(name="Far place")
    assert t.pending is None and t.back is None


def test_a_party_that_comes_back_drops_the_hop_silently(disks, monkeypatch):
    m, t = _pending_hop(monkeypatch, 5)
    assert t.continue_pending(m) is None and t.pending is not None
    m.at(trips.ROWS[POOL].area, bytes([7]))
    assert t.continue_pending(m) is None and t.pending is None


def test_a_party_in_some_other_area_drops_the_hop_silently(disks, monkeypatch):
    m, t = _pending_hop(monkeypatch, 14)
    assert t.continue_pending(m) is None and t.pending is None


def test_the_second_hop_is_made_when_only_a_later_entry_word_changes(
        disks, pool_gate, monkeypatch):
    # Areas 14 and 27 share the first word, 0x9914, and differ in the rest.
    m, t, _ = _hop_trip(monkeypatch)
    _through(m, t)
    assert t.continue_pending(m) is None and t.pending is not None
    m.at(trips.ROWS[POOL].step_entry + 2, b"\x99\x40")
    out = t.continue_pending(m)
    assert out.ok and out.message == "Traveling to Far place."
    assert t.pending is None and t.trip is not None


def test_a_hop_whose_step_entry_never_changes_clears_after_the_deadline(
        disks, pool_gate, monkeypatch):
    m, t, _ = _hop_trip(monkeypatch)
    _through(m, t)
    assert t.continue_pending(m) is None and t.pending is not None
    t.pending.deadline = 0.0
    assert t.continue_pending(m) is None and t.pending is None
    m.at(trips.ROWS[POOL].step_entry, (POOL_ENTRY + 2).to_bytes(2, "big"))
    assert t.continue_pending(m) is None and t.trip is None


def test_return_never_goes_through_the_door_path(disks, pool_gate, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("Return reached the door path")
    m = pool(14)
    t = pool_travel(monkeypatch, offered=("return_landing",))
    monkeypatch.setattr(t, "_run_door", boom)
    monkeypatch.setattr(trips, "door_leg_held", boom)
    t.back = engine.Waypoint(0, None, (1, 1, 0))
    assert t.apply_back(m).ok
    assert not t.trip.door
