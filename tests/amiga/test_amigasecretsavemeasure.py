"""The measure mode, per-state waits, guard polling and configurable route of the recon driver."""

from __future__ import annotations

import pytest

from goldbox.amiga_adf import AmigaDisk
from tests.amiga.test_amigasecretsave import (
    FailedPostWriteGuest,
    _audio_proof,
    _prepared,
)
from tools.amiga import amigasecretsave


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        now = 1000.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

        sleeps: list = []

    c = Clock()
    c.sleeps = []
    monkeypatch.setattr(amigasecretsave.time, "monotonic", c.monotonic)
    monkeypatch.setattr(amigasecretsave.time, "sleep", c.sleep)
    return c


class ScreenGuest(FailedPostWriteGuest):
    """Screen content is the count of keys pressed, so each key changes it."""

    def __init__(self, clock, same_after=None, stuck_states=()):
        super().__init__()
        self.clock, self.presses = clock, 0
        self.same_after, self.stuck = same_after, set(stuck_states)
        self.at = []

    def press(self, holder, key, timeout=None):
        self.calls.append(("press", holder, key))
        self.presses += 1

    def capture(self, state, raw, cropped, timeout=None):
        self.calls.append(("capture", state))
        self.at.append((state, self.clock.now))
        shown = self.presses
        if self.same_after is not None and shown >= self.same_after:
            shown = self.same_after - 1
        raw.write_bytes(f"frame {shown}".encode())
        cropped.write_bytes(b"crop")


def _keys(guest):
    return [c[2] for c in guest.calls if c[0] == "press"]


def _measure(tmp_path, guest, **kw):
    return amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, holder="wish672-test",
        audio_proof=_audio_proof(tmp_path), measure=True, **kw)


def test_measure_presses_only_the_route_and_never_the_write_key(tmp_path, clock):
    guest = ScreenGuest(clock)
    result = _measure(tmp_path, guest)
    assert _keys(guest) == [k for k, _ in amigasecretsave.ROUTE]
    assert "B" not in _keys(guest)
    assert result["measure"] is True and result["success"] is True
    assert result["slot_a_unchanged"] and result["df0_unchanged"]
    assert result["slot_b_sha256"] is None


def test_measure_never_presses_a_write_key_inside_the_route(tmp_path, clock):
    guest = ScreenGuest(clock)
    route = (("RET", "version"), ("W", "sheet"), ("X", "items"))
    result = _measure(tmp_path, guest, route=route, write_keys=("w",))
    assert _keys(guest) == ["RET"]
    assert result["success"] is False


def test_measure_stops_at_an_unchanged_capture_then_still_cleans_up(tmp_path, clock):
    guest = ScreenGuest(clock, same_after=4)
    result = _measure(tmp_path, guest)
    assert len(_keys(guest)) == 4
    assert any(e.get("unchanged") for e in result["events"])
    assert result["success"] is False
    assert [c[0] for c in guest.calls if c[0] in ("stop", "get", "release")] == [
        "stop", "get", "get", "release"]


def test_measure_writes_nothing_to_the_save_disk(tmp_path, clock):
    guest = ScreenGuest(clock)
    result = _measure(tmp_path, guest)
    assert result["slot_b_sha256"] is None
    assert result["published_unchanged"] and result["working_unchanged"]


def test_measure_refuses_without_a_fresh_mute_proof(tmp_path, clock):
    guest = ScreenGuest(clock)
    stale = tmp_path / "stale.json"
    stale.write_text("{}")
    with pytest.raises(amigasecretsave.RouteError, match="audio mute"):
        amigasecretsave.run_recon(
            _prepared(tmp_path), guest=guest, holder="wish672-test",
            audio_proof=stale, measure=True)
    assert guest.calls == []


def test_measure_keeps_only_distinct_boot_frames(tmp_path, clock):
    guest = ScreenGuest(clock)
    _measure(tmp_path, guest)
    boot = [s for s, _ in guest.at if s.startswith("00-boot")]
    assert len(boot) == 13  # every 10 s across 120 s
    kept = sorted(p.name for p in (tmp_path / "recon1" / "shots").glob("00-boot-*.png")
                  if not p.name.endswith(".raw.png"))
    assert len(kept) == 1


def test_the_route_and_write_keys_are_arguments(tmp_path, clock):
    guest = ScreenGuest(clock)
    route = (("ESC", "party_menu"), ("L", "load_picker"))
    amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, guard=lambda s, p: True,
        holder="wish672-test", audio_proof=_audio_proof(tmp_path),
        route=route, write_keys=("Y",))
    assert _keys(guest) == ["ESC", "L", "Y"]


def test_parse_route():
    assert amigasecretsave.parse_route("esc:party_menu, L:load_picker") == (
        ("ESC", "party_menu"), ("L", "load_picker"))
    with pytest.raises(amigasecretsave.RouteError):
        amigasecretsave.parse_route("ESC")


def test_the_minimum_wait_is_spent_before_each_capture(tmp_path, clock):
    guest = ScreenGuest(clock)
    route = (("RET", "version"), ("P", "party_menu"))
    amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, guard=lambda s, p: True,
        holder="wish672-test", audio_proof=_audio_proof(tmp_path), route=route,
        min_waits={"version": 50, "party_menu": 15})
    pressed_at = {}
    for name, at in guest.at:
        pressed_at[name] = at
    assert pressed_at["01-version"] - pressed_at["title"] == 50
    assert pressed_at["02-party_menu"] - pressed_at["01-version"] == 15


def test_default_waits_follow_the_measured_timings():
    waits = amigasecretsave.default_min_waits()
    assert waits["version"] == 50 and waits["load_picker"] == 20
    assert waits["loaded_menu"] == 20 and waits["items"] == 15


def test_a_guard_that_matches_late_is_polled_for(tmp_path, clock):
    guest = ScreenGuest(clock)
    seen = {"n": 0}

    def guard(state, path):
        if state == "version":
            seen["n"] += 1
            return seen["n"] >= 4
        return True

    amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, guard=guard, holder="wish672-test",
        audio_proof=_audio_proof(tmp_path), route=(("RET", "version"),))
    assert seen["n"] == 4
    assert [c for c in guest.calls if c[0] == "capture"].count(("capture", "01-version")) == 4
    assert clock.sleeps.count(amigasecretsave.GUARD_POLL) == 3


def test_a_guard_that_never_matches_raises_after_its_limit(tmp_path, clock):
    guest = ScreenGuest(clock)
    result = amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest,
        guard=lambda s, p: s == "title", holder="wish672-test",
        audio_proof=_audio_proof(tmp_path), route=(("RET", "version"),),
        deadline_seconds=1800)
    assert "not recognized" in result["error"]
    assert "B" not in _keys(guest)
    assert sum(clock.sleeps) >= amigasecretsave.GUARD_LIMIT - amigasecretsave.GUARD_POLL


def test_the_title_is_polled_until_its_guard_matches(tmp_path, clock):
    guest = ScreenGuest(clock)
    seen = {"n": 0}

    def guard(state, path):
        if state == "title":
            seen["n"] += 1
            return seen["n"] >= 3
        return True

    amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, guard=guard, holder="wish672-test",
        audio_proof=_audio_proof(tmp_path), route=())
    assert seen["n"] == 3
    assert clock.sleeps.count(amigasecretsave.TITLE_POLL) == 2


def test_guarded_mode_without_a_guard_is_refused(tmp_path):
    with pytest.raises(amigasecretsave.RouteError, match="guard"):
        amigasecretsave.run_recon(
            _prepared(tmp_path), guest=FailedPostWriteGuest(),
            holder="wish672-test", audio_proof=_audio_proof(tmp_path))


class SlotBGuest(ScreenGuest):
    """A key other than B that makes the guest write slot B without an error."""

    def press(self, holder, key, timeout=None):
        super().press(holder, key, timeout)
        if key == "X":
            disk = AmigaDisk(self.remote[self.drives[1]])
            disk.write_file("/SAVE/savgamB.sav", b"engine wrote B")
            self.remote[self.drives[1]] = disk.to_bytes()


def _cleanup_ran(guest):
    return [c[0] for c in guest.calls if c[0] in ("stop", "get", "release")] == [
        "stop", "get", "get", "release"]


def test_measure_fails_when_slot_b_appears(tmp_path, clock):
    guest = SlotBGuest(clock)
    result = _measure(tmp_path, guest, route=(("RET", "version"), ("X", "items")))
    assert result["route_changed"] is True
    assert result["slot_b_sha256"] is not None
    assert result["success"] is False


def test_measure_never_presses_b_even_when_write_keys_replace_it(tmp_path, clock):
    for keys in (("W",), ("",)):
        (tmp_path / str(len(keys[0]))).mkdir()
        guest = ScreenGuest(clock)
        try:
            _measure(tmp_path / str(len(keys[0])), guest,
                     route=(("RET", "version"), ("B", "sheet")), write_keys=keys)
        except amigasecretsave.RouteError:
            pass  # an empty entry is refused before anything is pressed
        assert "B" not in _keys(guest)


def test_write_keys_reject_an_empty_entry():
    assert amigasecretsave.parse_write_keys("b, w") == ("B", "W")
    for text in ("", "B,", ",B"):
        with pytest.raises(amigasecretsave.RouteError, match="empty"):
            amigasecretsave.parse_write_keys(text)


def test_measure_with_an_empty_route_is_refused(tmp_path, clock):
    guest = ScreenGuest(clock)
    with pytest.raises(amigasecretsave.RouteError, match="route step"):
        _measure(tmp_path, guest, route=())
    assert guest.calls == []


def test_a_minimum_wait_that_does_not_fit_the_deadline_fails_instead_of_shrinking(
        tmp_path, clock):
    guest = ScreenGuest(clock)
    result = _measure(tmp_path, guest, deadline_seconds=400,
                      route=(("RET", "version"),), min_waits={"version": 100})
    assert "minimum wait" in result["error"]
    assert "unchanged" not in str(result["events"])
    assert result.get("route_changed") is None
    assert _cleanup_ran(guest)


def test_a_tight_deadline_still_cleans_up(tmp_path, clock):
    guest = ScreenGuest(clock)
    result = _measure(tmp_path, guest, deadline_seconds=100)
    assert "deadline" in result["error"]
    assert _cleanup_ran(guest)


def test_a_keyboard_interrupt_still_cleans_up(tmp_path, clock):
    class Interrupted(ScreenGuest):
        def press(self, holder, key, timeout=None):
            raise KeyboardInterrupt

    guest = Interrupted(clock)
    result = _measure(tmp_path, guest)
    assert "KeyboardInterrupt" in result["error"]
    assert _cleanup_ran(guest)


def test_parse_route_rejects_a_trailing_comma_and_an_empty_state():
    for text in ("ESC:party_menu,", "ESC:", ":party_menu", ""):
        with pytest.raises(amigasecretsave.RouteError):
            amigasecretsave.parse_route(text)
