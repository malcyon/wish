"""Amiga Fast Travel and Return, against a fake `amigatrip` and a fake target."""

from types import SimpleNamespace

import pytest

from automap import actions as engine
from automap import amigaactions
from automap import amigafasttravel as aft

KEY = "curse-of-the-azure-bonds"
UNSUPPORTED = "ERROR: Action unsupported on Curse of the Azure Bonds (Amiga)."


class Difference:
    def __init__(self, pairs=(), back=None, offered=False):
        self.pairs, self.back, self.offered = set(pairs), back, offered

    def covers(self, here, to, back):
        return (here, to) in self.pairs and (self.back is None
                                            or self.back == back)


class Target:
    can_write = True

    def read(self, addr, length):
        raise AssertionError("a C64 address was read")


class World:
    """The fake `amigatrip`: the area byte, the gate, and a log of calls."""

    def __init__(self):
        self.row = SimpleNamespace(confirmed=True, differences=())
        self.ROWS = {KEY: self.row}
        self.here = 3
        self.open = True
        self.tier = 1
        self.fires = True
        self.log = []

    def gate(self, target, row):
        return self.open

    def area_id(self, target, row):
        return self.here

    def square(self, target, row):
        return (4, 5, 2)

    def overland(self, target, row):
        return None

    def free_tail(self, row, area, disks):
        self.log.append(("free_tail", area))
        return self.tier

    def plan(self, area, square, overland, tier):
        return SimpleNamespace(area=area, square=square, overland=overland,
                               tier=tier)

    def arm(self, target, row, plan):
        self.log.append(("arm", plan.area, plan.square, plan.tier))
        return SimpleNamespace(plan=plan, writes=((0x10, b"\x01"),))

    def fired(self, target, armed):
        return True if self.fires else None

    def disarm(self, target, armed):
        self.log.append(("disarm",))

    def tidy(self, target, armed, new_area):
        self.log.append(("tidy", new_area))


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setattr(aft, "_trips", lambda: w)

    def no_c64(*a, **k):
        raise AssertionError("a C64 address was consulted")

    monkeypatch.setattr(engine.c64, "machine_for", no_c64)
    monkeypatch.setattr(engine, "program_counter", no_c64)
    monkeypatch.setattr(engine, "mode", no_c64)
    return w


def area(id, name="Shadowdale", **kw):
    return SimpleNamespace(id=id, name=name, **kw)


def travel():
    t = aft.AmigaFastTravel(KEY)
    t._row = lambda id: area(id, "Tilverton")
    return t


def test_an_offered_trip_arms_and_says_the_c64_sentence(world):
    out = travel().apply(Target(), area(7, arrival=(1, 2, 0)))
    assert out.ok and out.message == "Traveling to Shadowdale."
    assert ("arm", 7, (1, 2, 0), 1) in world.log
    assert out.writes == ((0x10, b"\x01"),)


def test_return_arms_the_recorded_square(world):
    t = travel()
    t.apply(Target(), area(7, arrival=(1, 2, 0)))
    world.here = 7
    t.continue_pending(Target())
    out = t.apply_back(Target())
    assert out.ok and out.message == "travelled back to Tilverton"
    assert ("arm", 3, (4, 5, 2), 1) in world.log


def test_each_of_the_five_held_trips_is_not_offered(world):
    """Return landing, Tilverton, leaving the wilderness, doors, weaker check:
    one undecided difference each, over its own pair of areas."""
    pairs = [(3, 10), (3, 11), (3, 12), (3, 13), (3, 14)]
    world.row.differences = tuple(Difference({p}) for p in pairs)
    for _, to in pairs:
        out = travel().apply(Target(), area(to))
        assert not out.ok and out.message == UNSUPPORTED
    assert not [e for e in world.log if e[0] == "arm"]
    assert travel().apply(Target(), area(7)).ok


def test_a_decided_difference_is_offered(world):
    world.row.differences = (Difference({(3, 7)}, offered=True),)
    assert travel().apply(Target(), area(7)).ok


def test_return_held_for_its_own_difference_only(world):
    world.row.differences = (Difference({(7, 3)}, back=True),)
    t = travel()
    assert t.apply(Target(), area(7)).ok
    world.here = 7
    t.continue_pending(Target())
    out = t.apply_back(Target())
    assert not out.ok and out.message == UNSUPPORTED


def test_an_unconfirmed_row_or_no_row_or_no_write_is_unsupported(world):
    world.row.confirmed = False
    assert travel().legality(Target(), area(7)).reason == UNSUPPORTED
    world.row.confirmed = True
    world.ROWS.clear()
    assert travel().legality(Target(), area(7)).reason == UNSUPPORTED
    world.ROWS[KEY] = world.row
    ro = Target()
    ro.can_write = False
    assert travel().legality(ro, area(7)).reason == UNSUPPORTED


def test_a_tier_three_area_is_unsupported(world):
    world.tier = 3
    out = travel().apply(Target(), area(7))
    assert not out.ok and out.message == UNSUPPORTED


def test_gate_and_parent_checks_keep_the_c64_sentences(world):
    t = travel()
    assert t.legality(None, area(7)).reason == engine.NO_EMULATOR
    world.open = False
    assert t.legality(Target(), area(7)).reason == engine.FASTTRAVEL_BUSY
    world.open = True
    assert t.legality(Target(), None).reason == "choose an area"
    assert t.legality(Target(), area(3)).reason == (
        "the party is already in that area")
    assert t.legality(Target(), area(9, fasttravelable=False)).reason == (
        engine.FastTravel.ATTRACT_TRAP)
    assert t.back_verdict(Target()).reason.startswith("nothing to go back to")


def test_when_the_area_byte_changes_the_trip_is_tidied_silently(world):
    t = travel()
    t.apply(Target(), area(7))
    world.here = 7
    assert t.continue_pending(Target()) is None
    assert ("tidy", 7) in world.log and ("disarm",) not in world.log
    assert t.trip is None and t.back is not None


def test_when_it_does_not_change_the_trip_is_disarmed(world, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(aft.time, "monotonic", lambda: now[0])
    world.fires = False
    t = travel()
    t.apply(Target(), area(7))
    assert t.continue_pending(Target()) is None
    now[0] += aft.FIRE_SECONDS + 0.1
    out = t.continue_pending(Target())
    assert not out.ok
    assert out.message == ("ERROR: Unable to Fast Travel. The party is back "
                           "where it started.")
    assert ("disarm",) in world.log and not [e for e in world.log if e[0] == "tidy"]
    assert t.back is None and t.trip is None


def test_a_failed_return_keeps_the_waypoint(world, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(aft.time, "monotonic", lambda: now[0])
    t = travel()
    t.apply(Target(), area(7))
    world.here = 7
    t.continue_pending(Target())
    world.fires = False
    t.apply_back(Target())
    now[0] += 10
    t.continue_pending(Target())
    assert t.back is not None and t.back.area == 3


def test_no_c64_container_is_built():
    t = aft.AmigaFastTravel(KEY)
    assert t.game is None and t.addresses is None
    assert t.not_built == amigaactions.unsupported(
        "Curse of the Azure Bonds")
    assert (t.name, t.label) == ("fasttravel", "Fast Travel")


def test_an_unreadable_area_is_unsupported_and_never_armed(world):
    world.here = None
    t = travel()
    assert t.legality(Target(), area(7)).reason == UNSUPPORTED
    assert t.apply(Target(), area(7)).message == UNSUPPORTED
    assert not [e for e in world.log if e[0] == "arm"]


def test_return_is_recognised_by_a_waypoints_area(world):
    """`Waypoint.area`, with no `id`, is what Return is held on."""
    world.here = 7
    world.row.differences = (Difference({(7, 3)}, back=True),)
    t = travel()
    t.back = engine.Waypoint(3, None, (1, 1, 0))
    t._row = lambda id: None
    assert t.back_verdict(Target()).reason == UNSUPPORTED
    world.row.differences = ()
    assert t.back_verdict(Target()).ok


def test_the_waypoint_fallback_reads_area_when_there_is_no_id(world):
    world.here = 3
    t = travel()
    assert t.legality(Target(), SimpleNamespace(area=3)).reason == (
        "the party is already in that area")


def test_a_pending_trip_holds_every_other_trip(world):
    t = travel()
    assert t.apply(Target(), area(7)).ok
    armed = [e for e in world.log if e[0] == "arm"]
    for out in (t.apply(Target(), area(8)), t.run(Target(), area(8)),
                t.apply_back(Target())):
        assert not out.ok and out.message == engine.FASTTRAVEL_BUSY
    assert t.legality(Target(), area(8)).reason == engine.FASTTRAVEL_BUSY
    assert [e for e in world.log if e[0] == "arm"] == armed
    world.here = 7
    t.continue_pending(Target())
    world.here = 7
    assert t.apply(Target(), area(8)).ok


def test_a_raising_disarm_keeps_the_trip_and_logs_a_warning(world, monkeypatch,
                                                          caplog):
    now = [100.0]
    monkeypatch.setattr(aft.time, "monotonic", lambda: now[0])
    world.fires = False
    t = travel()
    t.apply(Target(), area(7))
    before = t.back

    def boom(target, armed):
        raise OSError("write failed")

    world.disarm = boom
    now[0] += aft.FIRE_SECONDS + 1
    with caplog.at_level("WARNING", logger="wish.automap.amigafasttravel"):
        assert t.continue_pending(Target()) is None
    assert t.trip is not None and t.back is before
    assert any(r.levelname == "WARNING" for r in caplog.records)
    del world.disarm
    out = t.continue_pending(Target())
    assert out.message == aft.NOT_HAPPENED and t.trip is None


def test_a_write_error_while_arming_reports_the_failure(world, caplog):
    def boom(target, row, plan):
        raise OSError("write failed")

    world.arm = boom
    t = travel()
    with caplog.at_level("WARNING", logger="wish.automap.amigafasttravel"):
        out = t.apply(Target(), area(7))
    assert not out.ok and out.message == aft.NOT_HAPPENED
    assert t.trip is None and t.back is None
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_arm_returning_nothing_reports_the_failure(world):
    world.arm = lambda target, row, plan: None
    out = travel().apply(Target(), area(7))
    assert not out.ok and out.message == aft.NOT_HAPPENED


def test_an_error_reading_the_area_waits_for_the_deadline(world, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(aft.time, "monotonic", lambda: now[0])

    def boom(target, armed):
        raise OSError("read failed")

    world.fired = boom
    t = travel()
    t.apply(Target(), area(7))
    assert t.continue_pending(Target()) is None
    now[0] += aft.FIRE_SECONDS + 1
    assert t.continue_pending(Target()).message == aft.NOT_HAPPENED
    assert ("disarm",) in world.log


def test_an_error_while_tidying_still_ends_the_trip(world):
    def boom(target, armed, new_area):
        raise OSError("write failed")

    world.tidy = boom
    t = travel()
    t.apply(Target(), area(7))
    world.here = 7
    assert t.continue_pending(Target()) is None
    assert t.trip is None


def test_the_failure_sentence_is_the_shared_constant():
    assert aft.NOT_HAPPENED is engine.FASTTRAVEL_FAILED
